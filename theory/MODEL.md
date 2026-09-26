# A formal model for snapshot placement and depth in FaaS workflows

> **See also `DAG_SNAPSHOT_THEORY.md` (2026-09-26):** that file decides *when to restore*
> each snapshot along the workflow DAG and *what to prime it with*, with proofs checked by
> `verify_dag.py`. **Its Theorem 7 supersedes this file's depth optimisation under
> look-ahead:** the objective below (`c_v = r_v + R_v`, summed along paths) is the
> restore-on-demand special case. Under look-ahead each sub-workflow needs two numbers
> `(W, P)`; the two coincide, with `R_v + C_v` in place of `c_v`, when restore times are equal
> (Theorem 7(c)).

Written 2026-09-24. Companion to `experiments/RESULTS.md` (the measurements that
supply this model's inputs and validate its assumptions) and `verify.py` (the
computational check of every claim below).

**What this document is for.** Experiments 1–10 measure *where cold-start cost lives*.
They do not say *what to do about it*. This model does: given a workflow DAG and a
per-function warm-up profile, it decides **which functions to snapshot and how deep**,
under a storage budget, with proofs.

**Why it is language-independent.** The model takes the per-function profile
`(A_v, e_v(·), s_v(·), r_v(·), m_v)` as *input*. Nothing in the theory knows about
HotSpot, V8 or CPython. The runtime determines only the numeric shape of the curves.
The measurement study becomes the *calibration* of this model, not the contribution.

Every claim is tagged:
**[proved]** analytically, **[verified]** by exhaustive computation in `verify.py`,
**[measured]** against real data, **[refuted]** — hypotheses that failed, kept visible.

---

## 1. Model

A workflow is a DAG `G = (V, E)`, `n = |V|`. One invocation of the workflow invokes
each `v ∈ V` once.

For each function `v`, measured directly by the `exp5` harness:

| symbol | meaning | measured as |
|---|---|---|
| `A_v` | process start + load + framework init | cold-to-ready time |
| `ℓ_v(i)` | latency of the `i`-th request served by one container | per-invocation curve |
| `C_v` | steady-state latency | median of the converged tail |
| `e_v(i) = (ℓ_v(i) − C_v)⁺` | **warm-up excess** at request `i` | curve minus steady state |
| `B_v = Σ_{i≥0} e_v(i)` | total warm-up cost | exp3/5/8's cost **B** |
| `m_v` | resident memory needed to stay warm | action memory limit |

A **snapshot of depth `K`** checkpoints the container after it has served `K` requests.
Restoring it yields a process that behaves as though it had already served `K`.

| symbol | meaning | measured as |
|---|---|---|
| `R_v(K) = Σ_{i≥K} e_v(i)` | **residual warm-up** after restoring a depth-`K` snapshot | tail sum of the curve |
| `s_v(K)` | image size at depth `K` | code cache + heap growth |
| `r_v(K)` | restore-to-first-response cost | **measured, exp11 + exp12** |

Note `R_v(0) = B_v` and `R_v(∞) = 0`. The captured fraction of exp6/exp8 is
`γ_v(K) = 1 − R_v(K)/B_v`.

**Decision variable.** For each `v`, choose `K_v ∈ 𝒦 = {∅, 0, 1, …, K_max}`, where `∅`
means "do not snapshot this function".

**Per-function cost under that choice:**

```
c_v(∅) = A_v + R_v(0)          full cold start: init, then all of the warm-up
c_v(K) = r_v(K) + R_v(K)       restore, then only the warm-up that remains
s_v(∅) = 0
```

**Problem (SNAPSHOT-BUDGET).** Choose `K = (K_v)_{v∈V}` minimising workflow
cold-start latency `L(K)` subject to `Σ_v s_v(K_v) ≤ S`.

For a **chain**, `L(K) = Σ_v c_v(K_v)`. For a general DAG,
`L(K) = max_{P ∈ paths(G)} Σ_{v∈P} c_v(K_v)`.

