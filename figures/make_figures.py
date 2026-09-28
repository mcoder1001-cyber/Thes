#!/usr/bin/env python3
"""Thesis figures, from the committed results only (no simulation is run here).

    python3 figures/make_figures.py        -> figures/fig*.pdf (vector, for LaTeX) and fig*.png

Style: one colour per entity across all figures (look-ahead restore = blue, restore on demand
= orange, cold prewarm = aqua, keep-alive / baselines = gray); palette validated for colour-
blind separation on a white page (dataviz validate_palette.js: all pairs pass, aqua needs its
visible labels); thin marks, hairline solid grid, values labelled directly, no dual axes.
The data behind every figure is the CSV named in figures/README.md.
"""
import csv
import math
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
from matplotlib.path import Path  # noqa: E402
from matplotlib.patches import PathPatch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SIM = os.path.join(REPO, "ideas", "sim", "results")
sys.path.insert(0, os.path.join(REPO, "theory"))

# ---------------------------------------------------------------- palette (validated)
BLUE, ORANGE, AQUA, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"
GRAY = "#a9a79f"                 # baselines / de-emphasis marks
RAMP = {"light": "#86b6ef", "mid": "#2a78d6", "dark": "#104281", "mid2": "#256abf"}
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE = "#e1e0d9", "#c3c2b7", "#ffffff"
PX = 0.75                        # 1 px in points (96 dpi reference)

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8.5, "axes.titlesize": 9.5, "axes.titleweight": "bold",
    "axes.labelsize": 8.5, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "xtick.labelcolor": INK2, "ytick.labelcolor": INK2, "axes.edgecolor": AXIS, "axes.linewidth": PX,
    "xtick.major.width": PX, "ytick.major.width": PX, "xtick.major.size": 3, "ytick.major.size": 0,
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "legend.frameon": False, "legend.fontsize": 8, "pdf.fonttype": 42, "ps.fonttype": 42,
})
W = 6.3                          # thesis text width, inches


def read(name, base=SIM):
    with open(os.path.join(base, name)) as f:
        return list(csv.DictReader(f))


def style(ax, grid="y"):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    if grid == "y":
        ax.spines["left"].set_visible(False)
        ax.yaxis.grid(True, color=GRID, linewidth=PX)
    else:
        ax.spines["bottom"].set_visible(False)
        ax.spines["left"].set_color(AXIS)
        ax.xaxis.grid(True, color=GRID, linewidth=PX)
        ax.tick_params(axis="x", length=0)
        ax.tick_params(axis="y", length=0)
    ax.set_axisbelow(True)


def title(ax, t, sub=None):
    ax.set_title(t, loc="left", color=INK, pad=14 if sub else 6)
    if sub:
        ax.text(0, 1.015, sub, transform=ax.transAxes, fontsize=8, color=INK2, va="bottom")


def _px_to_data(ax, px):
    """Data units per pixel along x and y for the axes as currently laid out."""
    fig = ax.figure
    fig.canvas.draw()
    bb = ax.get_window_extent()
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    return px * abs(x1 - x0) / bb.width, px * abs(y1 - y0) / bb.height


def bar(ax, base, value, center, thick, color, horizontal):
    """A bar with 4 px rounded corners at the data end and a square baseline (marks spec)."""
    rx, ry = _px_to_data(ax, 4 * ax.figure.dpi / 96)
    if horizontal:
        a, b = center - thick / 2, center + thick / 2
        r_len, r_th = min(rx, abs(value - base)), min(ry, thick / 2)
        e = value
        v = [(base, a), (e - r_len, a), (e, a), (e, a + r_th), (e, b - r_th), (e, b), (e - r_len, b), (base, b), (base, a)]
    else:
        a, b = center - thick / 2, center + thick / 2
        r_len, r_th = min(ry, abs(value - base)), min(rx, thick / 2)
        e = value
        v = [(a, base), (a, e - r_len), (a, e), (a + r_th, e), (b - r_th, e), (b, e), (b, e - r_len), (b, base), (a, base)]
    codes = [Path.MOVETO, Path.LINETO, Path.CURVE3, Path.CURVE3, Path.LINETO, Path.CURVE3, Path.CURVE3,
             Path.LINETO, Path.CLOSEPOLY]
    ax.add_patch(PathPatch(Path(v, codes), facecolor=color, edgecolor="none", zorder=3))


