# T6b. CPU during start-up: speed-up, CPU cost, boost while starting, contention

**Engine: Warp.** Data: the grid (`../T3-profile/raw/`: `grid.jsonl`, `boost.jsonl`,
`contention_v2.jsonl`); `analyze.py` → `speedup.csv`, `boost.csv`, `contention.csv`.

## Question
The CPU plan (`ideas/sim/cpuplan.py`, e11, e12) assumes that a start-up (1) finishes about in
proportion to the CPU it gets, up to about one core, (2) uses the same CPU-seconds whatever its
quota, and (3) can be boosted while starting and lowered afterwards without harm. True?

## Setup
- Speed-up: the grid's fixed-quota runs (T3), cold and restore at K = 0 / 50, vCPU 0.25–4, 20 each;
  CPU-seconds and throttled periods from the cgroup's `cpu.stat`.
- Boost: start at 1 or 2 vCPU, set the quota to 0.25 vCPU the moment the first response is printed
  (`grid.py` phase `boost`; the change lands 1.4–4.8 ms after the response), then the 200 requests at
  0.25 vCPU; cold, restore K = 0, K = 50; 20 each.
- Contention: 2 or 4 K = 50 restores on **one core** (cpuset), each in its own cgroup: `equal` (quota
  1/N each, all at once) vs `one_at_a_time` (full core, the next starts when the previous answered,
  the e11 rule). A copy is ended at its first response (`cgroup.kill`) so it stops competing.
  (A first version throttled finished copies to 1% instead, which made each repetition take
  minutes; its partial rows are in `contention.jsonl`, unused.) 20 repetitions.

## Prediction (`prediction.md`)
0.25 → 1 vCPU about 4× faster at about the same CPU-seconds; 1 → 4 vCPU less, with more
CPU-seconds; restores scale like warm-up (if < 2× from 0.25 to 1, the linear model is wrong for
restores); boost runs serve requests 2–200 as fast as runs that stayed at 0.25. Control: at 1 vCPU,
fixed and boost runs identical up to the first response.

## Result

**Speed-up and CPU cost** (TTFR median; speed-up and CPU-seconds relative to 0.25 vCPU):

| mode | 0.5 | 1 | 2 | 4 vCPU | CPU-s (0.25 → 4) |
|---|---|---|---|---|---|
| cold | 2.07× | **4.17×** | **8.32×** | 9.2× | 5.40 → 5.16 (0.94–1.00×) |
| cold, JVM not pinned | 2.05× | 4.16× | 8.56× | 10.5× | 5.45 → 5.61 |
| restore K = 0 | 2.61× | **3.53×** | 10.0× | 10.8× | 2.11 → 1.85 |
| restore K = 50 | 2.34× | 2.10×* | 6.28× | 6.48× | 1.12 → 1.03 |

\* the grid's bimodal 1 vCPU restores (`../T3-profile/REPORT.md`); D2 gives 284 → 67 ms = 4.2× for
Warp and 375 → 84 ms = 4.5× for CRIU from 0.25 to 1 vCPU.

**Boost** (median):

| boost | mode | TTFR boost | TTFR fixed at 0.25 | later requests p50, boost / fixed 0.25 | CPU-s boost / fixed |
|---|---|---|---|---|---|
| 1 vCPU | restore K = 50 | **59 ms** | 380 ms | 1.71 / 1.68 ms | 1.11 / 1.12 |
| 1 vCPU | restore K = 0 | 472 ms | 2 675 ms | 3.34 / 2.44 ms | 2.06 / 2.11 |
| 1 vCPU | cold | 3 824 ms | 16 551 ms | 2.57 / 2.20 ms | 5.27 / 5.40 |
| 2 vCPU | restore K = 50 | 60 ms | 380 ms | 1.84 / 1.68 ms | 1.17 / 1.12 |
| 2 vCPU | restore K = 0 | 250 ms | 2 675 ms | 3.03 / 2.44 ms | 2.05 / 2.11 |
| 2 vCPU | cold | 1 957 ms | 16 551 ms | 3.34 / 2.20 ms | 5.28 / 5.40 |

**Contention on one core** (ready time after the common start, ms, median; n = 20):

| N | rule | mean | first | last |
|---|---|---|---|---|
| 2 | equal | 140 | 135 | 146 |
| 2 | one at a time | **114** | 70 | 158 |
| 4 | equal | 279 | 259 | 299 |
| 4 | one at a time | **203** | 72 | 335 |

## Control
At 1 vCPU, boost and fixed-quota runs should be identical up to the first response. Against the
grid's fixed runs it **fails** (restore K = 50: 59 vs 181 ms; K = 0: 472 vs 758 ms), because of the
grid's interleaving anomaly; against D1/D2's fixed 1 vCPU restores (K = 50: 67–82 ms; K = 0:
474–499 ms) it **passes**. Cold starts pass against the grid itself (3 824 vs 3 968 ms).

## Verdict
1. **Speed-up in proportion to CPU: confirmed, beyond one core.** A cold JVM start runs 4.2× faster
   at 4× the CPU and **8.3× faster at 8×** (2 vCPU), flattening only past 2 vCPU. A restore at K = 0:
   3.5× at 1 vCPU, 10× at 2. The JVM pinned to one CPU (`ActiveProcessorCount=1`) still uses ~2
   cores during start-up (GC, JIT and class-loading threads). **The model's cap of one core is
   too low: ≈ 2 cores.**
2. **Same CPU-seconds: confirmed.** 0.88–1.03× of the 0.25 vCPU CPU-seconds at every quota, for
   every mode. More CPU does the same work sooner, not more work.
3. **Boost, then lower: half confirmed.** Lowering the quota works (1.4–4.8 ms) and costs no extra
   CPU. For a deep restore, the later requests are as fast as without the boost (1.71 vs 1.68 ms).
   **For K = 0 and cold starts they are 17–52% slower**: the boost brings the first response
   forward, so less JIT compilation has happened by then and the residual warm-up moves into the
   following requests. The boost buys the first response; it does not buy the warm-up.
4. **One core: one at a time beats an equal split by 19–27% in mean ready time** and readies the
   first start-up 1.9–3.6× sooner, at an 8–12% later last one: the CPU plan's rule for ≤ 1 spare core,
   measured.

**Decision:** the CPU plan's premise holds — start-up is CPU work that speeds up with CPU at constant
CPU-seconds — so the plan has something to allocate.

## What changes
- `cpu_cap` in the simulator: 1 → **2 cores** for JVM start-up (cold and restore). Rerun e11/e12.
- The boost should last until the start-up's **warm-up** is done (or its residual is small), not
  only until the first response; for a deep snapshot the first response is enough.
- `-XX:ActiveProcessorCount=1` does not limit start-up to one core; the quota does.
