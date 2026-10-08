# T2 prediction: readiness tiers (x1)

Written 2026-10-08, before any run. Source: `MACHINE_TEST_PLAN.md` T2 (exp11 values).

- **Control:** T4 ≤ T3 ≤ T2 ≤ T1 ≤ T0 within CIs.
- 1 vCPU: T1 and T2 about **200–250 ms**; T1 − T2 < 50 ms; T3 **3–15 ms**; T4 a few ms;
  T0 several hundred ms or more.
- 0.25 vCPU: T0, T1, T2 several times slower (restore is CPU-bound); T3 barely changes.
- Memory held: T3 ≈ T4 ≈ JVM RSS (100–300 MB with -Xmx256m); T2 ≈ image size (~30 MB).
