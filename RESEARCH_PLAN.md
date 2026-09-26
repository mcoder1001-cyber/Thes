# Research Plan v4 — the measurement thesis

**Thesis:** Improving function runtime environment in FaaS to reduce workflow cold start
**Degree:** MSc, Amirkabir University of Technology · 18 months
**Data:** `experiments/RESULTS.md`

---

## 0. Why v4 exists

v3 planned a *mechanism* thesis: build deep-but-safe snapshots, verify safety by
cross-run page agreement. **Experiment 4 killed the verification method** — it failed
its own control (1.2% agreement on byte-identical input) because a real framework's
heap is not reproducible at page granularity, and because byte agreement measures
reproducibility rather than safety in the first place.

What survived the four pilots is the *measurement* work, and it is stronger than the
mechanism work ever was. v4 builds the thesis on that.

| v3 | v4 |
|---|---|
| Build deep-but-safe snapshots | **Characterize where cold-start cost lives and what determines snapshot headroom** |
| Cross-run agreement as safety proof | **Retracted** |
| Contribution = a system | **Contribution = a characterization + a predictive model + actionable guidance** |
| Needs CRIU, needs x86 Linux | **Runs on the existing laptop** |

---

## 1. The thesis in plain language

Everyone agrees FaaS cold starts are bad and that snapshots help. But **the published
work measures the wrong workloads.** Papers evaluate small handlers, on machines with
plenty of CPU, one function at a time.

Real FaaS is the opposite: **heavy frameworks, one vCPU, chained into workflows.**

We measured all three factors and each one changes the answer by an order of magnitude:

* a real framework instead of a toy handler multiplies the warm-up cost by **~20×**
* dropping from 4 vCPU to 1 vCPU **doubles it again**
* every extra workflow stage **adds the whole cost over again**, linearly

So the headroom available to snapshot techniques is **systematically understated by
the standard evaluation setup** — and it is largest exactly where it has been least
measured.

This thesis measures that properly, models it, and says when each snapshot strategy
is worth using.

---

## 2. The claim

> Cold-start cost in FaaS is dominated by three factors that the literature holds
> fixed at unrepresentative values: framework weight, CPU allocation, and workflow
> depth. This thesis quantifies each, shows their interaction, and derives when a
> cheap shallow snapshot suffices and when the extra cost of a deep one is justified.

**Three sub-claims, each already partly measured:**

| | Claim | Evidence so far |
|---|---|---|
| **(a)** | Framework weight dominates: toy handlers understate warm-up ~20× | exp 3 vs 3b: 19 ms → 165 ms |
| **(b)** | The prize *grows* as CPU shrinks — biggest where FaaS actually runs | exp 3b: 190 ms @4 vCPU → 370 ms @1 vCPU |
| **(c)** | Workflow depth multiplies everything linearly | exp 2: ~550 ms/stage, no amortization |

**(b) is the most interesting and appears unreported.** Total JIT compilation is
2.5–4 s of CPU work; with spare cores it hides on background threads, with one core
it lands on the critical path. Lab machines have spare cores. Lambda does not.

---

## 3. What is already measured

Pilots only (n=1–2). Direction, not evidence.

| Finding | Value | Experiment |
|---|---|---|
| Cascade share of end-to-end | **97.5–98%** | exp 2 |
| Cascade linearity | ~550 ms/stage, no overlap | exp 2 |
| Cold/warm ratio | **48×** | exp 2 |
| Warm-up state: CPython vs JVM | 1.6% vs **26%** of process | exp 1, 1b |
| Warm-up cost: toy vs framework | 19 ms → **165 ms** | exp 3, 3b |
| Warm-up cost vs vCPU | 190 ms @4 → **370 ms @1** | exp 3b |
| Spring Boot cold start @1 vCPU | **2.9 s** (2510 ms init + 370 ms warm-up) | exp 3b |
| JIT code cache is run-specific | 318/330 pages differ | exp 1b |

**Headline, if it holds up at scale:** a 3-stage Spring Boot workflow at 1 vCPU costs
**~8.7 s cold against ~35 ms warm** — of which ~7.5 s is removable by a shallow
snapshot and ~1.1 s only by a deep one.

