# Report: reducing workflow cold start with snapshots

*Plain-English summary of the whole approach: the problem, the conditions, the method step by
step, how to build it, and what has been done so far. Written 2026-09-26.*

---

## 0. Which document to read for what

| file | what it is | read it when |
|---|---|---|
| **`REPORT.md`** (this file) | the whole story in simple English | first |
| `theory/DAG_SNAPSHOT_THEORY.md` | the mathematics: model, theorems, proofs | you need the exact statements and proofs |
| `theory/verify_dag.py` | a program that checks every theorem (44/44 pass) | you want to see the proofs checked by computer |
| `ideas/IDEAS.md` | the evidence: experiments, simulations, numbers, novelty check | you need a number or a source |
| `ideas/exp-a-context-priming/` | real Java experiments (1,600 runs) | you want to rerun or extend the measurements |
| `ideas/sim/` | the workflow simulator and the Azure trace study | you want to rerun the simulations |
| `ideas/criu-box/` | scripts to run on the machine with working CRIU | you run the real snapshot tests |
| `theory/MODEL.md` | your earlier model: how deep to snapshot each function | background; Theorem 7 updates it |
| `READING_LIST.md` | papers, including the 5 added this session (read Pronghorn first) | related work |

---

## 1. The problem

### 1.1 Background in three sentences
- In FaaS, a function that has not run for a while must **cold start**: the platform starts a
  container, starts the runtime, loads the framework (cost **A**), and then the first requests
  are slow while the JIT compiler warms up (cost **B**). After that it runs at normal speed
  (cost **C**).
- A **workflow** is a set of functions connected as a **DAG** (a graph of stages: A calls B,
  B calls C, sometimes in parallel, sometimes with if/else branches). When a workflow has been
  idle, *every* stage is cold, and the cold starts **add up along the chain**. Your own
  measurement: a 3-stage Spring Boot workflow takes **12.1 s cold vs 35 ms warm**.
- A **snapshot** (CRIU / CRaC) saves a running process to disk; restoring it is much faster than
  starting from zero. If the snapshot is taken after some warm-up requests (a **deep**
  snapshot), the JIT work is saved too.

### 1.2 What is still wrong with snapshots today
1. **Restores happen one after another.** Today's systems (AWS SnapStart, Prebaking,
   Pronghorn) restore a function only when its request arrives. In a workflow, stage 2's
   request arrives only after stage 1 finishes, so a 5-stage workflow pays **5 restores in a
   row**. On your machine one Spring Boot restore takes **0.6 to 9 seconds** under CPU limits.
2. **Deep snapshots need warm-up requests, and those carry user data.** To warm the JIT before
   the snapshot you must run requests. Real requests put **user data inside the snapshot
   image**, which is then stored and reused for other users. Fake requests are safe but usually
   warm the wrong code.
3. **Deciding how deep to snapshot ignored the workflow.** Your `MODEL.md` chose snapshot depth
   assuming restores sit one after another on the critical path. Once restores are overlapped
   (problem 1 solved), that choice can be wrong.

### 1.3 The problem statement
> **Given** a workflow DAG whose stages can be snapshotted, **decide**
> (1) *when* to restore each stage,
> (2) *how deep* each stage's snapshot should be, or whether it needs one at all,
> (3) *what inputs* to warm each snapshot with,
> **so that** the latency of a cold workflow is as small as possible, memory and storage stay
> within budget, and **no user data enters any snapshot**.

### 1.4 What is new (the novelty)
Every snapshot system we found works on **one function at a time**. Every system that uses the
workflow DAG to fight cold starts uses **cold boots or keep-alive**, not snapshots. Nobody we
found uses the DAG to manage snapshots. A workflow orchestrator knows things a single function
does not: which stages will run, roughly when, and what their inputs look like. We use that
knowledge twice:

- **Innovation 1: look-ahead restore (timing).** While the first stages run, restore the later
  stages' snapshots so each one is ready the moment its input arrives. The workflow's own
  execution hides the restores.
- **Innovation 2: data-free, certifiable priming (content).** Warm each snapshot using copies of
  the messages the DAG already carries, with all personal values randomised but their format
  kept, then check that these copies follow the same code paths as real requests.

