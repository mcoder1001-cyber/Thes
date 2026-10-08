# Predictions from ideas/criu-box/profile_thesis.json (vCPU 1.0, delta 2.0 ms, beta 0.0)

Chain function `java`: r = 650 ms, w = RK + C = 75 ms, m = 512 MB.

## T8. Chains: latency and memory per policy

| d | on demand (ms) | look-ahead, beta=0 (ms) | look-ahead bound at beta (ms) | peak MB od / JIT / eager | memory-time GB·s od = JIT / eager |
|---|---|---|---|---|---|
| 1 | 725 | 725 | 725 | 512 / 512 / 512 | 0.37 / 0.37 |
| 2 | 1452 | 802 | 802 | 512 / 1024 / 1024 | 0.74 / 0.78 |
| 3 | 2179 | 879 | 879 | 512 / 1536 / 1536 | 1.11 / 1.23 |
| 4 | 2906 | 956 | 956 | 512 / 2048 / 2048 | 1.48 / 1.72 |
| 5 | 3633 | 1033 | 1033 | 512 / 2560 / 2560 | 1.86 / 2.25 |
| 6 | 4360 | 1110 | 1110 | 512 / 3072 / 3072 | 2.23 / 2.82 |
| 7 | 5087 | 1187 | 1187 | 512 / 3584 / 3584 | 2.60 / 3.43 |
| 8 | 5814 | 1264 | 1264 | 512 / 4096 / 4096 | 2.97 / 4.07 |

Slopes per extra stage: on demand r + w + delta = **727 ms**; look-ahead w + delta = **77 ms**. JIT peak = m·min(d, ceil((r+w)/(w+delta))) = m·min(d, 10).

## T9. 8-stage chain with a memory budget of k sandboxes (Theorem 8(b))

| k (budget = k·m) | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| latency (ms) | 5800 | 2977 | 2252 | 1681 | 1604 | 1527 | 1450 | 1264 |

## T1 -> T8. 5-stage chain with c restores at a time (ALGORITHM.md Corollary A3)

| c | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| latency (ms) | 3325 | 2025 | 1452 | 1375 | 1033 |

(On demand: 3633 ms. One channel is x2's 'fully serial' case.)

## T10. Planner example: python entry -> java -> java, entry -> py-ml; cap 1024 MB

| no cap (peak) | memory guard | capped on demand | exact plan | plan's triggers (entry, java1, java2, ml) |
|---|---|---|---|---|
| 802 ms (2304 MB) | 1950 ms | 2037 ms | **1310 ms** | 0, 0, 85, 810 |

## Keep-alive vs look-ahead (Theorem 6), 3-stage chain

cold 8680 ms, warm 40 ms, look-ahead 879 ms, eps = 0.097. Keep-alive needs more memory than look-ahead below **1.25 invocations/s**; at one per minute it needs 75x more.
