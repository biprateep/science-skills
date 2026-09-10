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
mapping. The methodologies are conceptual and adapt to further frameworks by
adding a column to that map.

## Installation

Clone the repo anywhere, then run the one script:

```sh
git clone https://github.com/biprateep/science-skills.git
bash science-skills/scripts/install.sh
```

That is the whole installation. The script does two things, and skips whatever
this machine does not have:

1. **Registers every skill** in `skills/` with each harness it finds:

   | Harness | Mechanism | Picks up new skills |
   | :--- | :--- | :--- |
   | **Claude Code** | symlinks in `~/.claude/skills/<name>` | rerun the script |
   | **Google Antigravity** | a directory entry in `~/.gemini/config/skills.json` | automatically |

2. **Builds and registers the MCP toolboxes** that skills ship (currently
   co-scientist's): one `.venv` per toolbox, then an entry in Claude Code
   (`--scope user`), OpenAI Codex (`~/.codex/config.toml`) and Antigravity
   (`mcp_config.json`). This step needs the network and takes a minute — pass
   `--skip-mcp` to leave it out, or run
   `bash skills/co-scientist/mcp/setup_mcp.sh` on its own later.

No skill file is copied — both harnesses read this working tree, so a `git pull`
publishes skill edits immediately, with no reinstall. The script is idempotent,
never touches unrelated skills, MCP servers or config entries, and understands
`--dry-run`, `--skip-mcp` and `--help`. Set `CLAUDE_CONFIG_DIR` or
`GEMINI_CONFIG_DIR` to target a non-default install location.

To undo all of it — symlinks, config entries, MCP registrations and the
toolbox venvs — run the matching uninstaller, which takes the same flags:

```sh
bash science-skills/scripts/uninstall.sh --dry-run   # see what would go
bash science-skills/scripts/uninstall.sh             # do it
```

It leaves the clone itself in place; delete that by hand if you want it gone.

A directory under `skills/` is installed only if it contains a `SKILL.md`;
work-in-progress folders are reported and skipped.

**Skills and MCP servers load at the next session start**, so restart the
harness before looking for them. To confirm the install took:

```sh
ls -l ~/.claude/skills                     # three symlinks into this repo
claude mcp list | grep co-scientist        # ✔ Connected
```

In a fresh Claude Code session, `/co-scientist`, `/jupytext` and `/plot-style`
should appear; in Antigravity the skills show up in the skills menu.

For other harnesses (OpenAI Codex, Cursor, …) place or reference the skill
folder wherever that agent discovers instructions — the Harness Adapter maps the
capabilities.

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
- **MCP Toolbox** (`skills/co-scientist/mcp/`): the enforcement-critical core —
  step-chain CAS verification, citation resolution, file-locked manifest
  state, figure validation, and a gate-enforcing report compiler — implemented
  as an MCP server, so verdicts come from code the agent cannot narrate around.
  `scripts/install.sh` builds and registers it in every harness found on the
  machine; `bash skills/co-scientist/mcp/setup_mcp.sh` does the same step alone.
  The skill self-bootstraps: if the tools are absent at run time it runs this
  script itself and falls back to the identical CLI interface
  (`mcp/server.py call <tool> '<json>'`) for the current session.

### Jupytext (`skills/jupytext`)
An agent skill that enforces the Jupytext percent format (`py:percent`) for all generated Python scripts. Key features:
- **Dual-Purpose Files**: Scripts are valid `.py` files AND openable as Jupyter notebooks in VS Code, JupyterLab, and PyCharm.
- **Clean Version Control**: Produces human-readable diffs unlike JSON-based `.ipynb` files.
- **Mandatory Structure**: Enforces YAML headers, cell delimiters, narrative markdown, and meaningful chunking.
- **Anti-Pattern Guards**: Prevents common LLM mistakes like missing headers, monolithic cells, and mixed markdown styles.

### Plot Style (`skills/plot-style`)
Enforces a single publication matplotlib aesthetic on every figure, derived from
the figure code in real AASTeX (AJ/ApJ) manuscripts. Key features:
- **Journal geometry**: figure widths are always the measured `\columnwidth` or
  `\textwidth` of a registered journal class (AASTeX by default; add another
  with one `register_journal()` call), heights a named aspect of that width — so
  figures drop into the manuscript unscaled and print with the same type size
  as the surrounding text.
- **One preamble, every glyph**: Nimbus Roman serif at the manuscript's
  9/10/12 pt with Computer Modern math, on ticks, labels, titles, legends,
  colorbars and annotations alike; inward ticks on all four sides; frameless
  legends — set once, never patched per-axis.
- **Idiom library** (`assets/plotstyle.py`): stacked histograms, shared
  colorbars, one-to-one comparisons, and equal-count running-median bands, each
  as a helper plus a copy-paste template in `references/recipes.md`.
- **Matplotlib's own palettes** unless the user names one: the default cycle
  for series, `viridis` for continuous data, pinned by the style sheet; a
  stated palette is installed once in the preamble and series still address
  it by `C`-index.
- **Press-ready output**: tight 300 dpi PNG, every time.
- **Enforced, not narrated**: `verify_style()` fails at run time if the serif
  face silently fell back to DejaVu, and `scripts/check_plot_style.py` lints a
  plotting script for invented figure sizes, vector output, boxed legends,
  hand-picked colours, unrequested third-party palettes and numeric font sizes.

## Acknowledgments and Sources

This project was built by drawing inspiration and structural methodologies from several excellent open-source projects and documentation guidelines:

- **[K-Dense-AI/scientific-agent-skills](https://github.com/K-Dense-AI/scientific-agent-skills)**: Our `co-scientist` skill builds upon their `scientific-brainstorming` workflow template and advanced ideation methodologies (SCAMPER, Six Thinking Hats, etc.).
- **[obra/superpowers](https://github.com/obra/superpowers)**: The phased process flow, gating, and `<HARD-GATE>` mechanisms were inspired by their `brainstorming` skill.
- **[Gemini CLI Skill Best Practices](https://geminicli.com/docs/cli/skills-best-practices/)**: Used to audit and structure the skill prompts for maximum LLM adherence.
- **[Claude Agent Skills Best Practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)**: Provided guidance on using XML tags for constraints and defining explicit anti-patterns.