One claim of the old plan had to go: "nobody has studied how many warm-up requests to run
before checkpointing" is no longer true (Pronghorn, EuroSys 2024, does it for single
functions). The new contribution is at the workflow level, where nobody has worked yet.

---

## 2. Conditions (assumptions), in plain words

The proofs hold when these conditions hold. The last column says how each one is checked.

| # | condition | meaning | checked by |
|---|---|---|---|
| C1 | **No fortune-telling** | we start restores only when the workflow request arrives, never before | safe side: prediction could only help. The proofs show exactly how much the result depends on this |
| C2 | **Parallel restores do not slow each other much** | restoring 5 stages at once takes about as long as restoring 1 | **must be measured**: `ideas/criu-box` test **x2** decides whether Innovation 1 works on your machine. The theory also covers partial slow-down: the gain shrinks with the slow-down factor β but never becomes a loss while β ≤ 1 |
| C3 | **A stage's work time is fixed once it starts** | the time after a restore (leftover warm-up plus normal run) is known | measured per function; test **x3** measures warm-up lost by a real restore |
| C4 | **Memory is held from restore start until the stage finishes** | the cost model for memory | conservative (lazy restore would use less) |
| C5 | **The DAG is known** | the orchestrator knows the workflow structure | true for OpenWhisk sequences, Step Functions, Durable Functions |
| C6 | **Stage timings can be profiled** | restore time r, work w, memory m per function | a one-off measurement per function version |
| C7 | **For safe priming: the code branches on "category-like" fields** | decisions depend on fields with few values (type, country, plan), not on free text or ids | **checked automatically** per function (step A5 below); if it fails, that function falls back to normal priming |
| C8 | **No kernel or OS changes** | uses only CRIU/CRaC and the platform | from your proposal's constraints |

---

## 3. The approach, step by step

The approach has two phases: **build time** (when a function is deployed) and **run time**
(every time a workflow is called). For each step: **Input** is what the step needs, **Aim** is
what it is for, **Output** is what it produces, and **How** says what exists in the repo.

### Phase A: build time (per function, when it is deployed or its traffic changes)

**A1. Profile the function**
- *Input:* the function's code and a sample of requests.
- *Aim:* know how slow each way of starting it is.
- *Output:* a table per function: cold start time **A**, warm-up **B**, normal run **C**, restore
  time **r**, leftover warm-up after a snapshot of depth K **R(K)**, memory **m**, image size
  **s**.
- *How:* your existing `exp5` harness plus `ideas/criu-box/criu_box.py` (x1 for restore times).

**A2. Collect the traffic on each incoming edge**
- *Input:* the messages that flow into this function from each upstream stage (the orchestrator
  already passes them along; it only has to keep a sample).
- *Aim:* know what the function's inputs look like, per edge, and how much work each one causes.
- *Output:* a sample of messages per incoming edge, with its share of traffic.

**A3. Find the control-flow fields**
- *Input:* the samples from A2.
- *Aim:* separate fields that *steer the code* (few distinct values: `type`, `currency`,
  `country`, `tier`, `plan`) from fields that are *data* (names, emails, ids, amounts).
- *Output:* a list of "keep" fields. Rule used: a text or integer field seen at least 50 times
  with at most 32 distinct values (and at most one per 5 observations) is control flow.
- *How:* `learn_categorical(..., numbers=True)` in `ideas/exp-a-context-priming/gen_inputs.py`.

**A4. Scrub the samples**
- *Input:* samples plus the keep-list.
- *Aim:* remove all personal content while keeping everything the code looks at.
- *Output:* a scrubbed priming set. Keys, control-flow values and booleans are kept. Every other
  character is replaced by a random one of the same kind (capital → capital, digit → digit,
  lowercase → lowercase; punctuation stays). Numbers keep their number of digits and decimals.
  So `pablo.moreau@corp.net` becomes something like `qvbav.uoxlqg@cpsn.zsx`: still a valid email,
  no longer anyone's.
- *How:* `scrub()` in `gen_inputs.py` (this is "fps2").

