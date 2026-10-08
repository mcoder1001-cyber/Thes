# D2 prediction: Warp vs CRIU engine (registered before running)

Written 2026-10-08 after finding that all earlier box runs used CRaC's default engine, Warp.

- Both engines restore the function correctly (20/20 per cell).
- **CRIU is slower than Warp to first response**, by a constant of a few hundred ms (process tree
  restore, namespaces, the criu binary's own start), and its restore scales with CPU like Warp's.
- Image sizes similar (both hold the same heap and code).
- The bimodal deep-restore times seen in the grid (≈ 70 / ≈ 300 ms at 1 vCPU) are a property of
  Warp's restore path; CRIU's K = 50 restores are unimodal. (Weak guess.)
