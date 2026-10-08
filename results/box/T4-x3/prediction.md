# T4 prediction: warm-up lost to the checkpoint L(K), and re-warming (x3)

Written 2026-10-08, before any run. Source: `MACHINE_TEST_PLAN.md` T4.

- `L(K) > 0`, **larger at 0.25 than at 1 vCPU** (exp12: within ~10 points at 4 vCPU, up to
  29 points at 0.25).
- Re-warming recovers **≥ 30%** of `L` at 0.25 vCPU.
- **Control:** `R_continued ≤ R_restored`.
