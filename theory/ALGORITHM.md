# The algorithm, and the known problem behind it

Written 2026-09-27, answering "somewhere there must be an algorithm for the approach, and it
should be solved using one of the known problems". Companion to `DAG_SNAPSHOT_THEORY.md` (the
theorems) and `../ideas/PAPER_NOTES.md` (what the 28 papers give us). Every claim here is
checked in `verify_dag.py`, sections **A1–A5** and **P9**.

---

## 0. In one paragraph

Scheduling snapshot restores inside a workflow is a **project-scheduling problem**. It is
known in operations research as the *(multi-mode) resource-constrained project scheduling
problem with time lags*, **(M)RCPSP/max**. Each stage's sandbox is one activity: it lasts from
the start of its restore to the end of its run and holds its memory the whole time. Each DAG
edge is a time lag. Memory is the scarce resource. The snapshot choice is the activity's
*mode*. The pieces this thesis proves are the special cases of that problem that can be solved
exactly: without a memory cap it is a longest-path problem (Theorems 1–2); the snapshot choice
on a series-parallel DAG is a time–cost trade-off solved by a DP (Theorem 7); a chain under a
cap has a closed form (Theorem 8(b)). The general capped case is NP-hard. For it we use the
textbook exact method, branch and bound on *forbidden sets*, when the workflow is small, which
covers most real ones. Otherwise we use a list-scheduling heuristic, the memory guard. The
exact solver shows how far the guard is from the optimum.

---

## 1. The problem

| | |
|---|---|
| **given** | the workflow DAG; per stage `v` its profiled restore time `r_v`, run time `w_v`, memory `m_v`; the edge delay `δ`; a memory budget `C`; per function the snapshot options (modes) and their storage |
| **decide, at build time** | each stage's mode: cold, or a snapshot of a given depth, stored locally or remotely |
| **decide, at run time** | `τ_v`, when to start restoring each stage, for each cold workflow arrival |
| **objective** | the workflow's latency (makespan); then memory·time |
| **constraints** | a stage runs only after its restore and its input; memory in use ≤ `C` at every instant; nothing starts before the workflow arrives (no arrival prediction); storage or money within budget |

### The key step: a sandbox is one activity, an edge is a time lag

**Lemma A1 (no idle sandbox).** Some optimal schedule never lets a restored sandbox wait for
its input. *Proof.* If `τ_v + r_v < I_v` (restore done before the input `I_v` arrives), move
the restore later to `τ'_v = I_v − r_v`. The stage still starts at `I_v`, so no finish time
changes. It holds memory on `[τ'_v, F_v) ⊂ [τ_v, F_v)`, so memory in use never rises. ∎

So stage `v` becomes **one activity of fixed length `p_v = r_v + w_v`** that holds `m_v`. The
edge `u → v` becomes a **start-to-start time lag**:

```
τ_v  ≥  τ_u + p_u + δ − r_v          (look-ahead)
τ_v  ≥  τ_u + p_u + δ                (restore-on-demand, today's platforms)
τ_v  ≥  0                            (the workflow arrives at 0)
```

**Look-ahead is exactly "shorten every precedence lag by the successor's restore time".**
The lag can be negative: `v`'s restore may start before `u` has even started.

*Example.* A 3-stage Java chain, `r = 650`, `w = 75`, `δ = 2` ms, so `p = 725`.
- On demand each lag is 727 ms: `L = 3·725 + 2·2 = 2179` ms. This is the linear cascade; each
  stage adds `r + w + δ`.
- Look-ahead makes each lag `727 − 650 = 77` ms: `L = 650 + 3·75 + 2·2 = 879` ms. Each stage
  now adds only `w + δ`.

Two consequences that simplify everything else:
- **Memory·time is the same for every no-idle schedule**: `Σ_v m_v (r_v + w_v)`. That is
  Theorem 2's minimum. Schedules differ only in *when* they hold memory, and that is exactly
  what the cap limits.
