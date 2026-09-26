# Workflow-aware snapshots: the approach, the policy, and the proofs

Written 2026-09-26. Companion to `MODEL.md` (which decides *how deep* to snapshot each
function under a storage budget) and to `../ideas/IDEAS.md` (the evidence). Every claim is
checked by `verify_dag.py`: **62/62 checks pass, 12 of them controls designed to fail**,
which do. Tags as in `MODEL.md`: **[proved]**, **[verified]** (exhaustive or randomised computation),
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
| guarantee | latency-optimal **and** memory-minimal at once (Thm 1, 2); depth chosen jointly with timing on any series-parallel DAG (Thm 7) | if the scrub preserves the handler's branch predicates, the JIT profile is *identical* (Prop 7); checkable per deployment |
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
   container's CPU shape (exp-b). **Pick each stage's depth, or no snapshot at all, with
   Theorem 7's DP.** Stages whose cold start the DAG hides need none (Cor 7.1). When the
   options differ only in restore time, snapshot the longest-tail stages first (Cor 7.2).
   With prices instead of a budget, choose from the DP's cost–latency front, by a latency
   price or an SLO (Cor 7.3). This also decides whether an image lives next to the invoker
   or in cheap remote storage (§3.6).
6. **Checkpoint** with CRaC/CRIU, after `beforeCheckpoint` hooks reset RNG, UUID and secrets.

Steps 1–4 only supply *safe warm-up inputs* for step 5. They matter only for JIT runtimes and
structured (JSON-like) messages. They buy **equal warm-up without user data in the image**
(exp-a: 0.98–1.11× real traffic; format-blind synthetic inputs up to 1.31×; none 2–5×). When
step 4 fails, or the payload is not structured, fall back to developer-written warm-up requests
or a depth-0 snapshot. Theorems 1–8 do not depend on them.

*At run time, per workflow invocation:*
1. Keep-alive as usual. **If the entry function has a live sandbox, do nothing more.** This
   gate is lossless (Lemma 5).
2. Otherwise compute the eager schedule `S*_v` from the DAG and profiled `r_v, w_v`. Issue
   `criu restore` for each stage at **τ_v = S*_v − r_v** (just in time, Theorem 2). Under
   uncertainty, trigger so the sandbox is ready at the **κ-quantile** of the stage's input time,
   **κ = b/(a+b)**, with `a` the latency price and `b` the memory price (Theorem 3).
   **Every restore goes through the memory guard** (Theorem 8(c)). Stages whose input has
   arrived come first, and may preempt look-ahead sandboxes not yet needed. Look-ahead keeps
   memory·time but raises the peak.
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

### 3.5 Theorem 7 — the unified theorem: snapshot depth AND restore timing, jointly [proved] [verified]

`MODEL.md` chooses each function's snapshot depth to minimise the **on-demand** latency: stage
`v` costs `c_v(K) = r_v(K) + R_v(K)` (restore time plus leftover warm-up at depth `K`), summed
along series and maxed across parallel branches. Under look-ahead that objective is wrong,
because restore time no longer adds up along paths (Theorem 1). This theorem replaces it.

**Setting.** A series-parallel (SP) workflow is built from single stages by series composition
`H₁ ; H₂` (every exit of `H₁` feeds every entry of `H₂`, delay `δ`) and parallel composition
`H₁ ‖ H₂` (same input; the output waits for both). Real workflow languages express exactly
this (Step Functions `Parallel`, Durable Functions fan-out). Each stage `v` picks one option
`K ∈ 𝒦_v`. Option `K` has a provisioning time `p_v(K)`, warm work `w_v(K)` and storage `s_v(K)`:
- a snapshot of depth `K`: `p = r_v(K)` (restore), `w = R_v(K) + C_v`, `s = s_v(K)`;
- no snapshot (`K = ∅`): `p = A_v` (cold boot), `w = B_v + C_v`, `s = 0`.

Look-ahead starts every provisioning at `t = 0`; by Theorem 2, JIT timing gives the same
finish times with minimum memory. The same framework covers cold prewarming (Xanadu/ORION:
all `K = ∅`) and restore-on-demand, so the theorem unifies the three.

