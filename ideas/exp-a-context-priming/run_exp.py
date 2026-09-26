#!/usr/bin/env python3
"""Harness for exp-a (context-keyed priming) and exp-b (CPU-asymmetric priming).

Every run is a FRESH JVM placed in its own cgroup (v1: cpu + cpuset) before exec.
The JVM is "primed" on K requests from one input set -- the state a deep snapshot
taken at that point would contain -- then serves a fixed request set whose
per-request latency is recorded.

What this emulates and what it does not:
  * It emulates the CONTENT of a depth-K snapshot: a process that has served K
    requests of a given kind. Mis-priming effects (wrong type profiles, uncompiled
    paths, deoptimisation) are properties of that content and transfer to a restore.
  * It does NOT include CRIU's own restore cost r_v, nor the warm-up a real
    checkpoint loses (L_v(K) in MODEL.md §6b). Both are additive and independent of
    which input set was used for priming, so the comparisons between priming sets
    are unaffected; absolute residuals are optimistic.

JIT counters are read from the JVM's own hsperfdata file (no extra process, no CPU
charged to the measured cgroup).

usage:
  run_exp.py exp-a  [--reps N] [--slots 1,2,3]
  run_exp.py exp-a-web [--reps N]
  run_exp.py exp-b  [--reps N]
"""
import argparse
import json
import mmap
import os
import random
import struct
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
INP = os.path.join(HERE, "inputs")
RES = os.path.join(HERE, "results")
CP = f"{HERE}/build:{HERE}/lib/*"
CG_CPU = "/sys/fs/cgroup/cpu"
CG_SET = "/sys/fs/cgroup/cpuset"
PERIOD = 100_000


# ------------------------------------------------------------------ hsperfdata
def perf_counters(pid, names=("sun.ci.totalCompiles", "sun.ci.totalInvalidates",
                              "sun.ci.totalBailouts", "java.ci.totalTime",
                              "sun.os.hrt.frequency", "sun.ci.osrCompiles",
                              "sun.ci.standardCompiles")):
    """Parse /tmp/hsperfdata_<user>/<pid> (HotSpot PerfDataPrologue/PerfDataEntry)."""
    path = f"/tmp/hsperfdata_root/{pid}"
    try:
        with open(path, "rb") as f:
            buf = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    except OSError:
        return {}
    try:
        order = "<" if buf[4] == 1 else ">"
        entry_off, n = struct.unpack_from(order + "ii", buf, 24)
        out, off = {}, entry_off
        for _ in range(n):
            elen, name_off, vlen, dtype, _fl, _u, _v, doff = struct.unpack_from(order + "iiibbbbi", buf, off)
            end = buf.find(b"\0", off + name_off)
            name = buf[off + name_off:end].decode()
            if name in names and vlen == 0 and dtype == ord("J"):
                out[name] = struct.unpack_from(order + "q", buf, off + doff)[0]
            off += elen
        return out
    finally:
        buf.close()


def steal():
    with open("/proc/stat") as f:
        return int(f.readline().split()[8])


# ------------------------------------------------------------------ cgroups
def make_cgroup(name, cpus, quota_vcpu):
    for base in (CG_CPU, CG_SET):
        os.makedirs(f"{base}/{name}", exist_ok=True)
    with open(f"{CG_SET}/{name}/cpuset.cpus", "w") as f:
        f.write(cpus)
    with open(f"{CG_SET}/{name}/cpuset.mems", "w") as f:
        f.write("0")
    set_quota(name, quota_vcpu)


def set_quota(name, vcpu):
    with open(f"{CG_CPU}/{name}/cpu.cfs_period_us", "w") as f:
        f.write(str(PERIOD))
    with open(f"{CG_CPU}/{name}/cpu.cfs_quota_us", "w") as f:
        f.write(str(int(vcpu * PERIOD)))


def throttled(name):
    d = {}
    with open(f"{CG_CPU}/{name}/cpu.stat") as f:
        for line in f:
            k, v = line.split()
            d[k] = int(v)
    return d


