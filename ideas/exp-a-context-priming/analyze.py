#!/usr/bin/env python3
"""Analyse exp-a / exp-a-web / exp-b results -> results/summary_*.csv, figures, and a
printed report.

Residual R_N  = sum over the N served requests of max(0, latency - C), in ms, where C is
the steady-state latency at that CPU level: the median of the last 200 served requests
of the reference condition (primed on 1500 requests of the right edge).
Every ratio is reported with a 95% bootstrap CI over reps (resampling runs, 4000 draws).
"""
import collections
import csv
import glob
import json
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RES = os.path.join(HERE, "results")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    plt = None


def load(exp):
    runs = collections.defaultdict(list)
    for p in sorted(glob.glob(os.path.join(RES, exp, "*.json"))):
        r = json.load(open(p))
        runs[r["spec"]["name"]].append(r)
    errs = glob.glob(os.path.join(RES, exp, "*.err"))
    return runs, errs


def jit_ms(a, b):
    f = a.get("sun.os.hrt.frequency", 1e9) or 1e9
    return (b.get("java.ci.totalTime", 0) - a.get("java.ci.totalTime", 0)) / f * 1000


def metrics(run, C):
    lat = [x / 1000 for x in run["serve_lat_us"]]
    return dict(
        R=sum(max(0.0, x - C) for x in lat),
        first=lat[0],
        first10=statistics.mean(lat[:10]),
        p50=statistics.median(lat),
        jit_serve_ms=jit_ms(run["jit_at_snapshot"], run["jit_after_serve"]),
        compiles_serve=run["jit_after_serve"].get("sun.ci.totalCompiles", 0) - run["jit_at_snapshot"].get("sun.ci.totalCompiles", 0),
        compiles_snap=run["jit_at_snapshot"].get("sun.ci.totalCompiles", 0),
        jit_snap_ms=jit_ms({}, run["jit_at_snapshot"]),
        prime_wall=run.get("prime_wall_s", 0.0),
        steal=run.get("steal_ticks", 0),
    )


def ref_C(runs, name):
    tails = []
    for r in runs.get(name, []):
        tails += [x / 1000 for x in r["serve_lat_us"][-200:]]
    return statistics.median(tails) if tails else None


def boot_ratio(xs, ys, B=4000, seed=0):
    """CI of median(xs)/median(ys), resampling runs."""
    rnd = random.Random(seed)
    vals = []
    for _ in range(B):
        a = [rnd.choice(xs) for _ in xs]
        b = [rnd.choice(ys) for _ in ys]
        mb = statistics.median(b)
        if mb > 0:
            vals.append(statistics.median(a) / mb)
    vals.sort()
    return statistics.median(xs) / statistics.median(ys), vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def boot_med(xs, B=4000, seed=0):
    rnd = random.Random(seed)
    vals = sorted(statistics.median([rnd.choice(xs) for _ in xs]) for _ in range(B))
    return statistics.median(xs), vals[int(0.025 * B)], vals[int(0.975 * B) - 1]


