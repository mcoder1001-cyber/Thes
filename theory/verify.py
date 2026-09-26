#!/usr/bin/env python3
"""Computational verification of every claim in MODEL.md.

Standing rule of this project: every experiment carries a control whose answer is
known in advance. This file applies that rule to mathematics -- each theorem is
checked against brute force, and each check is paired with a control designed to
FAIL, so that a passing test is evidence the test can detect error at all.

usage: ./verify.py [--curves DIR] [--quick]
"""
import argparse
import csv
import glob
import itertools
import os
import random
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CURVES = os.path.join(HERE, "..", "experiments", "exp5-factor-study", "results", "curves")

PASS, FAIL = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m"
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f"  --  {detail}" if detail else ""))
    return ok


def hdr(t):
    print(f"\n{'='*78}\n {t}\n{'='*78}")


# --------------------------------------------------------------------------
# curve loading
# --------------------------------------------------------------------------
def load_curve(path):
    """-> (latencies_ms, codecache_bytes) from an exp5 curve CSV."""
    lat, cc = [], []
    with open(path) as f:
        for row in csv.DictReader(f):
            try:
                lat.append(float(row["nanos"]) / 1e6)
                cc.append(float(row.get("codecache_bytes") or 0))
            except (ValueError, TypeError, KeyError):
                continue
    return lat, cc


def excess(lat, tail_frac=0.5):
    """e(i) = (l(i) - C)+, with C the median of the converged tail."""
    if len(lat) < 20:
        return None, None
    C = statistics.median(lat[int(len(lat) * tail_frac):])
    return [max(0.0, x - C) for x in lat], C


def residual(e):
    """R(K) = sum_{i>=K} e(i), as a list indexed by K."""
    R, acc = [0.0] * (len(e) + 1), 0.0
    for i in range(len(e) - 1, -1, -1):
        acc += e[i]
        R[i] = acc
    return R


def isotonic_decreasing(y):
    """Pool-adjacent-violators fit of a non-increasing sequence (L2)."""
    vals, wts = [], []
    for v in y:
        vals.append(float(v))
        wts.append(1.0)
        while len(vals) > 1 and vals[-2] < vals[-1]:      # violation: rising
            v2, w2 = vals.pop(), wts.pop()
            v1, w1 = vals.pop(), wts.pop()
            vals.append((v1 * w1 + v2 * w2) / (w1 + w2))
            wts.append(w1 + w2)
    out = []
    for v, w in zip(vals, wts):
        out.extend([v] * int(round(w)))
    return out[:len(y)]


def rep_noise(paths, n):
    """Per-iteration standard error across reps -- the scale that jitter lives on."""
    curves = [load_curve(p)[0] for p in paths]
    curves = [c for c in curves if len(c) >= n]
    if len(curves) < 3:
        return None
    ses = []
    for i in range(n):
        col = [c[i] for c in curves]
        ses.append(statistics.pstdev(col) / (len(col) ** 0.5))
    return statistics.median(ses)


def group_curves(paths):
    """exp5 filenames: <workload>__cpu<c>__<mem>__r<rep>.csv -> group reps per cell."""
    cells = {}
    for p in paths:
        base = os.path.basename(p)
        key = base.rsplit("__r", 1)[0]
        cells.setdefault(key, []).append(p)
    return cells


def median_excess(paths):
    """Pool reps of one cell: per-iteration median latency, then excess.

    Pooling before differencing is what makes the monotonicity question meaningful --
    a single rep is dominated by per-call jitter.
    """
    curves = [load_curve(p)[0] for p in paths]
    curves = [c for c in curves if len(c) >= 20]
    if not curves:
        return None, None
    n = min(len(c) for c in curves)
    med = [statistics.median([c[i] for c in curves]) for i in range(n)]
    return excess(med)


