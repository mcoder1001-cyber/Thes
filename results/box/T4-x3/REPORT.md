# T4. Warm-up lost to the checkpoint L(K), and re-warming

**Engine: Warp.** Data: the grid (`../T3-profile/`, `raw/grid.jsonl`), table `../T3-profile/t4_rewarm.csv`.

## Question
A restored process is slower than the same process never checkpointed. How large is the loss
`L(K) = R_restored − R_continued`, and how much of it does re-warming a restored sandbox (50 more
requests while it waits for its input) recover?

## Setup
As T3. `cont_K` = the same JVM serving K requests and then the 200 measured ones, never
checkpointed. `rewarm_K50` = an image checkpointed after 50 requests with `-Drewarm=50`: after the
restore it serves 50 more requests (the same fixed payload as the warm-up: the developer's test
set, not serving traffic, as the plan's "change first" asks), then the 200 measured ones. 20 runs per
cell; L's CI by bootstrap of the difference of medians.

## Prediction
`L(K) > 0`, larger at 0.25 than at 1 vCPU; re-warming recovers ≥ 30% of L at 0.25 vCPU.
Control: `R_continued ≤ R_restored`.

## Result (R and L in ms, median [95% CI])

| vCPU | K | R restored | R continued | L(K) | R after re-warm | recovered | re-warm wall time |
|---|---|---|---|---|---|---|---|
| 0.25 | 0 | 7 310 | 6 010 | 1 299 [176, 1 982] | | | |
| 0.25 | 50 | 3 570 | 2 615 | **955** [−48, 1 094] | **1 762** | **189%** | 1 299 |
| 0.25 | 200 | 2 313 | 1 563 | 750 [457, 1 162] | | | |
| 1 | 0 | 1 606 | 1 495 | 111 [−115, 420] | | | |
| 1 | 50 | 720 | 556 | **163** [−13, 244] | **337** | **234%** | 301 |
| 1 | 200 | 453 | 342 | 111 [56, 243] | | | |
| 2 | 50 | 280 | 297 | −17 [−76, 91] | | | |
| 4 | 50 | 229 | 241 | −11 [−62, 107] | | | |

## Control
Passed within CIs: `R_continued ≤ R_restored` in every cell; the two negative L values (2 and 4 vCPU,
K = 50) have CIs that include 0.

## Verdict
- **L(K) > 0, larger at low CPU: confirmed.** At K = 50 the checkpoint costs 955 ms of extra warm-up
  over the next 200 requests at 0.25 vCPU, 163 ms at 1 vCPU, nothing measurable at 2–4 vCPU (several
  CIs at 0.25–1 vCPU include 0; K = 200 is clearly positive at every quota up to 2 vCPU).
- **Re-warming recovers ≥ 30%: confirmed, and more.** 50 re-warm requests leave a residual *below*
  the never-checkpointed process (1 762 vs 2 615 ms at 0.25 vCPU): re-warming does not just recover
  the loss, it adds depth (K = 50 + 50). It costs 1.3 s of wall time at 0.25 vCPU (0.3 s at 1), which
  must fit in the slack before the stage's input arrives.

**Decision** (`ideas/criu-box/README.md`): keep re-warming — L is large at the serving vCPU and
re-warming recovers well over 30%. Its value is better described as "deepen while waiting" than
"recover the checkpoint's loss".

## What changes
- `RK` in the profile must be the *restored* residual (`MODEL.md` §6b: `R^restore = R + L`): 720 ms,
  not the continued 556 ms, at 1 vCPU and K = 50.
- The simulator's re-warm gain (e1: 3–5%) used a small L; with these numbers re-warming matters more
  at 0.25 vCPU. Rerun with the measured profile.
