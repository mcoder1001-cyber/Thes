# T6. The vCPU cliff, cold vs restored

**Engine: Warp.** Data: the grid (`../T3-profile/raw/grid.jsonl`); table `cliff.csv`.

## Question
(a) The cliff, re-measured on this function: how much do start-up and warm-up grow from 4 to 0.25
vCPU? (b) Do deep snapshots flatten it (S4)?

## Setup
As T3: vCPU ∈ {0.25, 0.5, 1, 2, 4}, 20 runs per cell; B for cold starts and R(K) for restores as
defined there; C(v) per vCPU. (exp14's raw CSV is not in this repository and was not copied.)

## Prediction
Cold `B(0.25)/B(4)` = 13–35× (exp14). Restored at K = 0: most of the cliff remains. Restored deep:
ratio below 5× (registered guess). Control: C at each vCPU is the floor.

## Result (`cliff.csv`; ratio = value at v / value at 4 vCPU)

| mode | R or B at 0.25 / 0.5 / 1 / 2 / 4 vCPU (ms) | ratio 0.25 : 4 | TTFR ratio |
|---|---|---|---|
| cold (B) | 5 759 / 3 084 / 1 271 / 628 / 561 | **10.3×** | 9.2× |
| restore K = 0 | 7 310 / 3 590 / 1 606 / 753 / 577 | 12.7× | 10.8× |
| restore K = 50 | 3 570 / 1 656 / 720 / 280 / 229 | 15.6× | 6.5× |
| restore K = 200 | 2 313 / 1 105 / 453 / 165 / 112 | **20.6×** | 15.2× |
| never checkpointed, K = 200 | 1 563 / 811 / 342 / 93 / 69 | 22.7× | — |

What the snapshot saves, TTFR + R (cold minus restore at K = 200): **19.1 s at 0.25 vCPU,
4.5 s at 1, 2.2 s at 4.**

## Control
Passed: C (0.69–0.89 ms) is below every mode's per-request latency at every vCPU.

## Verdict
- **Cold cliff: 10.3×, below the predicted 13–35×** (exp14 measured a different, heavier warm-up
  workload). Falsified in magnitude; the cliff is real (B grows 10×, TTFR 9×).
- **"Deep snapshots flatten the cliff": falsified as a ratio.** The deeper the snapshot, the *steeper*
  the relative cliff (12.7× → 15.6× → 20.6×): at 4 vCPU a deep restore leaves almost nothing, at
  0.25 vCPU it still leaves 2.3 s.
- **In absolute time the S4 claim holds:** the snapshot saves 19.1 s at 0.25 vCPU and 2.2 s at
  4 vCPU, so deep snapshots matter most exactly where FaaS runs. The thesis should state S4 in
  absolute saving, not as a flatter ratio.

## What changes
- S4's wording (`RESEARCH_PLAN.md`): "snapshots save most at low vCPU" (absolute), not "flatten the
  cliff". Figure 9 (`figures/make_figures.py`) should plot absolute TTFR + R per mode against vCPU.
