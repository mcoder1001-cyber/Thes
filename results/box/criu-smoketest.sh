#!/usr/bin/env bash
# Does CRIU actually work on this machine, and can it checkpoint a JVM?
#
# Four escalating levels. Level 3 is the one that decides whether the thesis
# can be built here: if CRIU cannot checkpoint and restore a JIT-warmed JVM,
# the whole snapshot mechanism has no foundation on this machine.
#
# Run as root (or via sudo): `sudo bash criu-smoketest.sh`
#
# LAYOUT MATTERS (fixed 2026-09-24, after two false failures):
#   * `criu -D <dir>` requires <dir> to ALREADY EXIST -- it will not create it.
#   * The checkpointed process's cwd and its open files must NOT live inside the
#     image directory. If they do, restore fails with
#     "Couldn't unlink remap ...: Directory not empty", because CRIU tries to
#     clean up a path that now contains its own dump files.
#   So: IMG (images) and STATE (process files) are separate trees, and every
#   target process is started with cwd=/.
set -uo pipefail

IMG=${IMG:-/var/tmp/criu-img}
STATE=${STATE:-/var/tmp/criu-state}
rm -rf "$IMG" "$STATE"; mkdir -p "$IMG" "$STATE"
cd /
PASS=0; FAIL=0
ok()  { echo "   PASS  $*"; PASS=$((PASS+1)); }
bad() { echo "   FAIL  $*"; FAIL=$((FAIL+1)); }
CRIU=$(command -v criu || echo /usr/local/sbin/criu)

echo "================================================================"
echo " CRIU smoke test   arch=$(uname -m)  kernel=$(uname -r)"
echo " criu: $($CRIU --version 2>&1 | head -1)"
echo "================================================================"

# ---------------------------------------------------------------- level 0
echo
echo "[0] kernel support"
if $CRIU check --all >"$STATE/check.log" 2>&1; then
  ok "criu check --all"
elif $CRIU check >/dev/null 2>&1; then
  ok "criu check (basic) - some optional features missing, usually fine"
  grep -E "^Warn" "$STATE/check.log" | tail -3 | sed 's/^/        /'
else
  bad "criu check - kernel lacks checkpoint/restore support"
  echo; echo "   STOP: nothing below will work."; exit 1
fi

# ---------------------------------------------------------------- level 1
echo
echo "[1] trivial process: counter in a loop"
cat > "$STATE/counter.sh" <<EOS
#!/bin/bash
i=0
while true; do i=\$((i+1)); echo \$i > $STATE/counter.val; sleep 0.2; done
EOS
chmod +x "$STATE/counter.sh"
setsid "$STATE/counter.sh" </dev/null >/dev/null 2>&1 &
sleep 2
PID=$(pgrep -f "$STATE/counter.sh" | head -1)
if [ -z "$PID" ]; then bad "could not start counter"; else
  B=$(cat "$STATE/counter.val")
  mkdir -p "$IMG/d1"
  if $CRIU dump -t "$PID" -D "$IMG/d1" --shell-job >"$STATE/dump1.log" 2>&1; then
    ok "dump a shell process (was at $B)"
    if $CRIU restore -D "$IMG/d1" --shell-job -d >"$STATE/restore1.log" 2>&1; then
      sleep 2; A=$(cat "$STATE/counter.val")
      [ "$A" -gt "$B" ] && ok "restore resumed counting ($B -> $A)" \
                        || bad "restored but not progressing"
    else
      bad "restore failed"; tail -5 "$STATE/restore1.log" | sed 's/^/        /'
    fi
  else
    bad "dump failed"; tail -5 "$STATE/dump1.log" | sed 's/^/        /'
  fi
  pkill -f "$STATE/counter.sh" 2>/dev/null
fi

# ---------------------------------------------------------------- level 2
echo
echo "[2] python process with libraries loaded"
cat > "$STATE/pyloop.py" <<EOS
import time, hashlib
state = {"n": 0, "tbl": {i: hashlib.sha256(str(i).encode()).hexdigest() for i in range(5000)}}
while True:
    state["n"] += 1
    open("$STATE/py.val", "w").write(str(state["n"]))
    time.sleep(0.2)