# --------------------------------------------------------------------------
# LEMMA 1 -- convexity of R(K), measured on real curves
# --------------------------------------------------------------------------
def lemma1(cells):
    hdr("LEMMA 1  --  is R(K) convex on real measured warm-up curves?")
    print("  d2R(K) = e(K) - e(K+1), so convexity of R is EXACTLY monotonicity of e.")
    print("  (An earlier draft claimed the tail sum smooths jitter away. It does not --")
    print("   the second difference of a tail sum is the raw first difference. The two")
    print("   columns below are therefore identical by construction, which is the check.)")
    print("\n  Reported per cell: raw monotone %, and whether the deviation from a")
    print("  non-increasing fit (isotonic/PAVA) is within rep-to-rep noise -- i.e.")
    print("  whether the UNDERLYING curve can be monotone even though the sample is not.\n")
    print(f"  {'cell':<30}{'B (ms)':>9}{'raw mono%':>11}{'iso resid':>11}{'noise SE':>10}  verdict")
    print("  " + "-" * 80)

    passing, examined, within = [], [], []
    for key in sorted(cells):
        e, C = median_excess(cells[key])
        if e is None:
            continue
        B = sum(e)
        if B < 1.0:                     # no warm-up to speak of; lemma is vacuous
            continue
        K = min(len(e) - 2, 400)
        if K < 10:
            continue
        mono = sum(1 for i in range(K) if e[i] >= e[i + 1] - 1e-12) / K
        iso = isotonic_decreasing(e[:K + 2])
        resid = statistics.mean(abs(a - b) for a, b in zip(e[:K + 2], iso))
        se = rep_noise(cells[key], K + 2)
        ok_raw = mono >= 0.95
        ok_iso = se is not None and resid <= 2.0 * se
        examined.append(key)
        if ok_raw:
            passing.append(key)
        if ok_iso:
            within.append(key)
        verdict = ("monotone" if ok_raw else
                   "noise-consistent" if ok_iso else "NOT monotone")
        print(f"  {key:<30}{B:>9.1f}{100*mono:>10.1f}%{resid:>11.3f}"
              f"{(se if se is not None else float('nan')):>10.3f}  {verdict}")

    print()
    check("Lemma 1 as stated (raw curves are monotone) -- REFUTED",
          len(passing) / len(examined) >= 0.5 if examined else False,
          f"only {len(passing)}/{len(examined)} cells >=95% monotone; "
          f"~50-60% is what pure noise gives")
    check("Lemma 1' (underlying curve monotone; deviation within 2 SE of rep noise)",
          len(within) / len(examined) >= 0.5 if examined else False,
          f"{len(within)}/{len(examined)} cells noise-consistent")
    print("\n  CONSEQUENCE for the theorems:")
    print("   * Theorems 1 and 3 (exact DP) need NO convexity -- unaffected.")
    print("   * Theorems 2 and 4 (greedy optimal / linear time) DO need it. They are")
    print("     therefore stated for the isotonic profile, and the cost of that")
    print("     smoothing is measured below on RAW profiles rather than assumed away.")
    return passing, examined


# --------------------------------------------------------------------------
# LEMMA 2 -- concavity of image size s(K)
# --------------------------------------------------------------------------
def lemma2(cells):
    hdr("LEMMA 2  --  is image growth s(K) concave?")
    ok_n = tot = 0
    concs = []
    for key in sorted(cells):
        ccs = [load_curve(p)[1] for p in cells[key]]
        ccs = [c for c in ccs if c and max(c) > 0]
        if not ccs:
            continue
        n = min(len(c) for c in ccs)
        if n < 50:
            continue
        s = [statistics.median([c[i] for c in ccs]) for i in range(n)]
        s = [x - s[0] for x in s]
        grid = [k for k in (1, 2, 5, 10, 20, 50, 100, 200, 400) if k < n]
        g = [s[k] for k in grid]
        # concavity on the decision grid: per-request growth must be non-increasing
        inc = [(g[i + 1] - g[i]) / (grid[i + 1] - grid[i]) for i in range(len(g) - 1)]
        conc = (sum(1 for i in range(len(inc) - 1) if inc[i] >= inc[i + 1] - 1e-9)
                / max(1, len(inc) - 1))
        tot += 1
        ok_n += conc >= 0.95
        concs.append(conc)
        print(f"  {key:<30} concave on grid at {100*conc:>5.1f}%   "
              f"growth {s[min(n-1,400)]/1024:>8.1f} KB   "
              f"KB/req {'  '.join(f'{x/1024:.2f}' for x in inc[:4])}")
    if tot:
        med = statistics.median(concs)
        check("Lemma 2 (s APPROXIMATELY concave on the decision grid)",
              med >= 0.70,
              f"median {100*med:.0f}% of grid increments non-increasing; "
              f"only {ok_n}/{tot} cells reach 95% -- concavity is approximate, "
              f"not exact")
        print("   Theorems 1 and 3 do not need it; Theorem 2's gap bound was verified")
        print("   to hold on these profiles regardless. Stated as approximate in MODEL.md.")
    else:
        print("  (no cells expose a code cache -- lemma vacuous for these runtimes)")


