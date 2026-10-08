#!/usr/bin/env python3
"""D1: is CRIU (via CRaC) worth it against the JDK's own AOT cache? (decision experiment)

Same Spring Boot jar (app/, the exp12 workload), same cgroup quota, seven start modes:
  cold21    CRaC JDK 21, no snapshot                       (the JDK the restores use)
  c1_21     CRaC JDK 21, -XX:TieredStopAtLevel=1           (the no-snapshot JIT flag)
  crac_K0   CRaC restore, checkpoint after start-up        (SnapStart's point)
  crac_K50  CRaC restore, checkpoint after 50 requests     (exp15's knee at 1 vCPU)
  cold25    stock JDK 25, no cache                         (control for the JDK change)
  aot_K0    JDK 25 AOT cache, training = start-up only     (JEP 483/514)
  aot_K50   JDK 25 AOT cache, training = start-up + 50 req (+ JEP 515 method profiles)

Per run: ttfr_ms = launch -> first response done (wall clock, measured outside: the app
prints FIRST_DONE_EPOCH_NS), the first request's own latency, the 200 later requests, CPU
seconds and throttled periods from the run's cgroup. All runs share one cgroup path, so a
restored process cannot land in a different quota; each run's own /proc/self/cgroup is
recorded and checked. Host page cache is warm for every mode (jar, JDK, images, caches),
which is what an invoker with a local image store sees.

usage: sudo python3 run.py --vcpu 0.25 1.0 --reps 20 --out raw/
"""
import argparse
import json
import os
import random
import shutil
import subprocess
import time

HERE = os.path.dirname(os.path.abspath(__file__))
J21 = "/opt/crac/bin/java"
J25 = "/usr/lib/jvm/java-25-openjdk-amd64/bin/java"
APP = "/var/tmp/d1/app/craca.jar"             # extracted layout (AOT needs real jar files)
WORK = "/var/tmp/d1"
CG = "/sys/fs/cgroup/d1run"
# the serving shape for every mode: one CPU as the JVM sees it, a fixed GC and heap (exp-b)
SHAPE = ["-XX:ActiveProcessorCount=1", "-XX:+UseSerialGC", "-Xms256m", "-Xmx512m"]
POST = 200
NIMG = 4                                       # checkpoints / caches per depth, used round-robin
MODES = ["cold21", "c1_21", "crac_K0", "crac_K50", "cold25", "aot_K0", "aot_K50"]


def cg_setup(vcpu):
    os.makedirs(CG, exist_ok=True)
    open(f"{CG}/cpu.max", "w").write(f"{int(vcpu * 100000)} 100000")
    open(f"{CG}/memory.max", "w").write(str(4 << 30))


def cg_stat():
    d = dict(l.split() for l in open(f"{CG}/cpu.stat"))
    return int(d["usage_usec"]), int(d["nr_throttled"]), int(d["throttled_usec"])


def launch(cmd, timeout=600):
    """Run cmd inside the cgroup; return (launch_epoch_ns, stdout, rc, cpu_s, throttled, thr_s)."""
    u0, n0, t0u = cg_stat()
    t0 = time.time_ns()
    p = subprocess.run(["sh", "-c", f'echo $$ > {CG}/cgroup.procs; exec "$@"', "sh", *cmd],
                       capture_output=True, text=True, timeout=timeout, cwd="/")
    u1, n1, t1u = cg_stat()
    return t0, p.stdout + p.stderr, p.returncode, (u1 - u0) / 1e6, n1 - n0, (t1u - t0u) / 1e6


def parse(out):
    r, curve, in_curve = {}, [], False
    for ln in out.splitlines():
        if ln.startswith("POST_RESTORE_CURVE"):
            in_curve = True
            continue
        if in_curve and ln[:1].isdigit() and "," in ln:
            curve.append(int(ln.split(",")[1]) / 1e6)
            continue
        in_curve = False
        k, _, v = ln.partition(" ")
        if k in ("FIRST_AFTER_RESTORE_MS", "STEADY_MS"):
            r[k] = float(v)
        elif k == "FIRST_DONE_EPOCH_NS":
            r[k] = int(v)
        elif k == "CHECKPOINT_META":
            r["spring_ms"] = int(v.split()[0])
        elif k == "CGROUP":
            r["cgroup"] = v.strip()
    r["curve_ms"] = curve
    return r


