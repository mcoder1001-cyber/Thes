#!/usr/bin/env python3
"""Experiments on dagsim. Every experiment writes a CSV to results/ and a figure.

  e0  controls: closed-form latencies of deterministic chains and a fan-out DAG (known in advance)
  e1  cascade collapse: isolated workflow invocation, depth 1..8, per policy
  e2  branch speculation: latency vs memory as the speculation threshold varies
  e3  context-keyed snapshots on the router DAG (R_mis from exp-a)
  e4  trace-driven: Azure 2021 arrivals, 68 workflows, 3 days, several memory budgets
  e4b the gated restore-ahead variant on the same trace (figure: plot_e4.py)
  e5  sensitivity: restore time r and restore contention beta

usage: run_sim.py [e0 e1 ...]   (default: all)
"""
import csv
import gzip
import math
import os
import statistics
import sys
import time
from dataclasses import replace

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dagsim import (JAVA, PY, PYML, POLICIES, EDGE_MS, Profile, Sim, chain, fanout, ml_pipeline,
                    pct, router, trip_booking, ttl0)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "results")
os.makedirs(OUT, exist_ok=True)

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:          # figures are optional; CSVs are the record
    plt = None

COL = {"cold": "#9a9a9a", "keepalive": "#6b6b6b", "snap": "#d1603d", "prewarm": "#8a6fb3",
       "ahead": "#2f7fbf", "ahead+rw": "#1f9e89", "ahead+rw+ctx": "#0b5d4f"}


def write_csv(name, rows, header):
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def isolated(dag, policy, seeds=300, **kw):
    """One invocation into an empty platform (every stage misses keep-alive)."""
    lats, mems = [], []
    for k in range(seeds):
        sim = Sim(ttl0(policy), seed=k, **kw)
        sim.invoke(0.0, dag, "w")
        sim.run()
        lats.append(sim.results[0][3])
        mems.append(sim.memtime / 1e6)          # MB*ms -> GB*s
    return lats, mems


# ------------------------------------------------------------------ e0
def e0():
    print("e0: closed-form controls (deterministic chain)")
    J = JAVA
    ok = True
    rows = []
    for d in range(1, 9):
        want = {"cold": d * (J.A + J.B + J.C) + (d - 1) * EDGE_MS,
                "snap": d * (J.r + J.RK + J.C) + (d - 1) * EDGE_MS,
                "ahead": J.r + d * (J.RK + J.C) + (d - 1) * EDGE_MS}
        for pn, w in want.items():
            sim = Sim(ttl0(POLICIES[pn]), jitter=False)
            sim.invoke(0.0, chain(d), "w")
            sim.run()
            got = sim.results[0][3]
            ok &= abs(got - w) < 1e-6
            rows.append((d, pn, w, got))
    # general AND-DAG (fan-out/fan-in): restore-ahead latency is a longest path with
    # release times,  L_ah = max_v [ r_v + l(v) ],  l(v) = R_v + C_v + max_succ (delta + l(s)),
    # while restore-on-demand is the longest path with node weights r + R + C
    dag = fanout(4, "f")

    def longest(v, w):
        node = dag.nodes[v]
        return w(node.prof) + max([EDGE_MS + longest(s, w) for s in node.succ], default=0.0)
    want = {"snap": longest(dag.entry, lambda p: p.r + p.RK + p.C),
            "ahead": max(dag.nodes[v].prof.r + longest(v, lambda p: p.RK + p.C) for v in dag.nodes)}
    for pn, w in want.items():
        sim = Sim(ttl0(POLICIES[pn]), jitter=False)
        sim.invoke(0.0, dag, "w")
        sim.run()
        got = sim.results[0][3]
        ok &= abs(got - w) < 1e-6
        rows.append(("fanout4", pn, w, got))
    write_csv("e0_controls.csv", rows, ["depth", "policy", "closed_form_ms", "simulated_ms"])
    print(f"   {'PASS' if ok else 'FAIL'}: {len(rows)} closed-form checks (chains d=1..8 + fan-out/fan-in)")
    return ok