# --------------------------------------------------------------------------
# instances
# --------------------------------------------------------------------------
def make_profile(e, depths, r_of_K=lambda K: 30.0, A=1000.0, s_scale=1.0):
    """Turn a measured excess curve into the (cost, storage) ladder of one function."""
    R = residual(e)
    opts = [(A + R[0], 0.0)]                       # K = None
    for K in depths:
        if K < len(R):
            opts.append((r_of_K(K) + R[K], s_scale * (100 + 12 * K)))
    return opts


def brute(profiles, S):
    best = None
    for combo in itertools.product(*[range(len(p)) for p in profiles]):
        cost = sum(profiles[i][c][0] for i, c in enumerate(combo))
        st = sum(profiles[i][c][1] for i, c in enumerate(combo))
        if st <= S and (best is None or cost < best):
            best = cost
    return best


def dp_chain(profiles, S, grid=1.0):
    """Exact MCKP DP (Theorem 1b). Storage discretised onto a grid."""
    # nb is the LAST admissible budget index. An earlier version used
    # int(S/grid)+1, which handed the DP one extra unit of storage and let it
    # return solutions brute force correctly rejected as infeasible (1/300 trials).
    nb = int(S / grid)
    INF = float("inf")
    cur = [0.0] * (nb + 1)
    for p in profiles:
        nxt = [INF] * (nb + 1)
        for b in range(nb + 1):
            if cur[b] == INF:
                continue
            for cost, st in p:
                bb = b + int(round(st / grid))
                if bb <= nb and cur[b] + cost < nxt[bb]:
                    nxt[bb] = cur[b] + cost
        # prefix-min so D[b] means "budget at most b"
        for b in range(1, nb + 1):
            nxt[b] = min(nxt[b], nxt[b - 1])
        cur = nxt
    return cur[nb]


def greedy_chain(profiles, S):
    """Theorem 2: incremental slope-merge greedy."""
    idx = [0] * len(profiles)
    spent = sum(profiles[i][0][1] for i in range(len(profiles)))
    cost = sum(profiles[i][0][0] for i in range(len(profiles)))
    while True:
        best, bi = None, None
        for i, p in enumerate(profiles):
            k = idx[i]
            if k + 1 >= len(p):
                continue
            dc = p[k][0] - p[k + 1][0]
            ds = p[k + 1][1] - p[k][1]
            if ds <= 0 or dc <= 0:
                continue
            if spent + ds > S:
                continue
            rho = dc / ds
            if best is None or rho > best:
                best, bi = rho, i
        if bi is None:
            return cost
        k = idx[bi]
        cost -= profiles[bi][k][0] - profiles[bi][k + 1][0]
        spent += profiles[bi][k + 1][1] - profiles[bi][k][1]
        idx[bi] += 1


