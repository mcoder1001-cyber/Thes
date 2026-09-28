# Machine test plan: what to run on the CRIU box, what to measure, what to expect

*Written 2026-09-28. The theory, the simulator, the figures and the report are done. Every
remaining claim needs a measurement on the real machine. This file lists each test: the
question it answers, how to run it, what to measure, the known-answer control, the expected
result (with its source), the output files, and what to decide. It is written so you can hand
it to a Claude Code session on the box as a prompt: the section "Prompt" below is that
prompt.*

---

## Prompt

> You are working in the `Thes` repository on the thesis's test machine (8 × Xeon Gold 6248R,
> 31 GB RAM, Ubuntu 24.04, CRIU 4.2.1, Azul Zulu CRaC JDK 21, OpenWhisk built from `master`).
> The thesis claims that restoring snapshots **ahead of need along a workflow DAG** hides all
> but one restore (`REPORT.md`, `theory/DAG_SNAPSHOT_THEORY.md`, `theory/ALGORITHM.md`).
> Everything so far is proved or simulated. Your job is to **measure** it. Read
> `MACHINE_TEST_PLAN.md` and do the tests in order, starting at T0. Work on a branch, commit
> after each test, and open a draft pull request. Follow the rules in the next section. Stop
> and report when a control fails, when a decision rule says stop, or when the plan's
> instructions do not fit what you find on the machine. Do not guess numbers. Do not change
> the theory's claims: if a measurement disagrees with a prediction, report it and propose
> what should change.

**How to start such a session.** A cloud session cannot reach the box. Either install Claude
Code on the box and run it in the `Thes` checkout, or run `claude remote-control` on the
computer that can SSH into the box (`ROADMAP.md` §3, "Who runs it").

---

## Rules (for every test)

1. **Prediction first.** Before running, write `results/box/<test>/prediction.md`: the
   numbers from `ideas/criu-box/predict.py` with the current profile (see "The profile"
   below), or the numbers given in this plan, and commit it. A prediction written after the
   data is worthless (`RESEARCH_PLAN.md` §9, rule 7).
2. **Control first.** Each test has a control whose answer is known in advance. Run it first.
   If it fails, the setup is wrong: fix it before reading any other number (rule 1).
3. **n ≥ 20 per cell.** Report the median, p95 (p99 when n ≥ 100), and a 95% bootstrap
   confidence interval (10,000 resamples of the repetitions). Never a single number (rule 2).
4. **Keep the raw data.** One JSON or CSV row per repetition in `raw/`. Never edit raw files.
   Summaries are computed by a script that is committed next to them.
5. **One factor at a time** (rule 4).
6. **A falsified prediction is a result.** Write it plainly in the test's `REPORT.md`; do not
   tune the setup until it matches (rules 5 and 7).
7. **No credentials, user names or host names in any file.** Write `<user>` in examples.
8. **Cold means cold.** Before each cold repetition, no container, process or page-cache
   state of the function may survive from the last one, unless the test says otherwise
   (for example, image kept in the page cache). Write down how you ensured it.
9. **Record the machine state** with each result (`env.json`, T0), and note anything else
   running on the box.

### Where results go

```
results/box/
  env.json                         machine, kernel, versions (T0)
  profile_vcpu1.0.json             the model's inputs, measured (T2, T3, T7); format of
  profile_vcpu0.25.json            ideas/criu-box/profile_thesis.json
  T1-x2/                           one folder per test:
    prediction.md                    written and committed BEFORE the run
    raw/                             one row per repetition, as produced
    summary.csv                      computed by analyze.py
    analyze.py                       the summary script
    REPORT.md                        question, setup, prediction, result, control, verdict
  T2-x1/ ...
```

`REPORT.md` for each test, always the same sections: **Question. Setup** (commands, commit,
anything unusual). **Prediction** (copied from `prediction.md`). **Result** (table with CIs).
**Control** (passed or not). **Verdict**: confirmed, falsified or inconclusive, and by how
much. **What changes** in the thesis, the profile or the plan.

### The profile

The theory and the simulator take a few numbers per function. `ideas/criu-box/profile_thesis.json`
holds the thesis's current values (Java at 1 vCPU: restore `r` = 650 ms, residual warm-up
`RK` = 63 ms, steady run `C` = 12 ms, memory `m` = 512 MB; edge delay `delta_ms` = 2 ms;
contention `beta` = 0). Copy it to `results/box/profile_vcpu<v>.json` and replace each value
as soon as a test measures it. Then:

```bash
python3 ideas/criu-box/predict.py --profile results/box/profile_vcpu1.0.json   # every closed-form prediction
DAGSIM_PROFILE=results/box/profile_vcpu1.0.json DAGSIM_OUT=results/box/sim \
    python3 ideas/sim/run_sim.py e10a e9a                                    # the simulator, measured inputs
```