---

## 4. The core of the work: a factorial measurement study

Replace one-off experiments with a systematic design. This *is* the thesis.

| Factor | Levels | What it tests |
|---|---|---|
| **Runtime** | CPython, Node/V8, JVM, Go | does a JIT exist? how much warm-up is there to capture? |
| **Framework weight** | none · library-only (Jackson) · Spring Boot · Spring + JPA | claim (a) |
| **vCPU** | 0.25, 0.5, 1, 2, 4 | claim (b) — matches Lambda's memory→vCPU scaling |
| **Memory** | 256 MB … 2 GB | the knob users actually control |
| **Workflow depth** | 1, 3, 5, 8 stages | claim (c) |
| **Snapshot point** | none (A+B+C) · at init (B) · after warm-up (E) | headroom per strategy |
| **Container reuse** | 1, 5, 20, 50 requests | how much of the prize is collected |

**Repetitions: ≥20 per cell.** Report distributions and p95/p99, never single numbers.
Full crossing is too large — use a screening design first, then fill in the cells
that matter.

### Outputs

1. **A characterization.** Where cold-start cost lives, per factor, with confidence
   intervals.
2. **A predictive model.** Given (runtime, framework, vCPU, depth), predict cold-start
   cost and the headroom each snapshot point removes. Fit and validate on held-out
   configurations.
3. **Actionable guidance.** *"A shallow snapshot is enough when X; a deep one is only
   worth its cost when Y."* This is what makes it more than a pile of numbers.

---

## 4b. Decisions taken (session of 2026-09-23)

### Generality: the method is universal, the answer is a classification

The thesis must not read as "a study of Java". It does not have to, because the
**method** applies to every runtime and only the **answer** differs:

* **Method (universal).** For any runtime, measure the three costs A / B / C. The
  `exp5` harness already does this for seven runtimes with one command.
* **Answer (a two-class result).** Once B is measured, runtimes sort themselves:

| class | B at 1 vCPU | policy |
|---|---|---|
| **heavy-compilation** (HotSpot JVM) | 195–607 ms | a deep snapshot is worth the complexity |
| **everything else** (.NET, V8, Go, CPython) | 0–19 ms | snapshot at init and stop |

So the thesis states: *here is a general method for deciding snapshot policy; applied
across seven runtimes it yields two policies, separated by a measurable threshold in
total compilation work (~100 ms).* **Language dependence becomes a result, not a
limitation.**

### Where snapshot depth currently stands

**Known.** For Spring Boot at 1 vCPU, cold start ≈ 2.9 s:
* a snapshot at **B** (after init, before any request) removes **2510 ms — 87%**
* a snapshot at **E** (after processing requests) removes **370 ms more — 13%**

Practical answer today: **take the snapshot at B.** That is where nearly all the value
is, it is safe, and it is what SnapStart already does.

**Not known — and this is the open question worth owning.** "Point E" is not a single
place. Warm-up converges only after **31–190 invocations** depending on workload, yet
Prebaking snapshots after **one** request and SnapStart after **zero**. Nobody has
asked **how many warm-up requests should be processed before checkpointing.** That
question is general across languages, measurable on the existing harness, and
unanswered. It is now the primary experiment (§5, depth sweep).

### ORION's role — a supplier, not a competitor

Not dead, and not a rival. Three concrete uses:

1. **It answers "which functions are worth snapshotting."** Its performance model —
   latency as a *distribution*, **convolved** for functions in series and **max**-ed
   for functions in parallel, with a correlation correction — identifies the straggler
   and the critical path. Speeding up a non-bottleneck function gains nothing, and
   this is how you know which is which. **Reimplement the model (~100 lines of numpy)
   and cite them; do not port their AWS codebase.**
2. **Prewarming baseline** — published, OSDI'22, open source.
3. **Its limits are the opening.** Zero mentions of "snapshot" (they prewarm by
   cold-booting early) and zero of "branch" (they cannot handle DAGs whose path
   depends on request content).

