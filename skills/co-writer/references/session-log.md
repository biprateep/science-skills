# The session log

Read at the end of every rewrite: the form of the entry that goes into `.co-writer/log/` in the paper's repository, and the session note that closes a session.

Every rewrite is logged, whichever agent performs it. The log is what the
improvement loop runs on; a rewrite that is not logged teaches nothing.

After delivering the text, append a file to `.co-writer/log/` **in the
repository that holds the paper** (create the directory if it is missing),
named `YYYY-MM-DD-NN.md` with `NN` the next free number that day:

```
---
id: 2026-09-12-03
date: 2026-09-12T14:05
agent: claude-code | antigravity | <other>
profile_version: <the Version line at the top of voice-profile.md>
slot: abstract | intro-opener | gap | methods | definition | equation | results | interpretation | limitation | close | caption
register: journal | workshop
cold_read: yes | no | n/a
file: <path of the .tex the output went into, relative to the repo root; omit if returned inline only>
---
## Input
<the input exactly as received>
## Output
<the output exactly as delivered>
## Note
<what the user said about the output in the same session, verbatim; omit the section if nothing>
## Unsure
<the passages the writer is least sure of, quoted; omit if none>
```

At the end of any session in which co-writer was used, append one more file,
`YYYY-MM-DD-session.md`, same frontmatter with `slot: session`, and three
lines under `## Note`: what was asked, what was produced, what the user said
was wrong. This makes the record independent of where each agent keeps its
chat.

The log is gitignored where the paper lives. Never write it into the skill's
own directory.
