# The CPU plan: theory

*Written 2026-09-29. Companion to `DAG_SNAPSHOT_THEORY.md` (report 1's theorems, which this
extends) and `ALGORITHM.md` (the problem as project scheduling). The design and the simulation
results are in `../ideas/CPU_PLAN.md`. The code is in `../ideas/sim/cpuplan.py` (the exact plan) and
`../ideas/sim/dagsim.py` (`Policy.boost = "plan"`, the online rule; `Policy.lazy`, just in time).
Every result below is checked in `verify_dag.py`, section CP: 21 checks, 5 of them controls
designed to fail, which they do. With the new section, `verify_dag.py` passes 97/97. Tags as in `DAG_SNAPSHOT_THEORY.md`:
**[proved]**, **[verified]**, **[measured]**, **[assumption]**. In the thesis chapter
(`../thesis/ch_theory.tex`, §4.9) these results are Definition 4.24 to Proposition 4.33 and
Algorithm 5; there the spare CPU is written `Π`, because `P` names paths.*

---

## 0. In one page

Report 1 gave every start-up a fixed speed: a restore took `r_v`. The CPU plan makes the speed a
decision. A start-up is CPU work, and the platform decides how much of the server's spare CPU each
start-up gets, and when.

| result | statement | status |
|---|---|---|
| **Lemma CP1** | Whatever CPU the start-ups get, the workflow finishes by `Λ` iff every stage is ready by `Λ − ℓ(v)`. Each start-up has its own deadline. | proved, verified (2000 DAGs) |
| **Theorem CP2** | For a latency target, "can every start-up meet its deadline?" is a max-flow problem. Binary search on the target gives the exact optimum, and the flow gives each start-up's CPU over time. | proved; verified against an exhaustive min-cut condition (3000 instances); plan sound and optimal (500 DAGs) |
| **Proposition CP3** | With no spare CPU the optimum is report 1's `L*` with `r_v = U_v/q_v`. With unlimited spare CPU it is `L_ideal`. Report 1 is the fixed-CPU special case. | proved, verified |
| **Proposition CP4** | With at most one start-up's worth of spare CPU, the optimum runs start-ups one at a time, earliest deadline first. On a chain, look-ahead then gains at most `Σ_{v<d} (w_v + δ)` over restoring on demand with the same boost, and this is tight for CPU-bound chains. | proved, verified |
| **Proposition CP5** | A speculative start-up that gets only leftover CPU never delays a certain one. | proved, verified |
| **Proposition CP6** | With at most one spare core, a speculative start-up served as certain and not taken delays a CPU-bound chain by exactly `U_s/P`. So speculation pays only if `p · gain ≥ (1 − p) · U_s/P`. | proved, verified |
| **Proposition CP7** | A burst with at most one spare core: earliest deadline first across workflows minimises the largest lateness (Horn 1974). With more spare CPU it is not optimal, and the exact plan is needed. | proved (known result), verified |
| **Proposition CP8** | Just in time. Holding each start-up back to its latest start (the latest release that keeps CP2's network feasible) keeps every target reachable, and no start-up can start later. With one spare core, one start-up at a time, each holding memory only from its first CPU, reaches both the optimal latency and the least memory·time on a CPU-bound chain. | proved, verified |
| online rule | Balanced rates for one workflow, earliest deadline first for several, speculation only on leftover CPU; each certain start-up held back to its latest start. | within 0–9% of CP2 on test cases (e11o); the burst choice is empirical (e11b); just in time: latency −8% to +1.3%, memory·time up to 88% lower for one workflow and 76–82% lower in a burst (e11a, e11b) |

---

## 1. Model

A workflow `G = (V, E)` with one entry arrives at time 0, as in report 1 (`DAG_SNAPSHOT_THEORY.md`
§2). Each stage `v` has:

- a **start-up**: CPU work `U_v` (CPU-seconds), a snapshot restore plus the first request's
  residual warm-up, or a cold boot plus the full warm-up;
- a **cap** `c_v`: the most CPU the start-up can use (about one core for a JVM pinned to one CPU);
- a **quota** `q_v ≥ 0`: CPU reserved for this start-up alone. The simulator's plan uses
  `q_v = 0`: the platform sets each starting sandbox's CPU limit, so start-ups are guaranteed
  nothing;
- **steady work** `w_v`: the wall time of the stage once started, at its normal CPU share;
- and each edge adds `δ`.

The server has **spare CPU** `P(t)`: the CPU not used by running requests. A **CPU plan** gives each
start-up a rate `x_v(t)` with `0 ≤ x_v(t) ≤ c_v`, of which at most `q_v` is private, and
`Σ_v (x_v(t) − private_v(t)) ≤ P(t)`. Start-up `v` is ready at `ready_v`, when `∫ x_v = U_v`. The stages
then follow report 1's semantics: `I_e = 0`, `I_v = max_{u∈pred(v)} F_u + δ`,
`S_v = max(ready_v, I_v)`, `F_v = S_v + w_v`, latency `L = max_{sinks} F`.

| assumption | statement | status |
|---|---|---|
| B1 linear speed-up | a start-up given rate `x ≤ c` finishes `U` CPU-seconds of work in `U/x` | **measured** for JVM warm-up from 0.25 to 1 vCPU (exp-b: 4.2× faster, 0.90 vs 0.86 CPU-s); **assumption** for restores and cold starts: `MACHINE_TEST_PLAN.md` T6b |
| B2 separate requests | running requests keep their CPU share; start-ups use only the spare `P(t)` | the platform's choice (cgroup `cpu.max` per sandbox) |
| B3 known work | `U_v`, `w_v` profiled | as report 1; under uncertainty use quantiles (report 1, Theorem 3) |
| B4 look-ahead | every start-up may begin when the workflow arrives | as report 1 |

## 2. Deadlines per start-up

**Lemma CP1.** For any CPU plan, `L = max_v (ready_v + ℓ(v))`, where `ℓ(v)` is the longest warm path
from `v` to a sink (report 1's `ℓ`). Hence `L ≤ Λ` if and only if `ready_v ≤ D_v(Λ) := Λ − ℓ(v)` for
every `v`.

*Proof.* By induction in topological order,
`F_v = max_{u ⪯ v, P: u ⇝ v} (ready_u + W(P))`. At the entry, `F_e = max(ready_e, 0) + w_e = ready_e + w_e`.
For `v ≠ e`, `F_v = max(ready_v, max_{u∈pred(v)} F_u + δ) + w_v`, which extends every path into a
predecessor by one edge. At the sinks this is `max_u (ready_u + ℓ(u))`. The "iff" follows because
`L` is a maximum of terms `ready_v + ℓ(v)`. ∎

This is report 1's Theorem 1(b), with the restore finish `r_v` replaced by any ready time. The
lemma turns "shortest workflow" into "every start-up meets its own deadline". The deadlines depend
on the target `Λ` only through a common shift.

**[verified]** CP1: 2000 random DAGs with random ready times give the formula exactly, and the "iff".

## 3. The exact plan

**Theorem CP2.** Fix `Λ` and let `P(t)` be piecewise constant. Every start-up can meet its deadline
`D_v(Λ)` if and only if the maximum flow in the following network saturates every source arc:

- time points: all release times `a_v` (0 under look-ahead), deadlines `D_v(Λ)` and breakpoints of
  `P`; slices `I_k` between consecutive points;
- source → job `v`, capacity `U_v`;
- job `v` → sink (private), capacity `q_v · (D_v − a_v)`;
- job `v` → slice `k` for every `I_k ⊆ [a_v, D_v]`, capacity `(c_v − q_v)·|I_k|`;
- slice `k` → sink, capacity `P_k · |I_k|`.

Feasibility is monotone in `Λ`, so the smallest `Λ` (the optimal latency) is found by bisection to
any precision. The flow at that `Λ` is an optimal plan (within the bisection's tolerance).

*Proof.*
- **(⇐) A flow gives a plan.** In slice `k`, job `v` gets shared rate `f_vk/|I_k| ≤ c_v − q_v`,
  and these rates sum to at most `P_k`. Its private flow `g_v` is spread evenly over its window,
  at rate `g_v/(D_v − a_v) ≤ q_v`. The total rate is at most `c_v`, and the work done by `D_v` is
  `g_v + Σ_k f_vk = U_v`.
- **(⇒) A plan gives a flow.** Split each job's rate into a private part (at most `q_v`) and a
  shared part, and integrate the shared part over each slice. Every capacity is respected.
- **Monotonicity.** A larger `Λ` moves every deadline later, so every window only grows, and any
  plan for `Λ` works for `Λ' > Λ`. ∎

This is Horn's (1974) flow construction for preemptive scheduling with release times and
deadlines, with a rate cap per job. In project-scheduling terms, the start-ups are activities
whose duration depends on the resource they get: project scheduling with flexible resource
profiles (Naber and Kolisch 2014). Report 1's problems are the special case with fixed durations.

**Corollary CP2.1 (a certificate).** Suppose `q = 0` and all releases are 0. By max-flow/min-cut,
the targets are infeasible exactly when some set `T` of start-ups has
`Σ_{v∈T} U_v > ∫ min(P(t), Σ_{v∈T active at t} c_v) dt`. Such a set proves that no plan reaches
`Λ`; it is a lower bound that needs no search. The same holds with private quotas, adding
`Σ_{v∈T} q_v (D_v − a_v)` on the right.

**[verified]**
- CP2: the flow's answer equals the exhaustive subset condition on 3000 random instances with up
  to 6 start-ups, with and without private quotas.
- CP2: on 500 random DAGs, the plan's rates meet every deadline within caps and spare CPU, and a
  slightly smaller target is infeasible by the subset condition.
- **Controls:** ignoring the caps changes the answer (172 of 500 instances), so the check sees
  caps; an equal split of the spare CPU is worse than the plan on 398 of 500.

## 4. Special cases

**Proposition CP3.**
- (a) With `P ≡ 0`, the optimum is `max_v (U_v/q_v + ℓ(v))`. This is report 1's `L*` (Theorem 1)
  with restore time `r_v = U_v/q_v`: every start-up runs at its own quota from the arrival.
- (b) With unlimited `P`, the optimum is `L_ideal = max_v (U_v/c_v + ℓ(v))`.
- (c) The optimum is non-increasing in `P`.

*Proof.* (a) With no shared CPU, the fastest a start-up can finish is `U_v/q_v`, and Lemma CP1 gives
the maximum. (b) Each start-up runs at its cap from time 0. (c) A plan for `P` is a plan for any
`P' ≥ P`. ∎

So the CPU plan interpolates between report 1's fixed-CPU look-ahead (`P = 0`) and the ideal
(every start-up at full speed).

**[verified]** CP3: 500 DAGs each for (a) and (b).

**Proposition CP4 (one spare core).** Let `q_v = 0` and `P(t) ≤ c_v` for all `v` and `t`: the spare
CPU never exceeds what one start-up can use.
- (a) An optimal plan runs one start-up at a time, earliest deadline first (EDF): longest remaining
  path `ℓ(v)` first, since all deadlines are `Λ − ℓ(v)`.
- (b) On a chain of `d` stages with constant `P`, look-ahead's optimum `L*_P` and restoring on
  demand with the same boost `L_od,P = Σ_v (U_v/P + w_v) + (d−1)δ` satisfy
  `0 ≤ L_od,P − L*_P ≤ Σ_{v<d} (w_v + δ)`. Equality holds when the chain is CPU-bound, that is when
  `L*_P = Σ_v U_v/P + w_d`.

*Proof.*
- (a) Each start-up can absorb all spare CPU, so the problem is one machine of speed `P(t)`.
  Number the start-ups by deadline, `ℓ(v_1) ≥ ℓ(v_2) ≥ …`, and let `C(t) = ∫_0^t P`. EDF serves
  them one at a time in this order at rate `P(t) ≤ c`, so `v_k` is ready at `ρ_k`, the first time
  `C` reaches `U_{v_1} + … + U_{v_k}`. In any plan the total rate is at most `P(t)`, so the first `k`
  start-ups cannot all be ready before `ρ_k`: some `v_i` with `i ≤ k` has `ready_{v_i} ≥ ρ_k`, and
  `ℓ(v_i) ≥ ℓ(v_k)`. By Lemma CP1 that plan's latency is at least `ρ_k + ℓ(v_k)` for every `k`, which
  is EDF's latency. (This is Jackson's rule.)
- (b) Restoring on demand is a feasible plan (one start-up at a time, when its input arrives), so
  `L*_P ≤ L_od,P`. In any plan the last start-up to be ready, say `v`, is ready no earlier than
  `Σ U_u / P`, and `ℓ(v) ≥ w_d` on a chain, so by Lemma CP1 `L*_P ≥ Σ U_v/P + w_d`. Subtracting
  gives the bound. ∎

*Meaning.* When the server has about one core to spare, look-ahead can only overlap restores with
the stages' own run times: `Σ (w + δ)`, about 0.1 s for a 3-stage Java chain at 0.25 vCPU. That is
the tie with the Cloud Run-style boost that e11a measured on 1 core. Look-ahead's parallelism
needs more than one spare core.

**[verified]** CP4: EDF equals the exact plan on 500 DAGs, and the chain bound holds on 250 chains
(with equality when CPU-bound). **Control:** with more than one spare core, one start-up at a time
is worse than the plan on 443 of 500 instances, so the condition `P ≤ c` is needed.

## 5. Speculation

**Proposition CP5 (non-interference).** If the start-ups of stages that may not run (behind an
if/else not yet decided) get only the CPU that the certain start-ups' plan leaves, then every
certain start-up finishes exactly when it would without them.

*Proof.* The certain start-ups' allocation is computed without the speculative ones, and they use
only what is left at each instant. ∎

**Proposition CP6 (the cost of treating a guess as certain).** Under CP4's conditions, let a
speculative start-up `s` get priority as if certain, ahead of some certain start-ups, and let its
branch not be taken. Then every certain start-up after it in EDF order finishes `U_s/P` later, and
a CPU-bound chain is delayed by exactly `U_s/P`.

*Proof.* With one start-up at a time at rate `P`, inserting `U_s` of work before them shifts each
later completion by `U_s/P`. When the chain is CPU-bound, its latency is the last completion plus
`w_d`. ∎

Therefore treating a branch reached with probability `p` as certain pays only if
`p · G ≥ (1 − p) · U_s/P`. Here `G` is what restoring it early saves when the branch is taken, which
under CP4 is at most the overlap with run times, `Σ (w + δ)` along its path. With the thesis's
Java numbers on one spare core (`U_s/P ≈ 0.7 s`, `G ≈ 0.05 s`), this needs `p ≥ 0.93`. Hence the
online rule: with at most one spare core, only stages certain to run are served as certain. With
more spare CPU, the likely path is (`p ≥ 0.5`, as in report 1's Algorithm 2). This has the same
form as report 1's Theorem 4 (speculate iff `p ≥ κ`), with CPU time as the cost.

**[verified]** CP5 and CP6: 500 CPU-bound chains each.

## 6. Bursts

**Proposition CP7.** Several workflows arrive at different times, with `P ≤ c_v` and `q_v = 0`.
Give each start-up the absolute deadline `t_w + Λ_w − ℓ(v)`, where `t_w` is its workflow's arrival and
`Λ_w` its ideal latency. Preemptive EDF then minimises the largest lateness: the worst extra delay of
any workflow over its ideal.

*Proof.* Under `P ≤ c`, this is `1|r_j, pmtn|L_max`, for which preemptive EDF is optimal (Horn
1974). ∎

With more than one spare core, greedy EDF is not optimal (**control**: worse on 171 of 500
instances; the multiprocessor case, cf. Dhall and Liu 1978). The exact plan then comes from
Theorem CP2 with a common shift for all deadlines (`cpuplan.min_shift`). Two notes for the online
rule:
- the objective differs: the plan minimises the worst workflow's lateness, while e11b also reports
  the mean;
- e11b found EDF best on both for mixed bursts, while the fluid model's bursts of identical chains
  favour balanced rates.

So the burst rule is chosen from experiment, not proved.

**[verified]** CP7: EDF reaches the exact smallest largest lateness on 250 random bursts.

## 7. Just in time: memory

The plan so far starts every look-ahead start-up when the workflow arrives. A sandbox holds its
memory from then until its stage finishes, so a start-up that gets little CPU for a long time
holds memory for a long time. In the simulator this made the plan hold up to 11× the
memory·time of restoring on demand with an equal startup boost (e11a). Report 1's Theorem 2 answered the same problem for fixed restore times:
start each restore just in time. Here the start time interacts with the CPU the others get.

**Proposition CP8 (just in time).**
- (a) Let the targets `D_v` be feasible (Theorem CP2). Take the start-ups latest target first,
  and move each one's release as late as the network stays feasible. Then the final releases
  are feasible: some plan meets every target with no start-up getting CPU before its release.
  And no single release can move later.
- (b) Let a sandbox hold memory `m_v` from the first CPU its start-up gets, `σ_v`, until its stage
  finishes, `F_v`. Under the conditions of CP4 (`q = 0`, constant `P ≤ c`):
    - every plan holds at least `Σ_v m_v (U_v/P + w_v)`, the memory·time of restoring on demand
      with the same boost;
    - on a chain that is CPU-bound at every stage (`U_{v+1}/P ≥ w_v + δ`), one start-up at a time,
      in order, each holding memory only from its first CPU, attains this minimum and the
      optimal latency `Σ_v U_v/P + w_d` together.

*Proof.*
- (a) Feasibility is monotone in each release: a later release shrinks the job's window, and a
  plan for the smaller window is a plan for the larger one. The bisection accepts only feasible
  positions, so feasibility holds throughout. When start-up `v` was moved, the start-ups
  moved after it had releases no later than their final ones. Moving those later afterwards
  only removes plans, so `v` still cannot move later.
- (b) A start-up gets at most `P` at any instant, so `ready_v ≥ σ_v + U_v/P`, and
  `F_v ≥ ready_v + w_v`. One at a time, start-up `v` runs from `Σ_{u<v} U_u/P` to
  `ready_v = Σ_{u≤v} U_u/P`. If stage `v−1` started at `ready_{v−1}`, then `v`'s input arrives at
  `ready_{v−1} + w_{v−1} + δ ≤ ready_{v−1} + U_v/P = ready_v`, by CPU-boundness. So stage `v` starts
  at `ready_v`, and `F_v − σ_v = U_v/P + w_v` exactly; by induction this holds for every stage.
  The latency is `F_d = Σ U_v/P + w_d`, CP4(b)'s lower bound. ∎

This is Theorem 2 of report 1 for the CPU plan on one spare core: no trade-off between latency
and memory. With more spare CPU, (a) still guarantees that holding start-ups back loses no
feasible target. How much memory it saves is measured, not proved.

**[verified]** CP8: (a) 500 random instances, with releases feasible after the moves and none
able to move later; (b) 250 CPU-bound chains. **Control:** an equal split with every sandbox
from the arrival holds more memory on 250 of 250.

**The rule in the simulator** (`Policy.lazy`, `Sim._lazy_starts`):
- At the arrival, the workflow's start-ups and first requests become jobs of CP2's network,
  on the stages likely to run. The smallest feasible lateness `λ` gives the targets, and
  `cpuplan.latest_starts` gives each look-ahead start-up its latest start. The trigger comes a
  margin earlier: 0.3 of the time its start-up and first request take at cap.
- A start-up holds no memory and gets no CPU before its latest start. The exception is a
  CPU-bound workflow (`λ` above the all-at-cap lateness), where the next start-up runs rather
  than leave CPU idle.
- With at most one spare core, one start-up at a time (CP4, CP8(b)).
- Stages that may not run are not held back: they get only leftover CPU anyway (CP5). A branch
  not taken cancels its start-ups.
- Results (e11a, e11b; functions at 0.25 vCPU; against the plan without it):
    - one workflow, one spare core: 49–88% less memory·time at the same latency, and exactly the
      memory·time of restoring on demand for chains;
    - two spare cores: up to 73% less (router 10.6 → 2.9 GB·s), latency 8% lower to 0.7% higher;
    - four spare cores: up to 33% less, latency 3.8% lower to 1.3% higher (start-ups wait little
      there anyway);
    - a burst of 16 workflows: 76–82% less, the same latency, and less than restoring on demand
      with an equal boost.
- Controls (`run_sim.py e11x`):
    - without the CPU layer, the flag changes nothing (80/80);
    - every run gives all memory back;
    - on one spare core, a chain holds exactly the memory·time of restoring on demand with the
      boost, and finishes `(d − 1)δ` sooner: the edge delays are the only idle CPU there is to
      overlap.

## 8. The online rule, and what is not proved

The rule `dagsim` runs (`Policy.boost = "plan"`), recomputed at every event:
- **one workflow starting:** constant rates that minimise the largest lateness of its start-ups.
  These are optimal among plans that keep every rate constant from now on, by construction (a
  bisection on the lateness, monotone). They are not always optimal overall: the exact plan is up
  to 9% better on our test cases (e11o), because it can front-load CPU;
- **several workflows:** earliest deadline first. This is optimal for the largest lateness with at
  most one spare core (CP7) and chosen by experiment beyond that (e11b);
- **speculation:** leftover only (CP5), and only certain stages count as certain when at most one
  core is spare (CP6);
- **just in time:** each certain start-up is held back to its latest start (CP8(a)); with at most
  one spare core, one start-up at a time (CP4, CP8(b)).

**Not proved, and not claimed:**
- a competitive ratio for the online rule;
- the burst rule beyond one spare core;
- how much memory just in time saves with more than one spare core;
- anything about real speed-up curves (B1, to be measured).

## 9. Status

| claim | status |
|---|---|
| deadlines per start-up (CP1) | proved; verified |
| exact plan by max-flow and bisection, with a min-cut certificate (CP2) | proved; verified against exhaustive enumeration |
| report 1 as the fixed-CPU case; the ideal as the unlimited case (CP3) | proved; verified |
| one spare core: EDF optimal; look-ahead's gain bounded by `Σ (w + δ)` (CP4) | proved; verified; explains the 1-core tie in e11a |
| speculation: non-interference; cost of a wrong guess (CP5, CP6) | proved; verified |
| bursts with one spare core: EDF (CP7) | known result (Horn 1974); verified |
| just in time: latest starts keep targets; least memory·time on one spare core (CP8) | proved; verified |
| just in time with more spare CPU: same latency, less memory | measured in the simulator (e11a, e11b) |
| online rule within 0–9% of the exact plan | measured in the fluid model (e11o) |
| the burst rule beyond one spare core | chosen by simulation (e11b) |
| linear speed-up of restores and cold starts (B1) | **assumption**: T6b |

## References

- W. A. Horn. Some simple scheduling algorithms. *Naval Research Logistics Quarterly* 21(1), 1974.
  (Flow construction for preemptive deadline scheduling; EDF for `1|r_j,pmtn|L_max`.)
- J. R. Jackson. Scheduling a production line to minimize maximum tardiness. Research Report 43,
  UCLA, 1955. (EDF on one machine.)
- A. Naber, R. Kolisch. MIP models for resource-constrained project scheduling with flexible
  resource profiles. *European Journal of Operational Research* 239(2), 2014.
- S. K. Dhall, C. L. Liu. On a real-time scheduling problem. *Operations Research* 26(1), 1978.
  (EDF is not optimal on several processors.)

Run: `python3 verify_dag.py` (section CP, about 1 minute).