Their own prewarming method is a greedy search: start all delays at zero, repeatedly
add 100 ms to whichever stage improves utilization without hurting end-to-end latency.

### Novelty check — partially done

**arXiv 2410.06145, "Serverless Cold Starts and Where to Find Them": complementary,
not competing.** It is a trace analysis of **85 billion requests and 11.9 million cold
starts** from Huawei's platform across five data centres, studying cold starts from the
*platform* side — pod allocation, dependency deployment, scheduling, regional variation
(*"cold starts in Region 1 take up to 7 seconds"*). **It does not study JIT warm-up,
CPU-allocation effects, framework weight, or snapshots.** Cite its 7-second figure as
motivation. Still to check: *automatic priming*, *priming depth*, *snapshot depth*.

## 5. Supporting studies

**Container reuse from the Azure traces.** How many requests does a container serve
before reclamation? That determines how much of the warm-up prize is ever collected —
exp 3b showed the answer ranges from 85 ms (one request) to 143 ms (fifty). **This
finally gives the Azure traces cited in the proposal a concrete job.**

**Real workflows, not synthetic chains.** Port the study to SeBS-Flow (EuroSys'25,
the first serverless *workflow* benchmark suite) so the depth results come from real
application DAGs.

**Validation against published numbers.** AWS reports Spring Boot 6.1 s → 1.4 s with
SnapStart. If the model predicts that from its inputs, it is calibrated; if not, say
why.

---

## 5b. The snapshot phase — not yet started

Everything so far is **measurement**. We have never built or restored a snapshot. This
section is the plan for doing so, and it starts from a measured position rather than a
guess. Full reasoning in `SYNTHESIS.md`.

### What the measurements already decided for us

| decision | settled by |
|---|---|
| Target the **JVM** | CPython/Go have no warm-up to capture (B=0); .NET's is ~18 ms |
| **Depth matters, and differs by runtime** | K=1 captures 100% (.NET) vs 4–38% (JVM) |
| The prize is **~19% of compilation wall-time** | `B ≈ 0.185·W`, MAPE 49% |
| **Low vCPU is where it pays** | the vCPU cliff: **13–35×** from 4 → 0.25 vCPU (exp14, server x86, n=20). The 33–111× figure was an Apple Silicon artifact — see RESULTS.md exp14 |
| Depth is **cheap in image size** | +1.3 MB buys +350 ms |
| Depth is **bounded by correctness** | Brooker et al.: RNG/UUID/nonce reuse, real TLS attacks |

### S0 — unblock the environment — ✅ **DONE 2026-09-24**

**A Linux box is provisioned and every blocker below is cleared.** Full details in
`experiments/vm-setup/REMOTE-BOX.md`. Summary:

* **The machine:** 8 × Xeon Gold 6248R, native x86_64, 31 GB RAM, Ubuntu 24.04,
  **zero CPU steal** (so the vCPU-cliff measurements are valid on it).
* **CRIU 4.2.1** built from source (Ubuntu 24.04 dropped the `criu` package).
  `criu-smoketest.sh` now passes **6/6, including level 3 — checkpoint and restore of
  a JIT-warmed JVM.** That was the designated go/no-go test for the whole snapshot
  phase.
* **Zulu CRaC JDK 21** installed; first real restore measurements are exp11.
* **OpenWhisk** built from `master` and verified: node 5/5, python 5/5, 3-stage
  sequence, **java 5/5 on stock OpenWhisk with no patch**.
* **The "Java is structurally broken" conclusion below is RETRACTED.** It was never an
  Apple Silicon problem. OpenWhisk sends `/init` ~150 ms after `docker run`; the action
  proxy binds at 14 ms (python) / 318 ms (java) / 451 ms (node) **under QEMU**, and
  Docker Desktop's macOS port forwarder answers an unbound port with `RST` instead of
  `ECONNREFUSED`, which OpenWhisk's retry path does not cover. Both factors are needed.
  On the Linux box java binds in 46 ms and stock OpenWhisk works. A one-line macOS
  workaround is in `experiments/exp10-workflow-depth/openwhisk-socket-retry.patch`.

The original text is kept below for the record.