def bar_thickness(ax, slot, horizontal, n_in_slot=1):
    """Bar thickness in data units: at most 24 px, and leaving a 2 px surface gap."""
    rx, ry = _px_to_data(ax, ax.figure.dpi / 96)
    px = ry if horizontal else rx
    per = slot / n_in_slot
    return min(24 * px, per - 2 * px), per


def line(ax, xs, ys, color, label=None, z=3):
    ax.plot(xs, ys, color=color, linewidth=2 * PX, solid_capstyle="round", solid_joinstyle="round", zorder=z,
            label=label)
    ax.plot(xs, ys, linestyle="none", marker="o", markersize=8 * PX, markerfacecolor=color,
            markeredgecolor=SURFACE, markeredgewidth=2 * PX, zorder=z + 1)


def end_label(ax, x, y, text, ytext=None, dx=6):
    """Direct label in text ink at a line's end; a hairline leader if it had to move."""
    ytext = y if ytext is None else ytext
    ax.annotate(text, (x, y), xytext=(dx, 0), textcoords="offset points", va="center", fontsize=8, color=INK,
                annotation_clip=False) if ytext == y else \
        ax.annotate(text, (x, y), xytext=(x, ytext), textcoords="data", va="center", fontsize=8, color=INK,
                    annotation_clip=False, arrowprops=dict(arrowstyle="-", color=MUTED, lw=PX, shrinkA=2, shrinkB=4))


def save(fig, name):
    for ext in ("pdf", "png"):
        fig.savefig(os.path.join(HERE, f"{name}.{ext}"), dpi=220 if ext == "png" else None)
    plt.close(fig)
    print("wrote", name)


# ---------------------------------------------------------------- figure 1
def fig1_cascade():
    """The cascade, and what look-ahead does to it (e10a + e1 cold prewarm)."""
    e10 = read("e10a_chains_final.csv")
    e1 = read("e1_cascade.csv")
    d = list(range(1, 9))
    get = lambda rows, pol: [float(next(r["mean_ms"] for r in rows if r["policy"] == pol and int(r["depth"]) == k)) / 1000 for k in d]
    od, la, pw = get(e10, "snap"), get(e10, "recommended"), get(e1, "prewarm")
    fig = plt.figure(figsize=(W, 3.3))
    ax = fig.add_axes([0.08, 0.14, 0.62, 0.72])
    style(ax)
    line(ax, d, pw, AQUA, "Cold prewarm along the DAG (Xanadu-style)")
    line(ax, d, od, ORANGE, "Restore on demand (SnapStart-style)")
    line(ax, d, la, BLUE, "Look-ahead restore (this thesis)")
    ax.set_xlim(0.7, 8.3)
    ax.set_ylim(0, 6.6)
    ax.set_xticks(d)
    ax.set_xlabel("Workflow depth (stages), every stage cold")
    ax.set_ylabel("End-to-end latency (s)")
    title(ax, "Look-ahead removes the restore from the cascade",
          "Cold Java chain (restore 650 ms, run 75 ms per stage), mean of 200 simulated runs")
    end_label(ax, 8, od[-1], f"Restore on demand  {od[-1]:.2f} s", ytext=od[-1] + 0.45)
    end_label(ax, 8, pw[-1], f"Cold prewarm  {pw[-1]:.2f} s", ytext=pw[-1] - 0.45)
    end_label(ax, 8, la[-1], f"Look-ahead  {la[-1]:.2f} s")
    slope = lambda ys: (ys[-1] - ys[0]) / (len(ys) - 1)
    ax.text(5.35, 3.35, f"+{slope(od):.2f} s per stage", color=INK2, fontsize=8)
    ax.text(4.6, la[4] + 0.35, f"+{slope(la):.2f} s per stage", color=INK2, fontsize=8)
    ax.legend(loc="upper left", bbox_to_anchor=(0.0, 1.0), handlelength=1.6)
    save(fig, "fig1_cascade")


