# Measurements on the test machine (2026-10-08)

Machine and versions: `env.json` (8 × Xeon Gold 6248R, 2 sockets, Ubuntu 24.04, kernel 6.8, CRIU
4.2.1, Zulu CRaC JDK 21.0.12, OpenJDK 25.0.4, Docker 29.8.1, podman 4.9.3). Plan:
`../../MACHINE_TEST_PLAN.md`. Every test folder has `prediction.md` (committed before its run),
`raw/` (one row per run, never edited), the analysis script and `REPORT.md`.

**Engine.** The Zulu CRaC JDK checkpoints with Azul's **Warp** engine by default. Every test below
used Warp except D2, which measured Warp and CRIU side by side (CRIU: 17–91 ms slower per restore,
same CPU).

| test | question | verdict | report |
|---|---|---|---|
| T0 | machine state | `criu check` and the smoketest pass (7/7); steal 0; swap on, unused | `env.json` |
| **D1** | snapshot restore vs the JDK 25 AOT cache | **restore 25–30× faster to first response** (CRIU ≈ 23–24×); AOT cache halves cold start | `D1-aot-vs-crac/` |
| **D2** | Warp vs CRIU engine | CRIU within 17–91 ms of Warp; D1's verdict holds for CRIU | `D2-warp-vs-criu/` |
| T1 | parallel restores, raw CRIU in podman | **not run**: the first `podman container checkpoint` hung in `criu dump` | — |
| **T1b** | parallel restores in Docker (β) | `docker run`: β(4) 0.21–0.53, all of it Docker's container creation; **into pre-created containers β(4) = 0.04–0.07**, restore 101 ms at 1 vCPU | `T1b-crac-docker/` |
| T2 | readiness tiers | disk 505 ms, page cache 67 ms, warm 2.7 ms (1 vCPU); pre-restored tier not measured | `T2-x1/` |
| **T3** | profile r(K), R(K), s(K) | image 82–88 MB flat; deep restore ≈ 60–84 ms; R(K) keeps falling to K = 200; bimodal restore anomaly in the grid | `T3-profile/` |
| T4 | checkpoint loss L(K), re-warm | L(50) = 955 ms at 0.25 vCPU, 163 at 1; re-warm recovers 189–234%: keep | `T4-x3/` |
| T5 | snapshot uniqueness | hooks fix `Random` and start-up secrets; **`Math.random()` still repeats**: Stage 5 exit not met | `T5-uniq/` |
| T6 | the vCPU cliff | cold 10.3×; deep snapshots steepen the ratio but save 19.1 s at 0.25 vs 2.2 s at 4 vCPU | `T6-cliff/` |
| **T6b** | CPU during start-up | **speed-up ∝ CPU up to ~2 cores at constant CPU-seconds**; boost buys the first response, not the warm-up; one-at-a-time beats equal split on one core | `T6b-speedup/` |
| T7–T13 | OpenWhisk, chains, memory, evaluation | not started | — |

Derived: `profile_vcpu1.0.json`, `profile_vcpu0.25.json` (measured Java profile; Python/ML assumed),
`predict_measured_vcpu*.md` (the closed-form predictions with them), `sim/` (the cost sweep e12 with
the measured profile and a 2-core start-up cap, two bounds: `e12_measured_cap2_*` with only the first
request's warm-up, `e12_lumped_cap2_*` with the whole residual warm-up in the first request; summaries
`*_summary.txt` from `sim/summary.py`: the CPU plan needs 25–33% fewer cores than an equal split), `logs/` (run logs from the box).

**Scripts.** D1 `D1-aot-vs-crac/run.py`; T1b `T1b-crac-docker/run.py`; T2–T6b and T5
`T3-profile/grid.py` (phases build, uniq, contention, boost, grid) and `T3-profile/t5_rerun.sh`; D2
`D2-warp-vs-criu/run.py`. Analyses: `*/analyze.py`.