### S0 (original) — unblock the environment (prerequisite)
* **An x86_64 Linux machine.** Hard requirement, two reasons: CRIU has no arm64 Ubuntu
  package, and all OpenWhisk runtime images are amd64 (emulated here). Lab machine or
  a ~$5/month VPS.
* Validate with `experiments/vm-setup/criu-smoketest.sh` — level 3 (checkpoint and
  restore a JIT-warmed JVM) is the one that decides whether the phase can proceed.
* Fallback if raw CRIU fights the JVM: a **CRaC-enabled JDK** (Azul Zulu CRaC,
  BellSoft Liberica CRaC), which bundles a CRIU engine and does the JVM-side
  coordination. This is the supported path and should probably be first choice.
* **~~Java on OpenWhisk is confirmed broken on this host~~ — RETRACTED 2026-09-24.
  Java works here. exp7 and S5 are unblocked; only CRIU still needs Linux.**
  The failure was a **startup race**, not an architecture problem: OpenWhisk sends
  `/init` ~150 ms after `docker run` returns, and the action proxy binds its socket at
  14 ms (python), 318 ms (java), 451 ms (nodejs) under emulation. OpenWhisk's container
  client retries only on ECONNREFUSED; Docker Desktop for macOS *resets* the connection
  instead of refusing it, so the retry never fires and a lost race becomes permanent.
  One-line fix in `ApacheBlockingContainerClient.scala`
  (`experiments/exp10-workflow-depth/openwhisk-socket-retry.patch`): after rebuilding,
  java and node both go 0/5 → 5/5 cold starts with the prewarm pool disabled entirely.
  Full write-up in `RESULTS.md`, Experiment 10. **Rebuild the OpenWhisk checkout after
  any `git pull` or the patch is lost.**
