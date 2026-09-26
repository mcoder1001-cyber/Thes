#!/bin/bash
# Fetch Jackson 2.17.2 (the only dependency) and build. Then: python3 gen_inputs.py
set -e
cd "$(dirname "$0")"
mkdir -p lib build
for a in jackson-databind jackson-core jackson-annotations; do
  [ -f lib/$a-2.17.2.jar ] || curl -sSfL -o lib/$a-2.17.2.jar \
    https://repo.maven.apache.org/maven2/com/fasterxml/jackson/core/$a/2.17.2/$a-2.17.2.jar
done
javac -d build -cp "lib/*" src/Fn.java
echo "built; now: python3 gen_inputs.py && sudo ./run_all.sh"