# ------------------------------------------------------------------ e1
def e1():
    print("e1: cascade collapse (isolated invocation, java chain)")
    pols = ["cold", "snap", "prewarm", "ahead", "ahead+rw"]
    rows = []
    for d in range(1, 9):
        for pn in pols:
            lats, mems = isolated(chain(d), POLICIES[pn], seeds=200)
            rows.append((d, pn, statistics.mean(lats), pct(lats, .5), pct(lats, .99), statistics.mean(mems)))
    write_csv("e1_cascade.csv", rows, ["depth", "policy", "mean_ms", "p50_ms", "p99_ms", "mem_GBs"])
    for d in (3, 5, 8):
        r = {p: m for dd, p, m, *_ in rows if dd == d}
        print(f"   d={d}: cold {r['cold']:.0f}  snap {r['snap']:.0f}  prewarm {r['prewarm']:.0f}  "
              f"ahead {r['ahead']:.0f}  ahead+rw {r['ahead+rw']:.0f}  ms   "
              f"(snap/ahead = {r['snap']/r['ahead']:.2f}x)")
    if plt:
        fig, ax = plt.subplots(1, 2, figsize=(10, 3.8))
        for pn in pols:
            xs = [d for d, p, *_ in rows if p == pn]
            ys = [m / 1000 for d, p, m, *_ in rows if p == pn]
            ax[0].plot(xs, ys, "o-", color=COL[pn], label=pn)
            ms = [mem for d, p, _, _, _, mem in rows if p == pn]
            ax[1].plot(xs, ms, "o-", color=COL[pn], label=pn)
        ax[0].set_xlabel("workflow depth (stages)")
        ax[0].set_ylabel("end-to-end latency, s (mean)")
        ax[0].set_yscale("log")
        ax[0].set_title("Java chain, every stage misses keep-alive")
        ax[1].set_xlabel("workflow depth (stages)")
        ax[1].set_ylabel("memory-time per invocation, GB·s")
        ax[1].set_title("cost of the invocation itself (no keep-alive)")
        ax[0].legend(frameon=False, fontsize=8)
        for a in ax:
            a.grid(alpha=.3)
        fig.tight_layout()
        fig.savefig(os.path.join(OUT, "e1_cascade.png"), dpi=150)
    return rows


# ------------------------------------------------------------------ e2
def e2():
    print("e2: branch speculation (trip-booking saga + router), restore vs cold prewarm")
    rows = []
    for dag in (trip_booking(), router()):
        for kind, base in (("restore", POLICIES["ahead"]), ("cold", POLICIES["prewarm"])):
            for th in (1.01, 0.5, 0.2, 0.08, 0.01):
                pol = replace(base, theta=th, name=f"{kind}-th{th}")
                lats, mems = isolated(dag, pol, seeds=400)
                rows.append((dag.name, kind, th, statistics.mean(lats), pct(lats, .5), pct(lats, .99),
                             statistics.mean(mems)))
    write_csv("e2_speculation.csv", rows, ["dag", "ahead_kind", "theta", "mean_ms", "p50_ms", "p99_ms", "mem_GBs"])
    for r in rows:
        print(f"   {r[0]:7s} {r[1]:8s} theta={r[2]:<5} mean {r[3]:7.0f}  p99 {r[5]:7.0f} ms  mem {r[6]:6.2f} GB·s")
    if plt:
        fig, axs = plt.subplots(1, 2, figsize=(10, 3.8))
        for ax, dn in zip(axs, ("trip", "router")):
            for kind, c in (("restore", COL["ahead"]), ("cold", COL["prewarm"])):
                pts = [(r[6], r[5] / 1000, r[2]) for r in rows if r[0] == dn and r[1] == kind]
                ax.plot([p[0] for p in pts], [p[1] for p in pts], "o-", color=c, label=f"{kind} ahead")
                labels = {}
                for x, y, th in pts:        # identical outcomes share one label
                    labels.setdefault((round(x, 3), round(y, 3)), []).append("none" if th > 1 else str(th))
                for (x, y), ths in labels.items():
                    txt = ths[0] if ths == ["none"] else "θ=" + ", ".join(t for t in ths if t != "none")
                    ax.annotate(txt, (x, y), fontsize=7, xytext=(3, 3), textcoords="offset points")
            ax.set_xlabel("memory-time per invocation, GB·s")
            ax.set_ylabel("p99 end-to-end latency, s")
            ax.set_title(f"{dn}: lowering θ = speculating on rarer branches")
            ax.grid(alpha=.3)
            ax.legend(frameon=False, fontsize=8)
        fig.tight_layout()
        fig.savefig(os.path.join(OUT, "e2_speculation.png"), dpi=150)
    return rows


