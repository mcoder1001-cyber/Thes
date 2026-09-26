# Reading list — compiled 2026-09-24

**Download status (updated 2026-09-24):** 14 files confirmed present in
`baselines/papers/` — Fork in the Road, Cold Starts Where to Find Them, Taming Cold
Starts, High Cost of Keeping Warm, REAP, Restoring Uniqueness, Snapshot Methods Eval,
ORION (2 copies, different filenames, same paper — harmless dup), SeBS-Flow, CIDRE,
MPC Proactive Scheduling, Characterizing FaaS Workflows, SPES. Everything else in this
list marked 🆓 is fetchable but **not yet downloaded**. See §3b of `SYNTHESIS.md` for
the scored comparison of these against our snapshot/cold-start/workflow criteria.

Ordered by how much it matters to *this* thesis, not by date.

**Availability legend:** 🆓 free (USENIX / arXiv / open access) · 💰 likely paywalled
(ACM DL, IEEE, Springer, Elsevier) · 📂 already in `ideas/` or `baselines/`

> Almost everything in Tier 1 is **free**. USENIX (OSDI/ATC/NSDI) publishes all papers
> openly, and most recent systems work has an arXiv preprint. Check arXiv before paying.

---

## TIER 1 — read first; these could affect the novelty of our findings

### 1. Fork in the Road: Reflections and Optimizations for Cold Start Latency in Production Serverless Systems 🆓
* **OSDI '25** · Chai et al. · Tsinghua, Ant Group, SJTU
* PDF: https://www.usenix.org/system/files/osdi25-chai-xiaohu.pdf
* ACM: `10.5555/3767901.3767929`
* **⚠️ HIGHEST PRIORITY — potential direct overlap with our headline.** They name
  three overlooked latency sources, two of which look close to ours:
  **"resource contention latency, arising under high concurrency and sustained
  execution"** and **"user code initialization latency (10 ms–1 s)"**. Our CPU-starvation
  result may be a special case of their contention finding, or may be distinct
  (theirs is concurrency-driven, ours is vCPU-allocation-driven). **Read before
  writing any claim about novelty.** Production system: AFaaS, 18 months deployed.

### 2. Serverless Cold Starts and Where to Find Them 🆓
* **EuroSys '25** · DOI `10.1145/3689031.3696073` · arXiv 2410.06145
* PDF: https://arxiv.org/pdf/2410.06145
* **Already checked: complementary, not competing.** Trace study of 85B requests /
  11.9M cold starts at Huawei across 5 regions. Platform-side decomposition (pod
  allocation, dependency deployment, scheduling). Does **not** cover JIT warm-up,
  vCPU effects, framework weight, or snapshots. **Cite its 7-second figure as motivation.**

### 3. Taming Serverless Cold Starts Through OS Co-Design 🆓
* arXiv 2509.14292 · https://arxiv.org/pdf/2509.14292
* Recent, OS-level. Check whether it touches runtime warm-up or only sandbox setup.
  Relevant to our C1 constraint (we rejected OS-level solutions) — good related work.

### 4. The High Cost of Keeping Warm: Characterizing Overhead in Serverless Autoscaling Policies 🆓
* arXiv 2509.03104 · https://arxiv.org/pdf/2509.03104
* Characterization study of keep-alive cost. Directly relevant to our cost side —
  we argue depth is cheap; they quantify what keeping warm costs.

---

## TIER 2 — snapshot mechanisms (the technique we measure)

### 5. Benchmarking, Analysis, and Optimization of Serverless Function Snapshots (REAP) 🆓
* **ASPLOS '21** · Ustiugov et al. · DOI `10.1145/3445814.3446714` · arXiv 2101.09355
* PDF: https://arxiv.org/pdf/2101.09355
* Record-and-prefetch of the guest working set. **The nearest prior work on snapshot
  *content*.** Also the origin of the vHive framework.

### 6. FaaSnap: FaaS Made Fast Using Snapshot-based VMs 💰
* **EuroSys '22** · Ao, Porter, Voelker · DOI `10.1145/3492321.3524270`
* Snapshot restore optimization, per-region prefetch.

### 7. Medes: Memory Deduplication for Serverless 💰
* **EuroSys '22** · Saxena et al. · DOI `10.1145/3492321.3524271` *(verify)*
* Dedup across idle sandboxes — the memory-cost angle.

