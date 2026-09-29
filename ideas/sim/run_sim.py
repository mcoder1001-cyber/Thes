#!/usr/bin/env python3
"""Experiments on dagsim. Every experiment writes a CSV to results/ and a figure.

  e0  controls: closed-form latencies of deterministic chains and a fan-out DAG (known in advance)
  e1  cascade collapse: isolated workflow invocation, depth 1..8, per policy
  e2  branch speculation: latency vs memory as the speculation threshold varies
  e3  context-keyed snapshots on the router DAG (R_mis from exp-a)
  e4  trace-driven: Azure 2021 arrivals, 68 workflows, 3 days, several memory budgets
  e4b the gated restore-ahead variant on the same trace (figure: plot_e4.py)
  e5  sensitivity: restore time r and restore contention beta
  e6  which stages are worth a snapshot, in latency and money (e6_cost.py; exact model)
  e7  memory overload: look-ahead's higher peak (Theorem 8) and the preemption guard --
      e7a a burst of cold workflows under a hard budget, e7b the Azure trace at tight budgets
  e8  keep-alive under look-ahead (theory/ALGORITHM.md Proposition 9): per-function LRU and
      GDSF eviction vs evicting whole workflows, on the Azure trace at tight budgets
  e9  the exact planner (theory/ALGORITHM.md, Algorithm 2) vs the guard alone: e9a single
      workflows under a budget, e9b a burst of mixed workflows, e9c the Azure trace
  e10 the headline numbers again, with the final policy ("recommended"): e10a isolated chains
      (as e1), e10b the Azure trace (as e4/e4b), against restore-on-demand with the same
      keep-alive
  e11 CPU during start-up (the vCPU cliff): functions at 0.25 vCPU on a node with a few cores;
      who gets the spare CPU while sandboxes start. e11a isolated workflows, e11b a burst, e11c
      the Azure trace, e11d which stages still need a snapshot, e11o the online rule vs the
      exact plan (cpuplan.py); la+plan+jit is the CPU plan just in time (Policy.lazy), whose
      controls are e11x

usage: run_sim.py [e0 e1 ...]   (default: all)
       DAGSIM_PROFILE=measured.json DAGSIM_OUT=out/ run_sim.py e10a   (measured parameters)
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
from dagsim import (JAVA, PY, PYML, POLICIES, EDGE_MS, Policy, Profile, Sim, chain, fanout, ml_pipeline,
                    mixed, pct, router, trip_booking, ttl0)

HERE = os.path.dirname(os.path.abspath(__file__))
# DAGSIM_OUT redirects the CSVs, e.g. for runs with measured parameters (DAGSIM_PROFILE in dagsim.py)
OUT = os.environ.get("DAGSIM_OUT") or os.path.join(HERE, "results")
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
def e7a(W=16, seeds=20, budgets_gb=(4, 8, 16, 32, 64)):
    """W cold 8-stage Java chains (distinct functions) arrive within one second into an empty
    platform with a hard memory budget. On demand holds ~W x 512 MB at most; just-in-time
    look-ahead ~8x that per workflow (Theorem 8(a))."""
    print(f"e7a: burst of {W} cold 8-stage Java chains within 1 s, hard memory budget")
    dags = [chain(8, JAVA, tag=f"b{i}") for i in range(W)]
    pols = ["snap", "ahead+rw/gated/jit", "ahead+rw/gated/jit/guard"]
    rows = []
    for M in budgets_gb:
        for pn in pols:
            lats, over, ovmt, pre, peak = [], 0, 0.0, 0, 0.0
            for seed in range(seeds):
                sim = Sim(POLICIES[pn], mem_budget_mb=M * 1024, seed=seed)
                for i, d in enumerate(dags):
                    sim.invoke(i * 1000.0 / W, d, f"b{i}")
                sim.run()
                lats += [r[3] for r in sim.results]
                over += sim.stats["overflow"]
                ovmt += sim.over_memtime / 1024 / 1000
                pre += sim.stats["preempted"]
                peak = max(peak, sim.peak_mem / 1024)
            row = (M, pn, len(lats), statistics.mean(lats), pct(lats, .99), over / seeds, ovmt / seeds,
                   pre / seeds, peak)
            rows.append(row)
            print(f"   M={M:>3}GB {pn:26s} mean {row[3]:6.0f} p99 {row[4]:6.0f} ms | overflow {row[5]:5.1f}/run "
                  f"({row[6]:6.1f} GB-s above budget) | preempted {row[7]:5.1f} | peak {row[8]:5.1f} GB", flush=True)
    write_csv("e7a_burst.csv", rows, ["budget_GB", "policy", "n", "mean_ms", "p99_ms", "overflow_per_run",
                                      "over_budget_GBs_per_run", "preempted_per_run", "peak_GB"])
    return rows


def _policy(pn):
    """'<base>' or '<base>|opt,opt,...' with opts guard (preemption), noevict, h=<headroom>,
    keep=<lru|gdsf|wf>, gateall."""
    if pn in POLICIES:
        return POLICIES[pn]
    base, spec = pn.split("|")
    kw = dict(name=pn)
    for part in spec.split(","):
        if part == "guard":
            kw["preempt"] = True
        elif part == "noevict":
            kw["ahead_evicts"] = False
        elif part.startswith("h="):
            kw["headroom"] = float(part[2:])
        elif part.startswith("keep="):
            kw["keep"] = part[5:]
        elif part == "gateall":
            kw["gate_all"] = True
        elif part == "plan":
            kw["plan"] = True
        elif part == "queue":               # the planner's wait queue with just-in-time triggers
            kw["plan"], kw["plan_exact"] = True, False
        else:
            raise ValueError(part)
    return replace(POLICIES[base], **kw)


def _trace_row(args):
    M, pn, days = args
    pol = _policy(pn)
    arr = load_arrivals(days)
    apps = sorted({a for _, a in arr})
    dags = {a: TEMPLATES[a % len(TEMPLATES)][1](f"app{a}") for a in apps}
    last, gap = {}, []
    for t, a in arr:
        gap.append(t - last[a] if a in last else math.inf)
        last[a] = t
    t0 = time.time()
    sim = Sim(pol, mem_budget_mb=M * 1024, seed=1)
    for t, a in arr:
        sim.invoke(t, dags[a], a)
    sim.run()
    key = {(w, t): lat for w, _, t, lat in sim.results}
    lats = [key[(a, t)] for t, a in arr if (a, t) in key]
    gaps = [g for (t, a), g in zip(arr, gap) if (a, t) in key]
    miss = [l for l, g in zip(lats, gaps) if g > 600_000]
    return (M, pn, len(lats), statistics.mean(lats), pct(lats, .99), pct(lats, .999),
            statistics.mean(miss), pct(miss, .99), sim.stats["overflow"], sim.over_memtime / 1024 / 1000,
            sim.peak_mem / 1024, sim.stats["preempted"], sim.stats["evictions"], sim.stats["restores"],
            time.time() - t0)


def e7b(days=3, budgets_gb=(16, 24, 32)):
    """The Azure trace (as e4) at budgets below its working set (~50 GB): does look-ahead
    overload memory, and does the guard stop it? '|guard' = the same policy with preemption."""
    from multiprocessing import Pool
    print(f"e7b: Azure 2021 trace, first {days} days, tight memory budgets")
    pols = ["snap", "ahead+rw", "ahead+rw|guard", "ahead+rw/gated/jit", "ahead+rw/gated/jit/guard",
            "ahead+rw/gated/jit|guard,noevict"]
    jobs = [(M, pn, days) for M in budgets_gb for pn in pols]
    with Pool(3) as pool:
        rows = pool.map(_trace_row, jobs)
    for r in rows:
        print(f"   M={r[0]:>3}GB {r[1]:26s} mean {r[3]:6.0f} p99 {r[4]:6.0f} | after-idle mean {r[6]:6.0f} "
              f"p99 {r[7]:6.0f} | overflow {r[8]:5d} ({r[9]:8.1f} GB-s over) | peak {r[10]:5.1f} GB | "
              f"preempted {r[11]:5d} | evictions {r[12]:6d} | restores {r[13]:6d} ({r[14]:.0f}s)", flush=True)
    write_csv("e7b_trace_budget.csv", [r[:-1] for r in rows],
              ["budget_GB", "policy", "n", "mean_ms", "p99_ms", "p999_ms", "after_idle_mean_ms",
               "after_idle_p99_ms", "overflow", "over_budget_GBs", "peak_GB", "preempted", "evictions", "restores"])
    return rows


def _e8_row(args):
    M, pn, days = args[:3]
    seed = args[3] if len(args) > 3 else 1
    pol = _policy(pn)
    arr = load_arrivals(days)
    apps = sorted({a for _, a in arr})
    dags = {a: TEMPLATES[a % len(TEMPLATES)][1](f"app{a}") for a in apps}
    last, gap = {}, []
    for t, a in arr:
        gap.append(t - last[a] if a in last else math.inf)
        last[a] = t
    t0 = time.time()
    sim = Sim(pol, mem_budget_mb=M * 1024, seed=seed)
    for t, a in arr:
        sim.invoke(t, dags[a], a)
    sim.run()
    key = {(w, t): lat for w, _, t, lat in sim.results}
    lats = [key[(a, t)] for t, a in arr if (a, t) in key]
    gaps = [g for (t, a), g in zip(arr, gap) if (a, t) in key]
    miss = [l for l, g in zip(lats, gaps) if g > 600_000]
    hot = [l for l, g in zip(lats, gaps) if g <= 600_000]
    return (M, pn, len(lats), statistics.mean(lats), pct(lats, .5), pct(lats, .99),
            len(miss), statistics.mean(miss), pct(miss, .99), statistics.mean(hot), pct(hot, .99),
            sim.stats["partial_warm"], sim.stats["evictions"], sim.stats["restores"],
            sim.stats["overflow"], sim.over_memtime / 1024 / 1000, sim.stats["plans"],
            sim.stats["plan_timeouts"], time.time() - t0)


def e8(days=3, budgets_gb=(16, 24, 32, 48), pols=None):
    """Keep-alive under look-ahead (Proposition 9). Same trace as e4/e7b, budgets below and near
    its working set (~50 GB), where eviction decides what stays warm. On-demand baselines with
    LRU and with GDSF (FaasCache-style); the recommended look-ahead policy with LRU, GDSF, and
    workflow-level eviction ('wf'), each also with the all-stages gate."""
    from multiprocessing import Pool
    print(f"e8: keep-alive under look-ahead, Azure 2021 trace, first {days} days")
    R = "ahead+rw/gated/jit/guard"
    pols = pols or ["snap", "snap|keep=gdsf", R, R + "|keep=gdsf", R + "|keep=wf", R + "|gateall",
            R + "|keep=wf,gateall", R + "|keep=wfp", R + "|keep=wfp,gateall"]
    jobs = [(M, pn, days) for M in budgets_gb for pn in pols]
    with Pool(int(os.environ.get("SIM_PROCS", "3"))) as pool:
        rows = pool.map(_e8_row, jobs)
    for r in rows:
        print(f"   M={r[0]:>3}GB {r[1]:40s} mean {r[3]:5.0f} p99 {r[5]:5.0f} | after-idle n={r[6]} mean {r[7]:5.0f} "
              f"p99 {r[8]:5.0f} | hot mean {r[9]:5.0f} p99 {r[10]:5.0f} | partial-warm {r[11]:5d} | "
              f"evictions {r[12]:6d} restores {r[13]:6d} overflow {r[14]:5d} ({r[-1]:.0f}s)", flush=True)
    write_csv("e8_keepalive.csv", [r[:-3] for r in rows],
              ["budget_GB", "policy", "n", "mean_ms", "p50_ms", "p99_ms", "n_after_idle",
               "after_idle_mean_ms", "after_idle_p99_ms", "hot_mean_ms", "hot_p99_ms", "partial_warm_arrivals",
               "evictions", "restores", "overflow", "over_budget_GBs"])
    return rows


E9_DAGS = [("mixed", mixed), ("trip", trip_booking), ("fanout4", lambda t: fanout(4, t)),
           ("ml", ml_pipeline), ("router", router), ("chain5", lambda t: chain(5, JAVA, t)),
           ("chain8", lambda t: chain(8, JAVA, t))]
E9_POLS = ["snap", "ahead+rw/gated/jit/guard", "ahead+rw/gated/jit/guard|queue",
           "ahead+rw/gated/jit/guard|plan"]


def e9a(seeds=50, factors=(1.0, 1.5, 2.0, 3.0, None)):
    """One cold workflow alone, with a memory budget of f x its largest stage (None: no budget),
    restore-time and run-time jitter on. The planner plans with the profiled means."""
    print("e9a: single cold workflows under a memory budget (planner vs guard)")
    rows = []
    for name, mk in E9_DAGS:
        dag = mk(name)
        mmax = max(nd.prof.m for nd in dag.nodes.values())
        for f in factors:
            M = mmax * f if f else 1e9
            for pn in E9_POLS:
                pol = _policy(pn)
                lats, over, pre, plans, tmo = [], 0, 0, 0, 0
                for k in range(seeds):
                    sim = Sim(ttl0(pol), mem_budget_mb=M, seed=k)
                    sim.invoke(0.0, dag, "w")
                    sim.run()
                    lats.append(sim.results[0][3])
                    over += sim.stats["overflow"]
                    pre += sim.stats["preempted"]
                    plans += sim.stats["plans"]
                    tmo += sim.stats["plan_timeouts"]
                rows.append((name, f if f else "inf", pn, statistics.mean(lats), pct(lats, .99), over / seeds,
                             pre / seeds, plans / seeds, tmo / seeds))
            best = {r[2]: r for r in rows[-len(E9_POLS):]}
            print(f"   {name:8s} budget {('%.1fx' % f) if f else ' inf':>5}: " + " | ".join(
                f"{pn.split('/')[-1] if '/' in pn else pn:11s} {r[3]:5.0f} (over {r[5]:.1f})"
                for pn, r in best.items()), flush=True)
    write_csv("e9a_planner_single.csv", rows, ["dag", "budget_x_max_m", "policy", "mean_ms", "p99_ms",
                                               "overflow_per_run", "preempted_per_run", "plans_per_run",
                                               "plan_timeouts_per_run"])
    return rows


def e9b(W=16, seeds=10, budgets_gb=(4, 6, 8, 12, 16, 32)):
    """W cold workflows of the E9 shapes arrive within one second into an empty platform with a
    hard budget (as e7a, but mixed shapes, where the order of restores matters)."""
    print(f"e9b: burst of {W} cold mixed workflows within 1 s, hard memory budget")
    rows = []
    for M in budgets_gb:
        for pn in E9_POLS:
            pol = _policy(pn)
            lats, over, pre, plans, tmo, ptime = [], 0, 0, 0, 0, 0.0
            for seed in range(seeds):
                sim = Sim(pol, mem_budget_mb=M * 1024, seed=seed)
                for i in range(W):
                    name, mk = E9_DAGS[i % len(E9_DAGS)]
                    sim.invoke(i * 1000.0 / W, mk(f"{name}{i}"), f"w{i}")
                sim.run()
                lats += [r[3] for r in sim.results]
                over += sim.stats["overflow"]
                pre += sim.stats["preempted"]
                plans += sim.stats["plans"]
                tmo += sim.stats["plan_timeouts"]
                ptime += sim.plan_time
            row = (M, pn, len(lats), statistics.mean(lats), pct(lats, .99), over / seeds, pre / seeds,
                   plans / seeds, tmo / seeds, ptime / max(1, plans) * 1000)
            rows.append(row)
            print(f"   M={M:>3}GB {pn:32s} mean {row[3]:6.0f} p99 {row[4]:6.0f} ms | overflow {row[5]:5.1f}/run | "
                  f"preempted {row[6]:5.1f} | plans {row[7]:4.1f} timeouts {row[8]:4.1f} | "
                  f"{row[9]:.1f} ms/plan", flush=True)
    write_csv("e9b_planner_burst.csv", rows, ["budget_GB", "policy", "n", "mean_ms", "p99_ms", "overflow_per_run",
                                              "preempted_per_run", "plans_per_run", "plan_timeouts_per_run",
                                              "ms_per_plan"])
    return rows


def e9c(days=3, budgets_gb=(16, 24, 32), seeds=(1, 2, 3)):
    """The Azure trace (as e8) with and without the planner, keep-alive GDSF (e8's best), three
    seeds (restore-time and run-time jitter): below the working set the platform thrashes and
    a single seed can swing (e9c found one collapse episode at 16 GB on seed 1)."""
    from multiprocessing import Pool
    print(f"e9c: planner on the Azure 2021 trace, first {days} days")
    R = "ahead+rw/gated/jit/guard"
    pols = [R + "|keep=gdsf", R + "|keep=gdsf,plan"]
    jobs = [(M, pn, days, sd) for M in budgets_gb for sd in seeds for pn in pols]
    with Pool(int(os.environ.get("SIM_PROCS", "3"))) as pool:
        rows = pool.map(_e8_row, jobs)
    rows = [(j[3],) + r for j, r in zip(jobs, rows)]
    for r in rows:
        print(f"   M={r[1]:>3}GB seed {r[0]} {r[2]:40s} mean {r[4]:5.0f} p99 {r[6]:5.0f} | after-idle mean "
              f"{r[8]:5.0f} p99 {r[9]:5.0f} | restores {r[14]:6d} overflow {r[15]:5d} | plans {r[17]} "
              f"timeouts {r[18]} ({r[-1]:.0f}s)", flush=True)
    write_csv("e9c_planner_trace.csv", [r[:-1] for r in rows],
              ["seed", "budget_GB", "policy", "n", "mean_ms", "p50_ms", "p99_ms", "n_after_idle",
               "after_idle_mean_ms", "after_idle_p99_ms", "hot_mean_ms", "hot_p99_ms", "partial_warm_arrivals",
               "evictions", "restores", "overflow", "over_budget_GBs", "plans", "plan_timeouts"])
    return rows


def e9():
    e9a()
    e9b()
    e9c()


def e10a(seeds=200):
    """Isolated cold Java chains (as e1): restore-on-demand vs the first headline policy
    (ahead+rw) vs the final policy. No memory budget, so the planner and keep-alive are idle."""
    print("e10a: isolated cold Java chains, final policy")
    pols = ["snap", "ahead+rw", "recommended"]
    rows = []
    for d in range(1, 9):
        res = {}
        for pn in pols:
            lats, mems = isolated(chain(d), POLICIES[pn], seeds=seeds)
            res[pn] = statistics.mean(lats)
            rows.append((d, pn, statistics.mean(lats), pct(lats, .5), pct(lats, .99), statistics.mean(mems)))
        print(f"   d={d}: on demand {res['snap']:6.0f}  ahead+rw {res['ahead+rw']:6.0f}  recommended "
              f"{res['recommended']:6.0f} ms  ({res['snap'] / res['recommended']:.2f}x)", flush=True)
    write_csv("e10a_chains_final.csv", rows, ["depth", "policy", "mean_ms", "p50_ms", "p99_ms", "mem_GBs"])
    return rows


def _e10_row(args):
    """One Azure-trace run with e4's columns plus overflow."""
    M, pn, days, seed = args
    pol = _policy(pn)
    arr = load_arrivals(days)
    apps = sorted({a for _, a in arr})
    dags = {a: TEMPLATES[a % len(TEMPLATES)][1](f"app{a}") for a in apps}
    last, gap = {}, []
    for t, a in arr:
        gap.append(t - last[a] if a in last else math.inf)
        last[a] = t
    t0 = time.time()
    sim = Sim(pol, mem_budget_mb=M * 1024, seed=seed)
    for t, a in arr:
        sim.invoke(t, dags[a], a)
    sim.run()
    key = {(w, t): lat for w, _, t, lat in sim.results}
    lats = [key[(a, t)] for t, a in arr if (a, t) in key]
    gaps = [g for (t, a), g in zip(arr, gap) if (a, t) in key]
    miss = [l for l, g in zip(lats, gaps) if g > 600_000]
    hot = [l for l, g in zip(lats, gaps) if g <= 600_000]
    hours = days * 24
    n = len(lats)
    return (M, pn, seed, n, statistics.mean(lats), pct(lats, .5), pct(lats, .99), pct(lats, .999),
            len(miss), statistics.mean(miss), pct(miss, .5), pct(miss, .99), statistics.mean(hot),
            sim.memtime / 1e6 / 3600 / hours, sim.idle_memtime / 1e6 / 3600 / hours,
            (sim.stats["cold_boots"] + sim.stats["restores"]) / n * 1000, sim.stats["overflow"],
            sim.stats["plans"], time.time() - t0)


def e10b(days=3, budgets_gb=(24, 32, 128), seeds=(1,)):
    """The Azure trace (as e4/e4b) with the final policy. Baselines: restore-on-demand with
    OpenWhisk-like LRU keep-alive (e4's baseline) and with the same GDSF keep-alive as the
    final policy (so the difference is look-ahead, not keep-alive); the first headline
    policy (ahead+rw/gated) for continuity."""
    from multiprocessing import Pool
    print(f"e10b: the Azure 2021 trace, first {days} days, final policy")
    pols = ["snap", "snap|keep=gdsf", "ahead+rw/gated", "recommended"]
    jobs = [(M, pn, days, sd) for M in budgets_gb for sd in seeds for pn in pols]
    with Pool(int(os.environ.get("SIM_PROCS", "3"))) as pool:
        rows = pool.map(_e10_row, jobs)
    for r in rows:
        print(f"   M={r[0]:>4}GB {r[1]:18s} mean {r[4]:5.0f} p99 {r[6]:5.0f} p99.9 {r[7]:5.0f} | cold workflows "
              f"(n={r[8]}) mean {r[9]:5.0f} p99 {r[11]:5.0f} | mem {r[13]:5.1f} GB (idle {r[14]:5.1f}) | "
              f"starts/1000 {r[15]:6.1f} | overflow {r[16]:5d} | plans {r[17]} ({r[-1]:.0f}s)", flush=True)
    write_csv("e10b_trace_final.csv", [r[:-1] for r in rows],
              ["budget_GB", "policy", "seed", "n", "mean_ms", "p50_ms", "p99_ms", "p999_ms", "n_after_idle",
               "after_idle_mean_ms", "after_idle_p50_ms", "after_idle_p99_ms", "hot_mean_ms", "avg_mem_GB",
               "avg_idle_mem_GB", "starts_per_1000", "overflow", "plans"])
    return rows


def e10():
    e10a()
    e10b()


# ------------------------------------------------------------------ e11
# Start-up is CPU work, and at FaaS sizes it is starved: exp-b measured the same JVM warm-up at
# 3.59 s on 0.25 vCPU and 0.86 s on 1 vCPU, about the same CPU-seconds. e11 runs dagsim with its
# CPU layer: every sandbox has a quota q, the node has K cores, and a boost policy decides who
# gets the spare CPU while sandboxes start (provisioning + the first request's warm-up).
_LA = Policy("la", snap=True, ahead="restore", gate=True, jit=True, margin=0.3, preempt=True, keep="gdsf")
_PW = Policy("prewarm", ahead="cold", theta=0.5, gate=True, preempt=True, keep="gdsf")
E11_POLS = {
    "od": Policy("od", snap=True, keep="gdsf"),                       # restore on demand (SnapStart-like)
    "od+uniform": Policy("od+uniform", snap=True, keep="gdsf", boost="uniform"),   # + Cloud Run's boost
    "la": _LA,                                                         # look-ahead restore, no boost
    "la+uniform": replace(_LA, name="la+uniform", boost="uniform"),
    "la+cp": replace(_LA, name="la+cp", boost="cp"),
    "la+slack": replace(_LA, name="la+slack", boost="slack"),          # fair: smallest largest lateness
    "la+plan": replace(_LA, name="la+plan", boost="plan"),             # THE CPU PLAN (this proposal)
    "la+plan+jit": replace(_LA, name="la+plan+jit", boost="plan", lazy=True),   # ... just in time
    "cold": Policy("cold", keep="gdsf"),                               # no snapshots: cold start on demand
    "cold+uniform": Policy("cold+uniform", keep="gdsf", boost="uniform"),
    "prewarm": _PW,                                                    # Xanadu-style just-in-time cold prewarm
    "prewarm+plan": replace(_PW, name="prewarm+plan", boost="plan"),
    "prewarm+plan+jit": replace(_PW, name="prewarm+plan+jit", boost="plan", lazy=True),
}
E11_DAGS = [("chain3", lambda t: chain(3, JAVA, t)), ("chain5", lambda t: chain(5, JAVA, t)),
            ("chain8", lambda t: chain(8, JAVA, t)), ("fanout4", lambda t: fanout(4, t)),
            ("ml", ml_pipeline), ("mixed", mixed), ("router", router), ("trip", trip_booking)]


def _e11_iso(args):
    q, K, dname, pn, seeds = args
    mk = dict(E11_DAGS)[dname]
    pol = E11_POLS[pn]
    lats, boost, mem = [], [], []
    for k in range(seeds):
        sim = Sim(ttl0(pol), seed=k, cpu_cores=K, cpu_quota=q)
        sim.invoke(0.0, mk(dname), "w")
        sim.run()
        lats.append(sim.results[0][3])
        boost.append(sim.cpu_boost / 1000)
        mem.append(sim.memtime / 1e6)
    return (q, K, dname, pn, statistics.mean(lats), pct(lats, .99), statistics.mean(boost), statistics.mean(mem))


def e11a(seeds=50, quotas=(0.25, 0.5), cores=(1, 2, 4)):
    """One cold workflow alone on a node with K cores; every sandbox has quota q. Also a
    reference with every sandbox at 1 vCPU and no limit (static right-sizing, as ORION or
    Aquatope would size a stage)."""
    from multiprocessing import Pool
    print(f"e11a: isolated cold workflows, functions at {quotas} vCPU, node {cores} cores")
    jobs = [(q, K, d, pn, seeds) for q in quotas for K in cores for d, _ in E11_DAGS for pn in E11_POLS]
    jobs += [(1.0, math.inf, d, pn, seeds) for d, _ in E11_DAGS for pn in ("od", "la")]
    with Pool(int(os.environ.get("SIM_PROCS", "4"))) as pool:
        rows = pool.map(_e11_iso, jobs)
    write_csv("e11a_cpu_isolated.csv", rows, ["quota_vcpu", "cores", "dag", "policy", "mean_ms", "p99_ms",
                                              "boost_cpu_s", "mem_GBs"])
    res = {(r[0], r[1], r[2], r[3]): r[4] for r in rows}
    for q in quotas:
        for K in cores:
            print(f"   q={q} vCPU, {K} cores: mean latency, s (od | od+uniform | la | la+uniform | la+cp | "
                  f"la+slack | la+plan | la+plan+jit || cold | cold+uniform | prewarm | prewarm+plan | "
                  f"prewarm+plan+jit)")
            for d, _ in E11_DAGS:
                v = [res[(q, K, d, pn)] / 1000 for pn in E11_POLS]
                print(f"      {d:8s} " + " ".join(f"{x:6.2f}" for x in v[:8]) + "  ||" +
                      " ".join(f"{x:6.2f}" for x in v[8:]), flush=True)
    return rows


def e11b(seeds=10, cores=(2, 4, 8), q=0.25):
    """A burst: 16 cold workflows (two of each shape, distinct functions) within one second."""
    print(f"e11b: burst of 16 cold workflows within 1 s, functions at {q} vCPU")
    rows = []
    for K in cores:
        for pn, pol in E11_POLS.items():
            lats, boost, mem = [], 0.0, 0.0
            for seed in range(seeds):
                # no keep-alive: the burst's workflows share no function, so it changes no latency,
                # and memory then counts start-ups and runs, not sandboxes kept for later
                sim = Sim(ttl0(pol), mem_budget_mb=64 * 1024, seed=seed, cpu_cores=K, cpu_quota=q)
                i = 0
                for rep in range(2):
                    for dname, mk in E11_DAGS:
                        sim.invoke(i * 1000.0 / 16, mk(f"b{rep}{dname}"), f"b{rep}{dname}")
                        i += 1
                sim.run()
                lats += [r[3] for r in sim.results]
                boost += sim.cpu_boost / 1000
                mem += sim.memtime / 1e6
            row = (K, pn, len(lats), statistics.mean(lats), pct(lats, .99), max(lats), boost / seeds, mem / seeds)
            rows.append(row)
            print(f"   {K} cores {pn:16s} mean {row[3]/1000:6.2f} s  p99 {row[4]/1000:6.2f} s  max {row[5]/1000:6.2f} s"
                  f"  | boost {row[6]:6.1f} CPU-s | memory {row[7]:6.1f} GB*s per burst", flush=True)
    write_csv("e11b_cpu_burst.csv", rows, ["cores", "policy", "n", "mean_ms", "p99_ms", "max_ms", "boost_cpu_s",
                                           "mem_GBs"])
    return rows


def _e11_trace(args):
    M, pn, K, q, days, seed = args
    pol = E11_POLS[pn]
    arr = load_arrivals(days)
    apps = sorted({a for _, a in arr})
    dags = {a: TEMPLATES[a % len(TEMPLATES)][1](f"app{a}") for a in apps}
    last, gap = {}, []
    for t, a in arr:
        gap.append(t - last[a] if a in last else math.inf)
        last[a] = t
    t0 = time.time()
    sim = Sim(pol, mem_budget_mb=M * 1024, seed=seed, cpu_cores=K, cpu_quota=q)
    for t, a in arr:
        sim.invoke(t, dags[a], a)
    sim.run()
    key = {(w, t): lat for w, _, t, lat in sim.results}
    lats = [key[(a, t)] for t, a in arr if (a, t) in key]
    gaps = [g for (t, a), g in zip(arr, gap) if (a, t) in key]
    miss = [l for l, g in zip(lats, gaps) if g > 600_000]
    hot = [l for l, g in zip(lats, gaps) if g <= 600_000]
    n = len(lats)
    return (M, pn, K, q, n, statistics.mean(lats), pct(lats, .5), pct(lats, .99), len(miss), statistics.mean(miss),
            pct(miss, .99), statistics.mean(hot), pct(hot, .99),
            (sim.stats["cold_boots"] + sim.stats["restores"]) / n * 1000, sim.memtime / 1e6 / 3600 / (days * 24),
            sim.cpu_used / 1000 / 3600, sim.cpu_boost / 1000 / 3600, sim.stats["overflow"], time.time() - t0)


def e11c(days=3, budgets_gb=(32,), cores=(64, 32), q=0.25, seed=1, pols=None):
    """The Azure trace (as e10b) with functions at q vCPU on a node with K cores. The trace's CPU
    demand at 0.25 vCPU is very bursty (unlimited cores: mean 0.6 cores in use, p99 3-7.5,
    p99.9 34, peak 84), so a node of 1-8 cores collapses into queues at the peaks; 32 and 64
    cores hold the p99.9. Snapshot policies only: without snapshots, cold starts are ~4x the CPU
    work and overload even these nodes at the peaks (e11a/e11b cover the no-snapshot case).
    Rows are printed and saved as each run finishes. With pols, only those policies run and the
    CSV keeps its other rows."""
    from multiprocessing import Pool
    print(f"e11c: Azure 2021 trace, {days} days, functions at {q} vCPU, node {cores} cores", flush=True)
    every = ["od", "od+uniform", "la", "la+uniform", "la+cp", "la+slack", "la+plan", "la+plan+jit"]
    jobs = [(M, pn, K, q, days, seed) for M in budgets_gb for K in cores for pn in (pols or every)]
    order = {(K, pn): i for i, (K, pn) in enumerate((K, pn) for M in budgets_gb for K in cores for pn in every)}
    keep = []
    if pols and os.path.exists(os.path.join(OUT, "e11c_cpu_trace.csv")):
        with open(os.path.join(OUT, "e11c_cpu_trace.csv")) as f:
            keep = [r for r in list(csv.reader(f))[1:] if r[1] not in pols]
    header = ["budget_GB", "policy", "cores", "quota_vcpu", "n", "mean_ms", "p50_ms", "p99_ms", "n_after_idle",
              "after_idle_mean_ms", "after_idle_p99_ms", "hot_mean_ms", "hot_p99_ms", "starts_per_1000",
              "avg_mem_GB", "cpu_h", "boost_cpu_h", "overflow"]
    rows = []
    with Pool(int(os.environ.get("SIM_PROCS", "4"))) as pool:
        for r in pool.imap_unordered(_e11_trace, jobs):
            rows.append(r)
            print(f"   {r[0]}GB {r[2]} cores {r[1]:14s} mean {r[5]:6.0f} p99 {r[7]:6.0f} | cold workflows (n={r[8]}) "
                  f"mean {r[9]:6.0f} p99 {r[10]:6.0f} | hot mean {r[11]:5.0f} p99 {r[12]:6.0f} | starts/1000 {r[13]:5.1f} | "
                  f"mem {r[14]:5.1f} GB | CPU {r[15]:5.2f} h (boost {r[16]:5.2f} h) | overflow {r[17]} ({r[-1]:.0f}s)",
                  flush=True)
            write_csv("e11c_cpu_trace.csv", sorted(keep + [x[:-1] for x in rows],
                                                   key=lambda x: order[(int(x[2]), x[1])]), header)
    return rows


def e11x(seeds=10):
    """Controls for the CPU plan just in time (Policy.lazy): (1) without the CPU layer the flag
    changes nothing; (2) every isolated run gives all its memory back; (3) the known answer: on
    one spare core a chain holds exactly the memory-time of on-demand restore with the boost,
    and finishes (d - 1) edge delays sooner, the only idle CPU there is to overlap (Proposition
    CP4 with every request CPU work)."""
    print("e11x: controls for the CPU plan just in time")
    ok, rows = True, []
    same = 0
    for dname, mk in E11_DAGS:
        for k in range(seeds):
            got = []
            for pn in ("la", "la+plan+jit"):
                sim = Sim(ttl0(E11_POLS[pn]), seed=k)
                sim.invoke(0.0, mk(dname), "w")
                sim.run()
                got.append((sim.results[0][3], sim.memtime))
            same += got[0] == got[1]
    n = len(E11_DAGS) * seeds
    ok &= same == n
    rows.append(("inert without the CPU layer", same, n))
    print(f"   without the CPU layer, la+plan+jit = la exactly: {same}/{n}")
    back = 0
    for dname, mk in E11_DAGS:
        for K in (1, 2, 4):
            for k in range(seeds):
                sim = Sim(ttl0(E11_POLS["la+plan+jit"]), seed=k, cpu_cores=K, cpu_quota=0.25)
                sim.invoke(0.0, mk(dname), "w")
                sim.run()
                back += abs(sim.mem) < 1e-9 and not sim.cjobs
    n = len(E11_DAGS) * 3 * seeds
    ok &= back == n
    rows.append(("memory and CPU jobs all released", back, n))
    print(f"   every run ends with no memory held and no CPU job left: {back}/{n}")
    exact = 0
    for d in (2, 3, 5, 8):
        got = {}
        for pn in ("od+uniform", "la+plan+jit"):
            sim = Sim(ttl0(E11_POLS[pn]), jitter=False, cpu_cores=1, cpu_quota=0.25)
            sim.invoke(0.0, chain(d, JAVA, f"c{d}"), "w")
            sim.run()
            got[pn] = (sim.results[0][3], sim.memtime)
        (l0, m0), (l1, m1) = got["od+uniform"], got["la+plan+jit"]
        hit = abs(m1 - m0) <= 1e-9 * m0 and abs((l0 - l1) - (d - 1) * EDGE_MS) < 1e-6
        exact += hit
        print(f"   chain of {d}, 1 spare core: memory {m1 / 1e6:.4f} vs {m0 / 1e6:.4f} GB*s, "
              f"latency {l1:.1f} vs {l0:.1f} ms ({'ok' if hit else 'FAIL'})")
    ok &= exact == 4
    rows.append(("one spare core: memory of on-demand, (d-1) edges sooner", exact, 4))
    write_csv("e11x_jit_controls.csv", rows, ["control", "passed", "of"])
    print("   e11x", "PASS" if ok else "FAIL")
    return ok


def _e11_sel(args):
    dname, pn, nosnap, q, K, seeds = args
    mk = dict(E11_DAGS)[dname]
    pol = replace(E11_POLS[pn], nosnap=frozenset(nosnap))
    lats = []
    for k in range(seeds):
        sim = Sim(ttl0(pol), seed=k, cpu_cores=K, cpu_quota=q)
        sim.invoke(0.0, mk(dname), "w")
        sim.run()
        lats.append(sim.results[0][3])
    return dname, pn, tuple(sorted(nosnap)), statistics.mean(lats)


def e11d(seeds=20, q=0.25, K=2, tol=0.05):
    """Which stages still need a snapshot? Every subset of a workflow's functions gets a snapshot,
    the rest cold-start (ahead, with the same CPU policy). Reported: the fewest snapshots whose
    latency is within tol of snapshotting everything, with and without the CPU plan."""
    import itertools
    from multiprocessing import Pool
    print(f"e11d: which stages need a snapshot (functions at {q} vCPU, {K} cores, within {tol:.0%} of all)")
    jobs = []
    fns = {}
    for dname, mk in E11_DAGS:
        if dname in ("chain8", "router"):
            continue                        # 2^8+ subsets; chain5 and trip cover the shapes
        fns[dname] = sorted({n.fn.split(".", 1)[1] for n in mk(dname).nodes.values()})
        for pn in ("la", "la+plan"):
            for k in range(len(fns[dname]) + 1):
                for sub in itertools.combinations(fns[dname], k):
                    jobs.append((dname, pn, sub, q, K, seeds))
    with Pool(int(os.environ.get("SIM_PROCS", "4"))) as pool:
        res = pool.map(_e11_sel, jobs)
    rows = []
    for dname in fns:
        for pn in ("la", "la+plan"):
            mine = [r for r in res if r[0] == dname and r[1] == pn]
            full = next(r[3] for r in mine if not r[2])
            none = next(r[3] for r in mine if len(r[2]) == len(fns[dname]))
            ok = [r for r in mine if r[3] <= full * (1 + tol)]
            best = max(ok, key=lambda r: (len(r[2]), -r[3]))
            snap = [f for f in fns[dname] if f not in best[2]]
            rows.append((dname, pn, len(fns[dname]), full, none, len(snap), best[3], " ".join(snap)))
            print(f"   {dname:8s} {pn:9s} all snapshots {full/1000:5.2f} s, none {none/1000:5.2f} s; "
                  f"{len(snap)}/{len(fns[dname])} suffice: {best[3]/1000:5.2f} s ({' '.join(snap)})", flush=True)
    write_csv("e11d_cpu_selection.csv", rows, ["dag", "policy", "functions", "all_snap_ms", "no_snap_ms",
                                               "snapshots_needed", "latency_ms", "snapshotted"])
    return rows


def e11o():
    """The online rule (dagsim's boost="slack") against the exact plan, in cpuplan.py's fluid model."""
    import cpuplan
    rows = cpuplan.main()
    pols = ["no_boost", "equal", "critical_first", "fair", "cpu_plan", "exact"]
    write_csv("e11o_cpu_plan.csv", rows, ["case", "spare_cores"] + [f"slowest_{p}_s" for p in pols]
              + [f"mean_{p}_s" for p in pols] + [f"boost_{p}_cpu_s" for p in pols[1:]])


def e11():
    e11o()
    e11a()
    e11b()
    e11d()
    e11c()


def e6():
    import e6_cost
    e6_cost.main()


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
    which = sys.argv[1:] or ["e0", "e1", "e2", "e3", "e5", "e6", "e7a", "e4", "e4b", "e7b", "e8", "e9", "e10"]
    for w in which:
        globals()[w]()
