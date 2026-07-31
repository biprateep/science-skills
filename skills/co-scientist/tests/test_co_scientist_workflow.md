# Co-Scientist Skill Test Workflow

## Test Scenario: Central Limit Theorem from First Principles

### Test Prompt

> I'm interested in understanding the Central Limit Theorem from first
> principles. Help me develop this into a small research write-up: derive it
> rigorously using characteristic functions, verify it numerically with a
> simulation, and write up the results as a LaTeX report.

This is phrased as a multi-phase project, so it should enter **Full Project**
mode. (A bare "derive the CLT" should instead enter the lighter **Derivation**
mode — worth testing separately that the skill does *not* over-scaffold it.)

### Why this exercises the skill

| Capability | What it tests |
|------------|---------------|
| Activation & mode triage | Project-shaped prompt → Full Project; a bare derivation → Derivation mode |
| Harness adapter | Skill detects the harness and uses the right tools for `<literature-search>`, `<spawn-subagent>`, etc. |
| Hypothesis ranking | 3–5 framings generated and ranked before the design gate |
| Math rigor + verification | CLT via characteristic functions has ≥8 load-bearing steps; sanity + sympy/numeric verification |
| Literature + novelty | Verified citations (resolvable ids) + a novelty verdict |
| Red-team | Independent reviewer challenges the derivation |
| Checkpoints + manifest | Multiple phases, resumable manifest |
| Visualization | Histogram convergence to Gaussian, inline |
| Report | Compiles, with an Assumptions and Limitations section |

---

## Setup (per harness)

**Install the skill where your harness discovers skills:**

- **Claude Code:** `~/.claude/skills/co-scientist/` (personal) or
  `.claude/skills/co-scientist/` (project), or ship it in a plugin.
- **Google Antigravity:** its skill/agent discovery path (e.g. `.agents/` or the
  configured plugin location).
- **Any other harness (OpenAI Codex, Cursor, …):** place the skill folder where
  the agent discovers instructions (e.g. reference it from `AGENTS.md`), or
  paste `SKILL.md` as context — the Harness Adapter maps the capabilities.

**Launch an autonomous run with the test prompt:**

- **Claude Code:** start a session in a clean working directory and paste the
  test prompt (the skill activates on the trigger phrasing), or run headless:
  `claude -p "<test prompt>"`.
- **Google Antigravity:** start an autonomous run (e.g. `/goal`) with the test
  prompt.
- **Any other harness:** start a session in a clean working directory with the
  skill loaded and paste the test prompt.

After completion, from the **clean working directory** run:
`bash <skill-dir>/tests/verify_co_scientist.sh`

---

## Expected Outcomes

### Activation & modes
- [ ] The project-shaped prompt triggers Full Project mode; a bare "derive the CLT" stays in Derivation mode (no directories/report unless asked)
- [ ] `checkpoints/`, `figures/`, `scripts/` created (Full Project); `checkpoints/manifest.json` written and updated across phases
- [ ] The skill states which harness it detected

### Hypothesis ranking & gates
- [ ] 3–5 candidate framings generated and ranked on explicit axes before the design gate
- [ ] The design gate waits for explicit user approval; the post-literature review gate offers continue/pivot/abort
- [ ] *(Optional)* If the user asks for a tournament, the Elo hypothesis tournament runs (pairwise side-swapped debates, Elo ratings, a `tournament` block in the manifest, and a `checkpoint_NNN_tournament.md` meta-review) — and it does NOT replace the design gate

### Mathematical derivation quality
- [ ] ≥8 numbered, load-bearing steps; the single hardest step is flagged
- [ ] Each non-obvious operation is justified (validity, not just algebra); no padding
- [ ] Sanity checks performed (dimensions / limiting cases / symmetry)
- [ ] Assumptions stated and appended to the ledger (i.i.d., finite mean/variance, characteristic function exists)
- [ ] No "it can be shown that" / "after simplification" without expansion
- [ ] Independent verification: a `scripts/check_*.py` step-chain script (sympy, per-step `STEP <k> [<class>] PASS` lines, seed logged) PASSes on every step
- [ ] Covers: definition of φ_X(t), c.f. of the standardized sum, Taylor expansion of log φ, limit → Gaussian c.f., Lévy continuity theorem

### Literature, novelty & honesty
- [ ] Citations carry resolvable arXiv/DOI/OpenAlex ids confirmed via fetch (no fabricated references)
- [ ] An explicit novelty verdict is given
- [ ] A red-team / review checkpoint exists, produced by a separate invocation
- [ ] Hypotheses and results carry confidence tags

### Checkpointing
- [ ] `checkpoint_000_project_init.md` plus ≥3 more (ranking/design, literature, derivation, visualization, red-team)
- [ ] Each follows the template (Phase, Status, Confidence, Summary, Content, Open Questions, Dependencies)
- [ ] `checkpoint_assumptions.md` ledger present

### Subagent delegation (when `<spawn-subagent>` is available)
- [ ] Literature, derivation, and red-team delegated; orchestrator remains the single writer (subagents return content)
- [ ] No id collisions; the red-team is a separate invocation from the producer

### Visualizations
- [ ] ≥1 `viz_*.py` and ≥1 figure in `figures/`, with a logged seed
- [ ] Histogram convergence to Gaussian across sample sizes, with a quantitative agreement metric
- [ ] Figures referenced inline in checkpoints and the report (not a trailing dump)

### Report quality
- [ ] `report.tex` exists in the working directory (the bundled template was NOT edited in place)
- [ ] Compiles to PDF without errors; `\includegraphics` inline; an Assumptions and Limitations section is present

---

## Running the automated checks

1. Work in a clean directory.
2. Install + launch per your harness (above).
3. Run `bash <skill-dir>/tests/verify_co_scientist.sh` from the working directory.
4. Review the quality checkboxes above manually.

## Pass Criteria

- **Hard pass**: zero `FAIL`s from the verify script and all manual quality items checked
- **Soft pass**: zero `FAIL`s, ≥80% of manual items, remaining items minor
- **Fail**: any `FAIL` from the verify script (missing workspace, <4 checkpoints, step-skipping language, …)