For a sub-workflow `H` with options fixed, define
`W_H` = the longest warm path through `H` (node weights `w`, internal edges `δ`), and
`P_H = max_{v ∈ H} (p_v + ℓ_H(v))`, with `ℓ_H(v)` the longest warm path from `v` to `H`'s exits.

**Theorem 7.**
(a) *(Two numbers describe any sub-workflow.)* If `H`'s input arrives at time `x`, its output is
ready at **`F_H(x) = max(x + W_H, P_H)`**, and the pair composes as

```
stage v:     W = w_v(K)            P = p_v(K) + w_v(K)
H₁ ; H₂:     W = W₁ + δ + W₂       P = max(P₁ + δ + W₂,  P₂)
H₁ ‖ H₂:     W = max(W₁, W₂)       P = max(P₁, P₂)
```

The workflow's latency is `L(K) = max(W, P)` at the root, which equals `L*` of Theorem 1.
(b) *(Exact algorithm.)* Minimising `L(K)` subject to `Σ_v s_v(K_v) ≤ S` is solved exactly by
dynamic programming over the SP tree, keeping per sub-workflow the Pareto-minimal triples
`(storage, W, P)`. **No one-number state suffices**: the DP needs both `W` and `P`.
(c) *(When `MODEL.md`'s DP is right after all.)* If every chosen option has the same
provisioning time `r` (restore time flat in depth, as exp11 measured), then
`L(K) = r + W_root(K)`, and the problem is exactly `MODEL.md`'s SP dynamic program (its
Theorem 3) with node weights `w_v = R_v(K) + C_v` **instead of** `r_v + R_v(K) + C_v`.
(d) *(Complexity.)* The problem is NP-hard even for chains (by (c) it contains `MODEL.md`'s
multiple-choice-knapsack reduction), and the DP is pseudo-polynomial in `S`.

*Proof.* (a) By induction on the SP tree.
- Stage: its output is ready at `max(x, p) + w = max(x + w, p + w)`.
- Series: `F(x) = F₂(F₁(x) + δ) = max(max(x + W₁, P₁) + δ + W₂, P₂)
  = max(x + (W₁ + δ + W₂), max(P₁ + δ + W₂, P₂))`.
- Parallel: `F(x) = max(F₁(x), F₂(x)) = max(x + max(W₁, W₂), max(P₁, P₂))`.
- At the root `x = 0`, so `L = max(W, P)`, and unrolling `P` gives `max_v (p_v + ℓ(v)) = L*`.

(b) The composition maps are coordinatewise non-decreasing in `(W₁, P₁, W₂, P₂)`, and
storage adds. So if one partial solution of a sub-workflow is no worse than another in all of
`(storage, W, P)`, then no completion of the worse one beats the same completion of the better
one: discarding dominated triples is safe. The DP enumerates every non-dominated combination,
so it is exact.
*Why one number is not enough:* take a stage with two options of equal storage,
`c = (p 990, w 10)` (so `W 10, P 1000`) and `d = (p 100, w 500)` (so `W 500, P 600`). Put it
after a sub-workflow with `P₁ = 900` (`δ = 0`). By its own latency, `d` looks better (600 < 1000).
In context, `c` gives `max(900 + 10, 1000) = 1000` and `d` gives `max(900 + 500, 600) = 1400`.
A successor's warm work is added to its predecessor's finish, and own-latency ignores that.
(c) If `p_v = r` for all `v`, then `P = max_v (r + ℓ(v)) = r + max_v ℓ(v) = r + W`, so
`L = r + W`. Minimising `W` under the budget is the series-sum / parallel-max recursion on `w`.
(d) A chain under (c) is `min Σ_v w_v(K_v)` s.t. `Σ s ≤ S`, which is `MODEL.md` Theorem 1's
multiple-choice knapsack. ∎

