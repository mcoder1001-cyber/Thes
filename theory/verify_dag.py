#!/usr/bin/env python3
"""Computational verification of theory/DAG_SNAPSHOT_THEORY.md.

Same rule as verify.py: every theorem is checked against an independent computation, and
every check is paired with a CONTROL designed to fail -- a check that cannot fail proves
nothing. Controls are labelled "CONTROL" and pass when they DETECT the violation.

  T1   look-ahead restore is latency-optimal (lower bound + attainment), random DAGs
  C1.1 chain speedup formula, its monotonicity and its bound 1 + r/(w+delta)
  C1.2 restore contention: saving >= (1-beta)(d-1)r; also inside dagsim
  C1.3 random restore times: look-ahead pays the max of parallel restores, on-demand the sum
  T2   just-in-time look-ahead is latency- AND memory-optimal; cross-checked against dagsim
  T3   restore trigger under uncertainty = newsvendor quantile kappa = b/(a+b)
  T4   speculation on XOR branches: restore ahead iff p >= kappa; unnecessary if decided early
  L5   gating is lossless without concurrency (dagsim), and is NOT under concurrency/XOR
  T6   keep-alive vs look-ahead memory for rare workflows (renewal Monte Carlo)
  P7   predicate-preserving scrubbing preserves control-flow paths (src/Sig.java; needs java)
  P8   depth is work, not requests: JIT compile counts / residuals from exp-a (committed CSV)
  T7   UNIFIED: joint snapshot depth + look-ahead timing on series-parallel DAGs -- composition
       rules, exact (storage, W, P) Pareto DP vs brute force, hidden-restore reduction to
       MODEL.md's DP, cold-start-hidden stages, and what the unification buys

usage: ./verify_dag.py [--quick]
"""
import argparse
import csv
import itertools
import math
import os
import random
import shutil
import statistics
import string
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SIM = os.path.join(REPO, "ideas", "sim")
EXPA = os.path.join(REPO, "ideas", "exp-a-context-priming")

PASS, FAIL, SKIP = "\033[32mPASS\033[0m", "\033[31mFAIL\033[0m", "\033[33mSKIP\033[0m"
results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    tag = SKIP if ok is None else (PASS if ok else FAIL)
    print(f"  [{tag}] {name}" + (f"  --  {detail}" if detail else ""))
    return ok


def hdr(t):
    print(f"\n{'=' * 78}\n {t}\n{'=' * 78}")


# ============================================================ the model
class DAG:
    """AND-DAG with one entry (node 0), nodes numbered in topological order."""

    def __init__(self, n, preds, r, w, m, delta):
        self.n, self.preds, self.r, self.w, self.m, self.delta = n, preds, r, w, m, delta
        self.succ = [[] for _ in range(n)]
        for v in range(n):
            for u in preds[v]:
                self.succ[u].append(v)

    def ell(self, restore_on_path=False):
        """Longest path from v to any sink; weights w (+r if restore_on_path) and delta per edge."""
        L = [0.0] * self.n
        for v in reversed(range(self.n)):
            own = self.w[v] + (self.r[v] if restore_on_path else 0.0)
            L[v] = own + max((self.delta + L[s] for s in self.succ[v]), default=0.0)
        return L


def random_dag(rnd, n=None, chain=False):
    n = n or rnd.randint(2, 12)
    preds = [[]]
    for v in range(1, n):
        if chain:
            preds.append([v - 1])
        else:
            k = rnd.randint(1, min(3, v))
            preds.append(sorted(rnd.sample(range(v), k)))
    r = [rnd.uniform(50, 3000) for _ in range(n)]
    w = [rnd.uniform(1, 500) for _ in range(n)]
    m = [rnd.uniform(128, 2048) for _ in range(n)]
    return DAG(n, preds, r, w, m, rnd.choice([0.0, 2.0, 10.0]))


def evaluate(g, trigger, ready_time=None):
    """Exact schedule for trigger policy trigger(v, I_v) -> tau_v.

    S_v = max(tau_v + r_v, I_v), F_v = S_v + w_v, I_v = max_pred F + delta (I_0 = 0).
    ready_time(v, tau) can override tau + r_v (used for contention). Returns (L, M, tau, S, F).
    """
    I, S, F, tau = [0.0] * g.n, [0.0] * g.n, [0.0] * g.n, [0.0] * g.n
    for v in range(g.n):
        I[v] = 0.0 if not g.preds[v] else max(F[u] for u in g.preds[v]) + g.delta
        tau[v] = trigger(v, I[v])
        ready = ready_time(v, tau[v]) if ready_time else tau[v] + g.r[v]
        S[v] = max(ready, I[v])
        F[v] = S[v] + g.w[v]
    L = max(F[v] for v in range(g.n) if not g.succ[v])
    M = sum(g.m[v] * (F[v] - tau[v]) for v in range(g.n))
    return L, M, tau, S, F


def eager(g):
    return evaluate(g, lambda v, I: 0.0)


def on_demand(g):
    return evaluate(g, lambda v, I: I)


def jit(g):
    _, _, _, S_e, _ = eager(g)
    return evaluate(g, lambda v, I: S_e[v] - g.r[v])


def L_star(g):
    ell = g.ell()
    return max(g.r[v] + ell[v] for v in range(g.n))


def M_min(g):
    return sum(g.m[v] * (g.r[v] + g.w[v]) for v in range(g.n))


# ============================================================ T1
def t1(quick):
    hdr("THEOREM 1 -- look-ahead restore is latency-optimal")
    rnd = random.Random(1)
    N = 400 if quick else 2000
    ok_a = ok_c = ok_d = 0
    for _ in range(N):
        g = random_dag(rnd)
        La = eager(g)[0]
        Ls = L_star(g)
        Lod = on_demand(g)[0]
        ok_a += abs(La - Ls) < 1e-7
        ok_c += abs(Lod - g.ell(True)[0]) < 1e-7
        ok_d += Ls <= Lod + 1e-7
    check(f"T1(b) eager attains L* = max_v (r_v + l(v))  [{N} random DAGs]", ok_a == N, f"{ok_a}/{N} exact")
    check("T1(c) on-demand = longest path with weights r + w", ok_c == N, f"{ok_c}/{N} exact")
    check("T1(d) L* <= L_on-demand", ok_d == N, f"{ok_d}/{N}")

    # (a) lower bound against arbitrary policies
    G = 100 if quick else 300
    P = 200 if quick else 500
    viol = tried = 0
    for _ in range(G):
        g = random_dag(rnd)
        Ls = L_star(g)
        hi = on_demand(g)[0]
        for _ in range(P):
            mode = rnd.random()
            if mode < 0.4:
                pol = lambda v, I, hi=hi: rnd.uniform(0, hi)
            elif mode < 0.8:
                pol = lambda v, I: I * rnd.random()          # anywhere between eager and on-demand
            else:
                pol = lambda v, I: max(0.0, I - rnd.uniform(0, 2) * g.r[v])
            tried += 1
            viol += evaluate(g, pol)[0] < Ls - 1e-7
    check(f"T1(a) no policy with tau >= 0 beats L*  [{tried} random policies]", viol == 0,
          f"{viol} violations")

    # CONTROL: drop assumption A1 (allow restores to start BEFORE the workflow arrives)
    beat = 0
    for _ in range(G):
        g = random_dag(rnd)
        Ls = L_star(g)
        for _ in range(20):
            beat += evaluate(g, lambda v, I: -rnd.uniform(0, g.r[v]))[0] < Ls - 1e-7
    check("CONTROL: a clairvoyant policy (tau < 0) DOES beat L* -- the bound rests on A1",
          beat > 0, f"{beat} beats found; the test can detect a violation")


