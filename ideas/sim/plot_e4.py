#!/usr/bin/env python3
"""Figure for e4/e4b: per memory budget, latency of invocations that arrive after >10 min
idle (the population snapshots are for), overall p99, and the CPU-cost proxy
(sandbox starts per 1000 invocations)."""
import csv
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker

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
# one category list for every panel: the rows share a y axis, so each panel must place the
# same policy at the same position (an earlier version used per-panel lists and mislabelled bars)
present = {r["policy"] for r in rows}
pols = [p for p in ORDER if p in present]
fig, axs = plt.subplots(3, len(budgets), figsize=(4.4 * len(budgets), 9.5), sharey="row", squeeze=False)
for j, M in enumerate(budgets):
    sub = {r["policy"]: r for r in rows if int(r["budget_GB"]) == M}
    for i, (key, lab, scale) in enumerate((("after_idle_mean_ms", "mean latency after >10 min idle, s", 1e-3),
                                           ("p99_ms", "p99 latency, all invocations, s", 1e-3),
                                           (None, "sandbox starts per 1000 invocations", 1))):
        ax = axs[i][j]
        for k, p in enumerate(pols):
            if p not in sub:
                continue
            r = sub[p]
            v = (float(r[key]) * scale if key else
                 1000 * (int(r["cold_boots"]) + int(r["restores"])) / int(r["n"]))
            ax.barh(k, v, color=COL[p])
            extra = f"  ({float(r['avg_mem_GB']):.1f} GB)" if i == 0 else ""
            ax.text(v, k, (f" {v:.2f}" if v < 10 else f" {v:.0f}") + extra, va="center", fontsize=7)
        ax.set_yticks(range(len(pols)))
        ax.set_yticklabels(pols, fontsize=8)
        ax.set_ylim(len(pols) - 0.5, -0.5)
        ax.set_xscale("log")
        ax.xaxis.set_minor_formatter(matplotlib.ticker.NullFormatter())
        ax.grid(axis="x", alpha=.3)
        if i == 0:
            ax.set_title(f"memory budget {M} GB", fontsize=10)
        ax.set_xlabel(lab, fontsize=8)
fig.suptitle("Azure 2021 trace, first 3 days, 68 workflows, 432,945 invocations; "
             "(GB) = average resident memory; empty row = policy not run at that budget", fontsize=9)
fig.tight_layout()
fig.savefig(os.path.join(R, "e4_trace_bars.png"), dpi=150)
print("wrote e4_trace_bars.png")
