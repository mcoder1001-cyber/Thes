# Predictions from results/box/profile_vcpu0.25.json (vCPU 0.25, delta 2.0 ms, beta 0.04)

Chain function `java`: r = 282 ms, w = RK + C = 93 ms, m = 512 MB.

## T8. Chains: latency and memory per policy

| d | on demand (ms) | look-ahead, beta=0 (ms) | look-ahead bound at beta (ms) | look-ahead, c=25 channels (ms) | peak MB od / JIT / eager | memory-time GB·s od = JIT / eager |
|---|---|---|---|---|---|---|
| 1 | 375 | 375 | 375 | 375 | 512 / 512 / 512 | 0.19 / 0.19 |
| 2 | 753 | 471 | 482 | 471 | 512 / 1024 / 1024 | 0.38 / 0.43 |
| 3 | 1130 | 566 | 589 | 566 | 512 / 1536 / 1536 | 0.58 / 0.72 |
| 4 | 1508 | 662 | 696 | 662 | 512 / 2048 / 2048 | 0.77 / 1.06 |
| 5 | 1885 | 757 | 803 | 757 | 512 / 2048 / 2560 | 0.96 / 1.45 |
| 6 | 2263 | 853 | 909 | 853 | 512 / 2048 / 3072 | 1.15 / 1.89 |
| 7 | 2640 | 948 | 1016 | 948 | 512 / 2048 / 3584 | 1.35 / 2.37 |
| 8 | 3018 | 1044 | 1123 | 1044 | 512 / 2048 / 4096 | 1.54 / 2.91 |

Slopes per extra stage: on demand r + w + delta = **377 ms**; look-ahead w + delta = **95 ms**. JIT peak = m·min(d, ceil((r+w)/(w+delta))) = m·min(d, 4).
Contention: beta = 0.04 behaves roughly like c = floor(1/beta) = 25 restores at a time.

## T9. 8-stage chain with a memory budget of k sandboxes (Theorem 8(b))

| k (budget = k·m) | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| latency (ms) | 3004 | 1597 | 1222 | 1044 | 1044 | 1044 | 1044 | 1044 |

## T1 -> T8. 5-stage chain with c restores at a time (ALGORITHM.md Corollary A3)

| c | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| latency (ms) | 1503 | 939 | 757 | 757 | 757 |

(On demand: 1885 ms. One channel is x2's 'fully serial' case.)

## T10. Planner example: python entry -> java -> java, entry -> py-ml; cap 1024 MB

| no cap (peak) | memory guard | capped on demand | exact plan | plan's triggers (entry, java1, java2, ml) |
|---|---|---|---|---|
| 500 ms (2048 MB) | 1251 ms | 1338 ms | **971 ms** | 0, 0, 95, 471 |

## Keep-alive vs look-ahead (Theorem 6), 3-stage chain

cold 49656 ms, warm 6 ms, look-ahead 566 ms, eps = 0.011. Keep-alive needs more memory than look-ahead below **2.63 invocations/s**; at one per minute it needs 158x more.
