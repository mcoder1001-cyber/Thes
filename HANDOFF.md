# Handoff prompt — paste this into a new chat session

Copy everything between the lines below and give it as your first message to a new
Claude session pointed at this same project folder (`~/Desktop/thes/`).

---

I'm continuing an MSc thesis on reducing FaaS cold start, currently mid-project. Before
responding, read these four files in `~/Desktop/thes/` in this order:

1. `RESEARCH_PLAN.md` — the plan (v4). It records why earlier approaches were dropped
   and what the current direction is.
2. `experiments/RESULTS.md` — every experiment run so far, in order, including two
   retracted results and the reasoning for each retraction. Don't skip the retractions.
3. `SYNTHESIS.md` — how the read literature connects to our work, including a scored
   comparison table (§3b) of candidate techniques from other papers.
4. `READING_LIST.md` — 28 papers found relevant, 14 already downloaded to
   `baselines/papers/`.

Then check `experiments/exp10-workflow-depth/out.json` — if it exists and is complete,
that experiment (workflow-depth cascade for Python and Node, realistic per-function
weight) finished after the documents above were last written. Read its raw data and
fold the results into `RESULTS.md`'s "Experiment 10" section, which is currently
marked in-progress.

**The one-paragraph summary, so you don't have to reconstruct it from the files:**
this started as a proposal to reduce workflow cold start via snapshots. Several
theoretical approaches (a hedging/betting policy, snapshot lineage, a resource pool)
were killed by cheap experiments before being built. The thesis pivoted to a
**measurement thesis**: cold-start cost is dominated by factors the literature
measures at unrepresentative values (framework weight, CPU allocation, workflow
depth), and we've quantified each with real experiments — the headline is a
**13–35× warm-up cost increase from 4 to 0.25 vCPU on the JVM** (server x86; an
earlier laptop measurement said 33–111× and is retracted), explained by a
compilation-work-vs-available-CPU mechanism, not "has a JIT" (that guess was wrong;
the correction is in the files). We also tested the obvious cheap fix
(`-XX:TieredStopAtLevel=3`) and found it has a real, computable break-even rather than
being free, which sets the actual bar the eventual snapshot mechanism has to clear.

**Two environment facts you need before touching OpenWhisk:** the host is Apple
Silicon and Java's OpenWhisk runtime is confirmed structurally broken there (a
socket-level bug, root-caused via the invoker log, not a code issue — needs an
x86_64 Linux machine we don't have yet). Separately, this OpenWhisk build has a
1024MB invoker memory limit that silently exhausts over a long session and produces
an *identical-looking* but *unrelated* failure — the invoker's own log, not the `wsk`
CLI, is what tells the two apart. Both are documented in `RESEARCH_PLAN.md`'s S0
section.

**Working style established this session, please continue it:** every experiment
needs a control whose answer is known in advance (this caught three analyzer bugs).
Don't trust a model or a claim until it's been checked against data — three of my own
confident predictions were wrong this session, and every one of those corrections
made the thesis stronger, not weaker. Report negative and retracted results as
prominently as positive ones. Prefer running a cheap experiment over arguing from
theory.

Once you've read the four files and the exp10 status, tell me in a few sentences
where things stand and what you'd do next — don't just start executing.

---