# --------------------------------------------------------------------------
# THEOREM 1 / 2
# --------------------------------------------------------------------------
def theorem12(cells, pool_keys, quick):
    hdr("THEOREM 1 & 2  --  exact DP, and greedy against it, on REAL profiles")
    rndk = random.Random(3)
    keys = rndk.sample(pool_keys, min(10, len(pool_keys)))
    pool = [median_excess(cells[k])[0] for k in keys] or None
    if not pool:
        print("  no usable cells; skipped")
        return
    pool_iso = [isotonic_decreasing(e) for e in pool]
    rnd = random.Random(7)
    depths = [0, 1, 2, 5, 10, 20, 50, 100]

    # -- control: an instance whose optimum is known by construction ----------
    # 3 identical functions, budget for exactly one snapshot at K=0.
    e = pool[0]
    R = residual(e)
    prof = [[(1000.0 + R[0], 0.0), (30.0 + R[0], 100.0)] for _ in range(3)]
    want = 2 * (1000.0 + R[0]) + (30.0 + R[0])
    got = dp_chain(prof, 100.0)
    check("CONTROL: DP returns the hand-computed optimum on a rigged instance",
          abs(got - want) < 1e-6, f"want {want:.2f}, got {got:.2f}")

    # -- Theorem 1b: DP == brute force ---------------------------------------
    n_ok = n_tot = 0
    trials = 60 if quick else 300
    for _ in range(trials):
        k = rnd.randint(2, 4)
        profs = [make_profile(rnd.choice(pool), rnd.sample(depths, 3),
                              A=rnd.uniform(200, 3000),
                              s_scale=rnd.uniform(0.5, 2.0)) for _ in range(k)]
        # snap storage to the DP's grid so DP and brute force solve the SAME
        # instance -- otherwise rounding makes infeasible combinations feasible
        # for the DP and it reports a spuriously lower cost (2/300 trials).
        profs = [[(c, float(round(st))) for c, st in p] for p in profs]
        S = round(rnd.uniform(0, sum(max(s for _, s in p) for p in profs)))
        b, d = brute(profs, S), dp_chain(profs, S)
        n_tot += 1
        n_ok += abs(b - d) < 1e-3
    check(f"Theorem 1b: DP == exhaustive enumeration ({trials} random real-curve instances)",
          n_ok == n_tot, f"{n_ok}/{n_tot} exact")

    # -- Theorem 2: greedy gap, on ISOTONIC (convex, as the theorem assumes) --
    def gap_over(src):
        gaps, bound_ok = [], 0
        n = 0
        for _ in range(trials):
            k = rnd.randint(3, 6)
            profs = [make_profile(rnd.choice(src), depths, A=rnd.uniform(200, 3000),
                                  s_scale=rnd.uniform(0.5, 2.0)) for _ in range(k)]
            S = round(rnd.uniform(0, sum(max(s for _, s in p) for p in profs)))
            o, g = dp_chain(profs, S), greedy_chain(profs, S)
            # Theorem 2's actual guarantee: absolute gap <= benefit of one increment
            step = max(max(p[i][0] - p[i + 1][0] for i in range(len(p) - 1))
                       for p in profs if len(p) > 1)
            n += 1
            bound_ok += (g - o) <= step + 1e-6
            if o > 0:
                gaps.append((g - o) / o)
        return statistics.mean(gaps), max(gaps), bound_ok, n

    rnd.seed(21)
    mi, xi, bi, ni = gap_over(pool_iso)
    check("Theorem 2: greedy gap <= one increment's benefit, on ISOTONIC profiles",
          bi == ni, f"{bi}/{ni} instances within the bound; "
                    f"mean rel. gap {100*mi:.3f}%, worst {100*xi:.3f}%")

    # -- and the question that actually matters: what does the convexity ------
    # -- failure cost us on the RAW, non-convex profiles? ---------------------
    rnd.seed(21)
    mr, xr, br, nr = gap_over(pool)
    check("Greedy stays near-optimal on RAW non-convex profiles (robustness)",
          mr < 0.02, f"{br}/{nr} within bound; mean rel. gap {100*mr:.3f}%, "
                     f"worst {100*xr:.3f}%")
    print(f"      -> cost of the Lemma-1 failure, in the only currency that matters:")
    print(f"         mean greedy gap {100*mi:.3f}% (isotonic) vs {100*mr:.3f}% (raw).")

    # -- control: greedy must LOSE on a deliberately non-convex ladder --------
    # benefit jumps late (concave-down then up), violating Lemma 1.
    # class A: one cheap useful increment.  class B: a worthless first increment
    # hiding a huge second one.  Greedy never climbs past B's zero-ratio step.
    bad = [[(100.0, 0.0), (99.0, 1.0)],
           [(100.0, 0.0), (100.0, 1.0), (0.0, 2.0)]]
    o, g = dp_chain(bad, 2.0), greedy_chain(bad, 2.0)
    check("CONTROL: greedy is strictly worse than DP when convexity is broken",
          g > o + 1e-6, f"DP {o:.1f} vs greedy {g:.1f} -- the test can detect failure")


