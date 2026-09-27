# Notes on the committed papers (`ideas/*.pdf`)

Read 2026-09-27. For each paper: what it does, the numbers or data we can use, and what it
means for our approach, especially for the algorithm (question 5). The closing section,
**"What this means for us"**, collects the conclusions.

---

## A. Workflow-level cold-start work (closest to us)

### Xanadu — Daw, Bellur, Kulkarni, Middleware '20 (`xanadu.pdf`)
- **Problem.** "Cascading cold starts": each function in a chain is provisioned only when
  its trigger arrives, so overhead grows **linearly with chain length**. Measured on AWS Step
  Functions (R² = 0.993) and Azure Durable Functions (R² = 0.953), and on Knative and OpenWhisk.
  - Cold-start overhead is 48.5% (ASF) and 41.2% (ADF) of total runtime, against 13% warm.
  - With 500 ms functions the cascade reaches up to 90% of a 6-function workflow.
  - Keep-alive observed: ASF reclaims after ~10 min idle, ADF after ~20 min.
- **Mechanism.**
  1. The *most likely path* (MLP) through a DAG with XOR branches, from branch probabilities
     learned online (exponential averaging).
  2. *Speculative* provisioning of the MLP at workflow start, with an "aggressiveness"
     (look-ahead depth) knob.
  3. **Just-in-time (JIT) deployment:** a planning phase builds a timeline so that each
     container starts `startup time` before its expected invocation (Algorithm 2: delay =
     max over parents of their expected finish − own cold-start time).
  4. Implicit chains are detected with a request-header tag.
- **Cost model.** `C_D` = end-to-end latency − Σ function runtimes. `C_R` = memory × idle time
  before use. Penalty `φ = C_R · C_D`.
- **Numbers.**
  - Depth-10 chain of 5 s functions (Docker): overhead 4.85 s speculative vs 76.3 s Knative
    and 44.4 s OpenWhisk.
  - JIT vs speculative: JIT costs only 2.18× the memory of "cold" instead of up to 250×, and
    is ~10% *faster*, because starting all containers at once hits Docker's concurrency
    bottleneck. **This is exactly our β (restore contention).**
  - On random trees with misprediction: 29–45% overhead reduction.
- **For us — important.**
  - **The JIT timing rule is not new.** Xanadu already starts each downstream container
    "just in time" from profiled times. Our Theorem 2's `τ = S* − r` is the same rule, with a
    snapshot restore in place of a cold container.
  - What Xanadu lacks, and we have:
    - a *snapshot* whose provisioning time `r` is small enough to be **hidden** by upstream
      work (a 2.5 s cold container is not);
    - **proofs** of optimality and memory-minimality;
    - the choice of **which stages get snapshots, and how deep** (Theorem 7);
    - the **memory peak and guard** (Theorem 8);
    - **contention β** as a parameter (Xanadu observed it but did not model it).
  - Xanadu's evidence that "start everything at once" is *slower* than JIT is support for our
    Corollary 1.2 and for x2 on the box.
  - The novelty statement must say this plainly: *timing* is Xanadu's idea; applying it to
    **snapshots**, with guarantees and the depth/selection/memory decisions, is ours.

### ORION — Mahgoub et al., OSDI '22 (`ORION_OSDI22.pdf`)
- **Data: Azure Durable Functions production traces**, 6 datacenters, 1 week (Oct 2021),
  20–30 M DAG executions/day. Released with code at `github.com/icanforce/Orion-OSDI22`.
  - DAG **depth**: median **3**, P95 **8**, max 47.
  - **65% are linear chains**; width P95 37, max 10.9 K.
  - E2E time: 10 ms to 112 min; median 3.7 s, mean 48 s.
  - Invocations are heavily skewed: the top-5 DAGs are 46% of invocations.
    - **80% of DAGs run < 100 times/day, and these see a median 50% cold starts.**
    - DAGs run ≥ 100 times/day see a median 0.35% cold starts.
    - So keep-alive fails exactly for the rare DAGs. This is our target population, and it
      supports Theorem 6.
  - Variance is large: P95 = 80× P25 for the same DAG. Parallel-stage skew (slowest/fastest)
    is ≥ 2× in 98.2% of DAGs.
- **Performance model.** Latency is a *distribution*: series → **convolution**, parallel →
  **max** of CDFs (dependent versions for correlated stages; Pearson > 0.4; correlations at most
  pairwise). The E2E error is under 2.5% at P95.
