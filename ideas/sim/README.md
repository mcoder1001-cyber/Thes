# dagsim — snapshot policies on serverless workflow DAGs

`dagsim.py` is a discrete-event simulator; `run_sim.py` holds the experiments. Results are in
`results/`; interpretation is in `../IDEAS.md` §1.

| exp | question | output |
|---|---|---|
| **e0** | **controls**: simulated latency must equal the closed forms. Chains d = 1…8 (cold, restore-on-demand, restore-ahead) and a fan-out/fan-in DAG, where restore-ahead is a longest path with release times | `e0_controls.csv` — 26/26 |
| e1 | depth 1–8 Java chain, every stage missing keep-alive | `e1_cascade.csv/.png` |
| e2 | speculation threshold θ on a saga and a router DAG, restore-ahead vs cold prewarm | `e2_speculation.csv/.png` |
| e3 | per-edge snapshot variants vs one snapshot, as a function of the mis-priming penalty | `e3_context.csv` |
| e4 / e4b | Azure 2021 trace (first 3 days, 68 workflows, 432,945 invocations), memory budgets 32 / 128 / 1024 GB | `e4_trace.csv`, `e4b_trace_gated.csv`, `e4_trace_bars.png` (plot_e4.py) |
| e5 | sensitivity to restore time `r` and restore contention `β` | `e5_sensitivity.csv` |
| e6 | which stages are worth a snapshot, in latency **and money** (exact model, `e6_cost.py`): per-function break-even, per-workflow choices, the trace's cold invocations per day | `e6a_cost_functions.csv`, `e6b_cost_workflows.csv`, `e6c_cost_trace.csv` |
| e7a / e7b | **memory overload**: a burst of cold workflows under a hard budget; the Azure trace at 16/24/32 GB; with and without the memory guard (Theorem 8) | `e7a_burst.csv`, `e7b_trace_budget.csv` |
| e8 | **keep-alive under look-ahead** (Proposition 9): per-function LRU and GDSF eviction vs whole-workflow eviction, and the all-stages gate; Azure trace at 16/24/32/48 GB | `e8_keepalive.csv` |
| e10 | **the headline numbers with the final policy** (`recommended` in `dagsim.py`: gated just-in-time look-ahead + re-warm + guard + planner + GDSF keep-alive): e10a isolated chains (as e1), e10b the Azure trace at 24/32/128 GB (as e4/e4b), against restore-on-demand with LRU and with GDSF keep-alive | `e10a_chains_final.csv`, `e10b_trace_final.csv` |
| e9 | **the exact planner** (`theory/ALGORITHM.md` Algorithms 2–3, `planner.py`) vs the guard alone and vs the guard with a wait queue: e9a single workflows under a budget, e9b a burst of 16 mixed workflows, e9c the Azure trace | `e9a_planner_single.csv`, `e9b_planner_burst.csv`, `e9c_planner_trace.csv` |
| e11 | **CPU during start-up** (the vCPU cliff; `../CPU_PLAN.md`). `dagsim` gets a CPU layer: `Sim(cpu_cores=K, cpu_quota=q)` makes every start-up and request CPU work at its quota, and `Policy.boost` shares the spare CPU among start-ups: `uniform` (Cloud Run's startup boost), `cp` (critical path first), `slack`, `plan` (the CPU plan's online rule). `lazy` makes it just in time: a start-up holds no memory and no CPU before its latest start (`cpuplan.latest_starts`). `nosnap` picks stages without a snapshot. Experiments: e11o the online rule vs the exact plan (`cpuplan.py`, max-flow), e11a isolated workflows at 0.25/0.5 vCPU on 1/2/4 cores, e11b a burst of 16 workflows (without keep-alive, so memory counts start-ups and runs), e11d which stages still need a snapshot, e11c the Azure trace, e11x the controls for `lazy`. With the layer off, or with q = 1 and unlimited cores, results are identical to before (checked on 980 isolated runs and a day of the trace) | `e11o_cpu_plan.csv`, `e11a_cpu_isolated.csv`, `e11b_cpu_burst.csv`, `e11d_cpu_selection.csv`, `e11c_cpu_trace.csv`, `e11x_jit_controls.csv` |
| `predict_gaps.py` | can the platform predict when a cold workflow will be called (to pre-restore its entry)? Azure 2021: 86% of cold arrivals fall in a histogram window, but the gaps are irregular (median CV 1.28) and the entry would be held ~56 min per cold call: **no** | printed |