**Corollary 7.1 (cold starts the DAG hides).** Switching stage `v` from a snapshot to a cold
start with the same warm work changes the latency to `max(A_v + ℓ(v), L_rest)`, where
`L_rest = max_{u≠v} (p_u + ℓ(u))`. **It costs nothing iff `A_v + ℓ(v) ≤ L_rest`.** The stages
that qualify are late in the DAG (short remaining path `ℓ(v)`) and have little JIT warm-up
(CPython, Go: `B ≈ 0`). They need **no snapshot and no storage**; look-ahead cold-starts them
behind upstream work.

**Corollary 7.2 (longest tail first).** If the options change only the provisioning time
(`w_v` the same for every option), and each snapshot costs the same storage with budget for
`k` of them, then **the optimum snapshots the `k` stages with the largest `ℓ(v)`**. It is a
sort, not a DP. *Proof:* `ℓ` does not depend on the choice, and `L = max_v (p_v + ℓ(v))`.
If `ℓ(u) ≥ ℓ(v)` and only `v` has the snapshot (`r ≤ A`), swapping gives
`max(r + ℓ(u), A + ℓ(v)) ≤ A + ℓ(u) ≤ max(A + ℓ(u), r + ℓ(v))`, never worse. ∎
Under on-demand, by contrast, every snapshot on the critical path is worth the same `A − r`.
Under look-ahead, **position in the DAG decides the value**: the entry is worth most, late
stages least.

**Two worked examples** (thesis parameters: Java `A 2510, B 370, r 650`, `R(K)` down to 20 ms,
30 MB per snapshot; Python `A 400, B 15, r 60`, 20 MB):
- *The entry matters most.* A 3-stage Python chain runs in parallel with one more Python stage,
  with storage for two snapshots. `MODEL.md`'s on-demand DP rates every chain stage equally and
  snapshots stages 1 and 2, leaving the entry cold (look-ahead latency 489 ms). The joint
  optimum snapshots the entry and stage 1. Stage 2's cold start is then hidden behind upstream
  work, and the latency (435 ms) is set by the parallel stage's own cold start (400 + 35 ms).
- *Look-ahead moves the critical path.* A 5-stage Java chain runs in parallel with a single Java
  stage, with storage for all six. Under on-demand the chain (3.4 s) is critical, so
  `MODEL.md`'s objective is indifferent to the side stage and leaves it cold. Look-ahead
  collapses the chain to 0.82 s, and the cold side stage (2.9 s) *becomes* the critical path.
  Choosing depth for look-ahead gives **0.82 s vs 2.89 s (3.5×)**.

**[verified]** `verify_dag.py`:
- (a) the composition rules equal the exact schedule of the expanded DAG on 2000 random SP
  workflows, and the on-demand recursion equals the on-demand schedule (2000/2000);
- (b) the `(storage, W, P)` DP equals brute force on 600/600 instances. **Control:** a
  one-number state `(storage, latency)` is wrong on 63/600, and the proof's explicit
  counterexample reproduces (1000 vs 1400 ms);
- (c) with equal `r`, the joint optimum equals `r + MODEL.md`'s DP on `w` (600/600).
  **Control:** one slow-restoring stage breaks the reduction (600/600);
- Cor 7.1 holds 600/600 (159 hidden cases);
- Cor 7.2 equals the exact optimum 600/600. **Control:** snapshotting the shortest-tail stages
  instead is worse (600/600).

**What unification buys, on 1000 random thesis-like SP workflows** (60% Java stages, all budgets):
- look-ahead alone, keeping `MODEL.md`'s depth choices, is 1.75× faster than on-demand on average;
- choosing the depths for look-ahead (Theorem 7) improves further on 25% of instances, usually
  slightly (median 1.012×, p95 1.04×), occasionally a lot (max 3.35×, the critical-path shift
  above);
- it leaves 7% more Python stages without a snapshot (2001 vs 1876), i.e. the same or better
  latency for less storage.

Honest summary: **the big gain is look-ahead itself; Theorem 7 makes the depth decision
correct for it**. Without it, the old objective occasionally leaves the new critical path
unprotected.

### 3.6 Which stages are worth a snapshot: latency, money, and where the image lives [proved] [verified]