### 8. WorksetEnclave: Optimizing Cold Starts in Confidential Serverless with Workset-Based Enclave Restore 💰
* **ASPLOS '26** · DOI `10.1145/3779212.3790249`
* Newest snapshot-restore work. Claims 1.9–54× faster cold start, 13–95% less memory.
  Confidential-computing framing, but the workset idea is the same family as REAP.

### 9. Restoring Uniqueness in MicroVM Snapshots 🆓
* Brooker et al. (AWS) · arXiv 2102.12892 · https://arxiv.org/pdf/2102.12892
* **The safety boundary on snapshot depth.** RNG/UUID/nonce reuse, demonstrated TLS
  attacks. `MADV_WIPEONSUSPEND` and `SysGenId`. Cite whenever we discuss how deep is safe.

### 10. Performance Evaluation of Snapshot Methods to Warm the Serverless Cold Start 🆓
* arXiv 2105.13894 · https://arxiv.org/pdf/2105.13894
* Earlier work by the Prebaking group. Useful for positioning exp 6 (depth sweep).

### 11. DeltaBox: Scaling Stateful AI Agents with Millisecond-Level Sandbox Checkpoint/Rollback 🆓
* arXiv 2605.22781 · https://arxiv.org/pdf/2605.22781
* Checkpoint/rollback outside the FaaS framing. Skim for mechanism ideas.

### 12. SOCK: Rapid Task Provisioning with Serverless-Optimized Containers 🆓
* **USENIX ATC '18** · Oakes et al.
* Zygote provisioning, pre-imported package cache. The ancestor of "what to pre-load".

### 13. Firecracker: Lightweight Virtualization for Serverless Applications 🆓
* **NSDI '20** · Agache et al.
* Background for SnapStart's microVM snapshots.

---

## TIER 3 — workflows and DAGs

### 14. ORION and the Three Rights: Sizing, Bundling, and Prewarming for Serverless DAGs 🆓 📂
* **OSDI '22** · Mahgoub et al. · https://www.usenix.org/system/files/osdi22-mahgoub.pdf
* Code: https://github.com/icanforce/Orion-OSDI22
* **We use its performance model** (convolve for series, max for parallel, correlation
  correction) to decide which functions are worth snapshotting. No snapshots, no
  branching — those gaps are ours.

### 15. WISEFUSE: Workload Characterization and DAG Transformation for Serverless Workflows 💰
* **SIGMETRICS '22** · DOI `10.1145/3530892`
* DAG transformation / fusion. Same group as ORION.

### 16. Concurrency-Informed Orchestration for Serverless Functions (CIDRE) 🆓
* **ASPLOS '25** · https://ds2-lab.github.io/pdfs/asplos25-cidre.pdf
* Speculatively chooses between a delayed warm start and a cold start under
  concurrency-driven scaling. −75.1% cold-start ratio. **Close to the "when to
  provision" question; read alongside ORION.**

### 17. SeBS-Flow: Benchmarking Serverless Cloud Function Workflows 🆓
* **EuroSys '25** · arXiv 2410.03480 · https://arxiv.org/pdf/2410.03480
* Repo: https://github.com/spcl/serverless-benchmarks
* **First serverless *workflow* benchmark suite.** Solves our "Azure traces have no
  DAGs" problem. Use for the workflow-depth experiments.

### 18. Xanadu: Mitigating Cascading Cold Starts in Serverless Function Chain Deployments 💰 📂
* **Middleware '20** · DOI `10.1145/3423211.3425690`

### 19. Taming Cold Starts: Proactive Serverless Scheduling with Model Predictive Control 🆓
* arXiv 2508.07640 · https://arxiv.org/html/2508.07640v1
* MPC-based prewarming. −85% p90 tail latency, −34% resources.

### 20. PliKOS: Pre-warming Serverless Functions Under Pulsed Loads 💰
* Springer · uses service call graphs to prewarm chains.

### 21. Characterizing FaaS Workflows on Public Clouds 🆓
* arXiv 2509.23013 · https://arxiv.org/pdf/2509.23013

---

## TIER 4 — application level, traces, surveys

### 22. Serverless in the Wild 🆓 📂
* **USENIX ATC '20** · Shahrad et al. · **the model for a measurement thesis.**
  Source of the Azure traces cited in the proposal.

### 23. Cold Start Latency in Serverless Computing: A Systematic Review 🆓 📂
* **ACM Computing Surveys 2024** · DOI `10.1145/3700875` · arXiv 2310.08437

