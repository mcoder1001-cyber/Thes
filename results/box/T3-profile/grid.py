#!/usr/bin/env python3
"""The CRIU grid: T3 (profile r(K), R(K), s(K)), T4 (L(K), re-warm), T5 (uniqueness), T6 (cliff,
cold vs restored), T6b (speed-up and CPU cost, boost while starting, contention), and the
disk-vs-page-cache tier of T2, on the Spring Boot workload (app/, = D1's app + opt-in probes).

Phases (each writes its own raw/*.jsonl, one row per run, appended; never edited):
  build       images at 1 vCPU, serving shape: CRaC K in KS x NIMG; K=50 with rewarm=50 x NIMG;
              one uniqueness image with hooks off and one with hooks on            -> images.jsonl
  grid        per vCPU in VCPUS, REPS repetitions, modes in random order:          -> grid.jsonl
                cold        no snapshot, JVM pinned to 1 CPU (the serving shape)
                cold_np     no snapshot, JVM not pinned (sees the node's 8 CPUs)
                restore_K   CRaC restore of a depth-K image (image in page cache)
                cont_K      never checkpointed: K requests, then the same 200 (T4's floor)
                rewarm_K50  restore, then 50 re-warm requests, then the 200 (0.25 and 1 vCPU)
                disk_K50    restore after dropping the page cache (T2 tier 1; 0.25 and 1 vCPU)
  uniq        10 restores of each uniqueness image (1 vCPU)                       -> uniq.jsonl
  boost       start at 1 or 2 vCPU, quota lowered to 0.25 as soon as the first response is
              out; restore_K0, restore_K50, cold                                    -> boost.jsonl
  contention  2 and 4 K=50 restores at once on ONE core: equal split (quota 1/N each) vs one
              at a time at the full core (the e11 rule)                              -> contention.jsonl

All runs live in cgroup /grid/run (cpuset cores 0-3, socket 0; the simulator may use 4-7) so
a restored process cannot land in another quota; its /proc/self/cgroup is recorded.
Memory: cgroup memory.current sampled every 20 ms, max kept. CPU: cpu.stat before/after.

usage: sudo python3 grid.py all            (or a list of phases)
"""
import json
import os
import random
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw")
J21 = "/opt/crac/bin/java"
APP = "/var/tmp/grid/app/craca.jar"
WORK = "/var/tmp/grid"
CGP = "/sys/fs/cgroup/grid"
CG = f"{CGP}/run"
CPUS = os.environ.get("GRID_CPUS", "0-3")
SHAPE = ["-XX:ActiveProcessorCount=1", "-XX:+UseSerialGC", "-Xms256m", "-Xmx512m"]
UNPINNED = ["-XX:+UseSerialGC", "-Xms256m", "-Xmx512m"]
KS = [0, 1, 5, 20, 50, 100, 200]
CONT_KS = [0, 50, 200]
VCPUS = [float(x) for x in os.environ.get("GRID_VCPUS", "0.25 0.5 1 2 4").split()]
REPS = int(os.environ.get("GRID_REPS", "20"))
NIMG = 4
POST = 200


def w(path, v):
    with open(path, "w") as f:
        f.write(v)


def cg_init():
    os.makedirs(CGP, exist_ok=True)
    w("/sys/fs/cgroup/cgroup.subtree_control", "+cpu +cpuset +memory")
    w(f"{CGP}/cpuset.cpus", CPUS)
    w(f"{CGP}/cgroup.subtree_control", "+cpu +cpuset +memory")
    os.makedirs(CG, exist_ok=True)
    w(f"{CG}/memory.max", str(4 << 30))


def quota(vcpu, cg=CG):
    w(f"{cg}/cpu.max", f"{int(vcpu * 100000)} 100000")


def cpustat(cg=CG):
    d = dict(l.split() for l in open(f"{cg}/cpu.stat"))
    return int(d["usage_usec"]), int(d["nr_throttled"])


def drop_caches():
    subprocess.run("sync; echo 3 > /proc/sys/vm/drop_caches", shell=True)