Not every stage should get a snapshot. Theorem 7 already lets each stage choose "no snapshot"
(`K = ∅`). A snapshot option is not worth it for one of three reasons:

1. **Dominated.** It is no better than a cold start: `p_v(K) ≥ A_v` and `w_v(K) ≥ B_v + C_v`.
   `F_H(x) = max(x + W, P)` is non-decreasing in every `p` and `w` (Theorem 7(a)), so such an
   option can never help and is dropped. Typical cases: a runtime whose cold start is already
   fast, and a **large image restored from remote storage**, where the restore time grows with
   the image, `p = r + s/bandwidth`.
2. **Hidden by the DAG** (Corollary 7.1). Its cold start fits in time that other stages spend
   anyway. This includes the *entry*, when a parallel downstream restore is longer than the
   entry's cold start (e6: the Python entry of `mixed-order`).
3. **Not worth its cost** (Corollary 7.3 below).

**Corollary 7.3 (price instead of budget).** Give every option an additive cost `c_v(K)` per
month: its image's storage price, plus the resources one cold invocation spends in the stage
(memory × time, `m_v (p_v + w_v)`, additive by Theorem 2) times the number of cold invocations
`n_c`. Let `a` be the price of one ms of workflow latency. Minimise `J = n_c·a·L + Σ_v c_v`.
(a) The optimum is a point of the (cost, latency) Pareto front, which Theorem 7(b)'s DP
computes with cost in place of storage.
(b) It lies on the front's lower convex hull, so one slope `μ = 1/(n_c·a)` selects it. The
**SLO form**, the cheapest point with `L ≤ SLO`, is read off the same front.
(c) With Poisson arrivals at rate `λ` and keep-alive TTL `T`, `n_c` per unit time is
`λ e^{−λT}`. It is largest at `λ = 1/T`, where it equals `1/(eT)`. **Very frequent workflows
stay warm, very rare ones are rarely invoked; both gain little from a snapshot.**
*Proof.* (a) `J` is non-decreasing in both coordinates. (b) A linear function over a finite set
is minimised at a vertex of its convex hull. (c) A Poisson gap exceeds `T` with probability
`e^{−λT}`. The derivative of `λ e^{−λT}` is `(1 − λT) e^{−λT}`. ∎
**[verified]** `verify_dag.py`: front optimum = brute force over all assignments 600/600;
the chosen point is on the lower hull 600/600; `λ e^{−λT}` and its maximum, and a renewal
Monte Carlo at `λT = 0.1, 1, 5`. **Control:** counting every invocation as cold ranks
frequent workflows wrongly.

**What the cost view shows** (`ideas/sim/e6_cost.py`, exact model). Prices are public list
prices used only as an example: $0.0000167 per GB-second, $0.08 per GB-month next to the
invoker, $0.023 per GB-month in object storage, and 100 MB/s from object storage **[assumption]**.
The Spring Boot image (90 MB) and the ML image (≈ its 1 GB of memory) are **[assumption]**.

| function | cold start | restore, deepest snapshot | image in local / remote storage pays for itself above |
|---|---|---|---|
| Java (Spring Boot) | 2.89 s, 1.45 GB-s | 0.68 s, 0.34 GB-s (remote 1.58 s) | **12.7 / 6.2** cold invocations per day |
| Python (light) | 0.44 s, 0.11 GB-s | 0.09 s, 0.02 GB-s (remote 0.29 s) | 35.7 / 24.0 per day |
| ML stage (1 GB image) | 2.14 s, 2.14 GB-s | 0.50 s local; **10.7 s remote, slower than cold** | 97.6 / never |

At a 10-minute TTL no workflow can have more than **53** cold invocations a day (c). The Azure
2021 trace has a median of **1.0** per day and a maximum of 27. A Java image in local storage
pays for itself in 6/68 workflows (13/68 in object storage), a Python image in 0–1/68, an ML
image in none. **In money, most snapshots do not pay for themselves. They buy latency.** Cost
decides *where* an image lives and which snapshots to drop when their latency value is zero.

