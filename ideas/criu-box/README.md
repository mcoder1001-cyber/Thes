# CRIU-box protocols (x1–x4)

These four experiments need a working CRIU, so they are meant for the S0 box
(`experiments/vm-setup/REMOTE-BOX.md`). **None of them has been run.** The session that wrote
them ran in a VM whose kernel lacks `kcmp` (`CONFIG_CHECKPOINT_RESTORE`), so `criu dump`
fails there with `kcmp failed ... Function not implemented`. `FnServer` itself was built and
smoke-tested there (`/ping`, `/prime`, `/run`, `/jit` all work). Everything that calls
`criu` is a first draft: read `criu_box.py` before trusting it.

Each protocol decides whether one idea in `../IDEAS.md` survives. Every one has a
**control whose answer is known in advance**: the never-checkpointed process, which
the restore-based numbers can match but not beat.

| id | measures | decides | kill criterion |
|---|---|---|---|
| **x1-ladder** | activation latency and memory held, per readiness tier: cold JVM · restore from disk · restore from page cache · pre-restored & stopped (`criu restore --leave-stopped`, then `SIGCONT`) · warm | Idea 1's mechanism and the ladder's tier costs (`dagsim` parameters `r`, `m`) | none; it is calibration |
| **x2-parallel** | wall-clock to restore N = 1, 2, 4, 8 copies of one image at once | Idea 1 itself: restore-ahead needs restores that run in parallel. Output: `beta = (r(N)/r(1) − 1)/(N − 1)` | **beta ≳ 0.7**: restores serialise and restore-ahead gains little (`dagsim` e5: 1.0× at beta = 1) |
| **x3-rewarm** | `L(K)` = warm-up lost to the checkpoint, and how much of it synthetic re-warming (scrubbed `fps_bulk` requests) recovers | Idea 4 | `L(K)` ≈ 0 at the target vCPU, or re-warming recovers < ~30% of it |
| **x4-mispriming** | exp-a's comparison (right edge / scrubbed / wrong edge / mixed) with **real restores** instead of process continuation | Ideas 2 and 3 hold after a real checkpoint | scrubbed priming ≥ 1.2× the real-traffic residual once `L(K)` is included |

## Setup

```bash
cd ideas/exp-a-context-priming && ./fetch_deps.sh && python3 gen_inputs.py
cd .. && javac -d criu-box/build -cp "exp-a-context-priming/lib/*" \
    exp-a-context-priming/src/Fn.java criu-box/FnServer.java
sudo ./criu-box/criu_box.py x2-parallel --reps 20 --vcpu 1.0   # needs podman
sudo ./criu-box/criu_box.py x1-ladder   --reps 20 --vcpu 1.0
sudo ./criu-box/criu_box.py x3-rewarm   --reps 20 --vcpu 0.25 --K 50
sudo ./criu-box/criu_box.py x4-mispriming --reps 20 --vcpu 0.25 --K 100
```

Run **x2 first**. It is the go/no-go for Idea 1, the same way `criu-smoketest.sh`
level 3 was for the snapshot phase.

## Known rough edges

* JVM flags for raw CRIU (`JFLAGS` in the script) are a guess: `-XX:-UsePerfData` avoids
  the usual hsperfdata mmap failure. Use whatever the smoketest's level 3 used.
* Raw `criu restore` reuses the dumped PIDs, so one image cannot be restored twice at once
  in the same PID namespace. That is why x2 goes through `podman container restore
  --import --name` (a new PID and network namespace per copy). Docker's checkpoint support
  is experimental and cannot restore one export into many containers.
* To do the same through CRaC instead of raw CRIU: CRaC's restore runs CRIU underneath,
  and extra CRIU options (e.g. `--leave-stopped`) have to go through the engine's
  option-passing mechanism. Check the Zulu CRaC docs for the exact variable on the
  installed version.
* x1's T3 tier measures only the `SIGCONT` → first response path. The memory it holds is
  the stopped process's RSS; with `--lazy-pages` that would drop, at the cost of page
  faults on the first request. That variant is worth adding once the base numbers exist.
