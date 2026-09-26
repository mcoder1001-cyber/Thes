# ideas/ — snapshot × DAG ideas, with the experiments and simulation behind them

New here? Read **[../REPORT.md](../REPORT.md)** first: the problem, conditions, approach step by
step and what has been done, in plain English.

Start with **[../theory/DAG_SNAPSHOT_THEORY.md](../theory/DAG_SNAPSHOT_THEORY.md)**: the
approach, the policy and the proofs (checked by `theory/verify_dag.py`, 62/62). Then
**[IDEAS.md](IDEAS.md)**: the evidence, including the ideas tried and dropped. The approach reads
no user data; warming snapshots on scrubbed copies of the workflow's messages was dropped.

| directory | what | run it |
|---|---|---|
| `exp-a-context-priming/` | **Real JVM warm-up experiments** (OpenJDK 21, Jackson workload, cgroup CPU quota). exp-a: how much warm-up a snapshot keeps, and on which kind of requests (its scrubbed-input part belongs to the dropped priming idea); exp-b: warm up on 4 vCPU, serve on 0.25 | `./fetch_deps.sh && python3 gen_inputs.py && sudo ./run_all.sh && python3 analyze.py` |
| `sim/` | **dagsim**: discrete-event simulator of snapshot policies on workflow DAGs (restore-on-demand, cold prewarm, restore-ahead, speculation, re-warm, memory guard), driven by the thesis's measured parameters and the Azure Functions 2021 trace; plus `e6_cost.py` (which stages are worth a snapshot) and `predict_gaps.py` (can arrivals be predicted? no) | `python3 run_sim.py` (e0 = closed-form controls, must pass) |
| `criu-box/` | **Protocols for the S0 box** (need a kernel with `CONFIG_CHECKPOINT_RESTORE`): x1 readiness-ladder tiers, **x2 parallel-restore contention (the go/no-go, `run_x2.sh`)**, x3 checkpoint-lost warm-up and re-warming; x4 belongs to the dropped priming idea | see `criu-box/README.md` |

Raw results are committed (`exp-a-context-priming/results/*/`, `sim/results/`). Generated
inputs (74 MB) and the Jackson jars are not; the scripts recreate them deterministically.

Standing rules followed (from `RESEARCH_PLAN.md` §9): every experiment has a control whose
answer is known in advance (A/A priming set; closed-form chain and fan-out latencies), n = 20 per cell
with bootstrap CIs, negative results reported next to positive ones (per-edge snapshot
variants: not worth it; re-warming: small in simulation).