EOS
setsid python3 "$STATE/pyloop.py" </dev/null >/dev/null 2>&1 &
sleep 2
PYPID=$(pgrep -f "python3 $STATE/pyloop.py" | head -1)
if [ -z "$PYPID" ]; then bad "could not start python"; else
  B=$(cat "$STATE/py.val" 2>/dev/null || echo 0)
  mkdir -p "$IMG/d2"
  if $CRIU dump -t "$PYPID" -D "$IMG/d2" --shell-job >"$STATE/dump2.log" 2>&1 \
     && $CRIU restore -D "$IMG/d2" --shell-job -d >"$STATE/restore2.log" 2>&1; then
    sleep 2; A=$(cat "$STATE/py.val" 2>/dev/null || echo 0)
    [ "$A" -gt "$B" ] && ok "python checkpoint/restore ($B -> $A)" \
                      || bad "python restored but stalled"
  else
    bad "python checkpoint/restore"
    tail -4 "$STATE/dump2.log" "$STATE/restore2.log" 2>/dev/null | sed 's/^/        /'
  fi
  pkill -f "pyloop.py" 2>/dev/null
fi

# ---------------------------------------------------------------- level 3
echo
echo "[3] THE DECIDING TEST: a JIT-warmed JVM"
cat > "$STATE/Loop.java" <<EOS
import java.io.*;
public class Loop {
  static double hot(double[] d, int k) {
    double s = 0; for (double v : d) s += Math.sqrt(Math.abs(v * k + 1)); return s;
  }
  public static void main(String[] a) throws Exception {
    double[] d = new double[10000];
    for (int i = 0; i < d.length; i++) d[i] = i * 0.37;
    long n = 0; double acc = 0;
    for (int w = 0; w < 3000; w++) acc += hot(d, w);   // force C1/C2
    while (true) {
      acc += hot(d, (int) (n % 100)); n++;
      try (PrintWriter p = new PrintWriter("$STATE/jvm.val")) { p.println(n); }
      Thread.sleep(200);
    }
  }
}
EOS
(cd "$STATE" && javac Loop.java 2>/dev/null) || bad "javac not available"
if [ -f "$STATE/Loop.class" ]; then
  setsid java -XX:-UsePerfData -XX:+UseSerialGC -cp "$STATE" Loop </dev/null >/dev/null 2>&1 &
  sleep 6   # let JIT warm up
  JPID=$(pgrep -f "java .*Loop" | head -1)
  if [ -z "$JPID" ]; then bad "could not start JVM"; else
    B=$(cat "$STATE/jvm.val" 2>/dev/null || echo 0)
    mkdir -p "$IMG/d3"
    if $CRIU dump -t "$JPID" -D "$IMG/d3" --shell-job >"$STATE/dump3.log" 2>&1; then
      ok "DUMPED a JIT-warmed JVM (was at $B)"
      SZ=$(du -sh "$IMG/d3" | cut -f1)
      echo "         image size: $SZ"
      if $CRIU restore -D "$IMG/d3" --shell-job -d >"$STATE/restore3.log" 2>&1; then
        sleep 3; A=$(cat "$STATE/jvm.val" 2>/dev/null || echo 0)
        if [ "$A" -gt "$B" ]; then
          ok "RESTORED and still running ($B -> $A)  <-- the thesis is buildable here"
        else
          bad "restored but stalled - JVM did not resume"
        fi
      else
        bad "JVM restore failed"; tail -12 "$STATE/restore3.log" | sed 's/^/        /'
      fi
    else
      bad "JVM dump failed"; tail -12 "$STATE/dump3.log" | sed 's/^/        /'
    fi
    pkill -f "java .*Loop" 2>/dev/null
  fi
fi

# ---------------------------------------------------------------- level 4
echo
echo "[4] CRaC JDK present? (the supported path for checkpointing Java)"
if [ -x /opt/crac/bin/java ]; then
  /opt/crac/bin/java -XX:CRaCCheckpointTo="$IMG/cracdir" -version >/dev/null 2>&1 \
    && ok "CRaC JDK accepts -XX:CRaCCheckpointTo" \
    || bad "CRaC JDK present but rejected the flag"
else
  echo "   SKIP  no CRaC JDK at /opt/crac (optional; raw CRIU may be enough)"
fi

echo
echo "================================================================"
echo " passed: $PASS   failed: $FAIL"
[ "$FAIL" -eq 0 ] && echo " ALL GOOD - build here." \
                  || echo " Level 3 is the one that matters."
echo " images in $IMG   logs/state in $STATE"
echo "================================================================"