# ---------------------------------------------------------------- figure 2
def fig2_trace():
    """Azure 2021 trace, 128 GB (memory not binding): cold workflows and memory by policy."""
    e4 = {r["policy"]: r for r in read("e4_trace.csv") if r["budget_GB"] == "128"}
    e10 = {r["policy"]: r for r in read("e10b_trace_final.csv") if r["budget_GB"] == "128"}
    rows = [  # label, mean s, p99 s, memory GB, colour
        ("Keep-alive 10 min\n(OpenWhisk default)", e4["keepalive"], GRAY),
        ("Keep-alive 60 min", e4["keepalive-60min"], GRAY),
        ("Cold prewarm along the DAG", e4["prewarm"], AQUA),
        ("Restore on demand", e10["snap"], ORANGE),
        ("Look-ahead restore\n(final policy)", e10["recommended"], BLUE),
    ]
    fig = plt.figure(figsize=(W, 3.1))
    sig = lambda v: f"{v:.2f}" if v < 10 else f"{v:.1f}"
    panels = [("Mean latency (s)", lambda r: float(r["after_idle_mean_ms"]) / 1000, 11, sig),
              ("p99 latency (s)", lambda r: float(r["after_idle_p99_ms"]) / 1000, 29, sig),
              ("Memory held (GB)", lambda r: float(r["avg_mem_GB"]), 100, lambda v: f"{v:.0f}")]
    left, gap, wpan = 0.305, 0.035, 0.195
    for i, (name, f, xmax, fmt) in enumerate(panels):
        ax = fig.add_axes([left + i * (wpan + gap), 0.08, wpan, 0.72])
        style(ax, grid="x")
        n = len(rows)
        ax.set_ylim(-0.6, n - 0.4)
        ax.set_xlim(0, xmax)
        ax.invert_yaxis()
        th, _ = bar_thickness(ax, 1.0, True)
        for j, (lab, r, c) in enumerate(rows):
            v = f(r)
            bar(ax, 0, v, j, th, c, True)
            ax.text(v + xmax * 0.02, j, fmt(v), va="center", fontsize=8, color=INK)
        ax.set_yticks(range(n))
        ax.set_yticklabels([lab for lab, *_ in rows] if i == 0 else [])
        ax.set_title(name, loc="left", fontsize=8.5, color=INK, pad=4, fontweight="normal")
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(3))
    fig.text(0.01, 0.955, "Azure trace: cold workflows 2.9× faster than restore on demand, same memory",
             fontsize=9.5, fontweight="bold", color=INK)
    fig.text(0.01, 0.905, "68 workflows, 432,945 calls; latency of the 794 cold calls (> 10 min idle); "
             "memory over all calls; 128 GB", fontsize=8, color=INK2)
    save(fig, "fig2_trace")


