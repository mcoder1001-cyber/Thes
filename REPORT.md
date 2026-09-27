# Report: reducing workflow cold start with snapshots

*Plain-English summary of the approach: the problem, the conditions, the method step by step,
how to build it, and what has been done. Written 2026-09-26, cleaned up the same day. The
approach reads **no user data** at any point.*

---

## 0. The thesis in one sentence

**When a workflow of functions starts cold, restore all its stages' snapshots in parallel,
each timed to be ready just when its input arrives, instead of one after another.** It uses
only the workflow's shape (the DAG) and measured timings: no user data, no predictions.

```
today:   restore1 → run1 → restore2 → run2 → restore3 → run3 → ...   = 5 restores in a row (3.4 s)
ours:    restore1..5 start together, each ready just in time          = 1 restore + the work   (0.8 s)
```
(a 5-stage Java workflow, one restore ≈ 0.65 s)

---

## 1. Which document to read for what

| file | what it is | read it when |
|---|---|---|
| **`REPORT.md`** (this file) | the whole story in simple English | first |
| `ROADMAP.md` | tools, the math behind each proof, the stages from here | you plan the next months |
| `theory/DAG_SNAPSHOT_THEORY.md` | the mathematics: model, theorems, proofs (§0 is a one-page summary) | you need exact statements and proofs |
| `theory/ALGORITHM.md` | **the algorithm**, and the known OR problem it solves (project scheduling) | you need the algorithm, or the "which known problem is it" answer |
| `theory/verify_dag.py` | a program that checks every theorem (75/75 pass) | you want the proofs checked by computer |
| `ideas/PAPER_NOTES.md` | notes on the 28 papers: what each gives us, numbers to reuse | you write related work, or need a parameter |
| `ideas/sim/` | the workflow simulator and the Azure trace study | you want to rerun the simulations |
| `ideas/criu-box/` | scripts for the machine with working CRIU (`run_x2.sh`) | you run the real snapshot tests |
| `ideas/IDEAS.md` | the evidence, including ideas tried and dropped | you need a number or a source |
| `ideas/exp-a-context-priming/` | real JVM warm-up experiments (1,600 runs) | background; its input-scrubbing part is dropped |
| `theory/MODEL.md` | your earlier model: how deep to snapshot each function | background; Theorem 7 updates it |

---

## 2. The problem

### 2.1 Background in three sentences
- In FaaS, a function that has not run for a while must **cold start**: the platform starts a
  container, starts the runtime and loads the framework (cost **A**). The first requests are then
  slow while the JIT compiler warms up (cost **B**), and after that it runs at normal speed (**C**).
- A **workflow** is a set of functions connected as a **DAG**: A calls B, B calls C, sometimes in
  parallel, sometimes with if/else. When a workflow has been idle, *every* stage is cold, and the
  cold starts **add up along the chain**. Your own measurement: a 3-stage Spring Boot workflow
  takes **12.1 s cold vs 35 ms warm**.
- A **snapshot** (CRIU / CRaC) saves a running process to disk. Restoring it is much faster than
  starting from zero.

### 2.2 What is still wrong with snapshots today
1. **Restores happen one after another.** Today's systems (AWS SnapStart, Prebaking, Pronghorn)
   restore a function only when its request arrives. In a workflow, stage 2's request arrives
   only after stage 1 finishes, so a 5-stage workflow pays **5 restores in a row**. On your
   machine one Spring Boot restore takes **0.6 to 9 seconds** under CPU limits.
2. **Not every stage is worth a snapshot.** Some runtimes start fast anyway. Some images are big
   and slow to load. Some stages' start-up is hidden behind others. Your `MODEL.md` chose
   snapshot depth assuming restores run one after another, and that choice changes once they overlap.
3. **Restoring ahead uses memory earlier.** Restores overlap with stages still running, so the
   memory peak is higher, and a platform's memory budget can overflow.

### 2.2b The two effects that make it matter: the cascade and the vCPU cliff
- **The linear cascade.** On demand, each stage adds its restore and its run: a `d`-stage
  chain takes `d·(r + w)`, a straight line in `d` with slope `r + w` per stage. Others have
  measured this line on public clouds: Xanadu fits it with R² = 0.993 on AWS Step Functions;
  Kulkarni et al. 2025 find cold starts cascading in sequential workflows on Azure (252 s, 74%,
  on their image workflow).
