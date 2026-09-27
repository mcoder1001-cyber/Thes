# Definitions, once and for all, with one running example

Every term and symbol the thesis uses is defined here, once. All examples use **the same
workflow**, so the numbers can be compared directly. Other documents (`REPORT.md`,
`theory/*.md`) use exactly these meanings.

---

## The running example

A **3-stage Java workflow**: `resize → classify → store`. Each stage is a Spring Boot function
at 1 vCPU, with the thesis's measured numbers:

| symbol | meaning | value |
|---|---|---|
| `A` | cold start: start the container, the JVM and the framework | 2510 ms |
| `B` | JIT warm-up that the first request pays after a cold start | 370 ms |
| `C` | steady-state run time of one request | 12 ms |
| `r` | restore time: bring a snapshot back to a running process | 650 ms |
| `R(K)` | leftover warm-up after restoring a snapshot taken at depth `K` | 63 ms |
| `w` | run time of the first request after a restore, `w = R(K) + C` | 75 ms |
| `m` | memory one sandbox holds | 512 MB |
| `δ` | hand-off delay between two stages (the orchestrator passes the output on) | 2 ms |

---

## 1. Basic words

- **Function / stage.** One piece of code. In a workflow, each function is a **stage**.
- **Workflow (DAG).** Stages connected by arrows: an arrow `u → v` means `v` needs `u`'s output.
  A **chain** is a workflow with no branches. The **entry** is the first stage. The **depth**
  `d` is the number of stages on the longest path (3 in the example).
- **Sandbox.** The container in which one function runs. It holds memory `m` while it is alive.
- **Warm / cold.** A sandbox that is alive and idle is **warm**: a request runs at once (`C`).
  With no sandbox, the platform must create one: a **cold start**.
- **Keep-alive.** After a request, the platform keeps the sandbox for a while (for example 10
  minutes) hoping for another request. Free if requests come often, useless if they are rare.
- **Snapshot (checkpoint).** A copy of a running process saved to disk (CRIU / CRaC). **Restore**
  loads it back, taking `r` instead of `A + B`.
- **Snapshot depth `K`.** How many warm-up requests ran before the snapshot was taken. `K = 0`
  is right after start-up (what AWS SnapStart does). A deeper snapshot contains the JIT's
  compiled code, so the leftover warm-up `R(K)` is smaller.

## 2. Times inside one workflow run