# ---------------------------------------------------------------- figure 3
def fig3_memory_slots():
    """Theorem 8(b): latency of an 8-stage Java chain against the number of memory slots."""
    import verify_dag as vd
    r, w, delta, d = 650.0, 75.0, 2.0, 8
    ks = list(range(1, d + 1))
    lat = [vd.chain_slots_rec(d, r, w, delta, k) / 1000 for k in ks]
    od = (d * (r + w) + (d - 1) * delta) / 1000
    fig = plt.figure(figsize=(W, 3.2))
    ax = fig.add_axes([0.08, 0.22, 0.88, 0.6])
    style(ax)
    ax.set_xlim(0.4, d + 0.6)
    ax.set_ylim(0, 6.6)
    th, _ = bar_thickness(ax, 1.0, False)
    for k, v in zip(ks, lat):
        bar(ax, 0, v, k, th, BLUE, False)
        if k > 1:                   # k = 1 equals the reference line, which carries its label
            ax.text(k, v + 0.12, f"{v:.2f}", ha="center", va="bottom", fontsize=8, color=INK)
    ax.axhline(od, color=ORANGE, linewidth=2 * PX, zorder=2)
    ax.text(d + 0.55, od + 0.12, f"Restore on demand {od:.2f} s  (1 slot: {lat[0]:.2f} s)", ha="right",
            va="bottom", fontsize=8, color=INK)
    ax.set_xticks(ks)
    ax.set_xticklabels([f"{k}\n{k * 0.5:g} GB" for k in ks])
    ax.set_xlabel("Memory budget: sandboxes the workflow may hold at once (× 512 MB)")
    ax.set_ylabel("Latency (s)")
    title(ax, "Each extra memory slot divides the restore cost (Theorem 8(b))",
          "8-stage Java chain under a memory cap; the schedule is optimal (checked by the exact solver)")
    save(fig, "fig3_memory_slots")


# ---------------------------------------------------------------- figure 4
def fig4_budget():
    """Azure trace under memory pressure: p99 of all calls and of cold workflows, by budget."""
    e10 = read("e10b_trace_final.csv")
    budgets = ["24", "32", "128"]
    g = lambda pol, col: [float(next(r[col] for r in e10 if r["policy"] == pol and r["budget_GB"] == b)) / 1000
                          for b in budgets]
    fig = plt.figure(figsize=(W, 3.2))
    for i, (col, name, ymax) in enumerate([("p99_ms", "All calls: p99 (s)", 4.6),
                                           ("after_idle_p99_ms", "Cold workflows: p99 (s)", 7.4)]):
        ax = fig.add_axes([0.07 + i * 0.49, 0.2, 0.42, 0.58])
        style(ax)
        ax.set_xlim(-0.6, len(budgets) - 0.4)
        ax.set_ylim(0, ymax)
        th, per = bar_thickness(ax, 0.72, False, 2)
        for s, (pol, c) in enumerate([("snap", ORANGE), ("recommended", BLUE)]):
            for j, v in enumerate(g(pol, col)):
                x = j + (s - 0.5) * per
                bar(ax, 0, v, x, th, c, False)
                ax.text(x, v + ymax * 0.015, f"{v:.2f}", ha="center", va="bottom", fontsize=7.5, color=INK)
        ax.set_xticks(range(len(budgets)))
        ax.set_xticklabels([f"{b} GB" for b in budgets])
        ax.set_title(name, loc="left", fontsize=8.5, color=INK, pad=4, fontweight="normal")
    h = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (ORANGE, BLUE)]
    fig.legend(h, ["Restore on demand", "Look-ahead restore (final policy)"], loc="lower center",
               bbox_to_anchor=(0.5, 0.0), ncol=2, handlelength=1.0, handleheight=0.8)
    fig.text(0.01, 0.955, "The gain holds when memory is tight", fontsize=9.5, fontweight="bold", color=INK)
    fig.text(0.01, 0.905, "Azure trace; memory budget below (24, 32 GB) and above (128 GB) the ~50 GB working set",
             fontsize=8, color=INK2)
    save(fig, "fig4_budget")


