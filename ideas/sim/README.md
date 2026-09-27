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
| `predict_gaps.py` | can the platform predict when a cold workflow will be called (to pre-restore its entry)? Azure 2021: 86% of cold arrivals fall in a histogram window, but the gaps are irregular (median CV 1.28) and the entry would be held ~56 min per cold call: **no** | printed |

```bash
python3 prep_azure.py <AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt> 3   # -> data/
python3 run_sim.py            # all; e4 takes ~45 min (single core), e7b ~6 min on 3 cores
python3 plot_e4.py
```

**Policies** (`dagsim.POLICIES`): `cold`, `keepalive`, `snap` (restore on demand), `prewarm`
(DAG-aware cold prewarm), `ahead` (look-ahead restore), `+rw` (re-warm while waiting),
`/gated` (only when the workflow is cold, Lemma 5), `/jit` (trigger at `S*_v − r_v`, Theorem 2
of `theory/DAG_SNAPSHOT_THEORY.md`), `/guard` or `|guard` (a demand start that does not fit
preempts unclaimed look-ahead sandboxes, Theorem 8; options `noevict`, where look-ahead may not
evict other workflows' idle sandboxes, and `h=<fraction>`, a headroom look-ahead may not use). `theory/verify_dag.py` checks that the JIT policy reproduces
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
