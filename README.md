# Science Skills

This repository contains a collection of AI agent skills tailored for scientific research: brainstorming, mathematical derivation, prototyping, code style, publication figures, citation integrity and paper writing.

## Note on Customization

> [!WARNING]
> **Not General Purpose**
> These tools and skills are highly customized to suit the specific physics, mathematics, statistics, and AI research needs of the creator. They are not intended as general-purpose, out-of-the-box solutions for all use cases.

## Agent Compatibility

Every skill here is **harness-agnostic**: a single `SKILL.md` runs on
**Claude Code**, **Google Antigravity** and other harnesses. The two that ship
an MCP toolbox (`co-scientist`, `cite-check`) carry a *Harness Adapter* — a
capability map at the top of the skill that the agent resolves to its own
tools at runtime, with a CLI fallback that runs the same code. The others
(`code-style`, `co-writer`, `jupytext`, `plot-style`) need only file access and
a shell with Python 3 (`code-style` runs its checks through
[uv](https://docs.astral.sh/uv/)). The methodologies are conceptual and adapt
to further frameworks by adding a column to a map.

## Installation

Clone the repo anywhere, then run the one script:

```sh
git clone https://github.com/biprateep/science-skills.git
bash science-skills/scripts/install.sh
```

That is the whole installation. The script does four things, and skips whatever
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

4. **Checks the tools the skills run** — [uv](https://docs.astral.sh/uv/)
   (`code-style` formats, lints and type-checks through it; the toolboxes also
   build faster with it) and Python 3.10+ — and prints the install command for
   any that is missing. It installs neither itself; without them the skills
   still load, only `code-style`'s checks cannot run.

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
`/code-style`, `/jupytext` and `/plot-style` should appear; in Antigravity the
skills show up in the skills menu.

cite-check uses NASA ADS when a token was entered at install time (astronomy
search and ADS BibTeX exports); `bash skills/cite-check/mcp/setup_mcp.sh --keys`
adds or changes it, and `python skills/cite-check/mcp/server.py keys list`
shows what is configured — see `skills/cite-check/references/registries.md`.

For other harnesses (OpenAI Codex, Cursor, …) place or reference the skill
folder wherever that agent discovers instructions — the Harness Adapter maps the
capabilities.

### Updating

On each machine where the skills are installed, pull and rerun the installer:

```sh
git -C science-skills pull
bash science-skills/scripts/install.sh
```

The pull alone makes edits to existing skills live. The rerun covers what a
pull cannot: it links skills that are new since the last run into Claude Code,
removes the links of skills renamed or deleted upstream, reinstalls each MCP
toolbox's requirements, and repeats the tool check. Antigravity scans
`skills/` and needs nothing. As always, restart the harness to load the changes.

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
- **Reproducible computation & data analysis**: seeds, an environment locked
  by uv (`uv.lock`), and effect sizes — for synthetic data and the user's real
  datasets.
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
  alone, and verbatim specimens indexed by section function (abstract, gap,
  methods, equation, results, limitation, close, caption); every rule is traced
  to excerpts in `references/extraction-report.md` and ratified in an interview.
- **Preservation outranks voice**: numbers survive exactly, a claim never moves
  up the profile's ladder (`proves > demonstrates > shows > indicates > is
  consistent with > suggests`), the citation set never grows, LaTeX markup
  passes through untouched, and flourish with no checkable content is dropped;
  `scripts/check_fixed.py` gates all of it, and a cold read by an agent that
  never saw the input answers the question the writer cannot — would the
  author have written this.
- **Built from the papers, not from self-description**: `scripts/extract_prose.py`
  turns `.tex` into readable prose, `references/extraction.md` is the deep-read
  prompt, and `references/interview.md` asks only what the text cannot answer.
- **Improves from use**: every rewrite is logged; `scripts/capture_edits.py`
  diffs what was delivered against what the author committed, and
  `scripts/collect_transcripts.py` indexes the Claude Code and Antigravity
  sessions behind a paper. A fixed six-input `eval/` set scores each profile
  version by how much the author still edits.
- **Citations go through cite-check**, never through co-writer's own
  reasoning: a rewrite that touches a citing sentence is re-judged against
  the cited paper, a citation gap is filled by `search_citation` → `bib_add`,
  and a draft is finished only when cite-check's `audit` is ok. co-writer
  keeps one check of its own — the citation set never grows or moves.
- Papers only, for now — astrophysics, physics and ML manuscripts in LaTeX.

The committed profile is the repository author's voice. To make it yours:
extract prose from your own papers (`python skills/co-writer/scripts/extract_prose.py
paper/main.tex … --out-dir prose/`), run the deep read in
`references/extraction.md` over it, answer `references/interview.md`, and
write `references/voice-profile.md` from the two — then let the capture loop
correct it as you use it.

### Code Style (`skills/code-style`)
Every line of Python an agent writes follows the
[Google Python Style Guide](https://google.github.io/styleguide/pyguide.html),
with a modern toolchain in place of Google's own:
- **The whole guide, restated**: `references/rules.md` goes through it
  section by section — imports of modules only, Google docstrings,
  exceptions, defaults, truthiness, resources, naming, `main()`, type
  annotations — with the reason for each rule, an example from scientific
  code, and the check that enforces it.
- **ruff for lint and format** in place of pylint and Black:
  `assets/ruff.toml` selects the ruff equivalents of the checks Google's
  pylintrc keeps and of the guide's own rules (80 columns, Google docstring
  convention, Google import order), each annotated with its guide section.
- **uv for Python, environments and dependencies**: projects through
  `uv init` / `uv add` with a committed `uv.lock`, standalone scripts through
  inline PEP 723 metadata — including where that block goes in a jupytext
  notebook.
- **mypy in place of pytype**, which Google has discontinued
  (`assets/mypy.ini`); every function signature is annotated.
- **A checker for what ruff cannot express** (`scripts/check_code_style.py`,
  standard library only): member imports resolved against the real packages,
  NumPy- or reST-style docstrings, a notebook's title cell standing in for
  its module docstring, `@staticmethod`, asserts used for validation,
  unclosed h5py/FITS/xarray handles and figures, the TODO layout, top-level
  program code, and more — 30 rules, each tied to a guide section, with
  tests.
- **Research code in mind**: shapes and units in docstrings, NumPy
  truthiness, paper notation with a citation, explicit random generators,
  and notebook-specific allowances agreed with `jupytext` and `plot-style`.
- **Followed across the repository**: the examples of `jupytext` and
  `plot-style`, plot-style's helper and checker, co-writer's scripts and
  co-scientist's script template are all written to it.

### Jupytext (`skills/jupytext`)
An agent skill that enforces the Jupytext percent format (`py:percent`) for all generated Python scripts. Key features:
- **Dual-Purpose Files**: Scripts are valid `.py` files AND openable as Jupyter notebooks in VS Code, JupyterLab, and PyCharm.
- **Clean Version Control**: Produces human-readable diffs unlike JSON-based `.ipynb` files.
- **Mandatory Structure**: Enforces YAML headers, cell delimiters, narrative markdown, and meaningful chunking.
- **Anti-Pattern Guards**: Prevents common LLM mistakes like missing headers, monolithic cells, and mixed markdown styles.
- **Code-style inside the cells**: the complete example follows `code-style` — modules imported, constants in a configuration cell, the figure closed once saved.

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
  as a helper plus a copy-paste template in `references/recipes.md`. The
  helper follows `code-style` (typed, Google docstrings) and is imported as a
  module: `import plotstyle`, then `plotstyle.use_style()`.
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
- **[lout33/writing-style-skill](https://github.com/lout33/writing-style-skill)**: The packaging of `co-writer` — a thin `SKILL.md` over a profile in `references/`, and the "return only the rewritten text" output discipline — follows this skill.
- **[Artificial Corner, "Voice"](https://artificialcorner.com/p/voice)** and **[AI Blew My Mind, "Claude Skills: AI that writes like you"](https://aiblewmymind.substack.com/p/claude-skills-ai-write-like-you)**: `co-writer`'s interview instrument (push back on vague answers, reject the aspirational and the generic, grade rules HARD / STRONG / LIGHT, weight rejections over preferences) and its extraction-first method with a size cap on the profile come from these two write-ups.
- **[biprateep/conceptual_intro_to_deep_learning](https://github.com/biprateep/conceptual_intro_to_deep_learning)** (`.claude/skills`): the book-writing skills there supplied `co-writer`'s cold read, its trim protocol (measure first, two classes of cut, scaffolding never cut, the author rules on each), the tested route for profile changes, and the ported `check_fixed.py` and `check_mannered.py`.
- **[Google Python Style Guide](https://google.github.io/styleguide/pyguide.html)** and its **[pylintrc](https://google.github.io/styleguide/pylintrc)** (© Google, [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/)): `code-style` restates the guide's rules in its own words and maps them, and the pylintrc's checks, onto ruff, mypy and uv.
- **[cheyanneshariat/OverCite](https://github.com/cheyanneshariat/OverCite)** and **[biprateep/zerovibes](https://github.com/biprateep/zerovibes)**: `cite-check`'s registry search with official ADS export, and its tiered title-search verifier, grew from these.
