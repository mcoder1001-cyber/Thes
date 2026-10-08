# T1b prediction: parallel restores through CRaC in Docker

Written 2026-10-08, before any run. Source: `MACHINE_TEST_PLAN.md` T1b.

- Restore time = Docker start-up (control b, docker-noop: a few hundred ms, a guess) + CRaC
  restore (about T1's restore part).
- β of the restore part as in T1 (< 0.3 for N ≤ 4).
- The Docker part adds its own β, likely **0.1–0.3 at N = 8** (guess from Fork in the Road,
  OSDI '25: 110 → 45 starts/s at 24 concurrent starts).
- **Controls:** (a) serial gives β = 1.0 ± 0.1; (b) docker-noop measures Docker's own cost.
- exp11 (light handler, CRaC, no container): restore 200–240 ms wall clock, 2.8–15 ms
  restore → first response, image 27–32 MB.

## Addendum (2026-10-08, after 7 reps at 1 vCPU, before the `exec` variant ran)
The first reps showed docker-noop's r_max(8) / r_max(1) ≈ 5.8 against ≈ 5.5 for parallel
restores: Docker's container creation, not the restore, sets β on the `docker run` path. A new
variant `exec` restores into containers created before the clock (OpenWhisk's prewarmed stem
cells), separating the restore's own contention. **Prediction for `exec`: β < 0.3 for N ≤ 4 at
both vCPU (the original T1 prediction, now about the restore alone); β(8) at 1 vCPU higher than
at 0.25 vCPU.**
