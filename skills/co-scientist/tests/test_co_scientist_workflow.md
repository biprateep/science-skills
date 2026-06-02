# Co-Scientist Skill Test Workflow

## Test Scenario: Central Limit Theorem from First Principles

### Test Prompt

Use this prompt with `/goal` to run an autonomous end-to-end test:

> I'm interested in understanding the Central Limit Theorem from first
> principles. Help me derive it rigorously using characteristic functions,
> verify it numerically with a simulation, and write up the results as a
> LaTeX report.

### Why This Tests All 5 Flaws

| Flaw | What This Tests |
|------|----------------|
| #1 Activation | Prompt uses "derive", "first principles", "understand" — should trigger co-scientist |
| #2 Math steps | CLT derivation via characteristic functions has ≥8 logical steps |
| #3 Checkpoints | Multiple phases: formulation → literature → derivation → simulation → report |
| #4 Subagents | Natural split: literature review, math derivation, and visualization are independent |
| #5 Visualization | Histogram convergence to Gaussian is the canonical CLT visualization |

---

## Expected Outcomes

### Flaw #1: Activation
- [ ] The co-scientist skill activates on the test prompt
- [ ] The agent follows the co-scientist checklist (workspace init, strategy consultation, etc.)
- [ ] The agent creates the `checkpoints/`, `figures/`, and `scripts/` directories

### Flaw #2: Mathematical Derivation Quality
- [ ] Derivation shows ≥8 numbered equation steps
- [ ] Each step states the operation being applied (e.g., "take the logarithm of both sides")
- [ ] Intermediate algebra is shown (not skipped)
- [ ] Assumptions are explicitly stated:
  - i.i.d. random variables
  - Finite mean and variance
  - Characteristic function exists
- [ ] No instances of "it can be shown that" or "after simplification" without expansion
- [ ] Derivation covers:
  - Definition of characteristic function φ_X(t)
  - Characteristic function of the standardized sum
  - Taylor expansion of log(φ_X(t/√n))
  - Limit as n → ∞ giving the Gaussian characteristic function
  - Lévy's continuity theorem to conclude convergence in distribution

### Flaw #3: Checkpointing
- [ ] A `checkpoints/` directory exists
- [ ] `checkpoint_000_project_init.md` exists with the research goal
- [ ] At least 4 additional checkpoint files exist covering:
  - Problem formulation / hypothesis approval
  - Literature review on CLT
  - Mathematical derivation
  - Visualization / simulation
- [ ] Each checkpoint follows the template format (Date, Phase, Status, Summary, Content, Open Questions, Dependencies)

### Flaw #4: Subagent Delegation
- [ ] At least 2 subagents are spawned
- [ ] Literature review is delegated to a `research` subagent
- [ ] Math derivation is delegated to a `self` subagent with derivation-specific prompt
- [ ] Main agent context is preserved for orchestration (not exhausted on derivation details)

### Flaw #5: Visualizations
- [ ] At least 1 Python script is created in `scripts/` (e.g., `viz_001_clt_convergence.py`)
- [ ] At least 1 figure is saved to `figures/` (e.g., `fig_001_clt_convergence.png`)
- [ ] The figure shows histogram convergence to Gaussian for multiple sample sizes
- [ ] The figure is embedded **inline** in the relevant checkpoint (not in a separate "Figures" section)
- [ ] The LaTeX report includes `\includegraphics` **inline** in the Mathematical Derivations or Results section
- [ ] Figure has a caption explaining what it shows

### Report Quality
- [ ] LaTeX report compiles to PDF without errors
- [ ] Report has populated Introduction, Literature Review, Mathematical Derivations, and Results sections
- [ ] Figures appear inline within the relevant sections (not grouped at the end)

---

## Running the Test

1. Navigate to a clean test directory
2. Ensure the co-scientist skill is discoverable (in `.agents/` or plugin config)
3. Run: `/goal` followed by the test prompt above
4. After completion, run `tests/verify_co_scientist.sh` from the test directory
5. Review the checklist above manually for quality items

## Pass Criteria

- **Hard pass**: All checkbox items above are checked
- **Soft pass**: ≥80% of items checked, with remaining items being minor quality issues
- **Fail**: Any of the 5 flaw categories has zero items checked
