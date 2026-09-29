# Thesis chapters (drafts)

| file | what |
|---|---|
| `ch_theory.tex` | **Chapter 4, theory** (draft, English): the model, the theorems with proofs, the problem as RCPSP/max, the algorithm, the CPU plan, and how everything was verified |
| `theory.bib` | the references the chapter cites |
| `theory_standalone.tex` | a wrapper that compiles the chapter on its own |
| `theory_standalone.pdf` | the compiled draft (23 pages) |

**Build** (pdflatex, as installed here):
```bash
cd thesis
pdflatex theory_standalone && bibtex theory_standalone && pdflatex theory_standalone && pdflatex theory_standalone
```

**Put it into the thesis.**
- `\input{ch_theory}` from the department's template.
- The chapter needs these packages: `amsmath`, `amsthm`, `enumitem`, `booktabs`, `graphicx`,
  `tikz`, `xcolor`, `algorithm`, `algpseudocode` and `cleveref`. It also needs the theorem
  environments `theorem`, `corollary`, `lemma`, `proposition`, `definition` and `example`,
  sharing one counter. `theory_standalone.tex` shows the exact preamble.
- Figures come from `../figures/` (`\graphicspath`).
- The chapter refers to two other chapters by label: `ch:model` (the measurement study and
  the on-demand depth model, `theory/MODEL.md`) and `ch:evaluation`. The standalone build
  prints "Chapter 3" and "Chapter 6" instead; in the thesis, give those chapters these labels.
- The XePersian template: if the thesis is written in Persian, this text must be translated.
  Keep the mathematics as it is. To include English text as is, wrap it in XePersian's
  `latin` environment.

**What the chapter contains** (numbers as in the standalone build, with the names used in
the repository's documents):

| chapter | repository | content |
|---|---|---|
| Definitions 4.1–4.2, Example 4.3 | `DAG_SNAPSHOT_THEORY.md` §2 | workflow, schedule, running example |
| Theorem 4.4 | Theorem 1 | look-ahead is latency-optimal |
| Corollary 4.5 | Corollary 1.1 | chains: the cascade collapses to one restore |
| Theorem 4.6 | Theorem 2 | just in time is also memory·time-minimal |
| Corollaries 4.7, 4.8 | Corollaries 1.2, 1.3 | restore contention β; random restore times |
| Theorem 4.9 | Theorem 3 | trigger under uncertainty: the κ-quantile |
| Theorem 4.10 | Theorem 4 | speculation on branches: iff p ≥ κ |
| Lemma 4.11 | Lemma 5 | the entry gate |
| Theorem 4.12 | Theorem 6 | keep-alive cannot replace look-ahead |
| Theorem 4.13 | Theorem 7 | snapshot depth and timing jointly: the (W, P) DP |
| Corollaries 4.14–4.16 | Corollaries 7.1–7.3 | hidden cold starts; longest tail first; prices |
| Theorem 4.17 | Theorem 8 | peak memory, k slots, the guard |
| Lemma 4.18 | Lemma A1 (`ALGORITHM.md`) | no idle sandbox: the lag network |
| Propositions 4.19, 4.20 | `ALGORITHM.md` §2–3 | NP-hardness; exactness of the branch and bound |
| Corollary 4.21 | Corollary A3 | restore channels |
| Proposition 4.22 | Proposition 9 | keep-alive under look-ahead |
| Proposition 4.23 | Proposition 8 | when to stop warming up |
| Algorithms 1–4 | `ALGORITHM.md` §4 | Exact (branch and bound), Build, Plan, Run |
| Definition 4.24, Table 4.4 | `CPU_PLAN_THEORY.md` §1 | the CPU plan; assumptions B1–B4 |
| Lemma 4.25 | Lemma CP1 | deadlines per start-up |
| Theorem 4.26, Corollary 4.27 | Theorem CP2, Corollary CP2.1 | the exact plan by max-flow; the min-cut certificate |
| Proposition 4.28 | Proposition CP3 | no spare CPU gives Theorem 4.4; unlimited gives the ideal |
| Proposition 4.29 | Proposition CP4 | one spare core: earliest deadline first; look-ahead's gain bounded |
| Propositions 4.30, 4.31 | Propositions CP5, CP6 | speculation on leftover CPU; the cost of a wrong guess |
| Proposition 4.32 | Proposition CP7 | bursts on one spare core |
| Algorithm 5 | `CPU_PLAN_THEORY.md` §7 | Boost: the online CPU rule (`dagsim`, `Policy.boost = "plan"`) |

Left out on purpose: `MODEL.md`'s on-demand depth model belongs to the measurement chapter,
and Proposition 7 (scrubbed priming) belongs to a dropped idea. Simulation results appear
only where they explain a design rule; the evaluation chapter reports them.

**Still to do in this chapter.**
- Once the machine tests run (`../MACHINE_TEST_PLAN.md`), replace "to be measured" in
  Table 4.1 (assumptions A2, A3), Table 4.4 (assumption B1, the CPU speed-up; test T6b) and
  Table 4.7 (status) with the measured values.
- Check the bibliography entries against the final versions of the papers. Two entries list
  only their first authors (CIDRE, Fork in the Road).
- Decide whether §4.8 (when to stop warming up) belongs here or in the design chapter.
