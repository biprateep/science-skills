# Science Skills

This repository contains a collection of AI agent skills tailored for scientific research, brainstorming, mathematical derivation, and prototyping.

## Note on Customization

> [!WARNING]
> **Not General Purpose**
> These tools and skills are highly customized to suit the specific physics, mathematics, statistics, and AI research needs of the creator. They are not intended as general-purpose, out-of-the-box solutions for all use cases.

## Agent Compatibility

The `co-scientist` skill is **harness-agnostic**: a single `SKILL.md` runs on both
**Claude Code** and **Google Antigravity** (and other harnesses) via a *Harness
Adapter* — a capability map at the top of the skill that the agent resolves to its
own tools at runtime. See `skills/co-scientist/SKILL.md` for the per-harness
mapping and `tests/test_co_scientist_workflow.md` for install paths and launch
commands for each harness. The methodologies are conceptual and adapt to further
frameworks by adding a column to that map.

## Featured Skills

### Co-Scientist (`skills/co-scientist`)
A scientific research partner that develops an idea into grounded, verified,
written-up work. It is built around one rule — **verify substance, don't just
perform process** — and features:
- **Operating modes**: a lightweight path for quick questions and single
  derivations, and a full multi-phase pipeline for research projects.
- **Hypothesis ranking**: generates and ranks competing hypotheses before
  committing to one.
- **Verified mathematics**: step-by-step derivations with dimensional/limiting-case
  sanity checks and independent symbolic + numeric (`sympy`) verification — not
  just well-formatted output.
- **Grounded, fact-checked literature**: every citation resolves to a real
  arXiv/DOI/OpenAlex id, plus an explicit novelty / prior-art verdict.
- **Adversarial red-team**: an independent reviewer tries to break each result
  before it reaches the report.
- **Reproducible computation & data analysis**: seeds, recorded environments, and
  effect sizes — for synthetic data and the user's real datasets.
- **Single-writer subagent orchestration**: a resumable run manifest, an
  assumptions/limitations ledger, and LaTeX reporting that compiles to PDF.

### Jupytext (`skills/jupytext`)
An agent skill that enforces the Jupytext percent format (`py:percent`) for all generated Python scripts. Key features:
- **Dual-Purpose Files**: Scripts are valid `.py` files AND openable as Jupyter notebooks in VS Code, JupyterLab, and PyCharm.
- **Clean Version Control**: Produces human-readable diffs unlike JSON-based `.ipynb` files.
- **Mandatory Structure**: Enforces YAML headers, cell delimiters, narrative markdown, and meaningful chunking.
- **Anti-Pattern Guards**: Prevents common LLM mistakes like missing headers, monolithic cells, and mixed markdown styles.

## Acknowledgments and Sources

This project was built by drawing inspiration and structural methodologies from several excellent open-source projects and documentation guidelines:

- **[K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills)**: Our `co-scientist` skill builds upon their `scientific-brainstorming` workflow template and advanced ideation methodologies (SCAMPER, Six Thinking Hats, etc.).
- **[obra/superpowers](https://github.com/obra/superpowers)**: The phased process flow, gating, and `<HARD-GATE>` mechanisms were inspired by their `brainstorming` skill.
- **[Gemini CLI Skill Best Practices](https://geminicli.com/docs/cli/skills-best-practices/)**: Used to audit and structure the skill prompts for maximum LLM adherence.
- **[Claude Agent Skills Best Practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)**: Provided guidance on using XML tags for constraints and defining explicit anti-patterns.
