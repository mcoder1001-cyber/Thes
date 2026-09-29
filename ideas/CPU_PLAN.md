# The CPU plan: CPU for start-ups, planned along the workflow

*Written 2026-09-28, after the supervisor's review of `PROFESSOR_REPORT.md`. Supervisor-facing
summary: `PROFESSOR_REPORT_2.md`. Theory, with proofs: `../theory/CPU_PLAN_THEORY.md` (and §4.9
of `../thesis/ch_theory.tex`). Code: `sim/dagsim.py` (the CPU layer), `sim/cpuplan.py` (the
exact plan). Experiments: `sim/run_sim.py` e11o, e11a, e11b, e11d, e11c. Everything here is
simulated; `MACHINE_TEST_PLAN.md` T6b measures the one assumption it rests on.*

---

## 1. Why

The review made three points:
- report 1 restored every stage;
- "restore earlier" is Xanadu's timing idea applied to snapshots;
- no baseline was improved.

The thesis's most original measurement is the **vCPU cliff**:
- JVM warm-up is 13–35× slower at 0.25 vCPU than at 4 vCPU (exp14);
- the same warm-up takes 3.59 s at 0.25 vCPU and 0.86 s at 1 vCPU, for 0.90 vs 0.86 CPU-seconds
  (exp-b);
- Spring Boot cold starts take 2.3–26.8 s and restores 0.64–9.1 s, depending on the quota
  (exp12).

**Start-up is CPU work, and small quotas starve it.** Lending spare CPU to a sandbox while it
starts does the same work sooner. When a workflow starts cold, several sandboxes start at once and
compete for that CPU. The workflow graph tells which start-ups are urgent.

Industry does a crude version of this. Cloud Run's startup CPU boost gives every starting
instance the same extra CPU. ORION and Aquatope choose one CPU size per stage for its whole run.
Nothing plans start-up CPU per start-up, over time, from a workflow's deadlines.

## 2. Model

- **Start-up:** a restore plus the first request's residual warm-up, or a cold boot plus the full
  warm-up. It is CPU work `U` (profile ms at 1 vCPU).
- **Rate:** a start-up runs at the rate it is given, at most `cpu_cap` cores (1: a JVM pinned to one
  CPU). The speed-up is linear up to the cap, as exp-b measured from 0.25 to 1 vCPU.
- **Requests** run at the sandbox's quota `q`.
- **Server:** `K` cores. When the quotas exceed `K`, everyone is scaled down in proportion.

## 3. The algorithm

