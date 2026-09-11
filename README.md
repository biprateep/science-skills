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

That is the whole installation. The script does three things, and skips whatever
this machine does not have:

1. **Registers every skill** in `skills/` with each harness it finds:

   | Harness | Mechanism | Picks up new skills |
   | :--- | :--- | :--- |
   | **Claude Code** | symlinks in `~/.claude/skills/<name>` | rerun the script |
   | **Google Antigravity** | a directory entry in `~/.gemini/config/skills.json` | automatically |

2. **Builds and registers the MCP toolboxes** that skills ship (co-scientist's
   and cite-check's): one `.venv` per toolbox, then an entry in Claude Code
   (`--scope user`), OpenAI Codex (`~/.codex/config.toml`) and Antigravity
   (`mcp_config.json`). This step needs the network and takes a minute — pass
   `--skip-mcp` to leave it out, or run
   `bash skills/co-scientist/mcp/setup_mcp.sh` on its own later.

3. **Asks for registry API keys** that a toolbox can use (cite-check: a NASA
   ADS token, and a contact e-mail for the Crossref/OpenAlex polite pools).
   Typing is not echoed; a token is tested against the registry before it is
   kept; secrets go to the OS keychain (macOS Keychain or Linux Secret
   Service) when there is one and otherwise to a 0600 file under
   `~/.config/cite-check/keys/` — never into a harness config, a command
   line, or this repo. Press Enter to skip a key and that source simply stays
   off while the others work. With no terminal the questions are skipped;
   `--skip-keys` skips them explicitly. Enter or change keys later with
   `bash skills/cite-check/mcp/setup_mcp.sh --keys`.

No skill file is copied — both harnesses read this working tree, so a `git pull`
publishes skill edits immediately, with no reinstall. The script is idempotent,
never touches unrelated skills, MCP servers or config entries, and understands
`--dry-run`, `--skip-mcp`, `--skip-keys` and `--help`. Set `CLAUDE_CONFIG_DIR` or
`GEMINI_CONFIG_DIR` to target a non-default install location.

To undo all of it — symlinks, config entries, MCP registrations and the
toolbox venvs — run the matching uninstaller, which takes the same flags
(stored API keys are kept; `bash skills/cite-check/mcp/setup_mcp.sh --uninstall
--purge-keys` forgets them too):

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
ls -l ~/.claude/skills                     # one symlink per skill into this repo
claude mcp list | grep -E 'co-scientist|cite-check'   # ✔ Connected
```

In a fresh Claude Code session, `/co-scientist`, `/cite-check`, `/co-writer`,
`/jupytext` and `/plot-style` should appear; in Antigravity the skills show up in the
skills menu.

cite-check uses NASA ADS when a token was entered at install time (astronomy
search and ADS BibTeX exports); `bash skills/cite-check/mcp/setup_mcp.sh --keys`
adds or changes it, and `python skills/cite-check/mcp/server.py keys list`
shows what is configured — see `skills/cite-check/references/registries.md`.

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

### Cite-Check (`skills/cite-check`)
Citation integrity for anything the agent writes with references, built on
the co-scientist `resolve_citation` idea and hardened against the ways an LLM
bibliography actually fails:
- **Existence, properly tested**: every entry's own DOI / arXiv id / bibcode is
  resolved and its title, first author and year compared with the registry
  record — a real DOI on an invented title is a `MISMATCH`, not a pass.
  Entries with no identifier (a third of a real astronomy `.bib`) are searched
  by title, author and year across registries.
- **Official BibTeX only**: entries are fetched from NASA ADS, Crossref,
  DataCite, INSPIRE or arXiv exports, stamped with a provenance comment, and
  inserted by the tool; nothing is hand-written.
- **Search that does not trust the registries**: candidates from ADS, arXiv,
  Crossref, OpenAlex and INSPIRE are merged and re-ranked locally (Crossref and
  OpenAlex both rank a fraudulent republication of *Attention Is All You Need*
  first).
- **Claim support**: each citation instance is extracted with its sentence,
  the cited paper's text is fetched (arXiv HTML/PDF, open-access PDF, else
  abstract, or your own PDF), an independent judge returns a verdict, and the
  ledger accepts `SUPPORTS` only with quotes the tool finds verbatim in the
  paper.
- **An audit gate** (`audit`) that fails on undefined keys, unresolved or
  mismatched entries, and unsupported or unjudged claims, and writes a
  Markdown report.
- **MCP Toolbox** (`skills/cite-check/mcp/`), installed and registered by
  `scripts/install.sh`; `co-writer` and `co-scientist` are meant to call it
  rather than verify citations themselves (`references/integration.md`).

### Co-Writer (`skills/co-writer`)
Writes and rewrites paper prose in the author's own voice — from rough notes,
an agent's draft or a collaborator's section — preserving the information and
changing only how it is said. Key features:
- **One profile, evidence-backed**: `references/voice-profile.md` holds graded
  rules (HARD / STRONG / LIGHT), a Never list, the words a de-AI pass must leave
  alone, and verbatim exemplars indexed by section function (abstract, gap,
  methods, equation, results, limitation, close, caption); every rule is traced
  to excerpts in `references/extraction-report.md` and ratified in an interview.
- **Preservation outranks voice**: numbers survive exactly, a claim never moves
  up the profile's ladder (`proves > demonstrates > shows > indicates > is
  consistent with > suggests`), the citation set never grows, LaTeX markup
  passes through untouched, and flourish with no checkable content is dropped.
- **Built from the papers, not from self-description**: `scripts/extract_prose.py`
  turns `.tex` into readable prose, `references/extraction.md` is the deep-read
  prompt, and `references/interview.md` asks only what the text cannot answer.
- **Improves from use**: every rewrite is logged; `scripts/capture_edits.py`
  diffs what was delivered against what the author committed, and
  `scripts/collect_transcripts.py` indexes the Claude Code and Antigravity
  sessions behind a paper. A fixed six-input `eval/` set scores each profile
  version by how much the author still edits.
- Papers only, for now — astrophysics, physics and ML manuscripts in LaTeX.
  Citations are cite-check's job, not co-writer's.

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
