#!/usr/bin/env python3
"""Experiments that need a working CRIU -- written for the S0 box (x86_64, Ubuntu 24.04,
CRIU 4.2.1, see experiments/vm-setup/REMOTE-BOX.md). NOT run in the session that wrote
it: that VM's kernel lacks kcmp (CONFIG_CHECKPOINT_RESTORE), so `criu dump` fails there.
Treat as a protocol with a first-draft implementation; expect to fix small things.

  x1-ladder     activation latency + memory held, per readiness tier
                  cold JVM | restore from disk | restore from page cache |
                  pre-restored & stopped (criu --leave-stopped, then SIGCONT) | warm
  x2-parallel   restore N copies of one image at once -> r(N), i.e. the beta of dagsim
                  (uses podman: separate pid/net namespaces per copy)
  x3-rewarm     warm-up lost to the checkpoint (L_v(K)) and how much synthetic re-warming
                  during DAG slack recovers: restored-then-served vs restored-rewarmed-served
                  vs never-checkpointed (the continuation that exp-a used)
  x4-mispriming exp-a's comparison with REAL restores instead of continuation

Every experiment includes the never-checkpointed reference, which is the control:
restore-based numbers must be >= it, or the harness is wrong.

usage: sudo ./criu_box.py x1-ladder --reps 20 [--vcpu 1.0]
"""
import argparse
import http.client
import json
import os
import shutil
import signal
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
IDEAS = os.path.dirname(HERE)
INP = os.path.join(IDEAS, "exp-a-context-priming", "inputs")
CP = f"{HERE}/build:{IDEAS}/exp-a-context-priming/lib/*"
JAVA = os.environ.get("JAVA", "java")
# flags that keep a HotSpot process checkpointable by raw CRIU (hsperfdata mmap is the
# usual failure); adjust to whatever criu-smoketest.sh level 3 used on the box
JFLAGS = ["-XX:-UsePerfData", "-XX:+UseSerialGC", "-Xms256m", "-Xmx256m", "-Xshare:off"]
CG = "/sys/fs/cgroup"          # cgroup v2 on Ubuntu 24.04


def sh(cmd, check=True, **kw):
    return subprocess.run(cmd, shell=isinstance(cmd, str), check=check, capture_output=True, text=True, **kw)


def cgroup(name, vcpu):
    p = f"{CG}/{name}"
    os.makedirs(p, exist_ok=True)
    with open(f"{p}/cpu.max", "w") as f:
        f.write(f"{int(vcpu * 100000)} 100000")
    return p


def req(port, method, path, body=None, timeout=120):
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    c.request(method, path, body=body)
    r = c.getresponse()
    data = r.read().decode()
    us = r.getheader("X-Handler-Us")
    c.close()
    return r.status, data, (int(us) if us else None)


def wait_ready(port, deadline_s=60):
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < deadline_s:
        try:
            if req(port, "GET", "/ping", timeout=1)[0] == 200:
                return time.perf_counter() - t0
        except (OSError, http.client.HTTPException):   # half-restored server can answer garbage
            time.sleep(0.002)
    raise TimeoutError(f"port {port} not ready")


