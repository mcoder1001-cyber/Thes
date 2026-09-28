#!/usr/bin/env python3
"""The CPU plan for a workflow's start-ups: the exact optimum, and the online rule dagsim uses.

Model (fluid). A start-up (a snapshot restore plus the first request's residual warm-up, or a
cold boot plus the full warm-up) is CPU work U, in CPU-seconds. It runs at the CPU rate it is
given: its sandbox's own quota q, plus a share of the node's spare CPU P, at most c cores in all
(a JVM pinned to one CPU: c = 1). exp-b measured that 0.25 -> 1 vCPU makes the same JVM warm-up
4.2x faster for about the same CPU-seconds, so the speed-up is taken as linear up to c. After its
start-up a stage runs its steady work w (wall time at its quota) and passes its output on after
DELTA.

Key step (Theorem 1 of theory/DAG_SNAPSHOT_THEORY.md). Under look-ahead, the workflow finishes
by L if and only if every stage v is ready by D_v = arrival + L - l(v), l(v) = the warm path from
v to the end. So for a target L every start-up has its own deadline, and "can the node's CPU meet
L?" is preemptive deadline scheduling with rate caps: a max-flow (Horn 1974). Source -> job
(U_v); job -> sink privately (q x its window); job -> time slice k of its window ((c - q) x
|I_k|); slice k -> sink (P x |I_k|). Binary search on L gives the smallest reachable latency,
and the flow gives each start-up's CPU rate in each slice. For several workflows the same is
done with a common extra delay lam over each workflow's ideal latency (the fairest schedule).

The online rule ("slack", dagsim's boost="slack") recomputes at every event the constant rates
that minimise the largest lateness of the active start-ups, and shares any spare left equally.
main() compares it with the exact plan, an equal split (Cloud Run's startup boost, idealised)
and critical-path-first (earliest deadline first) on six cases; `python3 run_sim.py e11o`.
"""
import sys

DT = 0.001
DELTA = 0.002
EPS = 1e-9

# thesis values (ideas/sim/dagsim.py JAVA), CPU-seconds, for a 0.25-vCPU function
RESTORE = 0.650 + 0.063          # CRaC restore + residual warm-up at depth K=50
COLD = 2.510 + 0.370             # cold boot + full JIT warm-up
W_SHORT = 0.012 / 0.25           # steady run: 12 ms at 1 vCPU -> 48 ms at 0.25 vCPU


class Stage:
    def __init__(self, U, w, q=0.25, c=1.0):
        self.U, self.w, self.q, self.c = U, w, q, c


def chain(stages):
    return [(s, [] if i == 0 else [i - 1]) for i, s in enumerate(stages)]


def ell(wf):
    """Warm path from each stage to the end: its own w, plus delta and the longest successor."""
    succ = [[] for _ in wf]
    for v, (_, preds) in enumerate(wf):
        for u in preds:
            succ[u].append(v)
    L = [0.0] * len(wf)
    for v in reversed(range(len(wf))):
        L[v] = wf[v][0].w + max((DELTA + L[s] for s in succ[v]), default=0.0)
    return L


def _ideal(wf):
    l = ell(wf)
    return max(s.U / s.c + l[v] for v, (s, _) in enumerate(wf)), l


# ------------------------------------------------------------------ allocation rules
def _water_fill(items, rate, spare):
    free = [it for it in items if rate[it["id"]] < it["s"].c - 1e-12]
    while spare > 1e-12 and free:
        share = spare / len(free)
        nxt = []
        for it in free:
            add = min(share, it["s"].c - rate[it["id"]])
            rate[it["id"]] += add
            spare -= add
            if rate[it["id"]] < it["s"].c - 1e-12:
                nxt.append(it)
        if len(nxt) == len(free):
            break
        free = nxt
    return spare


def _slack(items, rate, spare, now):
    def rates(Lam):
        out = {}
        for it in items:
            T = it["D"] + Lam - now
            q, c = it["s"].q, it["s"].c
            out[it["id"]] = c if T <= EPS else min(c, max(q, it["rem"] / T))
        return out

    def extra(Lam):
        r = rates(Lam)
        return sum(r[it["id"]] - it["s"].q for it in items)
    lo, hi = -1e4, 1e4
    if extra(lo) <= spare:
        hi = lo
    else:
        for _ in range(60):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if extra(mid) <= spare else (mid, hi)
    r = rates(hi)
    for it in items:
        rate[it["id"]] = r[it["id"]]
    _water_fill(items, rate, max(0.0, spare - sum(r[it["id"]] - it["s"].q for it in items)))


