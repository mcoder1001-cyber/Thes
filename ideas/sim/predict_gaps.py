#!/usr/bin/env python3
"""Can the platform predict when a cold workflow will be called? (Azure 2021, entry arrivals)

For every cold invocation (the workflow idled longer than the keep-alive TTL), check whether
its idle gap falls inside [p5, p99] of that workflow's earlier cold gaps: the window a
histogram policy (Shahrad et al., ATC '20) would pre-restore the entry in. Also report how long
the entry sandbox would be held per cold call, and how regular the gaps are.

Result (3 days): 86% of cold arrivals fall in the window, but the gaps are irregular
(median CV 1.28) and the entry would be held ~56 min per cold call -> not worth it; dropped.
"""
import gzip
import math
import os
import statistics
from bisect import insort

HERE = os.path.dirname(os.path.abspath(__file__))
TTL = 600.0


def main(days=3):
    arr = []
    with gzip.open(os.path.join(HERE, "data", f"azure2021_entry_arrivals_{days}d.csv.gz"), "rt") as f:
        next(f)
        for line in f:
            t, a = line.split(",")
            arr.append((float(t), int(a)))
    arr.sort()
    last, hist = {}, {}
    n = few = covered = early = late = 0
    held = 0.0
    for t, a in arr:
        if a in last:
            g = t - last[a]
            if g > TTL:
                n += 1
                h = hist.get(a, [])
                if len(h) >= 5:
                    lo = h[max(0, int(0.05 * (len(h) - 1)))]
                    hi = h[min(len(h) - 1, int(math.ceil(0.99 * (len(h) - 1))))]
                    if lo <= g <= hi:
                        covered += 1
                        held += g - lo          # entry held from the window start to arrival
                    elif g < lo:
                        early += 1
                    else:
                        late += 1
                        held += hi - lo
                else:
                    few += 1
                insort(hist.setdefault(a, []), g)
        last[a] = t
    m = n - few
    print(f"cold invocations (gap > {TTL:.0f} s): {n}; with >= 5 earlier cold gaps: {m}")
    print(f"  inside [p5, p99] of earlier gaps: {covered} ({covered / m:.0%}); earlier: {early}; later: {late}")
    print(f"  entry held per cold call: {held / m / 60:.1f} min on average")
    cv = sorted(statistics.pstdev(h) / statistics.mean(h) for h in hist.values() if len(h) >= 5)
    print(f"  workflows with >= 5 cold gaps: {len(cv)}; CV of gaps: median {cv[len(cv) // 2]:.2f}, "
          f"share below 0.5: {sum(c < 0.5 for c in cv) / len(cv):.0%}")


if __name__ == "__main__":
    main()