Per workflow, at 10 cold invocations a day (latency under look-ahead, $ per month):

| workflow | today: every stage, restore on demand | every stage + look-ahead | Theorem 7: fastest, then cheapest | cheapest overall (`a = 0`) |
|---|---|---|---|---|
| Java chain, 5 stages | 3.42 s, $0.044 | 0.82 s, $0.044 | 0.82 s, $0.044 (5/5 images) | 1.72 s, $0.030 (5/5, all remote) |
| ML pipeline (Py, ML, Java, Java, Py) | 2.04 s, $0.103 | 0.74 s, $0.103 | 0.74 s, $0.102 (both Python images remote) | 2.25 s, $0.024 (2/5) |
| fan-out 4 (Java) | 2.14 s, $0.054 | 0.78 s, $0.054 | 0.78 s, $0.053 | 1.69 s, $0.036 (6/7, remote) |
| mixed (Py, Java ‖ Py, Java, Py) | 1.54 s, $0.023 | 0.74 s, $0.023 | 0.74 s, **$0.019 with 3/5 images** | 1.65 s, $0.014 (2/5) |

So: the same latency as snapshotting everything with **two images fewer** in `mixed` (the
Python entry and the parallel Python stage are hidden); hidden small images can move to cheap
remote storage at no latency cost; and the cheapest choice costs 2–3× the latency. Which point
to take depends on what latency is worth (`a`, or an SLO). The theory cannot decide that; it
computes the whole front so the operator can.

**Is the cost view sound? Criticism.**
- *Right:* it turns "is this snapshot worth it?" into a computable rule, picks the storage tier,
  and shows that storage is cheap but cold invocations are rare.
- *Wrong if done per function:* comparing one function's cold-start cost with its restore cost
  ignores its position in the DAG. A hidden stage gains nothing however cheap its restore
  (Corollary 7.1), and the entry is worth most (Corollary 7.2). The comparison must be made on
  the workflow's latency, by the DP.
- *Only cold invocations count:* the benefit scales with `λ e^{−λT}`, not `λ`.
- *Money alone says "no snapshot"* for the median real workflow. Latency needs a price or an SLO.
- *List prices are not a provider's cost.* For a provider, the scarce resources are local
  image cache on the invokers (Theorem 7's budget form) and memory at peak (Theorem 8, a hard
  limit, not a price).
- *Inputs are uncertain:* restore time depends on load (β) and on where the image is cached.
  Use measured distributions, as Theorem 3 does for triggers.

### 3.7 Theorem 8 — memory: look-ahead keeps memory-time, not the peak [proved] [verified]