def simulate(workflows, P, policy, plan_rates=None):
    """workflows: [(arrival, wf)]. policy: fixed | uniform | cp | slack | plan. All start-ups
    begin at their workflow's arrival (look-ahead). Returns (latencies, boost CPU-seconds)."""
    jobs = []
    for k, (t0, wf) in enumerate(workflows):
        Li, l = _ideal(wf)
        for v, (s, preds) in enumerate(wf):
            jobs.append(dict(id=len(jobs), wf=k, v=v, s=s, preds=preds, t0=t0, rem=s.U, ready=None,
                             inp=None, fin=None, D=t0 + Li - l[v]))
    by = {(j["wf"], j["v"]): j for j in jobs}
    t, boost = 0.0, 0.0
    while any(j["fin"] is None for j in jobs):
        for j in jobs:
            if j["inp"] is None:
                if not j["preds"]:
                    if t >= j["t0"] - 1e-12:
                        j["inp"] = j["t0"]
                else:
                    ps = [by[(j["wf"], u)] for u in j["preds"]]
                    if all(p["fin"] is not None for p in ps):
                        j["inp"] = max(p["fin"] for p in ps) + DELTA
        active = [j for j in jobs if t >= j["t0"] - 1e-12 and j["ready"] is None]
        rate = {j["id"]: j["s"].q for j in active}
        if policy == "uniform":
            _water_fill(active, rate, P)
        elif policy == "cp":
            spare = P
            for j in sorted(active, key=lambda j: (j["D"], j["id"])):
                add = min(spare, j["s"].c - j["s"].q)
                rate[j["id"]] += add
                spare -= add
        elif policy == "slack":
            _slack(active, rate, P, t)
        elif policy == "plan":
            I, R = plan_rates
            k = next((i for i, (a, b) in enumerate(I) if a - 1e-12 <= t < b), None)
            for j in active:
                rate[j["id"]] += R.get((j["id"], k), 0.0) if k is not None else 0.0
        for j in active:
            boost += (rate[j["id"]] - j["s"].q) * DT
            j["rem"] -= rate[j["id"]] * DT
            if j["rem"] <= 1e-9:
                j["ready"] = t + DT
        for j in jobs:
            if j["fin"] is None and j["ready"] is not None and j["inp"] is not None:
                j["fin"] = max(j["ready"], j["inp"]) + j["s"].w
        t += DT
        if t > 1e4:
            sys.exit("no progress")
    lat = [max(by[(k, v)]["fin"] for v in range(len(wf))) - t0 for k, (t0, wf) in enumerate(workflows)]
    return lat, boost


# ------------------------------------------------------------------ the exact plan
class MaxFlow:
    def __init__(self, n):
        self.g = [[] for _ in range(n)]

    def add(self, u, v, cap):
        self.g[u].append([v, cap, len(self.g[v])])
        self.g[v].append([u, 0.0, len(self.g[u]) - 1])
        return u, len(self.g[u]) - 1

    def flow(self, s, t):
        total = 0.0
        while True:
            level = [-1] * len(self.g)
            level[s] = 0
            q = [s]
            for u in q:
                for v, cap, _ in self.g[u]:
                    if cap > EPS and level[v] < 0:
                        level[v] = level[u] + 1
                        q.append(v)
            if level[t] < 0:
                return total
            it = [0] * len(self.g)

            def dfs(u, f):
                if u == t:
                    return f
                while it[u] < len(self.g[u]):
                    e = self.g[u][it[u]]
                    v, cap, rev = e
                    if cap > EPS and level[v] == level[u] + 1:
                        d = dfs(v, min(f, cap))
                        if d > EPS:
                            e[1] -= d
                            self.g[v][rev][1] += d
                            return d
                    it[u] += 1
                return 0.0
            while True:
                f = dfs(s, float("inf"))
                if f <= EPS:
                    break
                total += f