- **Right pre-warming.** Choose a delay vector `d` (when to start initialising each stage's VM,
  relative to DAG start) to **minimise E2E latency subject to utilisation ≥ target**
  (utilisation = busy / (busy + idle)). `d₁ = 0`, because predicting DAG arrivals "is
  challenging". Solved by **best-first search in 100 ms steps**, a heuristic.
  - Zero-delay (eager) gives the lowest latency and the lowest utilisation; no pre-warm is the
    reverse.
- **Other optimisations.** Right-sizing (VM size per function to meet a P95 SLO at minimum cost;
  BFS again) and bundling of parallel invocations.
- **For us.**
  - ORION's pre-warm problem is our Theorems 2–3 **for cold VMs, solved heuristically**.
    - Deterministic durations: Theorem 2's JIT (`τ = S* − r`) is the exact optimum (latency
      `L*`, minimum idle memory) with no search.
    - Distributions: Theorem 3's **κ-quantile of the input-time distribution** is the exact
      optimum of the latency-vs-idle-cost trade-off. ORION's CONV/MAX model supplies exactly
      that distribution (`F_I` for each stage).
  - **Combining them is a concrete algorithmic improvement:** ORION's CONV/MAX gives the input
    time distribution, and our quantile rule turns it into the trigger. There's no BFS, and it
    is optimal per stage.
  - The depth/width/frequency data is the realistic DAG population for our simulations
    (the chain shares, and depths up to 8, match our e1/e7 settings).

### CIDRE — Liu, Cheng, Shen, Wang, Balaji, ASPLOS '25 (`CIDRE_ASPLOS25.pdf`; code: `github.com/nzc5ve/cidre_asplos25`; deployed at Alibaba FC)
- **Problem.** Keep-alive policies treat warm containers like cache objects, but concurrency
  creates two gaps:
  - *delayed warm starts*: waiting for a busy warm container can beat a cold start;
  - *imbalanced evictions*: bulk evictions hit functions that will be reused soon.
- **Mechanism.**
  1. *Speculative scaling*: start a cold start **and** wait for a busy container; whichever
     is ready first serves the request. The guarantee: **never worse than a cold start**.
     The conditional variant skips the cold start when containers will not be reused.
  2. *Eviction priority* (GDSF from FaasCache, made concurrency-aware):
     **`Priority = Clock + Freq × Cost / (Size × K)`**. `Cost` is provisioning time, `Size`
     memory, `K` the number of the function's warm containers. Evict the lowest priority.
- **Data.**
  - Alibaba FC: in **40.4%** of cold starts, cold-start time exceeds execution time.
  - Azure: cold-start time estimated as 1–3 ms per MB of memory.
- **Results.** Up to 75.1% fewer cold starts and 39.3% lower overhead than FaasCache,
  RainbowCake, IceBreaker, CodeCrunch and others.
- **For us.**
  - The **GDSF eviction formula** is the keep-alive part of our algorithm, with one change:
    `Cost` = the latency a stage *adds to its workflow* if it must be restored (from Theorem 7
    or Corollary 7.1), **not** its cold-start time. A hidden stage then has Cost ≈ 0 and is
    evicted first; the entry has the highest cost. This addresses the memory competition
    between look-ahead and keep-alive that e7b found.
  - Speculative scaling (race a restore against a busy warm container) is a cheap add-on for
    our demand starts, with the same "never worse" guarantee.

### MPC scheduler — Nguyen, Bhuyan, Elmroth, arXiv 2508.07640 (`MPC_ProactiveScheduling.pdf`)
- **Mechanism.** Per function, every Δt:
  1. forecast the invocations over a horizon `H` (Fourier/FFT fit);
  2. solve an MPC problem with cvxpy over the number of warm containers `w_k`, cold starts
     `x_k` and reclaims `r_k`. The objective is
     `α·max(0, λ_k − μ w_k)(L_cold + L_warm) + β·q_k L_warm + δ x_k + γ·max(0, μ w_k − λ_k) − η r_k`
     plus smoothness penalties;
  3. apply only the first step (receding horizon).
- **Results.** Built on OpenWhisk and Kubernetes: up to 85% lower P90 latency and 34% fewer
  resources. Relative to OpenWhisk's 10-minute TTL, 34.8% fewer warm containers and 64.3%
  shorter keep-alive (IceBreaker: 17.4% / 43%).
- **For us.** One function at a time, cold containers, and it relies on *predicting* arrivals.
  Our trace check (`sim/predict_gaps.py`) says the gaps before *cold* workflow arrivals are
  irregular. Useful as a **baseline** and as the "arrival-level" layer, which is orthogonal to
  our in-workflow timing. The **receding-horizon** idea (re-plan whenever state changes) fits
  our run-time planner: when a stage finishes early or late, recompute the remaining τ.