**Deadlines** (Theorem 1 of `theory/DAG_SNAPSHOT_THEORY.md`). Under look-ahead, the workflow
finishes by `L` if and only if every stage `v` is ready by `D_v = L − T(v)`, where `T(v)` is the
work from `v`'s start to the end. So every start-up has its own deadline
(`dagsim.Sim._cpu_deadlines`, with `L` = the workflow's ideal latency).

**The exact plan** (`cpuplan.py`; Theorem CP2 in `../theory/CPU_PLAN_THEORY.md`):
1. Checking that every start-up can meet its deadline is a max-flow problem (Horn 1974):
   - source → job, capacity `U`;
   - job → its own quota (private);
   - job → each time slice of its window, capacity `(c − q)·|slice|`;
   - slice → sink, capacity `P·|slice|`.
2. Binary search on `L` gives the optimum, and the flow gives every start-up's rate per slice.
3. It is a case of project scheduling with flexible resource profiles: activities that run faster
   with more resource. Report 1's timing results are its fixed-CPU special case.

**The online rule** (`Policy.boost = "plan"`), recomputed at every event:
- **Rates:** requests run at their quota. Start-ups are guaranteed nothing: the platform sets each
  starting sandbox's CPU limit, so a start-up that is not urgent cannot hold CPU the critical one
  needs.
- **One workflow starting:** "slack" rates. Constant rates are chosen that minimise the largest
  lateness of its start-ups, never below what all-at-cap reaches, and the leftover is shared
  equally. This is within 0–9% of the exact plan (e11o).
- **Several workflows starting:** earliest deadline first across all start-ups (e11b).
- **Speculation:** start-ups for stages that may not run (an if/else not yet decided) get only the
  CPU the certain ones leave. With at most one spare core, only stages certain to run count as
  certain: without parallelism, early start-ups cannot beat sequential ones, and speculation only
  takes CPU.

Ablations kept in the code:
- `uniform`: equal shares (Cloud Run, idealised: all spare CPU);
- `cp`: earliest deadline first always;
- `slack`: the balanced rule always.

**Snapshot selection** (`Policy.nosnap`): stages without a snapshot cold-start, ahead or on
demand, under the same CPU policy.

**Controls:**
- With the CPU layer off, or with `q = 1` and unlimited cores, `dagsim` reproduces its earlier
  results exactly: 980 isolated runs to 1e-12 ms, a day of the trace, e10a byte for byte, e0 26/26.
- `theory/verify_dag.py` passes 93/93, including section CP, which checks the theory (CP1–CP7).
- `cpuplan.controls()`: a lone start-up runs at `min(c, q + P)`.

## 4. Results (functions at 0.25 vCPU unless stated)

**e11o: online rule vs exact plan** (fluid model, slowest workflow). The online rule is within
0–9% of the exact plan on one workflow. An equal split is up to 1.39× slower, and critical path
first up to 1.16× slower.

**e11a: one cold workflow** (mean latency in seconds; `od` = restore on demand, `la` = look-ahead):

| cores | workflow | od (SnapStart-style) | od + equal boost (Cloud Run) | la (report 1) | la + equal boost | **la + CPU plan** |
|---|---|---|---|---|---|---|
| 2 | chain of 3 | 8.64 | 2.16 | 3.63 | 1.20 | **1.14** |
| 2 | chain of 8 | 23.47 | 5.88 | 5.20 | 3.20 | **3.05** |
| 2 | fan-out 4 | 7.04 | 2.43 | 3.75 | 2.01 | **1.97** |
| 2 | router (if/else) | 12.28 | 3.08 | 4.61 | 2.79 | **2.06** |
| 2 | trip (saga) | 12.41 | 3.11 | 4.28 | 2.63 | **1.64** |
| 4 | chain of 8 | 23.47 | 5.88 | 5.20 | 1.89 | **1.70** |
| 4 | trip (saga) | 12.41 | 3.11 | 4.28 | 1.48 | **1.07** |

Over the eight workflow shapes:
- **vs Cloud Run-style:** 19–48% faster on 2 cores, 41–71% on 4 cores, equal on 1 core.
- **vs look-ahead with an equal boost:** 0–37% faster.
- **vs SnapStart-style:** 3.6–14× faster.
- **At 0.5 vCPU:** the same picture (`e11a_cpu_isolated.csv`).
- **Memory:** starting restores at arrival makes sandboxes wait. The plan holds 1.3–3.8× the
  memory·time of on-demand restore per cold invocation, less than report 1's look-ahead at 0.25 vCPU.

**e11b: a burst** of 16 cold workflows within 1 s (mean / p99, s):

| cores | SnapStart-style | Cloud Run-style | la (report 1) | la + equal | la + "slack" everywhere | **la + CPU plan** |
|---|---|---|---|---|---|---|
| 2 | 21.2 / 34.7 | 19.9 / 26.0 | 28.9 / 31.2 | 28.7 / 30.4 | 24.5 / 26.8 | **16.7 / 25.5** |
| 4 | 12.8 / 25.8 | 9.9 / 14.1 | 14.5 / 16.3 | 14.1 / 15.2 | 12.0 / 13.5 | **8.1 / 12.6** |
| 8 | 11.6 / 24.6 | 5.1 / 8.4 | 7.5 / 9.1 | 6.9 / 7.6 | 5.8 / 6.9 | **3.9 / 6.4** |

- Report 1's look-ahead is slower than on demand in a burst, because all restores compete for CPU.
- The fair "slack" rule, applied across workflows, makes everyone late. It was the first version
  of the rule, and e11b is why the plan now switches to earliest deadline first when several
  workflows start.

**e11d: which stages need a snapshot** (2 cores; the fewest snapshots within 5% of snapshotting all):
- under the CPU plan, every stage of every workflow tested: a cold start is about 4× the CPU work
  of a restore, and with short stages (about 50 ms) there is no slack to hide it;
- without the plan, fewer: fan-out 2 of 4, ML 4 of 5, trip 7 of 8;
- the fluid model drops the last two stages of a chain only when stages last about a second.

**No snapshots at all:** cold prewarm with the CPU plan beats SnapStart-style restores for 7 of 8
shapes on 2 cores and 8 of 8 on 4.

**e11c: the Azure 2021 trace** (3 days, 32 GB, GDSF keep-alive):
- **Server size:** at 0.25 vCPU the trace's CPU demand is bursty. With unlimited cores it averages
  0.6 cores in use, with a 99th percentile of 3–7.5, a 99.9th of 34 and a peak of 84. A server of
  1–8 cores collapses into queues of 1,000–2,200 jobs at the peaks, so the experiment uses 32 and
  64 cores.

On 32–64 cores (mean / p99, seconds; cold workflows = calls to a workflow idle for more than 10
minutes, n = 794 of 432,945):

| cores | | SnapStart-style | Cloud Run-style | la (report 1) | la + equal | **la + CPU plan** |
|---|---|---|---|---|---|---|
| 64 | cold workflows | 9.36 / 24.77 | 2.35 / 6.20 | 3.41 / 6.28 | 0.84 / 1.53 | **0.84 / 1.53** |
| 64 | all calls | 1.49 / 14.33 | 0.87 / 3.52 | 1.31 / 9.24 | 0.80 / 2.27 | **0.80 / 2.27** |
| 32 | cold workflows | 9.37 / 24.77 | 2.35 / 6.20 | 3.43 / 6.28 | 0.87 / 1.53 | **0.85 / 1.62** |
| 32 | all calls | 1.75 / 22.88 | 0.87 / 3.61 | 1.58 / 17.47 | 0.82 / 2.31 | **0.81 / 2.33** |
| 64 | CPU-hours, starts / 1000 calls | 44.7, 309 | 37.2, 211 | 53.5, 452 | 42.5, 289 | **42.5, 289** |

- **Look-ahead with a startup boost against the Cloud Run-style boost:** cold workflows are 2.8×
  faster on average and 4× at p99; all calls' p99 is 36% lower. The cost is 14% more CPU-hours:
  37% more sandbox starts, from starting restores ahead.
- **On this trace the allocation rule does not matter.** With 32–64 cores, spare CPU is almost
  always available, so equal split, critical path first, "slack" and the CPU plan give the same
  result at 64 cores and are within 3% at 32. The CPU plan's gains need contention: small servers
  (e11a) and bursts (e11b).
- **Report 1's look-ahead without a boost is poor at 0.25 vCPU** (3.4 s for cold workflows, and a
  9–17 s p99 over all calls). Its parallel restores starve each other and the running requests of
  CPU.

## 5. Open questions

1. **The speed-up curve of restores and cold starts** (T6b on the machine). exp-b measured only
   warm-up.
2. **The burst rule.** Earliest deadline first wins in mixed bursts (e11b). In the fluid model's
   bursts of identical chains, "slack" wins.
3. **Memory:** trigger restores just in time under the plan, rather than all at arrival.
4. **Snapshot selection:** it saves snapshots only for long-stage workflows. Measure real stage
   lengths (SeBS-Flow).

Run: `python3 ideas/sim/run_sim.py e11o e11a e11b e11d e11c` (e11c: about 30 minutes on 4 cores).
