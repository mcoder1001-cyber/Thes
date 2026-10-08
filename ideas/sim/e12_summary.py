#!/usr/bin/env python3
"""e12 summary over seeds 1-5: results/e12_cost_cores*.csv -> printed table + paired ratios
against look-ahead with an equal split (la+uniform), per seed."""
import csv, statistics as st, os
R = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
rows = []
def load(f, seed):
    for r in csv.DictReader(open(os.path.join(R, f))):
        r["seed"] = seed
        rows.append(r)
load("e12_cost_cores.csv", 1); load("e12_cost_cores_planov.csv", 1)
for s in (2, 3, 4, 5):
    load(f"e12_cost_cores_seed{s}.csv", s)
pols = ["la+uniform", "la+plan", "la+planov"]
print("cores policy n | all-calls p99 s mean[min,max] | cold-wf mean s | cold-wf p99 s")
for K in ("16", "20", "24", "32"):
    for p in pols:
        xs = [r for r in rows if r["cores"] == K and r["policy"] == p]
        f = lambda k: [float(r[k]) / 1000 for r in xs]
        g = lambda v: f"{st.mean(v):5.2f}[{min(v):.2f},{max(v):.2f}]"
        print(K, f"{p:11s}", len(xs), "|", g(f("p99_ms")), "|", g(f("after_idle_mean_ms")), "|", g(f("after_idle_p99_ms")))
print("\npaired change vs la+uniform, mean [min, max] over seeds")
for K in ("16", "20", "24", "32"):
    for p in ("la+plan", "la+planov"):
        d = {k: [] for k in ("after_idle_mean_ms", "after_idle_p99_ms", "p99_ms")}
        for s in range(1, 6):
            a = [r for r in rows if r["cores"] == K and r["policy"] == p and r["seed"] == s]
            b = [r for r in rows if r["cores"] == K and r["policy"] == "la+uniform" and r["seed"] == s]
            if a and b:
                for k in d:
                    d[k].append(float(a[0][k]) / float(b[0][k]) - 1)
        print(K, f"{p:10s}", " ".join(f"{k}: {100*st.mean(v):+.0f}% [{100*min(v):+.0f},{100*max(v):+.0f}]" for k, v in d.items()))
