#!/usr/bin/env python3
"""e6 -- which stages are worth a snapshot, in latency AND in money.

Exact model (theory/verify_dag.py: Theorem 7's composition rules and DP, Corollary 7.3's
price form), no simulation noise. Three parts:

  e6a  per function: resource cost of one cold start vs one restore (GB-seconds, the unit
       FaaS bills memory x time in), monthly storage cost of the image, and the break-even
       number of cold invocations per day for the image to pay for itself
  e6b  per workflow: none / snapshot every stage / the cheapest choice with the lowest
       latency / the cheapest choice overall, at several cold-invocation rates
  e6c  Azure 2021 trace: how many cold invocations per day real workflows actually have

Prices are public list prices used as an EXAMPLE (they change and differ by provider);
image sizes of Java/ML and the remote bandwidth are assumptions, stated below.
"""
import csv
import gzip
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), "theory"))
from verify_dag import rules, rules_od, pareto_front, expand, jit, on_demand, peak_mem  # noqa: E402

GBS = 0.0000166667          # $ per GB-second of function memory (AWS Lambda x86 list price)
STORE = {"local": 0.08,     # $ per GB-month, block storage next to the invoker (gp3-like)
         "remote": 0.023}   # $ per GB-month, object storage (S3 Standard-like)
REMOTE_MBPS = 100.0         # MB/s pulling an image from object storage at restore (assumption)
TTL_S = 600.0               # keep-alive: an invocation is cold if the workflow idled > 10 min

# A, B, C, r in ms (thesis measurements, same as dagsim.py); R[K] = residual warm-up after a
# depth-K snapshot; m, s in MB.
FN = {
    # java-spring: A, B, C, r as dagsim.JAVA. R: K=0 captures nothing (SnapStart's point),
    # K=1 ~32% (Prebaking's point, RESEARCH_PLAN S1), K=50 63 ms (exp15), K=200 20 ms.
    # Image size NOT measured for Spring Boot (exp11: 27-32 MB for a light handler): 90 MB assumed.
    "java": dict(A=2510, B=370, C=12, r=650, R={0: 370, 1: 252, 50: 63, 200: 20}, m=512, s=90),
    # CPython: no JIT to capture; restore time and 20 MB image are assumptions (dagsim.PY).
    "py": dict(A=400, B=15, C=20, r=60, R={0: 5}, m=256, s=20),
    # ML stage (dagsim.PYML, assumed): model weights are resident, so the image ~ its memory.
    "ml": dict(A=1800, B=40, C=300, r=180, R={0: 20}, m=1024, s=1024),
}


def options(kind, n_cold_day):
    """Theorem 7 options for one stage: (p, w, cost $/month, label). The cost folds the
    GB-seconds spent per cold invocation (additive over stages, Theorem 2) and the image's
    monthly storage into one additive number, so Corollary 7.3's DP applies as is."""
    f = FN[kind]
    per_month = n_cold_day * 30
    gb = f["m"] / 1024
    out = [(f["A"], f["B"] + f["C"], per_month * GBS * gb * (f["A"] + f["B"] + f["C"]) / 1000, "cold")]
    for tier in ("local", "remote"):
        p = f["r"] + (f["s"] / REMOTE_MBPS * 1000 if tier == "remote" else 0.0)
        for K, R in f["R"].items():
            w = R + f["C"]
            cost = per_month * GBS * gb * (p + w) / 1000 + f["s"] / 1024 * STORE[tier]
            out.append((p, w, cost, f"{tier}:K{K}"))
    return out


# ------------------------------------------------------------------ e6a
def e6a():
    rows = []
    for kind, f in FN.items():
        gb = f["m"] / 1024
        cold = gb * (f["A"] + f["B"] + f["C"]) / 1000
        Kmax = max(f["R"])
        for tier in ("local", "remote"):
            p = f["r"] + (f["s"] / REMOTE_MBPS * 1000 if tier == "remote" else 0.0)
            rest = gb * (p + f["R"][Kmax] + f["C"]) / 1000
            save = (cold - rest) * GBS
            store = f["s"] / 1024 * STORE[tier]
            be = store / save / 30 if save > 0 else math.inf
            rows.append((kind, tier, f["A"] + f["B"] + f["C"], p + f["R"][Kmax] + f["C"], cold, rest,
                         save * 1e6, store, be))
    print("e6a: one cold start vs one restore (deepest snapshot), per function")
    print(f"   {'fn':5s} {'tier':6s} {'cold ms':>8s} {'rest ms':>8s} {'cold GB-s':>9s} {'rest GB-s':>9s} "
          f"{'saves u$':>9s} {'image $/mo':>10s} {'break-even cold/day':>20s}")
    for r in rows:
        be = "never" if math.isinf(r[8]) else f"{r[8]:.1f}"
        print(f"   {r[0]:5s} {r[1]:6s} {r[2]:8.0f} {r[3]:8.0f} {r[4]:9.3f} {r[5]:9.3f} {r[6]:9.2f} "
              f"{r[7]:10.4f} {be:>20s}")
    print(f"   max cold invocations/day any workflow can have at TTL {TTL_S:.0f}s (Corollary 7.3, "
          f"lambda = 1/T): {86400 / (math.e * TTL_S):.0f}")
    with open(os.path.join(HERE, "results", "e6a_cost_functions.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fn", "tier", "cold_ms", "restore_ms", "cold_GBs", "restore_GBs", "saving_micro_usd",
                    "image_usd_month", "breakeven_cold_per_day"])
        w.writerows(rows)
    return rows