- **The earliest-start schedule of this lag network is the JIT schedule** `τ_v = S*_v − r_v` of
  Theorem 2 (A1 checks this on 1000 DAGs). With the on-demand lags, it is today's on-demand
  schedule.

---

## 2. Which known problem, and what is known about it

| project scheduling (OR) | our problem |
|---|---|
| project | one cold workflow invocation |
| activity | one stage's sandbox: restore + run, length `r_v + w_v` |
| mode of an activity | how the stage is provisioned: cold boot; snapshot of depth `K`, local or remote; restore + re-warm (Idea 4) |
| generalised precedence (time lag) | DAG edge: `τ_v ≥ τ_u + p_u + δ − r_v` |
| renewable resource | memory (budget `C`); optionally restore channels (§6) |
| non-renewable resource | snapshot storage, or money |
| makespan | workflow latency |
| release date | the workflow's arrival |

The problem is **MRCPSP/max** (De Reyck & Herroelen 1999). With the modes fixed it is
**RCPSP/max** (Bartusch, Möhring & Radermacher 1988; book: Neumann, Schwindt & Zimmermann 2003).
Each theorem of the thesis solves one of its tractable special cases, or, for keep-alive, a
neighbouring problem:

| case | known problem | how hard | our result |
|---|---|---|---|
| no cap, modes fixed | temporal scheduling: longest paths in the lag network (CPM) | `O(V+E)` | Theorems 1–2: `L* = max_v (r_v + ℓ(v))`, JIT = earliest start, memory·time minimal |
| + random durations | stochastic PERT; ORION's CONV/MAX gives each input-time distribution | per stage | Theorem 3: be ready at the κ-quantile (newsvendor) |
| + if/else branches | GERT-style probabilistic networks; Xanadu's most likely path | per branch | Theorem 4: speculate iff `P ≥ κ` |
| choose modes, no cap | **discrete time–cost trade-off** (DTCTP) | strongly NP-hard on general DAGs (De et al. 1997); solvable by series/parallel reduction on SP DAGs (Demeulemeester et al. 1996) | Theorem 7: exact `(storage, W, P)` DP on SP DAGs; Corollary 7.3 for prices and SLOs. Chains with prices are Costless's constrained shortest path, but look-ahead latency is not a sum, hence `(W, P)` |
| cap, equal chain | RCPSP/max, special structure | closed form | Theorem 8(b), **now shown optimal** (A3) |
| cap, general | **RCPSP/max, one resource** | NP-hard in the strong sense: with `r = 0`, `δ = 0`, `m_v = 1`, it is `P\|prec\|C_max` (Ullman 1975) | exact branch and bound (§3) for small DAGs; the memory guard (Theorem 8(c)) as an online list-scheduling heuristic |
| keep-alive between invocations (a neighbouring problem) | online weighted caching (GreedyDual-Size, GDSF) | online | Theorem 6 + Proposition 9 (§7): for a cold arrival, a warm sandbox's value is not per function; as an eviction policy this loses in simulation (e8), so per-function GDSF is used |

**What is ours and what is not.** The problem class, the branch and bound and the heuristics
are textbook OR. What is ours: the modelling (Lemma A1 turns a snapshot-restoring workflow
into this problem); the special cases solved exactly and proved; the SP DP with the `(W, P)`
state; Proposition 9; and the measurements that feed the model. Say it this way in the
thesis. Examiners like "we reduced it to a known problem and solved the tractable cases
exactly" much more than a home-made heuristic.

---

## 3. The exact solver (for small workflows)

**Branch and bound on forbidden sets** (Bartusch et al. 1988), in `verify_dag.py`
`exact_capped`:

```
EXACT(G, C):
  best ← the guard's latency (or capped on-demand, whichever is lower)
  search(no extra constraints)

search(E):                        # E = extra "u ends before v starts" constraints
  τ ← earliest start of the lag network + E        # longest paths; none if E has a positive cycle
  if makespan(τ) ≥ best: return                     # τ is a lower bound for everything below
  F ← a set of stages running at the same instant in τ whose memory exceeds C, made minimal
  if no such F: best ← makespan(τ); return          # feasible: a new best schedule
  for every ordered pair (u, v) in F:               # some pair of F must be ordered:
      search(E ∪ {τ_v ≥ τ_u + p_u})                 #   otherwise all of F overlap at one instant
```

