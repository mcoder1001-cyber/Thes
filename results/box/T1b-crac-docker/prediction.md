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
