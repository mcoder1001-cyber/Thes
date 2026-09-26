# Synthesis — what the literature gives us, and the idea it adds up to

Written 2026-09-24 after reading the downloaded papers in `baselines/papers/`.
Companion to `RESULTS.md` (our measurements) and `READING_LIST.md` (the catalogue).

Purpose: a defensible story for the advisor. Not a novelty claim — overlap is fine.

---

## 1. The idea, in one page

**The problem, from production.** Fork in the Road (OSDI '25, Ant Group, 18 months in
production) decomposes cold start and names three overlooked sources. Their third is
ours, word for word:

> *"Just-In-Time (JIT) compilation or language runtime-specific code loading can
> significantly affect startup latency, especially when dealing with complex
> application frameworks or extensive dependencies (e.g., Spring). User code
> initialization latency depends on user-specific behaviors. **This makes it
> challenging for current optimization methods, such as provisioning and SnapStart,
> to balance cost and efficiency.**"*

**An OSDI production paper names our problem and says SnapStart cannot balance it.**
They then do not measure it — they optimize the platform's control path instead. That
is the gap, stated by someone else, in a top venue.

**What we measured.** Three costs, per runtime, across CPU allocations:

* **A** = start + load + framework init — removed by a snapshot at init (SnapStart)
* **B** = first-call + JIT warm-up — removed only by a *deeper* snapshot
* **C** = steady state — irreducible

**What we found.** Two things, both measured at n=20 over 700 runs:

1. **The vCPU cliff.** B rises **13–35×** as vCPU falls from 4 to 0.25 on the JVM,
   measured on server-class x86 (exp14, n=20). An earlier Apple Silicon measurement
   gave 33–111×; that ratio was inflated by the laptop's unusually fast 4-vCPU
   baseline and is retracted. **The model `B ≈ 0.18·W` reproduced across both
   machines (φ = 0.185 vs 0.177) and is the claim to lead with.**
   .NET is flat from 4→1 but shows 5.4× at 0.25. Go and CPython show nothing. The
   governing quantity is **total compilation work relative to available CPU**, not
   "does the runtime have a JIT".
2. **Snapshot depth is unswept — and depth pays, measured with real restores.**
   SnapStart checkpoints after 0 requests, Prebaking after 1. On a 3-stage Spring Boot
   workflow with real CRaC snapshots (exp15): cold **12.1 s**, SnapStart's point
   **1.47 s**, depth K=50 **0.225 s** — **54× against cold, and 6.5× beyond
   SnapStart's checkpoint point**, with byte-identical output. Depth pays ~2× more at
   workflow level than for a single function (exp12b: 2.3–3.9×), because a chain
   multiplies the per-stage saving.
3. **Priming needs no script.** In a workflow, stage *i+1* can be primed with stage
   *i*'s real output — the DAG supplies its own priming workload. That is the one
   thing a single-function tool like SnapStart or CRaC cannot do.

**The synthesis.** Cold start is not one number, and the snapshot policy that is right
for one runtime is wrong for another. Given (runtime, framework weight, vCPU), the
three costs are predictable — `B ≈ 0.185·W` — and from them the right snapshot depth
follows. **The method is general; the answer is a four-way runtime classification.**

---

## 2. The vCPU cliff — what explains it, and what is already known

**The mechanism is CFS quota throttling.** The Linux scheduler divides time into
~100 ms windows; a 0.25-CPU limit grants ~25 ms of runtime per window, after which
**every thread in the container is frozen until the window rolls over.** JIT
compilation is a CPU-heavy burst. Against a quota tuned for steady state, that burst
hits the wall repeatedly. This explains why the effect is *super-linear*: it is not
simple time-slicing, it is periodic hard freezing.

**It is known as practitioner folklore, not as measured science.** The
JVM-on-Kubernetes community states it plainly — *"Java warmup issues in Kubernetes are
almost always a mismatch between the JVM's CPU-hungry startup and a CPU quota tuned for
steady state"* — and has mitigations: `-XX:TieredStopAtLevel=3` (stop at C1, warms
faster, ~5% lower peak throughput), bounded compiler threads, burstable QoS.

**So what is ours:** nobody has (a) measured it across runtimes with a controlled
factor design, (b) reduced it to a model, or (c) connected it to *snapshot policy*.
That is a perfectly good MSc contribution and an honest one. Say "we quantify and
model a known practitioner effect, and derive its consequence for snapshotting" — not
"we discovered it".

**And it gives us a free experiment:** does `-XX:TieredStopAtLevel=3` flatten the
cliff? If yes, that is an actionable finding with a one-flag fix.

---

## 3. What each paper is *for*