- **The vCPU cliff.** Small containers make every term bigger. Your exp14: the JVM's warm-up
  `B` grows **13–35×** from 4 to 0.25 vCPU (CFS quota throttling freezes the JIT's compile
  bursts). A restore is CPU work too (0.64–9 s under CPU limits).
- **Together they multiply:** the slope of the line is `r(c) + w(c)`, and both grow as the
  vCPU `c` shrinks. The worst case is a deep workflow in small containers, which is exactly
  what FaaS runs.
- **What the thesis does to each:**
  - **look-ahead** removes `r` from the slope: `r + d·w` instead of `d·(r + w)`
    (Theorem 1). The slope drops from `r + w + δ` to `w + δ`: 727 → 77 ms per Java stage;
  - **snapshot depth** shrinks `w`, because the warm-up is inside the image (Theorem 7,
    `MODEL.md`).

  So the cascade is the reason for look-ahead, and the cliff is the reason for depth.
- **How the thesis shows it** (ROADMAP Stage 4): one figure, latency against depth at 0.25 and
  1 vCPU, on demand and with look-ahead, with a fitted line for each. The predicted slopes are
  `r(c) + w(c) + δ` and `w(c) + δ`. The two effects also enter the model as its inputs: `r`
  and `w` are profiled at the serving vCPU (step A1). The cliff raises the memory peak too
  (Theorem 8(a): `⌈(r+w)/(w+δ)⌉` grows with `r`), so small containers need the memory guard
  most.

### 2.3 The problem statement
> **Given** a workflow DAG and the measured timings of its functions, **decide**
> (1) *when* to restore each stage,
> (2) *which* stages get a snapshot, how deep, and where the image is stored,
> (3) how to stay within the memory budget,
> **so that** a cold workflow is as fast as possible, **without reading any user data**.

### 2.4 What is new
Every snapshot system we found works on **one function at a time**. Every system that uses the
workflow DAG against cold starts uses **cold boots or keep-alive**, not snapshots. **Nobody uses
the DAG to schedule snapshot restores.** (Credit where due: *timing* cold containers just in
time along the DAG is Xanadu's idea, 2020. Ours is doing it with snapshots, with proofs, plus
the snapshot choice and memory.) The workflow knows what a single function cannot:
which stages will run and roughly when. The workflow's own execution then hides the restores
(**look-ahead restore**). Deciding which stages get snapshots, and keeping memory safe, follow
from the same idea.

---

## 3. Conditions (assumptions), in plain words

The proofs hold when these conditions hold. The last column says how each one is checked.

| # | condition | meaning | checked by |
|---|---|---|---|
| C1 | **No fortune-telling** | restores start only when the workflow request arrives, never before | safe side: prediction could only help (and on the Azure trace it barely would) |
| C2 | **Parallel restores do not slow each other much** | restoring 5 stages at once takes about as long as restoring 1 | **must be measured**: test **x2** (`run_x2.sh`). The theory covers partial slow-down: the gain shrinks by the factor (1 − β) but never becomes a loss |
| C3 | **A stage's work time is fixed once it starts** | the time after a restore is known | measured per function; test **x3** measures warm-up lost by a real restore |
| C4 | **Memory is held from restore start until the stage finishes** | the memory cost model | conservative (lazy restore would use less) |
| C5 | **The DAG is known** | the orchestrator knows the workflow structure | true for OpenWhisk sequences, Step Functions, Durable Functions |
| C6 | **Timings can be profiled** | restore time r, work w, memory m, image size s per function | a few test runs per function version |
| C7 | **No kernel or OS changes** | only CRIU/CRaC and the platform | from your proposal's constraints |

---

## 4. The approach, step by step

Two phases: **build time** (when a function is deployed) and **run time** (every time a
workflow is called). Each step gives its **Input**, **Aim** and **Output**, and **How** it is
done.

### Phase A: build time (per function, on each deploy)

**A1. Profile the function**
- *Input:* the function's code and the developer's own test requests (none if it has none).
- *Aim:* know how slow each way of starting it is.
- *Output:* per function: cold start **A**, warm-up **B**, normal run **C**, restore time **r**,
  leftover warm-up after a snapshot **R**, memory **m**, image size **s**.
- *How:* a few test cold starts and restores (`ideas/criu-box` x1 measures the restore times).