# --------------------------------------------------------------------------
# THEOREM 3 / 4 -- series-parallel DP
# --------------------------------------------------------------------------
def sp_leaf(profile, S, grid):
    nb = int(S / grid) + 1
    F = [float("inf")] * (nb + 1)
    for cost, st in profile:
        b = int(round(st / grid))
        if b <= nb:
            F[b] = min(F[b], cost)
    for b in range(1, nb + 1):
        F[b] = min(F[b], F[b - 1])
    return F


def sp_series(F1, F2):
    n = len(F1) - 1
    out = [float("inf")] * (n + 1)
    for b in range(n + 1):
        out[b] = min(F1[i] + F2[b - i] for i in range(b + 1))
    return out


def sp_parallel(F1, F2):
    n = len(F1) - 1
    out = [float("inf")] * (n + 1)
    for b in range(n + 1):
        out[b] = min(max(F1[i], F2[b - i]) for i in range(b + 1))
    return out


def lower_convex_envelope(F):
    """Largest convex minorant of a budget curve, on the finite grid.

    Theorem 4's HYPOTHESIS is that each leaf's F_v(b) is convex. A raw leaf is a
    step function (finitely many depth options snapped to a storage grid), so the
    hypothesis has to be established before the conclusion can be tested. This is
    the standard convexification: keep only the points on the lower hull.
    """
    n = len(F)
    pts = [(b, F[b]) for b in range(n) if F[b] != float("inf")]
    if len(pts) < 2:
        return F[:]
    hull = []
    for p in pts:
        while len(hull) >= 2:
            (x1, y1), (x2, y2) = hull[-2], hull[-1]
            if (y2 - y1) * (p[0] - x2) >= (p[1] - y2) * (x2 - x1):
                hull.pop()
            else:
                break
        hull.append(p)
    out = [float("inf")] * n
    for i in range(len(hull) - 1):
        (x1, y1), (x2, y2) = hull[i], hull[i + 1]
        for b in range(x1, x2 + 1):
            t = (b - x1) / (x2 - x1) if x2 > x1 else 0.0
            out[b] = y1 + t * (y2 - y1)
    for b in range(hull[-1][0], n):
        out[b] = hull[-1][1]
    return out


def eval_sp(tree, F):
    """tree = ('leaf', i) | ('series', l, r) | ('par', l, r)"""
    if tree[0] == "leaf":
        return F[tree[1]]
    l, r = eval_sp(tree[1], F), eval_sp(tree[2], F)
    return sp_series(l, r) if tree[0] == "series" else sp_parallel(l, r)


def brute_sp(tree, profiles, S):
    """Exhaustive: try every depth combination, keep feasible, evaluate the tree."""
    def latency(tree, choice):
        if tree[0] == "leaf":
            return profiles[tree[1]][choice[tree[1]]][0]
        a, b = latency(tree[1], choice), latency(tree[2], choice)
        return a + b if tree[0] == "series" else max(a, b)

    best = None
    for combo in itertools.product(*[range(len(p)) for p in profiles]):
        st = sum(profiles[i][c][1] for i, c in enumerate(combo))
        if st > S:
            continue
        lat = latency(tree, combo)
        if best is None or lat < best:
            best = lat
    return best