# ---------------------------------------------------------------- figure 5
def fig5_contention():
    """What could kill it: restores that slow each other down (e5; restore channels, closed form)."""
    e5 = read("e5_sensitivity.csv")
    fig = plt.figure(figsize=(W, 3.3))
    ax = fig.add_axes([0.09, 0.22, 0.37, 0.56])
    style(ax)
    for rr, c, lab in (("100", RAMP["light"], "restore 100 ms"), ("650", RAMP["mid"], "restore 650 ms"),
                       ("2000", RAMP["dark"], "restore 2 s")):
        pts = [(float(r["beta"]), float(r["speedup"])) for r in e5 if r["r_ms"] == rr]
        xs, ys = zip(*pts)
        line(ax, xs, ys, c, lab)
    ax.set_xlim(-0.05, 1.05)
    ax.set_ylim(0, 4.6)
    ax.set_xticks([0, 0.25, 1])
    ax.set_xticklabels(["0", "0.25", "1"])
    ax.set_xlabel("Restore contention β  (0 parallel, 1 serial)")
    ax.set_ylabel("Speed-up vs on demand (×)")
    ax.legend(loc="upper right", handlelength=1.6)
    ax.set_title("(a) Gain shrinks as restores serialise", loc="left", fontsize=8.5, color=INK, fontweight="normal")
    # (b) restore channels, closed form (theory/ALGORITHM.md, Corollary A3)
    r, w, delta, d = 650.0, 75.0, 2.0, 5
    cs = list(range(1, 10))
    lat = []
    for c in cs:
        tau = []
        for v in range(d):
            tau.append(max(0.0, tau[v - 1] + w + delta if v else 0.0, tau[v - c] + r if v >= c else 0.0))
        lat.append((tau[-1] + r + w) / 1000)
    od = (d * (r + w) + (d - 1) * delta) / 1000
    bx = fig.add_axes([0.6, 0.22, 0.37, 0.56])
    style(bx)
    line(bx, cs, lat, BLUE)
    bx.axhline(od, color=ORANGE, linewidth=2 * PX, zorder=2)
    bx.text(9.4, od + 0.1, f"Restore on demand {od:.2f} s", ha="right", va="bottom", fontsize=8, color=INK)
    bx.annotate(f"{lat[0]:.2f} s", (1, lat[0]), xytext=(8, 0), textcoords="offset points", va="center",
                fontsize=8, color=INK)
    bx.text(7, lat[-1] + 0.2, f"{lat[-1]:.2f} s from 5 at once", ha="center", va="bottom", fontsize=8, color=INK)
    bx.set_xlim(0.5, 9.5)
    bx.set_ylim(0, 4.2)
    bx.set_xticks(cs)
    bx.set_xlabel("Restores that can run at once (c)")
    bx.set_ylabel("Latency (s)")
    bx.set_title("(b) 5-stage Java chain, look-ahead", loc="left", fontsize=8.5, color=INK, fontweight="normal")
    fig.text(0.01, 0.955, "The main risk: restores that slow each other down", fontsize=9.5, fontweight="bold",
             color=INK)
    fig.text(0.01, 0.905, "(a) simulated 5-stage Java chain; (b) exact optimum with c parallel restores; "
             "test x2 will measure it", fontsize=8, color=INK2)
    save(fig, "fig5_contention")