def run(cmd, cg=CG, on_first=None, timeout=900):
    """Run cmd in cgroup cg, streaming stdout. on_first(): called when the first response is out
    (boost). Returns a dict of everything measured."""
    u0, n0 = cpustat(cg)
    peak, stop = [0], threading.Event()

    def sample():
        while not stop.is_set():
            try:
                peak[0] = max(peak[0], int(open(f"{cg}/memory.current").read()))
            except OSError:
                pass
            time.sleep(0.02)
    th = threading.Thread(target=sample, daemon=True)
    th.start()
    t0 = time.time_ns()
    p = subprocess.Popen(["sh", "-c", f'echo $$ > {cg}/cgroup.procs; exec "$@"', "sh", *cmd],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd="/")
    r, curve, in_curve, tail, first_seen_ns = {}, [], False, [], None
    deadline = time.time() + timeout
    for ln in p.stdout:
        tail.append(ln)
        tail = tail[-30:]
        if ln.startswith("POST_RESTORE_CURVE"):
            in_curve = True
            continue
        if in_curve and ln[:1].isdigit() and "," in ln:
            curve.append(int(ln.split(",")[1]) / 1e6)
            continue
        in_curve = False
        k, _, v = ln.strip().partition(" ")
        if k == "FIRST_DONE_EPOCH_NS":
            r["first_done_ns"] = int(v)
            first_seen_ns = time.time_ns()
            if on_first:
                on_first()
        elif k in ("FIRST_AFTER_RESTORE_MS", "STEADY_MS", "REWARM_MS"):
            r[k.lower()] = float(v)
        elif k == "CHECKPOINT_META":
            a = v.split()
            r.update(spring_ms=int(a[0]), codecache_ckpt=int(a[1]), compile_ms_ckpt=int(a[2]))
        elif k == "RESTORE_META":
            a = v.split()
            r.update(codecache_end=int(a[0]), compile_ms_end=int(a[1]))
        elif k == "CGROUP":
            r["cgroup"] = v
        elif k == "UNIQ":
            f, h = v.split()
            r.setdefault("uniq", {})[f] = h
        if time.time() > deadline:
            p.kill()
    rc = p.wait()
    stop.set()
    th.join()
    u1, n1 = cpustat(cg)
    r.update(rc=rc, launch_ns=t0, cpu_s=(u1 - u0) / 1e6, nr_throttled=n1 - n0, mem_peak_MB=peak[0] / 2 ** 20,
             curve_ms=curve, wall_ms=(time.time_ns() - t0) / 1e6)
    r["ttfr_ms"] = (r["first_done_ns"] - t0) / 1e6 if "first_done_ns" in r else None
    r["first_seen_lag_ms"] = (first_seen_ns - r["first_done_ns"]) / 1e6 if first_seen_ns and "first_done_ns" in r else None
    if r["ttfr_ms"] is None:
        r["error"] = "".join(tail)[-800:]
    return r


def du(d):
    return int(subprocess.run(["du", "-sb", d], capture_output=True, text=True).stdout.split()[0])


def emit(name, row):
    with open(os.path.join(RAW, name), "a") as f:
        f.write(json.dumps(row) + "\n")


# ------------------------------------------------------------------ build
def ckpt(d, props):
    shutil.rmtree(d, ignore_errors=True)
    r = run([J21, *SHAPE, f"-XX:CRaCCheckpointTo={d}", "-Dckpt=true", f"-Dpost={POST}", *props, "-jar", APP])
    ok = os.path.isdir(d) and bool(os.listdir(d))
    r.update(dir=d, ok=ok, bytes=du(d) if ok else 0)
    r.pop("curve_ms")
    return r