Theorem 2 says just-in-time look-ahead holds no more memory·time than on-demand. It does not
say the **peak** is the same, and it is not: look-ahead restores later stages *while* earlier
ones run. A real invoker has a hard budget (OpenWhisk's was 1024 MB on the S0 box), so this
matters.

**Theorem 8.**
(a) *(Peak.)* On a chain of `d` equal stages the on-demand peak is `m`. The just-in-time
look-ahead peak is **`m · min(d, ⌈(r+w)/(w+δ)⌉)`**. Thesis numbers: `⌈725/77⌉ = 10`, so an
8-stage Java chain holds 8 × 512 MB = 4 GB for about 0.7 s, instead of 512 MB.
(b) *(Memory buys latency, chains.)* Allow at most `k` sandboxes at once, admitted in stage
order. Then `S_v = r + (v−1)(w+δ)` for `v ≤ k` and `S_v = max(S_{v−k} + r + w, S_{v−1} + w + δ)`
after, so:
- latency is non-increasing in `k`;
- `k = 1` gives `d(r+w)`, never worse than on-demand's `d(r+w) + (d−1)δ`;
- latency is `L*` exactly iff `k ≥ min(d, ⌈(r+w)/(w+δ)⌉)`;
- on long chains each stage costs `max(w+δ, (r+w)/k)`: **each extra slot divides the restore
  cost**.

  8-stage Java chain: `k` = 1, 2, 3, 4, 8 gives 5.80, 2.98, 2.25, 1.68, 1.26 s (on-demand 5.81 s).

(c) *(The guard, any DAG, hard cap `C ≥ max m`.)* Memory requests queue: stages whose input has
arrived come first, then by trigger time, with strict head-of-line admission. A stage whose
input has arrived and does not fit **preempts** admitted stages whose input has not arrived
(latest trigger first); these re-queue. Then:
- the cap is never exceeded;
- no deadlock (running stages always finish, and look-ahead sandboxes can always be preempted);
- if `C` is at least the just-in-time schedule's own peak, latency is `L*` with no preemption;
- on a chain, capped look-ahead is never slower than capped on-demand.

*Proof.* (a) Under JIT, stage `v` holds memory on `[(v−1)(w+δ), (v−1)(w+δ) + r + w)`: intervals of
length `r + w` starting every `w + δ`. At most `⌈(r+w)/(w+δ)⌉` of them contain any point. Under
on-demand the intervals are disjoint.
(b) Stages finish in order, so the slot for `v` is freed by `v − k`. Hence
`S_v = max(S*_v, F_{v−k} + r, F_{v−1} + δ)`, and `S*_v ≤ S_{v−1} + w + δ`.
- Monotone: by induction, since `S_{v−k−1} ≤ S_{v−k}`.
- No stall iff `k(w+δ) ≥ r + w`: substitute `S_{v−1} = S_{v−k} + (k−1)(w+δ)`. A stall persists,
  because `S*` advances by exactly `w + δ` per stage and `S` by at least that.
- In a stall, `S_{v+k} = S_v + r + w`, so the schedule is periodic.

(c) Preemption removes the only way memory can be held by stages that cannot progress.
- If `C ≥` the JIT peak, every admission happens at its trigger time, as in the JIT schedule.
- On a chain, when `v`'s input arrives, `v − 1` has finished and every other holder is a
  look-ahead sandbox, which can be preempted. So `S_v ≤ I_v + r_v`, and induction on `I` gives
  the claim. ∎

**[verified]** `verify_dag.py`:
- (a) holds 2000/2000 on chains. On random DAGs, memory·time equals on-demand's (2000/2000,
  Theorem 2), yet the peak is higher on 1999/2000.
- (b) the recurrence equals an independent slot simulation, and all four consequences hold
  (1500 chains, every `k`).
- (c) holds 1500/1500: cap never exceeded, `L*` once the cap covers the JIT peak, and on 750
  heterogeneous chains never slower than capped on-demand and monotone in the cap. **Control:**
  without preemption, look-ahead sandboxes fill the cap and deadlock the workflow (582/1500
  instances at some cap).
- *Measured, not proved:* on general DAGs capped look-ahead is 1.94× faster than capped
  on-demand on average across caps, but not always. It is slower at some cap on 88/750 random
  DAGs (12%), at worst by 1.37×. A scratch run over 21,000 (DAG, cap) pairs gives 1.7% slower,
  median 6%. Critical-path priority does not remove it (89/750). It is the classical anomaly of
  scheduling under a resource limit: speeding tasks up can lengthen the schedule (Graham,
  *SIAM J. Appl. Math.* 1969).

**In the simulator** (`ideas/sim` e7, policy `…/guard`: demand starts preempt unclaimed
look-ahead sandboxes):
- *Burst:* 16 cold 8-stage Java chains arrive within 1 s.
  - Unguarded look-ahead **overflows the budget** (32.6 demand starts per run at 8 GB, where
    on-demand has none).
  - The guard brings this to **0 at every budget on-demand itself fits in**, and is still
    faster: 5.77 vs 5.91 s at 8 GB, 4.35 s at 16, 2.81 s at 32, 1.19 s at 64.
  - Below on-demand's own need (4 GB) it behaves exactly like on-demand.
