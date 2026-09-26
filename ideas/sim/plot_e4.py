#!/usr/bin/env python3
"""Figure for e4/e4b: per memory budget, latency of invocations that arrive after >10 min
idle (the population snapshots are for), overall p99, and the CPU-cost proxy
(sandbox starts per 1000 invocations)."""
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
R = os.path.join(HERE, "results")
rows = []
for f in ("e4_trace.csv", "e4b_trace_gated.csv"):
    p = os.path.join(R, f)
    if os.path.exists(p):
        rows += list(csv.DictReader(open(p)))
ORDER = ["cold", "keepalive", "keepalive-60min", "prewarm", "snap", "snap@ttl0",
         "ahead", "ahead+rw", "ahead+rw/gated", "ahead+rw@ttl0"]
COL = {"cold": "#9a9a9a", "keepalive": "#6b6b6b", "keepalive-60min": "#444444", "prewarm": "#8a6fb3",
       "snap": "#d1603d", "snap@ttl0": "#e8a48f", "ahead": "#2f7fbf", "ahead+rw": "#1f9e89",
       "ahead+rw/gated": "#0b5d4f", "ahead+rw@ttl0": "#8fd1c4"}
budgets = sorted({int(r["budget_GB"]) for r in rows})
fig, axs = plt.subplots(3, len(budgets), figsize=(4.2 * len(budgets), 9), sharey="row", squeeze=False)
for j, M in enumerate(budgets):
    sub = {r["policy"]: r for r in rows if int(r["budget_GB"]) == M}
    pols = [p for p in ORDER if p in sub]
    for i, (key, lab, scale) in enumerate((("after_idle_mean_ms", "mean latency after >10 min idle, s", 1e-3),
                                           ("p99_ms", "p99 latency, all invocations, s", 1e-3),
                                           (None, "sandbox starts per 1000 invocations", 1))):
        ax = axs[i][j]
        if key:
            vals = [float(sub[p][key]) * scale for p in pols]
        else:
            vals = [1000 * (int(sub[p]["cold_boots"]) + int(sub[p]["restores"])) / int(sub[p]["n"]) for p in pols]
        ax.barh(range(len(pols)), vals, color=[COL[p] for p in pols])
        ax.set_yticks(range(len(pols)))
        ax.set_yticklabels(pols, fontsize=8)
        ax.invert_yaxis()
        ax.set_xscale("log")
        ax.grid(axis="x", alpha=.3)
        for k, v in enumerate(vals):
            extra = f"  ({float(sub[pols[k]]['avg_mem_GB']):.1f} GB)" if i == 0 else ""
            ax.text(v, k, f" {v:.2f}{extra}" if v < 10 else f" {v:.0f}{extra}", va="center", fontsize=7)
        if i == 0:
            ax.set_title(f"memory budget {M} GB", fontsize=10)
        if j == 0:
            ax.set_ylabel("")
        ax.set_xlabel(lab, fontsize=8)
fig.suptitle("Azure 2021 trace, 3 days, 68 workflows: (GB) = average resident memory", fontsize=10)
fig.tight_layout()
fig.savefig(os.path.join(R, "e4_trace_bars.png"), dpi=150)
print("wrote e4_trace_bars.png")