# ============================================================ C1.1 / C1.2
def c1():
    hdr("COROLLARY 1.1 / 1.2 / 1.3 -- chains: speedup, bound, contention, random restore times")
    ok = mono = bound = 0
    cases = 0
    for r in (100, 650, 2000, 9000):
        for w in (10, 75, 400):
            for delta in (0.0, 2.0):
                prev = 0
                for d in range(1, 17):
                    g = DAG(d, [[]] + [[v - 1] for v in range(1, d)], [r] * d, [w] * d, [512] * d, delta)
                    s_sim = on_demand(g)[0] / eager(g)[0]
                    s_formula = (d * (r + w) + (d - 1) * delta) / (r + d * w + (d - 1) * delta)
                    cases += 1
                    ok += abs(s_sim - s_formula) < 1e-9
                    mono += s_sim >= prev - 1e-12
                    bound += s_sim < 1 + r / (w + delta) + 1e-12
                    prev = s_sim
    check("C1.1 speedup = d(r+w)+(d-1)delta over r+dw+(d-1)delta", ok == cases, f"{ok}/{cases}")
    check("C1.1 speedup is non-decreasing in depth d", mono == cases, f"{mono}/{cases}")
    check("C1.1 speedup < 1 + r/(w+delta) for every d", bound == cases, f"{bound}/{cases}")
    r, w, delta = 650.0, 75.0, 2.0
    print(f"      thesis numbers (r=650, w=R(50)+C=75, delta=2): bound {1 + r / (w + delta):.2f}x; "
          f"d=3 {(3 * (r + w) + 2 * delta) / (r + 3 * w + 2 * delta):.2f}x, "
          f"d=8 {(8 * (r + w) + 7 * delta) / (r + 8 * w + 7 * delta):.2f}x")

    # C1.2: contention. n restores started together each finish within r(1 + beta(n-1)).
    ok2 = tot2 = 0
    for beta in (0.0, 0.25, 0.5, 1.0):
        for d in range(2, 12):
            g = DAG(d, [[]] + [[v - 1] for v in range(1, d)], [r] * d, [w] * d, [512] * d, delta)
            slow = r * (1 + beta * (d - 1))
            La = evaluate(g, lambda v, I: 0.0, ready_time=lambda v, tau: tau + slow)[0]
            Lod = on_demand(g)[0]                      # a chain's on-demand restores never overlap
            tot2 += 1
            ok2 += (Lod - La) >= (1 - beta) * (d - 1) * r - 1e-7
    check("C1.2 saving >= (1-beta)(d-1)r, so look-ahead never loses for beta <= 1", ok2 == tot2, f"{ok2}/{tot2}")

    # the same inequality inside the discrete-event simulator (its own contention model:
    # a restore is slowed by the number of restores already running when it starts)
    try:
        sys.path.insert(0, SIM)
        from dataclasses import replace
        from dagsim import JAVA, POLICIES, Sim, chain, ttl0
        ok3 = tot3 = 0
        for rr in (250.0, 650.0, 2000.0, 6000.0):
            for b in (0.0, 0.25, 1.0):
                dag = chain(5, replace(JAVA, r=rr), "s")
                out = {}
                for pn, pol in (("od", POLICIES["snap"]), ("eager", replace(POLICIES["ahead"], margin=1e9))):
                    sim = Sim(ttl0(pol), restore_beta=b, jitter=False)
                    sim.invoke(0.0, dag, "w")
                    sim.run()
                    out[pn] = sim.results[0][3]
                bound_ms = rr * (1 + b * 4) + 5 * (JAVA.RK + JAVA.C) + 4 * 2
                tot3 += 1
                ok3 += out["eager"] <= bound_ms + 1e-6 and out["eager"] <= out["od"] + 1e-6
        check("C1.2 dagsim (deterministic, its own contention model): look-ahead <= bound and <= on-demand",
              ok3 == tot3, f"{ok3}/{tot3}")
    except ImportError as e:                          # pragma: no cover
        check("C1.2 dagsim consistency", None, str(e))

    # C1.3: random restore times. Pointwise, eager on a chain <= max_j r_j + sum w + (d-1)delta,
    # so E[saving] >= d E[r] - E[max_j r_j]: look-ahead pays the MAXIMUM of the parallel
    # restores, on-demand their SUM.
    rnd = random.Random(13)
    ok4 = tot4 = 0
    for sigma in (0.15, 0.5):
        for d in (3, 5, 8):
            sav, emax, er = [], [], []
            for _ in range(3000):
                rs = [650.0 * rnd.lognormvariate(0, sigma) for _ in range(d)]
                g = DAG(d, [[]] + [[v - 1] for v in range(1, d)], rs, [75.0] * d, [512] * d, 2.0)
                La, Lod = eager(g)[0], on_demand(g)[0]
                tot4 += 1
                ok4 += La <= max(rs) + d * 75.0 + (d - 1) * 2.0 + 1e-7
                sav.append(Lod - La)
                emax.append(max(rs))
                er.append(sum(rs) / d)
            tot4 += 1
            ok4 += statistics.mean(sav) >= d * statistics.mean(er) - statistics.mean(emax) - 1e-6
    check("C1.3 random restore times: L_eager <= max_j r_j + sum w, E[saving] >= d E[r] - E[max r]",
          ok4 == tot4, f"{ok4}/{tot4}")
    zs = sorted(max(rnd.lognormvariate(0, 0.15) for _ in range(5)) for _ in range(20000))
    print(f"      E[max of 5 restore times] / r = {statistics.mean(zs):.3f} at sigma = 0.15 "
          f"(dagsim's jitter): the 3-16% by which jittered e5 exceeds the deterministic bound")


# ============================================================ T2
def t2(quick):
    hdr("THEOREM 2 -- just-in-time look-ahead: optimal latency AND minimum memory")
    rnd = random.Random(2)
    N = 400 if quick else 2000
    feas = lat = mem = od = 0
    for _ in range(N):
        g = random_dag(rnd)
        Lj, Mj, tau, _, _ = jit(g)
        feas += min(tau) >= -1e-9
        lat += abs(Lj - L_star(g)) < 1e-7
        mem += abs(Mj - M_min(g)) < 1e-6 * M_min(g)
        od += abs(on_demand(g)[1] - M_min(g)) < 1e-6 * M_min(g)
    check("T2(c) JIT triggers are feasible (tau_v = S*_v - r_v >= 0)", feas == N, f"{feas}/{N}")
    check("T2(c) JIT latency = L*", lat == N, f"{lat}/{N}")
    check("T2(c) JIT memory-time = M_min = sum m_v (r_v + w_v)", mem == N, f"{mem}/{N}")
    check("T2(b) on-demand memory-time = M_min", od == N, f"{od}/{N}")
    viol = tried = 0
    for _ in range(100 if quick else 300):
        g = random_dag(rnd)
        Mm = M_min(g)
        for _ in range(100):
            tried += 1
            viol += evaluate(g, lambda v, I: I * rnd.random())[1] < Mm * (1 - 1e-9)
    check(f"T2(a) no policy holds less than M_min  [{tried} random policies]", viol == 0, f"{viol} violations")
    # eager holds strictly more on some DAGs: JIT is a real improvement, not a restatement
    worse = sum(eager(g)[1] > M_min(g) * (1 + 1e-9) for g in (random_dag(rnd) for _ in range(200)))
    check("CONTROL: eager look-ahead holds MORE than M_min on some DAGs (the test can see it)",
          worse > 0, f"{worse}/200 DAGs")

    # cross-check against the discrete-event simulator (independent code path)
    try:
        sys.path.insert(0, SIM)
        from dagsim import JAVA, PY, EDGE_MS, Policy, Sim, chain, fanout
    except Exception as e:                            # pragma: no cover
        check("T2 cross-check against dagsim", None, f"dagsim not importable: {e}")
        return
    pol = Policy("jit0", ttl=0.0, snap=True, ahead="restore", jit=True, margin=0.0)
    ok = tot = 0
    for dag in [chain(d, JAVA, "c") for d in (1, 2, 3, 5, 8)] + [chain(4, PY, "p"), fanout(4, "f")]:
        order = dag.topo()                            # entry first: it is the only source
        idx = {n: i for i, n in enumerate(order)}
        preds = [[] for _ in order]
        for n, node in dag.nodes.items():
            for s in node.succ:
                preds[idx[s]].append(idx[n])
        g = DAG(len(order), [sorted(p) for p in preds],
                [dag.nodes[n].prof.r for n in order],
                [dag.nodes[n].prof.RK + dag.nodes[n].prof.C for n in order],
                [dag.nodes[n].prof.m for n in order], EDGE_MS)
        sim = Sim(pol, jitter=False)
        sim.invoke(0.0, dag, "w")
        sim.run()
        tot += 1
        ok += abs(sim.results[0][3] - L_star(g)) < 1e-6 and abs(sim.memtime - M_min(g)) < 1e-6 * M_min(g)
    check("T2 dagsim's JIT policy reproduces L* and M_min exactly (chains, fan-out)", ok == tot, f"{ok}/{tot}")


