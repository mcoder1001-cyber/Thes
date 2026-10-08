# T3. The function's profile: restore time r(K), residual warm-up R(K), image size s(K)

**Engine: Warp** (the Zulu CRaC JDK's default; CRIU is 17–91 ms slower per restore, D2).

## Question
What are the model's inputs for a real function — cold start `A`, warm-up `B`, steady latency `C`,
time to first response after a restore at snapshot depth `K`, residual warm-up `R(K)`, image size
`s(K)` — across CPU quotas? The simulator and the theorems used estimates (`r` = 650 ms).

## Setup
- Box `../env.json`. Workload: the exp12 Spring Boot function (`app/`). Serving shape for every run:
  `-XX:ActiveProcessorCount=1 -XX:+UseSerialGC -Xms256m -Xmx512m` (`cold_np`: not pinned).
- `grid.py` phase `build`: 4 images per K ∈ {0, 1, 5, 20, 50, 100, 200}, built at 1 vCPU (the
  builder runs at deploy time), warm-up requests = the app's fixed payload (seed 42).
- Phase `grid`: vCPU ∈ {0.25, 0.5, 1, 2, 4} (cgroup `cpu.max`, cpuset cores 0–3, one cgroup for all
  runs), 20 repetitions, modes in random order per repetition: `cold`, `cold_np`, `restore_K` for
  each K, `cont_K` for K ∈ {0, 50, 200} (never checkpointed; T4's floor), and at 0.25 and 1 vCPU
  `rewarm_K50` (T4) and `disk_K50` (page cache dropped first; T2's tier 1). 1,280 runs, 0 failed,
  all in `/grid/run`.
- After the first response every run serves the same 200 requests; `C(v)` = median of requests
  150–200 of the `cont_K200` runs; `R` = Σ max(0, latency − C(v)) over the first request and the
  200 (for `cold` this is `B`). `analyze.py` → `profile_table.csv` (medians, 95% bootstrap CIs).
- Memory: the sampled `memory.current` of the shared cgroup includes the page cache it accumulates
  (~2.4 GB of images), so it is not the process's memory; **not reported.** Image sizes are.

## Prediction (`prediction.md`)
`s(K)` nearly flat (Spring Boot size unknown; e6 assumed 90 MB). Restore time flat in K and
strongly vCPU-dependent (0.64 → 9 s from 4 to 0.25 vCPU, exp12). `R(K)` falls with K and
flattens; ≈ 63 ms per stage at 1 vCPU, K = 50 (exp15). Compiled-method count rises in K and
flattens where R(K) flattens (Proposition 8). Control: `R(0) ≈ B`; never-checkpointed is the floor.

## Result
Selected cells (all cells in `profile_table.csv`). TTFR = launch → first response; ms, median:

| vCPU | cold TTFR | cold B | restore K=0 TTFR / R | K=50 TTFR / R | K=200 TTFR / R | cont K=200 R (floor) |
|---|---|---|---|---|---|---|
| 0.25 | 16 551 | 5 759 | 2 675 / 7 310 | 380 / 3 570 | 875 / 2 313 | 1 563 |
| 0.5 | 7 981 | 3 084 | 1 025 / 3 590 | 163 / 1 656 | 161 / 1 105 | 811 |
| 1 | 3 968 | 1 271 | 758 / 1 606 | 181 / 720 | 297 / 453 | 342 |
| 2 | 1 988 | 628 | 267 / 753 | 61 / 280 | 60 / 165 | 93 |
| 4 | 1 798 | 561 | 248 / 577 | 59 / 229 | 58 / 112 | 69 |

Image and JIT state at the checkpoint (median of 4 images):

| K | 0 | 1 | 5 | 20 | 50 | 100 | 200 |
|---|---|---|---|---|---|---|---|
| s(K), MB | 86.5 | 84.7 | 81.6 | 86.5 | 87.9 | 84.2 | 87.4 |
| compile time at checkpoint, ms | 4 527 | 5 118 | 5 505 | 5 666 | 5 848 | 6 274 | 6 716 |
| code cache, MB | 7.59 | 8.24 | 8.60 | 8.78 | 8.92 | 9.02 | 9.39 |

Steady latency `C`: 0.69–0.72 ms at 0.25–2 vCPU, 0.89 ms at 4 vCPU. Spring start `A` (cold):
14.6 s / 7.1 / 3.5 / 1.7 / 1.6 s at 0.25 / 0.5 / 1 / 2 / 4 vCPU. CPU per start: cold 5.1–5.4 s at every
quota; restore 2.0 s (K = 0), 1.0–1.1 s (K = 50), 0.8–0.9 s (K = 200).

**An anomaly, reported as found.** At 1 and 0.25 vCPU, deep restores in this grid are bimodal:
at 1 vCPU K = 50 either 61–88 ms (10 runs) or 274–386 ms (10 runs); K = 5–200 sit mostly in the slow
mode (≈ 260–400 ms). The same images restored in 59 ms in the grid's own boost phase, and D1/D2
measured 67–84 ms unimodally at 1 vCPU. It is not page-cache eviction (0 file refaults in the
cgroup), not disk (an explicit restore from disk: 505 ms), not image-specific (all four images show
both modes). It appears when restores are interleaved with cold JVM runs; cause open. **Use
D1/D2's restore times for `r`, and treat this grid's 0.25/1 vCPU restore TTFRs as an upper bound.**
At 2 and 4 vCPU the effect is absent from the medians (≈ 60 ms) but present in the p95 (300–400 ms).

## Control
- `R(0) ≈ B`: **passed approximately** — restore at K = 0 leaves R = 1 606 [1 442, 1 773] at 1 vCPU
  against cold B = 1 271 [1 201, 1 454]: K = 0 captures no request-driven warm-up, and its residual
  is somewhat *higher* than a cold start's (T4's loss L(0)).
- Floor: `R(K) ≥ R_cont(K)` everywhere within CIs (T4).

## Verdict
- **s(K): confirmed flat**, 82–88 MB (no trend in K; the spread is the heap's garbage at the
  checkpoint). e6's assumed 90 MB is right for this function.
- **Restore time: flat in K for K ≥ 5 (at 2–4 vCPU: ≈ 60 ms), strongly vCPU-dependent at K = 0**
  (2.7 s → 0.25 s from 0.25 to 4 vCPU). Much smaller than exp12b's wall-clock numbers for the
  same app (K = 0: 1 970 ms at 1 vCPU, 9 092 at 0.25), which were taken with a different harness
  (`systemd-run` scopes, timing the whole command); the cause of the difference is not established. The model's `r` = 650 ms is **4–10× too high** for a deep
  restore (use 67–84 ms at 1 vCPU, D2; 284–375 ms at 0.25).
- **R(K): falls with K but does not flatten by K = 200** (1 vCPU: 1 606 → 720 → 453 ms), and the
  predicted ≈ 63 ms at K = 50 is **falsified by 11×** (720 ms): exp15's stage was a lighter handler.
  The JIT is still compiling at K = 200 (compile time +48% from K = 0, code cache +24%), so
  **Proposition 8's stopping rule does not trigger within 200 requests here.**
- `A` and `B` scale with the quota as the vCPU cliff says (T6).

## What changes
- **Profile** (`../profile_vcpu1.0.json`, `../profile_vcpu0.25.json`, written from this table and
  D2): Java at 1 vCPU `r` = 84 ms (CRIU, K = 50; Warp 67), `RK` = 720 ms over 200 requests
  (≈ 3.6 ms per request), `C` = 0.70 ms, `A` = 3 494 ms, `B` = 1 271 ms; at 0.25 vCPU `r` = 375 ms
  (CRIU) / 284 (Warp), `RK` = 3 570, `A` = 14 599, `B` = 5 759.
- **Depth:** the snapshot point should be deeper than 50 for this function (R keeps falling to
  K = 200 at no cost in image size or restore time); choose K by the R(K) curve, not by a compile
  counter that has not flattened.
- Look-ahead's gain per hidden restore, `(1 − β) r`, is smaller than assumed at 1 vCPU (84 vs
  650 ms) and the residual `R` is larger, so on this function the residual warm-up, not the restore,
  dominates what a stage costs after its snapshot. That shifts weight from *when* to restore to *how
  deep* and *how much CPU while warming*.
