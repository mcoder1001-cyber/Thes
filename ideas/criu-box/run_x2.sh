#!/bin/bash
# x2 in one command: parallel-restore contention (beta), the go/no-go for look-ahead restore
# (ROADMAP.md §3). Run on a machine whose kernel has CONFIG_CHECKPOINT_RESTORE, as root:
#   sudo ./ideas/criu-box/run_x2.sh [vcpu=1.0] [reps=20]
# Output: criu-box/x2_parallel_vcpu<vcpu>.json and .log, last lines print beta per N.
set -euo pipefail
VCPU=${1:-1.0}
REPS=${2:-20}
HERE=$(cd "$(dirname "$0")" && pwd)
IDEAS=$(dirname "$HERE")

# 1. preconditions
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }
CFG=$( (cat "/boot/config-$(uname -r)" || zcat /proc/config.gz) 2>/dev/null || true)
if [ -n "$CFG" ] && ! grep -q '^CONFIG_CHECKPOINT_RESTORE=y' <<<"$CFG"; then
  echo "this kernel ($(uname -r)) has no CONFIG_CHECKPOINT_RESTORE: CRIU cannot work here"; exit 1
fi
for t in criu podman javac python3; do
  command -v $t >/dev/null || { echo "missing: $t (podman: sudo apt install podman)"; exit 1; }
done

# 2. workload and inputs (skipped when already present)
cd "$IDEAS/exp-a-context-priming"
[ -f lib/jackson-databind-2.17.2.jar ] || ./fetch_deps.sh
[ -f inputs/real_bulk.jsonl ] || python3 gen_inputs.py
cd "$IDEAS"
mkdir -p criu-box/build
javac -d criu-box/build -cp "exp-a-context-priming/lib/*" \
  exp-a-context-priming/src/Fn.java criu-box/FnServer.java
podman image exists docker.io/library/eclipse-temurin:21-jdk \
  || podman pull docker.io/library/eclipse-temurin:21-jdk

# 3. run
cd "$HERE"
python3 criu_box.py x2-parallel --reps "$REPS" --vcpu "$VCPU" 2>&1 | tee "x2_parallel_vcpu${VCPU}.log"
