#!/bin/bash
# T5 rerun (2026-10-08) after fixing the reset hook's reflection (jdk.crac.Context.register).
# Own app copy, work dir, cgroup and cores (4-7), so the grid running on 0-3 is untouched.
set -euo pipefail
cd "$(dirname "$0")/app"
JAVA_HOME=/opt/crac mvn -q -B package -DskipTests
rm -rf /var/tmp/t5 && mkdir -p /var/tmp/t5
/opt/crac/bin/java -Djarmode=tools -jar target/craca.jar extract --destination /var/tmp/t5/app
cd ..
mkdir -p raw/t5_rerun
GRID_CGNAME=t5 GRID_CPUS=4-7 GRID_WORK=/var/tmp/t5 GRID_RAW=$PWD/raw/t5_rerun python3 grid.py build_uniq uniq