# ============================================================ T3
def t3(quick):
    hdr("THEOREM 3 -- trigger under uncertainty: ready at the kappa = b/(a+b) quantile")
    rnd = random.Random(3)
    n = 20000 if quick else 60000
    dists = {
        "lognormal": [rnd.lognormvariate(math.log(800), 0.35) for _ in range(n)],
        "gamma": [rnd.gammavariate(4.0, 200.0) for _ in range(n)],
        "bimodal": [rnd.gauss(400, 40) if rnd.random() < 0.7 else rnd.gauss(1500, 150) for _ in range(n)],
    }
    ok = tot = 0
    worse = tot_c = 0
    for name, xs in dists.items():
        xs.sort()

        def J(x, a, b):
            return sum(a * (x - s) if x > s else b * (s - x) for s in xs[::10]) / len(xs[::10])
        for a, b in ((1.0, 1.0), (4.0, 1.0), (1.0, 4.0), (20.0, 1.0)):
            kappa = b / (a + b)
            xq = xs[min(len(xs) - 1, int(kappa * len(xs)))]
            grid = [xs[int(q * (len(xs) - 1))] for q in [i / 200 for i in range(1, 200)]]
            jmin = min(J(x, a, b) for x in grid)
            tot += 1
            ok += J(xq, a, b) <= jmin * 1.005
            if a != b:
                wrong = xs[min(len(xs) - 1, int(a / (a + b) * len(xs)))]
                tot_c += 1
                worse += J(wrong, a, b) > J(xq, a, b) * 1.01
    check("T3 argmin of expected cost is the kappa-quantile (3 distributions x 4 price ratios)",
          ok == tot, f"{ok}/{tot} within 0.5% of the grid optimum")
    check("CONTROL: the wrong quantile a/(a+b) costs more whenever a != b", worse == tot_c, f"{worse}/{tot_c}")


# ============================================================ T4
def t4():
    hdr("THEOREM 4 -- speculation on an XOR branch: restore ahead iff p >= kappa")
    # decision node d (entry, restored on demand), then branch s (prob p) or s' (1-p), each a
    # single stage. Evaluate both policies exactly on each realised branch.
    def run(r_d, w_d, r_s, w_s, delta, spec, taken, lag=0.0, m_s=1.0):
        D = r_d + w_d                                  # decision known when d finishes
        I_s = D + delta + lag                          # lag: branch work before s (decided early)
        S_star = max(r_s, I_s)                         # eager start of s had it been certain
        tau_j = S_star - r_s                           # JIT trigger
        if not taken:
            waste = max(0.0, D - tau_j) if spec else 0.0
            return D, m_s * waste                      # workflow ends on the other branch (same cost both ways)
        tau = tau_j if spec else max(D, tau_j)
        S = max(tau + r_s, I_s)
        return S + w_s, m_s * (S + w_s - tau)
    ok = tot = 0
    early_cases = 0
    for (r_d, w_d, r_s, w_s, delta, lag) in ((650, 75, 650, 75, 2, 0), (60, 300, 650, 75, 2, 0),
                                             (2000, 50, 900, 10, 0, 0), (100, 50, 300, 10, 2, 1000)):
        for a, b in ((1.0, 0.2), (1.0, 1.0), (1.0, 5.0)):
            kappa = b / (a + b)
            for p in [i / 20 for i in range(1, 20)]:
                cost = {}
                for spec in (True, False):
                    Lt, Mt = run(r_d, w_d, r_s, w_s, delta, spec, True, lag)
                    Ln, Mn = run(r_d, w_d, r_s, w_s, delta, spec, False, lag)
                    cost[spec] = p * (a * Lt + b * Mt) + (1 - p) * (a * Ln + b * Mn)
                D = r_d + w_d
                decided_early = D <= max(r_s, D + delta + lag) - r_s
                early_cases += decided_early
                best = min(cost, key=cost.get)
                rule = False if decided_early else (p >= kappa)
                tot += 1
                ok += (best == rule) or abs(cost[True] - cost[False]) < 1e-9
    check("T4 exact expected cost agrees with 'speculate iff p >= kappa' (and 'no need if decided early')",
          ok == tot, f"{ok}/{tot} (p grid x 3 price ratios x 4 timings; {early_cases} decided early)")


# ============================================================ L5
def l5():
    hdr("LEMMA 5 -- gating is lossless without concurrency (and only then)")
    try:
        sys.path.insert(0, SIM)
        from dagsim import POLICIES, Sim, chain, fanout, trip_booking
    except Exception as e:                            # pragma: no cover
        check("L5 gating", None, f"dagsim not importable: {e}")
        return
    rnd = random.Random(5)

    def run(pol, dag, gaps):
        sim = Sim(POLICIES[pol], mem_budget_mb=10 ** 9, seed=9)
        t = 0.0
        for g in gaps:
            t += g
            sim.invoke(t, dag, "w")
        sim.run()
        return sorted((r[2], round(r[3], 9)) for r in sim.results), sim.stats["restores"]

    seq = [rnd.choice([20_000.0, 300_000.0, 900_000.0, 3_600_000.0]) for _ in range(200)]   # > latency; some > TTL
    same = tot = 0
    for dag in (chain(3), chain(6), fanout(4)):
        tot += 1
        same += run("ahead+rw", dag, seq) == run("ahead+rw/gated", dag, seq)
    check("L5 sequential invocations of AND-DAGs: gated == ungated, run for run", same == tot, f"{same}/{tot}")
    burst = [rnd.uniform(0, 400.0) for _ in range(200)]                                        # overlapping
    diff = run("ahead+rw", chain(6), burst) != run("ahead+rw/gated", chain(6), burst)
    check("CONTROL: overlapping invocations -> gated != ungated (busy sandboxes)", diff)
    diff2 = run("ahead+rw", trip_booking(), seq) != run("ahead+rw/gated", trip_booking(), seq)
    check("CONTROL: XOR DAG (saga) -> gated != ungated (rare branch expired, entry warm)", diff2)


# ============================================================ T6
def t6():
    hdr("THEOREM 6 -- keep-alive vs look-ahead memory for rare workflows")
    rnd = random.Random(6)
    T = 600.0
    ok = tot = 0
    for lam in (1 / 3600, 1 / 600, 1 / 60, 1.0):
        horizon = 2e7 if lam < 1e-2 else 2e5
        t, alive, n, miss, last = 0.0, 0.0, 0, 0, None
        while t < horizon:
            x = rnd.expovariate(lam)
            alive += min(x, T)
            miss += x > T
            n += 1
            t += x
        tot += 2
        ok += abs(alive / t - (1 - math.exp(-lam * T))) < 0.02
        ok += abs(miss / n - math.exp(-lam * T)) < 0.02
    check("T6 renewal Monte Carlo: alive fraction = 1-e^{-lambda T}, miss rate = e^{-lambda T}", ok == tot, f"{ok}/{tot}")
    Lc, Lw, La, c = 12.1, 0.035, 0.93, 0.725        # exp15 cold/warm, e1 look-ahead d=3, r+w per stage
    eps = (La - Lw) / (Lc - Lw)
    lam_star = (1 - eps) / c
    print(f"      thesis numbers: eps = {eps:.3f}; crossover lambda* = {lam_star:.2f}/s "
          f"(one invocation every {1 / lam_star:.2f} s)")
    for lam, lab in ((1 / 3600, "1/hour"), (1 / 60, "1/minute"), (1.0, "1/second")):
        print(f"      at {lab:>9}: keep-alive needs >= {(1 - eps) / (lam * c):8.1f}x the memory of "
              f"look-ahead for the same expected latency")
    check("T6 crossover lambda* is finite and positive for thesis parameters", 0 < lam_star < 100,
          f"lambda* = {lam_star:.2f}/s")