*Why it is exact.* Intervals that overlap pairwise all share a common point (the Helly
property of intervals). So a feasible schedule must put some `v` of `F` after some `u` of `F`,
and the loop covers every such choice. Each branch's earliest-start schedule is the pointwise
earliest schedule meeting its constraints, so its makespan bounds the whole branch from
below.

**Checked** (A2): it equals a brute force over *all* integer trigger vectors, with idle
sandboxes allowed, on 200 small DAGs. With integer data an integer optimum exists, because
each branch is a system of difference constraints, whose matrix is totally unimodular.

**Speed** (pure Python, one core, random DAGs, caps 1–4× the largest stage; `exact_scale.py`):

| stages | chain: median / p95 / max | DAG: median / p95 / max |
|---|---|---|
| 4 | < 0.1 ms / < 1 ms / < 0.1 s | < 0.1 ms / < 1 ms / < 0.1 s |
| 6 | 0.1 ms / 1 ms / < 0.1 s | 0.2 ms / 2 ms / < 0.1 s |
| 8 | 0.4 ms / 5 ms / 0.1 s | 1.6 ms / 135 ms / 1.3 s |
| 10 | 1.2 ms / 55 ms / 1.1 s | 21 ms / 12 s / 31 s (8 of 200 hit the 200k-node budget) |

ORION's Azure data puts the median DAG depth at 3 and P95 at 8, and SeBS-Flow finds that most
workflows have ≤ 10 functions. **Exact planning at arrival time is affordable for the
workflows that exist.** The tail grows fast from 10 stages on: a 10-stage DAG takes 21 ms at the
median but 12 s at p95. So the planner runs with a node budget (`limit=`). With 20k nodes on
10-stage DAGs this Python code takes 172 ms at the median and at most 4 s, and 22% of runs hit
the budget. Compiled code would be much faster. A run that hits the budget returns the best
schedule found so far, which is never worse than the guard's, because the search starts from
it.

---

## 4. The algorithm

Four parts. Part 2 is new relative to the policy already in `DAG_SNAPSHOT_THEORY.md` §0; part 4
is existing work (FaasCache/CIDRE), chosen by experiment e8.

**Algorithm 1: BUILD (per function, on each deploy; no user data)**
```
1  profile with the developer's test requests: A, B, r(K), s(K), m   (at the serving vCPU)
2  snapshot points: after start-up; for Java also after warm-up, stopping when JIT
   compile counters flatten (Proposition 8); prime on a big machine with the JVM
   pinned to the serving CPU shape (Idea 5)
3  modes per stage: cold | snapshot(K) local | snapshot(K) remote | snapshot(K) + re-warm
4  choose modes: Theorem 7's (storage, W, P) DP on the SP tree   → Pareto front
   pick a point by storage budget, price (Corollary 7.3) or SLO
5  checkpoint with reset hooks (RNG, UUIDs, secrets)
```

**Algorithm 2: PLAN (per cold workflow arrival)**
```
1  W ← stages that have an idle warm sandbox;  set r_v ← 0 for v in W
2  build the lag network (Lemma A1); τ ← its earliest-start schedule (= JIT, Theorem 2)
3  C_w ← memory this workflow may use now (free memory, or the operator's share)
4  if peak(τ) ≤ C_w: return τ                              # optimal (Theorems 1–2)
5  τ ← EXACT(G, C_w) with a node budget (§3), seeded with the guard's schedule
6  return τ                                                # the planned triggers
```
Under uncertainty, use each stage's κ-quantile durations (Theorem 3) in step 2.