### Motivation — why the problem matters
| paper | what we take |
|---|---|
| **Fork in the Road** (OSDI '25) 📄 | The quote above. Production validation that JIT + framework weight is unsolved and that SnapStart can't balance it. **Our single best motivation citation.** |
| **Serverless Cold Starts and Where to Find Them** (EuroSys '25) 📄 | 85B requests, 11.9M cold starts at Huawei. *"Region 1 cold starts take up to 7 s."* Scale and severity, from production. Platform-side only — no runtime warm-up. |
| **Characterizing FaaS Workflows** (2025) 📄 | 25 workflows, 139k invocations, 3 platforms. Workflow-level cold-start scaling. **The closest methodological sibling to our factor study.** |

### Method — how to run a measurement thesis
| paper | what we take |
|---|---|
| **Serverless in the Wild** (ATC '20) | The template: a measurement paper can be a top-tier contribution. Also the Azure traces our proposal cites. |
| **The High Cost of Keeping Warm** (2025) 📄 | Instance churn burns **10–40% of CPU cycles**; scaling policies allocate **2–10× more memory than used**. **This is our cost baseline** — it prices the alternative to snapshotting (keep-alive) and lets us argue depth is cheap by comparison. |
| **Characterizing FaaS Workflows** 📄 | Factor-design precedent at workflow level. |

### Mechanism — what to compare our model against
| paper | what we take |
|---|---|
| **REAP** (ASPLOS '21) 📄 | Working-set record-and-prefetch. **The state of the art on snapshot *content*** — and it optimizes *what is prefetched at restore*, not *when the snapshot is taken*. Our depth question sits beside it, not on top of it. Also gives us vHive. |
| **Spice / Taming Cold Starts** (2025) 📄 | Argues OS limits, not storage, bound restore speed; 14.9× over process-based systems. **Violates our C1 (no OS changes)** — cite as the alternative we deliberately do not take, and as evidence restore cost is not fundamental. |
| **Restoring Uniqueness in MicroVM Snapshots** (AWS) 📄 | The safety ceiling on depth: RNG/UUID/nonce reuse, real TLS attacks. **Cite whenever we discuss how deep is safe.** |
| **Prebaking** (FGCS '24) | **Our K=1 baseline.** Exp 6 shows its one-request checkpoint captures 32% of Spring Boot's warm-up. |
| **CRaC / SnapStart priming** (practitioner) | Priming is real, industrial, and **manual**. A community guide exists (`marksailes/snapstart-priming-guide`). "Automatic priming" is a practitioner term, not a research one. |

### Workflow layer — for the depth dimension
| paper | what we take |
|---|---|
| **ORION** (OSDI '22) 📄 | **The model we borrow**: latency as a distribution, convolve for series, max for parallel, correlation-corrected. Tells us *which* function in a DAG is worth snapshotting (the straggler on the critical path). ~100 lines of numpy; cite, don't port. No snapshots, no branching. |
| **CIDRE** (ASPLOS '25) 📄 | Keep-alive under *concurrency*; speculatively chooses delayed-warm vs cold. Orthogonal axis to ours (they vary concurrency, we vary allocation). Good related work; a possible future factor. |
| **SeBS-Flow** (EuroSys '25) 📄 | The first serverless **workflow** benchmark suite. **Solves "Azure traces have no DAGs".** Use for workflow-depth experiments. |
| **MPC proactive scheduling** (2025) 📄 | Forecast-driven prewarming, −85% p90. The "predict then warm" school — the one our approach deliberately does not need. |

📄 = PDF downloaded to `baselines/papers/`

---

## 3b. Scoring the field: what to build on (added 2026-09-24)

The user asked directly: given everything read, which existing technique is actually
worth implementing — one with a clear formula/definition **or** open-source code,
against our three pillars (snapshot, cold-start, workflow)? Score = Formula (0–5) +
Code (0–5) + Fits our C1 constraint, no kernel/OS changes (0–5) + Relevance to
snapshot+workflow+cold-start jointly (0–5), out of 20. Code availability is marked
**confirmed** only where a real repo was found and its existence verified by search;
everything else is **unverified**, stated as such.

| Paper | Formula | Code | Fits C1 | Relevance | **Total** | Note |
|---|---|---|---|---|---|---|
| **ORION** (OSDI'22) | 5 — explicit CONV/MAX latency composition, BFS prewarming search | 4 — repo confirmed to exist (`icanforce/Orion-OSDI22`); **contents never verified**, clone attempts failed/interrupted | 5 | Workflow 5, cold-start 4, **snapshot 0** | **14/20** | Best on workflow structure. Zero snapshots — their own stated gap. |
| **REAP** (ASPLOS'21) | 4 — record-and-prefetch working set | 5 — confirmed, part of vHive, ~4.5K Go LoC | 3 — "no kernel changes" claimed but touches the Firecracker hypervisor | Snapshot 5, cold-start 5, **workflow 0** | **12/20** | Best on snapshot content. Single-function only. |
| **Prebaking** | 3 — checkpoint-after-N=1, mostly empirical, no optimization formula | 2 — built on CRIU (open), their own OpenFaaS integration **never verified as public** | 5 — exactly matches the proposal's tool choice | Snapshot 5, cold-start 5, **workflow 0** | **10/20** | Closest fit to the original proposal. Our exp6 shows K=1 is wrong for the JVM (4–38% captured). |
| **Function Fusion** (Lee et al.) | 5 — explicit workflow response-time model + fusion algorithm | 1 — no evidence found | 5 | Workflow 5, cold-start 4, **snapshot 0** | **10/20** | Strong formula, orthogonal axis to snapshots (see the "honest accounting" note in the fusion discussion — combining naively double-counts). |
| **Zuk & Rzadca scheduling** | 5 — formal knapsack + dependency + setup-time model | 1 — no evidence found | 5 | Workflow 5, cold-start 4, snapshot 0 | **10/20** | Most rigorous formulation in the whole corpus. No code, no snapshots. |
| **Xanadu** | 4 — speculative JIT provisioning over DAG | 1 — no evidence found | 4 | Workflow 5, cold-start 5, **snapshot 0** | **10/20** | Cold-boots speculatively; the mechanism our depth work is meant to improve on. |
| **CIDRE** (ASPLOS'25) | 4 — concurrency-informed eviction policy | 1 — unverified | 5 | Workflow 1 (concurrency ≠ DAG structure), cold-start 5, snapshot 1 | **8/20** | Real technique, wrong axis for us. |
| **Fork in the Road / AFaaS** | 2 — described, not a portable formula | 0 — proprietary, Ant Group internal | 2 — FRI replaces OCI; invasive | Cold-start 5, snapshot 3, workflow 1 | **7/20** | Can't be implemented by us at all. Motivation only (see §2). |
| **Spice / OS Co-Design** | 3 | unverified | **0 — requires new OS primitives, directly violates C1** | Snapshot 5, cold-start 5, workflow 0 | **6/20** | Out of scope by our own constraint. |
| **PCPM** | 3 | **0 — confirmed no public repo** | 4 | Cold-start 4, snapshot 2, workflow 0 | **5/20** | Already dropped in v2 of the plan. |

**What the table says structurally.** Nothing scores well on all three pillars, and
that split is clean: papers with a real workflow formula never touch snapshots
(ORION, Fusion, Zuk&Rzadca, Xanadu); papers with real snapshot mechanics never touch
workflow structure (REAP, Prebaking, Spice). **That gap is the thesis's actual space**,
not a sign the search was insufficient.

**Recommendation, unchanged from what's already in §5b of the plan but now justified
by the table:** don't adopt one paper wholesale. Take **ORION's CONV/MAX latency
composition** (highest-scoring workflow formula, already cited as the "which function
is worth snapshotting" layer) as the workflow half, and **Prebaking's CRIU mechanism**
(highest-scoring fit to our own constraints, already what the approved proposal names)
as the snapshot half. **REAP is the strongest fallback** if the snapshot phase needs to
go beyond simple process checkpointing — it is the only fully-confirmed-open-source,
C1-adjacent, formula-bearing option among the pure snapshot papers.

## 3c. Where the formal contribution now sits (added 2026-09-24)

§3b concluded that no paper covers snapshot + workflow + cold-start jointly: papers
with a workflow formula never touch snapshots (ORION, Fusion, Zuk & Rzadca, Xanadu),
papers with snapshot mechanics never touch DAG structure (REAP, Prebaking, Spice).

`theory/MODEL.md` now occupies that gap with a formal model, and `theory/verify.py`
checks every claim computationally (14/15, the failure being a documented refutation).
It reduces **snapshot placement and depth over a workflow DAG** to a multiple-choice
knapsack, gives exact DPs for chains and series-parallel DAGs, and proves a capacity
result showing keep-alive cannot substitute for snapshots in deep workflows.

**Crucially, the model is language-independent**: it consumes the per-function profile
`(A_v, e_v(·), s_v(·), r_v(·), m_v)` as input and knows nothing about HotSpot or V8.
That demotes the vCPU-cliff chapter from headline to *calibration*, which is the right
place for a result that only applies to one runtime — and it is what makes the thesis
answer the proposal's actual question rather than a narrower one.

Three claims were **refuted** in the process and are kept visible: submodularity of
latency reduction on DAGs, convexity preservation under parallel composition, and
Lemma 1 on raw measured curves.

## 4. The story for the advisor

1. **The problem is real and production-validated.** Ant Group (OSDI '25) and Huawei
   (EuroSys '25) both report cold starts of seconds at scale; Ant explicitly names
   JIT + framework init as unsolved.
2. **We measured it properly.** 700 runs, 7 runtimes, 5 CPU levels, n=20. Three-way
   cost decomposition. Nobody has this table.
3. **We found a cliff nobody has quantified.** 13–35× on the JVM (server x86), with a mechanism
   (CFS quota throttling) and a model (`B ≈ 0.185·W`, one constant across four
   runtimes spanning 100× in compilation work).
4. **It has a direct consequence for snapshots.** The right snapshot depth differs by
   two orders of magnitude between runtimes — and the published points (SnapStart's 0,
   Prebaking's 1) are right for some and wrong for others.
5. **So the snapshot phase is not speculative.** It is the obvious next step from a
   measured starting point, with the decision rule already derived.

That is a coherent arc: production problem → controlled measurement → mechanism →
model → actionable snapshot policy.
