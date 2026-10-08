#!/usr/bin/env python3
"""T1b summary: raw/runs.jsonl -> summary.csv (MACHINE_TEST_PLAN.md T1 schema).

beta(N) = (median r_max(N) / median r_max(1) - 1) / (N - 1), with r(1) the parallel N = 1 cell of
the same vCPU (docker-noop uses its own N = 1). 95% CI: bootstrap, resampling the repetitions of
N and of N = 1 independently (10,000). c_eff = 1 / beta (restores that effectively run at once)."""
import csv
import json
import os
import random
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
rows = [json.loads(l) for l in open(os.path.join(HERE, "raw", "runs.jsonl"))]
rnd = random.Random(1)
B = 10_000


def p95(xs):
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def beta(rN, r1, N):
    return (statistics.median(rN) / statistics.median(r1) - 1) / (N - 1)


cell = {}
for r in rows:
    if r["r_max_ms"] is not None:
        cell.setdefault((r["variant"], r["vcpu"], r["N"]), []).append(r["r_max_ms"])
fails = sum(r["failed"] for r in rows)
out = []
for (var, v, N), xs in sorted(cell.items()):
    base = cell.get((var if var in ("docker-noop", "exec") else "parallel", v, 1))
    row = dict(variant=var, vcpu=v, N=N, reps=len(xs), r1_median_ms=round(statistics.median(base), 1),
               rmax_median_ms=round(statistics.median(xs), 1), rmax_p95_ms=round(p95(xs), 1),
               beta="", beta_ci_lo="", beta_ci_hi="", c_eff="")
    if N > 1:
        b = beta(xs, base, N)
        bs = sorted(beta(rnd.choices(xs, k=len(xs)), rnd.choices(base, k=len(base)), N) for _ in range(B))
        row.update(beta=round(b, 3), beta_ci_lo=round(bs[int(.025 * B)], 3), beta_ci_hi=round(bs[int(.975 * B)], 3),
                   c_eff=round(1 / b, 2) if b > 0 else "inf")
    out.append(row)
with open(os.path.join(HERE, "summary.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0]))
    w.writeheader()
    w.writerows(out)
for o in out:
    print(o)
print("failed copies:", fails)
