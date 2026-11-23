# The cold read

Read after the self-check, in section and draft mode always and in paragraph
mode when an agent is available. Who reads, what it is given, the brief, and
what the writer does with what comes back.

The session that has just written a passage is the worst-placed reader it will
ever have: it knows what every sentence was meant to do. So the litmus question
— would the author have written this? — is never answered by the writer. It
goes to a reader that never saw the composition.

**Who.** A separate agent: Claude Code `Agent` (general-purpose); Codex
`spawn_agent` with `fork_turns: "none"`, then `wait_agent`; Antigravity
`invoke_subagent` with `TypeName: "self"`; a harness with none, a later pass in
a fresh context with the text in front of you and nothing else, recorded in the
session log as `cold_read: no`. Section and draft mode: always. A single
paragraph: when an agent is available.

**What it gets.** The output, the active profile path (from
`cowriter.py profile`), the slot and the register. Never the input, never the
content list, never the writer's reasoning — a reader told what a passage was
meant to do reads what it was meant to do.

**The brief.** Hand it over with the slots filled.

> Read the passage at `<path>` as its author would, and report what they would
> not have written. You rewrite nothing and propose no sentences. Their voice
> profile is `<profile path>`; read it whole, specimens first (if any exist; on
> a `0.0.0` starter profile with no specimens yet, judge against generic
> LLM-isms, mannered phrasing, and the profile's starter rules). The passage is
> a `<slot>` from a `<journal | workshop>` paper.
>
> Answer three questions, each item with the sentence quoted.
> 1. Which sentences read as a model imitating the author (or defaulting to
>    generic LLM prose) rather than as them? Name the construction that gives
>    each away.
> 2. Where is a signature from the profile stacked — a construction used more
>    than twice in one paragraph, or a stock transition or gloss that carries
>    nothing?
> 3. Which claims read stronger than a careful referee would accept as
>    written — a hedge missing, a result verb above what the sentence's
>    evidence supports, a flourish standing where a fact should be?
>
> Nothing else is a finding: not length, not what the passage says twice, not
> whether you would have said it differently. If you find nothing under a
> question, say so; a clean answer is information. Order each list by how
> much it matters. Say what you mean — no metaphor where a literal phrase
> exists. Do not certify the voice, and do not stop to ask.

**What the writer does with it.** Check each item against the profile and the
specimen; a construction the profile attests is not a finding. For each that
survives, re-read the specimen for the slot (if present) and write that stretch
again. Do not patch the sentence against the Never list — a passage revised
against a list gets worse. One round; then the passage moves on. The cold read
describes; only the author certifies.
