# The session log

Read at the end of every rewrite: how the entry is written. Every agent writes
it the same way, with the same script, into the same place.

Every rewrite is logged, whichever agent performs it. The log is what the
improvement loop runs on; a rewrite that is not logged teaches nothing.

## Where and how

The log lives in the co-writer store, `~/.co-writer/papers/<paper>/log/`
(`$CO_WRITER_HOME` overrides the root), outside every repository. `<paper>`
is the name of the git repository holding the `.tex` file, so it is the same
whatever the agent's working directory. **Never write a log file by hand, and
never create a `.co-writer/` directory in a repository.** The script is the
only writer: it picks the path and the number, fills in the date, the
profile version and the paper, checks every field, and renders the one
format.

The input and output are the two files already written for `check_fixed.py`
(step 5 of the Process). Pass them as paths:

```bash
python3 <skill>/scripts/cowriter.py log \
  --file <path of the .tex the text belongs to> \
  --agent claude-code|antigravity|other \
  --slot abstract|intro-opener|gap|methods|definition|equation|results|interpretation|limitation|close|caption|appendix|mixed \
  --register journal|workshop \
  --cold-read yes|no|n/a \
  --input <scratch>/input.tex --output <scratch>/output.tex \
  [--note "<what the author said about it, verbatim>"] \
  [--unsure "<the passages you are least sure of, quoted>"]
```

- `--output` is the text exactly as delivered, never a summary of it. A
  whole-section rewrite logs the section; a rewrite made directly in the
  file logs the new text of what changed. The harvest pairs this text with
  what the author later keeps, and a summary pairs with nothing.
- `--input` is the input exactly as received (a path, `-` for stdin, or the
  text).
- Inline mode, with no file: `--paper <id>` in place of `--file`, using the
  id of the paper the text is for.
- One entry per delivery. When the author edits your output and asks for
  another pass, the second pass is a new entry.

At the end of any session in which co-writer was used, one session note:

```bash
python3 <skill>/scripts/cowriter.py session --file <the .tex> \
  --agent <agent> --register <register> \
  --asked "<what was asked>" --produced "<what was produced>" \
  --wrong "<what the author said was wrong, verbatim; or: nothing>"
```

## The format the script writes

For reference. Agents read it; they do not produce it.

```
---
id: 2026-09-29-03
date: 2026-09-29T14:05
agent: claude-code
profile_version: 0.4.0
paper: manuscript-fm4pz
file: main.tex
slot: results
register: workshop
cold_read: yes
---
## Input
<the input exactly as received>
## Output
<the output exactly as delivered>
## Note
<what the author said about the output in the same session, verbatim>
## Unsure
<the passages the writer is least sure of, quoted>
```

A session note has `slot: session` and a Note of three lines: `Asked:`,
`Produced:`, `Said was wrong:`.

## What reads it

`cowriter.py harvest` (run by "co-writer update"; see
[maintenance.md](maintenance.md)) reads these entries together with the
paper's git history and both agents' transcripts. It works without a log
entry too, but an entry with the exact output, the slot and the author's
Note is what makes a pair reliable.
