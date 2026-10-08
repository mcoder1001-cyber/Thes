#!/usr/bin/env python3
"""T0: record the machine state into results/box/env.json (MACHINE_TEST_PLAN.md T0).
Run on the box, as root (criu check, drop_caches):
    sudo python3 results/box/collect_env.py <thes-commit> > results/box/env.json
No host names or user names are recorded (rule 7)."""
import json
import os
import re
import subprocess
import sys


def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def read(p):
    try:
        return open(p).read().strip()
    except OSError as e:
        return f"unavailable ({e.strerror})"


lscpu = dict(l.split(":", 1) for l in run("lscpu").splitlines() if ":" in l)
lscpu = {k.strip(): v.strip() for k, v in lscpu.items()}
mem = {l.split()[0].rstrip(":"): int(l.split()[1]) for l in read("/proc/meminfo").splitlines()}
vm = run("vmstat 1 6").splitlines()
hdr = vm[1].split()
steal = [int(l.split()[hdr.index("st")]) for l in vm[3:]]   # skip the since-boot line

env = {
    "date_utc": run("date -u +%FT%TZ"),
    "thes_commit": sys.argv[1] if len(sys.argv) > 1 else "unknown",
    "kernel": run("uname -r"),
    "os": run("lsb_release -ds"),
    "cpu_model": lscpu.get("Model name"),
    "cpus": int(lscpu.get("CPU(s)", 0)),
    "sockets": lscpu.get("Socket(s)"),
    "threads_per_core": lscpu.get("Thread(s) per core"),
    "numa_nodes": lscpu.get("NUMA node(s)"),
    "hypervisor": lscpu.get("Hypervisor vendor"),
    "mem_total_MB": mem["MemTotal"] // 1024,
    "swap_total_MB": mem["SwapTotal"] // 1024,
    "swap": run("swapon --show --noheadings") or "off",
    "steal_pct_5s": steal,
    "cgroup_fs": run("stat -fc %T /sys/fs/cgroup"),
    "cpufreq_governor": read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"),
    "transparent_hugepage": read("/sys/kernel/mm/transparent_hugepage/enabled"),
    "criu_version": run("criu --version").splitlines()[0],
    "criu_check": run("criu check"),
    "crac_java": run("/opt/crac/bin/java -version").splitlines()[1],
    "default_java": run("java -version").splitlines()[1],
    "podman": run("podman --version"),
    "podman_oci_runtime": run("podman info --format '{{.Host.OCIRuntime.Name}} {{.Host.OCIRuntime.Version}}'").splitlines()[0],
    "docker": run("docker --version"),
    "disk": run("lsblk -dno NAME,ROTA,MODEL /dev/sda"),
    "root_fs": run("findmnt -no FSTYPE /"),
    "tmp_fs": run("findmnt -no FSTYPE -T /tmp"),
    "drop_caches_works": run("sync; echo 3 > /proc/sys/vm/drop_caches && echo yes"),
    "openwhisk": "built from master at /opt/openwhisk-src (not running during T0-T6b)",
    "load_avg": read("/proc/loadavg"),
}
env["openwhisk_commit"] = run("git -C /opt/openwhisk-src rev-parse HEAD")
json.dump(env, sys.stdout, indent=1)
print()