# ------------------------------------------------------------------ exp-a
def analyse_a(exp="exp-a", target="bulk", prefix="a", right="real_bulk", Ks=(25, 100, 400)):
    runs, errs = load(exp)
    if not runs:
        print(f"{exp}: no results")
        return None
    print(f"\n==== {exp}: {sum(len(v) for v in runs.values())} runs, {len(errs)} errors ====")
    rows, out = [], {}
    for q in ("1.0", "0.25"):
        C = ref_C(runs, f"{prefix}_q{q}_ref_K1500")
        if C is None:
            continue
        print(f"\n-- {q} vCPU: steady-state C = {C:.3f} ms/request (serving {target})")
        M = {name: [metrics(r, C) for r in rs] for name, rs in runs.items() if name.startswith(f"{prefix}_q{q}_")}
        base = {}
        for name, ms in sorted(M.items()):
            Rs = [m["R"] for m in ms]
            med, lo, hi = boot_med(Rs)
            rows.append(dict(exp=exp, vcpu=q, cond=name.split(f"_q{q}_")[1], n=len(ms), C_ms=C,
                             R_med=med, R_lo=lo, R_hi=hi,
                             first_med=statistics.median(m["first"] for m in ms),
                             first10_med=statistics.median(m["first10"] for m in ms),
                             jit_serve_ms=statistics.median(m["jit_serve_ms"] for m in ms),
                             compiles_serve=statistics.median(m["compiles_serve"] for m in ms),
                             compiles_snap=statistics.median(m["compiles_snap"] for m in ms),
                             steal_max=max(m["steal"] for m in ms)))
            base[name.split(f"_q{q}_")[1]] = Rs
        out[q] = base
        print(f"   {'priming set':<22}{'n':>3}{'R300 ms [95% CI]':>28}{'first ms':>10}{'JIT during serve ms':>21}")
        for r in rows:
            if r["vcpu"] == q:
                print(f"   {r['cond']:<22}{r['n']:>3}{r['R_med']:>12.1f} [{r['R_lo']:7.1f},{r['R_hi']:7.1f}]"
                      f"{r['first_med']:>10.1f}{r['jit_serve_ms']:>21.0f}")
        # the ratios that matter, per K
        print(f"\n   ratios of median residual vs '{right}' at the same K (95% bootstrap CI):")
        for K in Ks:
            ref = base.get(f"{right}_K{K}")
            if not ref:
                continue
            for other in ("real_bulk2" if target == "bulk" else None, f"fps_{target}", "schema_bulk" if target == "bulk" else None,
                          "real_web" if target == "bulk" else "real_bulk", "mixed", "none"):
                if other is None:
                    continue
                key = f"{other}_K{K}" if other != "none" else "none_K0"
                if key not in base:
                    continue
                r, lo, hi = boot_ratio(base[key], ref)
                tag = {"real_bulk2": "A/A CONTROL (expect ~1)", f"fps_{target}": "format-preserving scrub",
                       "schema_bulk": "schema-only synthetic", "real_web": "WRONG edge",
                       "real_bulk": "WRONG edge", "mixed": "mixed 50/50", "none": "no priming (K=0)"}[other]
                print(f"     K={K:<4} {tag:<26} {r:6.2f}x  [{lo:5.2f}, {hi:5.2f}]")
        # follow-up (exp-a-mix): a mixed snapshot holding as many target-edge requests
        for k in (100, 400):
            mix, ref = base.get(f"mixed_K{2 * k}"), base.get(f"{right}_K{k}")
            if mix and ref:
                r, lo, hi = boot_ratio(mix, ref)
                print(f"     mixed K={2 * k} (= {k} per edge) vs {right} K={k}:  {r:6.2f}x  [{lo:5.2f}, {hi:5.2f}]")
    with open(os.path.join(RES, f"summary_{exp}.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    if plt:
        plot_a(runs, exp, prefix, target, right)
    return out


def plot_a(runs, exp, prefix, target, right):
    fig, axs = plt.subplots(1, 2, figsize=(11, 4))
    for ax, q in zip(axs, ("1.0", "0.25")):
        C = ref_C(runs, f"{prefix}_q{q}_ref_K1500")
        if C is None:
            continue
        K = 100
        sets = [(f"{right}_K{K}", f"primed on right edge ({right})", "#2f7fbf"),
                (f"fps_{target}_K{K}", "format-preserving scrub of right edge", "#1f9e89"),
                ("mixed_K" + str(K), "mixed 50/50", "#b58b00"),
                ((("real_web" if target == "bulk" else "real_bulk") + f"_K{K}"), "primed on WRONG edge", "#d1603d"),
                ("none_K0", "no priming (K=0)", "#9a9a9a")]
        if target == "bulk":
            sets.insert(2, (f"schema_bulk_K{K}", "schema-only synthetic", "#8a6fb3"))
        for key, lab, c in sets:
            rs = runs.get(f"{prefix}_q{q}_{key}", [])
            if not rs:
                continue
            n = min(len(r["serve_lat_us"]) for r in rs)
            cums = []
            for r in rs:
                acc, cs = 0.0, []
                for x in r["serve_lat_us"][:n]:
                    acc += max(0.0, x / 1000 - C)
                    cs.append(acc)
                cums.append(cs)
            med = [statistics.median(cs[i] for cs in cums) for i in range(n)]
            ax.plot(range(1, n + 1), med, color=c, label=lab, lw=1.6)
        ax.set_xlabel(f"requests served after the 'restore' ({target} edge)")
        ax.set_ylabel("cumulative residual warm-up, ms (median of runs)")
        ax.set_title(f"{q} vCPU, snapshot depth K={K}")
        ax.grid(alpha=.3)
    axs[0].legend(frameon=False, fontsize=7)
    fig.tight_layout()
    fig.savefig(os.path.join(RES, f"{exp}_curves.png"), dpi=150)


# ------------------------------------------------------------------ exp-b
def analyse_b():
    runs, errs = load("exp-b")
    if not runs:
        print("exp-b: no results")
        return None
    print(f"\n==== exp-b: {sum(len(v) for v in runs.values())} runs, {len(errs)} errors ====")
    rows = []
    for tag in ("pinned", "ergo"):
        C = ref_C(runs, f"b_{tag}_ref_K1500")
        if C is None:
            continue
        print(f"\n-- JVM flags: {tag}; serving at 0.25 vCPU; C = {C:.3f} ms")
        print(f"   {'condition':<20}{'n':>3}{'prime wall s':>14}{'compiles@snap':>15}{'R300 ms [95% CI]':>28}{'first ms':>10}")
        base = {}
        for name in sorted(n for n in runs if n.startswith(f"b_{tag}_")):
            ms = [metrics(r, C) for r in runs[name]]
            Rs = [m["R"] for m in ms]
            med, lo, hi = boot_med(Rs)
            cond = name[len(f"b_{tag}_"):]
            base[cond] = Rs
            row = dict(flags=tag, cond=cond, n=len(ms), C_ms=C, R_med=med, R_lo=lo, R_hi=hi,
                       prime_wall_s=statistics.median(m["prime_wall"] for m in ms),
                       compiles_snap=statistics.median(m["compiles_snap"] for m in ms),
                       first_med=statistics.median(m["first"] for m in ms))
            rows.append(row)
            print(f"   {cond:<20}{row['n']:>3}{row['prime_wall_s']:>14.2f}{row['compiles_snap']:>15.0f}"
                  f"{med:>12.1f} [{lo:7.1f},{hi:7.1f}]{row['first_med']:>10.1f}")
        for K in (100, 400):
            a, b = base.get(f"prime4.0_K{K}"), base.get(f"prime0.25_K{K}")
            if a and b:
                r, lo, hi = boot_ratio(a, b)
                print(f"   K={K}: residual primed@4 / primed@0.25 = {r:.2f}x [{lo:.2f}, {hi:.2f}]")
    with open(os.path.join(RES, "summary_exp-b.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return rows


if __name__ == "__main__":
    which = sys.argv[1:] or ["exp-a", "exp-a-web", "exp-b"]
    if "exp-a" in which:
        analyse_a()
    if "exp-a-web" in which:
        analyse_a("exp-a-web", target="web", prefix="w", right="real_web", Ks=(100,))
    if "exp-b" in which:
        analyse_b()