# ---------------------------------------------------------------- figure 6
def fig6_planner():
    """The planner: (a) simulated single workflows under a budget, (b) guard's gap vs DAG size."""
    e9 = read("e9a_planner_single.csv")
    cases = [("mixed", "2.0", "Mixed workflow, 2×"), ("ml", "1.0", "ML pipeline, 1×"),
             ("router", "1.0", "Router (if/else), 1×"), ("trip", "2.0", "Trip booking, 2×"),
             ("chain8", "2.0", "8-stage chain, 2×")]
    G = "ahead+rw/gated/jit/guard"
    val = lambda dag, b, pol: float(next(r["mean_ms"] for r in e9 if r["dag"] == dag and r["budget_x_max_m"] == b
                                         and r["policy"] == pol)) / 1000
    fig = plt.figure(figsize=(W, 3.5))
    ax = fig.add_axes([0.2, 0.2, 0.33, 0.58])
    style(ax, grid="x")
    n = len(cases)
    ax.set_ylim(-0.6, n - 0.4)
    ax.set_xlim(0, 6.2)
    ax.invert_yaxis()
    th, per = bar_thickness(ax, 0.74, True, 2)
    for j, (dag, b, lab) in enumerate(cases):
        for s_, (pol, c) in enumerate([(G, GRAY), (G + "|plan", BLUE)]):
            v = val(dag, b, pol)
            y = j + (s_ - 0.5) * per
            bar(ax, 0, v, y, th, c, True)
            ax.text(v + 0.1, y, f"{v:.2f}", va="center", fontsize=7.5, color=INK)
    ax.set_yticks(range(n))
    ax.set_yticklabels([c[2] for c in cases])
    ax.set_xlabel("Mean latency (s)")
    ax.set_title("(a) One cold workflow, tight budget", loc="left", fontsize=8.5, color=INK, fontweight="normal")
    h = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (GRAY, BLUE)]
    fig.legend(h, ["Memory guard alone", "Guard + exact planner"], loc="lower left", bbox_to_anchor=(0.01, 0.0),
               ncol=2, handlelength=1.0, handleheight=0.8)
    # (b) the guard's gap to the exact optimum by size (theory/exact_scale.csv)
    sc = read("exact_scale.csv", base=os.path.join(REPO, "theory"))
    bx = fig.add_axes([0.65, 0.2, 0.22, 0.58])
    style(bx)
    for shape, c, lab in (("dag", VIOLET, "DAGs"), ("chain", AQUA, "chains")):
        pts = [(int(r["stages"]), 100 * float(r["guard_gap_mean"])) for r in sc if r["shape"] == shape]
        xs, ys = zip(*pts)
        line(bx, xs, ys, c)
        end_label(bx, xs[-1], ys[-1], f"{lab} {ys[-1]:.0f}%")
    bx.set_xlim(3.5, 10.5)
    bx.set_ylim(0, 16)
    bx.set_xticks([4, 6, 8, 10])
    bx.set_xlabel("Stages")
    bx.set_ylabel("Guard slower than optimum (%)")
    bx.set_title("(b) Guard's gap grows with size", loc="left", fontsize=8.5, color=INK, fontweight="normal")
    fig.text(0.01, 0.955, "Planning the restore order exactly beats reacting to it", fontsize=9.5,
             fontweight="bold", color=INK)
    fig.text(0.01, 0.905, "(a) simulated with timing noise, 50 runs, budget = f × largest stage; "
             "(b) exact solver vs guard", fontsize=8, color=INK2)
    save(fig, "fig6_planner")


# ---------------------------------------------------------------- figure 7
def fig7_keepalive():
    """Keep-alive under look-ahead (e8, 24 GB): per-function GDSF vs LRU vs whole-workflow eviction."""
    e8 = {r["policy"]: r for r in read("e8_keepalive.csv") if r["budget_GB"] == "24"}
    R = "ahead+rw/gated/jit/guard"
    rows = [("LRU (least recently used)", e8[R], GRAY), ("GDSF per function (chosen)", e8[R + "|keep=gdsf"], BLUE),
            ("Whole workflow (Prop. 9)", e8[R + "|keep=wf"], GRAY),
            ("Workflow, evict only needed", e8[R + "|keep=wfp"], GRAY)]
    fig = plt.figure(figsize=(W, 2.6))
    panels = [("All calls: p99 (s)", lambda r: float(r["p99_ms"]) / 1000, 2.1, "{:.2f}"),
              ("Starts over the budget", lambda r: float(r["overflow"]), 10500, "{:,.0f}")]
    for i, (name, f, xmax, fmt) in enumerate(panels):
        ax = fig.add_axes([0.3 + i * 0.36, 0.1, 0.27, 0.64])
        style(ax, grid="x")
        n = len(rows)
        ax.set_ylim(-0.6, n - 0.4)
        ax.set_xlim(0, xmax)
        ax.invert_yaxis()
        th, _ = bar_thickness(ax, 1.0, True)
        for j, (lab, r, c) in enumerate(rows):
            v = f(r)
            bar(ax, 0, v, j, th, c, True)
            ax.text(v + xmax * 0.02, j, fmt.format(v), va="center", fontsize=8, color=INK)
        ax.set_yticks(range(n))
        ax.set_yticklabels([lab for lab, *_ in rows] if i == 0 else [])
        ax.xaxis.set_major_locator(matplotlib.ticker.MaxNLocator(3))
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:,.0f}" if x >= 100 else f"{x:g}"))
        ax.set_title(name, loc="left", fontsize=8.5, color=INK, pad=4, fontweight="normal")
    fig.text(0.01, 0.95, "Keep-alive: evict per function by cost (GDSF), not whole workflows", fontsize=9.5,
             fontweight="bold", color=INK)
    fig.text(0.01, 0.885, "Azure trace, 24 GB budget, look-ahead restore with the memory guard", fontsize=8,
             color=INK2)
    save(fig, "fig7_keepalive")


