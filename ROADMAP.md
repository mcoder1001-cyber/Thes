# Roadmap: tools, math, and the stages from here

*Written 2026-09-26. Companion to `REPORT.md` (what the approach is). This file says what you
need to build it, what math you need to prove and defend it, and in which order to do the work.*

---

## 0. Where we are

- **Done:** the approach (`REPORT.md`), 7 theorems with proofs checked by computer
  (`theory/DAG_SNAPSHOT_THEORY.md`, 44/44), real JVM priming experiments (1,600 runs), a
  workflow simulator on the Azure trace.
- **Not done:** nothing has been measured with **real** snapshot restores for this approach, and
  nothing is built inside OpenWhisk yet.
- **The one open question that can change the plan:** do parallel restores slow each other
  down (the number **β**)? Test `x2` answers it. That is the next goal (§3).

---

## 1. Tools

### 1.1 What you already have (on the S0 box, per `RESEARCH_PLAN.md` §5b)

| tool | state |
|---|---|
| x86_64 Linux box: 8 × Xeon Gold 6248R, 31 GB RAM, Ubuntu 24.04, no CPU steal | ✅ ready |
| CRIU 4.2.1 (built from source), smoketest 6/6 including a JIT-warmed JVM | ✅ ready |
| Azul Zulu **CRaC JDK 21** | ✅ installed |
| **OpenWhisk** built from `master`, Java actions work on stock OpenWhisk | ✅ ready |
| cgroup CPU quotas for 0.25 / 1 / 4 vCPU | ✅ used in every experiment so far |

### 1.2 What to install or check