# ------------------------------------------------------------------ e3
def e3(R_mis_ratio=None):
    """Context-keyed variants. R_mis/RK ratio comes from exp-a (see IDEAS.md)."""
    ratios = [R_mis_ratio] if R_mis_ratio else [1.0, 2.0, 4.0, 8.0]
    print(f"e3: context-keyed snapshots on router.enrich, R_mis/RK in {ratios}")
    rows = []
    for ratio in ratios:
        enrich = replace(JAVA, name="java-enrich", R_mis=JAVA.RK * ratio)
        dag = router(enrich=enrich)
        for pn in ("ahead+rw", "ahead+rw+ctx"):
            lats, mems = isolated(dag, POLICIES[pn], seeds=600)
            rows.append((ratio, pn, statistics.mean(lats), pct(lats, .5), pct(lats, .9), pct(lats, .99),
                         statistics.mean(mems)))
    write_csv("e3_context.csv", rows, ["Rmis_over_RK", "policy", "mean_ms", "p50_ms", "p90_ms", "p99_ms", "mem_GBs"])
    for r in rows:
        print(f"   ratio {r[0]:>4}: {r[1]:13s} mean {r[2]:6.0f}  p90 {r[4]:6.0f}  p99 {r[5]:6.0f} ms  mem {r[6]:5.2f} GB·s")
    return rows


# ------------------------------------------------------------------ e4
TEMPLATES = [
    ("chain3", lambda t: chain(3, JAVA, t)),
    ("chain5", lambda t: chain(5, JAVA, t)),
    ("trip", lambda t: trip_booking(t)),
    ("fanout", lambda t: fanout(4, t)),
    ("router", lambda t: router(t)),
    ("ml", lambda t: ml_pipeline(t)),
    ("chain8", lambda t: chain(8, JAVA, t)),
    ("chain3py", lambda t: chain(3, PY, t)),
]


def load_arrivals(days=3):
    path = os.path.join(HERE, "data", f"azure2021_entry_arrivals_{days}d.csv.gz")
    arr = []
    with gzip.open(path, "rt") as f:
        next(f)
        for line in f:
            t, a = line.split(",")
            arr.append((float(t) * 1000.0, int(a)))
    return arr


def e4b():
    """Follow-up to e4: the gated restore-ahead variant (added after e4's restore counts)."""
    return e4(policies=["ahead+rw/gated"], out="e4b_trace_gated.csv")