# ------------------------------------------------------------------ e6b
def build(spec):
    """spec: nested ("ser"|"par", [children]) or a function kind; returns (tree, kinds) with
    leaves numbered in DFS order (the order expand() numbers nodes in)."""
    kinds = []

    def go(x):
        if isinstance(x, str):
            kinds.append(x)
            return ("leaf", len(kinds) - 1)
        op, ch = x
        t = go(ch[0])
        for c in ch[1:]:
            t = (op, t, go(c))
        return t
    return go(spec), kinds


WORKFLOWS = {
    "java-chain-5": ("ser", ["java"] * 5),
    "ml-pipeline": ("ser", ["py", "ml", "java", "java", "py"]),          # dagsim's ml template
    "fan-out-4": ("ser", ["java", ("par", ["java"] * 4), "java", "py"]),
    "mixed-order": ("ser", ["py", ("par", ["java", "py"]), "java", "py"]),
}
DELTA = 2.0


def evaluate(tree, kinds, opts, choice, sched=jit):
    """(latency, $/month, peak memory MB) of a choice; sched = jit (look-ahead) or on_demand."""
    pw = [(opts[i][choice[i]][0], opts[i][choice[i]][1]) for i in range(len(kinds))]
    W, P = rules(tree, pw, DELTA)
    g = expand(tree, pw, DELTA)
    g.m = [FN[k]["m"] for k in kinds]
    L, _, tau, _, F = sched(g)
    assert sched is not jit or abs(L - max(W, P)) < 1e-6          # Theorem 7(a) cross-check
    assert sched is not on_demand or abs(L - rules_od(tree, pw, DELTA)) < 1e-6
    cost = sum(opts[i][choice[i]][2] for i in range(len(kinds)))
    return L, cost, peak_mem(g, tau, F)


def e6b():
    rows = []
    print("e6b: per workflow; latency under look-ahead (Theorem 7), $/month = GB-s of cold "
          "invocations + image storage")
    for name, spec in WORKFLOWS.items():
        tree, kinds = build(spec)
        for n_day in (1, 10, 50):
            opts = [options(k, n_day) for k in kinds]
            labels = lambda ch: " ".join(opts[i][ch[i]][3] for i in range(len(kinds)))
            none = [0] * len(kinds)
            deep_local = [max(range(len(o)), key=lambda j: (o[j][3].startswith("local"), -o[j][1]))
                          for o in opts]
            front = pareto_front(tree, [[o[:3] for o in op] for op in opts], DELTA)   # (cost, L) front
            fastest = min(front, key=lambda it: (it[1], it[0]))
            cheapest = min(front, key=lambda it: (it[0], it[1]))
            pts = {"none (cold, look-ahead prewarm)": none, "snapshot every stage (deepest, local)": deep_local,
                   "fastest, cheapest such (Thm 7)": [fastest[2][i] for i in range(len(kinds))],
                   "cheapest overall (Cor 7.3, mu=0)": [cheapest[2][i] for i in range(len(kinds))]}
            for label, ch in pts.items():
                L, cost, peak = evaluate(tree, kinds, opts, ch)
                nsnap = sum(1 for i in range(len(kinds)) if opts[i][ch[i]][3] != "cold")
                rows.append((name, n_day, label, L, cost, nsnap, len(kinds), peak, labels(ch)))
            L_today, c_today, pk_today = evaluate(tree, kinds, opts, deep_local, sched=on_demand)
            rows.append((name, n_day, "today: every stage, restore on demand", L_today, c_today,
                         len(kinds), len(kinds), pk_today, labels(deep_local)))
    cur = None
    for r in rows:
        if (r[0], r[1]) != cur:
            cur = (r[0], r[1])
            print(f"   {r[0]}  ({r[1]} cold invocations/day)")
        print(f"      {r[2]:40s} L {r[3] / 1000:5.2f}s  ${r[4]:7.4f}/mo  snapshots {r[5]}/{r[6]}  "
              f"peak {r[7] / 1024:4.1f} GB   [{r[8]}]")
    with open(os.path.join(HERE, "results", "e6b_cost_workflows.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["workflow", "cold_per_day", "choice", "latency_ms", "usd_month", "snapshots", "stages",
                    "peak_mem_MB", "per_stage"])
        w.writerows(rows)
    return rows


# ------------------------------------------------------------------ e6c
def e6c(fa):
    path = os.path.join(HERE, "data", "azure2021_entry_arrivals_3d.csv.gz")
    last, cold, n = {}, {}, {}
    with gzip.open(path, "rt") as f:
        next(f)
        for line in f:
            t, a = line.split(",")
            t, a = float(t), int(a)
            n[a] = n.get(a, 0) + 1
            if a not in last or t - last[a] > TTL_S:
                cold[a] = cold.get(a, 0) + 1
            last[a] = t
    per_day = sorted(cold[a] / 3.0 for a in n)
    print(f"e6c: Azure 2021, {len(per_day)} workflows, cold invocations/day at TTL {TTL_S:.0f}s: "
          f"median {per_day[len(per_day) // 2]:.1f}, max {per_day[-1]:.1f}")
    rows = []
    for kind, tier, *_, be in fa:
        k = sum(1 for x in per_day if x >= be)
        rows.append((kind, tier, be, k, len(per_day)))
        print(f"   {kind:5s} image in {tier:6s} pays for itself (>= {be if not math.isinf(be) else float('inf'):.1f}/day) "
              f"in {k}/{len(per_day)} workflows")
    with open(os.path.join(HERE, "results", "e6c_cost_trace.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["fn", "tier", "breakeven_cold_per_day", "workflows_above", "workflows"])
        w.writerows(rows)
        w.writerow([])
        w.writerow(["cold_per_day_sorted"] + [f"{x:.3f}" for x in per_day])
    return rows


def main():
    fa = e6a()
    e6b()
    e6c(fa)


if __name__ == "__main__":
    main()
