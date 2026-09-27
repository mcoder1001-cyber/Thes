"""Exact restore planner for one workflow under a memory cap (theory/ALGORITHM.md, Algorithm 2).

A stage is one activity [tau_v, tau_v + r_v + w_v) that holds m_v; an edge u -> v is the time lag
tau_v >= tau_u + r_u + w_u + delta - r_v (Lemma A1). With no cap, the earliest-start schedule of
this lag network is the just-in-time schedule. Under a cap C the problem is RCPSP/max; this is
branch and bound on minimal forbidden sets (Bartusch, Moehring and Radermacher 1988), the same
algorithm as theory/verify_dag.py:exact_capped, which checks that the two agree.

Standard library only, so the simulator does not depend on theory/.
"""
import math


def earliest_start(n, edges):
    """Longest paths from time 0 in a time-lag network; None on a positive cycle."""
    t = [0.0] * n
    for _ in range(n + 1):
        changed = False
        for u, v, lag in edges:
            if t[u] + lag > t[v] + 1e-9:
                t[v] = t[u] + lag
                changed = True
        if not changed:
            return t
    return None


def lag_network(preds, r, w, delta):
    p = [r[v] + w[v] for v in range(len(r))]
    return p, [(u, v, p[u] + delta - r[v]) for v in range(len(r)) for u in preds[v]]


def peak(t, p, m):
    """Most memory held at one instant by activities [t_v, t_v + p_v)."""
    return max((sum(m[u] for u in range(len(t)) if t[u] <= t[v] + 1e-9 < t[u] + p[u]) for v in range(len(t))),
               default=0.0)


def plan(preds, r, w, m, delta, cap, limit=2000, ub=math.inf):
    """Trigger times tau (relative to the workflow's arrival) minimising the latency with at most
    `cap` memory held at once. Returns (tau, latency, nodes, exact): tau is None if the search
    found no schedule within `limit` nodes; exact is False if it stopped at the limit."""
    n = len(r)
    p, base = lag_network(preds, r, w, delta)
    best = [ub, None]
    seen = set()
    nodes = [0]

    def makespan(t):
        return max(t[v] + p[v] for v in range(n))

    def violated(t):
        for s in sorted(set(t)):
            A = [v for v in range(n) if t[v] <= s + 1e-9 < t[v] + p[v]]
            if sum(m[v] for v in A) > cap + 1e-9:
                F = list(A)
                for x in sorted(A, key=lambda v: m[v]):
                    if sum(m[y] for y in F) - m[x] > cap + 1e-9:
                        F.remove(x)
                return F
        return None

    def rec(extra):
        nodes[0] += 1
        if nodes[0] > limit or extra in seen:
            return
        seen.add(extra)
        t = earliest_start(n, base + sorted(extra))
        if t is None or makespan(t) >= best[0] - 1e-9:
            return
        F = violated(t)
        if F is None:
            best[0], best[1] = makespan(t), t
            return
        kids = []
        for u in F:
            for v in F:
                if u != v:
                    e = extra | {(u, v, p[u])}
                    t2 = earliest_start(n, base + sorted(e))
                    if t2 is not None:
                        kids.append((makespan(t2), e))
        for lb, e in sorted(kids, key=lambda k: k[0]):
            if lb >= best[0] - 1e-9:
                break
            rec(e)

    rec(frozenset())
    return best[1], best[0], nodes[0], nodes[0] <= limit