**A5. Certify the scrubbed samples**
- *Input:* the function, real samples, scrubbed samples.
- *Aim:* prove the scrubbed requests take **the same code paths** as the real ones, so the JIT
  learns the same thing (Proposition 7 in the theory).
- *Output:* pass or fail. On pass, use the scrubbed set. On fail, fall back to the normal priming
  for that function.
- *How:* compare branch-coverage counts (a coverage tool such as JaCoCo). In this repo,
  `ideas/exp-a-context-priming/src/Sig.java` does it by hand for the test function: 100% of
  requests take identical paths on one edge, 98.7% on the other.

**A6. Decide which stages get a snapshot, and how deep**
- *Input:* the DAG, the profiles from A1, a storage budget.
- *Aim:* the lowest cold-workflow latency *under look-ahead restore* within the budget.
- *Output:* for every stage, one of: no snapshot, or snapshot at depth K.
- *How:* Theorem 7's algorithm (`dp_joint` in `theory/verify_dag.py`). Two quick rules come out
  of it:
  - a late stage whose cold start is hidden behind the earlier stages' work needs **no
    snapshot** (Corollary 7.1);
  - if snapshots differ only in speed, give them to the stages **earliest in the workflow**,
    i.e. with the longest remaining path (Corollary 7.2).

**A7. Warm up and take the snapshot**
- *Input:* the function, the certified scrubbed set (from **all** incoming edges, enough work per
  edge), the depth K from A6.
- *Aim:* produce a snapshot image that is already warm and holds no user data.
- *Output:* the snapshot image.
- *How:*
  - run the warm-up on a large machine, where it is 10× faster, but start the JVM with the
    *small* container's CPU settings (`-XX:ActiveProcessorCount=1`, a fixed GC). Otherwise the
    snapshot is 11–17% worse;
  - count depth as *work done*, not number of requests; heavy requests warm more;
  - reset random seeds, UUID generators and secrets in CRaC's `beforeCheckpoint` hook;
  - take the checkpoint (`jcmd <pid> JDK.checkpoint` with CRaC, or `criu dump`).

**A8. Store the image near the machines that will run it**
- *Input:* the image.
- *Aim:* restores read from local disk or memory, not the network.
- *Output:* the image cached on each invoker (disk or page cache).

### Phase B: run time (every time a workflow is called)

**B1. Check whether the workflow is already warm**
- *Input:* the new workflow request and the current sandboxes.
- *Aim:* do nothing extra when not needed.
- *Output:* "warm" means stop here and run normally; "cold" means continue.
- *Rule:* if the entry function has a live sandbox, the others do too (Lemma 5), so do nothing.

**B2. Compute when each stage will need its sandbox**
- *Input:* the DAG and each stage's restore time r and work w.
- *Aim:* know each stage's start time **S\*** if everything is restored in time.
- *Output:* one number S\* per stage.
- *How:* one pass through the DAG in order: a stage starts when all its inputs have arrived, and
  not before its own restore could finish.

**B3. Compute when to start each restore**
- *Input:* S\*, r, and the ratio κ between the price of memory and the price of latency.
- *Aim:* the sandbox is ready exactly when needed, without holding memory longer than necessary.
- *Output:* a start time for each restore: **τ = S\* − r**. When stage times are uncertain,
  aim to be ready at the κ-quantile of the input time (Theorem 3).
- *Why it is good:* this gives the **lowest latency any policy can reach** (Theorem 1) and uses
  **no more memory than today's restore-on-demand** (Theorem 2).

**B4. Decide about if/else branches**
- *Input:* the probability p of each branch and κ.
- *Aim:* restore a branch's stages early only when it pays off.
- *Output:* for each branch stage, "restore early" or "wait for the decision". Restore early if
  p ≥ κ. If the branch is decided early enough, just wait (Theorem 4).

**B5. Execute**
- *Input:* the plan from B2–B4.
- *Aim:* run the workflow.
- *Output:* the result.
- *How:*
  - fire `criu restore` (or the CRaC restore) for each stage at its time τ;
  - run each stage when its input arrives;
  - if a branch is not taken, release its early-restored sandboxes;
  - optionally, while a restored stage waits for its input, send it a few scrubbed requests to
    finish warming up.