def phase_build():
    quota(1.0)
    jobs = [(f"{WORK}/img_K{K}_{i}", [f"-Dwarm={K}"], dict(kind="depth", K=K, i=i))
            for K in KS for i in range(NIMG)]
    jobs += [(f"{WORK}/img_rw50_{i}", ["-Dwarm=50", "-Drewarm=50"], dict(kind="rewarm", K=50, i=i))
             for i in range(NIMG)]
    jobs += [(f"{WORK}/img_uniq_{h}", ["-Dwarm=50", "-Duniq=true", f"-Dreset.hooks={h}"],
              dict(kind="uniq", K=50, hooks=h)) for h in ("off", "on")]
    for d, props, meta in jobs:
        r = ckpt(d, props)
        r.update(meta)
        emit("images.jsonl", r)
        print("build", meta, r["ok"], r["bytes"] // 2 ** 20, "MB", flush=True)


# ------------------------------------------------------------------ grid
def grid_cmd(mode, i):
    base = ["-Dwarm=0", f"-Dpost={POST}", "-jar", APP]
    if mode == "cold":
        return [J21, *SHAPE, *base]
    if mode == "cold_np":
        return [J21, *UNPINNED, *base]
    if mode.startswith("restore_K"):
        return [J21, f"-XX:CRaCRestoreFrom={WORK}/img_K{mode[9:]}_{i}"]
    if mode.startswith("disk_K"):
        return [J21, f"-XX:CRaCRestoreFrom={WORK}/img_K{mode[6:]}_{i}"]
    if mode == "rewarm_K50":
        return [J21, f"-XX:CRaCRestoreFrom={WORK}/img_rw50_{i}"]
    if mode.startswith("cont_K"):
        return [J21, *SHAPE, f"-Dwarm={mode[6:]}", f"-Dpost={POST}", "-jar", APP]
    raise ValueError(mode)


def phase_grid():
    rnd = random.Random(20261008)
    for v in VCPUS:
        quota(v)
        modes = ["cold", "cold_np"] + [f"restore_K{K}" for K in KS] + [f"cont_K{K}" for K in CONT_KS]
        if v in (0.25, 1.0):
            modes += ["rewarm_K50", "disk_K50"]
        for rep in range(REPS):
            order = modes[:]
            rnd.shuffle(order)
            for m in order:
                i = rep % NIMG
                if m.startswith("disk_"):
                    drop_caches()
                r = run(grid_cmd(m, i))
                r.update(vcpu=v, rep=rep, mode=m, img=i)
                emit("grid.jsonl", r)
                print(f"grid v={v} rep={rep} {m:11s} ttfr={r['ttfr_ms'] and round(r['ttfr_ms'])} "
                      f"cpu={r['cpu_s']:.2f} mem={r['mem_peak_MB']:.0f} cg={r.get('cgroup')}", flush=True)


# ------------------------------------------------------------------ uniq
def phase_uniq():
    quota(1.0)
    for h in ("off", "on"):
        for copy in range(10):
            r = run([J21, f"-XX:CRaCRestoreFrom={WORK}/img_uniq_{h}"])
            r.pop("curve_ms")
            r.update(hooks=h, copy=copy)
            emit("uniq.jsonl", r)
            print("uniq", h, copy, r.get("uniq"), flush=True)


# ------------------------------------------------------------------ boost
def phase_boost():
    rnd = random.Random(7)
    cells = [(b, m) for b in (1.0, 2.0) for m in ("restore_K0", "restore_K50", "cold")]
    for rep in range(REPS):
        rnd.shuffle(cells)
        for b, m in cells:
            quota(b)
            r = run(grid_cmd(m, rep % NIMG), on_first=lambda: quota(0.25))
            quota(0.25)
            r.update(boost_vcpu=b, after_vcpu=0.25, rep=rep, mode=m)
            emit("boost.jsonl", r)
            print(f"boost {b}->0.25 rep={rep} {m:11s} ttfr={r['ttfr_ms'] and round(r['ttfr_ms'])} "
                  f"lag={r['first_seen_lag_ms']} cpu={r['cpu_s']:.2f}", flush=True)


# ------------------------------------------------------------------ contention
def phase_contention():
    """N distinct K=50 images (different PIDs, so they can be restored side by side in one PID
    namespace) on one core (cpuset core 3), each copy in its own cgroup."""
    core = CPUS.split("-")[-1]
    par = f"{CGP}/cont"
    os.makedirs(par, exist_ok=True)
    w(f"{par}/cpuset.cpus", core)
    w(f"{par}/cgroup.subtree_control", "+cpu +memory")
    for N in (2, 4):
        cgs = []
        for c in range(N):
            p = f"{par}/c{c}"
            os.makedirs(p, exist_ok=True)
            cgs.append(p)
        for rep in range(REPS):
            for rule in ("equal", "one_at_a_time"):
                # after its first response a copy is throttled to 1% so it stops competing: only
                # the start-ups share the core, as in the CPU plan's model
                res, evs = [None] * N, [threading.Event() for _ in range(N)]
                for c, p in enumerate(cgs):
                    quota(1.0 / N if rule == "equal" else 1.0, p)

                def go(c):
                    def first():
                        quota(0.01, cgs[c])
                        evs[c].set()
                    res[c] = run([J21, f"-XX:CRaCRestoreFrom={WORK}/img_K50_{c}"], cg=cgs[c], on_first=first)
                    evs[c].set()
                ths = [threading.Thread(target=go, args=(c,)) for c in range(N)]
                t0 = time.time_ns()
                for c, t in enumerate(ths):
                    t.start()
                    if rule == "one_at_a_time":
                        evs[c].wait(300)        # the next start-up begins when this one answered
                for t in ths:
                    t.join()
                ready = [(x["first_done_ns"] - t0) / 1e6 if x.get("first_done_ns") else None for x in res]
                row = dict(N=N, rep=rep, rule=rule, ready_ms=ready, cpu_s=[x["cpu_s"] for x in res],
                           errors=[x.get("error") for x in res if x.get("error")])
                emit("contention.jsonl", row)
                print("contention", N, rule, rep, [r and round(r) for r in ready], flush=True)


def main():
    phases = sys.argv[1:] or ["all"]
    if phases == ["all"]:
        phases = ["build", "uniq", "contention", "boost", "grid"]
    os.makedirs(RAW, exist_ok=True)
    cg_init()
    env = dict(date=time.strftime("%FT%T"), cpus=CPUS, vcpus=VCPUS, reps=REPS, ks=KS, shape=SHAPE, phases=phases)
    emit("grid_runs_meta.jsonl", env)
    for ph in phases:
        print("=== phase", ph, flush=True)
        globals()[f"phase_{ph}"]()
    print("=== done", flush=True)


if __name__ == "__main__":
    main()