### Costless — Elgamal, Sandur, Nahrstedt, Agha, SEC '18 (`NEW_costless.pdf`)
- **Problem.** Minimise the **price** of an AWS Lambda workflow by fusing adjacent functions,
  placing them on edge or cloud, and choosing memory sizes, while keeping latency under a
  threshold.
- **Algorithm (the part that matters for us).** Build a **cost graph**: nodes are the
  (fused-function, placement, memory) choices along the workflow order, and every s–t path is
  one full solution. Each edge carries two weights, price and delay. Then solve the
  **Constrained Shortest Path (CSP)** problem: the minimum-price path with delay ≤ `T_thresh`.
  This is NP-hard in general and solved with **LARAC** (Lagrangian relaxation plus Dijkstra),
  `O(|E|² log² |E|)`. Parallel branches are first flattened into a sequence.
- **Results.** 35–57% lower price for 5–15% more latency on image-processing workflows.
- **For us.** This is the **known-problem template for our stage choice on chains**: a layered
  graph with one layer per stage and one node per option (cold, or snapshot at depth K, in
  local or remote storage), with edge weights latency and cost, solved as CSP. Two differences:
  - under look-ahead, a chain's latency is **not a sum** over stages
    (`max(W, P)`, Theorem 7), so plain CSP applies to *on-demand* latency only;
  - our (W, P) DP is the exact generalisation, and LARAC is the fast heuristic to cite for large
    instances.

### Function fusion — Lee, Yoon, Yeo, Oh, Sensors 2021 (`function-fusion.pdf`)
- **Idea.** Fusing two consecutive functions removes the second one's cold start. But fusing a
  **fan-out** serialises the parallel branches, so fusion can make things worse.
- **Model.** A recursive response-time model over the workflow DAG: a function costs
  `L_cold + L_invo + T_v`; a fan-out costs `L_fan + max` over sub-workflows; a conditional costs
  the probability-weighted sum. The greedy recursive algorithm RAOFS decides fusions item by
  item. Response time is 28–86% of the unfused original on five workflows.
- **For us.** The series-sum / parallel-max / branch-expectation recursion is the **on-demand
  special case** of our Theorem 7 recursion (compare `MODEL.md`), with the same structure.
  Fusion is a **competing way** to remove downstream cold starts. It costs independent scaling
  and parallelism (`IDEAS.md` §8 already dropped fusion plus one snapshot for the reason),
  so it is a baseline to compare against, not something to adopt.

### RightFusion — Sheshadri K R, J Lakshmi, IC2E '24 (`NEW_rightfusion.pdf`)
- QoS-aware fusion across edge and cloud with right-sized resources per fusion group, based
  on input size and QoS. **For us:** only background on fusion. Its decisions depend on input
  characteristics, which our no-inputs rule excludes.

### Scheduling methods to reduce FaaS response latency — Żuk & Rzadca, SBAC-PAD '20 (`scheduling methods.pdf`)
- **The formal model we need (question 5).** FaaS with compositions is a scheduling problem:
  - *jobs* (requests) are chains (or DAGs) of *tasks*, and each task belongs to a *family*
    (function) with duration `p_f`, memory `q_f` and **setup time `s_f`** (environment
    initialisation, the cold start);
  - an environment holds `q_f` from the moment its setup starts until it is removed;
  - each machine has capacity `Q` (a **multiple-knapsack** constraint);
  - the objective is mean response time.
  - It is NP-hard: it generalises knapsack and `P2 | chains | ΣC_j`.
  - The model is **clairvoyant**: durations and setups are learned from repeated invocations.