* **Separately, this OpenWhisk build has an invoker memory budget of 1024 MB total**
  (`Cannot create prewarm container due to reach the invoker memory limit: 1024` in the
  log). Across a long session with many actions/containers accumulated, this silently
  exhausts and causes *unrelated* actions — including multi-stage sequences — to fail
  with the same generic `"did not initialize"` message that the Java bug also produces.
  **The two failure modes look identical from the `wsk` CLI and are easy to conflate**
  (this cost real debugging time — don't repeat it). Distinguish them by checking the
  invoker log directly: memory-limit exhaustion logs the WARN above; the Java bug logs
  the `ConnectionError`/broken-pipe line. Fix for the memory issue: restart OpenWhisk to
  clear accumulated container state, and keep an eye on total concurrent memory
  (`--memory` across all simultaneously-live actions) during any large sweep.

### S1 — reproduce the two published snapshot points
Build **K=0** (SnapStart's point: after init, before any request) and **K=1**
(Prebaking's point: after one request) for the Spring Boot workload. Measure
restore-to-first-response at 0.25 / 1 / 4 vCPU.
**Exit:** our predicted B-capture (0% and ~32%) matches measured restore latency.
This validates the whole `captured(K)` model, which is currently derived from warm-up
curves rather than from real restores.

### S2 — sweep the depth
Snapshot at **K = 0, 1, 5, 20, 50, 100, 200** and measure restore-to-first-response,
image size, and restore latency for each.
**Exit:** an empirical depth curve to set against the derived one. **This is the
thesis's central snapshot result** — the answer to the proposal's own question.

### S3 — the safety boundary
For each K, check what request-specific state the image carries: RNG state, UUIDs,
timestamps, live sockets, credentials. Use CRaC's `beforeCheckpoint()` hooks (the
resource owner resets its own state) and verify what the hooks miss.
**Exit:** a stated maximum safe K, and a measurement of how much of the published
priming guidance actually holds.
**Note:** do **not** revive cross-run page agreement as the verification method —
exp 4 failed its control, and byte agreement measures reproducibility, not safety.

### S4 — the cliff, with snapshots
Re-run the vCPU sweep with snapshots in place. The prediction: **snapshots flatten the
cliff**, because restoring a warmed image skips the compilation burst that CFS quota
throttling punishes.
**Exit:** if confirmed, the headline becomes *"deep snapshots matter most exactly where
FaaS runs"* — which is a far stronger statement than a latency number.

### S5 — the workflow
Chain 3/5/8 Java stages on OpenWhisk (`exp7`, already built) with and without
snapshots. Use ORION's convolve/max model to identify which stage is the straggler,
and snapshot only those.
**Exit:** workflow depth measured rather than projected, and a per-stage policy.

### S6 — the one-flag alternative
Test `-XX:TieredStopAtLevel=3` (stop at C1) and bounded compiler threads at low vCPU.
The Kubernetes community claims this trades ~5% peak throughput for faster warm-up.
**Exit:** an honest comparison — if a JVM flag recovers most of the benefit, say so.
A thesis that reports the cheap alternative is more credible, not less.

**Ordering rationale:** S1 validates the model before S2 spends time on the sweep; S3
bounds what S2 can use; S4 is where the thesis's two halves join; S5 and S6 are upside.

## 6. Phases

| Phase | Months | Work | Exit |
|---|---|---|---|
| **0 — Novelty check** | 1 | §7. Read the near-neighbours properly | confirmed novel, or reframed |
| **1 — Harness** | 1–3 | Generalize exp 2/3b into one parameterized runner; automate the factor sweep | one command produces a full cell |
| **2 — Screening** | 3–5 | Coarse sweep over all factors, few reps; find which matter | ranked factor effects |
| **3 — Full study** | 5–10 | ≥20 reps on the cells that matter; distributions, tails | the characterization |
| **4 — Model** | 9–13 | Fit and validate the predictive model; calibrate against AWS figures | model + error bars |
| **5 — Workflows** | 11–15 | SeBS-Flow, Azure reuse distribution, OpenWhisk end-to-end | depth results on real DAGs |
| **6 — Writing** | 14–18 | Thesis + paper | submitted |

**Not blocked on CRIU or on x86 Linux.** Everything runs on the current laptop.
A bare-metal x86 check in Phase 3 would strengthen the absolute numbers; the *trends*
do not depend on it.

---

## 7. Novelty check — do this first

**Priority read:** *"Serverless Cold Starts and Where to Find Them"* (arXiv 2410.06145).
The title suggests direct overlap. **Read it before anything else** and position against
it explicitly.

Also: *"Characterizing FaaS Workflows on Public Clouds"* (arXiv 2509.23013);
*Serverless in the Wild* (Shahrad et al., ATC'20 — already cited in the proposal, and
the model for this kind of thesis); REAP (ASPLOS'21); FaaSnap; Medes; SOCK.

Search terms: *cold start characterization*, *FaaS performance measurement study*,
*JIT warm-up serverless*, *vCPU scaling cold start*, *snapshot headroom*.

**The specific thing to check:** has anyone reported that **JIT warm-up cost rises as
vCPU falls**? That is the most novel-looking result in hand.

---

## 8. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| A recent measurement paper already covers this | **High** | Phase 0, week one. Differentiate on the vCPU-scaling and workflow-depth axes |
| "Only a measurement study" — thin for a thesis | Medium | The **model** and the **guidance** are the contribution; measurement alone is not |
| Docker-on-macOS numbers not credible | Medium | Report trends as primary, absolutes as indicative; bare-metal x86 check in Phase 3 |
| Factor space too large | Medium | Screening design first (Phase 2), then fill selectively |
| Findings are JVM-specific | Low | That *is* a finding — state the scope honestly |

---

## 9. Standing rules

1. **Always run a control.** Exp 4 was caught only because `W0_IDENTICAL` existed.
   Every experiment gets a condition whose answer is known in advance.
2. n≥20 per cell. Report distributions and tails, never single numbers.
3. Report trends as the result; absolute milliseconds are platform-dependent.
4. **Vary one factor at a time** before interpreting interactions.
5. Negative and retracted results stay in `RESULTS.md`. Exp 4 stays visible.
6. Every claim traces to an experiment, or is labelled conjecture.
7. When a prediction is falsified, say so plainly and move on. It has happened twice
   already and both times the data was more useful than the prediction.