`predict.py` prints the chain, memory-slot, restore-channel, planner and keep-alive
predictions from the theorems (it calls `theory/verify_dag.py`'s reference code). With the
thesis defaults it prints the numbers quoted below.

---

## Overview

| test | question | roadmap stage | days | decides |
|---|---|---|---|---|
| **T0** | is the machine ready, and in what state | 1 | 0.5 | nothing; provenance |
| **T1** | do parallel restores slow each other down (β)? raw CRIU in podman | 1 | 1–2 | **go / no-go** for look-ahead |
| **T1b** | the same through CRaC in Docker (the deployment path) | 1 | 1–2 | which β the orchestrator uses |
| **T2** | cost of each readiness tier (disk, page cache, pre-restored, warm) | 1 | 1 | `r`, `m`; the fallback tier |
| **T3** | the real function's profile: `r(K)`, residual `R(K)`, image `s(K)` | 2 | 5–7 | the model's inputs; snapshot depth |
| **T4** | warm-up lost to the checkpoint `L(K)`, and what re-warming recovers | 2 | 1–2 | keep or drop re-warm (Idea 4) |
| **T5** | do copies restored from one image repeat random numbers and secrets? | 5 | 2 | the builder's reset hooks |
| **T6** | the vCPU cliff, cold vs restored | 2 | 2 | the missing figure; S4's headline |
| **T7** | one snapshot action inside OpenWhisk, the wake call, the edge delay δ | 3 | 10 | the platform works; `delta_ms` |
| **T8** | look-ahead on chains of 1–8 stages at 0.25 and 1 vCPU | 4 | 10 | **the headline result** |
| **T9** | peak memory; latency with k sandboxes allowed; the guard | 4 | 3 | Theorem 8 on the real system |
| **T10** | the exact planner vs the guard under a tight budget | 6 | 3 | Algorithm 2 |
| **T11** | fan-out and other shapes; branches (Theorem 4); uncertain times (Theorem 3) | 6 | 7 | the remaining theorems |
| **T12** | a burst of cold workflows under a shared budget | 6 | 2 | the guard under load |
| **T13** | evaluation against the baselines, with trace replay | 7 | 20 | the thesis's comparison |

T1 decides whether the rest is worth doing as planned. T2–T6 need only CRIU and the JDK.
T7 onwards need OpenWhisk and the orchestrator (`ROADMAP.md` §1.3).

---

## T0. Machine state and provenance

**Run.** Collect into `results/box/env.json`:
- `uname -r`, `lscpu` (model, cores, NUMA), `free -m`, swap on or off;
- `stat -fc %T /sys/fs/cgroup` (must be `cgroup2fs`);
- the CPU frequency governor (`/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor`, if present);
- transparent huge pages (`/sys/kernel/mm/transparent_hugepage/enabled`);
- `criu --version`, `java -version` (the CRaC JDK), `podman --version`, `docker --version`;
- the disk holding the images (`lsblk -o NAME,ROTA,MODEL`, and the filesystem type);
- `git rev-parse HEAD` of `Thes` and of the OpenWhisk checkout;
- the OpenWhisk invoker's user-memory setting.

**Control.** `criu check` passes. The S0 smoke test (`criu-smoketest.sh`, level 3: checkpoint
and restore a JIT-warmed JVM) passes. `sync; echo 3 > /proc/sys/vm/drop_caches` works as root.

**Expected.** As in `ROADMAP.md` §1.1. The invoker's user memory is **1024 MB**, which is too
small from T7 on (an 8-stage chain at 512 MB per stage needs 4 GB). Raise it before T7 to at
least 8 GB, and record the value.

**Output.** `results/box/env.json`. **Decision:** none; stop if CRIU or the JDK is missing.

---

## T1. Parallel restores: the contention β (x2)

**Question.** When N copies of one snapshot are restored at the same time, how much slower is
each? Look-ahead restores several stages at once; if they serialise, most of the gain is lost
(Corollary 1.2: the saving is at least `(1 − β)(d − 1)r`).

**Run.**
```bash
sudo ./ideas/criu-box/run_x2.sh 1.0 20      # N = 1, 2, 4, 8 copies, 20 repetitions, 1 vCPU each
sudo ./ideas/criu-box/run_x2.sh 0.25 20     # the same at 0.25 vCPU
```
`run_x2.sh` checks the kernel and tools, builds the workload, and runs
`criu_box.py x2-parallel`, which checkpoints one container with `podman container checkpoint
--export` and restores N copies at once, each in its own container with its own CPU quota.
While it runs, record CPU use (`mpstat -P ALL 1`) and disk reads (`iostat -x 1`) to a file.

**Add before running (small code change in `criu_box.py`):**
- a `--serial` option that restores the N copies **one after another** through the same code
  path (the control below);
- a `--drop-caches` option that drops the page cache before each repetition (to separate disk
  from CPU if β is high).

**Measure.** For each copy: time from the restore command to the first successful `/ping`
(ready). Per N: the slowest copy `r_max(N)` and the mean. Then
`β(N) = (r_max(N) / r(1) − 1) / (N − 1)` from the medians, with a bootstrap CI (resample the
20 repetitions of N and of N = 1). Also the image size (`du -sb` of the export).

**Control (known answer).** With `--serial`, β must come out **1.0 ± 0.1**: N restores in a row
take N times as long. (The β formula was already checked with podman stubbed out: serial
gives 1.00, simultaneous gives 0.01.) If this fails, the timing is wrong.

**Expected** (`ROADMAP.md` §3, registered 2026-09-26):
- **β < 0.3 for N ≤ 4**, at both vCPU levels: each copy has its own CPU quota, the box has 8
  cores, and the image (27–32 MB for this light handler, exp11) sits in the page cache.
- **β rises at N = 8 at 1 vCPU**: 8 quotas of 1 vCPU plus podman, conmon and CRIU's own work
  exceed 8 cores.
- **At 0.25 vCPU, β(8) is lower than at 1 vCPU**: 8 × 0.25 = 2 cores. If it is not, the
  bottleneck is not CPU (look at disk, or a lock in podman or CRIU).
- `r(1)` is a few hundred ms to about 1.5 s, including podman's own container set-up. This is
  a guess; the number that matters is the ratio.
- What β means for a 5-stage Java chain (`predict.py`, thesis values): with `c` restores
  running at a time, look-ahead takes 3325 / 2025 / 1452 / 1375 / 1033 ms for c = 1…5, against
  3633 ms on demand. β behaves roughly like `c ≈ 1/β` channels.

**Output.**
- `raw/x2_parallel_vcpu{v}.json` as written by the script (N, rep, per-copy `restore_ms`,
  `restore_ms_max`, `restore_ms_mean`), plus `raw/x2_serial_vcpu{v}.json` (control) and the
  `mpstat`/`iostat` logs;
- `summary.csv` with columns: `variant, vcpu, N, reps, r1_median_ms, rmax_median_ms,
  rmax_p95_ms, beta, beta_ci_lo, beta_ci_hi, c_eff, cpu_busy_pct_max, disk_read_MBps_max`.

**Decision** (`ROADMAP.md` §3):

| β at N = 4, serving vCPU | meaning | what to do |
|---|---|---|
| **< 0.3** | restores run in parallel | continue as planned |
| **0.3 – 0.7** | partial slow-down | continue; limit concurrent restores to about `1/β`; scale the claimed gains by `(1 − β)` |
| **≥ 0.7** | restores serialise | find the cause first (CPU, disk, or a lock: rerun with `--drop-caches`, with the image on tmpfs, and at 0.25 vCPU). If it cannot be fixed, look-ahead is weak on this hardware; the thesis then rests on Theorem 7, the memory results and the measurement study, and the fallback for timing is T2's pre-restored tier |

**Feed back.** Put β (N = 4, serving vCPU) into the profile's `"beta"`. Rerun `predict.py`: it
then prints the Corollary 1.2 bound and the channel estimate for T8.

---

## T1b. The same through CRaC in Docker

**Question.** OpenWhisk will restore through CRaC inside Docker, not raw CRIU in podman. Is β
the same on that path?

**Write** `ideas/criu-box/x2_crac_docker.sh` (new):
1. build a Docker image with the CRaC JDK and `FnServer` (+ `Fn` and its libraries);
2. start one container with `java -XX:CRaCCheckpointTo=/cr … FnServer`, prime it as `x2` does,
   and checkpoint with `jcmd <pid> JDK.checkpoint`. Start with `--privileged`; then narrow down
   to the capabilities Azul's CRaC documentation lists (`CHECKPOINT_RESTORE`, `SYS_PTRACE`, …)
   and record the minimal set that works;
3. restore N ∈ {1, 2, 4, 8} copies at once: `docker run --cpus=<v> … java -XX:CRaCRestoreFrom=/cr`,
   with `/cr` mounted read-only into every container;
4. time each copy from `docker run` to the first successful `/ping`; 20 repetitions.

**Control (known answer + a baseline).** (a) Serial restores give β = 1.0 ± 0.1, as in T1.
(b) N parallel `docker run` of the same image with a command that does nothing (`true`, or
the HTTP server without a restore): this measures Docker's own start-up cost and its own
contention, which must be separated from the restore's. Docker is known to serialise part of
container creation (Fork in the Road, OSDI '25: 110 → 45 starts/s at 24 concurrent starts).

**Expected.** Restore time = Docker start-up (control b, a few hundred ms, a guess) + CRaC
restore (about T1's). β of the restore part as in T1; the Docker part adds its own β, likely
0.1–0.3 at N = 8 (a guess from Fork in the Road).

**Output.** Same `summary.csv` schema as T1 with `variant = crac-docker` and
`variant = docker-noop` rows. **Decision:** this β is the one the orchestrator will see. If it
differs from T1's by more than 0.2, use this one in the profile and say which part (Docker or
restore) causes the difference.

---

## T2. Readiness tiers (x1)

**Question.** How fast can a stage become ready, and how much memory does it hold while it
waits, for each way of keeping it? This calibrates `r` and `m`, and prices the fallback if β
is high.

**Run.**
```bash
sudo ./ideas/criu-box/criu_box.py x1-ladder --reps 20 --vcpu 1.0
sudo ./ideas/criu-box/criu_box.py x1-ladder --reps 20 --vcpu 0.25
```
Tiers: T0 cold JVM; T1 restore from disk (page cache dropped); T2 restore with the image in
the page cache; T3 pre-restored and stopped (`criu restore --leave-stopped`, then `SIGCONT`);
T4 warm.

**Measure.** Per tier: activation latency (request sent → first response), memory held while
waiting (T1: 0; T2: image size in page cache; T3, T4: RSS), image size on disk.

**Control (known answer).** Order: T4 ≤ T3 ≤ T2 ≤ T1 ≤ T0, within CIs. No restore may be
faster than the warm process. A violation means the timing or the cache dropping is wrong.

**Expected** (light handler; exp11 measured CRaC restore at about 200–240 ms wall clock,
2.8–15 ms from restore to first response, image 27–32 MB):
- 1 vCPU: T1 and T2 about **200–250 ms**; T1 − T2 small (< 50 ms for 30 MB on an SSD);
  T3 **3–15 ms**; T4 a few ms; T0 several hundred ms or more.
- 0.25 vCPU: T0, T1 and T2 several times slower (restore is CPU-bound: CRIU replays system
  calls, per Spice); T3 barely changes.
- Memory: T3 ≈ T4 ≈ the JVM's RSS (the script uses `-Xmx256m`: roughly 100–300 MB);
  T2 ≈ the image size.

**Output.** `raw/x1_ladder_vcpu{v}.json`; `summary.csv`: `vcpu, tier, reps,
activation_ms_median, activation_ms_p95, ci_lo, ci_hi, held_MB_median, image_MB`.

**Decision.** None (calibration). **Feed back:** T2's tier is what an invoker with an image
cache sees; use its latency as `r` for the light handler. T3's cost is the fallback if β ≥ 0.7.

---

## T3. The real function's profile (S1, S2)

**Question.** What are the model's inputs for the real workload: cold start `A`, warm-up `B`,
steady run `C`, restore time `r(K)`, residual warm-up after restore `R(K)`, image size `s(K)`,
memory `m`, for snapshot depth `K`? The simulator and the predictions still use estimates
(`r` = 650 ms is the optimistic end of exp12's 0.64–9 s).

**Workload.** The Spring Boot function of exp12/exp15. It is on the box (see `RESULTS.md` on
the box), not in this repository; commit its source into `ideas/` if you can. If it is not
there, use `FnServer` + `Fn` and label every number "light handler".

**Run.** Snapshot after `K ∈ {0, 1, 5, 20, 50, 100, 200}` warm-up requests at
`vCPU ∈ {0.25, 1, 4}`, 20 repetitions per cell:
- warm-up requests are a **fixed test set, generated once with a fixed seed and committed**
  (the developer's test requests). Never copies of serving traffic;
- pin the JVM to the serving shape during warm-up (`-XX:ActiveProcessorCount=1`, an explicit
  GC), as exp-b requires;
- checkpoint with CRaC; restore; send 200 serving requests (a different fixed set).

Also measure, once per runtime, a **Python function** and an **ML-like Python stage** (loads a
model, about 300 ms per request) at K = 0 only (no JIT to capture). T10–T13 need them. If you
have none, keep the thesis's values for them and mark them "assumed".

**Measure** per cell: `A` (start → ready, no snapshot), `B` (sum over the first 200 requests
of the excess over `C`, cold), `C` (median latency of requests 150–200), `r_wall` (restore
issued → ready), `r_first` (restore → first response), `R(K)` (sum over the 200 requests
after restore of `max(0, latency − C)`), `s(K)` (image directory size), RSS after restore,
and the JIT's compiled-method count at the checkpoint (`jcmd <pid> Compiler.codelist | wc -l`).

**Control (known answer).** At `K = 0` nothing has been compiled by requests, so
`R(0) ≈ B` within the CI. A process that is never checkpointed and serves the same requests
is the floor: `R(K)` cannot be below it.

**Expected.**
- `s(K)` **nearly flat in K** (exp11: 27–32 MB for the light handler, +1.3 MB of compiled code
  from K = 0 to 200). The Spring Boot image size is unknown; `e6` assumed 90 MB. **Test it.**
- `r_wall` **flat in K** (exp11) and strongly dependent on vCPU: **0.64 s to 9 s** from 4 to
  0.25 vCPU for Spring Boot (exp12).
- `R(K)` falls with K and flattens. At 1 vCPU and K = 50, about **63 ms** per stage (exp15:
  225 ms for 3 stages, minus 3 × 12 ms of steady run).
- The compiled-method count rises monotonically in K (Proposition 8) and flattens where
  `R(K)` flattens.

**Output.** `raw/` per repetition; `profile_table.csv`: `runtime, vcpu, K, n, A_ms, B_ms,
C_ms, r_wall_ms, r_first_ms, R_ms, s_MB, rss_MB, compiled_methods` (medians, plus `_lo`/`_hi`
CI columns); the updated `results/box/profile_vcpu{v}.json` (`r` = `r_wall` at the chosen K,
`RK` = `R(K)` per stage, `C`, `A`, `B`, `m` = RSS).

**Decision.** Choose K per vCPU where the compiled-method count stops rising (Proposition 8's
stopping rule; check that `R(K)` flattens there too). Stage 2's exit: the profile table holds
measured `r`, `R`, `s` at the start-up point and at the chosen K.

---

## T4. Warm-up lost to the checkpoint, and re-warming (x3)

**Question.** A restored process is slower than the same process that was never checkpointed
(exp12: by up to 29 percentage points of captured warm-up at low CPU). How large is this loss
`L(K)`, and how much of it does re-warming a restored sandbox recover while it waits for its
input (Idea 4)?

**Change first.** `criu_box.py x3-rewarm` primes and re-warms with `fps_bulk` (scrubbed copies
of serving traffic, a dropped idea). Change it to use the fixed test set of T3.

**Run.** `sudo ./ideas/criu-box/criu_box.py x3-rewarm --reps 20 --vcpu 0.25 --K 50` and the
same at `--vcpu 1.0` (and at the K chosen in T3 if it differs).

**Measure.** Residual `R` over 200 serving requests in three modes: `continued` (never
checkpointed), `restored`, `restored+rewarm` (50 test requests after the restore). Then
`L(K) = R_restored − R_continued` and `recovered = (R_restored − R_rewarm) / L(K)`. Also the
wall time the re-warm takes (it must fit in the slack before the input arrives, or it costs
memory·time).

**Control (known answer).** `R_continued ≤ R_restored`: a restore cannot beat the process that
was never checkpointed. If it does beyond the CI, the measurement is broken.

**Expected.** `L(K) > 0`, **larger at 0.25 than at 1 vCPU** (exp12: within ~10 points at
4 vCPU, up to 29 points at 0.25). Re-warming recovers **at least 30%** of `L` at 0.25 vCPU. In
the simulator re-warming gains only 3–5% end to end (e1), so even a good result here is a
small effect.

**Output.** `raw/x3_rewarm_vcpu{v}_K{K}.json`; `summary.csv`: `vcpu, K, mode, reps,
R_ms_median, ci_lo, ci_hi, L_ms, recovered_pct, rewarm_wall_ms`.

**Decision** (`ideas/criu-box/README.md`): keep re-warming only if `L(K)` is large at the
serving vCPU **and** re-warming recovers ≥ 30% of it. Otherwise drop it: the recommended
policy loses its "+rw", and the thesis says so. **Feed back:** `RK` in the profile must include
`L(K)` (`MODEL.md` §6b: `R^restore = R + L`).

---

## T5. Snapshot uniqueness (S3; Stage 5's control)

**Question.** Copies restored from one image start with the same memory. Do they produce the
same random numbers, UUIDs and secrets (the risk Brooker et al. describe)? Do the builder's
reset hooks fix it?

**Write.** A `/uniq` endpoint in `FnServer` that returns: `nextLong()` of a `java.util.Random`
created at start-up; `Math.random()`; `UUID.randomUUID()`; 16 bytes of a `SecureRandom` created
at start-up; a "secret" token generated at start-up; `System.nanoTime()`. Plus a CRaC
`Resource` (`org.crac.Core.getGlobalContext().register(...)`) whose `afterRestore` re-seeds the
`Random`, re-creates the `SecureRandom` and regenerates the token, switched on and off by
`-Dreset.hooks=on|off`.

**Run.** Checkpoint once with the hooks off and once with them on. Restore 10 copies of each
(separate containers). Call `/uniq` once per copy right after its restore.

**Measure.** For each field, the number of distinct values among the 10 copies. **Store
SHA-256 hashes of the values, not the values.**

**Control (known answer).** Hooks off: the start-up `Random`'s `nextLong()` and the start-up
token are **identical in all 10 copies** (1 distinct value). If they are not, the test cannot
see the problem (something already re-seeds): find out what before going on.

**Expected.** Hooks off: `Random`, `Math.random()` and the token repeat (1 of 10 distinct).
`UUID.randomUUID()` and `SecureRandom`: record what happens, do not assume; the CRaC JDK may
re-seed its secure random sources on restore. `nanoTime` differs. Hooks on: **every field has
10 distinct values.**

**Output.** `raw/uniq.csv`: `hooks, copy, field, value_sha256`; `summary.csv`: `hooks, field,
distinct_of_10`. **Decision:** Stage 5's exit requires 10/10 distinct for every field with the
hooks on. The snapshot builder installs them.

---

## T6. The vCPU cliff, cold and restored (exp14 data; S4)

**Question.** (a) The thesis's first finding is the vCPU cliff (JVM warm-up 13–35× slower from 4
to 0.25 vCPU, exp14), but its raw data is not in this repository, so it has no figure.
(b) Do deep snapshots flatten the cliff (S4)?

**Run.** (a) Copy exp14's raw CSV from the box into `results/box/T6-cliff/raw/exp14.csv`, with
its column description. (b) At `vCPU ∈ {0.25, 0.5, 1, 2, 4}`, 20 repetitions: cold; restored
at K = 0; restored at the K chosen in T3.

**Measure.** `B` for cold starts, `R(K)` for restores (as in T3), first-response latency, `C`.

**Control.** `C` (steady state) at each vCPU is the floor for every mode.

**Expected.** Cold: `B(0.25) / B(4)` **13–35×** (exp14), and `B ≈ 0.185·W` still fits.
Restored at K = 0: most of the cliff remains (nothing was compiled before the checkpoint).
Restored deep: **flatter**. The theory gives no number here; register a guess before running
(ours: the deep-snapshot ratio is below 5×, against 13–35× cold).

**Output.** `raw/exp14.csv`, `raw/cliff.csv` (`vcpu, mode, rep, B_or_R_ms, first_ms, C_ms`),
`summary.csv`. Then add figure 9 to `figures/make_figures.py` in the same style (the
`figures/README.md` note asks for it). **Decision:** if confirmed, S4's headline stands: deep
snapshots matter most exactly where FaaS runs.

---

## T7. One snapshot action inside OpenWhisk; the wake call; the edge delay δ

**Question.** Can OpenWhisk start an action by restoring a CRaC snapshot, at what overhead,
and what is the real per-edge delay `δ` between two stages? (The model assumes 2 ms.
OpenWhisk's invocation path through the controller is likely much slower, and `δ` is in the
look-ahead slope `w + δ`.)

**Build** (`ROADMAP.md` §1.3): the snapshot action image (`FnServer` changed to OpenWhisk's
`/init` and `/run` on port 8080, started with `java -XX:CRaCRestoreFrom=<dir>`); the wake call
(`{"__wake": true}` returns at once); the invoker's capabilities for CRaC; the invoker's user
memory raised (T0); a local registry. Disable the prewarm pool for these actions. OpenWhisk sets
CPU shares from the action's memory, not quotas. To get 0.25 and 1 vCPU, pass `--cpus` through
the invoker's container arguments, and record exactly how.

**Run.** 20 cold activations each: the stock Java action; the snapshot action; the snapshot
action woken first (wake, wait for it, then the real call); warm activations as the floor.
Then δ: a 2-stage chain through your orchestrator with both containers warm, 100 repetitions.

**Measure.** Client end-to-end latency; the activation record's `duration`, `initTime` and
`waitTime`; the wake call's latency (cold and warm); `δ` = time from stage 1's result at the
orchestrator to stage 2's handler start.

**Control.** Warm activations are the floor. The standalone restore (T1b, N = 1) predicts the
snapshot action's cold start minus a constant OpenWhisk overhead.

**Expected.** **20/20** cold starts succeed. Snapshot-action cold start ≈ T1b's restore + a
constant overhead (small spread). `δ` well above 2 ms: tens of ms is plausible (a guess). With
`δ` = 30 ms, for example, the look-ahead slope for Java at 1 vCPU becomes 105 ms per stage
instead of 77.

**Output.** `raw/ow_cold.csv` (`mode, rep, e2e_ms, duration_ms, initTime_ms, waitTime_ms`),
`raw/delta.csv`, `summary.csv`. **Decision:** Stage 3's exit (20/20, and cold ≈ restore +
constant). **Feed back:** `delta_ms` in the profile; rerun `predict.py`.

---

## T8. Look-ahead on chains: the headline result (Stage 4)

**Question.** On the real system, does look-ahead collapse the restore cascade? The theory
says on demand costs `r + w + δ` per stage, and look-ahead `w + δ` per stage after the first
restore (Theorem 1, Corollary 1.1).

**Build.** The orchestrator (Python, `ROADMAP.md` §1.3): runs a chain through OpenWhisk's REST
API; three policies:
- **on demand**: call each stage when its input is ready;
- **eager**: wake every stage at t = 0;
- **JIT look-ahead**: wake stage v at `τ_v = S*_v − r_v`, computed from the profile
  (`theory/verify_dag.py: jit()`).

Plus the gate: if the entry has a live container, no wake calls.

**Run.** Chains of `d = 1…8` Java stages at 0.25 and 1 vCPU, three policies, **20 cold runs
each** (960 runs). Before each run, make sure no container of the chain's actions is alive.
Sample every action container's cgroup `memory.current` every 10 ms.

**Measure.** End-to-end latency; per stage: wake sent (τ), ready, input arrived, start,
finish; memory: the peak of the sum over containers, and memory·time (GB·s).

**Control (known answer).** At `d = 1` the three policies are equal within the CI: there is
nothing to look ahead to. And on-demand latency matches `Σ (r + w) + (d − 1)δ` with the T3/T7
profile (Theorem 1(c)).

**Expected.** Run `predict.py` with the measured profile and commit its output. With the
thesis's values (Java, 1 vCPU, β = 0) it gives:

| d | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| on demand (ms) | 725 | 1452 | 2179 | 2906 | 3633 | 4360 | 5087 | 5814 |
| look-ahead (ms) | 725 | 802 | 879 | 956 | 1033 | 1110 | 1187 | 1264 |
| peak memory, look-ahead (MB; on demand 512) | 512 | 1024 | 1536 | 2048 | 2560 | 3072 | 3584 | 4096 |

- **Slopes:** on demand **727 ms per stage** (`r + w + δ`), look-ahead **77 ms per stage**
  (`w + δ`); a straight line fits each with R² ≥ 0.99 (Xanadu reports 0.993 for the cascade on
  AWS Step Functions).
- With contention: look-ahead ≤ on demand − `(1 − β)(d − 1)r` (Corollary 1.2).
- Eager = JIT in latency. Memory·time: JIT = on demand (Theorem 2), eager more (at d = 8:
  2.97 vs 4.07 GB·s).
- Peak memory: on demand `m`; look-ahead `m · min(d, ⌈(r + w)/(w + δ)⌉)` (Theorem 8(a)): 8× at
  d = 8.
- The simulator with timing noise and re-warming (`e10a`): 3 / 5 / 8 stages 2.20 / 3.67 /
  5.89 s → 0.88 / 0.99 / 1.19 s.
- At 0.25 vCPU both slopes are steeper (`r` and `w` grow), and the gap between them grows.
  That is the **cascade × cliff figure**.

**Output.**
- `raw/runs.csv`: `vcpu, d, policy, rep, e2e_ms, peak_MB, memtime_GBs`;
- `raw/stages.csv`: `run_id, stage, tau_ms, ready_ms, input_ms, start_ms, finish_ms`;
- `raw/mem/`: the memory samples;
- `fit.csv`: `vcpu, policy, slope_ms, slope_ci_lo, slope_ci_hi, intercept_ms, R2,
  predicted_slope_ms`;
- the figure: latency against `d`, 4 lines (2 policies × 2 vCPU), fitted slopes written on it.

**Decision.** Stage 4's exit: each measured line matches its prediction within the CI, or the
difference is explained (the usual suspects: β, `δ`, the wake call's own cost, OpenWhisk
reusing or not reusing a woken container). If the look-ahead slope is not far below the
on-demand slope, stop and find out why before T9.

---

## T9. Memory: peak, k sandboxes, the guard (Theorem 8)

**Question.** Look-ahead raises the memory peak. With a budget of `k` sandboxes, how fast is
it, and does the guard keep the budget?

**Run.** The 8-stage chain at 1 vCPU, JIT look-ahead with the orchestrator's memory guard at a
budget of `k · m`, `k ∈ {1, 2, 3, 4, 8}`, 20 cold runs each; on demand at the same budgets.

**Measure.** Latency; the largest sampled memory (sum over the chain's containers); guard
preemptions.

**Control (known answer).** `k = 1` equals on demand within the CI (Theorem 8(b):
`d(r + w)` vs `d(r + w) + (d − 1)δ`). `k = 8` equals unconstrained look-ahead (T8).

**Expected** (`predict.py`, thesis values): **5800 / 2977 / 2252 / 1681 / 1264 ms** for
k = 1, 2, 3, 4, 8 (on demand 5814). Each extra slot divides the restore cost. The sampled
memory **never** exceeds `k · m` (allow the sampling error), and no run deadlocks.

**Output.** `raw/slots.csv`: `k, policy, rep, e2e_ms, max_mem_MB, preemptions`; `raw/mem/`.
**Decision:** Theorem 8 confirmed on the real system, or the gap explained.

---

## T10. The exact planner vs the guard (Algorithm 2)

**Question.** When the budget binds, does planning the restore triggers exactly beat the
guard, as the solver and the simulator say?

**Run.** `ALGORITHM.md` §5's workflow: a Python entry feeding a Java → Java chain and an ML
stage, budget = the ML stage's memory (1 GB). Policies: capped on demand, the guard, the plan
(port `ideas/sim/planner.py` into the orchestrator; the guard executes the planned triggers,
and a restore that does not fit waits in the queue). 20 cold runs each. Any three functions
with different `(r, w, m)` work; recompute the prediction from their measured profiles.

**Measure.** Latency; the largest sampled memory; preemptions; the planner's compute time.

**Control (known answer).** Without a budget, the three look-ahead policies are identical.

**Expected** (`predict.py`, thesis values): no budget **802 ms** (peak 2.3 GB); guard
**1950 ms**; capped on demand **2037 ms**; plan **1310 ms**, triggers 0, 0, 85, 810 ms (entry,
Java 1, Java 2, ML stage). The plan holds the ML stage back although its input is there,
because it is short enough to finish behind the Java chain. (`ALGORITHM.md` quotes 1930 /
2012 / 1285 ms with run times rounded to 20 and 300 ms.) The simulator (`e9a`): the plan is
never slower than the guard, and up to 48% faster.

**Output.** `raw/planner.csv`: `policy, budget_MB, rep, e2e_ms, max_mem_MB, preemptions,
plan_ms`.

---

## T11. Other shapes, branches, uncertain times (Theorems 1, 3, 4)

**(a) Shapes.** The simulator's workflows (`ideas/sim/dagsim.py`: `fanout`, `ml_pipeline`,
`mixed`, `router`, `trip_booking`), no budget, on demand vs look-ahead, 20 cold runs each.
*Expected* (`e9a`, thesis values, mean with timing noise): fan-out ×4 1764 → 918 ms; ML
pipeline 2123 → 852; mixed 1521 → 800; router 3077 → 1134; trip booking 3108 → 1017.
Recompute with the measured profile (`DAGSIM_PROFILE=… run_sim.py e9a`, rows with budget
`inf`). *Control:* a one-stage workflow, all policies equal.

**(b) Branches (Theorem 4).** The router with the branch probability set to
`p ∈ {0.1, 0.3, 0.5, 0.7, 0.9}`. Two policies: restore both branches ahead (speculate), or
restore after the decision. *Measure:* latency, and the wasted memory·time (restored, never
used). Compute the cost `J = a · latency + b · waste` with a price ratio chosen so that
`κ = b/(a + b) = 0.5`. *Expected:* speculation has the lower `J` **iff `p ≥ κ`** (0.5 here).
*Control:* when the branch is decided early enough (`D ≤ τ^J`), both policies give the same
latency (Theorem 4(a)).

**(c) Uncertain times (Theorem 3).** Make the upstream stage's run time random (the handler
sleeps a lognormal time, σ = 0.5), and trigger the downstream restore at quantiles
`q ∈ {0.1, 0.3, 0.5, 0.7, 0.9}` of the input-time distribution. *Measure:* the delay
`E[(x − I)⁺]` and the idle memory `m · E[(I − x)⁺]`; compute `J` for two price ratios.
*Expected:* `J` is lowest at **`q = κ`**. *Control:* the "wrong" quantile `a/(a + b)` costs
more.

**Output.** `raw/shapes.csv`, `raw/branches.csv`, `raw/quantile.csv`, one `summary.csv` each.

---

## T12. A burst of cold workflows under a shared budget

**Question.** 16 cold 8-stage chains arrive within 1 s. Does the guard keep the budget, and is
look-ahead still faster?

**Run.** Budgets of 8 and 16 GB (the box has 31 GB). Policies: on demand; look-ahead without
the guard; the guard; the plan. 10 bursts each.

**Measure.** Mean and p99 latency; starts over the budget (OpenWhisk refusing or queueing);
restores.

**Expected.** Recompute with the measured profile (`DAGSIM_PROFILE=… run_sim.py e7a e9b`). With
the thesis's values (`e7a`, `e9b`): look-ahead without the guard exceeds the budget
(32.6 starts over it per run at 8 GB, on demand none); with the guard, **zero** at every
budget that on demand itself fits in, and still faster (8 GB: 5.77 vs 5.91 s; 16 GB: 4.35 s);
the plan 3–11% faster than the guard on average.

**Output.** `raw/burst.csv`: `budget_GB, policy, burst, workflow, e2e_ms, over_budget_starts,
restores`.

---

## T13. Evaluation against the baselines (Stage 7)

**Question.** The comparison the thesis will be judged on.

**Workloads.** The exp15 3-stage Spring Boot workflow; 3–5 SeBS-Flow workflows ported to Java.
**Arrivals:** the Azure Functions 2021 trace (`ideas/sim/prep_azure.py` parses it). Choose the
workflows and a time window whose working set fits the box (for example a 6–24 h window,
replayed in real time, since keep-alive depends on real time). Record the choice.

**Baselines.** Cold (no snapshot); OpenWhisk keep-alive (10 min); restore on demand (what
SnapStart does); cold prewarm along the DAG (Xanadu-style, just in time); the JVM flag
`-XX:TieredStopAtLevel=1` (`RESEARCH_PLAN.md` S6 names level 3; run 1, and 3 if time allows);
JDK 25 ahead-of-time profiles (JEP 515). **Ours:** the recommended policy (gate + JIT
look-ahead + guard + planner + GDSF keep-alive, re-warm only if T4 kept it).

**Measure.** For all calls and for calls that find their workflow cold: mean, p50, p99
latency; memory·time and average memory held; restores per 1000 calls; starts over the budget;
snapshot storage. CIs by a block bootstrap over workflows (calls of one workflow are
correlated).

**Prediction.** Before the replay, run the simulator with the measured profile on the **same
workflows, window and budget** (add an experiment to `run_sim.py` that takes the subset), and
commit its output. For scale, the thesis's simulation (`e10b`, full trace):
- at a budget that does not bind: cold workflows **2.34 → 0.81 s** mean and **6.20 → 1.25 s**
  p99 against restore on demand, at the same memory (≈ 50 GB) and ≈ 21 starts per 1000 calls;
- at a tight budget (32 GB): all calls' p99 **3.24 → 1.10 s**, with 29% more restores.

**Output.** `raw/calls.csv`: `policy, workflow, invocation, t_arrival_s, cold, e2e_ms`;
`raw/mem/`; `summary.csv`: `policy, population, metric, value, ci_lo, ci_hi`; the figures.
**Decision:** Stage 7's exit: every claim in `REPORT.md` confirmed on the real system or
corrected.

---

## Feeding results back

After each test that changes a number the thesis uses:

1. Update `results/box/profile_vcpu<v>.json`, rerun `predict.py`, and commit its output.
2. Rerun the simulator with the measured profile into its own folder, keeping the thesis's
   runs intact:
   `DAGSIM_PROFILE=results/box/profile_vcpu1.0.json DAGSIM_OUT=results/box/sim python3 ideas/sim/run_sim.py e10`.
3. Update the documents, keeping the old number visible where it changes a claim:
   - `theory/DAG_SNAPSHOT_THEORY.md` §5: `[assumption]` → `[measured]` for A2 (β, T1) and
     A3 (`L(K)`, T4);
   - `ideas/IDEAS.md` and `ROADMAP.md` §0;
   - `REPORT.md`, `PROFESSOR_REPORT.md` and `figures/README.md` (captions quote numbers);
   - `figures/make_figures.py`: add the measured lines to figures 1, 3 and 5, and figure 9 (T6).
4. `python3 theory/verify_dag.py` must still pass 76/76. The theorems do not depend on the
   measured values; the verification is a check that nothing else broke.

## What would change the plan

| finding | consequence |
|---|---|
| β ≥ 0.7 (T1/T1b) and not fixable | look-ahead is weak here; the thesis leads with Theorem 7, the memory results and the measurement study; use T2's pre-restored tier as the timing fallback |
| restore time `r` far below 650 ms (T3), for example < 100 ms | little to hide: the look-ahead gain `(d − 1)r` shrinks; lead with 0.25 vCPU, where `r` is largest |
| `δ` ≫ `w` in OpenWhisk (T7) | the look-ahead slope is dominated by the platform, not the function; report it and compare with an orchestrator path that bypasses the controller |
| `L(K)` small or re-warming recovers < 30% (T4) | drop re-warm (Idea 4) from the recommended policy |
| identical random values with hooks on (T5) | the snapshot builder is not safe yet; fix before any evaluation with real secrets |