For each stage `v`:
- `I_v`: **input time**, when its input arrives (the previous stage's finish + `δ`).
- `τ_v` (tau): **trigger time**, when its restore is started.
- `S_v`: **start time** = `max(τ_v + r, I_v)`: it needs both its sandbox and its input.
- `F_v`: **finish time** = `S_v + w`.
- **Latency `L`**: from the workflow's arrival to the last stage's finish.
- **Memory·time**: memory × how long it is held, summed over sandboxes (MB·s). This is what the
  platform pays for.
- **Peak memory**: the most memory held at any one instant. The budget limits this.

---

## 3. The policies, on the running example

A workflow that has been idle arrives at time 0. Nothing is warm.

### 3.1 No snapshots (plain cold start)
Every stage cold-starts when its input arrives: `A + B + C` each.
- **Latency: 3 × 2892 + 2 × 2 = 8680 ms.** (Measured on your 3-stage workflow: 12.1 s.)

### 3.2 Keep-alive hit (the lucky case)
All three sandboxes are still warm from a recent run.
- **Latency: 3 × 12 + 4 ≈ 40 ms.** (Measured: 35 ms.) Nothing to improve. This is why the
  thesis only acts when the workflow is cold.

### 3.3 Restore on demand (what SnapStart, Prebaking and Pronghorn do)
Each stage has a snapshot, but its restore starts **only when its input arrives**
(`τ_v = I_v`). The restores happen one after another.
```
resize    [restore 650][run 75]
classify                        [restore 650][run 75]
store                                                 [restore 650][run 75]
```
- **Latency: 3 × (650 + 75) + 2 × 2 = 2179 ms.** Each stage adds `r + w`, the **linear cascade**.
- Memory: one sandbox at a time, **peak 512 MB**; memory·time 1.11 GB·s.

### 3.4 Look-ahead restore (the thesis)
When the workflow arrives, the orchestrator knows the DAG and the measured `r` and `w`. It
starts **every** stage's restore early, so that the sandbox is ready when the input arrives.
The upstream stages' own work **hides** the downstream restores.

**Eager look-ahead**: start all restores at time 0 (`τ_v = 0`).
```
resize    [restore 650][run 75]
classify  [restore 650 ]  wait [run 75]
store     [restore 650 ]    wait    [run 75]
```
- **Latency: 650 + 3 × 75 + 2 × 2 = 879 ms** (2.5× faster). Only the first restore is paid;
  each stage adds only `w + δ`.
- But `classify` and `store` sit restored and idle, waiting: memory·time 1.23 GB·s, more than
  on demand.

**Just-in-time (JIT) look-ahead** (Theorem 2): start each restore exactly `r` before the stage
will start in the eager schedule: `τ_v = S*_v − r`. Here `τ` = 0, 77, 154 ms.
- **Same latency, 879 ms**, which is the lowest any policy can reach (Theorem 1).
- **Same memory·time as on demand, 1.11 GB·s** (Theorem 2): nothing waits.
- But the **peak is 1.5 GB** instead of 512 MB, because the three sandboxes overlap in time
  (Theorem 8).

### 3.5 Cold prewarm (Xanadu, ORION: the closest earlier work)
The same just-in-time timing, but with a **cold** container instead of a snapshot: provisioning
takes `A = 2510` ms and the first request still pays `B`.
- **Latency: 2510 + 3 × (370 + 12) + 4 ≈ 3660 ms.** The cold start is too long to hide behind a
  75 ms upstream stage. That is why snapshots are the missing piece.

### 3.6 Look-ahead under a memory budget (the memory guard)
Suppose only **1 GB** is available, room for two sandboxes.
- The **memory guard** admits restores until the budget is full. A stage whose input has arrived
  goes first, and may evict a look-ahead sandbox that nobody needs yet.
- **Latency: 1450 ms.** That is between look-ahead's 879 ms and on-demand's 2179 ms. It never
  exceeds the budget and never deadlocks.
- For larger DAGs, the **planner** computes the best trigger times for the budget exactly (a
  known scheduling problem, `theory/ALGORITHM.md`), and the guard carries them out.

### Summary

| policy | latency | peak memory | memory·time |
|---|---|---|---|
| no snapshots | 8680 ms | 512 MB | — |
| cold prewarm, JIT (Xanadu) | 3660 ms | up to 1.5 GB | — |
| restore on demand (SnapStart) | 2179 ms | 512 MB | 1.11 GB·s |
| look-ahead, eager | 879 ms | 1.5 GB | 1.23 GB·s |
| **look-ahead, JIT** | **879 ms** | 1.5 GB | **1.11 GB·s** |
| look-ahead, JIT, 1 GB budget (guard) | 1450 ms | 1 GB | 1.11 GB·s |
| keep-alive hit (everything warm) | 40 ms | 1.5 GB, held all the time | large (idle memory) |

---

## 4. The other terms

- **`S*_v` (eager start).** The start time of stage `v` if every restore began at time 0. JIT uses
  it: `τ_v = S*_v − r_v`.
- **`L*`.** The lowest possible latency = `max over stages of (r_v + ℓ(v))`. Here
  `ℓ(v)` is the **remaining path**: the longest chain of `w`s and `δ`s from `v` to the end. In
  the example, `ℓ(resize) = 229`, so `L* = 650 + 229 = 879`.
- **Gate.** If the entry function has a warm sandbox, the workflow ran recently; do nothing
  special (Lemma 5).
- **κ (kappa).** Under uncertainty, how early to trigger. Be ready at the κ-quantile of the input
  time, `κ = b/(a+b)`, where `a` is the price of memory and `b` the price of latency
  (Theorem 3). The same κ decides whether to restore an if/else branch ahead: yes if its
  probability is at least κ (Theorem 4).
- **β (beta) / restore channels `c`.** Restores running at the same time may slow each other
  (one disk, CPU for CRIU). β = 0: no slowdown; β = 1: fully serialised. Equivalently, `c` =
  how many restores really run in parallel. With `c = 1` the example chain takes 2025 ms instead of
  879 ms (restores finish at 650, 1300, 1950 ms). Test `x2` measures this on the real machine.
- **Memory budget (cap).** The most memory the platform allows at once. Written `C` in
  `theory/ALGORITHM.md`. Do not confuse it with the run time `C` above.
- **Mode.** For each stage, the way it is provisioned: cold; a snapshot at depth `K` stored
  locally or remotely; or restore + re-warm. Theorem 7 chooses the mode per stage.
- **Re-warm.** Right after a restore, send the developer's test requests, so the leftover
  warm-up `R(K)` is paid before the real input arrives (Idea 4).
- **Priming / building a snapshot.** Running the warm-up requests before taking the
  snapshot. Done on a large machine, with the JVM pinned to the serving container's CPU shape
  (Idea 5).
- **vCPU cliff.** At small CPU limits, warm-up and restore get much slower (JVM warm-up
  13–35× from 4 to 0.25 vCPU). It makes `r`, `B` and `w` bigger, so it steepens the cascade.
- **Linear cascade.** On demand, latency grows by `r + w + δ` per stage (727 ms per stage in
  the example). Look-ahead cuts this to `w + δ` (77 ms per stage).
- **Keep-alive valuation (Proposition 9).** Under look-ahead, keeping *one* stage warm saves
  little, because the next stage's restore becomes the bottleneck. In the example, a warm
  `resize` alone only brings the cold run from 879 to 802 ms (−77 ms); all three warm remove
  the whole 650 ms restore. (As a rule for *what to evict*, this lost in simulation, e8: most
  traffic is hot, and there per-function cost-aware eviction, GDSF, is better.)
