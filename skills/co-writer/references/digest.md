# The digest — brief for the agent that runs it

Not read at write time. Read by the agent that turns a packet of the
author's edits into a proposal, when the author says "co-writer update".
`cowriter.py packet` copies this file into each packet, so the packet
directory is all the agent needs.

## What you are given

A packet directory, `~/.co-writer/packets/<stamp>/`, holding:

| file | what it is |
|---|---|
| `pairs.jsonl` | one record per paragraph an agent delivered and the author later changed: `delivered`, `accepted` (the author's version), `draft` (the author's text the delivery rewrote, when found), `feedback` (the author's chat turns in between, verbatim), `agent_spans` (added runs of six or more words that an agent wrote earlier: a merge or a pasted suggestion), `slot`, `distance`, and where each came from |
| `notes.md` | log entries since the last proposal that carry a Note or an Unsure — the author's words about outputs, verbatim |
| `voice-profile.md` | the profile as it stands |
| `counterexamples.md` | the sentences already recorded as rejected |
| `digest.md` | this brief |

A file named `extra-*.md`, if present, was added by hand for this digest;
it says what it holds. Read it with the rest.

The harvester's pairing is a heuristic. Treat each record as a claim to check
against its own fields, not as a fact. Two fields help: `agent_spans` (words
the author's version shares with earlier agent text, so not theirs) and
`provenance: uncertain` (the accepted text first appeared in a commit that
carries an agent's fingerprints, so an agent may have written it; weak
evidence at best).

## What you do

1. **Sort every record into one of four piles**, and say which for each id:
   - **voice**: the author changed how something is said: word choice,
     order, length, register, what a caption or paragraph opens with,
     which details a sentence carries. This pile is the signal.
   - **content**: the author changed what is said: a new number, a
     corrected fact, a new result, a claim weakened because it was wrong, a
     sentence added to report something the delivery lacked. Not voice.
     The profile must never learn to change content.
   - **artifact**: the difference is not the author's: most of the change
     is `agent_spans`, the delivered and accepted texts are not the same
     paragraph, or the feedback shows an agent made the change.
   - **trim**: the change is a cut for a page or word limit, visible from
     the feedback or from wholesale shortening across a session. Record it,
     but a cut made to fit is weak evidence about voice; it counts only
     where the same move also appears outside a trim.
2. **Cluster the voice pile.** An edit that recurs — the same word
   replaced, the same kind of clause dropped, the same opening rewritten —
   across two or more records is a pattern. A single edit is a pattern only
   when the author stated it as a rule in `feedback` or `notes.md`.
3. **Turn each pattern into a candidate**: the smallest change to
   `voice-profile.md` that would have produced what the author accepted.
   One of:
   - a **Never** entry, or a **words that stay** entry;
   - a rule **regraded** (LIGHT → STRONG, or down), or a new rule with its
     grade;
   - a new **specimen** for a slot, quoted verbatim from an `accepted`
     text, with the content nouns named for the quarantine list;
   - a **counterexample** for `counterexamples.md`: the delivered sentence,
     the author's objection verbatim from `feedback`, and what they
     accepted instead.
   Check each candidate against the profile first. If the profile already
   says it, the candidate is not a new rule: it is evidence that the rule
   is not being followed. Say so and propose a stronger grade or a
   specimen, not a duplicate.
4. **Give each candidate your lean**, one of the three routes in
   [maintenance.md](maintenance.md):
   - **adopt**: only when the author's own words state it, quoted with the
     record id or log entry;
   - **test**: when it is your reading of their edits; name the record ids
     whose `draft` or `delivered` input the test would rerun;
   - **hold**: when the evidence is one or two records and nothing the
     author said.
   Check the profile's Rejected section; a candidate recorded there is not
   proposed again unless new evidence answers the reason it was rejected.

## What you write

Exactly one file, `proposal.md`, in the packet directory. Nothing else is
written: not the profile, not the counterexamples, not the store. The author
rules; the review session applies the rulings.

```
---
status: pending
packet: <the packet directory name>
profile_version: <the Version line of the packet's voice-profile.md>
records: <n> (voice <a>, content <b>, artifact <c>, trim <d>)
---
# Digest proposal, <date>

## Candidates

### C1 · <Never | stays | regrade | rule | specimen | counterexample> · lean: <adopt | test | hold>
**Change.** <the exact text to add or replace, and where: § and line>
**Evidence.** <record ids; for each, the few words of the diff that show
it, as `delivered` → `accepted`>
**Author's words.** <verbatim quotes with their source, or "none">
**Test.** <for lean: test, the record ids to rerun and what counts as
passing>

### C2 ...

## Not voice
- content: <ids, one line each on what fact changed>
- artifact: <ids, one line each on why>
- trim: <ids>

## Rulings
<left empty; the review fills it>
```

Rules for the file:

- Quote, do not paraphrase, the author's words and the texts. A diff is
  shown as the words that changed, `delivered` → `accepted`, never
  reworded.
- Order candidates by the strength of the evidence, strongest first.
- At most ten candidates. If there are more, keep the ten with the most
  evidence and list the rest by one line under "Held for the next digest".
- Never propose a change that would alter a number, a claim's strength, a
  citation or a piece of markup; those are preservation rules and outrank
  voice.
- Never certify the profile ("the profile now captures the author's voice"). Report
  what the edits show.
