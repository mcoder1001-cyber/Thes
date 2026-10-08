# D1 prediction: CRaC restore vs the JDK 25 AOT cache (decision experiment)

Written 2026-10-08, before the full run. **Disclosure:** a smoke run (n = 1, 1 vCPU only, all
seven modes) was seen before this file was written: cold21 4074, c1_21 2314, aot_K0 2201,
aot_K50 2019, cold25 4182, crac_K0 493, crac_K50 62 ms time-to-first-response. The 1 vCPU
numbers below are therefore not blind. The 0.25 vCPU predictions are.

## Reasoning registered before any data
The AOT cache (JEP 483/514/515) removes class loading/linking and gives the JIT early profiles,
but Spring's context refresh (bean creation, reflection, proxies) still runs, and JDK 25 stores
no compiled code. A CRaC image holds the refreshed context and the compiled code. So:

- **TTFR order:** crac_K50 < crac_K0 < aot_K50 ≤ aot_K0 < c1_21 < cold25 ≈ cold21.
- **aot_K0 / cold25 ≈ 0.5–0.65** (Leyden's published Spring numbers: ~40% start-up gain for
  JEP 483, more with 515).
- **crac_K50 at least 5× faster than aot_K50 in TTFR, at both vCPU.**
- **At 0.25 vCPU the CRaC advantage grows** (aot still does CPU work — context refresh,
  JIT — that scales with the quota; a restore from page cache does less): ratio aot_K50 /
  crac_K50 at 0.25 ≥ the ratio at 1 vCPU.
- **Residual warm-up** over the 200 later requests: crac_K50 ≪ aot_K50 < cold.
- **CPU-seconds per start:** crac < aot < cold.
- **Control:** cold21 ≈ cold25 within 20% (else the JDK version is a confound and the AOT
  comparison is made against cold25 only). Every run's cgroup is `/d1run`.

## Decision rule (registered)
| aot_K50 TTFR / crac_K50 TTFR, at 0.25 and 1 vCPU | meaning |
|---|---|
| **≥ 3×** at both | CRIU/CRaC is justified as the mechanism; the AOT cache is a baseline it beats |
| **1.5–3×** | both are start modes; the planner chooses per stage (CRaC where safe and affordable) |
| **< 1.5×** | the AOT cache is enough; CRIU is not worth its operational cost; switch the mechanism |
