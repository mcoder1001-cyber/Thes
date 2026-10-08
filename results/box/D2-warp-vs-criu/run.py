#!/usr/bin/env python3
"""D2: CRaC's two checkpoint engines on the same function: Warp (Azul's, the default of the Zulu
CRaC JDK 21.0.12 on the box: CRaCEngine=warp) vs CRIU (-XX:CRaCEngine=criu).

Found 2026-10-08: D1, T1b and the grid all ran with the default engine, i.e. Warp, not CRIU.
This measures whether the thesis's numbers carry over to CRIU, and whether the grid's bimodal
deep-restore times (≈ 70 ms or ≈ 300 ms at 1 vCPU) belong to one engine.

Same app, cgroup and helpers as the grid (../T3-profile/grid.py: run(), cgroup /grid/run on cores
0-3). Images: engine x K in {0, 50} x 4, built at 1 vCPU. Restores: vCPU in {0.25, 1}, 20
repetitions, the four (engine, K) modes in random order per repetition. Raw: raw/*.jsonl.

usage: sudo python3 run.py
"""
import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault("GRID_RAW", os.path.join(HERE, "raw"))
sys.path.insert(0, os.path.join(HERE, "..", "T3-profile"))
import grid as G  # noqa: E402

WORK = "/var/tmp/d2"
ENG = {"warp": ["-XX:CRaCEngine=warp"], "criu": ["-XX:CRaCEngine=criu"]}


def main():
    os.makedirs(G.RAW, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    G.cg_init()
    G.quota(1.0)
    for e in ENG:
        for K in (0, 50):
            for i in range(G.NIMG):
                d = f"{WORK}/{e}_K{K}_{i}"
                G.shutil.rmtree(d, ignore_errors=True)
                r = G.run([G.J21, *G.SHAPE, *ENG[e], f"-XX:CRaCCheckpointTo={d}", "-Dckpt=true",
                           f"-Dpost={G.POST}", f"-Dwarm={K}", "-jar", G.APP])
                ok = os.path.isdir(d) and bool(os.listdir(d))
                r.pop("curve_ms")
                r.update(engine=e, K=K, i=i, ok=ok, bytes=G.du(d) if ok else 0, files=sorted(os.listdir(d))[:8] if ok else [])
                G.emit("images.jsonl", r)
                print("build", e, K, i, ok, r["bytes"] // 2 ** 20, "MB", flush=True)
    rnd = random.Random(2)
    modes = [(e, K) for e in ENG for K in (0, 50)]
    for v in (0.25, 1.0):
        G.quota(v)
        for rep in range(G.REPS):
            rnd.shuffle(modes)
            for e, K in modes:
                i = rep % G.NIMG
                r = G.run([G.J21, *ENG[e], f"-XX:CRaCRestoreFrom={WORK}/{e}_K{K}_{i}"])
                r.update(vcpu=v, rep=rep, engine=e, K=K, img=i)
                G.emit("restores.jsonl", r)
                print(f"v={v} rep={rep} {e} K={K} ttfr={r['ttfr_ms'] and round(r['ttfr_ms'])} cpu={r['cpu_s']:.2f}",
                      flush=True)


if __name__ == "__main__":
    main()
