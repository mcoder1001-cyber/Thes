#!/usr/bin/env python3
"""Size sweep for theory/ALGORITHM.md §3 and §5: how fast is the exact branch and bound, and
how far is the memory guard from the optimum, by workflow size (random chains and DAGs, caps
1-4x the largest stage). Search budget 200k nodes; unsolved instances are counted, not scored.
Slow at 10-stage DAGs (tens of minutes); the table in ALGORITHM.md covers 4-10 stages."""
import os
import random
import statistics
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_dag as vd  # noqa: E402

LIMIT = 200000


def main():
    rnd = random.Random(2)
    rows = []
    for n in (4, 6, 8, 10):
        for chain in (True, False):
            gaps, times, unsolved, tot = [], [], 0, 0
            for _ in range(40):
                g = vd.random_dag(rnd, n=n, chain=chain)
                g.m = [rnd.choice([256.0, 512.0, 1024.0]) for _ in range(g.n)]
                for f in (1, 1.5, 2, 3, 4):
                    C = max(g.m) * f
                    Lh, Lo, Lc = (vd.capped(g, C)[0], vd.capped(g, C, lookahead=False)[0],
                                  vd.capped(g, C, prio="cp")[0])
                    t0 = time.time()
                    Lx, _, nn = vd.exact_capped(g, C, ub=min(Lh, Lo, Lc) + 1e-6, limit=LIMIT)
                    times.append(time.time() - t0)
                    tot += 1
                    if nn > LIMIT:
                        unsolved += 1
                        continue
                    gaps.append(Lh / min(Lx, Lh, Lo, Lc) - 1)
            q, g2 = sorted(times), sorted(gaps)
            rows.append((n, "chain" if chain else "dag", tot, tot - unsolved, statistics.median(q) * 1e3,
                         q[int(.95 * (len(q) - 1))] * 1e3, q[-1] * 1e3,
                         sum(x < 1e-6 for x in g2) / len(g2), statistics.mean(g2), g2[int(.95 * (len(g2) - 1))], g2[-1]))
            print(f"n={n:2d} {'chain' if chain else 'DAG  '}: solved {tot - unsolved}/{tot}; exact time median "
                  f"{statistics.median(q) * 1e3:.1f} ms p95 {q[int(.95 * (len(q) - 1))] * 1e3:.0f} ms max {q[-1]:.1f} s"
                  f" | guard optimal {sum(x < 1e-6 for x in g2) / len(g2):.0%} gap mean {statistics.mean(g2):.1%} "
                  f"p95 {g2[int(.95 * (len(g2) - 1))]:.1%} max {g2[-1]:.1%}", flush=True)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "exact_scale.csv")
    with open(out, "w") as f:
        f.write("stages,shape,instances,solved,exact_ms_median,exact_ms_p95,exact_ms_max,guard_optimal_share,"
                "guard_gap_mean,guard_gap_p95,guard_gap_max\n")
        for r in rows:
            f.write(",".join(str(x) for x in r) + "\n")


if __name__ == "__main__":
    main()