```bash
python3 prep_azure.py <AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt> 3   # -> data/
python3 run_sim.py            # all; e4 takes ~45 min (single core), e7b ~6 min on 3 cores, e8 ~10 min on 4 cores (SIM_PROCS sets the pool size), e9 ~25 min
python3 plot_e4.py

# with measured parameters from the test machine (MACHINE_TEST_PLAN.md), into a separate folder:
DAGSIM_PROFILE=../../results/box/profile_vcpu1.0.json DAGSIM_OUT=../../results/box/sim python3 run_sim.py e10a e9a
```
`DAGSIM_PROFILE` replaces the `JAVA`, `PY` and `PYML` profiles and the edge delay with the values in a JSON file
(format: `../criu-box/profile_thesis.json`, which holds the defaults and reproduces the committed results).

**Policies** (`dagsim.POLICIES`): `cold`, `keepalive`, `snap` (restore on demand), `prewarm`
(DAG-aware cold prewarm), `ahead` (look-ahead restore), `+rw` (re-warm while waiting),
`/gated` (only when the workflow is cold, Lemma 5), `/jit` (trigger at `S*_v − r_v`, Theorem 2
of `theory/DAG_SNAPSHOT_THEORY.md`), `/guard` or `|guard` (a demand start that does not fit
preempts unclaimed look-ahead sandboxes, Theorem 8; options `noevict`, where look-ahead may not
evict other workflows' idle sandboxes, and `h=<fraction>`, a headroom look-ahead may not use), `|keep=gdsf` or `|keep=wf` (evict idle
sandboxes by per-function GreedyDual-Size-Frequency, or whole workflows at a time, Proposition 9)
and `|gateall` (skip planning only when every stage has a live sandbox).
`|plan` runs the exact planner at each cold arrival when the just-in-time schedule would not
fit in the memory the workflow can get (likely path only; restores that do not fit wait in a
queue; re-planning when memory frees; no planning while the platform is over budget or was
in the last minute, nor when the plan would not beat restoring on demand); `|queue` is the same machinery with just-in-time
triggers, to separate the value of the exact order from the queueing. `theory/verify_dag.py` checks that the JIT policy reproduces
the theorem's optimal latency and minimum memory exactly.

**Parameters** are the thesis's own measurements (`dagsim.py`: `JAVA`, `PY`, `PYML`, each
with its source in a comment). The Python restore time and the ML-stage profile are
assumptions, marked as such.

**Bugs caught by the controls** (as in `theory/verify.py`, they are recorded):
1. Fan-out siblings sharing a function could take each other's ahead-of-time reservation,
   leaving the last ones to restore on demand. The fan-out closed form caught it (916 vs
   829 ms). Fixed with an explicit claim flag; chain/saga/router results were byte-identical
   before and after.
2. Random draws were seeded with Python's `hash()` of a tuple containing a string, which is
   salted per process: comparisons within a run were fair but runs were not reproducible.
   Now `zlib.crc32`.

**Simplifications** (also in the module docstring): warm-up lumped into a sandbox's first
request; one request per sandbox at a time; the memory budget limits what is kept idle or
started ahead, while demand starts always proceed (counted as `overflow`); constant 2 ms per
DAG edge; the Azure trace has no DAGs, so each app gets a template deterministically
(`app index mod 8`).
