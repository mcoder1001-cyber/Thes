# Snapshots × DAGs: what a workflow knows that a single function does not

Written 2026-09-26 after reading `RESEARCH_PLAN.md`, `SYNTHESIS.md`, `READING_LIST.md`,
`HANDOFF.md`, `theory/MODEL.md`, `theory/verify.py` and the approved proposal
(`Proposal_Final2.pdf`). `experiments/` (RESULTS.md, raw curves) is **not in this repository**,
so every number quoted from the thesis's own experiments comes from the documents above.

Everything below is backed by one of three things, tagged the same way as `MODEL.md`:
**[measured]** a real JVM run in this session, **[simulated]** `sim/dagsim.py` driven by the
thesis's own measured parameters and the Azure 2021 trace, **[protocol]** an experiment
written for the CRIU box but not yet run (`criu-box/`, see §6 for why).

---

## 0. Verdict

**You can make it; the topic does not need to change. One claim does.**

* **The claim that must go.** `RESEARCH_PLAN.md` §4b and `READING_LIST.md` say nobody has
  asked *how many warm-up requests to process before checkpointing*, and call it "the thing
  to protect." **Pronghorn (EuroSys '24)** does exactly this: a snapshot orchestrator
  that "monitors function performance and decides when to take a snapshot and which snapshot
  to use", evaluated with OpenJDK 17 + CRIU and PyPy. Its motivation sentence is the
  thesis's own: runtimes "can take up to thousands of invocations to fully optimize a
  single function." **Fireworks (EuroSys '22)** already snapshots *after* JIT
  compilation. JDK 25's **JEP 515** (AOT method profiling) is a no-snapshot alternative
  for the JVM warm-up. Depth-as-novelty is gone. Depth-as-*calibration* survives, which is
  where `MODEL.md` §0 already moved it.