**B6. Keep-alive as usual afterwards.**

---

## 4. How to implement it on your setup (OpenWhisk + CRaC)

| component | what to build | where it hooks in |
|---|---|---|
| **Snapshot runtime** | a custom Java action runtime image whose `/init` restores a CRaC checkpoint instead of starting a new JVM | the OpenWhisk action proxy (each action is a container that answers `/init` and `/run`) |
| **Priming service** (steps A2–A7) | a job run on deploy: gathers edge samples, scrubs, certifies, warms up, checkpoints | outside OpenWhisk; stores images next to the invokers |
| **Profile store** (A1, A6) | a small table: r, w, m, image size per action version | read by the controller |
| **Look-ahead planner** (B1–B4) | when a sequence or composition starts cold, compute τ for each downstream action | the OpenWhisk controller, where sequences are executed |
| **Restore trigger** (B5) | at time τ, ask the invoker to `/init` (restore) the downstream action | uses OpenWhisk's existing prewarm path |

A sensible build order:
1. Run **x2** on the S0 box. If parallel restores slow each other badly, stop and rethink
   Innovation 1.
2. Build the snapshot runtime for one Java action and measure restore time (x1).
3. Add the planner for plain sequences (chains) only; measure a 3-stage and a 5-stage sequence
   against restore-on-demand.
4. Add the priming service with scrubbing and certification.
5. Add branches, the depth choice (Theorem 7) and uncertainty (κ-quantile).
6. Evaluate on real workflows (SeBS-Flow) and the Azure traces, against restore-on-demand,
   cold prewarm, keep-alive, `-XX:TieredStopAtLevel=3` and JDK 25's AOT profiles (JEP 515).

Check the details of the controller hook against the OpenWhisk version on the box before
writing code.

---

## 5. What was done in this session

**Reading and checking novelty**
- Read the proposal (Persian PDF), the research plan, synthesis, reading list, handoff,
  `MODEL.md` and `verify.py`. `experiments/` (RESULTS.md, raw data) is **not in the
  repository**, so all earlier numbers come from those documents.
- Searched the literature. **Found Pronghorn (EuroSys 2024)**, which already automates snapshot
  depth for single functions, plus Fireworks, Snapipeline, Faast and JEP 515. Added them to the
  reading list.