def e4(days=3, budgets_gb=(32, 128, 1024), policies=None, out="e4_trace.csv"):
    print(f"e4: trace-driven, Azure 2021 first {days} days")
    arr = load_arrivals(days)
    apps = sorted({a for _, a in arr})
    dags = {a: TEMPLATES[a % len(TEMPLATES)][1](f"app{a}") for a in apps}
    # label each invocation by the gap since the same workflow's previous invocation
    last, gap = {}, []
    for t, a in arr:
        gap.append(t - last[a] if a in last else math.inf)
        last[a] = t
    if policies:
        pols = [POLICIES[p] for p in policies]
    else:
        pols = [POLICIES[p] for p in ("cold", "keepalive", "snap", "prewarm", "ahead", "ahead+rw")]
        pols += [ttl0(POLICIES["snap"]), ttl0(POLICIES["ahead+rw"]),
                 replace(POLICIES["keepalive"], ttl=3_600_000.0, name="keepalive-60min")]
    rows = []
    for M in budgets_gb:
        for pol in pols:
            if M != budgets_gb[-1] and pol.name in ("cold",):
                continue
            t0 = time.time()
            sim = Sim(pol, mem_budget_mb=M * 1024, seed=1)
            for t, a in arr:
                sim.invoke(t, dags[a], a)
            sim.run()
            res = sorted(sim.results, key=lambda r: r[2])
            # results complete out of order; match back to arrival order by (wid, t0)
            key = {(w, t): lat for w, _, t, lat in res}
            lats = [key[(a, t)] for t, a in arr if (a, t) in key]
            gaps = [g for (t, a), g in zip(arr, gap) if (a, t) in key]
            miss = [l for l, g in zip(lats, gaps) if g > 600_000]      # >10 min since last run
            hot = [l for l, g in zip(lats, gaps) if g <= 600_000]
            hours = days * 24
            row = (M, pol.name, len(lats), statistics.mean(lats), pct(lats, .5), pct(lats, .99), pct(lats, .999),
                   len(miss), statistics.mean(miss) if miss else float("nan"), pct(miss, .5), pct(miss, .99),
                   statistics.mean(hot) if hot else float("nan"),
                   sim.memtime / 1e6 / 3600 / hours, sim.idle_memtime / 1e6 / 3600 / hours,
                   sim.stats["cold_boots"], sim.stats["restores"], sim.stats["ahead_started"],
                   sim.stats["ahead_unused"], sim.stats["overflow"], sim.stats["evictions"])
            rows.append(row)
            print(f"   M={M:>5}GB {pol.name:18s} n={row[2]} mean {row[3]:7.0f} p99 {row[5]:7.0f} | "
                  f"after-idle n={row[7]} mean {row[8]:7.0f} p99 {row[10]:7.0f} | "
                  f"mem {row[12]:6.1f} GB avg (idle {row[13]:6.1f}) | restores {row[15]} cold {row[14]} "
                  f"({time.time()-t0:.0f}s)", flush=True)
    write_csv(out, rows,
              ["budget_GB", "policy", "n", "mean_ms", "p50_ms", "p99_ms", "p999_ms",
               "n_after_idle", "after_idle_mean_ms", "after_idle_p50_ms", "after_idle_p99_ms", "hot_mean_ms",
               "avg_mem_GB", "avg_idle_mem_GB", "cold_boots", "restores", "ahead_started",
               "ahead_unused", "overflow", "evictions"])
    # figure: plot_e4.py (per-budget bars; reads e4_trace.csv and e4b_trace_gated.csv)
    return rows


# ------------------------------------------------------------------ e5
def e5():
    print("e5: sensitivity to restore time r and restore contention beta (chain5, java)")
    rows = []
    for r in (100, 250, 650, 2000, 6000):
        for beta in (0.0, 0.25, 1.0):
            prof = replace(JAVA, r=float(r))
            dag = chain(5, prof, "s")
            res = {}
            for pn in ("snap", "ahead", "ahead+rw"):
                lats, _ = isolated(dag, POLICIES[pn], seeds=150, restore_beta=beta)
                res[pn] = statistics.mean(lats)
            rows.append((r, beta, res["snap"], res["ahead"], res["ahead+rw"], res["snap"] / res["ahead+rw"]))
    write_csv("e5_sensitivity.csv", rows, ["r_ms", "beta", "snap_ms", "ahead_ms", "ahead_rw_ms", "speedup"])
    for row in rows:
        print(f"   r={row[0]:>5} beta={row[1]:<4}  snap {row[2]:7.0f}  ahead {row[3]:7.0f}  "
              f"ahead+rw {row[4]:7.0f}  speedup {row[5]:.2f}x")
    return rows


if __name__ == "__main__":
    which = sys.argv[1:] or ["e0", "e1", "e2", "e3", "e5", "e4", "e4b"]
    for w in which:
        globals()[w]()