> **Scope (updated 2026-09-24).** `r_v(K)` was the one input taken on faith. It is now
> measured — exp11 (light handler) and exp12 (Spring Boot under CPU quota): restore-to-
> first-response **5.3–2500 ms** depending on depth and CPU, wall-clock restore
> **642–9053 ms** against cold starts of **2286–26768 ms**.
>
> exp12 also found that `R_v(K)` as defined here — the tail sum of the warm-up curve —
> **overstates what a real restore delivers, by up to 29 percentage points, worsening
> as CPU falls.** See §6b: the optimiser must be fed `R_v^restore(K) = R_v(K) + L_v(K)`,
> where `L_v` is warm-up lost to the checkpoint itself. The *structural* results
> (Theorems 1–5) are unaffected — they take `R_v` as an input and do not care how it is
> obtained — but the calibration is not.

---

## 2. The structural lemma — and it is the load-bearing one

Everything algorithmic below rests on the shape of the warm-up curve, not on its scale.

### Lemma 1 (convexity of residual warm-up) **[proved]** — hypothesis **[REFUTED on raw data]**

*If the excess sequence `e_v(i)` is non-increasing in `i`, then `R_v(K)` is
non-increasing and **discretely convex** in `K`.*

**Proof.** The first forward difference is
`ΔR_v(K) = R_v(K+1) − R_v(K) = −e_v(K) ≤ 0`, so `R_v` is non-increasing.
The second difference is
`Δ²R_v(K) = ΔR_v(K+1) − ΔR_v(K) = e_v(K) − e_v(K+1) ≥ 0`
by the monotonicity hypothesis. A sequence with non-negative second differences is
discretely convex. ∎

**The implication is sound; its hypothesis fails on the measured curves.**
`verify.py` checks all 820 curves in `exp5-factor-study/results/curves/`, pooled into
50 `(workload, vCPU, memory)` cells. Result:

> **Only 4 of 50 cells have `e_v(i)` non-increasing at ≥95% of points.** The rest sit
> at **50–65%**, which is what an unbiased noise process gives. Lemma 1's hypothesis
> is refuted on raw data.

A first draft of this document claimed the tail sum `R` smooths jitter away. **That was
wrong**: `Δ²R(K) = e(K) − e(K+1)` exactly, so convexity of `R` *is* monotonicity of
`e`, with no smoothing whatsoever. The verifier prints both columns to make the
identity visible.

**Lemma 1′ (what survives).** Fit the non-increasing isotonic regression `ê_v` (PAVA)
to `e_v`. For **31 of 50 cells** the mean deviation `|e − ê|` is within **2 standard
errors of the rep-to-rep noise** at the same iteration — i.e. the *underlying* curve is
consistent with being monotone even though no single sample is. Theorems 2 and 4a are
therefore stated for the isotonic profile `ê`.

**What the smoothing costs, measured rather than assumed.** Running the optimiser on
raw versus isotonic profiles: mean greedy-vs-optimal gap **0.192% (isotonic) → 0.582%
(raw)**, both within the theorem's own bound in 60/60 instances. So the convexity
failure is real but practically cheap — and Theorems 1 and 3 (the exact DPs) do not
need convexity at all.

**Open question this raises.** Are the violations only noise, or does HotSpot's
warm-up genuinely rise at points — deoptimisation and recompilation would do exactly
that. 19 of 50 cells are *not* noise-consistent, which suggests some of it is real.
Worth a targeted look with `-XX:+PrintCompilation`; a non-monotone warm-up curve would
be a finding in its own right.

### Lemma 2 (concavity of image growth) **[measured]** — holds on the decision grid only

`s_v(K)` is non-decreasing and concave in `K`. Exp 6 measured code-cache growth for
Spring Boot at 1 vCPU: `+146 KB at K=1 → +1438 KB at K=100 → +2476 KB at K=500`
— per-request growth `146 → 13.1 → 2.6 KB`, sharply decreasing.

**Per-invocation, the code cache is a step function** (it jumps when a method
compiles), so pointwise concavity fails — `verify.py` finds only 10/40 cells concave
at per-call granularity. On the **decision grid** the optimiser actually uses
(`K ∈ {1,2,5,10,20,50,100,200,400}`) the per-request increments are decreasing for
most cells. Concavity is therefore asserted only at that granularity, which is the
only granularity the model consumes.

---

## 3. Chains

### Theorem 1 (chains are exactly a multiple-choice knapsack) **[proved]** **[verified]**

