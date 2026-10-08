# D1. Is CRIU (via CRaC) worth it against the JDK's own AOT cache?

## Question
The thesis's snapshot mechanism is CRIU through CRaC. JDK 24/25 ship a cheaper competitor that
needs no CRIU, no extra Linux capabilities and has no shared-random-state risk: the AOT cache
(Project Leyden; JEP 483 class loading/linking, JEP 514 one-step training, JEP 515 method
profiles). If the AOT cache gets close to a CRaC restore, CRIU is not worth its operational
cost. Decision rule registered in `prediction.md` before the full run.

## Setup
- Box: see `../env.json`. Workload: the exp12 Spring Boot function (`app/`, web starter + Jackson
  + Hibernate Validator, service called directly), one jar for every mode, Spring Boot's extracted
  layout (`setup.sh`; the AOT cache cannot use a nested fat jar).
- Serving shape for every mode: `-XX:ActiveProcessorCount=1 -XX:+UseSerialGC -Xms256m -Xmx512m`,
  cgroup v2 `cpu.max` quota 0.25 or 1 vCPU, one cgroup path for all runs (`/d1run`).
- Modes: `cold21` (Zulu CRaC JDK 21.0.12), `c1_21` (+ `-XX:TieredStopAtLevel=1`), `crac_K0` and
  `crac_K50` (CRaC restore, checkpoint after start-up / after 50 requests), `cold25` (Ubuntu
  OpenJDK 25.0.4), `aot_K0` and `aot_K50` (JDK 25 AOT cache, training run = start-up / start-up +
  50 requests, `-XX:AOTCacheOutput`, then `-XX:AOTCache`). 4 CRaC images and 4 AOT caches per depth,
  built at 1 vCPU, used round-robin.
- n = 20 per cell, 280 runs, modes in random order within each repetition (seed recorded in
  `run.py`). Host page cache warm for all modes (an invoker with a local image store).
- Metric: **TTFR** = launch → first response done, wall clock measured outside the process (the
  app prints the epoch at its first response). R = residual over the 200 later requests
  (`Σ max(0, latency − C*)`, C* = the fastest mode's steady latency at that vCPU). CPU-seconds and
  throttled periods from the cgroup.
- `run.py`, `analyze.py` (bootstrap, 10,000 resamples). Raw: `raw/runs.jsonl`, `raw/images.json`.

## Prediction (from `prediction.md`; the 1 vCPU part was written after an n = 1 smoke run)
TTFR order crac_K50 < crac_K0 < aot_K50 ≤ aot_K0 < c1_21 < cold; aot_K0 / cold25 ≈ 0.5–0.65;
crac_K50 ≥ 5× faster than aot_K50 at both vCPU, more so at 0.25; residual R: crac_K50 ≪ aot_K50;
CPU-seconds crac < aot < cold. Control: cold21 ≈ cold25 within 20%.

## Result
TTFR, median [95% CI], ms; CPU-seconds per start (median):

| mode | 0.25 vCPU | CPU-s | 1 vCPU | CPU-s |
|---|---|---|---|---|
| cold21 | 16 895 [16 794, 16 946] | 5.52 | 3 965 [3 915, 3 987] | 5.37 |
| cold25 | 17 594 [17 505, 17 787] | 5.66 | 4 080 [4 033, 4 098] | 5.36 |
| c1_21 | 9 802 [9 787, 9 885] | 3.03 | 2 320 [2 310, 2 347] | 2.93 |
| aot_K0 | 9 502 [9 393, 9 597] | 3.71 | 2 264 [2 241, 2 280] | 3.57 |
| aot_K50 | 8 691 [8 596, 8 786] | 3.25 | 2 049 [2 022, 2 074] | 3.01 |
| crac_K0 | 2 086 [2 043, 2 184] | 2.06 | 499 [492, 508] | 1.97 |
| **crac_K50** | **293 [264, 297]** | **1.20** | **82 [65, 88]** | **1.18** |

Ratios (`ratios.csv`): **aot_K50 / crac_K50 = 29.6× [29.2, 33.1] at 0.25 vCPU, 25.1× [23.3, 31.7]
at 1 vCPU.** aot_K0 / crac_K0 = 4.5×. aot_K0 / cold25 = 0.54–0.55. CRaC images 80–104 MB, AOT caches
45–47 MB (`raw/images.json`).

Residual warm-up over the 200 later requests, R median [CI], ms:

| | crac_K50 | aot_K50 | crac_K0 | aot_K0 | c1_21 | cold21 |
|---|---|---|---|---|---|---|
| 0.25 vCPU | 3 843 [3 692, 3 903] | 3 600 [3 351, 3 851] | 5 550 | 4 849 | 1 955 | 4 498 |
| 1 vCPU | 746 [675, 777] | 652 [593, 701] | 1 154 | 988 | 315 | 1 089 |

## Control
Passed. cold21 / cold25 = 0.96–0.97 (the JDK version changes cold start by 3–4%, far inside the
20% limit). All 280 runs ran in `/d1run`. No failures.

## Verdict
- **TTFR: confirmed, much larger than predicted.** A CRaC restore at depth 50 answers its first
  request 25–30× sooner than the AOT cache with the same training, at both vCPU; the gap is (just)
  larger at 0.25 vCPU, as predicted (CIs overlap). Even SnapStart's checkpoint point (K = 0)
  beats the AOT cache by 4.5×. aot_K0 / cold25 = 0.55, inside the predicted 0.5–0.65.
- **CPU per start: confirmed.** 1.2 CPU-s (crac_K50) vs 3.0–3.7 (AOT) vs 5.4–5.7 (cold).
- **Residual warm-up: falsified.** R after a K = 50 restore is *not* below the AOT cache's
  (746 vs 652 ms at 1 vCPU; 3 843 vs 3 600 at 0.25; CIs overlap). The deep snapshot's advantage is
  all in time-to-first-response; over the next 200 requests both still pay a similar JIT
  residual. This is consistent with exp12's warm-up lost at checkpoint (T4 measures it directly)
  and means `RK` in the profile cannot be taken from never-checkpointed runs.
- **The cheap flag:** C1 alone gets TTFR to the AOT cache's level (c1_21 / aot_K50 = 1.13) and the
  lowest residual, at a 1.5–1.7× higher steady latency C (2.09 vs 1.20–1.37 ms), as in exp9.

**Decision (registered rule): aot_K50 / crac_K50 ≥ 3× at both vCPU → CRIU/CRaC is justified as the
mechanism; the AOT cache is a baseline it beats.**

## What changes
- The thesis can answer "why CRIU?" with a measured number: on a production-shaped Java function
  the JDK's own answer to start-up (AOT cache, JDK 25) is 25–30× slower to first response than a
  depth-50 CRaC restore, and uses 2.5× the CPU per start.
- The AOT cache and C1 are cheap modes the planner can still choose where a snapshot is unsafe or
  not worth storing (they halve cold start with no CRIU).
- T3/T4 must measure R after restore directly (the residual is not removed by depth).
- Caveat: one workload (Spring Boot), page cache warm. A restore from disk is in the grid (T2 tier).