* **The space that is open.** Every snapshot system we found is **single-function**
  (SnapStart, Prebaking, Pronghorn, Fireworks, REAP, FaaSnap, Snapipeline, Faast). Every
  **DAG-aware** cold-start system we found uses **cold boots or keep-alive** (Xanadu, ORION,
  Aquatope, CIDRE). The nearest exception is Mitosis (OSDI '23), whose remote *fork* of a
  running instance moves state between workflow functions. That is a live parent, not a
  snapshot restored ahead of need, but it has to be discussed. `SYNTHESIS.md` §3b already found this
  split. The ideas below sit in it: **four things a workflow orchestrator knows that a
  single-function snapshot system cannot**, and a mechanism for each.

| what the DAG knows | idea | evidence | verdict |
|---|---|---|---|
| **when** each downstream stage will be needed | **1. Restore-ahead**: restore all downstream stages in parallel at workflow entry | [simulated] 2.3–4.3× over restore-on-demand at depth 3–8; beats cold DAG prewarming on *both* latency and memory; trace-driven TBD | **lead idea** |
| **which branches** may run | 1b. Speculative restores on branches | [simulated] full speculation on a saga: p99 4.7 s → 1.3 s for +1.5 GB·s per invocation, less than half the memory-time of a plain cold start | part of 1 |
| **what the inputs look like** (it carries every inter-stage message) | **2. Scrubbed priming**: prime deep snapshots on format-preserving scrubs of real edge traffic, so no user data enters the image | [measured] residual warm-up 0.97–1.08× of real-traffic priming (all 8 CIs span 1), vs 1.03–1.30× for naive synthetic inputs | **strong, safety-relevant** |
| **which edges** feed a stage, and how big their messages are | 3. Coverage-aware priming (not per-edge snapshots) | [measured] light-edge priming costs 1.3–2.4× on the heavy edge, but heavy-edge priming *beats* the right edge on the light one (0.76–0.87×), and a mix with enough heavy requests beats the right edge alone (0.75–0.96×); depth should be counted in work, not requests | **a refinement, and a negative result for per-edge variants** |
| **how much slack** a stage has between restore and input | 4. Re-warm in slack | [simulated] small (1–5%) with a conservative warm-up model; needs `L(K)` from the box | **conditional on x3** |
| (not DAG) the vCPU cliff | 5. Prime on big, serve on small | [measured] same snapshot quality (0.93–0.97×, CIs span 1) at 9–10× lower priming cost, *if* the JVM is pinned to the serving CPU shape; otherwise 11–23% worse | **a practical rule, not a thesis** |

The one-sentence thesis these add up to:

> *Snapshots make a workflow's downstream stages cheap enough to start **before** they are
> needed, on **every** branch that might run, primed on **scrubbed** copies of the traffic
> the DAG already carries. Together these turn a depth-d restore cascade into one restore
> without putting user data into any image.*

It answers the proposal's own question (§5: "finding the best time to perform
checkpointing … most prior methods take the first moment of readiness"). It moves the
question from *when to checkpoint* (Pronghorn's) to *when to restore and what to prime
with* (open), and it keeps CRIU, OpenWhisk and the Azure traces in the roles the proposal
gave them.

---

## 1. Idea 1: restore-ahead along the DAG

### The observation
With snapshots, a workflow that misses keep-alive pays **one restore per stage, in
series**: stage *j* cannot be restored until its request arrives, and its request arrives
only after stage *j−1* finishes. The thesis's own numbers make the restore the dominant
term: wall-clock restore is **642–9053 ms** for Spring Boot under CPU quota (`MODEL.md`
scope note), against a warm execution of **~12 ms per stage** (exp15, 35 ms for 3
stages).

A workflow orchestrator knows at the moment the workflow is invoked every stage that may
run. It can issue `criu restore` for all of them **immediately, in parallel**, while stage 1
is still being restored. Because `r ≫ C`, "just in time" and "immediately" are the same
instant: by the time stage 1 finishes, stage 2 has been restoring for as long as stage 1.

### The result (closed form, verified)
For a chain with restore times `r_j`, residual warm-up `R_j`, steady execution `C_j`, edge
overhead `δ`:

```
restore-on-demand:  L_od = Σ_j (r_j + R_j + C_j) + (d−1)δ
restore-ahead:      L_ah = max_j [ r_j + Σ_{i≥j} (R_i + C_i) + (d−j)δ ]
equal r:            L_ah = r + Σ_i (R_i + C_i) + (d−1)δ           so  L_od − L_ah = (d−1)·r
```

Proof: stage *j* starts at `max(finish_{j−1} + δ, r_j)`; unroll. **The restore cascade
collapses to a single restore. Depth adds only warm execution.** The simulator reproduces
the closed forms exactly for d = 1…8 (control `e0`: 24/24; answers registered before the run).

### Numbers **[simulated]**, Java chain, thesis parameters (A=2510, B=370, C=12, r=650, R(K=50)=63 ms, 512 MB)

| depth | cold | restore-on-demand (SnapStart/Pronghorn per function) | DAG cold prewarm (Xanadu/ORION style) | **restore-ahead** | ahead + re-warm |
|---|---|---|---|---|---|
| 3 | 8.79 s | 2.20 s | 3.78 s | **0.94 s** | 0.91 s |
| 5 | 14.61 s | 3.67 s | 4.60 s | **1.12 s** | 1.06 s |
| 8 | 23.29 s | 5.89 s | 5.79 s | **1.37 s** | 1.30 s |

(`sim/results/e1_cascade.csv`, 200 seeds per cell with jitter.) Two comparisons matter:
* **vs. restore-on-demand**: 2.3× at depth 3, 3.3× at depth 5, 4.3× at depth 8. This is the
  gain the DAG adds on top of having snapshots at all.
* **vs. DAG-aware cold prewarming**: 4.0–4.2× at the same depths. Prewarming also collapses
  the cascade, to one cold boot `A`. But `A = 2.5 s` is paid once and `B` is paid at
  every stage. Restore-ahead pays `r` once and `R(K) ≪ B` per stage.

### Branches: speculation becomes affordable (Idea 1b) **[simulated]**
On a SeBS-Flow-style **trip-booking saga** (reserve ×3 → confirm 0.9 | compensate ×3 0.1)
and a **router** DAG (3 branches, 0.6/0.3/0.1), sweeping the speculation threshold θ
(restore a stage ahead iff P(it runs) ≥ θ), all invocations missing keep-alive:

| trip saga | mean | p99 | memory-time / invocation |
|---|---|---|---|
| no ahead-of-time starts, cold | 12.47 s | 18.43 s | 6.27 GB·s |
| restore on demand | 3.12 s | 4.68 s | 1.57 GB·s |
| restore-ahead, likely path only (θ = 0.5) | 1.24 s | 3.34 s | 1.89 GB·s |
| **restore-ahead, all branches (θ ≤ 0.08)** | **1.11 s** | **1.32 s** | 3.03 GB·s |
| cold prewarm, likely path only (θ = 0.5, Xanadu-like) | 5.13 s | 12.83 s | 7.31 GB·s |
| cold prewarm, all branches | 4.63 s | 5.05 s | 11.72 GB·s |

**Restore-ahead with full speculation holds less memory-time than a plain cold start does
(3.0 vs 6.3 GB·s), and is 11× faster.** A cold boot holds 512 MB for `A + B ≈ 2.9 s` per
stage; a restore holds it for about a second. Restores are cheap enough to speculate on the
10% compensation branch, which is where the saga's p99 lives (3.34 s → 1.32 s for +1.1
GB·s). The router DAG shows the same shape (`sim/results/e2_speculation.csv`,
`e2_speculation.png`).

### Under real traffic **[simulated, Azure 2021]**
TBD (e4 running) — `sim/results/e4_trace.csv`.

### The CRIU mechanism: a readiness ladder
"Restore ahead" needs somewhere to park a restored stage until its input arrives, and
CRIU offers more than one tier. `criu-box/x1-ladder` measures each tier's activation
latency and memory held:

| tier | CRIU | memory held while waiting | activation |
|---|---|---|---|
| T1 image on disk | `criu restore` after cache drop | 0 | r (disk) |
| T2 image in page cache | pre-read / tmpfs image dir | image size (shared, evictable) | r (memory) |
| T3 restored & stopped | `criu restore --leave-stopped`, then `SIGCONT` | RSS (less with `--lazy-pages`) | ~ms + residual |
| T4 warm | keep-alive | RSS | 0 |

Keep-alive is the special case "T4 or nothing". The ladder turns Theorem 5's capacity
result (keep-alive cannot hold a deep workflow) into a policy question: which tier each
stage rests at between invocations (from its arrival rate, generalising Theorem 6), and
how far up it is promoted when an invocation enters the DAG (from its lead time).

### What could kill it
**Parallel restore capacity.** Restore-ahead assumes the d restores run concurrently. If
they share one disk or one core they serialise, and the gain disappears. `sim/e5`: with
contention `β` (each concurrent restore slows the others by β):

| r | β = 0 | β = 0.25 | β = 1 (fully serial) |
|---|---|---|---|
| 100 ms | 1.8× | 1.7× | 1.3× |
| 250 ms | 2.6× | 2.0× | 1.1× |
| 650 ms | 3.5× | 2.2× | 1.0× |
| 2000 ms | 4.1× | 2.4× | 1.0× |

(5-stage Java chain, speedup of restore-ahead + re-warm over restore-on-demand.) At β = 1
restore-ahead is never *worse*, just not better. The gain is `(d−1)·r`, so it is an answer
for CRIU-class restore costs (hundreds of ms to seconds, as measured on the thesis's box),
not for the microsecond-class restores of OS co-designs like Spice, which the C1 constraint
rules out anyway. **`criu-box/x2-parallel`
measures β on the S0 box and is the go/no-go for this idea.** Restores into separate
containers each run on their own CPU quota and read page-cache-resident images, so β should
be small, but that is a prediction and has not been measured.

### Where it sits in `MODEL.md`
Per-stage cost becomes `c_v = max(0, r_v − slack_v) + R_v^restore(K_v) + C_v`, with
`slack_v` the lead time the DAG provides. For chains the closed form above holds. For
series-parallel DAGs Theorem 3's recursion carries a finish-time instead of a latency. The
knapsack of Theorem 1 gains a second resource: **memory-time held while waiting**, which is
what speculation spends. That also repairs the model's weak spot. `MODEL.md` §6 found
`s_v(K)` nearly flat, so the storage knapsack was close to degenerate; memory-time is not.

**Related work to position against:** Xanadu (speculative cold provisioning along the most
likely path), ORION (prewarm delays via CONV/MAX; *use its distribution model to set the
restore trigger quantile*), Snapipeline (pipelines decompression, page restore and execution
*inside one* restore; restore-ahead pipelines restores *across stages*, and the two compose),
Medes and RainbowCake (intermediate sandbox states, single function, no DAG lead time).
Searches for DAG-aware snapshot restore returned nothing, but that is not proof it does not
exist. Queries to repeat with Scholar access: *"workflow" snapshot restore prewarm*,
*"function chain" checkpoint restore*, *speculative restore serverless*.

---

## 2. Idea 2: scrubbed priming, safe deep snapshots from real DAG traffic

### The problem it removes
A deep snapshot must be *primed*. Priming with real requests (what Pronghorn does, and what
`SYNTHESIS.md` §1.3 proposes: "stage *i+1* primed with stage *i*'s real output") writes user
data into the image. The image is then restored for other users and stored on disk. That is
the same class of problem as the RNG/UUID reuse in *Restoring Uniqueness* (Brooker et al.),
and S3 of the plan is the safety boundary on depth. Priming with synthetic requests is safe
but usually exercises the wrong paths.

### The mechanism
The workflow orchestrator sees every message on every edge. For each field it learns one
thing, whether the field is **categorical** (few distinct values over a window: type tags,
currency, country, plan) or **data** (high cardinality: names, emails, ids, amounts):
* categorical values are **kept**: they are control flow, and the JIT specialises on them;
* data values are **scrubbed format-preservingly**: every character is replaced by a random
  one of the same class (upper/lower/digit), and numbers keep their digit count and scale.
  Lengths, formats and regex matches survive; content does not.

No schema, no code analysis, nothing per-application (`exp-a-context-priming/gen_inputs.py`,
`learn_categorical` + `scrub`, ~60 lines).

### Result **[measured]**
A realistic stage (Jackson polymorphic deserialisation over 6 item subtypes, BigDecimal tax
rules, regex validation, stream grouping, JSON serialisation; `src/Fn.java`) on OpenJDK 21,
fresh JVM per run, cgroup CPU quota, n = 10 per cell. Residual warm-up over 300 served
requests, relative to priming on real traffic from the same edge, 95% bootstrap CI:

| priming set (ratio to real traffic, same edge) | 1 vCPU, K=25 | K=100 | K=400 | 0.25 vCPU, K=25 | K=100 | K=400 |
|---|---|---|---|---|---|---|
| **A/A control** (real traffic, other seed) | 1.04 [0.94, 1.14] | 0.95 [0.91, 1.07] | 0.94 [0.79, 1.03] | 0.98 [0.89, 1.06] | 1.07 [0.85, 1.19] | 1.13 [0.92, 1.21] |
| **format-preserving scrub** | **0.99 [0.90, 1.09]** | **0.98 [0.91, 1.05]** | **0.97 [0.82, 1.17]** | **0.99 [0.88, 1.11]** | **1.05 [0.83, 1.13]** | **1.08 [0.87, 1.19]** |
| schema-only synthetic | 1.11 [1.02, 1.20] | 1.06 [0.97, 1.15] | 1.18 [0.99, 1.31] | 1.03 [0.93, 1.14] | 1.16 [0.93, 1.27] | 1.30 [1.08, 1.40] |
| no priming (K = 0) | 2.03× | 2.32× | 4.61× | 1.93× | 2.49× | 4.81× |

Absolute scale, 0.25 vCPU, bulk edge: residual over 300 requests is 4588 ms unprimed, 2373 /
1846 / 954 ms primed at K = 25 / 100 / 400; steady state is 0.18 ms/request. Reverse
direction (serving the *web* edge, K = 100): scrub 0.91× [0.84, 1.13] at 1 vCPU and 1.13×
[0.92, 1.22] at 0.25 vCPU, CIs again spanning 1. (`exp-a-context-priming/results/summary_exp-a*.csv`,
figure `results/exp-a_curves.png`.)

* **A/A control** (real traffic, different seed): 0.94–1.13×, CIs spanning 1. That is also
  the noise floor: differences under ~15% are not resolvable at n = 10, least of all at 0.25 vCPU.
* **Format-preserving scrub: 0.97–1.08×, every CI spanning 1**, in both directions, at every
  depth and both CPU levels. Priming on scrubbed traffic is as good as priming on real
  traffic, to within the A/A control's own spread.
* **Schema-only synthetic inputs** (right field names/types, wrong distribution): 1.03–1.30×,
  significant in 2 of 6 cells. Naive synthetic priming is not free; format preservation is
  what closes the gap.
* **Leakage audit:** 0.019% of scrubbed strings coincide with some real value (short SKUs,
  by chance). Kept verbatim: 10 categorical fields (`channel`, `currency`, `kind`, `plan`,
  `origin`, `title`, `priority`, `tags`, `city`, `country`). Those can be quasi-identifiers,
  and lengths are preserved. That is structural leakage, not content leakage, and it has to
  be stated as such.

### Why it is new, and its limits
Priming today is either hand-written dummy requests (SnapStart/CRaC priming guides) or live
traffic (Pronghorn). Deriving priming automatically and **data-free** from the messages a
DAG already carries does not appear in the reading list or in searches. The limit to
test next is **x4**: does the equivalence survive a real checkpoint, i.e. once `L(K)` is
in play? It also has to be combined with CRaC `beforeCheckpoint` resets for RNG/UUID state:
scrubbing removes *request* data, not *process* secrets.

---

## 3. Idea 3: coverage-aware priming (and why not per-edge snapshots)

### Hypothesis tested
A stage reached from several DAG edges gets structurally different inputs per edge (here:
"web" checkouts of 1–4 book/electronics items in USD vs "bulk" imports of 40–120
grocery/subscription items in EUR with a metadata map). A snapshot primed on one edge
should serve the other badly, so snapshots should be **keyed by edge**.

### Result **[measured]**
Residual warm-up relative to priming on the edge being served (95% bootstrap CI, n = 10):

| served edge | primed on | 1 vCPU, K=25 | K=100 | K=400 | 0.25 vCPU, K=25 | K=100 | K=400 |
|---|---|---|---|---|---|---|---|
| bulk (heavy: 40–120 items) | web (light) | 1.36 [1.28, 1.48] | 1.42 [1.36, 1.57] | 2.41 [2.03, 2.90] | 1.28 [1.17, 1.40] | 1.56 [1.26, 1.67] | 2.37 [2.01, 2.62] |
| bulk | 50/50 mix | 1.07 [1.00, 1.21] | 0.98 [0.91, 1.07] | 1.10 [0.92, 1.21] | 1.07 [0.97, 1.22] | 1.10 [0.89, 1.16] | 1.24 [1.05, 1.34] |
| web (light: 1–4 items) | bulk (heavy) | | **0.76 [0.67, 0.86]** | | | **0.87 [0.77, 0.92]** | |
| web | 50/50 mix | | 0.75 [0.67, 0.93] | | | 0.86 [0.76, 1.01] | |

First request after "restore", 0.25 vCPU: 3–11 ms when primed on the served edge, 107–193 ms
when primed on the light edge and serving the heavy one (unseen subtypes → class loading,
deoptimisation, recompilation).

**The hypothesis was half wrong, and the half that is wrong is informative.**
* **Light → heavy is costly:** a snapshot primed on the light edge serves the heavy edge
  with 1.3–2.4× the residual. At K = 400 it is worth about as much as a right-edge
  snapshot at K = 25.
* **Heavy → light is *better* than the right edge** (0.76× and 0.87×): 100 bulk requests
  run the shared code (Jackson, BigDecimal, regex, streams) ~30× more often than 100 web
  requests do. The JIT compiles what it has *executed*, so only the first request pays for
  the light edge's own subtypes.
* **So "which edge" is the wrong question. The unit is wrong: priming depth measured in
  requests is misleading when request sizes differ 30×.** What a snapshot captures tracks
  the *work* executed on each code path. That bears on the thesis's depth model too:
  `R_v(K)` should be indexed by priming work (or JIT invocation counters), not request
  count, whenever a stage's inputs vary in size. Pronghorn counts requests.
* **A mix covers both edges.** The 50/50 mix is at least as good as the served edge in 5 of
  8 cells and worse only when it holds too few heavy requests (bulk, K = 400: 1.24×, with
  200 bulk requests against 400). **Follow-up (exp-a-mix, registered after that cell):**
  give the mix the same number of heavy requests (K = 200 and 800 for 100 and 400 per edge)
  and it matches or beats the right-edge snapshot: 0.85× [0.79, 0.97] and 0.75× [0.64, 0.83]
  at 1 vCPU, 0.89× [0.72, 0.96] and 0.96× [0.76, 1.00] at 0.25 vCPU. Adding the other edge's
  requests never hurt the served edge. It only added work on shared paths.

**Recommendation:** drop per-edge snapshot variants; keep **coverage-aware priming**. The
orchestrator primes each stage on scrubbed traffic drawn from *every* incoming edge, with
enough work per edge. It knows the edges and their message sizes, which a single-function
system does not. That also protects against the realistic failure: a snapshot primed on
whichever edge happened to be active at deploy time. `sim/e3` puts the workflow-level stakes
in proportion: at the measured penalty ratios (1.3–2.4×) per-edge variants change E2E latency
by 1–3% and cost +1 GB·s per invocation in speculative variant restores. Worth doing
right, not worth a mechanism of its own. This is a negative result on the stronger idea,
reported as one.

---

## 4. Idea 4: re-warm in slack

exp12 found a real checkpoint **loses** part of the captured warm-up (`MODEL.md` §6b,
`L_v(K)`, up to 29 pp at low CPU). With restore-ahead, a restored stage often waits idle
before its input arrives: behind long stages (an ML inference step), behind the entry
stage's restore, or on a speculative branch. The idea: spend that idle time running
**scrubbed** (Idea 2) requests to burn down the residual and `L(K)` off the critical path.

**[simulated]** With a conservative geometric warm-up model the gain is small: −3% at depth
3, −5% at depth 8, `sim/e1`. It grows with `L(K)`, which the model cannot know.
**[protocol]** `criu-box/x3-rewarm` measures `L(K)` directly (restored vs never-checkpointed)
and how much re-warming recovers. Keep this idea only if x3 shows `L(K)` is large at the
vCPU the thesis targets. exp12 suggests it is (worst at low CPU, which is where FaaS runs).

---

## 5. Idea 5: prime on big, serve on small (with the serving shape pinned)

The thesis's headline, the vCPU cliff, also applies to *producing* deep snapshots: priming at
0.25 vCPU is slow. A DAG orchestrator that owns priming can run it on a large machine and
ship the image to small containers. Does a snapshot primed at 4 vCPU serve at 0.25 vCPU as
well as one primed at 0.25?

**[measured]** exp-b: same workload, K requests of real bulk traffic, *serving always at
0.25 vCPU*, the CPU quota switched on the live process at the "snapshot" point:

| JVM sizing during priming | K | priming wall time at 0.25 / 1 / 4 vCPU | residual when serving at 0.25, primed@4 ÷ primed@0.25 |
|---|---|---|---|
| **pinned to the serving shape** (`-XX:ActiveProcessorCount=1 -XX:+UseSerialGC`) | 100 | 3.50 / 0.87 / **0.36 s** | **0.93× [0.86, 1.06]** |
| pinned | 400 | 5.80 / 1.38 / **0.62 s** | **0.97× [0.89, 1.13]** |
| default ergonomics (the JVM sizes itself to the priming machine) | 100 | 3.40 / 0.79 / 0.36 s | 1.23× [1.05, 1.39] |
| default ergonomics | 400 | 5.70 / 1.38 / 0.57 s | 1.11× [1.06, 1.30] |

(n = 10 per cell, `exp-a-context-priming/results/summary_exp-b.csv`.)

* **Pinned to the serving shape, the snapshot is just as good, and 9–10× cheaper to make.**
* **Not pinned, it is 11–23% worse.** The JVM sizes itself (GC choice, GC and compiler
  thread counts) to the machine it *starts* on, and a restored image keeps that sizing. So a
  snapshot primed on a 4-CPU builder brings G1 and four-CPU threading into a quarter-CPU
  function. That is what a CRaC checkpoint taken on a build machine does by default.
* **Rule:** prime where CPU is plentiful, but start the priming JVM with the *serving*
  container's CPU shape (`-XX:ActiveProcessorCount`, explicit GC). It is cheap and
  actionable, and it makes deep priming (and re-priming after every deploy) affordable. Not
  a thesis on its own: it belongs in Chapter 4's priming service and as a warning in
  Chapter 2.
* Caveat: emulated by changing a live process's cgroup quota, not by checkpoint/restore.
  The JVM keeps its start-time sizing either way, which is the effect measured. x4 on the box
  can repeat it with CRaC.

---

## 6. What was done in this session, and what was not

* **CRIU could not run here.** CRIU 4.2 was built from source, but this VM's kernel lacks
  `kcmp` (`CONFIG_CHECKPOINT_RESTORE`), so `criu dump` fails. Snapshots were therefore
  **emulated** in exp-a/b: the snapshot's *content* is a process that has served K
  requests. This is exact for comparing priming sets against each other (they differ only in
  content). It excludes CRIU's own restore time and the checkpoint loss `L(K)`, which are
  additive and independent of the priming set. x3 and x4 close that gap on the S0 box.
* **Simulation parameters are the thesis's own** (`sim/dagsim.py`, `JAVA`/`PY` profiles, each
  with its source). Where a number was not in the documents (Python restore time, the
  ML-stage profile) it is marked as an assumption in the code. The simulator's controls
  (closed-form chain latencies) pass 24/24.
* **Azure 2021 trace:** per-app entry-function arrivals, first 3 days, 68 apps, 432,945
  workflow invocations (`sim/prep_azure.py`). The trace has no DAGs, so each app is assigned
  a DAG template deterministically, the same limitation `RESEARCH_PLAN.md` §5 notes.
  The rar extraction lost the last ~0.1% of rows (day 14), which is outside the window used.
* **Not verified:** Pronghorn's full text (ACM DL is blocked from this VM). What it does is
  taken from its abstract and slides summary: automatic *when-to-snapshot* and
  *which-snapshot* for JIT runtimes, CRIU, OpenJDK 17, PyPy. **Read the paper before
  rewriting the novelty section.**

## 7. How the thesis reorganises

| chapter | content | status |
|---|---|---|
| 1. Problem | cascade is linear in depth and ~98% of E2E (exp2, exp10) | done |
| 2. Calibration | A/B/C per runtime, vCPU cliff, depth curve. **Position against Pronghorn and JEP 515**: we measure it, they automate or replace it | done, needs reframing |
| 3. Model | `MODEL.md` + lead time (§1 above) + memory-time as the second knapsack resource | extend |
| 4. Mechanism | DAG-aware snapshot orchestrator: restore-ahead (+ speculation) and scrubbed, coverage-aware priming, on OpenWhisk | design here; x1–x4 decide the details |
| 5. Evaluation | trace-driven (`sim/`) + real OpenWhisk sequences on the S0 box vs restore-on-demand, cold prewarm, keep-alive, TieredStopAtLevel=3, JEP 515 | sim done; real runs to do on the S0 box |

**Implementation path on OpenWhisk.** The cheapest integration is at the action-proxy
level: a custom Java runtime image whose `/init` restores a checkpointed JVM (CRaC or raw
CRIU) instead of starting one. Restore-ahead then becomes "the controller sends `/init` to
the downstream actions of a sequence when the sequence's first activation starts." OpenWhisk
already has the moving parts (prewarm "stem cells", sequence/composition execution in the
controller). Read the version on the box before committing to where the hook goes.

## 8. Ideas considered and dropped

| idea | why dropped |
|---|---|
| **Checkpoint at the input barrier** (dump when the handler first blocks reading its input: captures lazy init with no request data in the image) | captures init only, not JIT warm-up; SEUSS/SnapStart already cover init-point snapshots |
| **Per-edge snapshot variants** | measured (§3): what a snapshot captures follows the work executed per code path, not the edge; a snapshot primed on all edges covers them, and at workflow level variants move E2E latency by 1–3% |
| **Snapshot lineage / shared base across stages** | already killed by the thesis's own experiments (and 318/330 JIT code-cache pages differ run to run, exp1b) |
| **Fusion + one snapshot for the whole chain** | loses independent scaling; `SYNTHESIS.md`'s honest-accounting note on double counting applies |
| **Restore once, fork N for fan-out** | known (SOCK, Catalyzer `sfork`, Mitosis) |

## Sources checked in this session
* Pronghorn, EuroSys '24 — <https://dl.acm.org/doi/10.1145/3627703.3629556>
* Fireworks, EuroSys '22 — <https://dl.acm.org/doi/10.1145/3492321.3519581>
* Snapipeline, SoCC '24 — <https://dl.acm.org/doi/10.1145/3698038.3698513>
* Faast, HPDC '24 — <https://dl.acm.org/doi/10.1145/3625549.3658681>
* Medes, EuroSys '22 — <https://dl.acm.org/doi/10.1145/3492321.3524272>
* Xanadu, Middleware '20 — <https://dx.doi.org/10.1145/3423211.3425690>
* JEP 515, Ahead-of-Time Method Profiling — <https://openjdk.org/jeps/515>
* Lambda SnapStart uniqueness — <https://docs.aws.amazon.com/lambda/latest/dg/snapstart-uniqueness.html>
* Azure Functions Invocation Trace 2021 — <https://github.com/Azure/AzurePublicDataset/blob/master/AzureFunctionsInvocationTrace2021.md>
