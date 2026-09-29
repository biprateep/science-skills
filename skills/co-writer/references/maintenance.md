# Maintenance — the improvement loop

Not read at write time. How the profile improves from use: log, update
(harvest and digest), review, eval, new paper. Logging happens at every
rewrite; the update runs only when the author asks for it; the profile
changes only when the author rules.

```
every rewrite ──► cowriter.py log ──► ~/.co-writer/papers/<paper>/log/ (+ snapshot of the .tex)
                                                  │
author edits the text (file, Overleaf, chat)      │
                                                  ▼
"co-writer update" ──► update.sh ──► harvest ──► pairs.jsonl (draft → delivered → accepted)
                                       │
                                       ▼  if any edit is new
                            packet ──► digest agent ──► proposals/<stamp>.md  (status: pending)
                                                              │
                    "co-writer review" ◄──────────────────────┘
                      the author rules on each candidate ──► voice-profile.md, counterexamples.md
```

## 1. Log (every rewrite, any agent)

[session-log.md](session-log.md): `cowriter.py log` after each delivery,
`cowriter.py session` at the end. One script, one format, one location —
`~/.co-writer/`, never a repository. `log` also snapshots the `.tex` as it
stands, so the state at delivery is kept even if it is never committed.

## 2. Update ("co-writer update", when the author asks)

`bash <skill>/scripts/update.sh` harvests, then digests whatever the last
update has not seen. Nothing runs on a schedule. The two halves:

### Harvest

`cowriter.py harvest` rebuilds `~/.co-writer/pairs.jsonl` (and the readable
`pairs.md`) for every paper in `~/.co-writer/papers.json`. A paper is
registered the first time something is logged for it. It reads:

| source | what it gives |
|---|---|
| the store's log entries | deliveries with their slot and profile version; the author's Notes |
| the paper's git history, commit by commit | the file as it stood (Overleaf syncs land here) |
| snapshots of the working tree, at each `log` and each harvest | uncommitted states |
| Claude Code, `~/.claude/projects/*/*.jsonl` | Edit/Write/MultiEdit on the `.tex`, prose in Bash splices, Read results, the author's turns |
| Antigravity, `~/.gemini/antigravity/conversations/*.db` | `replace_file_content` / `write_to_file` edits (the new text and the text it replaced), `view_file` results, the author's turns |

A session is included if it mentions the paper's repository path; which
directory the agent ran in does not matter. For each delivered paragraph or
caption it finds the **accepted** version (the last version seen before an
agent next rewrote it) and, where it can, the author's **draft** that the
delivery rewrote, and records the author's turns in between as
**feedback**. Text an agent delivered is never counted as the author's. A
paragraph the author merged from two deliveries has the merged-in words
marked `agent_spans`. Paragraphs kept verbatim are recorded too (`kind:
kept`); they are evidence the delivery was right.

`cowriter.py status` prints the counts, the mean edit distance per profile
version (a later version is better if and only if the author edits less),
and any proposal awaiting a ruling.

### Digest

`cowriter.py packet` writes `~/.co-writer/packets/<stamp>/` when at least one
edited record has not been digested. The packet holds the records, the log
Notes since
the last proposal, and copies of the profile, the counterexamples and the
brief, [digest.md](digest.md). An agent confined to that directory follows
the brief and writes `proposal.md`: each record sorted into voice, content,
artifact or trim, the voice edits clustered, and each cluster made into one
candidate change with its evidence and a lean. `cowriter.py file PACKET`
moves the proposal to `~/.co-writer/proposals/` and marks its records
digested.

The digest never edits the profile. It proposes; the author rules.

Without `claude` on the machine (or with `CO_WRITER_DIGEST_CMD` unset for
another agent), do the digest in the session: `cowriter.py harvest`, then
`cowriter.py packet`, follow `digest.md` in the packet, then `cowriter.py
file PACKET`. After the update, tell the author how many edits were
digested and offer "co-writer review".

## 3. Review (the author, when a proposal is pending)

co-writer mentions a pending proposal once, at the end of any session in
which it is used (`cowriter.py status --brief` prints a line only when there
is one). When the author says "co-writer review":

1. Open the oldest pending proposal. Give the author the candidates one at a
   time: the change, the evidence as the few changed words, your lean. One
   question per candidate: **adopt**, **test**, **hold** or **reject**.
2. **Adopt**: apply the change to `voice-profile.md` (or
   `counterexamples.md`), exactly as ruled.
3. **Test**: run co-writer in a fresh context (a subagent that has not seen
   this conversation) on the listed records' `draft` (or `delivered`, where
   no draft) with the amended profile and nothing the author said, and
   compare with their `accepted` text: the change passes if the new output
   makes the author's edit unprompted, meaning its similarity to `accepted`
   rises for most of the listed records. Passing adopts. Failing rejects.
4. **Reject**, or a failed test: record the candidate in the profile's
   Rejected section with the reason (the author's words, or what the test
   showed), so it is not proposed again.
5. **Hold**: nothing changes; the next digest sees it again, and
   recurrence is evidence.
6. Under the proposal's `## Rulings`, one line per candidate with the
   ruling, then change its header to `status: ruled`. Bump the profile's
   Version line and add one changelog entry for the whole review.

A proposal is ruled all at once or not at all; a half-reviewed proposal stays
pending.

## 4. Eval (at each profile version)

The protocol in `eval/README.md`: six fixed inputs, rewritten and edited by
the author, harvested like any paper.

## 5. New paper

Run `scripts/extract_prose.py` on its `.tex`, re-run
[extraction.md](extraction.md) over the full set, update
[extraction-report.md](extraction-report.md), revise the profile. Rules whose
evidence disappears are demoted, not kept.

The interview ([interview.md](interview.md)) runs once; its Part 1 is re-run
whenever the profile changes materially. The profile has a 400-line cap —
past it, compress; do not append.