**Real experiments (Java, in this session's VM)**
- Built CRIU 4.2 from source. It **cannot run here**: this VM's kernel lacks a system call CRIU
  needs (`kcmp`). So snapshots were *emulated*: a process that has served K requests stands in
  for a depth-K snapshot. This is exact for comparing warm-up methods, but excludes restore time.
- Wrote a realistic Java function (Jackson JSON, BigDecimal, regex) and ran it under
  CPU limits (0.25, 1 and 4 vCPU): **1,600 runs**, 20 per condition, each experiment with a
  control whose answer is known in advance:
  - **scrubbed warm-up is as good as real traffic**: 0.98–1.11×, every confidence interval
    includes 1;
  - warming on the wrong edge's traffic is 1.3–2.6× worse; warming on a mix of all edges with
    enough work is *better* (0.80–0.89×);
  - warming on a big machine is 10× cheaper and equally good, *if* the JVM is set to the small
    container's CPU shape.

**Simulation**
- Built a workflow simulator and ran it on the Azure Functions 2021 trace (68 workflows,
  432,945 calls).
- For workflows called after more than 10 minutes idle, look-ahead restore gives
  **0.82 s instead of 2.34 s on average, and 1.36 s instead of 6.20 s at p99**, using the same
  memory and the same number of restores as today's restore-on-demand. Default keep-alive gives
  9.43 s for those calls.

**Theory**
- Wrote the model and **7 theorems plus corollaries** with proofs
  (`theory/DAG_SNAPSHOT_THEORY.md`). A checker program verifies all of it: **44/44 checks**,
  including 9 "controls" designed to fail, which do.
- The main results:
  - look-ahead reaches the **lowest possible latency**, and the just-in-time version also the
    **lowest possible memory** (Theorems 1–2);
  - on a chain, d restores become one;
  - one price ratio κ decides both *when* to trigger and *whether* to restore a branch early
    (Theorems 3–4);
  - skipping look-ahead when the workflow is warm costs nothing (Lemma 5);
  - keep-alive needs **77×** more memory for a workflow called once a minute (Theorem 6);
  - scrubbed warm-up gives the *same* JIT state when it keeps the code paths (Proposition 7);
  - depth should be measured in work, not requests (Proposition 8);
  - **Theorem 7 (the unified one):** chooses snapshot depth and restore timing together on any
    series-parallel workflow, and shows when your `MODEL.md` algorithm is still right.

**Scripts for the CRIU box**
- `ideas/criu-box/`: x1 (restore times per tier), **x2 (parallel restores, the go/no-go)**, x3
  (warm-up lost by a real restore), x4 (the priming comparison with real restores). Written but
  **not run**.

**Pull requests**
- #1 and #2 merged. #3 (Theorem 7 and this report) is open.

**Mistakes caught and fixed** (kept visible, as your standing rules ask)
- Two simulator bugs, both caught by the control checks:
  - parallel sibling stages stole each other's restored sandbox;
  - random seeds were not reproducible between runs.
- One wrong check: randomised simulator results were compared with an exact bound. Fixed by a
  new corollary: parallel restores cost the *slowest* restore, not the average.
- An unreadable figure (bars next to the wrong labels) was replaced.
- 15 Java runs that overlapped other CPU work were deleted and redone.

---

## 6. Main numbers at a glance

| what | number | source |
|---|---|---|
| cold vs warm, 3-stage Spring Boot workflow (1 vCPU) | 12.1 s vs 35 ms | your exp15 |
| one Spring Boot restore under CPU limits | 0.64–9.05 s | your exp11/12 |
| restore-on-demand vs look-ahead, 3 / 5 / 8-stage Java chain (sim) | 2.20 / 3.67 / 5.89 s vs 0.94 / 1.12 / 1.37 s | `ideas/sim` e1 |
| cold workflows on the Azure trace, mean / p99 | 2.34 / 6.20 s → **0.82 / 1.36 s**, same memory | `ideas/sim` e4 |
| scrubbed vs real warm-up | 0.98–1.11× (no measurable difference) | exp-a, n = 20 |
| identical code paths, scrubbed vs real | 100% and 98.7% (fps2); naive scrub 0% | `Sig.java` |
| theorems checked by computer | 44/44 | `theory/verify_dag.py` |

---

## 7. What is not done yet, and what can still go wrong

1. **x2 on the S0 box**: if restores in parallel slow each other badly, Innovation 1 loses most
   of its gain (the theory gives the exact loss).
2. **x3 and x4**: repeat the warm-up results with real CRaC restores.
3. **Build it in OpenWhisk** (section 4) and measure real workflows (SeBS-Flow).
4. **Theory gaps:** nested if/else branches are not fully covered (Theorem 4 treats one branch
   at a time), and DAGs that are not series-parallel have no exact algorithm yet.
5. **Read Pronghorn's full paper** before writing the novelty chapter (only its abstract was
   reachable from here).

---

## 8. Small glossary

- **Cold start**: the delay when a function starts from nothing.
- **Snapshot / checkpoint**: a saved copy of a running process, restored later.
- **CRIU**: the Linux tool that saves and restores processes.
- **CRaC**: a Java feature that uses CRIU and lets the program prepare for it.
- **DAG**: the workflow graph of stages.
- **Critical path**: the longest chain of work in the DAG; it sets the total time.
- **Depth K**: how many warm-up requests (really, how much warm-up work) ran before the snapshot.
- **Priming**: running warm-up requests before taking the snapshot.
- **Restore-on-demand**: today's way: restore a stage when its request arrives.
- **Look-ahead restore**: our way: restore later stages while earlier ones run.
- **Scrubbing**: replacing personal values with random ones of the same format.
- **κ (kappa)**: memory price ÷ (memory price + latency price); one knob that sets how early to
  restore and when to restore a branch early.