def feasible(workflows, P, lam, rates=False):
    """Can every start-up be ready by arrival + L_ideal + lam - l(v)? With rates=True also
    return the time slices and each job's shared-CPU rate in each slice."""
    J = []
    for t0, wf in workflows:
        Li, l = _ideal(wf)
        for v, (s, _) in enumerate(wf):
            J.append((t0, t0 + Li + lam - l[v], s))
    if any(D <= r + EPS for r, D, _ in J):
        return (False, None) if rates else False
    pts = sorted({x for r, D, _ in J for x in (r, D)})
    I = list(zip(pts, pts[1:]))
    n, m = len(J), len(I)
    S, T = 0, 1 + n + m
    mf = MaxFlow(T + 1)
    edges = {}
    for j, (r, D, s) in enumerate(J):
        mf.add(S, 1 + j, s.U)
        mf.add(1 + j, T, s.q * (D - r))
        for k, (a, b) in enumerate(I):
            if a >= r - EPS and b <= D + EPS:
                edges[(j, k)] = mf.add(1 + j, 1 + n + k, (s.c - s.q) * (b - a))
    for k, (a, b) in enumerate(I):
        mf.add(1 + n + k, T, P * (b - a))
    ok = mf.flow(S, T) >= sum(s.U for _, _, s in J) - 1e-6
    if not rates:
        return ok
    R = {}
    for (j, k), (u, idx) in edges.items():
        v, _, rev = mf.g[u][idx]
        a, b = I[k]
        R[(j, k)] = mf.g[v][rev][1] / (b - a)
    return ok, (I, R)


def plan(workflows, P):
    lo, hi = 0.0, 1.0
    while not feasible(workflows, P, hi):
        hi *= 2
    for _ in range(40):
        mid = (lo + hi) / 2
        lo, hi = (lo, mid) if feasible(workflows, P, mid) else (mid, hi)
    return feasible(workflows, P, hi, rates=True)[1]


def cases():
    java = lambda w=W_SHORT, U=RESTORE: Stage(U, w)
    return [
        ("3-stage Java chain", [(0.0, chain([java() for _ in range(3)]))], 1.0),
        ("5-stage chain, 1-s stages", [(0.0, chain([java(w=1.0) for _ in range(5)]))], 1.0),
        ("burst: 8 x 3-stage chains", [(0.1 * i / 8, chain([java() for _ in range(3)])) for i in range(8)], 2.0),
        ("3-stage chain, no snapshots", [(0.0, chain([java(U=COLD) for _ in range(3)]))], 1.0),
        ("burst: 8 chains, 1-s stages", [(0.1 * i / 8, chain([java(w=1.0) for _ in range(3)])) for i in range(8)], 2.0),
        ("5-stage chain, mixed stages", [(0.0, chain([java(w=1.0), java(), java(), java(w=0.5), java()]))], 0.5),
    ]


def controls():
    """Known answers: one start-up alone gets min(c, q + P); with no spare it runs at q."""
    ok = True
    one = [(0.0, chain([Stage(RESTORE, W_SHORT)]))]
    for pol, P, want in [("fixed", 1.0, RESTORE / 0.25 + W_SHORT), ("uniform", 1.0, RESTORE + W_SHORT),
                         ("slack", 1.0, RESTORE + W_SHORT), ("uniform", 0.5, RESTORE / 0.75 + W_SHORT)]:
        got = simulate(one, P, pol)[0][0]
        ok &= abs(got - want) < 2 * DT
    lat, _ = simulate(one, 1.0, "plan", plan(one, 1.0))
    ok &= abs(lat[0] - (RESTORE + W_SHORT)) < 2 * DT
    return ok


def main():
    print("e11o: the online rule vs the exact plan (fluid model, functions at 0.25 vCPU)")
    print(f"   controls (one start-up alone): {'PASS' if controls() else 'FAIL'}")
    rows = []
    for name, wfs, P in cases():
        out = {}
        for pol in ("fixed", "uniform", "cp", "slack"):
            out[pol] = simulate(wfs, P, pol)
        out["plan"] = simulate(wfs, P, "plan", plan(wfs, P))
        worst = {k: max(v[0]) for k, v in out.items()}
        print(f"   {name:28s} (spare {P}) slowest workflow, s: no boost {worst['fixed']:5.2f} | equal split "
              f"{worst['uniform']:5.2f} | critical first {worst['cp']:5.2f} | online rule {worst['slack']:5.2f} | "
              f"exact plan {worst['plan']:5.2f}   (online/exact {worst['slack'] / worst['plan']:.3f})")
        rows.append((name, P) + tuple(worst[k] for k in ("fixed", "uniform", "cp", "slack", "plan"))
                    + tuple(out[k][1] for k in ("uniform", "cp", "slack", "plan")))
    return rows


if __name__ == "__main__":
    main()
