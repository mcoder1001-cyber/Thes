# ideas/ — snapshot × DAG ideas, with the experiments and simulation behind them

Start with **[IDEAS.md](IDEAS.md)**: the verdict, five ideas ranked, what is measured vs
simulated vs only specified, and how the thesis reorganises around them.

| directory | what | run it |
|---|---|---|
| `exp-a-context-priming/` | **Real JVM experiments** (OpenJDK 21, Jackson workload, cgroup CPU quota). exp-a: does a snapshot primed on one DAG edge serve another? Does format-preserving-scrubbed priming match real-traffic priming? exp-b: prime on 4 vCPU, serve on 0.25 | `./fetch_deps.sh && python3 gen_inputs.py && sudo ./run_all.sh && python3 analyze.py` |
| `sim/` | **dagsim**: discrete-event simulator of snapshot policies on workflow DAGs (restore-on-demand, cold prewarm, restore-ahead, speculation, re-warm, per-edge variants), driven by the thesis's measured parameters and the Azure Functions 2021 trace | `python3 run_sim.py` (e0 = closed-form controls, must pass) |
| `criu-box/` | **Protocols x1–x4 for the S0 box** (need a kernel with `CONFIG_CHECKPOINT_RESTORE`): readiness-ladder tiers, parallel-restore contention (go/no-go for Idea 1), checkpoint-lost warm-up and re-warming, mis-priming with real restores | see `criu-box/README.md` |

Raw results are committed (`exp-a-context-priming/results/*/`, `sim/results/`). Generated
inputs (74 MB) and the Jackson jars are not; the scripts recreate them deterministically.

Standing rules followed (from `RESEARCH_PLAN.md` §9): every experiment has a control whose
answer is known in advance (A/A priming set; closed-form chain latencies), n = 10 per cell
with bootstrap CIs, negative results reported next to positive ones (per-edge snapshot
variants: not worth it; re-warming: small in simulation).