**A2. Pick the snapshot point**
- *Input:* the profile from A1 and the runtime type.
- *Aim:* the earliest point that captures the expensive start-up, with no request data in the image.
- *Output:* "after start-up" for every runtime; "after warm-up" only where warm-up is large.
- *How:*

  | runtime | warm-up to capture | snapshot point |
  |---|---|---|
  | Java | large (370 ms at 1 vCPU; 13–35× more at 0.25 vCPU than at 4 vCPU) | after start-up **plus warm-up with the developer's test requests** |
  | .NET | small (one request captures it all) | after start-up plus one test request |
  | Node.js | some (V8 has a JIT); not measured yet | measure; probably after start-up |
  | Python | about none (0–19 ms measured) | after start-up only; the cost is imports |
  | Go, C++, Rust | none (compiled ahead of time) | usually no snapshot (A3 decides); only if start-up does heavy work |

  **When to stop warming up:** when the JIT stops compiling new code. The runtime reports this
  itself (compile counters). Depth is *work done*, not a number of requests (Proposition 8).
  The test requests should cover every kind of call the stage receives: warming up on the wrong
  kind was 1.3–2.6× worse in our JVM runs.

**A3. Decide which stages get a snapshot**
- *Input:* the DAG, the profiles, and a storage budget, a price or a latency target.
- *Aim:* the lowest cold-workflow latency *under look-ahead restore*, at acceptable cost.
- *Output:* for every stage: no snapshot, or a snapshot at the point from A2, stored next to the
  invoker or in cheaper remote storage.
- *How:* Theorem 7's algorithm (`dp_joint` in `theory/verify_dag.py`). A stage gets **no**
  snapshot when:
  - its snapshot is no faster than its cold start (**dominated**). Examples: a fast-starting
    runtime, or a big image pulled from remote storage, where restore time grows with image size;
  - its cold start is **hidden** behind other stages' work (Corollary 7.1), even at the entry
    when a parallel downstream restore takes longer;
  - it is **not worth its cost** (Corollary 7.3). The algorithm gives the whole
    cost-versus-latency curve, and you pick by a latency target.

  In money alone, a Java image pays for itself only above ~6–13 cold invocations per day; the
  median Azure workflow has **1**. So snapshots **buy speed, not savings**. Cost mainly decides
  where each image lives.

**A4. Take the snapshot and store it**
- *Input:* the function and the snapshot point.
- *Aim:* a safe image, close to the machines that will use it.
- *Output:* the image, cached on each invoker (or in remote storage, per A3).
- *How:*
  - reset random-number state, UUID generators and secrets in CRaC's `beforeCheckpoint` hook.
    Every copy of a snapshot would otherwise share them, even with zero requests;
  - for Java, warm up on a large machine (10× faster) but start the JVM with the *small*
    container's CPU settings (`-XX:ActiveProcessorCount=1`, a fixed GC). Otherwise the snapshot
    is 11–17% worse;
  - take the checkpoint (`jcmd <pid> JDK.checkpoint` with CRaC, or `criu dump`).

### Phase B: run time (every time a workflow is called)

**B1. Check whether the workflow is already warm**
- *Rule:* if the entry function has a live sandbox, the others do too (Lemma 5): run normally.
  Otherwise continue.

**B2. Compute when each stage will need its sandbox**
- *Input:* the DAG and each stage's restore time r and work w.
- *Output:* each stage's start time **S\*** if everything is restored in time.
- *How:* one pass through the DAG: a stage starts when all its inputs have arrived, and not
  before its own restore could finish.

**B3. Compute when to start each restore**
- *Output:* **τ = S\* − r** for each stage. When stage times are uncertain, aim to be ready at
  the κ-quantile of the input time (Theorem 3).
- *Why:* this is the **lowest latency any policy can reach** (Theorem 1), with **no more
  memory·time than today's restore-on-demand** (Theorem 2).
- *But* the memory **peak** is higher (Theorem 8): an 8-stage Java chain peaks at 4 GB instead
  of 512 MB. Hence the guard in B5.

**B4. If/else branches**
- Restore a branch's stages early only if its probability p ≥ κ. If the branch is decided
  early enough, just wait (Theorem 4).