*For a chain, SNAPSHOT-BUDGET is an instance of the multiple-choice knapsack problem
(MCKP) with one class per function and one item per depth. Consequently:*

*(a) it is NP-hard;*
*(b) it is solvable exactly in `O(n · |𝒦| · S)` time by dynamic programming.*

**Proof.** For a chain `L(K) = Σ_v c_v(K_v)`, so both objective and constraint are
separable across `v`, and exactly one `K_v` is chosen per `v`. That is MCKP verbatim.

*(a)* Reduce 0/1-knapsack to it: given knapsack items `(w_i, p_i)` and capacity `W`,
build one function per item with `𝒦 = {∅, 0}`, `s_i(0) = w_i`,
`c_i(∅) − c_i(0) = p_i`, and `S = W`. A solution of SNAPSHOT-BUDGET selects a subset
of storage-weight `≤ W` maximising total benefit, i.e. solves the knapsack instance.

*(b)* Standard MCKP DP: let `D[j][b]` be the minimum cost using the first `j`
functions and storage exactly `≤ b`. Then
`D[j][b] = min_{K ∈ 𝒦, s_j(K) ≤ b} ( c_j(K) + D[j−1][b − s_j(K)] )`,
with `D[0][b] = 0`. Filling the table takes `O(n · |𝒦| · S)`. ∎

The reduction is the contribution; MCKP and its DP are classical (Kellerer, Pferschy &
Pisinger, *Knapsack Problems*, 2004). **[verified]**: `verify.py` checks the DP against
exhaustive enumeration on 2000 random instances built from real measured curves.

### Theorem 2 (greedy slope-merge is *exactly* optimal under convexity) **[proved]** **[verified]**

*If, for every `v`, the points `{(s_v(K), −c_v(K))}` lie on their class's upper convex
hull — which Lemmas 1 and 2 supply — then the greedy that repeatedly applies the
incremental upgrade `K → K+1` of highest ratio*

```
        c_v(K) − c_v(K+1)        (latency saved)
ρ_v(K) = ─────────────────
        s_v(K+1) − s_v(K)        (storage spent)
```

*solves the LP relaxation exactly, and its integral solution differs from the optimum
by at most the benefit of a single upgrade.*

**Proof sketch.** Under convexity each class's incremental ratios `ρ_v(K)` are
non-increasing in `K`, so a class is always upgraded in order and never needs to be
revisited or partially undone. The LP relaxation of MCKP with convex classes is then a
fractional knapsack over the pooled increments, which greedy solves exactly
(Dantzig). Integrality costs at most the one partially-taken increment. ∎

**Consequence.** The absolute gap is bounded by `max_{v,K} (c_v(K) − c_v(K+1))` and the
*relative* gap vanishes as `S` grows.

**[verified]** on 300 instances built from real curves: the bound holds in **300/300**,
mean relative gap **0.87%** (isotonic) / **1.38%** (raw). **But the worst case is
84.8%** — at budgets that afford only one snapshot among many functions, "within one
item of optimal" is a weak statement. **Use the exact DP (Theorem 1b / 3) at small
budgets; greedy is for large ones.** The control confirms the test can detect failure:
on a deliberately non-convex ladder greedy returns 199 against the DP's 99.

---

## 4. DAGs

### Hypothesis (REFUTED): latency reduction is submodular on DAGs **[refuted]**

I conjectured that on a DAG the reduction `f(X) = L(∅) − L(X)` is monotone submodular,
which would give the standard `(1 − 1/e)` greedy guarantee. **It is false**, by a
two-element counterexample:

Two disjoint parallel branches `a`, `b`, each one function, each path cost 10, each
snapshot saving 5. End-to-end latency is the `max` of the two branches.

| `X` | `L(X)` | `f(X)` |
|---|---|---|
| `∅` | 10 | 0 |
| `{a}` | max(5,10) = 10 | **0** |
| `{b}` | max(10,5) = 10 | **0** |
| `{a,b}` | max(5,5) = 5 | 5 |

Submodularity requires `f({a}) + f({b}) ≥ f({a,b}) + f(∅)`, i.e. `0 ≥ 5`. False.

