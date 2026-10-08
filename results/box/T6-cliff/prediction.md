# T6 prediction: the vCPU cliff, cold vs restored

Written 2026-10-08, before any run. Source: `MACHINE_TEST_PLAN.md` T6.

- Cold: `B(0.25) / B(4)` = **13–35×** (exp14); `B ≈ 0.185·W` still fits.
- Restored at K = 0: most of the cliff remains.
- Restored deep (chosen K): **ratio below 5×** (registered guess; the theory gives no number).
- **Control:** steady `C` at each vCPU is the floor for every mode.
