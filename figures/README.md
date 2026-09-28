# Thesis figures

`python3 figures/make_figures.py` redraws all figures from the committed results; no
simulation runs. Each figure comes as a **PDF** (vector, fonts embedded, for LaTeX:
`\includegraphics[width=\textwidth]{figures/fig1_cascade.pdf}`) and a **PNG** (220 dpi,
for slides and Word).

**Style.** Each thing has one colour in every figure:
- blue = look-ahead restore (this thesis);
- orange = restore on demand;
- aqua = cold prewarm;
- gray = keep-alive and other baselines.

The palette passed a colour-blindness check on a white page (all pairs distinguishable; aqua is
low-contrast, so every mark also carries a text label). Values are written on the figures, so
they also read in grayscale. The CSV named under each figure is its data table.

Draft captions follow; adjust them to your thesis style.

---

### Figure 1: `fig1_cascade`: look-ahead removes the restore from the cascade
> End-to-end latency of a cold Java workflow as it gets longer (restore 650 ms, run 75 ms per
> stage; mean of 200 simulated runs). Restoring on demand adds 0.74 s per stage: the linear
> cascade. Pre-starting cold containers along the DAG (Xanadu-style) cannot hide a 2.5 s cold
> start. Look-ahead restore hides every restore except the first and adds 0.06 s per stage:
> 5.0× faster at 8 stages.

Data: `ideas/sim/results/e10a_chains_final.csv` (restore on demand, look-ahead);
`ideas/sim/results/e1_cascade.csv` (cold prewarm).

### Figure 2: `fig2_trace`: the Azure trace
> Azure Functions 2021 trace (68 workflows, 432,945 calls, 3 days; 128 GB budget, not binding).
> Latency of the 794 calls that reach a workflow idle for more than 10 minutes, and average
> memory held over all calls. Look-ahead restore makes cold workflows 2.9× faster on average
> and 5× faster at p99 than restoring on demand, with the same memory. Keeping sandboxes warm
> longer (60 min) costs 68% more memory and is still 5× slower.

Data: `ideas/sim/results/e4_trace.csv` (keep-alive, prewarm);
`ideas/sim/results/e10b_trace_final.csv` (restore on demand, look-ahead; 128 GB rows).

### Figure 3: `fig3_memory_slots`: memory buys speed (Theorem 8(b))
> Latency of an 8-stage Java chain under look-ahead when the workflow may hold only k
> sandboxes at once. With one slot it equals restoring on demand. Each extra slot divides the
> restore cost, down to 1.26 s with eight. The schedule is optimal: an exact
> branch-and-bound solver finds nothing faster (check A3 in `theory/verify_dag.py`).

Data: computed from `theory/verify_dag.py: chain_slots_rec` (r = 650 ms, w = 75 ms, δ = 2 ms).

### Figure 4: `fig4_budget`: the gain holds when memory is tight
> The Azure trace at memory budgets below (24, 32 GB) and above (128 GB) its ~50 GB working
> set. Under pressure, restoring on demand has a p99 of 3.2–3.8 s over all calls, and
> look-ahead 1.1–1.2 s. Cold workflows keep their 1.2–1.3 s p99 at every budget.

Data: `ideas/sim/results/e10b_trace_final.csv`.

### Figure 5: `fig5_contention`: the main risk, restores that slow each other down
> (a) Speed-up of look-ahead over restoring on demand for a 5-stage Java chain, as restores
> slow each other (β = 0: fully parallel; β = 1: fully serial), for three restore times. At
> β = 1 look-ahead is never worse, only no better. (b) The exact optimum when the machine
> can run c restores at once: each extra parallel restore divides the restore cost, and 5
> suffice here. Test x2 measures this on the real machine.

Data: `ideas/sim/results/e5_sensitivity.csv`; (b) computed from the recurrence
τ_v = max(τ_{v−1} + w + δ, τ_{v−c} + r) (`theory/ALGORITHM.md`, Corollary A3).

### Figure 6: `fig6_planner`: planning the restore order exactly
> (a) One cold workflow under a tight memory budget, simulated with timing noise (50 runs): the
> memory guard alone vs the guard executing an exact plan. The planner is never slower in any
> of the 35 cases tested, and up to 48% faster. (b) How far the guard alone is from the true
> optimum (exact branch and bound) on random workflows. The gap grows with size: 14% on
> average for 10-stage DAGs.

Data: `ideas/sim/results/e9a_planner_single.csv`; `theory/exact_scale.csv`
(`theory/exact_scale.py`).

### Figure 7: `fig7_keepalive`: which keep-alive to use with look-ahead
> Azure trace at 24 GB, look-ahead with the memory guard, four ways to choose which idle
> sandbox to evict. Cost-aware per-function eviction (GDSF, from FaasCache/CIDRE) gives the
> lowest p99 and the fewest starts over the budget. Evicting whole workflows, which
> Proposition 9 suggested, is worse.

Data: `ideas/sim/results/e8_keepalive.csv` (24 GB rows).

### Figure 8: `fig8_priming`: build snapshots on a big machine
> Wall time to prime a Spring Boot snapshot with 100 or 400 warm-up requests, with the JVM
> pinned to the 0.25-vCPU serving shape (n = 20 per cell). Priming at 4 vCPU is about 10×
> faster than at 0.25 vCPU. Served at 0.25 vCPU, the resulting snapshot is as good (0.98×,
> 1.02×). Without pinning it is 11–17% worse.

Data: `ideas/exp-a-context-priming/results/summary_exp-b.csv` (rows `pinned`).

---

**Not yet available:** a figure of the vCPU cliff itself (JVM warm-up 13–35× slower from 4 to
0.25 vCPU, exp14). Its raw data is not in this repository. Add the exp14 CSV and it can be
drawn in the same style.