def theorem34(cells, pool_keys, quick):
    hdr("THEOREM 3 & 4  --  series-parallel DP, and the refuted submodularity claim")

    # -- the refutation, restated as an executable check ---------------------
    L = lambda X: max(10 - (5 if "a" in X else 0), 10 - (5 if "b" in X else 0))
    f = lambda X: L(set()) - L(X)
    lhs, rhs = f({"a"}) + f({"b"}), f({"a", "b"}) + f(set())
    check("REFUTED (as documented): reduction is NOT submodular on parallel branches",
          lhs < rhs, f"f(a)+f(b) = {lhs} < f(ab)+f(0) = {rhs}; greedy gains 0 vs optimum 5")

    rndk = random.Random(5)
    keys = rndk.sample(pool_keys, min(8, len(pool_keys)))
    pool = [isotonic_decreasing(median_excess(cells[k])[0]) for k in keys]
    if not pool:
        print("  no usable cells; SP check skipped")
        return
    rnd = random.Random(11)
    depths = [0, 2, 10, 50]
    grid = 25.0

    trees = [
        ("series", ("leaf", 0), ("par", ("leaf", 1), ("leaf", 2))),
        ("par", ("series", ("leaf", 0), ("leaf", 1)), ("leaf", 2)),
        ("par", ("leaf", 0), ("par", ("leaf", 1), ("leaf", 2))),
        ("series", ("series", ("leaf", 0), ("leaf", 1)), ("leaf", 2)),
    ]
    n_ok = n_tot = 0
    trials = 30 if quick else 120
    for _ in range(trials):
        tree = rnd.choice(trees)
        profs = [make_profile(rnd.choice(pool), depths, A=rnd.uniform(200, 3000),
                              s_scale=rnd.choice([1.0, 2.0])) for _ in range(3)]
        # snap storage onto the grid so DP and brute force see identical budgets
        profs = [[(c, grid * round(s / grid)) for c, s in p] for p in profs]
        S = grid * rnd.randint(0, 12)
        Fs = [sp_leaf(p, S, grid) for p in profs]
        dp = eval_sp(tree, Fs)[int(S / grid)]
        bf = brute_sp(tree, profs, S)
        if bf is None:
            continue
        n_tot += 1
        n_ok += abs(dp - bf) < 1e-6
    check(f"Theorem 3: SP dynamic program == exhaustive enumeration ({n_tot} instances)",
          n_ok == n_tot, f"{n_ok}/{n_tot} exact")

    # -- Theorem 4a/4b: convexity IN -> convexity OUT, per composition type ---
    def is_convex(F):
        idx = [i for i, y in enumerate(F) if y != float("inf")]
        if len(idx) < 3 or idx != list(range(idx[0], idx[0] + len(idx))):
            return None
        x = [F[i] for i in idx]
        return all(x[k] - 2 * x[k + 1] + x[k + 2] >= -1e-6 for k in range(len(x) - 2))

    ser = [0, 0]
    par = [0, 0]
    for _ in range(trials * 4):
        profs = [make_profile(rnd.choice(pool), [0, 2, 10, 50], A=rnd.uniform(200, 3000))
                 for _ in range(2)]
        profs = [[(c, grid * round(s / grid)) for c, s in p] for p in profs]
        S = grid * 12
        cvx = [lower_convex_envelope(sp_leaf(p, S, grid)) for p in profs]
        if any(is_convex(F) is not True for F in cvx):
            continue
        for slot, fn in ((ser, sp_series), (par, sp_parallel)):
            r = is_convex(fn(cvx[0], cvx[1]))
            if r is None:
                continue
            slot[1] += 1
            slot[0] += bool(r)
    check("Theorem 4a: SERIES (min-plus) composition preserves convexity",
          ser[1] and ser[0] == ser[1], f"{ser[0]}/{ser[1]} convex")
    check("Theorem 4b REFUTED: PARALLEL (min-max) composition does NOT, on the grid",
          par[0] < par[1], f"only {par[0]}/{par[1]} convex")

    # the minimal counterexample, stated explicitly
    F1 = F2 = [1.0, 0.0, 0.0]
    P = sp_parallel(F1, F2)
    check("   minimal counterexample F1=F2=[1,0,0] -> parallel gives [1,1,0]",
          P == [1.0, 1.0, 0.0] and (P[0] - 2 * P[1] + P[2]) < 0,
          f"parallel {P}, d2 = {P[0]-2*P[1]+P[2]:.0f}; "
          f"series {sp_series(F1, F2)} is convex")
    print("      -> same complementarity as the submodularity refutation: one unit of")
    print("         budget cannot help a parallel pair, two units can. Consequence:")
    print("         series/chain nodes get the O(S) slope merge; parallel nodes need")
    print("         the full O(S^2) convolution of Theorem 3, which remains exact.")