# ------------------------------------------------------------------ one run
class JVM:
    def __init__(self, cg, flags):
        cmd = (f"echo $$ > {CG_CPU}/{cg}/cgroup.procs; echo $$ > {CG_SET}/{cg}/cgroup.procs; "
               f"exec java {' '.join(flags)} -cp '{CP}' Fn")
        env = dict(os.environ)
        env.pop("JAVA_TOOL_OPTIONS", None)       # keep the proxy options out of the measured JVM
        self.t_spawn = time.perf_counter()
        self.p = subprocess.Popen(["sh", "-c", cmd], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)

    def cmd(self, line):
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()
        out = self.p.stdout.readline().strip()
        if not out:
            raise RuntimeError(f"JVM died on: {line}")
        return out

    def run(self, file, label, n):
        t0 = time.perf_counter()
        out = self.cmd(f"RUN {os.path.join(INP, file)}.jsonl {label} {n}")
        wall = time.perf_counter() - t0
        lat = [int(x) for x in out.split(" ", 2)[2].split(",")] if n else []
        return lat, wall

    def close(self):
        try:
            self.cmd("QUIT")
        except Exception:
            pass
        self.p.wait(timeout=30)


def one_run(spec, slot_cpus, cg):
    """spec: dict(name, prime, K, serve, n_serve, q_prime, q_serve, settle_ms, flags)"""
    make_cgroup(cg, slot_cpus, spec["q_prime"])
    st0 = steal()
    jvm = JVM(cg, spec["flags"])
    rec = {"spec": spec, "cpus": slot_cpus}
    try:
        t0 = time.perf_counter()
        jvm.cmd(f"INIT {os.path.join(INP, spec['serve'])}.jsonl")
        rec["init_wall_s"] = time.perf_counter() - jvm.t_spawn
        if spec["K"] > 0:
            rec["prime_lat_us"], rec["prime_wall_s"] = jvm.run(spec["prime"], "prime", spec["K"])
        else:
            rec["prime_lat_us"], rec["prime_wall_s"] = [], 0.0
        jvm.cmd(f"SLEEP {spec['settle_ms']}")
        rec["jit_at_snapshot"] = perf_counters(jvm.p.pid)
        rec["thr_at_snapshot"] = throttled(cg)
        # ---- the "restore": from here on the process is what a depth-K snapshot holds
        if spec["q_serve"] != spec["q_prime"]:
            set_quota(cg, spec["q_serve"])
        rec["serve_lat_us"], rec["serve_wall_s"] = jvm.run(spec["serve"], "serve", spec["n_serve"])
        rec["jit_after_serve"] = perf_counters(jvm.p.pid)
        rec["thr_after_serve"] = throttled(cg)
        rec["total_wall_s"] = time.perf_counter() - t0
    finally:
        jvm.close()
    rec["steal_ticks"] = steal() - st0
    return rec


# ------------------------------------------------------------------ designs
BASE_FLAGS = ["-Xms256m", "-Xmx256m", "-XX:+UsePerfData"]


def design_exp_a(reps):
    specs = []
    for q in (1.0, 0.25):
        for prime in ("real_bulk", "real_bulk2", "fps_bulk", "schema_bulk", "real_web", "mixed"):
            for K in (25, 100, 400):
                specs.append(dict(name=f"a_q{q}_{prime}_K{K}", prime=prime, K=K))
        specs.append(dict(name=f"a_q{q}_none_K0", prime="none", K=0))
        specs.append(dict(name=f"a_q{q}_ref_K1500", prime="real_bulk", K=1500))
        for s in specs:
            s.setdefault("q_prime", q)
            s.setdefault("q_serve", q)
    for s in specs:
        s.update(serve="serve_bulk", n_serve=300, settle_ms=1000, flags=BASE_FLAGS)
    return [dict(s, rep=r) for s in specs for r in range(reps)]


def design_exp_a_web(reps):
    specs = []
    for q in (1.0, 0.25):
        for prime in ("real_web", "fps_web", "real_bulk", "mixed"):
            specs.append(dict(name=f"w_q{q}_{prime}_K100", prime=prime, K=100, q_prime=q, q_serve=q))
        specs.append(dict(name=f"w_q{q}_none_K0", prime="none", K=0, q_prime=q, q_serve=q))
        specs.append(dict(name=f"w_q{q}_ref_K1500", prime="real_web", K=1500, q_prime=q, q_serve=q))
    for s in specs:
        s.update(serve="serve_web", n_serve=300, settle_ms=1000, flags=BASE_FLAGS)
    return [dict(s, rep=r) for s in specs for r in range(reps)]


