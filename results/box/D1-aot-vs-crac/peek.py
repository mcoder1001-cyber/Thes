#!/usr/bin/env python3
"""Quick look at a runs.jsonl while it is being written (not the analysis)."""
import json, sys
for l in open(sys.argv[1]):
    r = json.loads(l); c = r["curve_ms"]
    print(r["vcpu"], r["rep"], f'{r["mode"]:9s}', r["rc"], r["ttfr_ms"] and round(r["ttfr_ms"]),
          r["first_req_ms"] and round(r["first_req_ms"], 1), len(c),
          round(sorted(c)[len(c) // 2], 2) if c else None, round(r["cpu_s"], 2), r["cgroup"],
          (r["error"] or "")[-300:].replace("\n", " | "))
