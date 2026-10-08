# D2. CRaC's two engines: Warp (the default) vs CRIU

## Question
On 2026-10-08 the run logs showed `warp: Checkpoint …`: the Zulu CRaC JDK 21.0.12 on the box
defaults to Azul's **Warp** engine (`-XX:CRaCEngine=warp`), not CRIU. D1, T1b and the T3–T6b grid
all ran with Warp. Do their numbers carry over to CRIU (`-XX:CRaCEngine=criu`)? And is the grid's
bimodal deep-restore time (≈ 70 / ≈ 300 ms at 1 vCPU) a Warp property?

## Setup
- Same Spring Boot function, cgroup and helpers as the grid (`../T3-profile/grid.py`; cgroup
  `/grid/run`, cores 0–3, serving shape `-XX:ActiveProcessorCount=1 -XX:+UseSerialGC`).
- Images: engine ∈ {warp, criu} × K ∈ {0, 50} × 4, built at 1 vCPU. Warp writes one `core.img`;
  CRIU writes CRIU's per-object image files (`core-<pid>.img`, …).
- Restores: 0.25 and 1 vCPU, 20 repetitions, the four (engine, K) cells in random order within each
  repetition (seed in `run.py`). Image in the page cache. 160 restores.
- `run.py`; raw `raw/images.jsonl`, `raw/restores.jsonl`.

## Prediction (`prediction.md`, registered before running)
Both engines restore 20/20; **CRIU slower by a few hundred ms**, scaling with CPU like Warp; similar
image sizes; the bimodality belongs to Warp, CRIU unimodal (weak guess).

## Result
Time to first response, median [95% CI] (min–max), ms; CPU-seconds per restore (median):

| vCPU | K | Warp | CRIU | CRIU − Warp | CPU-s W / C |
|---|---|---|---|---|---|
| 1 | 0 | 474 [463, 483] (401–542) | 492 [482, 502] (472–564) | +18 | 1.82 / 2.04 |
| 1 | 50 | **67** [61, 72] (55–90) | **84** [80, 91] (74–145) | +17 | 1.03 / 1.02 |
| 0.25 | 0 | 1 986 [1 967, 2 035] | 2 076 [2 066, 2 131] | +90 | 2.06 / 2.11 |
| 0.25 | 50 | **284** [280, 291] (224–383) | **375** [301, 385] (280–487) | +91 | 1.05 / 1.05 |

All 160 restores succeeded; all 16 checkpoints succeeded. Image sizes: Warp 79–93 MB, CRIU
78–98 MB. The first request after the restore takes the same time with either engine (8.8 vs 9.7 ms
at K = 50, 1 vCPU): the engines differ only in the restore itself.

## Control
Both engines restore the same function and produce the same first-request latency, so the
comparison isolates the engine. Warp's numbers here match D1's Warp restores at the same cells
(K = 50, 1 vCPU: 67 vs 82 ms; K = 0: 474 vs 499 ms), within run-to-run spread.

## Verdict
- **CRIU vs Warp: falsified in CRIU's favour.** CRIU is 17–18 ms slower at 1 vCPU and ~90 ms at
  0.25 vCPU, not "a few hundred". It uses the same CPU-seconds.
- **The thesis's restore numbers carry over to CRIU.** D1's comparison with CRIU's numbers:
  AOT cache (K = 50) / CRIU restore (K = 50) = 2 049 / 84 ≈ **24× at 1 vCPU** and 8 691 / 375 ≈
  **23× at 0.25 vCPU** (Warp: 25–30×). The decision (≥ 3×) is unchanged.
- **Bimodality: not a Warp property.** In D2 Warp's K = 50 restores at 1 vCPU are unimodal
  (55–90 ms), as in D1 and the grid's boost phase (59 ms). CRIU at 0.25 vCPU shows two clusters
  (280–304 and 365–487 ms). The grid's ≈ 300 ms mode at 1 vCPU appears only when restores are
  interleaved with cold JVM runs (`../T3-profile/REPORT.md`); its cause is open. It is not
  page-cache eviction (0 refaults in the cgroup) and not disk reads (an explicit restore from disk
  takes ≈ 500 ms).

## What changes
- **Every box result must say which engine it used.** D1, T1b, T3–T6b: Warp. D2: both. The reports
  are corrected.
- **"Is CRIU wise?" now has a measured answer:** CRIU through CRaC restores this function within
  17–91 ms of Azul's own engine. Warp is the faster default here; whether it also needs fewer
  privileges inside containers than CRIU (root, `CHECKPOINT_RESTORE`, a free PID) is for T7 to
  check. The thesis's design does not depend on which engine restores. The T1b `exec` result (restore into pre-created containers) was measured with Warp; with CRIU,
  the restored PID must be free in the container (the `sh -c` wrapper used there) and the
  container needs CRIU's capabilities: to be checked in T7.