**Algorithm 3: RUN (event-driven, shared by all workflows on an invoker)**
```
on trigger τ_v:     queue v's restore          (never before its planned trigger)
on input of v:      if v is queued, it becomes a demand stage (moves to the front)
admission:          strict head-of-line; demand stages first, then by planned trigger
if a demand stage does not fit:
                    preempt admitted look-ahead sandboxes whose input has not arrived
                    (latest trigger first); they re-queue
on a stage finishing much earlier or later than planned (optional):
                    re-plan the remaining stages (receding horizon, as in the MPC paper)
```
This is Theorem 8(c)'s guard, now fed the *planned* triggers instead of the JIT ones. A5
checks that with exact durations it executes the plan exactly: latency = the optimum, no
preemption, cap never exceeded (800/800). With wrong durations the guard still keeps its
Theorem 8(c) guarantees: never over the cap, and no deadlock.

**Algorithm 4: KEEP-ALIVE (between invocations)**
```
evict idle sandboxes per function by GreedyDual-Size-Frequency (FaasCache / CIDRE):
priority = clock + frequency × restore cost / memory
```
The workflow-level eviction that Proposition 9 suggests was tried in the simulator (e8, §7)
and **loses**; per-function GDSF wins.

---

## 5. How good is each part (measured by the exact solver)

**The guard alone vs the optimum** (A4, 3000 (DAG, cap) pairs, 3–8 stages; plus the size
sweep above):

| | guard optimal on | mean gap | p95 gap | max gap | capped on-demand, mean gap |
|---|---|---|---|---|---|
| chains, 3–8 stages | 77% | 3.0% | 19.7% | 71.7% | 107% |
| DAGs, 3–8 stages | 67% | 4.8% | 26.2% | 86.8% | 80% |
| DAGs, 8 stages (size sweep) | 33% | 11.5% | 41.0% | 58.4% | |
| DAGs, 10 stages (size sweep, 192 solved) | 21% | 13.9% | 38.1% | 69.6% | |

The guard beats today's behaviour (capped on-demand) by a wide margin, but it leaves 5–14% on
average, and sometimes much more, on the table as DAGs grow. Trying three priority rules
instead of one barely helps (4.3% vs 4.8% on DAGs). **Planning at arrival (Algorithm 2)
closes the gap to zero** wherever the exact search finishes.

**Why the guard loses: an example.** A Python entry (60 ms restore, 20 ms run, 256 MB) feeds a
Java → Java chain (650 + 75 ms, 512 MB each) and an ML stage (180 + 300 ms, 1 GB). The cap is
1 GB.
- Without a cap, look-ahead takes 802 ms, but holds 2.3 GB at its peak.
- **Guard: 1930 ms.** When the entry finishes, the ML stage's input arrives first, so the
  guard (demand first) gives it the memory. The Java chain, the long pole, waits.
- Capped on-demand: 2012 ms.
- **Optimum: 1285 ms.** Restore the entry and Java 1 at 0, and Java 2 at 80 ms (when the entry
  frees its memory). Make the ML stage wait until 805 ms, although its input has been there
  since 80 ms: it is short enough to finish behind the chain.

The guard reacts to whoever is ready. The plan knows which stage is the long pole. This is
the classical reason list scheduling is not optimal (Graham 1969).

---

## 6. Restore contention (β) in the same model

"What could kill it" (Idea 1) is restores slowing each other down: one disk, or one core
replaying CRIU's system calls (Spice), or Docker's own concurrency limit (Xanadu, Fork in the
Road). In scheduling terms, that is a **second renewable resource**: `c` restore channels, each
restore holding one channel for `r_v`. `exact_capped(..., chan=c)` handles it.

**Corollary A3 (chains with `c` restore channels).** On a chain of equal stages:
`τ_v = max(τ_{v−1} + w + δ,  τ_{v−c} + r)`, and this is optimal. On a long chain each stage
costs **`max(w + δ, r/c)`**: each channel divides the restore cost, just as each memory slot
does in Theorem 8(b). (Checked A3: exact solver = recurrence, and the rate formula.)

5-stage Java chain (`r 650, w 75`), on demand 3.63 s:

| restore channels `c` | 1 | 2 | 4 | 9 |
|---|---|---|---|---|
| look-ahead latency | 3.33 s | 2.02 s | 1.38 s | 1.03 s |

`c = 1` is the "fully serialised" row of `IDEAS.md`'s β table: barely better than on-demand.
`criu-box/x2` measures how many restores the S0 box really runs in parallel. That number is
`c`.

---

## 7. Proposition 9: under look-ahead, keep-alive is all-or-nothing per workflow

Keep-alive policies (FaasCache, CIDRE) value a warm sandbox at *its own* cold-start cost. That
is right on demand, where every stage's restore adds to the latency. Under look-ahead it is
wrong.

**Proposition 9.** Take a workflow with one entry. Let `W` be the set of stages with an idle
warm sandbox when it arrives, and `ℓ(v)` the longest warm path from `v` to the end. Then
(a) the look-ahead latency is `L(W) = max( ℓ(entry),  max_{v ∉ W} (r_v + ℓ(v)) )`;
(b) the best `k` stages to keep warm are the `k` with the largest `r_v + ℓ(v)`;
(c) on a chain of `d` equal stages, keeping the first `j` warm saves `min(r, j(w+δ))` for
`j < d`, and `r` when all `d` are warm.

*Proof.* (a) Theorem 1 with `r_v = 0` for warm stages. (b) By (a) the latency depends only on
the largest `r_v + ℓ(v)` left outside `W`, so a top set is best. (c) `ℓ(0) − ℓ(j) = j(w+δ)`. ∎
(Checked P9 against brute force over all `k`-sets.)

*Example.* 5-stage Java chain, all restored: 1033 ms. Keeping stages warm saves:

| warm | first 1 | first 2 | first 3 | first 4 | all 5 |
|---|---|---|---|---|---|
| saving | 77 ms | 154 ms | 231 ms | 308 ms | **650 ms** |

A per-function policy thinks the entry alone saves 650 ms. It saves 77 ms: the next stage's
restore is now the long pole. **Control:** the per-function valuation overstates the saving
for 99% of stages on random DAGs.

*What this means, and what the simulator says (e8).* Proposition 9 is exact for a **cold**
arrival that look-ahead serves. So it suggested evicting whole workflows instead of single
functions. `ideas/sim` e8 tested that on the Azure trace at 16, 24, 32 and 48 GB:

| policy (24 GB, Azure trace, 433k invocations) | mean | p99 | cold-workflow mean | over-budget starts | restores |
|---|---|---|---|---|---|
| look-ahead + per-function LRU (today's default) | 267 ms | 1343 ms | 814 ms | 1,838 | 140k |
| look-ahead + **per-function GDSF** (FaasCache/CIDRE) | **258 ms** | **1193 ms** | 817 ms | **1,081** | 144k |
| look-ahead + whole-workflow eviction (Prop. 9) | 295 ms | 1759 ms | 822 ms | 8,529 | 178k |
| look-ahead + workflow priority, evict only what is needed, tail stages first | 276 ms | 1475 ms | 817 ms | 3,014 | 149k |
| look-ahead + LRU + "all stages" gate | 266 ms | 1220 ms | 815 ms | 2,339 | 158k |

- **Keep-alive does not change cold workflows** (~0.81 s under every policy): nothing of theirs
  is warm anyway. It only changes the *hot* traffic.
- **Whole-workflow eviction is worse.** It does cut arrivals that find a workflow partly warm
  (17.7k → 2.7k), but it throws away more warm sandboxes than needed: 27% more restores and
  4.6× more over-budget starts. Evicting only what is needed, tail stages first, is better
  but still behind LRU at 16–24 GB, and equal at 32–48 GB.
- **Why the proposition does not transfer.** Most arrivals are *hot* (the workflow ran within 10
  minutes). The gate then skips look-ahead, so a missing stage is restored on demand and costs
  its **full** restore time. For hot traffic, the per-function valuation is the right one.
- **Per-function GDSF is the best keep-alive**, modestly: at 24 GB, mean −3%, p99 −11%, and 41%
  fewer over-budget starts than LRU. It helps on-demand restore too (mean −7%). This is
  existing work (FaasCache, CIDRE), and the thesis adopts it rather than claiming it.
- Proposition 9 stays as a statement about cold arrivals. It is also why the simple entry gate
  (Lemma 5) is only approximate: a partly warm workflow still benefits from look-ahead for its
  cold stages. Planning with warm stages as `r = 0` (Algorithm 2, step 1) is the general form.
  The "all stages" gate helps p99 a little (1220 vs 1343 ms) at the cost of more restores.

---

## 8. Where the inputs come from (from `PAPER_NOTES.md`)

| model input | source |
|---|---|
| `r` per runtime and vCPU | our exp (Spring Boot restore 0.64–9 s by CPU quota and image size); Prebaking (Java start-up 150–1100 ms, Python 430–480, JS 83–150; CRIU restore of a small process 8 ms); Spice (CRIU is syscall replay, seconds for large functions); REAP (lazy restore is fast but pays page faults inside `w`) |
| `A` (cold start) | Huawei trace (mean 0.3–3 s by region, with components); Prebaking per runtime |
| `w` and its variance | ORION (median E2E 3.7 s; P95 = 80× P25 for the same DAG, so Theorem 3's quantile matters); SeBS-Flow benchmarks |
| DAG shapes | ORION (depth median 3, P95 8; 65% chains); SeBS-Flow (40% sequential, most ≤ 10 functions); Azure 2021 (our e4) |
| arrival rates | ORION (80% of DAGs run < 100 times/day, with a median 50% cold starts); Azure 2021 |
| memory `m`, sharing | Replayable (mmap restore shares one image copy: 2× less memory); HighCostOfKeepingWarm (2–10× over-provisioning) |
| restore channels `c` (β) | Xanadu (eager is slower than JIT under Docker), Fork in the Road (×24 concurrency: 110 → 45 starts/s), PCPM (network-namespace contention), Spice (CPU-bound restore); **x2 on the box** |
| keep-alive TTL | Huawei 1 min; OpenWhisk 10 min; AWS Step Functions ~10 min; Azure Durable ~20 min |

---

## 9. References to cite (classic OR)

- M. Bartusch, R. H. Möhring, F. J. Radermacher. Scheduling project networks with resource
  constraints and time windows. *Annals of OR* 16, 1988. (RCPSP/max; forbidden-set branching)
- K. Neumann, C. Schwindt, J. Zimmermann. *Project Scheduling with Time Windows and Scarce
  Resources.* Springer, 2003.
- B. De Reyck, W. Herroelen. The multi-mode resource-constrained project scheduling problem
  with generalized precedence relations. *EJOR* 119, 1999.
- P. De, E. J. Dunne, J. B. Ghosh, C. E. Wells. Complexity of the discrete time–cost tradeoff
  problem for project networks. *Operations Research* 45, 1997.
- E. Demeulemeester, W. Herroelen, S. E. Elmaghraby. Optimal procedures for the discrete
  time/cost trade-off problem in project networks. *EJOR* 88, 1996.
- R. Kolisch. Serial and parallel resource-constrained project scheduling methods revisited.
  *EJOR* 90, 1996. (list scheduling / schedule-generation schemes: what the guard is)
- R. L. Graham. Bounds on multiprocessing timing anomalies. *SIAM J. Appl. Math.* 17, 1969.
- J. D. Ullman. NP-complete scheduling problems. *JCSS* 10, 1975.
- P. Cao, S. Irani. Cost-aware WWW proxy caching algorithms. USITS 1997 (GreedyDual-Size);
  L. Cherkasova, HP Labs 1998 (GDSF); A. Fuerst, P. Sharma, FaasCache, ASPLOS 2021.
- Serverless: Xanadu, ORION, Costless, Żuk & Rzadca, CIDRE, MPC (see `PAPER_NOTES.md`).