### 24. FaaSLight: Application-Level Cold-Start Optimization 🆓 📂
* **TOSEM 2023** · DOI `10.1145/3585007` · arXiv 2207.08175

### 25. Prebaking Runtime Environments to Improve the FaaS Cold Start Latency 💰 📂
* **FGCS 2024** · DOI `10.1016/j.future.2024.01.019`
* **Our K=1 baseline.** Exp 6 shows its one-request checkpoint captures only ~32% of
  Spring Boot's warm-up.

### 26. Reducing Cold-Start Latency in Serverless Applications via Dynamic Slicing 🆓
* arXiv 2609.14040
* Application-level, same family as FaaSLight.

### 27. Lambda-Warmer: Measurement-driven adaptive cost-aware cold-start mitigation 💰
* **FGCS** · https://www.sciencedirect.com/science/article/pii/S0167739X26003158
* 2,880 deployments across runtimes/memory/regions. **Closest in spirit to our factor
  study — check their factor coverage carefully.**

### 28. SPES: Optimizing Performance-Resource Trade-Off for Serverless Functions 🆓
* arXiv 2403.17574

---

## What to check in each (the specific questions)

1. **Fork in the Road** — is their "resource contention latency" the same phenomenon as
   our vCPU-allocation effect, or a different one (concurrency vs allocation)?
2. **Lambda-Warmer** — do they vary vCPU/memory and measure *warm-up* separately from
   *init*? If they measure only total cold start, our A/B/C decomposition stands.
3. **REAP / WorksetEnclave** — do either optimize *when* the snapshot is taken, or only
   what is prefetched at restore? Our depth question survives if they only do the latter.
4. **CIDRE / ORION / MPC** — all answer "when to provision". None answer "what state the
   snapshot should contain".
5. **Anything** — has anyone swept *number of warm-up requests before checkpointing*?
   That is exp 6's contribution and the thing to protect.

## Still unsearched

*automatic priming*, *priming depth*, *checkpoint point selection*, *snapshot staleness*,
*JIT warm-up serverless*, *tiered compilation cold start*.

---

## Added 2026-09-26 — found while developing `ideas/IDEAS.md`

**Read #29 before anything else in this list: it overlaps the "depth is unswept" claim.**

### 29. Pronghorn: Effective Checkpoint Orchestration for Serverless Hot-Starts 💰
* **EuroSys '24** · Kohli, Kharbanda, Bruno, Carreira, Fonseca · DOI `10.1145/3627703.3629556`
* Slides: https://www.dpss.inesc-id.pt/~rbruno/papers/skohli-eurosys24-slides.pdf
* A snapshot orchestrator that "monitors function performance and decides **when to take a
  snapshot and which snapshot to use**" for JIT runtimes; OpenJDK 17 + CRIU, PyPy. 37.2%
  median latency improvement over state-of-the-art checkpointing policies. **This answers
  "how many requests before checkpointing" for single functions.** Rodrigo Bruno is also
  on CloudJIT [4] of the proposal. Single-function only: no DAG, no CPU-allocation axis,
  no treatment of user data in snapshots (unverified; ACM DL was not reachable).

### 30. Fireworks: A Fast, Efficient, and Safe Serverless Framework using VM-level post-JIT Snapshot 💰
* **EuroSys '22** · Shin, Kim, Min · DOI `10.1145/3492321.3519581`
* Snapshots a microVM **after JIT compilation** of the function. Prior art for "deep"
  snapshots.

### 31. Snapipeline: Accelerating Snapshot Startup for FaaS Containers 💰
* **SoCC '24** · Lan, Peng, Wang · DOI `10.1145/3698038.3698513`
* CRIU-family: pipelines decompression, hot-page restore and execution *within one restore*
  (userfaultfd). Composes with restore-ahead, which pipelines restores *across DAG stages*.

### 32. Faast: An Efficient Serverless Framework Made Snapshot-based Function Response Fast 💰
* **HPDC '24** · DOI `10.1145/3625549.3658681`
* Observes snapshot restore overhead varies with **function inputs**; builds a lightweight
  working set. Related to the input-dependence finding in `ideas/` exp-a.

### 33. JEP 515: Ahead-of-Time Method Profiling (JDK 25) 🆓
* https://openjdk.org/jeps/515 — stores method profiles from a training run in the AOT cache
  so the JIT compiles immediately at startup. **A no-snapshot competitor to deep snapshots
  on the JVM**, the same role `-XX:TieredStopAtLevel=3` plays in S6. Belongs in the evaluation.