# ============================================================ P7
def p7():
    hdr("PROPOSITION 7 -- predicate-preserving scrubbing preserves control-flow paths")
    inputs = os.path.join(EXPA, "inputs")
    build = os.path.join(EXPA, "build")
    if not (shutil.which("java") and os.path.exists(os.path.join(build, "Sig.class"))
            and os.path.exists(os.path.join(inputs, "fps2_bulk.jsonl"))):
        check("P7 path agreement (needs java, build/Sig.class, generated inputs)", None,
              "run ideas/exp-a-context-priming/fetch_deps.sh + gen_inputs.py + javac src/Sig.java")
        return
    cp = f"{build}:{os.path.join(EXPA, 'lib')}/*"
    env = dict(os.environ)
    env.pop("JAVA_TOOL_OPTIONS", None)

    def sigs(path):
        out = subprocess.run(["java", "-cp", cp, "Sig", path, "1500"], capture_output=True, text=True, env=env)
        return out.stdout.splitlines()

    def agree(a, b):
        A, B = sigs(os.path.join(inputs, a)), sigs(os.path.join(inputs, b))
        return sum(x == y for x, y in zip(A, B)) / max(1, len(A))

    # CONTROL: a naive scrub that randomises every string (no class or categorical preservation)
    rnd = random.Random(7)
    import json

    def naive(o):
        if isinstance(o, dict):
            return {k: naive(v) for k, v in o.items()}
        if isinstance(o, list):
            return [naive(v) for v in o]
        if isinstance(o, str):
            return "".join(rnd.choice(string.ascii_letters + string.digits) for _ in o)
        return o
    ctrl = os.path.join(inputs, "_naive_bulk.jsonl")
    with open(os.path.join(inputs, "real_bulk.jsonl")) as f, open(ctrl, "w") as g:
        for line in f:
            o = json.loads(line)
            n = naive(o)
            for it_o, it_n in zip(o["items"], n["items"]):
                it_n["kind"] = it_o["kind"]            # keep the type tag so Jackson can still parse
            g.write(json.dumps(n) + "\n")
    res = {k: agree(*k) for k in (("real_bulk.jsonl", "fps_bulk.jsonl"), ("real_bulk.jsonl", "fps2_bulk.jsonl"),
                                  ("real_web.jsonl", "fps_web.jsonl"), ("real_web.jsonl", "fps2_web.jsonl"),
                                  ("real_bulk.jsonl", "_naive_bulk.jsonl"))}
    os.remove(ctrl)
    for (a, b), v in res.items():
        print(f"      {b:<22} identical path on {100 * v:5.1f}% of requests")
    check("P7 fps2 (small-integer enums kept) preserves every predicate on the bulk edge",
          res[("real_bulk.jsonl", "fps2_bulk.jsonl")] == 1.0)
    check("P7 fps2 >= 98% identical paths on the web edge (rest: a price-sum threshold)",
          res[("real_web.jsonl", "fps2_web.jsonl")] >= 0.98)
    check("P7 fps2 >= fps on both edges (the theory-guided fix helps)",
          res[("real_bulk.jsonl", "fps2_bulk.jsonl")] >= res[("real_bulk.jsonl", "fps_bulk.jsonl")] and
          res[("real_web.jsonl", "fps2_web.jsonl")] >= res[("real_web.jsonl", "fps_web.jsonl")])
    check("CONTROL: a naive scrub breaks the paths (< 5% identical)",
          res[("real_bulk.jsonl", "_naive_bulk.jsonl")] < 0.05,
          f"{100 * res[('real_bulk.jsonl', '_naive_bulk.jsonl')]:.1f}%")


# ============================================================ P8
def p8():
    hdr("PROPOSITION 8 -- depth is work, not requests (exp-a, measured)")
    path = os.path.join(EXPA, "results", "summary_exp-a.csv")
    if not os.path.exists(path):
        check("P8", None, "summary_exp-a.csv missing")
        return
    rows = {(r["vcpu"], r["cond"]): r for r in csv.DictReader(open(path))}
    mono = tot = 0
    for q in ("1.0", "0.25"):
        seq = [float(rows[(q, c)]["compiles_snap"]) for c in ("real_bulk_K25", "real_bulk_K100", "real_bulk_K400",
                                                               "ref_K1500") if (q, c) in rows]
        tot += 1
        mono += all(a <= b for a, b in zip(seq, seq[1:]))
    check("P8 compiled-method count at the snapshot is monotone in priming work", mono == tot, f"{mono}/{tot}")
    inc = res = tot = 0
    for q in ("1.0", "0.25"):
        for k in (100, 400):
            a, b = rows.get((q, f"mixed_K{2 * k}")), rows.get((q, f"real_bulk_K{k}"))
            if not (a and b):
                continue
            tot += 1
            inc += float(a["compiles_snap"]) >= float(b["compiles_snap"])
            res += float(a["R_med"]) <= float(b["R_med"])
    check("P8 superset priming (mix incl. the same heavy requests) compiles at least as much",
          inc == tot, f"{inc}/{tot} cells")
    check("P8 ...and leaves no more residual warm-up (pollution < gain on this workload)", res == tot,
          f"{res}/{tot} cells")
    if shutil.which("java"):
        env = dict(os.environ)
        env.pop("JAVA_TOOL_OPTIONS", None)
        out = subprocess.run(["java", "-XX:+PrintFlagsFinal", "-version"], capture_output=True, text=True, env=env).stdout
        keep = [l.split()[1] + " = " + l.split()[3] for l in out.splitlines()
                if any(k in l for k in ("Tier3InvocationThreshold ", "Tier4InvocationThreshold ",
                                        "Tier3BackEdgeThreshold ", "Tier4BackEdgeThreshold "))]
        print("      HotSpot thresholds on this JDK: " + "; ".join(keep))


# ============================================================ T7 (unified)
# Series-parallel workflows. tree = ("leaf", i) | ("ser", A, B) | ("par", A, B).
# Every leaf i has options opts[i] = [(p, w, s), ...]: provisioning time p (restore r_v(K) for a
# snapshot of depth K, or cold-boot time A_v for "no snapshot"), warm work w after it
# (R_v(K) + C_v, or B_v + C_v), and storage s (0 for "no snapshot").
def gen_sp(rnd, n):
    if n == 1:
        gen_sp.k += 1
        return ("leaf", gen_sp.k - 1)
    a = rnd.randint(1, n - 1)
    return (rnd.choice(["ser", "par"]), gen_sp(rnd, a), gen_sp(rnd, n - a))


def fresh_sp(rnd, n):
    gen_sp.k = 0
    return gen_sp(rnd, n)


def expand(tree, pw, delta):
    """SP tree + chosen (p, w) per leaf -> DAG for the independent exact evaluator.
    Series joins every exit of A to every entry of B with an edge of weight delta."""
    preds, r, w = [], [], []

    def go(t):
        if t[0] == "leaf":
            preds.append([])
            r.append(pw[t[1]][0])
            w.append(pw[t[1]][1])
            v = len(preds) - 1
            return [v], [v]
        ea, xa = go(t[1])
        eb, xb = go(t[2])
        if t[0] == "par":
            return ea + eb, xa + xb
        for v in eb:
            preds[v] = sorted(set(preds[v]) | set(xa))
        return ea, xb
    go(tree)
    return DAG(len(preds), preds, r, w, [1.0] * len(preds), delta)


def rules(tree, pw, delta):
    """Theorem 7(a): (W, P) of a sub-workflow; its finish time for input at x is max(x+W, P)."""
    if tree[0] == "leaf":
        p, w = pw[tree[1]]
        return w, p + w
    W1, P1 = rules(tree[1], pw, delta)
    W2, P2 = rules(tree[2], pw, delta)
    if tree[0] == "ser":
        return W1 + delta + W2, max(P1 + delta + W2, P2)
    return max(W1, W2), max(P1, P2)


def rules_od(tree, pw, delta):
    """Restore-on-demand: one number per sub-workflow (MODEL.md's c = r + R + C)."""
    if tree[0] == "leaf":
        p, w = pw[tree[1]]
        return p + w
    a, b = rules_od(tree[1], pw, delta), rules_od(tree[2], pw, delta)
    return a + delta + b if tree[0] == "ser" else max(a, b)


def _prune(items, key):
    """Drop items dominated in every coordinate of key(item) (smaller is better)."""
    items = sorted(items, key=key)
    kept = []
    for it in items:
        k = key(it)
        if not any(all(a <= b for a, b in zip(key(o), k)) for o in kept):
            kept.append(it)
    return kept


def dp_joint(tree, opts, delta, S, prune_key=None):
    """Theorem 7(b): exact DP over the SP tree, state = Pareto set of (s, W, P).
    prune_key lets a CONTROL replace the 3-D dominance with a coarser (wrong) one."""
    key = prune_key or (lambda it: (it[0], it[1], it[2]))

    def go(t):
        if t[0] == "leaf":
            i = t[1]
            return _prune([(s, w, p + w, ((i, k),)) for k, (p, w, s) in enumerate(opts[i]) if s <= S], key)
        A, B = go(t[1]), go(t[2])
        out = []
        for s1, W1, P1, c1 in A:
            for s2, W2, P2, c2 in B:
                if s1 + s2 > S:
                    continue
                if t[0] == "ser":
                    out.append((s1 + s2, W1 + delta + W2, max(P1 + delta + W2, P2), c1 + c2))
                else:
                    out.append((s1 + s2, max(W1, W2), max(P1, P2), c1 + c2))
        return _prune(out, key)
    best = min(go(tree), key=lambda it: max(it[1], it[2]))
    return max(best[1], best[2]), dict(best[3])


