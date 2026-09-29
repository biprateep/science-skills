#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
#
# co-writer's update, run when the author asks for it ("co-writer update"):
# harvest the logs, the paper's git history and both agents' transcripts;
# if there are edits no digest has seen, write a packet, have an agent
# digest it into a proposal, and file the proposal for the author to rule on
# in "co-writer review". The profile is never changed here.
#
#   update.sh
#
# The digest agent is a headless Claude Code run confined to the packet
# directory (Read/Write/Glob/Grep only). Set CO_WRITER_DIGEST_CMD to use
# another agent: it is run with the packet directory as its working
# directory and the prompt as its one argument, and must leave proposal.md
# there. A copy of the output goes to $CO_WRITER_HOME/update.log.

set -euo pipefail

SKILL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STORE="${CO_WRITER_HOME:-$HOME/.co-writer}"
COWRITER=(python3 "$SKILL/scripts/cowriter.py")
mkdir -p "$STORE"
exec > >(tee -a "$STORE/update.log") 2>&1
echo "== $(date -Iseconds) co-writer update"

"${COWRITER[@]}" harvest

set +e
packet="$("${COWRITER[@]}" packet)"
status=$?
set -e
if [[ $status -eq 3 ]]; then
  echo "$packet"
  exit 0
fi
echo "packet: $packet"

prompt="You are running the co-writer digest. Read digest.md in this \
directory and follow it exactly: read pairs.jsonl, notes.md, \
voice-profile.md, counterexamples.md and any extra-*.md here, and write \
proposal.md here. Write no other file."

cd "$packet"
if [[ -n "${CO_WRITER_DIGEST_CMD:-}" ]]; then
  $CO_WRITER_DIGEST_CMD "$prompt"
elif command -v claude >/dev/null; then
  claude -p "$prompt" \
    --allowedTools "Read,Write,Glob,Grep" \
    --permission-mode acceptEdits \
    --output-format text >digest.out
else
  echo "no digest agent (install claude or set CO_WRITER_DIGEST_CMD);" \
    "packet left at $packet: digest it in a session with references/digest.md"
  exit 0
fi

"${COWRITER[@]}" file "$packet"