- *Azure trace* (e7b; its working set is ~50 GB, so these budgets are all tight). Every
  policy overflows at 16 and 24 GB, on-demand included: the running sandboxes alone exceed the
  budget. What look-ahead adds, at 24 GB:

  | policy | starts over budget | GB-s over budget | cold-workflow latency, mean / p99 | restores |
  |---|---|---|---|---|
  | on-demand (`snap`) | 1,513 | 147 | 2.35 / 6.20 s | 116k |
  | look-ahead, ungated (`ahead+rw`) | 6,823 | 641 | 0.85 / 1.82 s | 229k |
  | recommended (`…/gated/jit`) | 1,980 | 198 | 0.81 / 1.30 s | 140k |
  | recommended + guard | 1,838 | 184 | 0.81 / 1.31 s | 140k |
  | recommended + guard, look-ahead may not evict warm sandboxes | **889** | **84** | 2.29 / 6.16 s | 111k |

  The guard trims look-ahead's extra overflow but does not remove it. The rest comes from
  look-ahead **evicting other workflows' idle warm sandboxes**, which causes about 20% more
  restores later. Forbidding that eviction brings overflow *below* on-demand's, but the
  look-ahead gain disappears with it: at these budgets memory is always full of idle keep-alive
  sandboxes, so nothing is ever restored ahead. A headroom (look-ahead may use only 85% of the
  budget) made overflow worse (2,335). At 32 GB the recommended policy has no overflow, with or
  without the guard. **At a budget below the working set, look-ahead and keep-alive compete for
  the same memory, and the operator must choose.** Theorem 8(b) prices each GB for the first;
  Theorem 6 prices the second.

**What the platform does:** run-time step 2 asks the memory guard before each restore, and
starts that arrive when memory is short preempt look-ahead sandboxes that have not yet been
claimed. The operator sets the budget. Theorem 8(b) says what each extra GB buys.

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
| joint depth + timing on series-parallel DAGs (Thm 7): composition rules, exact DP, reduction to `MODEL.md`, hidden cold starts, longest-tail-first | **proved**; verified against brute force and the expanded-DAG evaluator |
| which stages are worth a snapshot under prices or an SLO (Cor 7.3), cold-invocation rate `λe^{−λT}` | **proved**; verified; money break-even **computed** with list prices and assumed image sizes (e6) |
| peak memory of look-ahead; memory slots on chains; the preemption guard (Thm 8) | **proved** for chains and for the guard's safety; on general DAGs capped look-ahead is occasionally slower than capped on-demand (**measured**, not fixed) |
| the model's gain on real traffic | **simulated** on the Azure 2021 trace (`ideas/sim` e4/e4b) |
| A2: restores run in parallel (β small) | **assumption**: x2 on the S0 box; Cor 1.2 gives the gain as a function of the measured β |
| A3: residual warm-up after restore, `L(K)` | **assumption**: x3 |
| scrubbed priming ⇒ same JIT profile | **proved** under predicate preservation; paths **measured** (Sig); warm-up capture **measured** (JVM, n = 20); a real-restore repeat is x4 |
| depth in work | **proved** for threshold compilation; **measured** on this workload |

What cannot be proven, and is not claimed: that every handler's control-flow-relevant fields
are low-cardinality (Prop 7 then fails, and step 4's certification rejects the scrub and falls
back to live-traffic priming); and absolute restore times, which are physics, not theory.

## 6. How this sits with `MODEL.md`

`MODEL.md`'s depth optimisation (MCKP, SP-DP) is exactly the **restore-on-demand** special case
of Theorem 7: one number per sub-workflow, restore time on the path. Under look-ahead it is
replaced by Theorem 7's `(W, P)` recursion. Theorem 7(c) shows the two coincide, with `w` in
place of `r + w`, whenever restore times are equal across stages. `MODEL.md`'s capacity
Theorem 5 and its refutations (submodularity, parallel convexity) stand unchanged; they are
statements about the DAG, not about the timing policy. The thesis's measurements (the vCPU
cliff, `B ≈ 0.185·W`, exp12's `L(K)`) are the calibration of `p_v(K)` and `w_v(K)`.

Run: `./verify_dag.py` (≈ 30 s; P7 needs Java and the generated inputs, otherwise it is skipped).
