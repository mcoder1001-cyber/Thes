# T6b prediction: start-up speed-up with CPU, its CPU cost, and boosting only the start-up

Written 2026-10-08, before any run. Source: `MACHINE_TEST_PLAN.md` T6b (exp-b).

- 0.25 → 1 vCPU: **about 4× faster at about the same CPU-seconds** (exp-b warm-up:
  3.59 → 0.86 s, 0.90 vs 0.86 CPU-s).
- 1 → 4 vCPU: less (exp-b 2.4×), with more CPU-seconds.
- CRIU restore scales like warm-up (CPU-bound). **If restore speeds up by < 2× from 0.25 to
  1 vCPU, the CPU plan's linear speed-up is wrong for restores.**
- Boost runs serve requests 2–200 as fast as a run that stayed at 0.25 vCPU after warming.
- **Control:** at 1 vCPU, fixed-quota and boost runs are identical up to the first response.
