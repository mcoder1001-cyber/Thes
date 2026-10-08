#!/usr/bin/env python3
"""T1b: parallel CRaC restores in Docker -> the contention beta (MACHINE_TEST_PLAN.md T1b).

Workload: the D1 Spring Boot app (results/box/D1-aot-vs-crac/app), checkpointed once inside
a container after K = 50 requests, restored N times at once, each copy in its own container
with its own --cpus quota. The CRaC JDK and the app are bind-mounted read-only into a plain
ubuntu:24.04 image (no image build, no registry pull on the timed path); the snapshot
directory is mounted read-only into every copy.

Variants (one row per repetition):
  parallel     N copies launched at the same instant; ready_i = launch -> copy i's first
               response (the app prints FIRST_DONE_EPOCH_NS)
  serial       copy i launched when copy i-1 answered (the control: beta = 1)
  docker-noop  N containers at once running `date +%s%N` (Docker's own start-up cost and
               contention, control b)
beta(N) = (median r_max(N) / median r_max(1) - 1) / (N - 1), CI by bootstrap in analyze.py.

Cold means cold here as in an invoker with a local image store: the snapshot and the JDK
are in the host page cache (read before each repetition); no container survives a repetition.

usage: sudo python3 run.py --vcpu 1.0 0.25 --reps 20 --out raw/
"""
import argparse
import json
import os
import shutil
import subprocess
import threading
import time

IMG = "ubuntu:24.04"
APPDIR = "/var/tmp/d1/app"
CR = "/var/tmp/t1b/cr"
SHAPE = ["-XX:ActiveProcessorCount=1", "-XX:+UseSerialGC", "-Xms256m", "-Xmx512m"]
CAPS = os.environ.get("T1B_CAPS", "--privileged").split()
MOUNTS = ["-v", "/opt/crac:/opt/crac:ro", "-v", f"{APPDIR}:/app:ro"]


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def checkpoint(K):
    shutil.rmtree(CR, ignore_errors=True)
    os.makedirs(CR)
    sh("docker rm -f t1b-ck")
    p = subprocess.run(["docker", "run", "--name", "t1b-ck", *CAPS, *MOUNTS, "-v", f"{CR}:/cr", IMG,
                        "/opt/crac/bin/java", *SHAPE, "-XX:CRaCCheckpointTo=/cr", "-Dckpt=true",
                        f"-Dwarm={K}", "-Dpost=20", "-jar", "/app/craca.jar"],
                       capture_output=True, text=True, timeout=600)
    sh("docker rm -f t1b-ck")
    size = int(sh(f"du -sb {CR}").stdout.split()[0])
    ok = size > 10 << 20
    return ok, size, (p.stdout + p.stderr)[-1500:]


class Copy:
    """One container; records the wall-clock instant its first response is done."""

    def __init__(self, i, cmd):
        self.i, self.cmd, self.ready_ns, self.out = i, cmd, None, []
        self.ev = threading.Event()

    def start(self):
        self.p = subprocess.Popen(self.cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for ln in self.p.stdout:
            self.out.append(ln)
            if ln.startswith("FIRST_DONE_EPOCH_NS") or ln.strip().isdigit():   # app, or `date +%s%N`
                self.ready_ns = int(ln.split()[-1])
                self.ev.set()
        self.ev.set()


def one_rep(variant, N, vcpu, rep):
    sh(f"cat {CR}/* > /dev/null")
    names = [f"t1b-{i}" for i in range(N)]
    sh("docker rm -f " + " ".join(names))
    if variant == "docker-noop":
        mk = lambda i: ["docker", "run", "--rm", "--name", names[i], f"--cpus={vcpu}", *CAPS, *MOUNTS, IMG,
                        "date", "+%s%N"]
    else:
        mk = lambda i: ["docker", "run", "--rm", "--name", names[i], f"--cpus={vcpu}", *CAPS, *MOUNTS,
                        "-v", f"{CR}:/cr:ro", IMG, "/opt/crac/bin/java", "-XX:CRaCRestoreFrom=/cr"]
    copies = [Copy(i, mk(i)) for i in range(N)]
    t0 = time.time_ns()
    if variant == "serial":
        for c in copies:
            c.start()
            c.ev.wait(300)
    else:
        for c in copies:
            c.start()
        for c in copies:
            c.ev.wait(300)
    for c in copies:
        try:
            c.p.wait(300)
        except subprocess.TimeoutExpired:
            c.p.kill()
    r = [(c.ready_ns - t0) / 1e6 if c.ready_ns else None for c in copies]
    ok = [x for x in r if x is not None]
    row = dict(variant=variant, vcpu=vcpu, N=N, rep=rep, ready_ms=r,
               r_max_ms=max(ok) if len(ok) == N else None, r_mean_ms=sum(ok) / len(ok) if ok else None,
               failed=N - len(ok), t_epoch=t0,
               errors=["".join(c.out)[-600:] for c in copies if c.ready_ns is None])
    sh("docker rm -f " + " ".join(names))
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vcpu", type=float, nargs="+", default=[1.0, 0.25])
    ap.add_argument("--reps", type=int, default=20)
    ap.add_argument("--N", type=int, nargs="+", default=[1, 2, 4, 8])
    ap.add_argument("--K", type=int, default=50)
    ap.add_argument("--variants", nargs="+", default=["parallel", "serial", "docker-noop"])
    ap.add_argument("--out", default="raw")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    if sh(f"docker image inspect {IMG}").returncode:
        sh(f"docker pull -q {IMG}")
    ok, size, log = checkpoint(a.K)
    json.dump(dict(K=a.K, ok=ok, bytes=size, caps=CAPS, log=log), open(f"{a.out}/checkpoint.json", "w"), indent=1)
    print("checkpoint", ok, size, flush=True)
    if not ok:
        print(log)
        return
    with open(f"{a.out}/runs.jsonl", "a") as f:
        for vcpu in a.vcpu:
            for rep in range(a.reps):            # interleave variants and N within a repetition
                for variant in a.variants:
                    for N in a.N:
                        if variant == "serial" and N == 1:
                            continue             # identical to parallel N = 1
                        row = one_rep(variant, N, vcpu, rep)
                        f.write(json.dumps(row) + "\n")
                        f.flush()
                        print(f"vcpu={vcpu} rep={rep} {variant:11s} N={N} r_max={row['r_max_ms']} "
                              f"failed={row['failed']}", flush=True)


if __name__ == "__main__":
    main()
