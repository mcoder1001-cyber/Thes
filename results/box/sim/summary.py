#!/usr/bin/env python3
"""Summary of the e12 cost sweeps in this folder: per profile tag, policy and node size, the mean
over seeds (min-max) of cold-workflow mean / p99 and all-calls p99, and the change of la+plan vs
la+uniform paired by seed.  usage: python3 summary.py <file prefix, e.g. e12_measured_cap2>"""
import csv, glob, os, re, statistics as st, sys
H = os.path.dirname(os.path.abspath(__file__))
pre = sys.argv[1] if len(sys.argv) > 1 else "e12_measured_cap2"
rows = []
for f in sorted(glob.glob(os.path.join(H, f"{pre}_seed*.csv"))):
    sd = int(re.search(r"seed(\d+)", f).group(1))
    for r in csv.DictReader(open(f)):
        r["seed"] = sd
        rows.append(r)
seeds = sorted({r["seed"] for r in rows})
print(f"{pre}: seeds {seeds}")
print("cores policy      | cold-wf mean ms  | cold-wf p99 ms   | all p99 ms")
for K in sorted({int(r["cores"]) for r in rows}):
    for p in ("od+uniform", "la+uniform", "la+plan"):
        xs = [r for r in rows if int(r["cores"]) == K and r["policy"] == p]
        if not xs:
            continue
        f = lambda k: [float(r[k]) for r in xs]
        g = lambda v: f"{st.mean(v):6.0f} [{min(v):.0f},{max(v):.0f}]"
        print(f"{K:5d} {p:11s} | {g(f('after_idle_mean_ms'))} | {g(f('after_idle_p99_ms'))} | {g(f('p99_ms'))}")
print("\nla+plan vs la+uniform, paired by seed: mean [min, max]")
for K in sorted({int(r["cores"]) for r in rows}):
    d = {k: [] for k in ("after_idle_mean_ms", "after_idle_p99_ms", "p99_ms")}
    for s in seeds:
        a = [r for r in rows if int(r["cores"]) == K and r["policy"] == "la+plan" and r["seed"] == s]
        b = [r for r in rows if int(r["cores"]) == K and r["policy"] == "la+uniform" and r["seed"] == s]
        if a and b:
            for k in d:
                d[k].append(float(a[0][k]) / float(b[0][k]) - 1)
    print(f"{K:5d}  " + "  ".join(f"{k}: {100*st.mean(v):+.0f}% [{100*min(v):+.0f},{100*max(v):+.0f}]" for k, v in d.items() if v))
