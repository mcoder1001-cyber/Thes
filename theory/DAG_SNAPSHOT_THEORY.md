# Workflow-aware snapshots: the approach, the policy, and the proofs

Written 2026-09-26. Companion to `MODEL.md` (which decides *how deep* to snapshot each
function under a storage budget) and to `../ideas/IDEAS.md` (the evidence). Every claim is
checked by `verify_dag.py`: **33/33 checks pass, 6 of them controls designed to fail**, which
do. Tags as in `MODEL.md`: **[proved]**, **[verified]** (exhaustive or randomised computation),
**[measured]** (real runs), **[assumption]** (a model input that the S0 box must confirm).

---

## 0. The approach in one page

**Principle.** A single-function snapshot system (SnapStart, Prebaking, Pronghorn, Fireworks)
sees one request at a time. A workflow orchestrator sees the whole DAG: which stages will run,
roughly when, and on what inputs. Existing snapshot work throws that information away. We
use it twice.

| | **Innovation 1: look-ahead restore** (timing) | **Innovation 2: data-free, certifiable priming** (content) |
|---|---|---|
| idea | The workflow's own upstream execution becomes the restore window for downstream snapshots | The messages the DAG already carries become the priming inputs, scrubbed so no user data enters an image |
| replaces | restore-on-demand: a depth-d workflow pays d restores in series | hand-written priming scripts (SnapStart/CRaC) or live traffic with user data in the image (Pronghorn) |
| guarantee | latency-optimal **and** memory-minimal at once (Thm 1, 2) | if the scrub preserves the handler's branch predicates, the JIT profile is *identical* (Prop 7); checkable per deployment |
| evidence | Azure trace: cold workflows 2.34 s → 0.82 s mean, 6.2 s → 1.36 s p99 at equal memory | JVM: 0.98–1.11× the warm-up capture of real traffic, all CIs span 1; path equality 100% / 98.7% |

**The policy** (what the platform does), in the order it runs:

*At build time, per function v* (on deploy, and when an edge's traffic drifts):
1. **Collect** the messages on every DAG edge into v. The orchestrator already routes them.
2. **Learn** which fields are control flow: strings **and integers** with few distinct values
   (≤ 32 over ≥ 50 observations). Everything else is data.
3. **Scrub** (fps2): keep keys, control-flow values and booleans. Replace every data character
   by a random one of the same class, and keep each number's digit count and scale.
4. **Certify**: run the handler on real and scrubbed samples with branch-coverage
   instrumentation and require equal branch profiles (Prop 7). Here the check is
   `src/Sig.java`; JaCoCo-style counts are the generic version.
5. **Prime** on a mix of all incoming edges, until each edge's JIT counters converge: depth in
   *work*, not requests (Prop 8). Run on a large machine, with the JVM pinned to the serving
   container's CPU shape (exp-b). Pick the depth with `MODEL.md`'s knapsack.
6. **Checkpoint** with CRaC/CRIU, after `beforeCheckpoint` hooks reset RNG, UUID and secrets.

*At run time, per workflow invocation:*
1. Keep-alive as usual. **If the entry function has a live sandbox, do nothing more.** This
   gate is lossless (Lemma 5).
2. Otherwise compute the eager schedule `S*_v` from the DAG and profiled `r_v, w_v`. Issue
   `criu restore` for each stage at **τ_v = S*_v − r_v** (just in time, Theorem 2). Under
   uncertainty, trigger so the sandbox is ready at the **κ-quantile** of the stage's input time,
   **κ = b/(a+b)**, with `a` the latency price and `b` the memory price (Theorem 3).
3. XOR branches: if the branch is decided at least `r_s` before the stage would start,
   restore after the decision. Otherwise **restore speculatively iff P(branch) ≥ κ**
   (Theorem 4). A single price ratio governs both the trigger and the speculation.
4. Optionally re-warm a restored stage with certified scrubbed requests while it waits.

---

## 1. What is new, and against what

| closest work | what it does | what it does not do (our part) |
|---|---|---|
| Pronghorn (EuroSys '24) | when to *checkpoint* one function; which snapshot to use | restore *timing* across a DAG; priming without user data |
| Fireworks (EuroSys '22), SnapStart | post-JIT / post-init snapshot of one function | either |
| Xanadu (Middleware '20), ORION (OSDI '22) | DAG-aware *cold* prewarming | snapshots; optimality; memory neutrality (a cold boot cannot fit in the DAG's own lead time) |
| REAP, FaaSnap, Snapipeline, Faast | make *one* restore faster (working set, pipelining) | cross-stage timing. They shrink `r_v` and **compose** with look-ahead |
| SnapStart/CRaC priming guides | manual dummy requests | automatic, data-free, certifiable priming |
| Mitosis (OSDI '23) | remote fork of a live instance, incl. inside workflows | a snapshot restored ahead of need |

The novelty is small, well-defined and double: **a scheduling result (look-ahead restore is
Pareto-optimal) and a content result (predicate-preserving scrubbed priming)**. Both follow
from the one thing a workflow knows that a function does not.

---

## 2. Model

A workflow is an **AND-DAG** `G = (V, E)` with a single entry `e`; XOR branches are §3.4.
Stage `v` has restore time `r_v > 0`, warm work `w_v = R_v + C_v ≥ 0` (residual warm-up after
the restore, plus steady execution) and memory `m_v`. Each edge adds `δ ≥ 0`. A **cold
workflow** arrives at `t = 0` and finds no live sandbox. A **policy** chooses a restore trigger
`τ_v` per stage.

| assumption | statement | status |
|---|---|---|
| **A1** no clairvoyance | `τ_v ≥ 0`: nothing starts before the workflow arrives | conservative: arrival prediction (MPC, ORION) could only help; the control in T1 shows the bound needs it |
| **A2** independent restores | a restore triggered at `τ` completes at `τ + r_v` | relaxed in Cor 1.2 (contention) and Cor 1.3 (random `r_v`); **x2 on the box measures it** |
| **A3** fixed work | a stage takes `w_v` once started | re-warming lowers `w_v`; **x3 measures it** |
| **A4** memory | stage `v` holds `m_v` from `τ_v` to its finish | lazy-pages restore would hold less, so A4 is conservative for Theorem 2 |

Semantics: `I_e = 0`, `I_v = max_{u ∈ pred(v)} F_u + δ`; `S_v = max(τ_v + r_v, I_v)`;
`F_v = S_v + w_v`; latency `L = max_sinks F`; memory-time `M = Σ_v m_v (F_v − τ_v)`.
Named policies: **on-demand** `τ_v = I_v` (today's snapshot systems); **eager** `τ_v = 0`;
**JIT** `τ_v = S^eager_v − r_v`. Path weight `W(P) = Σ_{v∈P} w_v + δ·(|P|−1)`;
`ℓ(v)` = longest `W` from `v` to a sink; `ℓ'` the same with `r_v + w_v` on each node.

---

## 3. Look-ahead restore

### Theorem 1 (look-ahead restore is latency-optimal) [proved] [verified]
(a) Every policy satisfying A1–A3 has `L ≥ L* := max_v (r_v + ℓ(v))`.
(b) The eager policy attains `L*`.
(c) On-demand has `L_od = ℓ'(e)`, the longest path with node weights `r + w`.
(d) `L* ≤ L_od`.

*Proof.* (a) Fix `v` and a path `P = (v = v_0, …, v_k)` to a sink. By A1–A2,
`S_{v_0} ≥ τ_{v_0} + r_{v_0} ≥ r_{v_0}`, and for `i ≥ 1`, `S_{v_i} ≥ I_{v_i} ≥ F_{v_{i−1}} + δ`.
Summing, `F_{v_k} ≥ r_{v_0} + W(P)`; maximise over `P` and `v`.
(b) Under eager, induction in topological order gives
`F_v = max_{u ⪯ v} (r_u + W(u ⇝ v))` over ancestors `u` of `v` (including `v`). At the sinks
this is `max_u (r_u + ℓ(u))`.
(c) With `τ_v = I_v`, `S_v = I_v + r_v`, so every node contributes `r + w` along the path.
(d) `r_v + ℓ(v) ≤ ℓ'(v) ≤ ℓ'(e)`, because `e` is an ancestor of every `v`. ∎

**[verified]** 2000 random DAGs (2–12 stages, random `r, w, m, δ`): eager equals `L*` and
on-demand equals `ℓ'(e)` exactly. 150,000 random policies never beat `L*`. **Control:**
allowing `τ < 0` (restores before the workflow arrives) does beat it, so the bound is exactly
as strong as A1.

### Corollary 1.1 (chains) [proved] [verified]
For `d` stages with equal `r, w`: `L_od = d(r+w) + (d−1)δ`, `L* = r + dw + (d−1)δ`. The saving
is `(d−1)·r`, **the restore cascade collapses to one restore**. The speedup
`σ(d) = L_od / L*` is increasing in `d` (its derivative has the sign of `r(r+w) > 0`), and
`σ(d) < 1 + r/(w+δ)`.
Thesis numbers (`r = 650`, `w = 75`, `δ = 2` ms): `σ(3) = 2.48`, `σ(8) = 4.60`, bound `9.44`.
**[verified]** 384 parameter combinations; `sim/e1` (with jitter) gives 2.34 and 4.30.

### Corollary 1.2 (restore contention) [proved] [verified]
If restores that start together slow each other so that `n` of them finish within
`r(1 + β(n−1))`, `β ∈ [0, 1]`, then on a chain the saving is at least `(1−β)(d−1)r`, never
negative. On-demand restores in a chain never overlap, so they pay no contention.
**[verified]** 40/40 analytically, and 12/12 inside the simulator's own (harsher) contention
model. **x2 on the box measures β, and it is the go/no-go for Innovation 1.**

### Corollary 1.3 (random restore times) [proved] [verified]
With random `r_j`, pointwise `L_eager ≤ max_j r_j + Σ w + (d−1)δ` on a chain, so
`E[saving] ≥ d·E[r] − E[max_j r_j]`. **Look-ahead pays the maximum of the parallel restores;
on-demand pays their sum.** With the simulator's jitter (lognormal, σ = 0.15, 5 restores),
`E[max]/r = 1.20`. That accounts for the 3–16% by which jittered `sim/e5` exceeds the
deterministic bound. (An earlier check compared the jittered runs with the deterministic
bound and failed; the failure is kept visible in the file's history.)
**[verified]** 18,006 Monte-Carlo instances.

### Theorem 2 (just-in-time look-ahead is latency-optimal AND memory-minimal) [proved] [verified]
(a) Every policy has `M ≥ M_min := Σ_v m_v (r_v + w_v)`.
(b) On-demand attains `M_min`, but in general not `L*`.
(c) JIT is feasible (`τ_v ≥ 0`) and attains **both** `L*` and `M_min`.

So in this model there is **no trade-off between latency and memory**: look-ahead done just
in time Pareto-dominates both today's on-demand restore and eager look-ahead.

*Proof.* (a) `F_v − τ_v = (S_v − τ_v) + w_v ≥ r_v + w_v`. (b) `S_v = τ_v + r_v` when `τ_v = I_v`.
(c) `S^eager_v = max(r_v, I^eager_v) ≥ r_v`, so `τ_v ≥ 0`. By induction, JIT reproduces the eager
schedule: its sandbox is ready at `S^eager_v ≥ I^eager_v`, so `S^JIT_v = S^eager_v`. Then
`L = L*`, and `S_v − τ_v = r_v` gives `M = M_min`. ∎

**[verified]** 2000 random DAGs; 30,000 random policies never go below `M_min`. **Control:**
eager holds strictly more than `M_min` on most DAGs, so JIT is a real improvement, not a
restatement. **Cross-check:** the discrete-event simulator's JIT policy (independent code)
reproduces `L*` and `M_min` exactly on chains and a fan-out/fan-in DAG.

### Theorem 3 (trigger under uncertainty = newsvendor) [proved] [verified]
Let a stage's input time `I` be random with CDF `F` (e.g. ORION's convolution model), with a
latency price `a` per ms of delay and a memory price `b = μ·m_v` per ms held idle. For ready
time `x = τ + r_v`, the expected cost `J(x) = a·E[(x−I)^+] + b·E[(I−x)^+]` is convex and
minimised at **`x* = F^{-1}(κ)`, `κ = b/(a+b)`**; trigger at `τ* = max(0, x* − r_v)`.
*Proof.* `J′(x) = a·F(x) − b·(1 − F(x))`, which is zero at `F(x) = κ`, and `J″ = (a+b)·f ≥ 0`. ∎
Cheap memory (`κ → 0`) gives ready-at-the-earliest-input, i.e. eager. Equal prices give the median.
**[verified]** 3 distributions × 4 price ratios: the κ-quantile is within 0.5% of the
numerical optimum. **Control:** the "wrong" quantile `a/(a+b)` always costs more.

### 3.4 Theorem 4 (speculation on XOR branches) [proved] [verified]
Let stage `s` be reached with probability `p`, with the branch decided at time `D`. Let
`τ^J_s` be its JIT trigger if the branch is taken, and suppose a delay at `s` reaches the
workflow's end with factor `π ∈ [0, 1]`.
(a) If `D ≤ τ^J_s`, restoring after the decision is as good as knowing the branch in
advance: **no speculation needed**.
(b) Otherwise, with `Δ = D − τ^J_s`, not speculating costs `π·a·Δ` with probability `p`, and
speculating wastes `b·Δ` with probability `1−p`. **Speculate iff `p ≥ b/(π·a + b)`**, which
is `κ` when the stage is on the critical path. *Proof:* compare the two expectations. ∎
**[verified]** Exact expected costs on a decision-plus-branch DAG agree with the rule in
228/228 (p, price, timing) cases, 57 of them decided early.

### Lemma 5 (the gate is lossless without concurrency) [proved] [verified]
AND-DAG, uniform keep-alive TTL `T`, no memory-pressure eviction, non-overlapping
invocations. If the entry function has a live sandbox at arrival time `t`, so does every
stage. *Proof:* the last invocation ran every stage, and every stage finished no earlier than
the entry (`F_v ≥ F_e`, since each stage is a descendant). So `t < F_e + T ≤ F_v + T`, and no
overlap means the sandbox is idle. ∎
So gating changes nothing in that regime. It differs only under concurrency, eviction, or XOR
branches skipped last time, which is where it trades tail latency for restores (e4b: p99.9
1.69 vs 1.00 s, 21 vs 28 starts per 1000). **[verified]** in the simulator: sequential
invocations give gated == ungated run for run. **Controls:** overlapping invocations and an
XOR saga both differ, as the lemma predicts.

### Theorem 6 (keep-alive cannot compete on rare workflows) [proved] [verified]
One workflow with Poisson arrivals at rate `λ` and keep-alive TTL `T`. A fraction `e^{−λT}` of
invocations are cold, and the sandboxes are alive a fraction `1 − e^{−λT}` of the time.
Matching look-ahead's *expected* latency requires `1 − e^{−λT} ≥ 1 − ε`, with
`ε = (L* − L_warm)/(L_cold − L_warm)`. So keep-alive holds at least `(1−ε)·Σm` continuously,
while JIT look-ahead with no keep-alive holds `λ·Σ m (r+w)`. The ratio is
`(1−ε)/(λ·c)` (with `c` the per-stage `r + w`), **unbounded as λ → 0**. Matching look-ahead's
p99 needs `e^{−λT} ≤ 0.01`, i.e. keep-alive alive 99% of the time.
*Proof:* renewal argument, alive time per inter-arrival `E[min(X, T)] = (1 − e^{−λT})/λ`. ∎
Thesis numbers (exp15 cold 12.1 s, warm 35 ms; `L*` 0.93 s; `c` 0.725 s): `ε = 0.074`,
crossover **λ\* = 1.28/s**. Below one invocation per ~0.8 s, look-ahead needs less memory.
At one per minute keep-alive needs **77×** the memory; at one per hour, **4,600×**.
**[verified]** by renewal Monte Carlo. Together with `MODEL.md` Theorem 5 (capacity), this
closes the keep-alive alternative from both sides.

---

## 4. Data-free, certifiable priming

### Proposition 7 (predicate preservation ⇒ identical JIT profile) [proved] [measured]
Model the handler `h` as deterministic, with control flow determined by a finite predicate
set `Π_h` (branch conditions, dispatch types, loop exits). A profile-guided tiered JIT's
state after executing a sequence `X` depends on `X` only through the multiset of executed
paths (invocation, back-edge and branch counts, receiver-type histograms), plus
compile-thread timing, which is independent of `X`. **If `φ` preserves `Π_h` on `X`, then
`φ(X)` executes the same path multiset, so the JIT state after priming on `φ(X)` has the same
distribution as after priming on `X`.** *Proof:* induction over execution steps. ∎

*Lemma 7.1 (what format-preserving scrubbing preserves).* It preserves equality tests on kept
(categorical) fields, and regex membership for patterns built from the preserved character
classes, since each character keeps its class. It also preserves lengths and loop trip counts,
digit counts and decimal scale (BigDecimal representation paths), booleans and null tests.
It does **not** preserve order comparisons of data fields against constants (`x > 500`),
equality with specific high-cardinality constants, or hash-dependent paths.

**[measured]** `src/Sig.java` evaluates every predicate of `Fn.handle` per request:

| scrubber | identical path, bulk edge | identical path, web edge | predicates it changes |
|---|---|---|---|
| fps (exp-a) | 77.6% | 57.3% | `tier ≥ 3 ∧ subtotal > 500`; `warrantyMonths > 12`: exactly the class Lemma 7.1 excludes |
| **fps2** (integer enums kept) | **100.0%** | **98.7%** | a price *sum* crossing 500 (20 of 1500 web requests) |
| naive scrub (**control**) | 0.0% | — | SKU regex (class structure destroyed) |

Warm-up capture (n = 20): fps 0.98–1.11×, fps2 1.02–1.12× the real-traffic residual. Seven of
fps2's 8 CIs span 1; the eighth is `1.06 [1.01, 1.13]` at K = 25, 1 vCPU, about the chance
rate for eight tests. **Equal paths are sufficient, not necessary.** fps was already
equivalent in performance because the branches it changes guard cheap code. **What fps2 adds
is a guarantee that can be checked before deployment.** That is why step 4 of the build-time
policy certifies branch profiles instead of trusting the scrubber.

### Proposition 8 (depth is work, not requests) [proved] [measured]
Under threshold tiered compilation without deoptimisation, method `m` reaches tier `k` after
priming set `P` iff `c_m(P) ≥ θ_k`, with additive counters `c_m(P) = Σ_{x∈P} n_m(x)` (this
JDK: `Tier3InvocationThreshold = 200`, `Tier4InvocationThreshold = 5000`). Hence
**`P ⊆ P′ ⇒ C_k(P) ⊆ C_k(P′)`**: adding requests never un-compiles. Two priming sets with the
same request count `K` can differ in `c_m` by the per-request work ratio (~30× here), so `K`
is not a sufficient statistic; `c_m` is.
Caveat: receiver-type pollution and deoptimisation can make the *larger* set compile *slower*
code, so the performance consequence is empirical.
**[measured]** Compiled-method count at the snapshot rises monotonically with priming work
(2/2 CPU levels). A mix containing the same heavy requests compiles at least as much (4/4)
and leaves no more residual warm-up (4/4, 0.80–0.89×). Pollution was smaller than the gain on
this workload.

---

## 5. What is proven, what is measured, what the box must still show

| claim | status |
|---|---|
| look-ahead is latency-optimal; JIT look-ahead is also memory-minimal; speculation and trigger rules | **proved** in the model; verified on random DAGs and cross-checked against the simulator |
| the model's gain on real traffic | **simulated** on the Azure 2021 trace (`ideas/sim` e4/e4b) |
| A2: restores run in parallel (β small) | **assumption**: x2 on the S0 box; Cor 1.2 gives the gain as a function of the measured β |
| A3: residual warm-up after restore, `L(K)` | **assumption**: x3 |
| scrubbed priming ⇒ same JIT profile | **proved** under predicate preservation; paths **measured** (Sig); warm-up capture **measured** (JVM, n = 20); a real-restore repeat is x4 |
| depth in work | **proved** for threshold compilation; **measured** on this workload |

What cannot be proven, and is not claimed: that every handler's control-flow-relevant fields
are low-cardinality (Prop 7 then fails, and step 4's certification rejects the scrub and falls
back to live-traffic priming); and absolute restore times, which are physics, not theory.

## 6. How this sits with `MODEL.md`

`MODEL.md` chooses **how deep** each function's snapshot is (MCKP, SP-DP, capacity
Theorem 5). This file chooses **when to restore** and **what to prime with**. They compose:
depth `K_v` sets `R_v(K_v)` and hence `w_v`, which is an input to Theorems 1–4. The pieces the
thesis already has (the vCPU cliff, `B ≈ 0.185·W`, exp12's `L(K)`) become the calibration of
`r_v` and `w_v`.

Run: `./verify_dag.py` (≈ 30 s; P7 needs Java and the generated inputs, otherwise it is skipped).
