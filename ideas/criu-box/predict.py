#!/usr/bin/env python3
"""Predictions for the machine tests (MACHINE_TEST_PLAN.md), computed from a function profile.

Run it BEFORE each test with the profile measured so far, and commit its output next to the
test's results: the prediction is written down before the measurement (RESEARCH_PLAN.md §9).

  python3 ideas/criu-box/predict.py                                  # thesis defaults, 1 vCPU
  python3 ideas/criu-box/predict.py --profile results/box/profile_vcpu1.0.json --out pred.json

Profile format: ideas/criu-box/profile_thesis.json (ms and MB; w = RK + C per function).
Every number comes from the theory's closed forms or its reference code (theory/verify_dag.py):
chains (Theorem 1, Corollaries 1.1-1.2), peak memory and k slots (Theorem 8), restore channels
(ALGORITHM.md Corollary A3), the capped planner example (ALGORITHM.md §5), keep-alive (Theorem 6).
"""
import argparse
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "theory"))
import verify_dag as vd  # noqa: E402


def chain_dag(d, f, delta):
    return vd.DAG(d, [[]] + [[v - 1] for v in range(1, d)], [f["r"]] * d, [f["w"]] * d, [f["m"]] * d, delta)


def channels(d, r, w, delta, c):
    """Corollary A3: tau_v = max(tau_{v-1} + w + delta, tau_{v-c} + r); latency of the last stage."""
    tau = []
    for v in range(d):
        t = 0.0 if v == 0 else tau[v - 1] + w + delta
        if v >= c:
            t = max(t, tau[v - c] + r)
        tau.append(t)
    return tau[-1] + r + w


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=os.path.join(HERE, "profile_thesis.json"))
    ap.add_argument("--fn", default="java", help="function used for the chain predictions")
    ap.add_argument("--out", help="also write every prediction to this JSON file")
    a = ap.parse_args()
    P = json.load(open(a.profile))
    delta, beta = float(P.get("delta_ms", 2.0)), float(P.get("beta", 0.0))
    F = {k: dict(v, w=v["RK"] + v["C"]) for k, v in P["functions"].items()}
    f = F[a.fn]
    r, w, m = f["r"], f["w"], f["m"]
    out = {"profile": a.profile, "vcpu": P.get("vcpu"), "delta_ms": delta, "beta": beta, "fn": a.fn}
    print(f"# Predictions from {os.path.relpath(a.profile, REPO)} (vCPU {P.get('vcpu')}, delta {delta} ms, "
          f"beta {beta})\n")
    print(f"Chain function `{a.fn}`: r = {r:.0f} ms, w = RK + C = {w:.0f} ms, m = {m:.0f} MB.\n")

    # T8: chains, the cascade (Theorem 1c, Corollary 1.1), contention bound (Corollary 1.2), memory (Theorem 8a)
    c_eff = max(1, math.floor(1 / beta)) if beta > 0 else None
    print("## T8. Chains: latency and memory per policy\n")
    print("| d | on demand (ms) | look-ahead, beta=0 (ms) | look-ahead bound at beta (ms) "
          + ("| look-ahead, c=%d channels (ms) " % c_eff if c_eff else "")
          + "| peak MB od / JIT / eager | memory-time GB·s od = JIT / eager |")
    print("|---|---|---|---|" + ("---|" if c_eff else "") + "---|---|")
    rows = []
    for d in range(1, 9):
        g = chain_dag(d, f, delta)
        Lod, Mod, _, _, _ = vd.on_demand(g)
        Lj, Mj, tj, _, Fj = vd.jit(g)
        Le, Me, te, _, Fe = vd.eager(g)
        bound = Lod - (1 - beta) * (d - 1) * r
        pk_od = m
        pk_j = vd.peak_mem(g, tj, Fj)
        pk_e = vd.peak_mem(g, te, Fe)
        row = dict(d=d, on_demand_ms=Lod, lookahead_ms=Lj, lookahead_bound_ms=bound, peak_od_MB=pk_od,
                   peak_jit_MB=pk_j, peak_eager_MB=pk_e, memtime_od_GBs=Mod / 1e6,
                   memtime_jit_GBs=Mj / 1e6, memtime_eager_GBs=Me / 1e6)
        if c_eff:
            row["lookahead_channels_ms"] = channels(d, r, w, delta, c_eff)
        rows.append(row)
        print(f"| {d} | {Lod:.0f} | {Lj:.0f} | {bound:.0f} |"
              + (f" {row['lookahead_channels_ms']:.0f} |" if c_eff else "")
              + f" {pk_od:.0f} / {pk_j:.0f} / {pk_e:.0f} | {Mod / 1e6:.2f} / {Me / 1e6:.2f} |")
    out["chains"] = rows
    print(f"\nSlopes per extra stage: on demand r + w + delta = **{r + w + delta:.0f} ms**; "
          f"look-ahead w + delta = **{w + delta:.0f} ms**. JIT peak = m·min(d, ceil((r+w)/(w+delta))) = "
          f"m·min(d, {math.ceil((r + w) / (w + delta))}).")
    if c_eff:
        print(f"Contention: beta = {beta} behaves roughly like c = floor(1/beta) = {c_eff} restores at a time.")
    out["slope_on_demand_ms"], out["slope_lookahead_ms"] = r + w + delta, w + delta

    # T9: k memory slots on an 8-stage chain (Theorem 8b)
    print("\n## T9. 8-stage chain with a memory budget of k sandboxes (Theorem 8(b))\n")
    print("| k (budget = k·m) | " + " | ".join(str(k) for k in range(1, 9)) + " |")
    print("|---|" + "---|" * 8)
    slots = {k: vd.chain_slots_rec(8, r, w, delta, k) for k in range(1, 9)}
    print("| latency (ms) | " + " | ".join(f"{slots[k]:.0f}" for k in range(1, 9)) + " |")
    out["slots_d8_ms"] = slots

    # restore channels on a 5-stage chain (Corollary A3): what x2's measured parallelism means
    print("\n## T1 -> T8. 5-stage chain with c restores at a time (ALGORITHM.md Corollary A3)\n")
    ch = {c: channels(5, r, w, delta, c) for c in range(1, 6)}
    print("| c | " + " | ".join(str(c) for c in ch) + " |")
    print("|---|" + "---|" * len(ch))
    print("| latency (ms) | " + " | ".join(f"{ch[c]:.0f}" for c in ch) + " |")
    print(f"\n(On demand: {rows[4]['on_demand_ms']:.0f} ms. One channel is x2's 'fully serial' case.)")
    out["channels_d5_ms"] = ch

    # T10: the planner example (ALGORITHM.md §5): python entry -> java -> java, and entry -> py-ml; cap = largest m
    if all(k in F for k in ("python", "java", "py-ml")):
        p, j, ml = F["python"], F["java"], F["py-ml"]
        g = vd.DAG(4, [[], [0], [1], [0]], [p["r"], j["r"], j["r"], ml["r"]], [p["w"], j["w"], j["w"], ml["w"]],
                   [p["m"], j["m"], j["m"], ml["m"]], delta)
        cap = max(g.m)
        Lj, _, tj, _, Fj = vd.jit(g)
        Lx, tx, _ = vd.exact_capped(g, cap)
        res = dict(cap_MB=cap, no_cap_ms=Lj, no_cap_peak_MB=vd.peak_mem(g, tj, Fj),
                   guard_ms=vd.capped(g, cap)[0], capped_on_demand_ms=vd.capped(g, cap, lookahead=False)[0],
                   plan_ms=Lx, plan_triggers_ms=tx)
        out["planner_example"] = res
        print(f"\n## T10. Planner example: python entry -> java -> java, entry -> py-ml; cap {cap:.0f} MB\n")
        print("| no cap (peak) | memory guard | capped on demand | exact plan | plan's triggers (entry, java1, java2, ml) |")
        print("|---|---|---|---|---|")
        print(f"| {res['no_cap_ms']:.0f} ms ({res['no_cap_peak_MB']:.0f} MB) | {res['guard_ms']:.0f} ms | "
              f"{res['capped_on_demand_ms']:.0f} ms | **{Lx:.0f} ms** | {', '.join(f'{t:.0f}' for t in tx)} |")

    # T13 context: keep-alive vs look-ahead memory (Theorem 6), 3-stage chain of `fn`
    d = 3
    g = chain_dag(d, f, delta)
    L_star = vd.L_star(g)
    L_cold = d * (f["A"] + f["B"] + f["C"]) + (d - 1) * delta
    L_warm = d * f["C"] + (d - 1) * delta
    eps = (L_star - L_warm) / (L_cold - L_warm)
    lam = (1 - eps) / ((r + w) / 1000)
    out["keepalive"] = dict(L_cold_ms=L_cold, L_warm_ms=L_warm, L_star_ms=L_star, eps=eps, crossover_per_s=lam)
    print(f"\n## Keep-alive vs look-ahead (Theorem 6), 3-stage chain\n\ncold {L_cold:.0f} ms, warm {L_warm:.0f} ms, "
          f"look-ahead {L_star:.0f} ms, eps = {eps:.3f}. Keep-alive needs more memory than look-ahead below "
          f"**{lam:.2f} invocations/s**; at one per minute it needs {(1 - eps) / (1 / 60 * (r + w) / 1000):.0f}x more.")

    if a.out:
        json.dump(out, open(a.out, "w"), indent=1, default=float)
        print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