def dp_od(tree, opts, delta, S):
    """MODEL.md's objective (restore on demand): Pareto set of (s, c)."""
    def go(t):
        if t[0] == "leaf":
            i = t[1]
            return _prune([(s, p + w, ((i, k),)) for k, (p, w, s) in enumerate(opts[i]) if s <= S],
                          lambda it: (it[0], it[1]))
        A, B = go(t[1]), go(t[2])
        out = []
        for s1, c1, a1 in A:
            for s2, c2, a2 in B:
                if s1 + s2 <= S:
                    out.append((s1 + s2, c1 + delta + c2 if t[0] == "ser" else max(c1, c2), a1 + a2))
        return _prune(out, lambda it: (it[0], it[1]))
    best = min(go(tree), key=lambda it: it[1])
    return best[1], dict(best[2])


def brute_joint(tree, opts, delta, S, n):
    best = None
    for combo in itertools.product(*[range(len(opts[i])) for i in range(n)]):
        if sum(opts[i][k][2] for i, k in enumerate(combo)) > S:
            continue
        pw = [(opts[i][k][0], opts[i][k][1]) for i, k in enumerate(combo)]
        L = eager(expand(tree, pw, delta))[0]          # independent evaluator, not rules()
        best = L if best is None else min(best, L)
    return best


def random_opts(rnd, n, equal_p=None, cold=True):
    opts = []
    for _ in range(n):
        o = []
        if cold:
            o.append((rnd.uniform(300, 3000), rnd.uniform(20, 500), 0))
        R = rnd.uniform(100, 500)
        C = rnd.uniform(1, 50)
        r = equal_p if equal_p is not None else rnd.uniform(50, 1500)
        for j in range(rnd.randint(1, 3)):
            R *= rnd.uniform(0.2, 0.8)
            o.append((r, R + C, rnd.randint(1, 4) * (j + 1)))
        opts.append(o)
    return opts