def start_server(port, cg):
    cmd = f"echo $$ > {cg}/cgroup.procs; exec setsid {JAVA} {' '.join(JFLAGS)} -cp '{CP}' FnServer {port}"
    p = subprocess.Popen(["sh", "-c", cmd], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    wait_ready(port)
    return p


def serve(port, file, n):
    lines = open(os.path.join(INP, file + ".jsonl")).read().splitlines()[:n]
    lat = []
    for body in lines:
        t0 = time.perf_counter()
        req(port, "POST", "/run", body)
        lat.append((time.perf_counter() - t0) * 1000)
    return lat


def prime(port, file, n):
    return req(port, "GET", f"/prime?file={os.path.join(INP, file)}.jsonl&n={n}")[1]


def dump(pid, img):
    shutil.rmtree(img, ignore_errors=True)
    os.makedirs(img)
    sh(["criu", "dump", "-t", str(pid), "-D", img, "--tcp-established", "-o", "dump.log", "-v2"])


def restore(img, extra=()):
    t0 = time.perf_counter()
    sh(["criu", "restore", "-D", img, "-d", "--tcp-established", "-o", "restore.log", "-v2", *extra])
    return time.perf_counter() - t0


def pid_on_port(port):
    out = sh(f"ss -ltnpH 'sport = :{port}'").stdout
    return int(out.split("pid=")[1].split(",")[0])


def rss_mb(pid):
    with open(f"/proc/{pid}/status") as f:
        for line in f:
            if line.startswith("VmRSS"):
                return int(line.split()[1]) / 1024
    return float("nan")


def mem_available_mb():
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith("MemAvailable"):
                return int(line.split()[1]) / 1024
    return float("inf")


def drop_caches():
    sh("sync; echo 3 > /proc/sys/vm/drop_caches")


def img_mb(img):
    return sum(os.path.getsize(os.path.join(img, f)) for f in os.listdir(img)) / 2 ** 20


def kill_port(port):
    try:
        os.kill(pid_on_port(port), signal.SIGKILL)
    except Exception:
        pass
    time.sleep(0.2)


# ------------------------------------------------------------------ x1
def x1_ladder(a):
    cg = cgroup("criubox", a.vcpu)
    port, img, rows = 18080, "/tmp/criubox-img", []
    for rep in range(a.reps):
        # build the snapshot: fresh JVM, K priming requests, checkpoint
        p = start_server(port, cg)
        prime(port, "real_bulk", a.K)
        time.sleep(1.0)
        pid = pid_on_port(port)
        dump(pid, img)
        size = img_mb(img)
        one = open(os.path.join(INP, "serve_bulk.jsonl")).readline()

        # T0 cold: new JVM from nothing, first request
        t0 = time.perf_counter()
        start_server(port, cg)
        req(port, "POST", "/run", one)
        rows.append(dict(rep=rep, tier="T0-cold", activate_ms=(time.perf_counter() - t0) * 1000, img_mb=size))
        kill_port(port)

        for tier, prep in (("T1-restore-disk", drop_caches),
                           ("T2-restore-pagecache", lambda: sh(f"cat {img}/* > /dev/null"))):
            prep()
            t0 = time.perf_counter()
            restore(img)
            wait_ready(port)
            req(port, "POST", "/run", one)
            rows.append(dict(rep=rep, tier=tier, activate_ms=(time.perf_counter() - t0) * 1000, img_mb=size))
            kill_port(port)

        # T3: restored ahead of need and left stopped; at "request time" only SIGCONT
        sh(f"cat {img}/* > /dev/null")
        restore(img, ["--leave-stopped"])
        spid = pid_on_port(port)          # the listening socket survives, stopped or not
        held = rss_mb(spid)
        t0 = time.perf_counter()
        os.kill(spid, signal.SIGCONT)     # SIGCONT resumes the whole thread group
        wait_ready(port)
        req(port, "POST", "/run", one)
        rows.append(dict(rep=rep, tier="T3-prerestored-stopped", activate_ms=(time.perf_counter() - t0) * 1000,
                         img_mb=size, held_rss_mb=held))
        # T4: warm process, second request
        t0 = time.perf_counter()
        req(port, "POST", "/run", one)
        rows.append(dict(rep=rep, tier="T4-warm", activate_ms=(time.perf_counter() - t0) * 1000,
                         held_rss_mb=rss_mb(spid)))
        kill_port(port)
        p.kill()
        print(json.dumps(rows[-5:]), flush=True)
    report(rows, "tier", "activate_ms")
    json.dump(rows, open(f"x1_ladder_vcpu{a.vcpu}.json", "w"), indent=1)


# ------------------------------------------------------------------ x2
def x2_parallel(a):
    """Needs podman. Checkpoint once, then restore N copies at the same instant."""
    img = "/tmp/fn-ckpt.tar.gz"
    sh("podman rm -f fnbase", check=False)
    sh(f"podman run -d --name fnbase -v {IDEAS}:/ideas:ro --cpus {a.vcpu} -p 19000:8080 "
       f"docker.io/library/eclipse-temurin:21-jdk java {' '.join(JFLAGS)} "
       f"-cp '/ideas/criu-box/build:/ideas/exp-a-context-priming/lib/*' FnServer 8080")
    wait_ready(19000)
    req(19000, "GET", f"/prime?file=/ideas/exp-a-context-priming/inputs/real_bulk.jsonl&n={a.K}")
    one = rss_mb(int(sh("podman inspect -f '{{.State.Pid}}' fnbase").stdout.strip()))
    sh(f"podman container checkpoint --export={img} fnbase")
    rows = []
    for N in (1, 2, 4, 8):
        # memory guard for the box itself: N restored copies must fit with 50% margin, or the
        # run would measure swapping instead of restore contention
        need, avail = 1.5 * N * one, mem_available_mb()
        if need > avail:
            print(f"N={N}: skipped, needs ~{need:.0f} MB (1.5 x {N} x {one:.0f} MB RSS), "
                  f"{avail:.0f} MB available", flush=True)
            continue
        for rep in range(a.reps):
            names = [f"fnr{i}" for i in range(N)]
            for nm in names:
                sh(f"podman rm -f {nm}", check=False)
            t0 = time.perf_counter()
            procs = [subprocess.Popen(["podman", "container", "restore", f"--import={img}", f"--name={nm}",
                                       "-p", f"{19100 + i}:8080"], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL) for i, nm in enumerate(names)]

            def ready_ms(i):   # each copy's own launch -> first /ping answered
                wait_ready(19100 + i)
                return (time.perf_counter() - t0) * 1000
            with ThreadPoolExecutor(N) as ex:
                r = list(ex.map(ready_ms, range(N)))
            for pr in procs:
                pr.wait()
            rows.append(dict(N=N, rep=rep, restore_ms_max=max(r), restore_ms_mean=statistics.mean(r),
                             restore_ms=r))
            for nm in names:
                sh(f"podman rm -f {nm}", check=False)
        print(N, statistics.median(x["restore_ms_max"] for x in rows if x["N"] == N), flush=True)
    base = statistics.median(x["restore_ms_max"] for x in rows if x["N"] == 1)
    for N in sorted({x["N"] for x in rows} - {1}):
        rN = statistics.median(x["restore_ms_max"] for x in rows if x["N"] == N)
        print(f"N={N}: r(N)/r(1) = {rN / base:.2f}  ->  dagsim beta ~ {(rN / base - 1) / (N - 1):.2f}")
    json.dump(rows, open(f"x2_parallel_vcpu{a.vcpu}.json", "w"), indent=1)


# ------------------------------------------------------------------ x3
def residual(lat, C):
    return sum(max(0.0, x - C) for x in lat)


def x3_rewarm(a):
    cg = cgroup("criubox", a.vcpu)
    port, img, rows = 18081, "/tmp/criubox-rw", []
    for rep in range(a.reps):
        for mode in ("continued", "restored", "restored+rewarm"):
            start_server(port, cg)
            prime(port, "real_bulk", a.K)
            time.sleep(1.0)
            if mode != "continued":
                dump(pid_on_port(port), img)
                sh(f"cat {img}/* > /dev/null")
                restore(img)
                wait_ready(port)
                if mode == "restored+rewarm":
                    # slack spent on SCRUBBED synthetic requests (fps_bulk): no user data enters
                    prime(port, "fps_bulk", a.rewarm_n)
            lat = serve(port, "serve_bulk", 200)
            rows.append(dict(rep=rep, mode=mode, lat=lat))
            kill_port(port)
        print(rep, flush=True)
    C = statistics.median(x for r in rows if r["mode"] == "continued" for x in r["lat"][-100:])
    for r in rows:
        r["R"] = residual(r["lat"], C)
    report(rows, "mode", "R")
    cont = statistics.median(r["R"] for r in rows if r["mode"] == "continued")
    rest = statistics.median(r["R"] for r in rows if r["mode"] == "restored")
    rw = statistics.median(r["R"] for r in rows if r["mode"] == "restored+rewarm")
    print(f"L(K) = restored - continued = {rest - cont:.1f} ms;  re-warming recovers "
          f"{100 * (rest - rw) / max(1e-9, rest - cont):.0f}% of it")
    json.dump(rows, open(f"x3_rewarm_vcpu{a.vcpu}_K{a.K}.json", "w"))


# ------------------------------------------------------------------ x4
def x4_mispriming(a):
    cg = cgroup("criubox", a.vcpu)
    port, img, rows = 18082, "/tmp/criubox-mp", []
    for rep in range(a.reps):
        for pset in ("real_bulk", "fps_bulk", "real_web", "mixed"):
            start_server(port, cg)
            prime(port, pset, a.K)
            time.sleep(1.0)
            dump(pid_on_port(port), img)
            sh(f"cat {img}/* > /dev/null")
            restore(img)
            wait_ready(port)
            rows.append(dict(rep=rep, pset=pset, lat=serve(port, "serve_bulk", 200)))
            kill_port(port)
    C = min(statistics.median(r["lat"][-100:]) for r in rows)
    for r in rows:
        r["R"] = residual(r["lat"], C)
    report(rows, "pset", "R")
    json.dump(rows, open(f"x4_mispriming_vcpu{a.vcpu}_K{a.K}.json", "w"))


def report(rows, key, val):
    for k in sorted({r[key] for r in rows}):
        xs = [r[val] for r in rows if r[key] == k]
        print(f"  {k:<26} n={len(xs):>3}  median {statistics.median(xs):9.1f}  "
              f"p90 {sorted(xs)[int(.9 * (len(xs) - 1))]:9.1f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exp", choices=["x1-ladder", "x2-parallel", "x3-rewarm", "x4-mispriming"])
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--vcpu", type=float, default=1.0)
    ap.add_argument("--K", type=int, default=100)
    ap.add_argument("--rewarm-n", type=int, default=50)
    a = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("run as root (criu, cgroups, drop_caches)")
    {"x1-ladder": x1_ladder, "x2-parallel": x2_parallel, "x3-rewarm": x3_rewarm,
     "x4-mispriming": x4_mispriming}[a.exp](a)


if __name__ == "__main__":
    main()
