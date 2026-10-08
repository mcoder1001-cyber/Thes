#!/usr/bin/env python3
"""D1 summary: raw/runs.jsonl -> summary.csv, ratios.csv, and the decision (prediction.md).

Per (vcpu, mode): n, failures, TTFR median / p95 with a 95% bootstrap CI of the median
(10,000 resamples), the first request's latency, steady latency C (median of requests
150-200), residual warm-up R = sum over the 200 later requests of max(0, latency - C*),
where C* is the fastest mode's C at that vCPU (one floor for all modes), CPU-seconds per
start, throttled periods. ratios.csv: TTFR ratios with bootstrap CIs (independent resamples
of the two modes)."""
import csv
import json
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "raw", "runs.jsonl")
B = 10_000
rnd = random.Random(1)


def med(xs):
    return statistics.median(xs)


def p95(xs):
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))]


def ci_median(xs):
    bs = sorted(med(rnd.choices(xs, k=len(xs))) for _ in range(B))
    return bs[int(0.025 * B)], bs[int(0.975 * B)]


def ci_ratio(a, b):
    bs = sorted(med(rnd.choices(a, k=len(a))) / med(rnd.choices(b, k=len(b))) for _ in range(B))
    return bs[int(0.025 * B)], bs[int(0.975 * B)]


rows = [json.loads(l) for l in open(RAW)]
bad_cg = [r for r in rows if r["cgroup"] not in (None, "0::/d1run")]
cells = {}
for r in rows:
    cells.setdefault((r["vcpu"], r["mode"]), []).append(r)

floor = {}
for (v, m), rs in cells.items():
    Cs = [med(r["curve_ms"][150:200]) for r in rs if len(r["curve_ms"]) >= 200]
    if Cs:
        floor[v] = min(floor.get(v, 1e9), med(Cs))

out, ttfr = [], {}
for (v, m), rs in sorted(cells.items()):
    ok = [r for r in rs if r["ttfr_ms"] is not None]
    t = [r["ttfr_ms"] for r in ok]
    ttfr[(v, m)] = t
    C = med([med(r["curve_ms"][150:200]) for r in ok]) if ok else float("nan")
    R = [sum(max(0.0, x - floor[v]) for x in r["curve_ms"]) for r in ok]
    lo, hi = ci_median(t) if t else (float("nan"),) * 2
    out.append(dict(vcpu=v, mode=m, n=len(ok), failed=len(rs) - len(ok),
                    ttfr_median_ms=round(med(t), 1), ttfr_ci_lo=round(lo, 1), ttfr_ci_hi=round(hi, 1),
                    ttfr_p95_ms=round(p95(t), 1),
                    first_req_median_ms=round(med([r["first_req_ms"] for r in ok]), 1),
                    C_median_ms=round(C, 3), floor_C_ms=round(floor[v], 3),
                    R_median_ms=round(med(R), 1), R_ci_lo=round(ci_median(R)[0], 1), R_ci_hi=round(ci_median(R)[1], 1),
                    cpu_s_median=round(med([r["cpu_s"] for r in ok]), 2),
                    throttled_median=med([r["nr_throttled"] for r in ok])))
with open(os.path.join(HERE, "summary.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(out[0]))
    w.writeheader()
    w.writerows(out)

pairs = [("aot_K50", "crac_K50"), ("aot_K0", "crac_K0"), ("aot_K0", "cold25"), ("aot_K50", "cold25"),
         ("cold21", "cold25"), ("crac_K0", "crac_K50"), ("cold21", "crac_K50"), ("c1_21", "crac_K50"),
         ("c1_21", "aot_K50")]
rat = []
for v in sorted({k[0] for k in ttfr}):
    for a, b in pairs:
        if (v, a) in ttfr and (v, b) in ttfr and ttfr[(v, a)] and ttfr[(v, b)]:
            lo, hi = ci_ratio(ttfr[(v, a)], ttfr[(v, b)])
            rat.append(dict(vcpu=v, num=a, den=b, ratio=round(med(ttfr[(v, a)]) / med(ttfr[(v, b)]), 2),
                            ci_lo=round(lo, 2), ci_hi=round(hi, 2)))
with open(os.path.join(HERE, "ratios.csv"), "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(rat[0]))
    w.writeheader()
    w.writerows(rat)

for o in out:
    print(o)
print()
for r in rat:
    print(r)
print("\ncontrol: runs outside /d1run:", len(bad_cg))
for v in sorted({k[0] for k in ttfr}):
    r = next((x for x in rat if x["vcpu"] == v and x["num"] == "aot_K50" and x["den"] == "crac_K50"), None)
    if r:
        verdict = ">= 3x: CRaC justified" if r["ci_lo"] >= 3 else ("< 1.5x: AOT enough" if r["ci_hi"] < 1.5
                                                                   else "between: both are start modes")
        print(f"decision at {v} vCPU: aot_K50/crac_K50 = {r['ratio']} [{r['ci_lo']}, {r['ci_hi']}] -> {verdict}")