- **Heuristics, from classic scheduling.**
  - *Ordering*: FIFO, EF (existing environment first), SJF, SW (smallest remaining work),
    RT (release time).
  - *Removal*: LRU, **min setup-time removal**, min-family removal.
  - *Wait*: wait for a busy environment if it frees before a new setup would finish (HEFT-like;
    the same idea as CIDRE's delayed warm start).
  - ***Dependency-aware "start"***: when a task is scheduled, its successor is queued
    immediately with release time = the predecessor's completion, so **the successor's
    environment is set up in advance.** This is eager look-ahead with cold environments.
- **Result.** Simulation calibrated against real OpenWhisk (high Pearson correlation):
  composition-aware ("start") policies clearly beat myopic ones when setup times are long.
- **For us.**
  1. Our problem **is** this model with two extensions:
     - each family has *several setup modes* (cold boot, or restore from a snapshot of depth
       `K`, each with its own setup time, later work and storage);
     - setup may start *before* the task is released, but only after the workflow arrives
       (no clairvoyance about arrivals).
  2. Their "start" policy is our *eager* look-ahead. Theorem 2 shows **JIT** reaches the same
     latency with minimum memory·time, a strict improvement under their knapsack constraint.
  3. "Min setup-time removal" is FaasCache/CIDRE's cost term; with snapshots and a DAG the cost
     becomes the stage's *unhidden* restore time.

## B. Production data (for parameters and simulation)

### Serverless Cold Starts and Where to Find Them — Joosen et al. (Huawei), EuroSys '25 (`ColdStartsWhereToFindThem_EuroSys25.pdf`; data at `github.com/sir-lab/data-release`)
- **Scale.** A 31-day trace from Huawei Cloud: 5 regions, **85 billion requests, 11.9 million
  cold starts**, 12 M pods. The trace has cold-start *components* per pod: pod allocation,
  code deployment, dependency deployment and scheduling delay, plus runtime, trigger type and
  CPU/memory configuration.
- **Findings.**
  - Mean cold-start time ranges from **< 0.3 s (Region 3) to 3 s (Region 1)**, up to 7 s.
    Region 1 is dominated by dependency deployment and scheduling, Region 2 by pod allocation.
  - Keep-alive is **1 minute**. Many cold starts come from functions invoked slightly less
    often than that (for example timers), so "releasing resources sooner" would help them.
  - Strong daily and weekly periodicity. **Synchronous workflow triggers (`workflow-S`)** and
    API-gateway calls drive the daily peaks.
  - Runtimes: Python, Node.js and PHP are mostly timer-triggered; Java mostly API-gateway.
  - *Pod utility ratio* (useful lifetime / cold-start time) is proposed as a metric.
- **For us.**
  - It is a public trace with **measured cold-start time distributions**, and it has a
    workflow trigger type. It can replace our assumed `A` values in simulation, per runtime and
    region.
  - The 1-minute keep-alive and timer effect means the population we target is big: frequent
    cold starts where keep-alive barely misses.

### Characterizing FaaS Workflows on Public Clouds — Kulkarni et al., arXiv 2509.23013 (`CharacterizingFaaSWorkflows.pdf`)
- **Setup.** 6 workflows with 38 functions and 160 configurations on AWS Step Functions and
  Azure Durable Functions (standard and Netherite); ≈ 139 K workflow invocations.
- **Findings on cold starts.**
  - Cold starts **cascade in sequential workflows** and are less severe with parallel paths.
  - Azure shows large cold-start overheads across the container, runtime and function
    initialisation phases. The Image workflow, with the longest path, paid **252 s (74%)** on
    Azure standard. AWS Step Functions show little impact.
  - Cold-start overhead per queue edge is ≈ 1 s. Inter-function transfer grows with payload
    (≈ 2–3× from 45 KiB to 250 KiB) as the platforms switch to blobs.
- **For us.** Independent confirmation of the **linear cascade on public clouds** (the point
  of your question 4). Longest path = largest cascade is exactly `L_od = ℓ'(e)` (Theorem 1c).

### SeBS-Flow — Schmid, Copik, Calotoiu, Brandner, Koziolek, Hoefler, EuroSys '25 (`SeBS-Flow_EuroSys25.pdf`)
- **What.** A benchmark suite with a platform-independent workflow model, for AWS Step
  Functions, Google Cloud Workflows and Azure Durable Functions. **Six benchmarks**: Trip
  Booking (saga), Video Analysis, MapReduce, ML training, ExCamera, 1000Genome. There are also
  four microbenchmarks: a function chain, object storage, parallel invocations, and one more.
- **Workflow shapes** (from the literature they survey): 40% sequential; most use ≤ 10
  functions; median 3 distinct functions; 52% invoke one function in parallel; 25% have
  functions longer than a minute.
- **Cold starts.** Frequent on AWS and GCP and "a major factor influencing the slowdown and
  performance instability". Rare on Azure Durable (apps hold many invocations concurrently).
  They analyse the effect on the *critical path*.
- **For us.** The evaluation workloads for Stage 7. **Caveat:** mostly Python, so porting a
  subset to Java stays in the plan (the JIT gain is Java's). The critical-path framing matches
  our `L*` / `ℓ'(e)`.

### The High Cost of Keeping Warm — Kondrashov, Zhou, Wang, Ustiugov, arXiv 2509.03104 (`HighCostOfKeepingWarm.pdf`)
- **What.** An open serverless system that approximates AWS Lambda and Cloud Run scaling,
  driven by production traces.
- **Findings.**
  - **Instance churn costs 10–40% extra CPU** (relative to request handling), mostly on
    worker nodes.
  - **Memory over-provisioning is 2–10× what is actively used**, caused by the autoscaling
    and keep-alive policy.
  - Raising keep-alive from 30 s to 600 s cuts instance creation by 45%, and Knative's
    synchronous overhead from 30% to 12%; it stabilises beyond 600 s. At 10 minutes, cold
    starts are a few percent of invocations (close to AWS).
- **For us.**
  - Supports the claim that keep-alive memory is the real cost (Theorem 6), and that the
    platform's **memory budget binds** (Theorem 8, e7b).
  - "Churn costs CPU" means **restore CPU matters too**: look-ahead restores are not free
    CPU. The restores we trigger should be counted in the evaluation (e4 already reports
    restore counts).

## C. Snapshot and restore mechanics (what `r` really is)

### REAP — Ustiugov, Petrov, Kogias, Bugnion, Grot, ASPLOS '21 (`REAP_ASPLOS21.pdf`; vHive, Firecracker)
- **Finding.** A function restored from a (lazy) snapshot runs **95% slower on average** than a
  memory-resident one. The cost is thousands of **serial page faults** on the critical path;
  guest accesses lack locality, so disk read-ahead does not help. A cold invocation from a
  snapshot is still 1–2 orders of magnitude slower than warm.
- **Mechanism.** Functions touch a **stable working set** across invocations. REAP records it
  on the first invocation (the page list plus a compact working-set file taken from the
  snapshot), then **prefetches it with one disk read** and installs it eagerly (userfaultfd).
  This removes 97% of page faults and cuts cold-start latency **3.7×** on average.
- **For us.**
  1. "Restore time" hides a split: a **lazy** restore returns fast and holds little memory,
     then pays page faults inside the first request (our `w`). An **eager/prefetching**
     restore pays up front (our `r`) and holds full memory. Our model's `p` and `w` should be
     measured *per restore mode*: x1's tiers.
  2. **Look-ahead can hide the prefetch too.** Start a lazy restore early (cheap in memory),
     then prefetch the working set just in time. Memory is held only after prefetch, so this
     lowers the peak of Theorem 8.
  3. The working set is page *addresses* plus pages from the snapshot image, never request
     data. It is compatible with our no-inputs rule if recorded on a test request.

### Prebaking — Fireman, Silva, Pereira, Mafra, Valadares, FGCS 2024 (`Prebaking.pdf`)
- **What.** CRIU checkpoint/restore of the *runtime environment process* after initialisation,
  optionally **after warming up the runtime** so the JIT's optimised code path is in the image.
  Works with Docker and Podman, unprivileged.
- **Numbers.**
  - Start-up (no snapshot): **Java > 150 ms, up to 1100 ms** depending on application init;
    **Python 430–480 ms; JavaScript 83–150 ms**.
  - Prebaking cuts start-up **12–13×** for every function, and up to 25× for a well-snapshotted
    function. Runtime start-up overhead drops to 0 ms. Overall latency under cold start
    improves 40–270% (Markdown).
  - Warming up before the snapshot compiles the whole request path (this is our depth `K`).
- **For us.** The origin of the "K = 1" snapshot point in our plan (RESEARCH_PLAN S1). It gives
  **per-runtime start-up numbers** (Java 150–1100 ms, Python 430–480 ms, JS 83–150 ms) and
  confirms that CRIU-based restore is practical with Docker/Podman, i.e. our x2 path.

### Snapshot methods evaluation (Portuguese) — Silva, Pereira et al., arXiv 2105.13894 (`SnapshotMethodsEval.pdf`)
- **What.** Prebaking (CRIU) vs SEUSS (unikernel snapshots) on NoOp and Markdown functions.
- **Numbers.**
  - Median start: **Prebaking 8 ms**; SEUSS 12–14 ms (NoOp) and 12–13 ms (Markdown).
  - First-request penalty: SEUSS +6 ms (+9.6%); **Prebaking with warm-up −11 ms (−34%)**,
    because warm-up is in the image.
  - Dependency-heavy apps: ×19 faster start.
- **For us.** Direct evidence that **warm-up before the checkpoint lowers the first request's
  time**, our `R(K)` term. CRIU restores of small processes take milliseconds; our Spring Boot
  restores took 0.64–9 s mainly because of image size and CPU quota.

### Catalyzer — Du, Yu, Xia, Zang, Yan, Qin, Wu, Chen, ASPLOS '20 (`catalyzer.pdf`; adopted at Ant Financial)
- **What.** Restore a virtualised (gVisor) function instance from a checkpoint image, skipping
  initialisation ("init-less"). Memory and system state are recovered **on demand**. A new
  primitive **`sfork`** forks a running *template* sandbox.
- **Numbers.** < 1 ms start (C hello), **< 2 ms Java SPECjbb** vs 400 ms+ for gVisor restore;
  about 1000× over the gVisor baseline. Cold boot from image ~40 ms, warm boot via sfork ~12 ms.
- **For us.** Shows how small `r` can get with OS support. When `r` is tiny, look-ahead has
  little to hide, so our gain is largest for **stock CRIU/CRaC**, where `r` is 0.6–9 s. That is
  the thesis's no-kernel-change setting. It also marks a boundary to state: with Catalyzer-class
  restores, look-ahead matters less.

### SEUSS — Cadden, Unger, Awad, Dong, Krieger, Appavoo, EuroSys '20 (`SEUSS.pdf`)
- **What.** Deploy functions from **unikernel snapshots**, with page-level sharing across the
  whole software stack (a snapshot hierarchy).
- **Numbers.** Deployment drops from hundreds of ms to **< 10 ms**; throughput 51× on new
  functions; **50,000 cached instances vs 3,000** with standard OS techniques.
- **For us.** Page sharing makes cached instances cheap. In our terms it shrinks `m` of idle or
  restored-waiting sandboxes, and so the peak of Theorem 8. It needs a custom OS, so it is
  outside our no-kernel-change constraint.

### Replayable Execution — Wang, Ho, Wu (Huawei), EuroSys '19 (`Replayable Execution Optimized.pdf`)
- **What.** Checkpoint a **warmed-up JVM** (trained with a training function and a fixed number
  of HTTP requests), then restore by **`mmap`ing the image**. The Linux page cache keeps **one
  shared copy** across all containers restored from it, and each process grows its private
  pages by copy-on-write. This relies on "intensive-deflated" execution: a heavy framework
  init, then a small working set.
- **Numbers.** **2× less memory, > 10× faster start-up** for Huawei's Java FaaS framework, with
  no kernel or runtime changes.
- **For us — directly useful for Theorem 8.**
  - With mmap/CoW restore, the memory a look-ahead sandbox holds is its **private dirty pages**,
    not its whole image. The shared image is counted **once per host**.
  - For fan-out stages (the same function restored N times) and concurrent workflows, the
    peak becomes `Σ_distinct images + Σ private`, much less than `N·m`.
  - This is a no-kernel-change way to cut the peak. It's worth an x1 variant: CRaC/CRIU
    restore vs mmap-style restore, measuring RSS vs PSS (proportional set size).

### Restoring Uniqueness in MicroVM Snapshots — Brooker et al. (AWS), arXiv 2102.12892 (`RestoringUniqueness_MicroVM.pdf`)
- **What.** Post-init snapshots, cloned and restored, raise two problems:
  - **secrets** stored in memory;
  - **uniqueness**: every clone shares RNG state, UUID generators, nonces and TLS state.
  The paper surveys fixes and proposes two kernel/VMM interfaces: **`MADV_WIPEONSUSPEND`**
  (wipe marked pages when the VM is suspended) and **`VmGenId`** (a generation counter that
  tells software it was cloned).
- **Lambda timeline.** MicroVM boot ~200 ms; code download 20 ms to 60 s; init is the "cold
  start"; invoke < 10 ms warm.
- **For us.** This is the safety basis for build-time step 4 (reset hooks). The danger exists
  **even with zero requests** in the image, so it does not depend on the dropped priming idea.
  The Stage 5 control ("two restored copies must produce different random numbers and UUIDs")
  is exactly the property this paper asks for. With CRaC, the `afterRestore` hooks play
  `VmGenId`'s role.

### Spice: Taming Serverless Cold Starts Through OS Co-Design — Holmes, Dinis, Honcharuk, Fried, Belay (MIT), arXiv 2509.14292, OSDI '26 (`TamingColdStarts_OSCoDesign.pdf`)
- **Finding.** OS-level limits, not storage speed, block fast restores from disk. **CRIU**
  restores kernel state by **replaying long sequences of system calls**, stages snapshot data in
  temporary regions, and updates page tables page by page. VM-based systems (REAP, FaaSnap)
  over-capture state or fault pages at run time. Even tuned systems are **orders of magnitude
  slower than ideal**; CRIU restores reach seconds for larger Python/Node/Java functions.
- **Mechanism.** An OS-integrated restore engine with dedicated primitives for kernel state and
  memory mappings.
- **Numbers.** Near-warm performance from disk: **up to 14.9× faster than process-based (CRIU)**
  and 10.6× faster than VM-based restores.
- **For us.**
  - CRIU's restore cost is largely **CPU work (syscall replay)**. Parallel restores may compete
    for CPU, so **β on a small box can be large**. That is precisely what x2 measures.
  - It also bounds our claims. With Spice-class restores, `r` shrinks and look-ahead matters
    less. Our setting (stock CRIU/CRaC, no kernel change) is where look-ahead matters most, and
    Spice is **complementary**: faster restores plus look-ahead compose.

### Fork in the Road (AFaaS) — Chai et al. (Tsinghua / Ant Group), OSDI '25 (`ForkInTheRoad_OSDI25.pdf`; in production > 18 months)
- **Reflection on prior work.** Even with Catalyzer-style fork and restore, production cold
  starts at Ant stayed at **hundreds of ms to seconds**. Three causes were overlooked:
  1. **control-path latency** (runtime interactions, "shim calls");
  2. **resource contention under concurrency**. At ×24 sustained concurrency, throughput fell
     from **110 to 45 functions/s**, and cold-start latency and its variance rose sharply
     compared with serial starts;
  3. user-code initialisation.
- **Mechanism.** Pool and share contended low-level resources instead of creating them; fork
  from **multi-level templates ("seeds")** arranged as a tree. Cold start reaches milliseconds.
- **Also.** Over 95% of requests are hot, concentrated in a few functions (as ORION and Huawei
  found).
- **For us.**
  1. **Contention is real in production.** Concurrent starts slow each other. Our β (Corollary
     1.2) is the right parameter to worry about, x2 is the right first test, and JIT spreading
     (Theorem 2; Xanadu's observation) is the right mitigation.
  2. Their argument "prior work optimises isolated components and ignores end-to-end workflow
     interaction" is an argument for our workflow-level view.

## D. Other techniques (background, or not applicable)

### FaaSLight — Liu, Wen, Chen, Li, Chen, Liu, Wang, Jin, TOSEM (`faaslight.pdf`)
- Application-level: separate *indispensable* from *optional* code (static call-graph
  analysis), load optional code lazily. Code loading latency down by **up to 78.78%**; total
  response latency improved up to 2.25×. **For us:** it shrinks `A` (cold start) for scripting
  runtimes and is orthogonal to snapshots; it could make some Python stages "not worth a
  snapshot" (Corollary 7.3's dominance rule).

### SPES — Lee et al. (CUHK), arXiv 2403.17574 (`SPES.pdf`)
- Categorises functions by **invocation pattern** (deterministic: always-warm, regular,
  appro-regular, dense, successive; indeterminate: pulsed, correlated, possible) and
  pre-loads/unloads per category. The 75th-percentile cold-start rate falls 49.77% and wasted
  memory·time 56.43% vs the state of the art. It notes **fan-out causes rapid successive calls**
  to the secondary functions ("correlated").
- **For us:** function-level prediction from *timestamps only* (no inputs). "Correlated"
  functions are what our DAG knows *exactly*, with no need to learn them. Categorisation could
  tell the keep-alive layer which workflows are regular (keep warm) vs rare (restore ahead).

### Cross-edge orchestration with probabilistic caching — Chen et al., arXiv 2310.04185 (`2310.04185v1.pdf`)
- Joint request distribution and container caching at the edge. It **proves NP-hardness** and
  gives an **online algorithm with a competitive-ratio guarantee** plus a probabilistic caching
  policy: 62.1% lower cost, 69.1% fewer cold starts. **For us:** an example of the "NP-hard,
  then online algorithm with a guarantee" presentation that examiners expect, the same shape as
  our Theorem 7(d) plus the guard.

### Agile cold starts via pause containers (PCPM) — Mohan et al. (Intel), HotCloud '19 (`PCPM_unlocked.pdf`)
- Pre-create network namespaces in **pause containers** and attach them to new function
  containers. Cold start drops by up to 80%; the saving grows with concurrency (75% at 50
  concurrent starts, 80% at 100). **For us:** part of container-creation cost is
  **concurrency-sensitive** setup (network), another source of β. Pre-created resources are
  cheap to keep.

### SPEC-RG Reference Architecture for FaaS — van Eyk et al., IEEE IC (`Reference-Architecture.pdf`)
- Layered reference architecture (resource orchestration, function management, workflow
  composition) and common operational patterns, including workflow execution. **For us:**
  vocabulary and a diagram for placing our orchestrator. Look-ahead lives in the
  **workflow-composition layer** and drives the **function-management layer** (restore
  requests) through its normal API.

### Cold Start Latency in Serverless Computing: A Systematic Review — Golec et al., ACM CSUR 2024 (`10.1145_3700875_6eu4.pdf`)
- Taxonomy: caching/keep-alive, application-level, snapshot/checkpoint, scheduling, and AI/ML
  prediction. **For us:** the related-work chapter's skeleton. It does not cover
  workflow-level snapshot scheduling, which is our gap.

### Your summary, "Recent Research on Mitigating FaaS Cold Starts in Workflows (2020–2025)"
- It lists Bermbach et al. (SAC '20: application-knowledge pre-warming along known
  compositions, ~40% and up to 80% of cold starts removed), Xanadu, function fusion, Arslan et al.
  2025 (cold-start-aware scientific workflow scheduling, ~20% makespan gain), FaasCache, HotC,
  PCPM, Incendio, RL/LSTM pre-warming, TCN forecasting, namespace carving, and Transformers.
  **All workflow-aware items pre-warm cold containers; none restore snapshots.** That remains
  our gap.

---

## What this means for us

### 1. The novelty, restated honestly
- **Timing** downstream provisioning just in time along the DAG is **Xanadu's** idea (2020).
  ORION searches the same delays, Żuk & Rzadca's "start" policy is the eager version in a
  formal model, and Bermbach et al. pre-warm along known compositions. **All of them
  provision cold containers.**
- **Ours**:
  - the same timing for **snapshot restores**, which are short enough to be hidden behind
    upstream work (a 2.5 s cold boot usually is not);
  - **proofs**: optimal latency, least memory·time (Theorems 1–2);
  - **which stages get a snapshot**, how deep, and where it is stored (Theorem 7);
  - **memory** under a hard cap (Theorem 8, and exact planning in `theory/ALGORITHM.md`);
  - **contention** as a resource (restore channels);
  - **keep-alive valuation** under look-ahead (Proposition 9);
  - **measurements** of `r` and the warm-up on real CRaC/CRIU.
- `theory/DAG_SNAPSHOT_THEORY.md` §1 now says this. The thesis's related-work chapter must
  credit Xanadu for the timing.

### 2. The algorithm is a known problem
The papers pointed to it; `theory/ALGORITHM.md` works it out. Snapshot-restore scheduling in a
workflow is **MRCPSP/max**: multi-mode resource-constrained project scheduling with time lags.

| paper | what it contributed to the algorithm |
|---|---|
| Żuk & Rzadca | the scheduling view: jobs with setup times, a memory knapsack, NP-hardness |
| Costless | the chain-with-prices case as constrained shortest path (LARAC) |
| ORION | input-time distributions by convolution/max, the input to Theorem 3's quantile trigger |
| Xanadu | the JIT timeline; the most-likely-path idea for branches |
| CIDRE / FaasCache | GDSF eviction; per function, it is the best keep-alive in e8 (the workflow-level variant Proposition 9 suggested loses) |
| MPC scheduler | receding-horizon re-planning when a stage runs early or late |

### 3. Numbers we can plug in
`theory/ALGORITHM.md` §8 has the full table. The short list:
- DAG shapes: ORION (depth median 3, P95 8; 65% chains) and SeBS-Flow (most workflows ≤ 10
  functions). This is why exact planning is affordable.
- Rarity: ORION (80% of DAGs run < 100/day, with a median 50% cold starts).
- Duration spread: ORION (P95 = 80× P25). The trigger must use quantiles, not means.
- Start-up per runtime: Prebaking. Cold-start distributions: Huawei.

### 4. The risks, confirmed by others
- **Restore contention** is real: Xanadu, Fork in the Road, PCPM, Spice. **x2 comes first.**
- **Memory** is the binding cost: HighCostOfKeepingWarm, and Replayable's 2× from sharing.
  Hence Theorem 8 and the guard.
- **Uniqueness** after restore: Brooker et al. Hence reset hooks.

### 5. What changes in the plan
- **Planner:** exact branch and bound at arrival, with the guard as executor (`ALGORITHM.md`
  Algorithms 2–3).
- **Keep-alive:** e8 evaluated workflow-level eviction (Proposition 9) in `ideas/sim`. It
  **loses** to per-function GDSF, which the thesis adopts from FaasCache/CIDRE
  (`theory/ALGORITHM.md` §7).
- **Data:**
  - ORION's released DAG traces and the Huawei cold-start trace can calibrate `ideas/sim`
    beyond Azure 2021;
  - SeBS-Flow's benchmarks are the Stage 7 workloads (port a subset to Java).
- **Baselines for the evaluation:**
  - restore-on-demand (SnapStart-like);
  - Xanadu-style JIT *cold* prewarm;
  - eager look-ahead (Żuk & Rzadca's "start");
  - function fusion (optional).
- **Scope:** with Catalyzer- or Spice-class restores (milliseconds), there is little to hide.
  Our setting, stock CRIU/CRaC with no kernel change, is where `r` is 0.6–9 s and look-ahead
  matters most. An x1 variant with mmap-style restore (Replayable) would lower Theorem 8's peak.