def build_images(vcpu_build=1.0):
    """NIMG CRaC images and NIMG AOT caches per depth, built at 1 vCPU in the same cgroup."""
    cg_setup(vcpu_build)
    meta = []
    for K in (0, 50):
        for i in range(NIMG):
            d = f"{WORK}/img_K{K}_{i}"
            shutil.rmtree(d, ignore_errors=True)
            _, out, rc, cpu, *_ = launch([J21, *SHAPE, f"-XX:CRaCCheckpointTo={d}", "-Dckpt=true",
                                          f"-Dwarm={K}", f"-Dpost={POST}", "-jar", APP])
            ok = os.path.isdir(d) and os.listdir(d)
            size = int(subprocess.run(["du", "-sb", d], capture_output=True, text=True).stdout.split()[0]) if ok else 0
            meta.append(dict(kind="crac", K=K, i=i, rc=rc, ok=bool(ok), bytes=size, build_cpu_s=cpu,
                             tail=out[-400:] if not ok else ""))
            a = f"{WORK}/aot_K{K}_{i}.aot"
            if os.path.exists(a):
                os.remove(a)
            _, out, rc, cpu, *_ = launch([J25, *SHAPE, f"-XX:AOTCacheOutput={a}", "-Dexit_at_ckpt=true",
                                          f"-Dwarm={K}", "-jar", APP])
            ok = os.path.exists(a)
            meta.append(dict(kind="aot", K=K, i=i, rc=rc, ok=ok, bytes=os.path.getsize(a) if ok else 0,
                             build_cpu_s=cpu, tail=out[-400:] if not ok else ""))
            print(json.dumps(meta[-2:]), flush=True)
    return meta


def cmd_for(mode, i):
    base = [f"-Dwarm=0", f"-Dpost={POST}", "-jar", APP]
    return {
        "cold21": [J21, *SHAPE, *base],
        "c1_21": [J21, *SHAPE, "-XX:TieredStopAtLevel=1", *base],
        "crac_K0": [J21, f"-XX:CRaCRestoreFrom={WORK}/img_K0_{i}"],
        "crac_K50": [J21, f"-XX:CRaCRestoreFrom={WORK}/img_K50_{i}"],
        "cold25": [J25, *SHAPE, *base],
        "aot_K0": [J25, *SHAPE, f"-XX:AOTCache={WORK}/aot_K0_{i}.aot", "-Xlog:aot=error", *base],
        "aot_K50": [J25, *SHAPE, f"-XX:AOTCache={WORK}/aot_K50_{i}.aot", "-Xlog:aot=error", *base],
    }[mode]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vcpu", type=float, nargs="+", default=[0.25, 1.0])
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--modes", nargs="+", default=MODES)
    ap.add_argument("--out", default=os.path.join(HERE, "raw"))
    ap.add_argument("--skip-build", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if not a.skip_build:
        json.dump(build_images(), open(f"{a.out}/images.json", "w"), indent=1)
    rnd = random.Random(20261008)                       # the run order is random but recorded
    with open(f"{a.out}/runs.jsonl", "a") as f:
        for vcpu in a.vcpu:
            cg_setup(vcpu)
            for rep in range(a.reps):
                order = a.modes[:]
                rnd.shuffle(order)
                for mode in order:
                    i = rep % NIMG
                    t0, out, rc, cpu, thr, thr_s = launch(cmd_for(mode, i))
                    r = parse(out)
                    row = dict(vcpu=vcpu, rep=rep, mode=mode, img=i, rc=rc, cpu_s=cpu, nr_throttled=thr,
                               throttled_s=thr_s, launch_epoch_ns=t0,
                               ttfr_ms=(r["FIRST_DONE_EPOCH_NS"] - t0) / 1e6 if "FIRST_DONE_EPOCH_NS" in r else None,
                               first_req_ms=r.get("FIRST_AFTER_RESTORE_MS"), steady_min_ms=r.get("STEADY_MS"),
                               spring_ms=r.get("spring_ms"), cgroup=r.get("cgroup"), curve_ms=r["curve_ms"],
                               error=None if r.get("FIRST_DONE_EPOCH_NS") else out[-600:])
                    f.write(json.dumps(row) + "\n")
                    f.flush()
                    print(f"vcpu={vcpu} rep={rep} {mode:9s} ttfr={row['ttfr_ms']} cpu={cpu:.2f}s "
                          f"cg={row['cgroup']}", flush=True)


if __name__ == "__main__":
    main()
