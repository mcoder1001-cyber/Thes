# Predictions from results/box/profile_vcpu1.0.json (vCPU 1.0, delta 2.0 ms, beta 0.07)

Chain function `java`: r = 74 ms, w = RK + C = 10 ms, m = 512 MB.

## T8. Chains: latency and memory per policy

| d | on demand (ms) | look-ahead, beta=0 (ms) | look-ahead bound at beta (ms) | look-ahead, c=14 channels (ms) | peak MB od / JIT / eager | memory-time GB·s od = JIT / eager |
|---|---|---|---|---|---|---|
| 1 | 84 | 84 | 84 | 84 | 512 / 512 / 512 | 0.04 / 0.04 |
| 2 | 169 | 95 | 101 | 95 | 512 / 1024 / 1024 | 0.09 / 0.09 |
| 3 | 255 | 107 | 117 | 107 | 512 / 1536 / 1536 | 0.13 / 0.15 |
| 4 | 341 | 119 | 134 | 119 | 512 / 2048 / 2048 | 0.17 / 0.21 |
| 5 | 426 | 130 | 151 | 130 | 512 / 2560 / 2560 | 0.21 / 0.27 |
| 6 | 512 | 142 | 168 | 142 | 512 / 3072 / 3072 | 0.26 / 0.35 |
| 7 | 598 | 154 | 185 | 154 | 512 / 3584 / 3584 | 0.30 / 0.43 |
| 8 | 684 | 166 | 202 | 166 | 512 / 4096 / 4096 | 0.34 / 0.51 |

Slopes per extra stage: on demand r + w + delta = **86 ms**; look-ahead w + delta = **12 ms**. JIT peak = m·min(d, ceil((r+w)/(w+delta))) = m·min(d, 8).
Contention: beta = 0.07 behaves roughly like c = floor(1/beta) = 14 restores at a time.

## T9. 8-stage chain with a memory budget of k sandboxes (Theorem 8(b))

| k (budget = k·m) | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| latency (ms) | 670 | 346 | 263 | 202 | 191 | 179 | 167 | 166 |

## T1 -> T8. 5-stage chain with c restores at a time (ALGORITHM.md Corollary A3)

| c | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| latency (ms) | 380 | 232 | 169 | 158 | 130 |

(On demand: 426 ms. One channel is x2's 'fully serial' case.)

## T10. Planner example: python entry -> java -> java, entry -> py-ml; cap 1024 MB

| no cap (peak) | memory guard | capped on demand | exact plan | plan's triggers (entry, java1, java2, ml) |
|---|---|---|---|---|
| 500 ms (2304 MB) | 680 ms | 754 ms | **669 ms** | 0, 13, 85, 169 |

## Keep-alive vs look-ahead (Theorem 6), 3-stage chain

cold 11907 ms, warm 6 ms, look-ahead 107 ms, eps = 0.008. Keep-alive needs more memory than look-ahead below **11.85 invocations/s**; at one per minute it needs 711x more.