def t7(quick):
    hdr("THEOREM 7 -- joint snapshot depth AND look-ahead timing on series-parallel DAGs")
    rnd = random.Random(7)
    # (a) composition rules == exact schedule of the expanded DAG
    N = 500 if quick else 2000
    ok_a = ok_od = 0
    for _ in range(N):
        n = rnd.randint(1, 9)
        tree = fresh_sp(rnd, n)
        delta = rnd.choice([0.0, 2.0, 10.0])
        pw = [(rnd.uniform(50, 3000), rnd.uniform(1, 500)) for _ in range(n)]
        W, P = rules(tree, pw, delta)
        g = expand(tree, pw, delta)
        ok_a += abs(max(W, P) - eager(g)[0]) < 1e-7 and abs(max(W, P) - L_star(g)) < 1e-7
        ok_od += abs(rules_od(tree, pw, delta) - on_demand(g)[0]) < 1e-7
    check(f"T7(a) look-ahead latency of an SP workflow = max(W, P) by the composition rules  [{N}]",
          ok_a == N, f"{ok_a}/{N} exact vs the expanded-DAG evaluator")
    check("T7(a) on-demand latency = MODEL.md's recursion (series: sum, parallel: max)", ok_od == N,
          f"{ok_od}/{N}")

    # (b) the (s, W, P) Pareto DP is exact
    M = 150 if quick else 600
    ok_b = 0
    naive_wrong = 0
    for _ in range(M):
        n = rnd.randint(2, 6)
        tree = fresh_sp(rnd, n)
        delta = rnd.choice([0.0, 2.0])
        opts = random_opts(rnd, n)
        S = rnd.randint(0, sum(max(o[2] for o in op) for op in opts))
        bf = brute_joint(tree, opts, delta, S, n)
        L, _ = dp_joint(tree, opts, delta, S)
        ok_b += abs(L - bf) < 1e-7
        # CONTROL: prune on (s, max(W, P)) only -- a one-number state, like the on-demand DP
        Ln, _ = dp_joint(tree, opts, delta, S, prune_key=lambda it: (it[0], max(it[1], it[2])))
        naive_wrong += Ln > bf + 1e-7
    check(f"T7(b) the (storage, W, P) Pareto DP is exact vs brute force  [{M} instances]", ok_b == M,
          f"{ok_b}/{M}")
    check("CONTROL: a one-number state (storage, latency) is NOT enough -- the DP needs (W, P)",
          naive_wrong > 0, f"wrong on {naive_wrong}/{M} instances")
    # the explicit counterexample in the proof of T7(b): stage 1 has c = (p 990, w 10) and
    # d = (p 100, w 500), equal storage, after a stage with P1 = 900 (delta = 0)
    ex_tree = ("ser", ("leaf", 0), ("leaf", 1))
    ex_opts = [[(880.0, 20.0, 0)], [(990.0, 10.0, 1), (100.0, 500.0, 1)]]
    L_ok, K_ok = dp_joint(ex_tree, ex_opts, 0.0, 1)
    L_bad, K_bad = dp_joint(ex_tree, ex_opts, 0.0, 1, prune_key=lambda it: (it[0], max(it[1], it[2])))
    check("T7(b) proof's counterexample: joint DP picks c (1000 ms); own-latency pruning picks d (1400 ms)",
          L_ok == 1000.0 and K_ok[1] == 0 and L_bad == 1400.0 and K_bad[1] == 1,
          f"joint {L_ok:.0f} ms (option {K_ok[1]}), one-number {L_bad:.0f} ms (option {K_bad[1]})")

    # (c) hidden-restore condition: equal p for every snapshot option -> joint = p + warm-path DP
    ok_c = tot_c = viol = 0
    for _ in range(M):
        n = rnd.randint(2, 6)
        tree = fresh_sp(rnd, n)
        delta = rnd.choice([0.0, 2.0])
        rr = rnd.uniform(50, 1500)
        opts = random_opts(rnd, n, equal_p=rr, cold=False)
        S = rnd.randint(sum(min(o[2] for o in op) for op in opts),    # every stage must afford one
                        sum(max(o[2] for o in op) for op in opts))
        L, _ = dp_joint(tree, opts, delta, S)
        warm = [[(0.0, w, s) for (_, w, s) in op] for op in opts]
        Lw, _ = dp_od(tree, warm, delta, S)                 # MODEL.md's DP on warm weights only
        tot_c += 1
        ok_c += abs(L - (rr + Lw)) < 1e-7
        # CONTROL: violate the condition -- one stage restores much more slowly than the rest
        bad = [list(op) for op in opts]
        j = rnd.randrange(n)
        bad[j] = [(rr + rnd.uniform(2000, 6000), w, s) for (_, w, s) in bad[j]]
        Lb, _ = dp_joint(tree, bad, delta, S)
        Lbw, _ = dp_od(tree, [[(0.0, w, s) for (_, w, s) in op] for op in bad], delta, S)
        viol += abs(Lb - (rr + Lbw)) > 1e-7
    check("T7(c) hidden restores (equal r): joint optimum = r + MODEL.md's DP on warm weights w",
          ok_c == tot_c, f"{ok_c}/{tot_c}")
    check("CONTROL: with one slow-restoring stage the reduction breaks (condition is needed)",
          viol > 0, f"differs on {viol}/{tot_c}")

    # Corollary 7.1: switching stage v to a cold start (provisioning A, same warm work) gives
    # latency max(A + l(v), L_rest); it is free iff A + l(v) <= L_rest (the DAG hides it)
    ok_h = tot_h = hidden_n = 0
    for _ in range(M):
        n = rnd.randint(2, 7)
        tree = fresh_sp(rnd, n)
        delta = 2.0
        pw = [(rnd.uniform(50, 1500), rnd.uniform(5, 300)) for _ in range(n)]
        v = rnd.randrange(n)
        g = expand(tree, pw, delta)                    # leaf i is node i (both in DFS order)
        ell = g.ell()
        L0 = eager(g)[0]
        L_rest = max((pw[u][0] + ell[u] for u in range(n) if u != v), default=0.0)
        A = rnd.uniform(50, 4000)
        pw2 = list(pw)
        pw2[v] = (A, pw[v][1])
        L1 = eager(expand(tree, pw2, delta))[0]
        hidden = A + ell[v] <= L_rest
        hidden_n += hidden
        tot_h += 1
        ok_h += abs(L1 - max(A + ell[v], L_rest)) < 1e-7 and (not hidden or L1 <= L0 + 1e-7)
    check("C7.1 cold start of stage v costs max(A_v + l(v), L_rest) - L; free iff hidden by the DAG",
          ok_h == tot_h, f"{ok_h}/{tot_h} ({hidden_n} hidden)")

    # Corollary 7.2 (longest tail first): identical stages whose options differ only in
    # provisioning (w fixed), unit storage, budget k -> the optimum restores the k stages with the
    # largest remaining warm path l(v) and cold-starts the rest (a sort, no DP)
    ok_g = tot_g = 0
    for _ in range(M):
        n = rnd.randint(2, 7)
        tree = fresh_sp(rnd, n)
        delta = rnd.choice([0.0, 2.0])
        ws = [rnd.uniform(5, 300) for _ in range(n)]
        A, r = rnd.uniform(300, 3000), rnd.uniform(20, 300)
        opts = [[(A, ws[i], 0), (r, ws[i], 1)] for i in range(n)]
        k = rnd.randint(0, n)
        L_opt, _ = dp_joint(tree, opts, delta, k)
        ell = expand(tree, [(0.0, ws[i]) for i in range(n)], delta).ell()
        top = set(sorted(range(n), key=lambda i: -ell[i])[:k])
        W, P = rules(tree, [(r if i in top else A, ws[i]) for i in range(n)], delta)
        tot_g += 1
        ok_g += abs(max(W, P) - L_opt) < 1e-7
    check("C7.2 longest-tail-first: snapshot the k stages with the largest l(v) = exact optimum",
          ok_g == tot_g, f"{ok_g}/{tot_g} vs the exact DP")
    # CONTROL: the on-demand intuition (any k stages on the critical path) is not optimal
    worse = 0
    for _ in range(M):
        n = rnd.randint(3, 7)
        tree = fresh_sp(rnd, n)
        ws = [rnd.uniform(5, 300) for _ in range(n)]
        A, r = rnd.uniform(300, 3000), rnd.uniform(20, 300)
        opts = [[(A, ws[i], 0), (r, ws[i], 1)] for i in range(n)]
        k = rnd.randint(1, n - 1)
        L_opt, _ = dp_joint(tree, opts, 2.0, k)
        ell = expand(tree, [(0.0, ws[i]) for i in range(n)], 2.0).ell()
        low = set(sorted(range(n), key=lambda i: ell[i])[:k])      # shortest tails instead
        W, P = rules(tree, [(r if i in low else A, ws[i]) for i in range(n)], 2.0)
        worse += max(W, P) > L_opt + 1e-7
    check("CONTROL: snapshotting the SHORTEST-tail stages instead is suboptimal", worse > 0,
          f"worse on {worse}/{M}")

    # what unifying buys: MODEL.md's on-demand choice, run under look-ahead, vs the joint optimum
    JAVA_OPTS = [(2510.0, 370 + 12.0, 0), (650.0, 370 + 12.0, 30), (650.0, 63 + 12.0, 30), (650.0, 20 + 12.0, 30)]
    PY_OPTS = [(400.0, 15 + 20.0, 0), (60.0, 5 + 20.0, 20)]
    rows = []
    for _ in range(200 if quick else 1000):
        n = rnd.randint(3, 8)
        tree = fresh_sp(rnd, n)
        opts = [JAVA_OPTS if rnd.random() < 0.6 else PY_OPTS for _ in range(n)]
        full = sum(max(o[2] for o in op) for op in opts)
        S = rnd.choice([0, 30, 60, 90, 120, full // 2, full])
        L_od, K_od = dp_od(tree, opts, 2.0, S)
        W, P = rules(tree, [(opts[i][K_od[i]][0], opts[i][K_od[i]][1]) for i in range(n)], 2.0)
        L_la_Kod = max(W, P)
        L_joint, K_j = dp_joint(tree, opts, 2.0, S)
        cold_py_joint = sum(1 for i in range(n) if opts[i] is PY_OPTS and K_j[i] == 0)
        cold_py_od = sum(1 for i in range(n) if opts[i] is PY_OPTS and K_od[i] == 0)
        rows.append((L_od, L_la_Kod, L_joint, cold_py_joint, cold_py_od))
    ge = all(r[1] >= r[2] - 1e-7 and r[0] >= r[1] - 1e-7 for r in rows)
    check("T7 ordering on thesis-like SP workflows: on-demand opt >= look-ahead(MODEL.md choice) >= joint opt",
          ge, f"{len(rows)} instances")
    sub = [r for r in rows if r[1] > r[2] + 1e-7]
    gain = [r[1] / r[2] for r in sub]
    print(f"      look-ahead alone (same depths as MODEL.md picks): mean {statistics.mean(r[0] / r[1] for r in rows):.2f}x "
          f"faster than on-demand")
    if gain:
        gs = sorted(gain)
        print(f"      choosing depth for look-ahead (Thm 7) improves further on {len(sub)}/{len(rows)} instances: "
              f"median {statistics.median(gs):.3f}x, p95 {gs[int(0.95 * (len(gs) - 1))]:.2f}x, max {gs[-1]:.2f}x")
    else:
        print("      choosing depth for look-ahead (Thm 7) never improved on MODEL.md's choice here")
    print(f"      Python stages left without a snapshot: joint {sum(r[3] for r in rows)}, "
          f"on-demand DP {sum(r[4] for r in rows)} (joint spends storage where lead time cannot hide the start)")
    T7_STATS.update(n=len(rows), sub=len(sub), gain=gain, rows=rows)


T7_STATS = {}


# ============================================================ C7.3 (which stages get a snapshot)
def pareto_front(tree, opts, delta):
    """All non-dominated (storage, latency) points of the joint problem (Theorem 7's DP with
    S = total storage, then projected to (s, L)). Returns [(s, L, choice), ...] sorted by s."""
    S = sum(max(o[2] for o in op) for op in opts)
    key = lambda it: (it[0], it[1], it[2])

    def go(t):
        if t[0] == "leaf":
            i = t[1]
            return _prune([(s, w, p + w, ((i, k),)) for k, (p, w, s) in enumerate(opts[i])], key)
        A, B = go(t[1]), go(t[2])
        out = []
        for s1, W1, P1, c1 in A:
            for s2, W2, P2, c2 in B:
                if t[0] == "ser":
                    out.append((s1 + s2, W1 + delta + W2, max(P1 + delta + W2, P2), c1 + c2))
                else:
                    out.append((s1 + s2, max(W1, W2), max(P1, P2), c1 + c2))
        return _prune(out, key)
    pts = _prune([(s, max(W, P), dict(c)) for s, W, P, c in go(tree) if s <= S], lambda it: (it[0], it[1]))
    return sorted(pts, key=lambda it: (it[0], it[1]))


def c73(quick):
    hdr("COROLLARY 7.3 -- which stages are worth a snapshot: price instead of budget")
    rnd = random.Random(73)
    M = 150 if quick else 600
    ok = hull_ok = 0
    for _ in range(M):
        n = rnd.randint(2, 6)
        tree = fresh_sp(rnd, n)
        delta = rnd.choice([0.0, 2.0])
        opts = random_opts(rnd, n)
        mu = rnd.choice([0.0, 1.0, 10.0, 100.0, 1000.0])      # ms of latency one storage unit is worth
        front = pareto_front(tree, opts, delta)
        best_front = min(L + mu * s for s, L, _ in front)
        # independent: brute force over every assignment with the expanded-DAG evaluator
        best_bf = None
        for combo in itertools.product(*[range(len(opts[i])) for i in range(n)]):
            s = sum(opts[i][k][2] for i, k in enumerate(combo))
            L = eager(expand(tree, [(opts[i][k][0], opts[i][k][1]) for i, k in enumerate(combo)], delta))[0]
            best_bf = L + mu * s if best_bf is None else min(best_bf, L + mu * s)
        ok += abs(best_front - best_bf) < 1e-6
        # the minimiser of L + mu*s over the front is on its lower convex hull (never a point
        # strictly above the segment joining two neighbours)
        arg = min(front, key=lambda it: it[1] + mu * it[0])
        i = front.index(arg)
        inside = all(not (front[a][0] < arg[0] < front[b][0] and
                          arg[1] > front[a][1] + (front[b][1] - front[a][1]) * (arg[0] - front[a][0])
                          / (front[b][0] - front[a][0]) + 1e-9)
                     for a in range(i) for b in range(i + 1, len(front)))
        hull_ok += inside
    check(f"C7.3 min (latency + mu * storage) is attained on the DP's (storage, latency) front  [{M}]",
          ok == M, f"{ok}/{M} vs brute force over all assignments")
    check("C7.3 the chosen point lies on the front's lower convex hull", hull_ok == M, f"{hull_ok}/{M}")
    # cold-invocation rate under keep-alive TTL T with Poisson arrivals: lambda * exp(-lambda T),
    # largest at lambda = 1/T with value 1/(e T): very frequent AND very rare workflows gain least
    T = 600.0
    lams = [10 ** (k / 20) / T for k in range(-60, 61)]
    vals = [l * math.exp(-l * T) for l in lams]
    kmax = max(range(len(lams)), key=lambda k: vals[k])
    check("C7.3 cold invocations per second, lambda*exp(-lambda*T), peak at lambda = 1/T, value 1/(eT)",
          abs(lams[kmax] * T - 1) < 1e-9 and abs(vals[kmax] - 1 / (math.e * T)) < 1e-12,
          f"argmax lambda*T = {lams[kmax] * T:.3f}, max = {vals[kmax] * T:.4f}/T")
    # renewal Monte Carlo of the same quantity (independent of the formula)
    mc_ok = True
    for lamT in (0.1, 1.0, 5.0):
        lam = lamT / T
        g = random.Random(int(lamT * 100))
        t, cold, last = 0.0, 0, -math.inf
        for _ in range(600_000):
            t += g.expovariate(lam)
            cold += (t - last) > T
            last = t
        mc_ok &= abs(cold / t - lam * math.exp(-lam * T)) / (lam * math.exp(-lam * T)) < 0.05
    check("C7.3 renewal Monte Carlo agrees with lambda*exp(-lambda*T) (lambda T = 0.1, 1, 5)", mc_ok)
    # CONTROL: pretending every invocation is cold (rate lambda) makes rare workflows look
    # worth more than they are -- it ranks lambda*T = 5 above lambda*T = 1
    naive = lambda l: l
    check("CONTROL: rate lambda instead of lambda*exp(-lambda*T) mis-ranks frequent workflows",
          naive(5 / T) > naive(1 / T) and (5 / T) * math.exp(-5) < (1 / T) * math.exp(-1))


# ============================================================ T8 (peak memory, memory cap)
def peak_mem(g, tau, F):
    """max_t sum of m_v over stages holding memory at t (holding = [tau_v, F_v))."""
    return max(sum(g.m[u] for u in range(g.n) if tau[u] <= tau[v] < F[u]) for v in range(g.n))


def chain_slots(d, r, w, delta, k):
    """Equal-stage chain, look-ahead with at most k sandboxes alive at once (k memory slots),
    admission in stage order. Independent event computation (heap of slot-free times)."""
    import heapq
    slots = [0.0] * k
    F_prev, L = None, 0.0
    for v in range(d):
        tau = v * (w + delta)                           # JIT trigger (Theorem 2)
        start = max(tau, heapq.heappop(slots))
        I = 0.0 if v == 0 else F_prev + delta
        S = max(start + r, I)
        F_prev = S + w
        heapq.heappush(slots, F_prev)
    return F_prev


def chain_slots_rec(d, r, w, delta, k):
    """Theorem 8(b)'s recurrence: S_v = r + (v-1)(w+delta) for v <= k, then
    S_v = max(S_{v-k} + r + w, S_{v-1} + w + delta)."""
    S = []
    for v in range(d):
        if v < k:
            S.append(r + v * (w + delta))
        else:
            S.append(max(S[v - k] + r + w, S[v - 1] + w + delta))
    return S[-1] + w


def capped(g, C, lookahead=True, preempt=True, prio="tau"):
    """Event-driven single-workflow schedule under a hard memory cap C (C >= max m).
    Look-ahead: stage v asks for memory at its JIT trigger tau_v (on demand: at its input time).
    Queue order: stages whose input has arrived (demand) first, then by trigger time; strict
    head-of-line admission; a sandbox holds m_v from admission until the stage finishes.
    preempt: a demand stage that does not fit evicts admitted stages whose input has NOT
    arrived (latest trigger first); they re-queue and restore again later. Without it, memory
    can fill with look-ahead sandboxes that all wait on a stage that cannot get memory.
    prio="cp": among waiting stages, the one with the longest restore + remaining path
    (r_v + l(v)) goes first instead of the earliest trigger.
    Returns (L, peak, preemptions); L is None on deadlock."""
    import heapq
    _, _, tau_jit, _, _ = jit(g)
    ell = g.ell()
    rank = (lambda v: -(g.r[v] + ell[v])) if prio == "cp" else (lambda v: tau_jit[v] if lookahead else 0.0)
    ev, seq = [], 0

    def push(t, pri, kind, v, ver=0):
        nonlocal seq
        seq += 1
        heapq.heappush(ev, (t, pri, seq, kind, v, ver))
    npred = [len(g.preds[v]) for v in range(g.n)]
    I, ready, F = [None] * g.n, [None] * g.n, [None] * g.n
    admitted, ver = [False] * g.n, [0] * g.n
    queue, used, peak, npre = [], 0.0, 0.0, 0
    I[0] = 0.0
    push(0.0, 1, "input", 0)
    if lookahead:
        for v in range(g.n):
            push(tau_jit[v], 2, "trigger", v)
    queued = set()

    def admit(t):
        nonlocal used, peak, npre
        while queue:
            queue.sort(key=lambda v: (I[v] is None, rank(v) if (lookahead or prio == "cp") else I[v], v))
            v = queue[0]
            if used + g.m[v] > C + 1e-9 and preempt and I[v] is not None:
                victims = sorted((u for u in range(g.n) if admitted[u] and I[u] is None),
                                 key=lambda u: -tau_jit[u] if prio == "tau" else (g.r[u] + ell[u]))
                for u in victims:
                    if used + g.m[v] <= C + 1e-9:
                        break
                    admitted[u], ready[u] = False, None
                    ver[u] += 1                      # cancels its pending "ready"
                    used -= g.m[u]
                    queue.append(u)
                    npre += 1
            if used + g.m[v] > C + 1e-9:
                return
            queue.remove(v)
            admitted[v] = True
            used += g.m[v]
            peak = max(peak, used)
            push(t + g.r[v], 3, "ready", v, ver[v])

    def try_start(v):
        if ready[v] is not None and I[v] is not None and F[v] is None:
            F[v] = max(ready[v], I[v]) + g.w[v]
            push(F[v], 0, "finish", v)
    while ev:
        t, _, _, kind, v, vv = heapq.heappop(ev)
        if kind == "finish":
            used -= g.m[v]
            admitted[v] = False
            for s in g.succ[v]:
                npred[s] -= 1
                if npred[s] == 0:
                    I[s] = max(F[u] for u in g.preds[s]) + g.delta
                    push(I[s], 1, "input", s)
        elif kind == "input":
            if v not in queued:
                if not lookahead:
                    queued.add(v)
                    queue.append(v)
            try_start(v)
        elif kind == "trigger":
            if v not in queued:
                queued.add(v)
                queue.append(v)
        elif kind == "ready":
            if vv != ver[v]:
                continue
            ready[v] = t
            try_start(v)
        admit(t)
    if any(f is None for f in F):
        return None, peak, npre
    return max(F[v] for v in range(g.n) if not g.succ[v]), peak, npre


def t8(quick):
    hdr("THEOREM 8 -- peak memory of look-ahead, and look-ahead under a memory cap")
    rnd = random.Random(8)
    # (a) chain of d equal stages: on-demand peak m, JIT peak m * min(d, ceil((r+w)/(w+delta)))
    N = 500 if quick else 2000
    ok_a = more = 0
    for _ in range(N):
        d = rnd.randint(1, 12)
        r, w, delta, m = rnd.uniform(50, 3000), rnd.uniform(5, 500), rnd.choice([0.0, 2.0, 10.0]), 512.0
        g = DAG(d, [[]] + [[v - 1] for v in range(1, d)], [r] * d, [w] * d, [m] * d, delta)
        _, _, tj, _, Fj = jit(g)
        _, _, to, _, Fo = on_demand(g)
        pj, po = peak_mem(g, tj, Fj), peak_mem(g, to, Fo)
        ok_a += abs(pj - m * min(d, math.ceil((r + w) / (w + delta)))) < 1e-6 and abs(po - m) < 1e-6
        more += pj > po + 1e-6
    check(f"T8(a) chain: peak memory on-demand = m, just-in-time look-ahead = m*min(d, ceil((r+w)/(w+delta)))  [{N}]",
          ok_a == N, f"{ok_a}/{N}")
    print(f"      thesis numbers (r 650, w 75, delta 2): ceil(725/77) = {math.ceil(725 / 77)} -> an 8-stage Java chain "
          f"holds 8 x 512 MB = 4 GB at its peak under look-ahead, 512 MB on demand, for the same memory-time")
    # same memory-time (Theorem 2) but a higher peak: on random DAGs
    same_M = higher = 0
    for _ in range(N):
        g = random_dag(rnd)
        _, Mj, tj, _, Fj = jit(g)
        _, Mo, to, _, Fo = on_demand(g)
        same_M += abs(Mj - Mo) < 1e-6 * max(1.0, Mo)
        higher += peak_mem(g, tj, Fj) > peak_mem(g, to, Fo) + 1e-6
    check("T8(a) random DAGs: JIT memory-time = on-demand memory-time (Theorem 2) ...", same_M == N, f"{same_M}/{N}")
    check("CONTROL: ... but the PEAK is higher under look-ahead on most DAGs (so a cap is needed)",
          higher > N // 2, f"higher on {higher}/{N}")

    # (b) k memory slots on an equal-stage chain
    ok_rec = ok_mono = ok_sat = ok_one = ok_rate = 0
    M = 300 if quick else 1500
    for _ in range(M):
        d = rnd.randint(2, 14)
        r, w, delta = rnd.uniform(50, 3000), rnd.uniform(5, 500), rnd.choice([0.0, 2.0, 10.0])
        Ls = [chain_slots(d, r, w, delta, k) for k in range(1, d + 1)]
        ok_rec += all(abs(Ls[k - 1] - chain_slots_rec(d, r, w, delta, k)) < 1e-6 for k in range(1, d + 1))
        ok_mono += all(Ls[k] <= Ls[k - 1] + 1e-9 for k in range(1, len(Ls)))
        Lstar = r + d * w + (d - 1) * delta
        kstar = min(d, math.ceil((r + w) / (w + delta)))
        ok_sat += all((abs(Ls[k - 1] - Lstar) < 1e-6) == (k >= kstar) for k in range(1, d + 1))
        L_od = d * (r + w) + (d - 1) * delta
        ok_one += abs(Ls[0] - d * (r + w)) < 1e-6 and Ls[0] <= L_od + 1e-9
    for _ in range(50):
        r, w, delta = rnd.uniform(50, 3000), rnd.uniform(5, 500), 2.0
        k = rnd.randint(1, 8)
        span = 40 * k                       # the schedule repeats every k stages, shifted by r+w
        per = (chain_slots(100 + span, r, w, delta, k) - chain_slots(100, r, w, delta, k)) / span
        ok_rate += abs(per - max(w + delta, (r + w) / k)) < 1e-6 * max(w + delta, (r + w) / k)
    check(f"T8(b) k slots on a chain: event computation = the recurrence  [{M} chains, all k]", ok_rec == M, f"{ok_rec}/{M}")
    check("T8(b) latency is non-increasing in k (more memory never hurts on a chain)", ok_mono == M, f"{ok_mono}/{M}")
    check("T8(b) latency = L* exactly iff k >= min(d, ceil((r+w)/(w+delta)))", ok_sat == M, f"{ok_sat}/{M}")
    check("T8(b) one slot = d(r+w): never worse than on-demand, which is d(r+w)+(d-1)delta", ok_one == M, f"{ok_one}/{M}")
    check("T8(b) per-stage cost on long chains = max(w+delta, (r+w)/k): each slot divides the restore",
          ok_rate == 50, f"{ok_rate}/50 exact")
    r, w, delta = 650.0, 75.0, 2.0
    row = "  ".join(f"k={k}: {chain_slots(8, r, w, delta, k) / 1000:.2f}s" for k in (1, 2, 3, 4, 8))
    print(f"      8-stage Java chain (r 650, w 75): {row}  (on-demand {(8 * 725 + 14) / 1000:.2f}s)")

    # (c) heterogeneous chains and DAGs under a cap C (memory units, C >= max m)
    ok_inf = ok_jit_fit = tot = 0
    worse_od = nonmono = over = 0
    worse_od_dag = nonmono_dag = tot_dag = dead_nopre = worse_cp_dag = 0
    ratio_dag = []
    gaps = []
    for trial in range(M):
        is_chain = trial % 2 == 0
        g = random_dag(rnd, chain=is_chain)
        g.m = [rnd.choice([256.0, 512.0, 1024.0]) for _ in range(g.n)]
        _, _, tj, _, Fj = jit(g)
        pj = peak_mem(g, tj, Fj)
        Linf = capped(g, 1e18)[0]
        Lod_inf = capped(g, 1e18, lookahead=False)[0]
        ok_inf += abs(Linf - L_star(g)) < 1e-6 and abs(Lod_inf - on_demand(g)[0]) < 1e-6
        Lfit, pk, npre = capped(g, pj)
        ok_jit_fit += abs(Lfit - L_star(g)) < 1e-6 and pk <= pj + 1e-6 and npre == 0
        tot += 1
        caps = sorted({max(g.m) * f for f in (1, 1.5, 2, 3, 4, 6, 8)})
        runs = [capped(g, C) for C in caps]
        Lc = [x[0] for x in runs]
        over += sum(x[1] > C + 1e-6 for x, C in zip(runs, caps))
        Lo = [capped(g, C, lookahead=False)[0] for C in caps]
        dead_nopre += any(capped(g, C, preempt=False)[0] is None for C in caps)
        wo = any(a > b + 1e-6 for a, b in zip(Lc, Lo))
        nm = any(Lc[i + 1] > Lc[i] + 1e-6 for i in range(len(Lc) - 1))
        if is_chain:
            worse_od += wo
            nonmono += nm
            gaps.append((Lo[0] - Lc[0]) / (Lo[0] - L_star(g)) if Lo[0] > L_star(g) + 1e-6 else 1.0)
        else:
            tot_dag += 1
            worse_od_dag += wo
            nonmono_dag += nm
            Lcp = [capped(g, C, prio="cp")[0] for C in caps]
            worse_cp_dag += any(a > b + 1e-6 for a, b in zip(Lcp, Lo))
            ratio_dag += [b / a for a, b in zip(Lc, Lo)]
    check("T8(c) cap = infinity: the capped scheduler reproduces L* (look-ahead) and L_od (on demand) exactly",
          ok_inf == tot, f"{ok_inf}/{tot}")
    check("T8(c) cap >= the JIT schedule's own peak: latency stays L*, no preemption, cap never exceeded",
          ok_jit_fit == tot, f"{ok_jit_fit}/{tot}")
    check("T8(c) the cap is never exceeded, at any cap >= max m", over == 0, f"{over} violations")
    n_chain = tot - tot_dag
    check("T8(c) heterogeneous chains, any cap >= max m: capped look-ahead <= capped on-demand, "
          "and monotone in the cap", worse_od == 0 and nonmono == 0,
          f"worse than on-demand {worse_od}/{n_chain}, non-monotone {nonmono}/{n_chain}")
    check("CONTROL: without preemption, look-ahead sandboxes can fill the cap and deadlock the workflow",
          dead_nopre > 0, f"deadlock on {dead_nopre}/{tot} instances at some cap")
    print(f"      chains at the tightest cap (= max m): capped look-ahead keeps a median "
          f"{statistics.median(gaps):.0%} of the look-ahead gain")
    print(f"      general DAGs (measured, not claimed): capped look-ahead worse than capped on-demand on "
          f"{worse_od_dag}/{tot_dag} at some cap (critical-path priority instead: {worse_cp_dag}/{tot_dag}), "
          f"non-monotone in the cap on {nonmono_dag}/{tot_dag}; mean speedup over capped on-demand across caps "
          f"{statistics.mean(ratio_dag):.2f}x, worst {min(ratio_dag):.2f}x")
    T8_STATS.update(worse_od_dag=worse_od_dag, nonmono_dag=nonmono_dag, tot_dag=tot_dag)


T8_STATS = {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    t1(a.quick)
    c1()
    t2(a.quick)
    t3(a.quick)
    t4()
    l5()
    t6()
    p7()
    p8()
    t7(a.quick)
    c73(a.quick)
    t8(a.quick)
    hdr("SUMMARY")
    bad = [n for n, ok in results if ok is False]
    skipped = [n for n, ok in results if ok is None]
    for n, ok in results:
        print(f"  [{SKIP if ok is None else (PASS if ok else FAIL)}] {n}")
    print(f"\n  {sum(1 for _, ok in results if ok)}/{len(results)} checks passed"
          + (f", {len(skipped)} skipped" if skipped else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
