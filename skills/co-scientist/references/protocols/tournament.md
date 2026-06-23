# Hypothesis Tournament Protocol (optional add-on)

An opt-in, heavier alternative to the lightweight ranking in **Phase 2**. It
implements the Google "AI co-scientist" selection loop:
**generate → pairwise scientific debate → Elo ranking → evolve → meta-review.**

## When to use it

- The user asks for a "tournament", "Elo ranking", "debate the hypotheses", or
  "maximum rigor on the idea selection", **or**
- You have many strong candidates (≈5+) that the lightweight table cannot
  cleanly separate.

Otherwise, keep the default lightweight ranking — the tournament costs many
subagent calls and is overkill for an obvious winner. Confirm scope with the user
before launching it (state the rough number of debates it will run).

## Inputs

- The candidate hypotheses from Phase 2 (best with **5–8**; need ≥4 to be worth it).
- The research goal and the evaluation axes: **soundness/correctness, novelty,
  testability, plausibility, tractability, alignment with the goal.**

## Procedure

### 1. Seed candidates & initialize ratings

Assign every candidate `H1, H2, …` a starting Elo rating of **1200** and
`wins/losses/draws = 0`, `generation = 0`. Record them in the manifest's
`tournament` block (schema below). Use a fixed `K` factor of **32**.

### 2. Pairwise scientific debates

Each matchup compares two hypotheses via the **Debate subagent** (definition
below). To cancel the well-known **position bias** in LLM pairwise judgments,
debate each pair **twice with the sides swapped** (A-vs-B and B-vs-A); if the two
verdicts disagree, score the pair a **draw**. The orchestrator records each
verdict; the subagent only returns it (single-writer rule).

### 3. Elo update (deterministic)

After each matchup, with ratings `R_A`, `R_B` and outcome `S_A ∈ {1 win, 0.5
draw, 0 loss}` (`S_B = 1 − S_A`):

```
E_A = 1 / (1 + 10^((R_B − R_A) / 400))      # expected score for A
R_A ← R_A + K · (S_A − E_A)                  # K = 32
R_B ← R_B + K · ((1 − S_A) − (1 − E_A))
```

The arithmetic is fully deterministic given the debate outcomes — do it in a
small script (`scripts/elo_tournament.py`) for reproducibility, or by hand for a
few candidates. Update the manifest after every matchup.

### 4. Pairing strategy & budget

- **Round-robin** (small pool, ≤6): every unordered pair once, each played as the
  side-swapped double above ⇒ `N·(N−1)` debates. (N=5 ⇒ 20 debates.)
- **Swiss** (larger pool): run `ceil(log2(N)) + 1` rounds, pairing
  similarly-rated candidates each round; far fewer debates than round-robin.

**Always state the resulting debate count up front and cap it.** If the budget is
tight, prefer Swiss and fewer evolution rounds. Log any cap you applied so
coverage is not silently truncated.

### 5. Evolution (optional, capped)

After a ranking round, optionally **evolve** the top 2–3:

- **Combine** complementary strengths surfaced in the debates into a hybrid.
- **Repair** the specific weaknesses the debates exposed.
- **Mutate** a key assumption to explore an adjacent idea.

Add the evolved candidates (`generation = g+1`) at the current median rating (not
1200 — they are informed), and run one more pairing round. **Cap at 2
generations** unless the user asks for more, to guarantee termination.

### 6. Meta-review & hand-off to the design gate

Synthesize the debates into a **meta-review** checkpoint: the final ranked table
with ratings, the recurring critique patterns (these become red-team targets and
Limitations later), and the single best next experiment. Present the **top 1–2**
at the Phase 3 design gate as usual — the tournament *informs* the gate, it does
not replace user approval.

## State — manifest `tournament` block (resumable)

```json
"tournament": {
  "k_factor": 32, "round": 2, "pairing": "round-robin", "max_generations": 2,
  "candidates": [
    {"id": "H1", "rating": 1287.4, "wins": 4, "losses": 1, "draws": 1,
     "generation": 0, "status": "active"}
  ],
  "matches": [
    {"round": 1, "a": "H1", "b": "H3", "winner": "H1", "sides_swapped": true,
     "rationale_ckpt": "checkpoint_00X_debate_h1_h3.md"}
  ],
  "stopped_reason": "ratings stable | budget cap | max generations"
}
```

Also write a human-readable `checkpoint_NNN_tournament.md` (final ranked table +
meta-review). On resume, read the manifest `tournament` block to continue from the
last completed matchup.

## Debate subagent

- **Spawn** via `<spawn-subagent>` (Antigravity `TypeName: self`; Claude Code
  `subagent_type: general-purpose`). If `<spawn-subagent>` is unavailable, the
  orchestrator runs each debate **inline**.
- **Contract** (per `references/subagents.md`): non-interactive; returns its
  verdict for the orchestrator to record; never writes files or updates ratings
  itself.
- **Prompt template:**
  > "You are judging a scientific debate between two competing hypotheses for the
  > goal: [GOAL].
  > **Hypothesis A:** [A]. **Hypothesis B:** [B].
  > Argue both sides, then judge **A vs B** on: soundness/correctness, novelty,
  > testability, plausibility, tractability, and alignment with the goal. Weight
  > **soundness highest** — a more exciting but likely-wrong idea loses. Give a
  > short rationale per axis, then declare a **winner (A / B / draw)** and a
  > one-line summary of the decisive factor. Be specific and skeptical; do not
  > favor an option for being listed first."

Return value the orchestrator records: `{winner, per_axis_rationale,
decisive_factor}`.

## Determinism & honesty notes

- The Elo math and pairings are deterministic; only the debate judgments are
  model-driven, and the side-swap reduces their variance.
- A high Elo rating means "won debates", **not** "is correct". The winner still
  goes through the normal literature grounding, math/data **verification**, and
  **red-team** phases. The tournament selects what to pursue; it does not certify
  truth.