| tool | why you need it | action |
|---|---|---|
| **podman** | `x2` restores one CRIU image into many containers at once; Docker cannot | install on the box (`apt install podman`) |
| Docker capabilities for CRaC | a CRaC restore *inside* a container needs extra Linux capabilities (Azul's CRaC docs list them; recent kernels need `CHECKPOINT_RESTORE` and `SYS_PTRACE`) | first test with `--privileged`, then narrow down |
| OpenWhisk invoker settings | (1) the invoker memory budget was **1024 MB**: an 8-stage workflow at 512 MB/stage needs 4 GB. (2) the container run arguments must carry the capabilities above | raise the budget, add the capabilities in the invoker's container-args config (check the exact key in your build) |
| a local Docker registry | OpenWhisk "blackbox" (custom image) actions may pull the image on a cold start; a local registry keeps pull time out of your numbers | `docker run -d -p 5000:5000 registry:2` |
| **JaCoCo** | branch-coverage counts to certify scrubbed priming (step A5) | a jar, no install |
| **JDK 25** | baseline: JEP 515 ahead-of-time method profiles, the non-snapshot competitor | second JDK next to the CRaC one |
| Python: numpy, scipy, pandas, matplotlib | analysis, plots, simulator (already used) | `pip install` |
| **Hypothesis** (optional) | property-based tests: turns `verify_dag.py`'s random checks into shrinking counterexamples | `pip install hypothesis` |
| LaTeX (XePersian) | writing the thesis; use your department's template | later |

### 1.3 What you must write (our own code)

| component | job | start from |
|---|---|---|
| **Snapshot action image** | a Docker image that starts with `java -XX:CRaCRestoreFrom=<dir>` instead of a fresh JVM, and answers OpenWhisk's `/init` and `/run` on port 8080 | `ideas/criu-box/FnServer.java` already serves HTTP; change it to OpenWhisk's `/init`, `/run` contract. Deploy as a blackbox action (`wsk action create --docker`) |
| **Workflow orchestrator + planner** | runs the DAG by calling OpenWhisk actions over its REST API, and does the look-ahead (steps B1–B5) | new, Python. **Recommended over changing OpenWhisk's controller** (Scala): OpenWhisk sequences are linear only, while you need fan-out and if/else, and your own orchestrator is where "the orchestrator knows the DAG" lives |
| **Wake call** | to "restore ahead", the planner sends a no-op activation (`{"__wake": true}`) to a downstream action at time τ. The invoker restores a container, the runtime returns at once, and the warm container is reused when the real input arrives | about 10 lines in the action image |
| **Priming pipeline** | steps A2–A7: capture edge samples, scrub, certify, warm up, checkpoint | `ideas/exp-a-context-priming/gen_inputs.py` (`learn_categorical`, `scrub`), `src/Sig.java` |
| **Depth planner** | step A6: picks depth per stage | `dp_joint` in `theory/verify_dag.py` |
| **Trace replayer** | sends workflow requests at the times of the Azure 2021 trace | `ideas/sim/prep_azure.py` already parses the trace |
| **Measurement collector** | per-stage times and memory | OpenWhisk activation records (`start`, `end`, `waitTime` and `initTime` annotations; `initTime` appears on cold starts) + cgroup `memory.current` sampling |

### 1.4 Pitfalls already known

- **Two failures that look the same** in the `wsk` CLI ("did not initialize"): the invoker
  memory budget running out, and a real runtime bug. Only the invoker log tells them apart
  (`RESEARCH_PLAN.md` S0).
- Raw `criu restore` reuses the saved process IDs, so one image cannot be restored twice in the
  same PID namespace. Each container has its own PID namespace, so this is fine inside
  containers.
- Checkpoint and restore on the same CPU model (you do, on one box).
- The warm-up machine must look like the small container to the JVM
  (`-XX:ActiveProcessorCount=1`, a fixed GC), or the snapshot is 11–17% worse (exp-b).

---

## 2. The math you need

### 2.1 One thing to understand first

**The mathematics is standard; the new part is the model.** Longest paths, dynamic
programming, the newsvendor rule and renewal arguments are all textbook tools. What is ours is
showing that snapshot restores in a workflow fit these tools, and what follows from that.
At the defense, say this plainly and **cite the classical results** (critical path method,
newsvendor, knapsack) instead of presenting them as new. It makes the thesis stronger, not
weaker.

### 2.2 Which math each result uses

| result | in one line | math it uses | where to learn it |
|---|---|---|---|
| **Theorem 1** | the lowest possible latency is `max_v (r_v + longest path from v)`; restoring ahead reaches it | DAGs, topological order, **longest path in a DAG**, proof by induction, lower-bound argument | CLRS (*Introduction to Algorithms*): topological sort, shortest paths in DAGs; the critical path method in Pinedo, *Scheduling* |
| Corollary 1.1 | on a chain, d restores become one | algebra, sign of a derivative, a limit | school calculus |
| Corollary 1.2 | contention β shrinks the gain but never makes it negative | inequalities | none extra |
| Corollary 1.3 | random restore times: you pay the max, not the sum | **expected value of a maximum** (order statistics) | Ross, *Introduction to Probability Models* |
| **Theorem 2** | just-in-time restore gives both lowest latency and lowest memory | same as Theorem 1, plus Pareto optimality | none extra |
| **Theorem 3** | under uncertainty, be ready at the κ-quantile of the input time | CDF, quantile, expectation of `(x−I)⁺`, **convex function, minimise by derivative = 0**: the **newsvendor** problem | any operations-research text, chapter on inventory / newsvendor |
| Theorem 4 | restore a branch early iff p ≥ κ | compare two expected costs | none extra |
| Lemma 5 | if the entry is warm, all stages are warm | ancestors and descendants in a DAG | none extra |
| Theorem 6 | keep-alive needs unboundedly more memory on rare workflows | **Poisson process**, exponential distribution, **renewal argument** | Ross: Poisson process and renewal theory chapters |
| **Theorem 7** | two numbers (W, P) describe any sub-workflow; an exact DP picks depth and timing together | functions of the form `max(x+W, P)` (**max-plus algebra**), **induction on the series-parallel decomposition tree**, **dynamic programming**, Pareto sets, **NP-hardness by reduction** (multiple-choice knapsack) | Kleinberg & Tardos, *Algorithm Design* (DP chapter, NP chapter); Kellerer, Pferschy & Pisinger, *Knapsack Problems* (multiple-choice knapsack); Valdes, Tarjan & Lawler (1982) for series-parallel graphs; first chapter of Heidergott, Olsder & van der Woude, *Max Plus at Work* (optional) |
| Corollaries 7.1, 7.2 | some cold starts are hidden by the DAG; give snapshots to the longest tail first | monotonicity, **exchange argument** | Kleinberg & Tardos, greedy chapter (exchange arguments) |
| Proposition 7 | same code paths ⇒ same JIT profile | control-flow graphs, counting argument, determinism | how HotSpot's tiered compilation counts invocations and branches (OpenJDK docs) |
| Proposition 8 | depth is work, not number of requests | additive counters, thresholds | same |
| `MODEL.md` | depth on chains (the on-demand special case) | multiple-choice knapsack, convexity, greedy, **isotonic regression (PAVA)** | Kellerer et al.; any isotonic-regression reference |

### 2.3 For the experiments

| topic | why | where to learn it |
|---|---|---|
| experimental design: controls, randomised run order, one factor at a time | every result needs a control whose answer is known | Jain, *The Art of Computer Systems Performance Analysis* (the classic for systems theses) |
| **bootstrap confidence intervals**, ratios | all comparisons in `exp-a` use them | Efron & Tibshirani, *An Introduction to the Bootstrap* |
| percentiles and tails | a p99 from 20 runs is not reliable; p99 claims need hundreds of samples (use the trace replay for them) | Jain |
| discrete-event simulation | `dagsim` | Law, *Simulation Modeling and Analysis* |

### 2.4 Learning order (if you start from a normal CS background)

1. **Proof techniques** (induction, contradiction, counterexample, exchange argument). About 1 week if rusty. Velleman, *How to Prove It*.
2. **DAGs and longest paths** (topological order, critical path). A few days. This alone covers Theorems 1, 2 and Lemma 5.
3. **Dynamic programming and NP-hardness**, knapsack. 1–2 weeks. Covers Theorem 7 and `MODEL.md`.
4. **Probability**: CDF and quantile, expectation, order statistics, Poisson process, renewal. About 2 weeks. Covers Theorems 3, 6 and Corollary 1.3.
5. **Statistics for experiments**: bootstrap, design. About 1 week.
6. Max-plus algebra, only the first chapter, if you want the elegant view of Theorem 7(a).

### 2.5 What you should be able to do at the defense without notes

- Prove **Theorem 1** on a board: the lower bound (follow one path, add up) and that eager
  restore reaches it (induction in topological order).
- Prove **Theorem 2(a)**: every stage holds memory at least `r + w`.
- Derive **Theorem 3**: write the expected cost, differentiate, set to zero, get `F(x) = κ`.
- Explain **Theorem 7(a)** with the counterexample in §3.5 of the theory file (1000 vs
  1400 ms): why choosing the fastest option per stage is wrong.
- Say what each assumption A1–A4 means and what happens when it fails (A2 → Corollary 1.2;
  A1 → prediction could only help).
- Say which results are classical and which are yours (§2.1).

---

## 3. The next goal

> **Measure β on the box.** Run `x2-parallel` (`sudo ./ideas/criu-box/run_x2.sh`) (1, 2, 4, 8 restores at once, 20 repetitions,
> 1 vCPU) and `x1-ladder`. One to three days.

**Why this first:** Innovation 1 (restore ahead) assumes parallel restores do not slow each
other much. Corollary 1.2 says the gain is at least `(1 − β)` of the ideal. If β is close to 1,
restores run one after another anyway and Innovation 1 gives little. Everything later depends
on this number, and it is cheap to get.

**Write the prediction down before running** (standing rule 7): each restore runs in its own
container with its own 1-vCPU quota, the box has 8 cores, and a light-handler image was 27–32 MB (exp11), so up to
about 7 parallel restores should not compete for CPU or disk. **Prediction: β small (< 0.3)
for N ≤ 4, rising at N = 8** (8 quotas + host work > 8 cores).

**Add one variant:** `x2` as written uses podman and raw CRIU. OpenWhisk will use CRaC inside
Docker. Run N parallel `docker run … java -XX:CRaCRestoreFrom=…` too, so β is measured on
the path you will deploy.

**Decision after x2:**

| β | meaning | what to do |
|---|---|---|
| **< 0.3** | restores run in parallel | continue as planned |
| **0.3 – 0.7** | partial slow-down | continue, but limit how many restores start at once and report gains scaled by `(1 − β)` |
| **≥ 0.7** | restores are serialised (the kill criterion in `ideas/criu-box/README.md`) | find the cause first (CPU, disk, or a lock in CRIU). If it cannot be fixed, Innovation 1 becomes weak on this hardware. The thesis then rests on Innovation 2 (safe priming) + Theorem 7 (depth choice) + the measurement study, and the fallback for timing is the "pre-restored and stopped" tier from `x1` |

---

## 4. The stages

Each stage has a **goal**, **input**, **output**, and an **exit test** (you do not start the
next stage until it passes). Times are rough estimates for one person, full time.

### Stage 1 — Go/no-go on the box *(1 week)*
- **Goal:** know whether Innovation 1 works on real hardware.
- **Input:** the S0 box, `ideas/criu-box/`.
- **Work:** `x2` (plus the CRaC-in-Docker variant), `x1`.
- **Output:** β; restore time `r` for each tier (disk, page cache, pre-restored); memory held.
- **Exit:** β known with a confidence interval; decision from the table in §3.
- **In parallel:** read Pronghorn's full paper; take `REPORT.md` to your supervisor and agree on the approach.

### Stage 2 — Real snapshots of one function *(3 weeks)*
- **Goal:** replace every emulated number with a measured one.
- **Input:** Spring Boot workload and `Fn.java`, CRaC JDK.
- **Work:**
  - snapshot at depth K = 0, 1, 5, 20, 50, 100, 200 and measure `r(K)`, leftover warm-up `R(K)`, image size `s(K)` (RESEARCH_PLAN S1, S2);
  - `x3`: warm-up lost at checkpoint `L(K)`;
  - `x4`: priming comparison with real restores;
  - check what private state the image carries and reset it in `beforeCheckpoint` (S3).
- **Output:** the real profile table (step A1), updated `dagsim` parameters.
- **Exit:** `x4`: scrubbed priming within 1.2× of real-traffic priming (the kill criterion in `criu-box/README.md`).

### Stage 3 — One snapshot action inside OpenWhisk *(2–3 weeks)*
- **Goal:** OpenWhisk starts an action by restoring a CRaC snapshot.
- **Input:** the Stage 2 image; OpenWhisk on the box.
- **Work:** the snapshot action image (§1.3), invoker capabilities and memory budget, local registry.
- **Output:** a blackbox action whose cold start is a restore; the wake call works.
- **Exit:** 20/20 cold starts succeed, and OpenWhisk cold start ≈ standalone restore time + a measured, constant OpenWhisk overhead.

### Stage 4 — Look-ahead on chains: the first headline result *(3 weeks)*
- **Goal:** measure Innovation 1 on a real system.
- **Input:** Stage 3; the profiles from Stage 2.
- **Work:** the orchestrator with steps B1–B3 and B5 (gate, compute start times, trigger restores at `τ = S* − r`, wake calls), for chains of 3, 5 and 8 stages at 1 and 0.25 vCPU; policies: on-demand, eager, just-in-time.
- **Output:** latency and memory-time per policy, n = 20.
- **Exit (the control):** on-demand latency ≈ `Σ (r + w)` (Theorem 1c) and look-ahead ≈ `r + Σ w` scaled by the measured β (Corollaries 1.1, 1.2). If the measurement disagrees with the theorem, find out why before going on.

### Stage 5 — The priming pipeline *(3 weeks)*
- **Goal:** snapshots are warmed with no user data, automatically.
- **Input:** edge samples captured by the orchestrator; `gen_inputs.py`; JaCoCo.
- **Work:** steps A2–A5 and A7: capture, find control-flow fields, scrub, certify with branch coverage, warm up in a small-shaped JVM, checkpoint.
- **Output:** a "deploy → certified snapshot image" pipeline.
- **Exit:** certification decides correctly on the exp-a function (fps2 passes, the naive scrub fails), and scrubbed images serve as well as real-traffic images inside OpenWhisk.

### Stage 6 — Full DAGs: parallel, branches, depth choice *(4 weeks)*
- **Goal:** the rest of the theory, measured.
- **Input:** Stages 4–5.
- **Work:**
  - fan-out/fan-in workflows (Theorem 1 on a real DAG);
  - if/else branches with the `p ≥ κ` rule (Theorem 4);
  - uncertain input times with the κ-quantile trigger (Theorem 3);
  - depth per stage from Theorem 7's DP (step A6).
- **Output:** one experiment per theorem, each with its control.
- **Exit:** each theorem's prediction matches the measurement within its confidence interval, or the difference is explained.

### Stage 7 — Evaluation against baselines *(4–5 weeks)*
- **Goal:** the comparison the thesis will be judged on.
- **Workloads:** your 3-stage Spring Boot workflow (exp15), plus 3–5 SeBS-Flow workflows **ported to Java** (most SeBS benchmarks are Python or Node.js, and the JIT gain is Java's).
- **Arrivals:** Azure Functions 2021 trace replay.
- **Baselines:** cold start; OpenWhisk keep-alive; restore-on-demand (what SnapStart does); cold prewarm (Xanadu/ORION style); `-XX:TieredStopAtLevel=3`; JDK 25 AOT profiles (JEP 515).
- **Metrics:** mean, p50, p99 latency; memory-time (GB·s); number of restores; snapshot storage. Bootstrap CIs.
- **Exit:** full result tables; every claim in `REPORT.md` either confirmed on the real system or corrected.

### Stage 8 — Writing *(6–8 weeks, starts during Stage 7)*
- **Thesis chapters:**
  1. introduction;
  2. background;
  3. the measurement study (existing experiments);
  4. model and theorems;
  5. design and implementation;
  6. evaluation;
  7. related work;
  8. conclusion.
- **Paper:** a serverless workshop first (for example WoSC), then a conference version if Stage 7 is strong.

**Total:** about 26–30 weeks (6–7 months) of work. Stages 1–4 (about 2 months) already give
the core result: look-ahead restore measured on a real system. Fit the rest to the time left
in your program.

```
Stage 1 ──► Stage 2 ──► Stage 3 ──► Stage 4 ──► Stage 6 ──► Stage 7 ──► Stage 8
 (β go/no-go)                         │                      ▲
                                      └──► Stage 5 ──────────┘
```
