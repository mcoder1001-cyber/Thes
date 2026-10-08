#!/usr/bin/env python3
"""T6b summary from the grid's raw data (../T3-profile/raw/):
  speedup.csv     per mode (cold, restore_K0, restore_K50) and vCPU: TTFR median [CI], CPU-s, speed-up
                  and CPU-s relative to 0.25 vCPU (from grid.jsonl)
  boost.csv       boost runs (1 or 2 vCPU until the first response, then 0.25): TTFR, residual over
                  the 200 later requests, steady p50; next to the fixed-quota grid runs at the
                  boost level (TTFR) and at 0.25 (later requests)
  contention.csv  2 and 4 K=50 restores on one core: equal split vs one at a time (mean, max ready)
Bootstrap: 10,000 resamples of the median."""
import csv
import json
import os
import random
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "..", "T3-profile", "raw")
rnd = random.Random(1)
B = 10_000


def load(name):
    p = os.path.join(RAW, name)
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


def med(x):
    return st.median(x)


def ci(x):
    bs = sorted(med(rnd.choices(x, k=len(x))) for _ in range(B))
    return bs[int(.025 * B)], bs[int(.975 * B)]


def write(name, rows):
    if not rows:
        return
    with open(os.path.join(HERE, name), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(r)
    print()


grid = [r for r in load("grid.jsonl") if r.get("ttfr_ms") is not None]
boost = [r for r in load("boost.jsonl") if r.get("ttfr_ms") is not None]
cont = load("contention_v2.jsonl")

# ---- speed-up curve
sp = []
for m in ("cold", "cold_np", "restore_K0", "restore_K50"):
    base = [r for r in grid if r["mode"] == m and r["vcpu"] == 0.25]
    for v in sorted({r["vcpu"] for r in grid}):
        xs = [r for r in grid if r["mode"] == m and r["vcpu"] == v]
        if not xs:
            continue
        t = [r["ttfr_ms"] for r in xs]
        c = [r["cpu_s"] for r in xs]
        lo, hi = ci(t)
        row = dict(mode=m, vcpu=v, n=len(xs), ttfr_median_ms=round(med(t), 1), ci_lo=round(lo, 1), ci_hi=round(hi, 1),
                   cpu_s_median=round(med(c), 2), throttled_median=med([r["nr_throttled"] for r in xs]))
        if base:
            row["speedup_vs_0.25"] = round(med([r["ttfr_ms"] for r in base]) / med(t), 2)
            row["cpu_s_vs_0.25"] = round(med(c) / med([r["cpu_s"] for r in base]), 2)
        sp.append(row)
write("speedup.csv", sp)


# ---- boost
def resid(r, floor):
    return sum(max(0.0, x - floor) for x in r["curve_ms"])


floor = min((med(r["curve_ms"][150:200]) for r in grid if r["vcpu"] == 0.25 and len(r["curve_ms"]) >= 200),
            default=None)
bo = []
for b in (1.0, 2.0):
    for m in ("cold", "restore_K0", "restore_K50"):
        xs = [r for r in boost if r["boost_vcpu"] == b and r["mode"] == m]
        fixed_b = [r["ttfr_ms"] for r in grid if r["vcpu"] == b and r["mode"] == m]
        fixed_q = [r for r in grid if r["vcpu"] == 0.25 and r["mode"] == m]
        if not xs:
            continue
        row = dict(boost_vcpu=b, mode=m, n=len(xs), ttfr_boost_ms=round(med([r["ttfr_ms"] for r in xs]), 1),
                   ttfr_fixed_at_boost_ms=round(med(fixed_b), 1) if fixed_b else "",
                   ttfr_fixed_q025_ms=round(med([r["ttfr_ms"] for r in fixed_q]), 1) if fixed_q else "",
                   cpu_s_boost=round(med([r["cpu_s"] for r in xs]), 2),
                   cpu_s_fixed_q025=round(med([r["cpu_s"] for r in fixed_q]), 2) if fixed_q else "",
                   steady_p50_boost_ms=round(med([med(r["curve_ms"][150:200]) for r in xs]), 3),
                   steady_p50_fixed_q025_ms=round(med([med(r["curve_ms"][150:200]) for r in fixed_q]), 3) if fixed_q else "",
                   lower_lag_ms_median=round(med([r["first_seen_lag_ms"] for r in xs if r.get("first_seen_lag_ms")]), 2))
        if floor:
            row["R_boost_ms"] = round(med([resid(r, floor) for r in xs]), 1)
            row["R_fixed_q025_ms"] = round(med([resid(r, floor) for r in fixed_q]), 1) if fixed_q else ""
        bo.append(row)
write("boost.csv", bo)

# ---- contention
co = []
for N in (2, 4):
    for rule in ("equal", "one_at_a_time"):
        xs = [r for r in cont if r["N"] == N and r["rule"] == rule and all(v is not None for v in r["ready_ms"])]
        if not xs:
            continue
        mean_r = [st.mean(r["ready_ms"]) for r in xs]
        max_r = [max(r["ready_ms"]) for r in xs]
        first = [min(r["ready_ms"]) for r in xs]
        co.append(dict(N=N, rule=rule, n=len(xs), mean_ready_ms=round(med(mean_r), 1),
                       mean_ci=f"{ci(mean_r)[0]:.1f}-{ci(mean_r)[1]:.1f}", max_ready_ms=round(med(max_r), 1),
                       first_ready_ms=round(med(first), 1),
                       cpu_s_sum=round(med([sum(r["cpu_s"]) for r in xs]), 2)))
write("contention.csv", co)
