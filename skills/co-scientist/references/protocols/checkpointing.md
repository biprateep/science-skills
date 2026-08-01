# Checkpointing, Run Manifest & Ledger Protocol

Read this at **Phase 0** and keep it open: checkpoints and the manifest are
updated throughout the run. Used in **Full Project** mode (Derivation mode may
write a single optional checkpoint; Quick mode writes none).

## Directory

All run artifacts live in the **current working directory** (never in the skill's
own install directory):

- `checkpoints/` — markdown checkpoints + the manifest
- `figures/` — generated figures
- `scripts/` — generated scripts (derivation checks, experiments, viz)

Create them in Phase 0 if absent.

## Single-Writer Rule

The **orchestrator** is the sole writer of checkpoints and the manifest, and the
sole authority for `NNN` ids. Subagents return content; the orchestrator assigns
the id, writes the file, and updates the manifest. This works on every harness
(including ones where subagents are isolated) and removes id-collision races.

**Where the MCP Toolbox is available, this rule is mechanically enforced** —
never hand-edit `manifest.json`; go through the tools (all file-locked):

| Operation | Tool |
|-----------|------|
| Create workspace + manifest (Phase 0; idempotent, resumes if present) | `manifest_init(workdir, run_id, goal, harness, mode)` |
| Read state (first thing on resume) | `manifest_read(workdir)` |
| Add checkpoint (pass `descriptor` + `phase`; the **tool** allocates the id and filename) | `manifest_append(workdir, "checkpoints", entry)` |
| Add hypothesis / citation / figure | `manifest_append(workdir, section, entry)` |
| Update run scalars (`phase`, `next_action`, …) | `manifest_set(workdir, fields)` |
| Set status / verified | `manifest_update_checkpoint(workdir, id, status, verified, evidence)` |

Two invariants the tools enforce that prose could only request: new checkpoints
always start `verified: false` (a `verified: true` passed to `manifest_append`
is stripped), and flipping to `verified: true` **requires an evidence string**
(which check ran, where, with what result). The checkpoint **markdown files**
are still written by the orchestrator with `<write-file>` as before — the tools
own only the manifest.

## Naming Convention

`checkpoint_NNN_<short_descriptor>.md`, `NNN` zero-padded, allocated from the
manifest's `next_id`. Examples:

- `checkpoint_000_project_init.md`
- `checkpoint_001_hypothesis_ranking.md`
- `checkpoint_002_design_approved.md`
- `checkpoint_003_literature.md`
- `checkpoint_004_derivation_hamiltonian.md`
- `checkpoint_005_redteam.md`

## Run Manifest — `checkpoints/manifest.json`

The single machine-readable source of truth. Created in Phase 0, **updated after
every phase**. On resume (new session / context loss), read it first to
reconstruct state. Schema:

```json
{
  "run_id": "<slug-or-timestamp passed in by the user/orchestrator>",
  "harness": "claude-code | antigravity | other",
  "mode": "full-project",
  "goal": "<one-line research goal>",
  "next_id": 6,
  "phase": "redteam",
  "hypotheses": [
    {"id": "H1", "text": "...", "scores": {"novelty": 4, "testability": 5,
     "plausibility": 3, "tractability": 4}, "rank": 1, "status": "selected"}
  ],
  "checkpoints": [
    {"id": "004", "file": "checkpoint_004_derivation_hamiltonian.md",
     "phase": "derivation", "status": "complete", "owner": "derivation-subagent",
     "verified": true, "depends_on": ["002", "003"]}
  ],
  "citations": [
    {"key": "smith2019", "id": "arXiv:1906.01234", "resolved": true,
     "supports": "claim about X"}
  ],
  "figures": [
    {"file": "fig_001_clt_convergence.png", "script": "viz_001_clt_convergence.py",
     "checkpoint": "006", "seed": 1234}
  ],
  "next_action": "resolve red-team critical #2 before assembling report"
}
```

Do not invent timestamps if your harness forbids nondeterministic clock calls in
this context; use a `run_id` provided by the user or derived from the goal.

## Checkpoint Template

```markdown
# Checkpoint NNN: <Title>

**Phase**: <init | clarify | ranking | design | literature | derivation | data | redteam | visualization | synthesis | report>
**Status**: <in-progress | complete | needs-revision>
**Confidence**: <high | medium | speculative> — <one-line reason>
**Verified**: <yes (symbolic+numeric / re-fetched citation / red-team passed) | n/a>

## Summary
<2-3 sentence summary.>

## Content
<The ideas, derivations, literature notes, data results, figures, etc.>

## Open Questions
<Unresolved questions / next steps.>

## Dependencies
<Which prior checkpoints (by id) this builds on.>
```

Checkpoint at **meaningful phase boundaries** — not after every micro-event. A
phase that produced a real result gets one checkpoint; trivial intermediate steps
do not.

## Assumptions & Limitations Ledger — `checkpoints/checkpoint_assumptions.md`

Every derivation and experiment **appends** its assumptions here so the whole
result's foundations are visible in one place. Before report assembly, do a
consistency pass (do any two assumptions contradict? was any later violated by an
experiment?). This ledger becomes the report's **Assumptions and Limitations**
section.

| Assumption | Where introduced | Justification | How it could fail | Validated? |
|------------|------------------|---------------|-------------------|------------|
| m constant in time | Lagrangian step 2 | non-relativistic regime | breaks at high v | n/a |

## Reproducibility

Anything stochastic or computational must be reproducible:

- Every generated script **sets and logs an explicit RNG seed**.
- Each run records its environment (Python version + key library versions) into
  the relevant checkpoint, and the project ships a `requirements.txt`
  (see `resources/requirements.txt`).
- Record the exact command used to produce each figure/result in the manifest.
