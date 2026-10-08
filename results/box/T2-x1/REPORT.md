# T2. Readiness tiers: disk, page cache, warm (partial)

**Engine: Warp.** Not run as `x1-ladder` (raw CRIU): the grid measured three of its five tiers on
the Spring Boot function instead (`../T3-profile/raw/grid.jsonl`, `disk_K50` with the page cache
dropped before each run) plus D2 (`../D2-warp-vs-criu`). The "pre-restored and stopped" tier was not
measured.

## Result (time to first response, median [95% CI], ms; n = 20 per cell; K = 50)

| tier | 0.25 vCPU | 1 vCPU |
|---|---|---|
| T0 cold JVM | 16 551 [16 487, 16 929] | 3 968 [3 889, 3 995] |
| T1 restore from disk (cache dropped) | 1 094 [1 079, 1 125] (p95 4 092) | 505 [499, 529] |
| T2 restore from page cache (D2, Warp) | 284 [280, 291] | 67 [61, 72] |
| T2 same, grid (interleaved; anomaly) | 380 [294, 871] | 181 [84, 332] |
| T4 warm (next request of a warm JVM) | 2.6 | 2.7 |

Image: 82–88 MB (T3).

## Control
Order T4 ≤ T2 ≤ T1 ≤ T0 holds at both quotas: **passed.**

## Verdict
- T1 − T2 = **440 ms at 1 vCPU, 810 ms at 0.25** for an ≈ 88 MB image on this (virtual) disk — not
  the "< 50 ms" predicted for a 30 MB image: falsified (larger image, slower disk than assumed).
- T2 at 1 vCPU: 67 ms (predicted 200–250 ms for the light handler: faster than predicted).
- A restore from the page cache is ≈ 25× slower than a warm request and ≈ 60× faster than a cold JVM.

## What changes
- An invoker should keep snapshot images in memory (page cache or tmpfs): a cold disk read costs
  more than the restore itself. This is the storage-tier term of Corollary 7.3; its measured cost is
  ≈ 0.44 s (1 vCPU) to 0.81 s (0.25 vCPU) per 88 MB.
- The pre-restored tier (x1's T3) remains unmeasured; it is the fallback only if β were high, and
  T1b found β ≈ 0.05 with stem containers.
