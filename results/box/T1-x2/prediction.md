# T1 prediction: parallel restores, raw CRIU in podman (x2)

Written 2026-10-08, before any run. Source: `ROADMAP.md` §3 (registered 2026-09-26) and
`MACHINE_TEST_PLAN.md` T1.

- **β(N) < 0.3 for N ≤ 4** at both 1 and 0.25 vCPU. Each copy has its own quota, the box has
  8 cores, the image (27–32 MB for this light handler, exp11) sits in the page cache.
- **β rises at N = 8 at 1 vCPU** (8 quotas + podman/conmon/CRIU work > 8 cores).
- **β(8) at 0.25 vCPU < β(8) at 1 vCPU** (8 × 0.25 = 2 cores). If not, the bottleneck is not
  CPU (disk, or a lock in podman or CRIU).
- `r(1)`: a few hundred ms to ~1.5 s including podman's container set-up (a guess; the ratio
  is what matters).
- **Control:** `--serial` gives β = 1.0 ± 0.1.
- Consequence for a 5-stage Java chain (`predict.py`, thesis values): look-ahead
  3325 / 2025 / 1452 / 1375 / 1033 ms for c = 1…5 restores at a time; on demand 3633 ms.