# ---------------------------------------------------------------- figure 8
def fig8_priming():
    """Building a deep Java snapshot: priming time by vCPU (exp-b, JVM pinned to the serving shape)."""
    rows = read("summary_exp-b.csv", base=os.path.join(REPO, "ideas", "exp-a-context-priming", "results"))
    vcpu = ["0.25", "1.0", "4.0"]
    val = lambda K, v: float(next(r["prime_wall_s"] for r in rows if r["flags"] == "pinned"
                                  and r["cond"] == f"prime{v}_K{K}"))
    fig = plt.figure(figsize=(W, 2.9))
    ax = fig.add_axes([0.08, 0.15, 0.56, 0.6])
    style(ax)
    ax.set_xlim(-0.6, len(vcpu) - 0.4)
    ax.set_ylim(0, 7)
    th, per = bar_thickness(ax, 0.6, False, 2)
    for s, (K, c) in enumerate([("100", RAMP["light"]), ("400", RAMP["mid2"])]):
        for j, v in enumerate(vcpu):
            y = val(K, v)
            x = j + (s - 0.5) * per
            bar(ax, 0, y, x, th, c, False)
            ax.text(x, y + 0.1, f"{y:.2f}", ha="center", va="bottom", fontsize=7.5, color=INK)
    ax.set_xticks(range(len(vcpu)))
    ax.set_xticklabels(["0.25 vCPU", "1 vCPU", "4 vCPU"])
    ax.set_ylabel("Priming wall time (s)")
    h = [plt.Rectangle((0, 0), 1, 1, color=c) for c in (RAMP["light"], RAMP["mid2"])]
    ax.legend(h, ["100 warm-up requests", "400 warm-up requests"], loc="upper right", handlelength=1.0,
              handleheight=0.8)
    title(ax, "Build snapshots on a big machine: 10× faster, same quality",
          "Spring Boot, JVM pinned to the 0.25-vCPU serving shape; n = 20 per cell (exp-b)")
    fig.text(0.68, 0.64, "Served at 0.25 vCPU, a snapshot\nprimed at 4 vCPU is as good as\n"
             "one primed at 0.25 vCPU\n(0.98×, 1.02×) when the JVM\nis pinned. Not pinned, it is\n11–17% worse.",
             fontsize=8, color=INK2, va="top")
    save(fig, "fig8_priming")


def main():
    fig1_cascade()
    fig2_trace()
    fig3_memory_slots()
    fig4_budget()
    fig5_contention()
    if os.path.exists(os.path.join(REPO, "theory", "exact_scale.csv")):
        fig6_planner()
    else:
        print("skip fig6: run theory/exact_scale.py first (writes theory/exact_scale.csv)")
    fig7_keepalive()
    fig8_priming()


if __name__ == "__main__":
    main()
