#!/usr/bin/env python3
"""Grid summary (raw/grid.jsonl, raw/images.jsonl) -> T3, T4, T6 tables. Engine: Warp (CRaC default).

Definitions (MACHINE_TEST_PLAN.md T3), per vCPU v:
  C(v)      steady latency: median over cont_K200 runs of the median of requests 150-200 (the most
            warmed process never checkpointed; the floor)
  A         cold start to Spring ready (spring_ms of the cold runs)
  ttfr      launch -> first response (cold: includes A; restore: r_wall + first request)
  first     the first request's own latency
  R         sum over the first request and the 200 later requests of max(0, latency - C(v))
            (cold: this is B; restore at depth K: R(K); cont_K: the never-checkpointed floor)
  s(K)      image size (images.jsonl), compile_ms / code cache at the checkpoint
Bootstrap 95% CI of medians, 10,000 resamples.

Outputs: profile_table.csv (T3), t4_rewarm.csv (T4), ../T6-cliff/cliff.csv (T6)."""
import csv
import json
import os
import random
import statistics as st

HERE = os.path.dirname(os.path.abspath(__file__))
rnd = random.Random(1)
B = 10_000
g = [json.loads(l) for l in open(os.path.join(HERE, "raw", "grid.jsonl"))]
imgs = [json.loads(l) for l in open(os.path.join(HERE, "raw", "images.jsonl"))]
ok = [r for r in g if r.get("ttfr_ms") is not None and len(r["curve_ms"]) >= 200]
failed = [r for r in g if r.get("ttfr_ms") is None]


def med(x):
    return st.median(x)


def ci(x):
    b = sorted(med(rnd.choices(x, k=len(x))) for _ in range(B))
    return b[int(.025 * B)], b[int(.975 * B)]


def write(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


V = sorted({r["vcpu"] for r in ok})
C = {v: med([med(r["curve_ms"][150:200]) for r in ok if r["vcpu"] == v and r["mode"] == "cont_K200"]) for v in V}


def R(r):
    return max(0.0, r["first_after_restore_ms"] - C[r["vcpu"]]) + sum(max(0.0, x - C[r["vcpu"]]) for x in r["curve_ms"])


def cell(v, m):
    return [r for r in ok if r["vcpu"] == v and r["mode"] == m]


def size(K):
    xs = [i for i in imgs if i.get("kind") == "depth" and i["K"] == K and i["ok"]]
    return (med([i["bytes"] / 2 ** 20 for i in xs]), med([i["compile_ms_ckpt"] for i in xs]),
            med([i["codecache_ckpt"] / 2 ** 20 for i in xs])) if xs else (None,) * 3


prof = []
modes = ["cold", "cold_np"] + [f"restore_K{K}" for K in (0, 1, 5, 20, 50, 100, 200)] + \
        [f"cont_K{K}" for K in (0, 50, 200)] + ["rewarm_K50", "disk_K50"]
for v in V:
    for m in modes:
        xs = cell(v, m)
        if not xs:
            continue
        t, rr = [r["ttfr_ms"] for r in xs], [R(r) for r in xs]
        K = int(m.split("_K")[1]) if "_K" in m else ""
        s_mb, comp, cc = size(K) if m.startswith("restore_K") else ("", "", "")
        tl, th = ci(t)
        rl, rh = ci(rr)
        prof.append(dict(engine="warp", vcpu=v, mode=m, K=K, n=len(xs),
                         ttfr_ms=round(med(t), 1), ttfr_lo=round(tl, 1), ttfr_hi=round(th, 1),
                         ttfr_p95_ms=round(sorted(t)[int(round(.95 * (len(t) - 1)))], 1),
                         first_ms=round(med([r["first_after_restore_ms"] for r in xs]), 1),
                         R_ms=round(med(rr), 1), R_lo=round(rl, 1), R_hi=round(rh, 1),
                         C_ms=round(C[v], 3), A_ms=round(med([r["spring_ms"] for r in xs]), 0) if m.startswith(("cold", "cont")) else "",
                         cpu_s=round(med([r["cpu_s"] for r in xs]), 2),
                         s_MB=round(s_mb, 1) if s_mb else "", compile_ms_ckpt=comp, codecache_MB_ckpt=round(cc, 2) if cc else ""))
write(os.path.join(HERE, "profile_table.csv"), prof)

# ---- T4: L(K) = R_restored - R_continued; re-warm recovery (K = 50; and K = 0, 200 without re-warm)
t4 = []
for v in V:
    for K in (0, 50, 200):
        rest, cont = [R(r) for r in cell(v, f"restore_K{K}")], [R(r) for r in cell(v, f"cont_K{K}")]
        if not rest or not cont:
            continue
        rw = [R(r) for r in cell(v, "rewarm_K50")] if K == 50 else []
        L = med(rest) - med(cont)
        bs = sorted(med(rnd.choices(rest, k=len(rest))) - med(rnd.choices(cont, k=len(cont))) for _ in range(B))
        row = dict(vcpu=v, K=K, R_restored_ms=round(med(rest), 1), R_continued_ms=round(med(cont), 1),
                   L_ms=round(L, 1), L_lo=round(bs[int(.025 * B)], 1), L_hi=round(bs[int(.975 * B)], 1),
                   R_rewarm_ms=round(med(rw), 1) if rw else "",
                   recovered_pct=round(100 * (med(rest) - med(rw)) / L, 0) if rw and L > 0 else "",
                   rewarm_wall_ms=round(med([r["rewarm_ms"] for r in cell(v, "rewarm_K50") if r.get("rewarm_ms")]), 0) if rw else "")
        t4.append(row)
write(os.path.join(HERE, "t4_rewarm.csv"), t4)

# ---- T6: the cliff, cold vs restored (B or R at each vCPU, ratio to 4 vCPU)
cl = []
top = max(V)
for m in ("cold", "restore_K0", "restore_K50", "restore_K200", "cont_K200"):
    ref = med([R(r) for r in cell(top, m)]) if cell(top, m) else None
    reft = med([r["ttfr_ms"] for r in cell(top, m)]) if cell(top, m) else None
    for v in V:
        xs = cell(v, m)
        if xs:
            cl.append(dict(mode=m, vcpu=v, n=len(xs), R_ms=round(med([R(r) for r in xs]), 1),
                           R_ratio_to_4=round(med([R(r) for r in xs]) / ref, 2) if ref else "",
                           ttfr_ms=round(med([r["ttfr_ms"] for r in xs]), 1),
                           ttfr_ratio_to_4=round(med([r["ttfr_ms"] for r in xs]) / reft, 2) if reft else "",
                           C_ms=round(C[v], 3)))
os.makedirs(os.path.join(HERE, "..", "T6-cliff"), exist_ok=True)
write(os.path.join(HERE, "..", "T6-cliff", "cliff.csv"), cl)

print("runs", len(g), "ok", len(ok), "failed", len(failed))
print("cgroups", {r.get("cgroup") for r in g})
print("C(v)", {v: round(c, 3) for v, c in C.items()})