The function is **super**modular here: parallel branches are *complements*, not
substitutes. Speeding up one branch buys nothing until the other is sped up too.

**Consequence — and it is a real negative result.** Greedy has **no constant-factor
guarantee** on general DAGs: in the example it gains 0 with budget for one snapshot
where the optimum gains 5, an unbounded ratio. Any paper applying the standard
submodular-greedy machinery to workflow critical paths without checking this is
making an unsound claim.

### Theorem 3 (series-parallel DAGs are exactly solvable) **[proved]** **[verified]**

*For a series-parallel DAG, SNAPSHOT-BUDGET is solvable exactly by dynamic programming
over the SP decomposition tree. Let `F_G(b)` be the minimum achievable latency of
sub-workflow `G` under storage budget `b`. Then*

```
leaf:      F_v(b)        = min { c_v(K) : s_v(K) ≤ b }
series:    F_{G₁;G₂}(b)  = min_{b₁+b₂=b} [ F_{G₁}(b₁) + F_{G₂}(b₂) ]     (min-plus convolution)
parallel:  F_{G₁‖G₂}(b)  = min_{b₁+b₂=b} max( F_{G₁}(b₁), F_{G₂}(b₂) )   (min-max convolution)
```

*in `O(|V|·|𝒦|·S + |V|·S²)` time.*

**Proof.** The recursions are exhaustive over the budget split at each composition
node, and the SP tree has `O(|V|)` internal nodes. Optimal substructure holds because
the latency of a composed sub-workflow depends on its children only through their
achieved latencies and consumed budgets. ∎