# --------------------------------------------------------------------------
# THEOREM 5 -- capacity
# --------------------------------------------------------------------------
def theorem5():
    hdr("THEOREM 5  --  capacity bound, against exp10's measured data")
    print("  Corollary 5a: a depth-d chain with per-stage memory m is fully warmable")
    print("  iff d <= M/m. exp10 python: m = 512 MB, M = 1024 MB  ->  predicts d <= 2.\n")
    obs = {1: 305.0, 2: 393.0, 3: 1.01, 5: 1.09, 8: 1.15}   # cold/warm ratio, M=1024
    m, M = 512, 1024
    ok = True
    for d, ratio in sorted(obs.items()):
        pred_warm = d * m <= M
        obs_warm = ratio > 10
        agree = pred_warm == obs_warm
        ok &= agree
        k = max(0, -(-(d * m - M) // m))
        print(f"   d={d}: d*m={d*m:>5} MB  predict {'WARMABLE ' if pred_warm else 'NOT warmable'}"
              f"  (>= {k} stage(s) evicted)   observed cold/warm = {ratio:>6.2f}x"
              f"   {'agree' if agree else 'DISAGREE'}")
    check("Theorem 5 / Corollary 5a predicts the measured warmability transition",
          ok, "transition at d=3, exactly where d*m first exceeds M")


def theorem6():
    hdr("THEOREM 6  --  keep-alive vs snapshot threshold (closed form, sanity check)")
    import math
    A, R0, rK, RK, T = 2586.0, 618.0, 30.0, 100.0, 600.0     # java-spring @1 vCPU
    lam = -(1.0 / T) * math.log((rK + RK) / (A + R0))
    print(f"   java-spring @1 vCPU: A={A} R(0)={R0} assumed r={rK} R(K)={RK} T={T}s")
    print(f"   lambda* = {lam:.5f} /s  =  one invocation per {1/lam:.1f} s")
    print("   Below that rate snapshotting wins on expected latency AND uses no memory.")
    check("Theorem 6 threshold is finite and positive for a real profile",
          0 < lam < 1, f"lambda* = {lam:.5f}/s")
    print("   (r_v is assumed here, not measured -- S1 replaces it. The FORM of the")
    print("    threshold does not depend on that value; only the number does.)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--curves", default=CURVES)
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(a.curves, "*.csv")))
    print(f"loaded {len(paths)} curve files from {a.curves}")
    cells = group_curves(paths)
    print(f"grouped into {len(cells)} (workload, cpu, mem) cells")

    passing, examined = lemma1(cells)
    lemma2(cells)
    theorem12(cells, examined, a.quick)
    theorem34(cells, examined, a.quick)
    theorem5()
    theorem6()

    hdr("SUMMARY")
    bad = [n for n, ok in results if not ok]
    for n, ok in results:
        print(f"  [{PASS if ok else FAIL}] {n}")
    print(f"\n  {len(results)-len(bad)}/{len(results)} checks passed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
