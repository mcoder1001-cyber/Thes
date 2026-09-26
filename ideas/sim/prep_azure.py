#!/usr/bin/env python3
"""Azure Functions Invocation Trace 2021 -> one arrival stream per app (= one workflow).

Each app's most-invoked function is taken as the workflow's entry: its invocation start
times (end_timestamp - duration) become workflow arrivals. Other functions of the app
are treated as internal stages and not used as arrivals (using them would count one
workflow run several times).

Source: https://github.com/Azure/AzurePublicDataset (CC-BY 4.0), Zhang et al. SOSP'21.
usage: prep_azure.py <AzureFunctionsInvocationTraceForTwoWeeksJan2021.txt> [days]
"""
import collections
import csv
import gzip
import os
import sys

src = sys.argv[1]
days = float(sys.argv[2]) if len(sys.argv) > 2 else 14.0
horizon = days * 86400.0
cnt = collections.Counter()
rows = []
with open(src) as f:
    r = csv.reader(f)
    next(r)
    for row in r:
        if len(row) < 4:
            continue
        try:
            end, dur = float(row[2]), float(row[3])
        except ValueError:
            continue
        start = end - dur
        if 0 <= start < horizon:
            rows.append((row[0], row[1], start))
            cnt[(row[0], row[1])] += 1
top = {}
for (app, fn), c in cnt.items():
    if app not in top or c > cnt[(app, top[app])]:
        top[app] = fn
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", f"azure2021_entry_arrivals_{int(days)}d.csv.gz")
apps = sorted(top)
idx = {a: i for i, a in enumerate(apps)}
arr = sorted((s, idx[a]) for a, fn, s in rows if top[a] == fn)
with gzip.open(out, "wt") as g:
    g.write("t_s,app\n")
    for s, i in arr:
        g.write(f"{s:.3f},{i}\n")
print(f"{len(apps)} apps, {len(arr)} workflow arrivals in {days} days -> {out}")