This is the right generalisation of Theorem 1: it covers chains, fan-out/fan-in, and
nested combinations — which is what real workflow languages (AWS Step Functions'
`Parallel`, Azure Durable Functions' fan-out) actually express.

### Theorem 4a (series composition preserves convexity) **[proved]** **[verified]**

*If `F₁` and `F₂` are convex, then `F_{G₁;G₂} = F₁ ⊕ F₂` (min-plus convolution) is
convex, and is computable in `O(S)` by merging the two sorted difference sequences.*

**Proof.** Infimal convolution of convex functions is convex, and the classical
slope-merge result says its difference sequence is the sorted merge of the inputs'
difference sequences. Merging is linear in the number of slopes. ∎

**[verified]** 120/120 random compositions built from real isotonic profiles.

**Consequence for chains.** A chain is a pure series composition, so for chains the
whole DP of Theorem 1 collapses to an `O(|V|·S)` slope merge and remains **exact**.
This is the payoff of the measurement study: the shape of the measured warm-up curve
is what makes whole-workflow depth optimisation tractable rather than an NP-hard
search.

### Theorem 4b (REFUTED): parallel composition does *not* preserve convexity **[refuted]**

I claimed the same for the parallel case, by the continuous argument that
`φ(b₁,b₂) = max(F₁(b₁), F₂(b₂))` is jointly convex and partial minimisation over the
affine slice `b₁+b₂=b` preserves convexity. **That argument is correct in the
continuous relaxation and fails on the integer grid.** Minimal counterexample:

```
F₁ = F₂ = [1, 0, 0]                        both convex, non-increasing
F₁ ‖ F₂ = [1, 1, 0]                        Δ² at b=0  =  1 − 2·1 + 0  =  −1  < 0
F₁ ; F₂ = [2, 1, 0]                        convex, as Theorem 4a says
```

One unit of budget cannot help a *pair* of parallel branches — it fixes one and leaves
the other on the critical path — while two units can. **This is the same
complementarity that refutes submodularity above**; the two negative results are one
fact seen twice. Empirically only 5/120 random parallel compositions are convex.

**Consequence.** Series/chain nodes get the `O(S)` slope merge; parallel nodes need
Theorem 3's full `O(S²)` convolution, which remains exact. Overall:
`O(|V|·S)` for chains, `O(|V|·S²)` when parallel nodes are present.
Partial minimisation on the grid would need L♮/M♮-convexity (Murota's discrete convex
analysis) to go through, and `max` does not preserve it.

---

## 5. Capacity: why workflows need snapshots and keep-alive cannot substitute

This section formalises an effect exp10 produced by accident (see `RESULTS.md`,
Experiment 10, capacity arm).

### Theorem 5 (capacity bound on keep-alive) **[proved]** **[measured]**

*Let the host have memory budget `M`, and let stage `v` require `m_v` resident memory
to remain warm. Under any keep-alive policy, the set `W ⊆ V` of simultaneously warm
stages satisfies `Σ_{v∈W} m_v ≤ M`. Hence if `Σ_{v∈V} m_v > M`, the number of stages
that cannot be warm is at least*

```
k ≥ ⌈ ( Σ_{v∈V} m_v − M ) / max_v m_v ⌉ > 0
```

*and every invocation of the workflow pays a full cold start on at least `k` stages,
**regardless of arrival rate, keep-alive timeout, or prediction quality**.*

**Proof.** Let `k = |V \ W|`. Then
`Σ_{v∈W} m_v ≥ Σ_{v∈V} m_v − k · max_v m_v`. Residency requires
`Σ_{v∈W} m_v ≤ M`. Combining gives
`Σ_{v∈V} m_v − k · max_v m_v ≤ M`, i.e. `k ≥ (Σ_v m_v − M)/max_v m_v`. ∎

**Corollary 5a (homogeneous chain).** A depth-`d` chain with per-stage memory `m` can
be fully warm iff `d ≤ M/m`. Beyond that depth the cold cascade is **structural**.

**Corollary 5b (the regime argument, and this is the thesis's claim).** A snapshot
occupies *storage*, not resident memory. So for the `k` stages that keep-alive
provably cannot hold, snapshotting reduces per-invocation cost from `A_v + R_v(0)` to
`r_v + R_v(K)`, while keep-alive's benefit is capped at `M/m` stages no matter what.
**The advantage of snapshotting over keep-alive grows without bound in workflow
depth.** This is a statement about workflows specifically, it is language-independent,
and it is provable.

**[measured]** — exp10, python, `m = 512 MB`, `M = 1024 MB`. Corollary 5a predicts full
warmth iff `d ≤ 2`. Observed cold/warm ratio: **305× at d=1, 393× at d=2, 1.01× at
d=3, 1.09× at d=5, 1.15× at d=8** — the workflow stops being warmable at exactly the
predicted depth. The `M = 8192 MB` arm is the control, and its prediction (warm at all
tested depths) was registered before the run.

### Theorem 6 (keep-alive vs snapshot threshold) **[proved]**

*Let invocations of stage `v` arrive with inter-arrival time `X`, and let keep-alive
use timeout `T`. Expected added latency per invocation is `P(X > T)·(A_v + R_v(0))`
under keep-alive and `r_v + R_v(K)` under snapshotting. Snapshotting has the lower
expected latency iff*

```
P(X > T) > ( r_v + R_v(K) ) / ( A_v + R_v(0) )
```

*For exponential inter-arrivals with rate `λ`, this is `λ < λ*` where*

```
λ* = −(1/T) · ln[ ( r_v + R_v(K) ) / ( A_v + R_v(0) ) ]
```

**Proof.** Immediate from the two expectations; the exponential case substitutes
`P(X>T) = e^{−λT}` and solves for `λ`. ∎

Combined with Theorem 5 this yields a **partition of the DAG**: stages with
`λ_v ≥ λ*_v` *and* which fit in the residency budget are kept warm; all others are
snapshotted. The `λ_v` come from the Azure traces — **which finally gives the traces
cited in the proposal a concrete job.**

---

## 5b. Verification status

`./verify.py` — **14/15 checks pass**; the one failure is the intentional record of a
refuted claim. Two controls are designed to fail and do.

| claim | status |
|---|---|
| Lemma 1 (raw curves monotone) | **REFUTED** — 4/50 cells; 50–65% is noise-level |
| Lemma 1′ (underlying curve monotone, within 2 SE) | pass — 31/50 cells |
| Lemma 2 (image growth concave) | pass as *approximate* — median 100% of grid increments, but only 10/40 cells at 95% |
| Theorem 1b (DP exact) | pass — 300/300 vs exhaustive enumeration |
| Theorem 2 (greedy within one increment) | pass — 300/300; mean gap 0.87%, **worst 84.8%** |
| Theorem 3 (SP DP exact) | pass — 120/120 vs exhaustive enumeration |
| Theorem 4a (series preserves convexity) | pass — 120/120 |
| Theorem 4b (parallel preserves convexity) | **REFUTED** — 5/120; minimal counterexample found |
| Submodularity on DAGs | **REFUTED** — two-element counterexample |
| Theorem 5 (capacity) | pass — predicts the measured transition for 3 runtimes × 2 memory sizes |
| Theorem 6 (λ\* threshold) | pass — finite and positive on a real profile |

**Two bugs in this file were caught by its own controls**, which is the reason they
exist: the DP had an off-by-one giving it one extra unit of budget (it beat brute force
by returning infeasible solutions, 1/300), and the instance generator produced
fractional storage the DP silently rounded (2/300). Both were found by exhaustive
enumeration, not by inspection.

## 6. What this model still needs

| gap | closed by |
|---|---|
| ~~`r_v(K)` is unmeasured~~ — **CLOSED 2026-09-24, exp11 + exp12** | CRaC restore measured: **2.8–15 ms** restore-to-first-response, ~200–240 ms wall clock, image 27–32 MB and **flat in K**. Caveat: light handler only; Spring Boot sweep is the next run. |
| `s_v(K)` turns out to be nearly flat | exp11 measured 27–32 MB across K=0…200 against ~1.3 MB of code-cache growth — so **storage is dominated by the number of snapshots, not their depth**, which simplifies the knapsack. Lemma 2 still holds; it just matters less than assumed. |
| Lemma 1's monotonicity holds only where the curve is clean | reported per-cell by `verify.py`; used only where it passes |
| Theorem 5 verified at one `(m, M)` pair | sweep `M` — the harness now takes `--budget` |
| General (non-SP) DAGs | open; Theorem 3 covers what workflow languages express |
| `λ_v` not yet extracted | Azure traces, per §5 |

## 6b. What exp12 did to the model (2026-09-24)

**The benefit side is now measured, and the model's estimate of it was wrong.**
`MODEL.md` defines `R_v(K)` as the tail sum of the warm-up curve, which is what exp6
used to derive `captured(K)`. exp12 restored real CRaC snapshots of a Spring Boot
workload and measured the residual directly. The derived figure **overstates capture
by up to 29 percentage points, and the error grows as CPU shrinks** (agreement within
~10 pp at 4 vCPU, badly off at 0.25).

Cause: `R_v(K) = Σ_{i≥K} e_v(i)` assumes a restore preserves everything the process had
learned by request `K`. It does not — checkpointing forces a safepoint and a GC, and
the restored process re-profiles and recompiles part of what it had.

**The fix is a correction factor, and it should be measured rather than assumed:**

```
R_v^restore(K) = R_v(K) + L_v(K)        L = warm-up lost to the checkpoint itself
```

`L_v(K)` is exactly what exp12 measures (the gap between the two curves). It is small
at high CPU and large at low CPU, which is consistent with the same
compilation-work-vs-available-CPU mechanism that drives the whole thesis: work the
restore has to redo costs more when there is less CPU to redo it with.

Theorems 1–5 are untouched — they take `R_v` as an input and do not care how it is
obtained. What changes is the *calibration*: the optimiser must be fed
`R_v^restore`, not `R_v`, or it will over-value shallow snapshots.

## 7. How this reorganises the thesis

| chapter | content | status |
|---|---|---|
| 1. Problem | cascade is 98.6–98.8% of end-to-end, linear in depth (exp2, exp10) | **done** |
| 2. Calibration | A/B/C per runtime, the vCPU cliff, `B ≈ 0.185·W`, depth sweep (exp3–9) | **done** — demoted from headline to model input |
| 3. Model | this document | **drafted, proofs verified** |
| 4. Mechanism | workflow-derived priming: the DAG supplies the priming workload for free | **S1/S2 done** (exp11, exp12): CRaC restore works, depth measured on a real framework, `captured(K)` corrected. Workflow-level priming still to build. |
| 5. Evaluation | optimiser vs SnapStart (K=0), Prebaking (K=1), C1 flag, keep-alive | **not started** |

The language-dependent measurement result stops being the headline and becomes
Chapter 2. The contribution becomes the model plus the mechanism, both general.