**B5. Execute, through the memory guard**
- If memory is short for this workflow (the JIT schedule's peak exceeds what it may use),
  first **plan** the restore times exactly: the problem is a known scheduling problem, and a
  standard branch and bound solves workflows of up to about 10 stages in milliseconds
  (`theory/ALGORITHM.md`). The guard then executes that plan.
- Every restore asks the **memory guard** first (Theorem 8(c)). Stages whose input has arrived
  go first. If one does not fit, it evicts look-ahead sandboxes that are not needed yet. The
  budget is never exceeded, and the workflow cannot deadlock.
- Fire the restore for each stage at τ, run each stage when its input arrives, and release the
  sandboxes of branches not taken.

**B6. Keep-alive afterwards.** Under look-ahead, keeping *one* stage of a workflow warm is worth
little: the next stage's restore becomes the long pole (Proposition 9: in a 5-stage Java chain,
the entry alone saves 77 ms, all five save 650 ms). So keep whole workflows warm, or none.

---

## 5. How to implement it on your setup (OpenWhisk + CRaC)

| component | what to build | where it hooks in |
|---|---|---|
| **Snapshot action image** | a Docker image that starts with a CRaC restore instead of a fresh JVM and answers `/init` and `/run` | an OpenWhisk blackbox action; `ideas/criu-box/FnServer.java` is a start |
| **Snapshot builder** (A1–A4) | on deploy: profile, warm up with the developer's test requests if needed, checkpoint with the reset hooks | outside OpenWhisk; images stored next to the invokers |
| **Profile store** | r, w, m, image size per function version | read by the orchestrator |
| **Workflow orchestrator** (B1–B5) | runs the DAG by calling OpenWhisk actions, computes τ, sends a "wake" call to restore a stage ahead, applies the memory guard | a small Python service; OpenWhisk sequences are linear only |

Build order:
1. Run **x2** on your machine. If parallel restores slow each other badly, rethink before building.
2. Build the snapshot action image for one Java action and measure its restore time (x1).
3. Add the orchestrator for chains only, and measure 3-, 5- and 8-stage chains against
   restore-on-demand, including peak memory.
4. Add parallel stages, branches, the which-stages choice (A3) and the memory guard.
5. Evaluate on Java workflows and an Azure trace replay against restore-on-demand, cold prewarm,
   keep-alive, `-XX:TieredStopAtLevel=3` and JDK 25's AOT cache (JEP 515).

---

## 6. What has been done

**Reading and novelty.** Proposal, research plan, synthesis and reading list; a literature search
(Pronghorn, Fireworks, Spice, TrEnv, RainbowCake, FaasCache, REAP, FaaSnap and others). **No
existing work uses the workflow DAG to schedule snapshot restores.**

**Theory** (`theory/DAG_SNAPSHOT_THEORY.md`, checked by `verify_dag.py`: **62/62 checks, 12 of
them controls designed to fail**, which do). Three main results:
- **Timing** (Theorems 1–2): look-ahead restore reaches the lowest possible latency, with no
  extra memory·time; on a chain, d restores in a row become one.
- **Which stages** (Theorem 7, Corollaries 7.1–7.3): an exact algorithm for which stages get a
  snapshot, how deep and where, under a budget, a price or a latency target.
- **Memory** (Theorem 8): the peak is higher; each extra memory slot buys a known amount of
  speed; the guard never exceeds the budget and cannot deadlock.

Supporting rules: uncertain timings (Theorem 3), branches (Theorem 4), skip when warm (Lemma 5),
why keep-alive cannot replace it (Theorem 6), when to stop warming up (Proposition 8).

**Simulation** (Azure Functions 2021 trace, 68 workflows, 432,945 calls):
- cold workflows go from **2.34 s to 0.82 s** on average, and from 6.20 s to 1.36 s at p99, with
  the same memory and number of restores as restore-on-demand;
- with the memory guard, a burst of cold workflows never exceeds the budget;
- on the trace at budgets below its working set, look-ahead and keep-alive compete for memory,
  and the operator has to choose.

**Real JVM measurements** (1,600 runs under CPU limits; snapshots were imitated by a process that
had served K requests, because CRIU cannot run in the cloud machine):
- warming up before the snapshot matters for Java: no warm-up leaves 2–5× more warm-up for later;
- warming up on the wrong kind of request is 1.3–2.6× worse;
- warming up on a big machine is 10× cheaper and equally good, if the JVM is pinned to the small
  container's CPU shape.

**Scripts for your CRIU machine:** `ideas/criu-box/run_x2.sh` (one command) and x1, x3, x4.
Written and tested with fake restores, **not yet run for real**.

