# exp-a / exp-b — what should a deep snapshot be primed on?

Real JVM measurements (OpenJDK 21.0.10, x86_64, 4 vCPU Firecracker VM), run 2026-09-26.
Results and interpretation: `../IDEAS.md` §2, §3, §5.

## Design

**Workload** (`src/Fn.java`): one stage of an order-processing workflow. Jackson
polymorphic deserialisation over 6 item subtypes, BigDecimal tax and discount rules, regex
validation, stream grouping, JSON serialisation. Two DAG edges feed it:
`web` (1–4 book/electronics items, USD, no metadata) and `bulk` (40–120
grocery/subscription items, EUR, 8–20 metadata entries).

**A run** = fresh JVM in its own cgroup (v1 `cpu` quota + `cpuset`) → `K` priming requests
from one set → 1 s settle → (exp-b: change the quota) → serve 300 requests of the target
edge, per-request latency recorded in-process. JIT counters are read from the JVM's
hsperfdata file, so measuring charges no CPU to the cgroup.

**Emulation, stated:** the snapshot's *content* is a process that has served K requests.
CRIU restore time and checkpoint-lost warm-up (`L(K)`) are not included. They are additive
and do not depend on the priming set, so comparisons *between priming sets* hold;
absolute residuals are optimistic. `../criu-box/` x4 repeats exp-a with real restores.

| design | factors | n |
|---|---|---|
| exp-a | priming set {real_bulk, real_bulk2 (A/A control), fps_bulk, schema_bulk, real_web, mixed} × K {25, 100, 400} × vCPU {1, 0.25}, + K=0 and reference K=1500; serve bulk | 10 |
| exp-a-web | priming set {real_web, fps_web, real_bulk, mixed} × vCPU {1, 0.25}, K=100, + K=0, ref; serve web | 10 |
| exp-a-mix | mixed at K {200, 800} (same bulk count as real_bulk K {100, 400}) × vCPU {1, 0.25} | 10 |
| exp-b | prime at {0.25, 1, 4} vCPU × K {100, 400} × JVM sizing {pinned to 1 CPU + SerialGC, default ergonomics}, serve at 0.25 vCPU | 10 |

**Metric:** residual warm-up `R300 = Σ max(0, latency − C)` over the 300 served requests,
with `C` the steady-state latency (median of the last 200 requests of the reference
condition at the same CPU level). Ratios between priming sets carry 95% bootstrap CIs over
runs.

**Controls:** `real_bulk2` is the same distribution as `real_bulk` with a different seed, so
its ratio must be ~1; K=0 and K=1500 bracket the range. Conditions are shuffled across the
run order; 3 parallel workers are pinned to separate cores, the harness and simulator to core 0. exp-b needs all four cores and ran alone. 8 exp-b runs that overlapped with a
simulator process were deleted and re-run.

## Reproduce

```bash
./fetch_deps.sh            # Jackson 2.17.2 + javac
python3 gen_inputs.py      # deterministic; ~74 MB of JSON lines in inputs/
sudo ./run_all.sh          # resumable; ~60 min on 4 cores
python3 analyze.py         # tables, ratios with CIs, results/*_curves.png
```

`gen_inputs.py` also contains the format-preserving scrubber (`learn_categorical`,
`scrub`) and writes a leakage audit to `inputs/fps_audit.json`.
