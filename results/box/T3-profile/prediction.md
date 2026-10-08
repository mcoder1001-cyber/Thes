# T3 prediction: the function's profile r(K), R(K), s(K)

Written 2026-10-08, before any run. Source: `MACHINE_TEST_PLAN.md` T3.

- `s(K)` nearly flat in K (exp11: 27–32 MB light handler, +1.3 MB from K = 0 to 200).
  Spring Boot image size unknown; e6 assumed **90 MB**.
- `r_wall` flat in K, strongly vCPU-dependent: **0.64 s → 9 s** from 4 to 0.25 vCPU (Spring
  Boot, exp12).
- `R(K)` falls with K and flattens; at 1 vCPU and K = 50 about **63 ms** per stage (exp15).
- Compiled-method count rises monotonically in K and flattens where `R(K)` flattens
  (Proposition 8).
- **Control:** `R(0) ≈ B` within CI; never-checkpointed process is the floor for `R(K)`.