**Dropped** (kept as a record in `ideas/IDEAS.md` and the theory's Appendix A):
- warming snapshots on scrubbed copies of users' messages: it reads user inputs;
- predicting when a workflow will be called: the gaps in the Azure trace are too irregular.

**Mistakes caught and fixed** (kept visible, as your standing rules ask):
- two simulator bugs, both caught by control checks;
- a wrong check (random results compared with an exact bound);
- an unreadable figure;
- 15 Java runs that overlapped other CPU work were redone;
- a timing bug in the x2 script.

---

## 7. Main numbers at a glance

| what | number | source |
|---|---|---|
| cold vs warm, 3-stage Spring Boot workflow (1 vCPU) | 12.1 s vs 35 ms | your exp15 |
| one Spring Boot restore under CPU limits | 0.64–9.05 s | your exp11/12 |
| restore-on-demand vs look-ahead, 3 / 5 / 8-stage Java chain | 2.20 / 3.67 / 5.89 s vs 0.94 / 1.12 / 1.37 s | `ideas/sim` e1 |
| cold workflows on the Azure trace, mean / p99 | 2.34 / 6.20 s → **0.82 / 1.36 s**, same memory | `ideas/sim` e4 / e4b |
| peak memory, 8-stage Java chain: on demand vs look-ahead | 0.5 GB vs 4 GB (same memory·time) | Theorem 8(a) |
| latency with 1 / 2 / 4 / 8 memory slots, same chain | 5.80 / 2.98 / 1.68 / 1.26 s (on demand 5.81 s) | Theorem 8(b) |
| burst of 16 cold 8-stage chains at 8 GB: starts over the budget per run | look-ahead 32.6 → **0 with the guard**, still faster than on demand | `ideas/sim` e7a |
| cold invocations/day for a Java image to pay for itself in money | 6–13 (Azure median workflow: 1) | `ideas/sim` e6 |
| memory guard vs the exact optimum, 3–8-stage DAGs under a cap | optimal on 67%, 4.8% slower on average; exact planning closes the gap | `theory/ALGORITHM.md` §5 |
| look-ahead with 1 / 2 / 4 / 9 parallel restores, 5-stage Java chain | 3.33 / 2.02 / 1.38 / 1.03 s (on demand 3.63 s) | `theory/ALGORITHM.md` §6 |
| theorems checked by computer | 75/75 | `theory/verify_dag.py` |

---

## 8. What is not done yet, and what can still go wrong

1. **x2 on your machine** (`sudo ./ideas/criu-box/run_x2.sh`). If parallel restores slow each
   other badly, look-ahead loses most of its gain; the theory gives the exact loss.
2. **x1 and x3**: real restore times, and how much warm-up a real restore keeps.
3. **Measure real image sizes** (the cost numbers assume 90 MB for Spring Boot).
4. **Build it in OpenWhisk** (section 5) and measure real workflows.
5. **Theory gaps:**
   - nested if/else branches (Theorem 4 treats one branch at a time);
   - DAGs that are not series-parallel have no exact algorithm yet;
   - under a hard memory cap, on general DAGs the guard alone is occasionally slower than
     on-demand (12% of random DAGs at some cap, by up to 1.37×), a known scheduling anomaly.
     Exact planning at arrival fixes this for small workflows; large ones (> ~10 stages) rely
     on the guard or a node-limited search.
   - Proposition 9's workflow-level keep-alive is proved but not yet simulated on the trace.
6. **Read Pronghorn's full paper** before writing the novelty chapter.

---

## 9. Small glossary

- **Cold start**: the delay when a function starts from nothing.
- **Snapshot / checkpoint**: a saved copy of a running process, restored later.
- **CRIU**: the Linux tool that saves and restores processes.
- **CRaC**: a Java feature that uses CRIU and lets the program prepare for it.
- **DAG**: the workflow graph of stages.
- **Critical path**: the longest chain of work in the DAG; it sets the total time.
- **Warm-up**: running test requests before the snapshot, so the JIT has already compiled the code.
- **Restore-on-demand**: today's way: restore a stage when its request arrives.
- **Look-ahead restore**: our way: restore later stages while earlier ones run.
- **Memory guard**: the rule that admits restores only while memory allows.
- **κ (kappa)**: memory price ÷ (memory price + latency price); one knob that sets how early to
  restore and when to restore a branch early.