def design_exp_a_mix(reps):
    """Follow-up to exp-a: is 'mixed' worse only because it saw half as many target-edge
    requests? mixed_K2k contains k bulk requests, the same as real_bulk_Kk in exp-a."""
    specs = []
    for q in (1.0, 0.25):
        for K in (200, 800):
            specs.append(dict(name=f"a_q{q}_mixed_K{K}", prime="mixed", K=K, q_prime=q, q_serve=q))
    for s in specs:
        s.update(serve="serve_bulk", n_serve=300, settle_ms=1000, flags=BASE_FLAGS)
    return [dict(s, rep=r) for s in specs for r in range(reps)]


def design_exp_b(reps):
    """Prime on big, serve on small. All serving at 0.25 vCPU."""
    pinned = BASE_FLAGS + ["-XX:ActiveProcessorCount=1", "-XX:+UseSerialGC"]
    specs = []
    for tag, flags in (("pinned", pinned), ("ergo", BASE_FLAGS)):
        for K in (100, 400):
            for qp in (0.25, 1.0, 4.0):
                specs.append(dict(name=f"b_{tag}_prime{qp}_K{K}", prime="real_bulk", K=K,
                                  q_prime=qp, q_serve=0.25, flags=flags))
        specs.append(dict(name=f"b_{tag}_none_K0", prime="none", K=0, q_prime=0.25, q_serve=0.25, flags=flags))
        specs.append(dict(name=f"b_{tag}_ref_K1500", prime="real_bulk", K=1500, q_prime=4.0, q_serve=0.25,
                          flags=flags, settle_ms=3000))
    for s in specs:
        s.setdefault("settle_ms", 1000)
        s.update(serve="serve_bulk", n_serve=300)
    return [dict(s, rep=r) for s in specs for r in range(reps)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exp", choices=["exp-a", "exp-a-web", "exp-a-mix", "exp-b"])
    ap.add_argument("--reps", type=int, default=10)
    ap.add_argument("--slots", default="1,2,3", help="cpusets, one parallel worker each (exp-a*)")
    ap.add_argument("--only", default=None, help="substring filter on condition name")
    a = ap.parse_args()

    runs = {"exp-a": design_exp_a, "exp-a-web": design_exp_a_web, "exp-a-mix": design_exp_a_mix,
            "exp-b": design_exp_b}[a.exp](a.reps)
    if a.only:
        runs = [r for r in runs if a.only in r["name"]]
    random.Random(42).shuffle(runs)                  # interleave conditions against drift
    out_dir = os.path.join(RES, "exp-a" if a.exp == "exp-a-mix" else a.exp)
    os.makedirs(out_dir, exist_ok=True)
    todo = [r for r in runs if not os.path.exists(os.path.join(out_dir, f"{r['name']}__r{r['rep']}.json"))]
    print(f"{a.exp}: {len(runs)} runs, {len(todo)} to do", flush=True)

    if a.exp == "exp-b":
        slots = ["0-3"]                              # 4-vCPU priming needs the whole box
    else:
        slots = a.slots.split(",")
    lock, done = threading.Lock(), [0]
    free = list(range(len(slots)))

    def work(spec):
        with lock:
            i = free.pop()
        try:
            rec = one_run(spec, slots[i], f"fnexp{i}")
            with open(os.path.join(out_dir, f"{spec['name']}__r{spec['rep']}.json"), "w") as f:
                json.dump(rec, f)
        except Exception as e:                       # record, never silently drop
            with open(os.path.join(out_dir, f"{spec['name']}__r{spec['rep']}.err"), "w") as f:
                f.write(repr(e))
        finally:
            with lock:
                free.append(i)
                done[0] += 1
                if done[0] % 20 == 0:
                    print(f"  {done[0]}/{len(todo)}", flush=True)

    with ThreadPoolExecutor(max_workers=len(slots)) as ex:
        list(ex.map(work, todo))
    print("done", flush=True)


if __name__ == "__main__":
    sys.exit(main())
