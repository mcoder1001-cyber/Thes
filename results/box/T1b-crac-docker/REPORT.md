# T1b. Parallel CRaC restores in Docker: the contention β

## Question
Look-ahead restores several stages at once. When N copies of one snapshot are restored at the
same time, how much slower is the slowest? (Corollary 1.2: the look-ahead saving is at least
`(1 − β)(d − 1)r`.) This is the path OpenWhisk will use: CRaC inside Docker.

## Setup
- Box: `../env.json` (8 × Xeon Gold 6248R, 2 sockets, Ubuntu 24.04, kernel 6.8, Docker 29.8.1,
  Zulu CRaC JDK 21.0.12). Workload: the D1 Spring Boot function, checkpointed once inside a
  container after K = 50 requests (image 97 MB; 93 MB for the `exec` image). CRaC JDK and app
  bind-mounted read-only into `ubuntu:24.04`; snapshot directory mounted read-only into every copy.
  `--privileged` (narrowing the capabilities is left for T7).
- Variants: `parallel` (N × `docker run … java -XX:CRaCRestoreFrom` at once), `serial` (copy i
  starts when copy i−1 answered; control), `docker-noop` (N × `docker run … date`; Docker's own
  cost), `exec` (N containers created *before* the clock, idle, as OpenWhisk's prewarmed stem
  cells; then N × `docker exec … java -XX:CRaCRestoreFrom` at once; the JVM was checkpointed under
  `sh -c` so its PID is free in a stem container). The `exec` variant was added after the first
  7 reps; its prediction was registered first (`prediction.md`, addendum).
- Ready = launch instant common to all copies → the copy's first response done (wall clock
  printed by the app). N ∈ {1, 2, 4, 8}, quotas 1 and 0.25 vCPU, 20 repetitions, variants and N
  interleaved within each repetition. Snapshot in the page cache.
- `run.py`, `analyze.py`; raw `raw/runs.jsonl` (one row per repetition); `summary.csv`.
- β(N) = (median r_max(N) / median r_max(1) − 1)/(N − 1); 95% CI by bootstrap (10,000).

## Prediction
β < 0.3 for N ≤ 4 at both vCPU; β rises at N = 8 at 1 vCPU; β(8) at 0.25 < at 1 vCPU; the Docker
part adds 0.1–0.3 at N = 8 (a guess). Serial control: β = 1.0 ± 0.1. For `exec`: β < 0.3 for
N ≤ 4, β(8) at 1 vCPU above 0.25.

## Result
r_max median, ms (β [95% CI]); 0 failed copies of about 2,400:

| variant | vCPU | N = 1 | N = 2 | N = 4 | N = 8 |
|---|---|---|---|---|---|
| parallel (`docker run`) | 1 | 419 | 646 (0.54 [0.12, 0.87]) | 1080 (**0.53** [0.35, 0.67]) | 2282 (0.64 [0.49, 0.80]) |
| parallel (`docker run`) | 0.25 | 574 | 692 (0.21 [0.10, 0.33]) | 928 (**0.21** [0.17, 0.27]) | 1543 (0.24 [0.21, 0.29]) |
| docker-noop | 1 | 362 | 519 (0.43) | 1035 (0.62) | 2326 (0.78) |
| docker-noop | 0.25 | 248 | 405 (0.63) | 757 (0.68) | 1409 (0.67) |
| **exec (stem cells)** | 1 | **101** | 106 (0.06) | 122 (**0.07** [0.03, 0.09]) | 201 (0.14 [0.11, 0.15]) |
| **exec (stem cells)** | 0.25 | **380** | 418 (0.10) | 429 (**0.04** [0.01, 0.08]) | 456 (0.03 [0.02, 0.04]) |
| serial (control) | 1 | | 1101 (1.63) | 1968 (1.23) | 4191 (1.29) |
| serial (control) | 0.25 | | 1169 (1.04) | 2511 (1.13) | 5139 (1.14) |

**Where the `docker run` slowdown comes from.** Extra time of the slowest copy at N = 8 over N = 1:
docker-noop +1964 ms (1 vCPU) / +1161 ms (0.25); parallel restores +1863 / +970 ms. All of it is
Docker creating containers (≈ 250 ms each, serialised, as Fork in the Road reports); the restores
add nothing measurable on top. Without container creation (`exec`), 8 restores at once cost
+100 ms (1 vCPU) and +76 ms (0.25) over one.

## Control
- Serial: **passed at 0.25 vCPU** (β 1.04–1.14; CIs include or touch 1.0), **failed at 1 vCPU**
  (1.23–1.63; the N = 4 and N = 8 CIs reach 0.90 and 1.02). The serial path is slower than N × r(1)
  because each copy's tail work (its 20 remaining requests, the JVM exit and `docker rm`) overlaps
  the next copy's start; at 1 vCPU that tail is a larger fraction of the 419 ms restore. The β
  formula itself is not at fault (checked with stubs: serial 1.00, simultaneous 0.01). Read the
  `docker run` β at 1 vCPU with this in mind; the `exec` result does not depend on it.
- docker-noop (control b): ran; it is what identifies Docker as the cause.

## Verdict
- **Through `docker run`: partly confirmed.** β(4) = 0.21 at 0.25 vCPU (confirmed, < 0.3) but 0.53
  at 1 vCPU (falsified: "partial slow-down" band), and the Docker part is ≈ 0.6–0.8, far above the
  0.1–0.3 guess.
- **The restore itself: confirmed, more strongly than predicted.** Into pre-created containers,
  β(4) = 0.04–0.07 and β(8) = 0.03–0.14; β(8) is higher at 1 vCPU than at 0.25, as predicted
  (8 × 1 vCPU = all 8 cores).
- Restore into a stem cell is also **4× faster** than `docker run` + restore at 1 vCPU
  (101 vs 419 ms), 1.5× at 0.25 vCPU (380 vs 574 ms).

**Decision** (`MACHINE_TEST_PLAN.md` T1 table, β at N = 4): with stem cells **β < 0.3 at both vCPU
→ continue as planned**. On the `docker run` path at 1 vCPU, β ≈ 0.5 → limit concurrent container
creation to ≈ 2 and scale the gains by (1 − β).

## What changes
- **Design:** restore into OpenWhisk's prewarmed stem containers (`docker exec` / the action
  proxy starting the restore), not `docker run` per restore. This removes Docker's serialised
  container creation from both the restore time `r` and the contention β. T7 should build the
  snapshot action this way.
- **Profile:** `beta` = 0.07 (1 vCPU, stem cells), 0.04 (0.25 vCPU); `r` for the light path of this
  function at K = 50: ≈ 100 ms (1 vCPU), ≈ 380 ms (0.25), against 650 ms assumed.
- T1 (raw CRIU in podman) was not run: the first `podman container checkpoint` hung inside
  `criu dump` (runc 1.5.1, CRIU 4.2.1) and was killed. T1b is the deployment path the plan says
  to use; T1 is not needed for the decision.
