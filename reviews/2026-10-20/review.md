# Science Skills compatibility and citation-engine review

Reviewed on October 20, 2026. **The existing architecture is worth keeping, but the current test passes do not establish the integrity guarantees described by the skills. Fix false passes and evidence identity before adding more citation sources.**

This is a review, not an implementation change. No production skill, server, installer, or agent configuration was changed. The isolated installer probe used temporary configuration directories. Tests made public registry requests; no new model API calls or agent evaluation runs were made.

**Source snapshots**

| Repository | Reviewed commit | Local source |
|---|---|---|
| science-skills | `1f2f4716d1ac6984a9d709f6c01c4f9bf93cb4b0` | [/home/bid13/code/science-skills](/home/bid13/code/science-skills) |
| color4-alt/CiteCheck | `fae7888bf7c1ce92bbafad15faf61cf55b7e2bd7` | [/tmp/science-skills-review-CiteCheck](/tmp/science-skills-review-CiteCheck) |
| aliradid/citation-needed | `8777c08f5ba59fac0f99bc7cfe91a433cf59fea4` | [/tmp/science-skills-review-citation-needed](/tmp/science-skills-review-citation-needed) |

`git pull --ff-only` completed: already up to date. Both comparison repositories were downloaded from GitHub. Their local clones are temporary; the commit-pinned links below remain useful after `/tmp` is cleared.

**Compatibility: Claude Code, OpenAI Codex, Google Antigravity**

| Surface | Evidence and assessment |
|---|---|
| Shared skill format | All six frontmatter blocks parse, names match their folders, and descriptions are 593–992 characters. No agent-specific dependency is needed just to read them. |
| Claude Code | Installed CLI: `2.1.301`. Per-skill user folders and user-scoped stdio MCP registration match the documented mechanisms. Installer ownership bugs remain. No full Claude task was run. |
| Codex | Installed CLI: `0.162.1`. All six skills are exposed in this session. Both native MCP pings work. User skill symlinks and TOML stdio registration match official documentation. Co-writer logging and the batch-resolution schema are incomplete integrations. |
| Antigravity | Installed `agy`: `1.3.6`. Global MCP JSON path and `command`/`args` match current documentation. Skill discovery is **unverified**: the installer writes `skills.json` and removes owned links from the documented global skill directory. No full Antigravity task was run. |
| Direct MCP protocol | Initialization, tool listing, and ping passed for both servers: 12 cite-check tools and 9 co-scientist tools. Installed SDKs are MCP `2.2.0` and `2.0.0`, respectively. This confirms protocol operation, not every agent's schema handling. |
| Operating systems | Runtime testing was Linux only. Bash/venv paths are Unix-oriented; `fcntl` is mandatory for manifest locking, and the CAS timeout guard falls back to unguarded execution without `fork`. Native Windows compatibility should not be claimed without an explicit WSL requirement or portability work. |

Official documentation supports [Codex skill paths and symlinks](https://learn.chatgpt.com/docs/build-skills), [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli), [Claude skills](https://code.claude.com/docs/en/skills), [Claude MCP scopes](https://code.claude.com/docs/en/mcp), [Antigravity skill locations](https://antigravity.google/docs/skills), and [Antigravity MCP configuration](https://antigravity.google/docs/mcp). Antigravity's page documents `~/.gemini/config/skills/<skill-folder>/`; it does not establish the installer's `skills.json` mechanism. That discrepancy is a verification gap, not proof that no version supports the registry.

**Confirmed findings, ordered for remediation**

P1 means incorrect verification, scientific output, or an execution boundary that should be fixed first. P2 means a functional defect or reliability issue. The isolated reproductions and observed results are summarized with each finding below. Generated logs are intentionally untracked; implementation PRs retain executable regression tests instead.

1. **P1 — Evidence quotes can change meaning and still pass.** [_norm_quote / _locate_quote](/home/bid13/code/science-skills/skills/cite-check/mcp/server.py:2958) discard punctuation and accept sequence similarity ≥0.85. Removing “not” matched at `0.915`; changing `0.01` to `0.91` matched at `0.981`; changing `-100` to `+100` matched at `1.0`. `record_support` trusts these results. Normalize only known extraction artifacts while preserving numbers, signs, negation, units, and mathematical symbols. Fuzzy retrieval may suggest a passage; it must not certify a submitted quote. Return the exact source span and offsets.

2. **P1 — Changed claims and changed sources reuse old verdicts.** [_claim_hash](/home/bid13/code/science-skills/skills/cite-check/mcp/server.py:2952) lowercases and ASCII-normalizes scientific text. `$α=1$` and `$β=1$` have identical hashes; so do `$x=1$` and `$X=1$`. Separately, ledger entries have no source-content digest: ingesting contradictory replacement text still produced `audit.ok=true` with the old `SUPPORTS`. Preserve Unicode and mathematical case, hash the claim and relevant context, and bind verdicts to source content, version, extraction version, and judge policy. Invalidate stale verdicts explicitly.

3. **P1 — Incomplete parsing can produce a clean audit.** [audit](/home/bid13/code/science-skills/skills/cite-check/mcp/server.py:3098) detects `\nocite{*}` but does not add the bibliography's keys to the verification set: a fabricated bibliography passed with zero existence checks and no warnings. [_gather_tex](/home/bid13/code/science-skills/skills/cite-check/mcp/server.py:2496) silently skips missing included files. [_parse_bib](/home/bid13/code/science-skills/skills/cite-check/mcp/server.py:1862) silently stops on an unterminated entry; `verify_bib` then returned `ok=true, n=0`. Track parse completeness and expected inputs, reject malformed entries and unreadable declared inputs, and verify every entry selected by `\nocite{*}`.

4. **P1 — The math verifier executes Python expressions.** [_check_one_step](/home/bid13/code/science-skills/skills/co-scientist/mcp/server.py:72) passes input directly to SymPy `parse_expr`. A harmless test expression created a marker file and was reported as verified. This matters when equations are supplied by papers, users, or model output to a server running outside the shell sandbox. Use an allowlisted expression grammar and explicit mathematical constructors, plus a restricted worker process. Merely catching exceptions or setting `evaluate=False` does not make evaluation safe.

5. **P1 — Report success ignores LaTeX errors and citation state.** [compile_report](/home/bid13/code/science-skills/skills/co-scientist/mcp/server.py:415) returned `success=true` for a report containing an undefined command and an unaudited citation; `latex_errors` even contained the error. It ignores process return codes and uses PDF existence as success. It also does not call cite-check or validate a fresh audit result. [validate_figures](/home/bid13/code/science-skills/skills/co-scientist/mcp/server.py:388) missed a nonexistent figure in an included section. Require successful tool exits, resolved references, recursive figure checks, and a citation audit bound to the current inputs. Bibliography discovery should follow declarations, not assume `<report-name>.bib`.

6. **P2 — Invalid verification settings can pass false mathematics.** [verify_derivation](/home/bid13/code/science-skills/skills/co-scientist/mcp/server.py:162) accepted `steps=[{"cls":"N","lhs":"x","rhs":"0"}], samples=0` and returned verified. An empty step list also returned verified. Validate nonempty work, positive finite tolerances, positive sample counts and timeouts, and usable domains. Sampling must respect integer/real/sign assumptions. The worker's [unbounded `q.get()`](/home/bid13/code/science-skills/skills/co-scientist/mcp/server.py:158) also needs a bounded wait and child exit-code handling.

7. **P2 — Registry outages become “paper not found.”** [_crossref_work](/home/bid13/code/science-skills/skills/cite-check/mcp/server.py:756), DataCite, and arXiv discard unsuccessful HTTP status information. With both DOI registries mocked to HTTP 503, `verify_bib` reported `NOT_FOUND` and “DOI is not registered,” not a lookup failure. Preserve typed outcomes: found, definitive absence, rate-limited, unavailable, malformed response. Only definitive absence should justify removing a reference.

8. **P2 — Concurrent evidence writes lose successful results.** [record_support](/home/bid13/code/science-skills/skills/cite-check/mcp/server.py:3036) performs an unlocked read-modify-write; [_write_project](/home/bid13/code/science-skills/skills/cite-check/mcp/server.py:2937) truncates files directly. Two synchronized calls both returned `recorded=true`, but only one entry survived. The probe serialized the final writes, so this demonstrates a lost update independently of file corruption. Use a per-project lock across the transaction and atomic replacement, or SQLite transactions. Apply the same discipline to `bib_add` and shared caches.

9. **P2 — A single bibliography batch can create duplicate keys.** [bib_add](/home/bid13/code/science-skills/skills/cite-check/mcp/server.py:2195) checks requested keys against the original parsed file, not against additions in the same call. Two different records requesting the new key `same` both returned `added`, with `ok=true`. Track pending keys and identities, validate the entire transaction, and make duplicate-key detection part of parsing/audit.

10. **P2 — Cache filenames can alias different works; versioned support is not pinned.** [_slug](/home/bid13/code/science-skills/skills/cite-check/mcp/server.py:627) maps both `doi:10.1234/a/b` and `doi:10.1234/a_b` to the same filename, and truncates long identifiers. Hash the full canonical identifier for cache keys. [_github_text](/home/bid13/code/science-skills/skills/cite-check/mcp/server.py:2792) requests the default-branch README, while citation metadata can name an older tag; CFF fetching likewise uses HEAD. Fetch text and CFF at the cited commit, preserve arXiv versions separately from work identity, and include version/content hashes in evidence identity.

11. **P2 — The MCP schema does not advertise batch resolution.** [resolve_citation](/home/bid13/code/science-skills/skills/cite-check/mcp/server.py:1525) has no argument annotation. The installed MCP SDK exposes `identifier` as a string, although the function and CLI accept lists. Direct protocol submission of an empty list succeeded, so this is an advertised-schema mismatch, not a server rejection. Agents or clients following the schema cannot reliably use the documented batch feature. Annotate `str | list[str]` and give nested tool inputs explicit models and validation.

12. **P2 — Installation does not preserve ownership consistently.** [Claude symlink creation](/home/bid13/code/science-skills/scripts/install.sh:134) replaced an unrelated `cite-check` symlink in an isolated test. Codex's collection symlink has the same unconditional replacement pattern. Both MCP setup scripts accept an existing name as “already registered” without validating the launch path; moving the clone leaves stale commands. Antigravity uninstall deletes by server name without checking ownership. Record and check ownership, distinguish refresh from conflict, and update only this installation's entries. Parse and serialize TOML rather than regex-editing tables or interpolating unescaped paths.

13. **P2 — Co-writer's mandatory logging is not fully Codex-compatible.** [AGENTS](/home/bid13/code/science-skills/skills/co-writer/scripts/cowriter.py:85) accepts only `claude-code`, `antigravity`, or `other`; `--agent codex` exits 2. Its transcript harvesters cover Claude and Antigravity only, and automatic digestion defaults to Claude. Add Codex as an explicit agent, document the `other` fallback until then, and distinguish portable explicit logging from optional transcript harvesting. Expose a native-agent/manual digestion route without assuming Claude is installed.

14. **P2 — Co-writer's preservation checker misses important changes.** [check_fixed.py](/home/bid13/code/science-skills/skills/co-writer/scripts/check_fixed.py:40) ignores biblatex commands such as `\parencite`. Changing its key passed. Plain-text `-100`→`+100` and `10 pc`→`10 kpc` also passed. The [math environment regex](/home/bid13/code/science-skills/skills/co-writer/scripts/check_fixed.py:74) fails to capture starred environments, allowing symbol-only changes inside them to escape the math comparison. Share citation parsing, capture starred environments correctly, and compare signed quantities with units. Keep the documented human/agent checks for meaning and citation attachment.

15. **P2 — Plot quantiles include data outside explicit bins.** [binned_quantiles](/home/bid13/code/science-skills/skills/plot-style/assets/plotstyle.py:704) clips every bin index into the allowed range. For `x=[-100,0.5,100], y=[-1000,10,1000], bins=[0,1]`, it reported quartiles `[-495,10,505]`; only the value 10 belongs in that bin. Mask underflow/overflow while including the rightmost edge deliberately. Also, [better_step](/home/bid13/code/science-skills/skills/plot-style/assets/plotstyle.py:588) consumes a generator twice through `zip(y,y)`, causing a dimension error despite accepting `Iterable`; materialize once.

16. **P2 — The static plot check certifies unrelated styles and explicit overrides.** [style detection](/home/bid13/code/science-skills/skills/plot-style/scripts/check_plot_style.py:224) treats any `plt.style.use(...)` as the house style. A `ggplot` script with a black data series, default-sized figure, and explicit 72-dpi output produced no findings. [savefig checking](/home/bid13/code/science-skills/skills/plot-style/scripts/check_plot_style.py:304) lets style presence excuse an explicitly wrong DPI. Recognize approved styles and helpers; explicit contradictory arguments must fail. Keep runtime `verify_style` as an independent check.

**Coverage and smaller improvements across all six skills**

| Skill | Assessment beyond the findings above |
|---|---|
| cite-check | Strong existing identifier comparison, registry exports, software records, batching, provenance, passage retrieval, and per-instance support design. Highest priority is strengthening the evidence contract and parser completeness. |
| co-scientist | Good separation of orchestration and component skills; atomic, locked manifest allocation is a pattern to reuse. “Verified” evidence is currently an arbitrary string of ten characters, not a machine-linked check result. Consider persisted verification receipts and explicit red-team status. |
| co-writer | Clear voice/preservation separation and a useful capture loop. Its mandatory global store needs a documented workspace override for sandboxed agents. Shared JSON/temp filenames and log allocation also need concurrency tests. |
| code-style | 53 tests passed; no new functional defect established in this review. Config and examples are coherent. Add version-matrix CI and classify heuristic warnings separately from deterministic errors; avoid making wholesale restyling a prerequisite for targeted server fixes. |
| jupytext | The supplied notebook round-trips correctly. Its minimal example fails plot-style's no-style check, and the long SKILL example uses arbitrary dimensions, colors, and 150 dpi. Use a non-plotting example or compose plot-style explicitly. Clarify the scope boundary between analysis notebooks and package/server/test modules. |
| plot-style | Runtime `use_style` + `verify_style` passed. Add regression tests for explicit bins, generators, constant/empty data, user-requested vector output, and explicit override detection. Tight-crop size drift is already documented; do not file it as a newly discovered bug. |

Additional cite-check improvements:

- **Explicit audit policy.** `PARTIAL`, `UNVERIFIABLE`, `PROBABLE`, and `FOUND` are intentionally warnings in the implementation; their presence is not a newly discovered bug. However, callers describe `ok=true` more strongly than that policy warrants. Return separate completeness, existence, provenance, and support results, plus named strict/advisory policies.
- **Provenance enforcement/reporting.** Missing provenance is collected in `unofficial_entries` but is not emitted as a warning in the human-readable report. The stale-source probe returned an unofficial entry with an empty warnings list. Show it, and decide explicitly whether strict mode must block it. A comment alone is not proof that an entry remains identical to its export; retain/export digests.
- **Reliable acquisition.** The PDF size cap is checked after `_http` has read the entire body. Stream with a byte cap; preserve extraction diagnostics and distinguish unreadable/partial text from full text. Permit an insufficient-evidence verdict even when a nominal full-text file exists.
- **Efficiency.** `_throttle` sleeps while holding one global host lock, so waiting for arXiv blocks unrelated registries. Use per-host scheduling, connection reuse, request coalescing, and bounded retries. Add cancellation and an overall operation budget; per-request timeouts are not a whole-job deadline.
- **Client deadlines.** Codex documents a default tool timeout of 60 seconds. Multi-step CAS work, PDF retrieval/extraction, and report compilation can exceed it. Configure a justified timeout or expose resumable jobs; don't rely on CLI smoke tests to establish long-call behavior.
- **Testing and packaging.** The only checked-in GitHub workflow is release creation, with no test job. Add offline regression CI, real MCP protocol/schema tests, installer fixtures, and separately scheduled live tests. Constrain tested dependency ranges; fresh `mcp>=1.2` installs currently have no upper compatibility bound. Reconcile SKILL and server versions or label their version domains explicitly.
- **Tool discovery.** Discover by capability/server rather than hard-coding hyphenated tool names. This Codex session exposes normalized namespaces `mcp__cite_check` and `mcp__co_scientist`. Deferred discovery is not exclusively a Claude concern.

**Comparison with the downloaded projects**

| Capability | Our cite-check | color4-alt/CiteCheck | aliradid/citation-needed | Decision |
|---|---|---|---|---|
| Scientific identity and official exports | DOI/arXiv/ADS/OpenAlex/INSPIRE/GitHub resolution; official export chain | Broad existence search, looser matching; no equivalent export gate | Generic web-source policy | Retain our engine |
| Citing-document inputs | LaTeX + BibTeX | LaTeX, inline bibliography, PDF | Prose drafts | Add adapters incrementally |
| Evidence granularity | Citation instance / sentence | Citation contexts and per-reference scores | Atomic factual claims with original spans | Add atomic subclaims without losing citation instances |
| Full-text evidence | Text acquisition, passage retrieval, quote checks | Mostly title/abstract/context; heuristic fallback | Agent searches/fetches pages | Retain acquisition; repair quote enforcement |
| Sources beyond ours | Existing astronomy/physics-focused set | Semantic Scholar, PubMed, dblp, generic search | General web | Add domain-specific adapters as needed, preserving our identity rules |
| Format checks | Limited compared with identity checks | Missing fields, entry types, venue/preprint/year checks | Structured report validator | Add advisory bibliography lint |
| Evaluation | CLI fixture checks, live checks | Parser/verifier/reporter unit tests | Planted errors, true controls, skipped claims, multi-agent runners | Adapt citation-needed's evaluation design first |
| Reporting | JSON + Markdown audit, ledger | Format/existence/relevance summary | Claim/evidence/fix ledger, annotated copy | Add specific fixes and coverage indicators |
| Packaging | Shared installer and two MCP servers | Python package and CLI | Agent manifests, plugin metadata, opt-in hooks | Prefer typed package + optional agent metadata |

**Useful ideas from CiteCheck**

The [parser](https://github.com/color4-alt/CiteCheck/blob/fae7888bf7c1ce92bbafad15faf61cf55b7e2bd7/src/citecheck/parser.py), [PDF adapter](https://github.com/color4-alt/CiteCheck/blob/fae7888bf7c1ce92bbafad15faf61cf55b7e2bd7/src/citecheck/pdf_parser.py), and [format checker](https://github.com/color4-alt/CiteCheck/blob/fae7888bf7c1ce92bbafad15faf61cf55b7e2bd7/src/citecheck/bibtex_parser.py) show useful input and linting categories. Its package separates models, parsing, verification, matching, and reporting; that separation would help maintain our 3,322-line server. PDF extraction should carry page/span locations and uncertainty, then feed the existing identity/evidence pipeline.

Do not copy the matching engine as a verification gate. Its [Crossref scoring](https://github.com/color4-alt/CiteCheck/blob/fae7888bf7c1ce92bbafad15faf61cf55b7e2bd7/src/citecheck/verifier.py) can accept an unrelated title on the year bonus, and several subsequent adapters trust the first hit. Its [semantic fallback](https://github.com/color4-alt/CiteCheck/blob/fae7888bf7c1ce92bbafad15faf61cf55b7e2bd7/src/citecheck/matcher.py) can award 0.9 for a title-word overlap and can substitute bibliography text for an abstract. It also contains biomedical-specific heuristic weights. These are retrieval hints, not evidence of support.

Other implementation cautions: PDF parsing deduplicates repeated citation markers, losing distinct claim instances; the report's summary map overwrites earlier semantic scores for the same reference; selecting a `.tex` file actually searches its parent directory for a main file. Adopt the capabilities, not those shortcuts.

**Useful ideas from citation-needed**

The [evaluation runner](https://github.com/aliradid/citation-needed/blob/8777c08f5ba59fac0f99bc7cfe91a433cf59fea4/scripts/run_evals.py) and fixtures are the best transferable component: measure planted-error recall, false alarms on true claims, omitted claims, and formatting validity across agent runners. Adapt this to scientific identity mismatches, altered quantities, negation, citation placement, changed source versions, retrieval failures, and concurrency. The project reports 15/16 planted errors caught for both Claude and Codex; those are upstream results, not measurements reproduced here.

Its [workflow](https://github.com/aliradid/citation-needed/blob/8777c08f5ba59fac0f99bc7cfe91a433cf59fea4/skills/citation-needed/SKILL.md) also offers useful atomic claims, explicit unchecked states, risk ordering, bounded searching, proposed corrections, and annotated text. Keep ordinary citation checking separate from an optional broader factual-claim audit; the latter includes uncited claims and has a larger scope.

Do not adopt its “Safe to publish” logic unchanged. The [validator](https://github.com/aliradid/citation-needed/blob/8777c08f5ba59fac0f99bc7cfe91a433cf59fea4/scripts/validate_report.py) can accept that verdict with only `UNVERIFIED` claims. It counts URLs and a “primary” label without proving source independence, retrieval, or entailment. The evaluation scorer does not count a missing true/skip row as a false alarm/triage violation; retain those metrics but add explicit coverage and omission rates. Our deterministic evidence gate should remain stronger than report-format validation.

Both downloaded projects contain MIT license files: [CiteCheck](https://github.com/color4-alt/CiteCheck/blob/fae7888bf7c1ce92bbafad15faf61cf55b7e2bd7/LICENSE), [citation-needed](https://github.com/aliradid/citation-needed/blob/8777c08f5ba59fac0f99bc7cfe91a433cf59fea4/LICENSE). Any copied portions should retain their notices and a record of the upstream commit. No third-party source was incorporated during this review.

**Recommended cite-check implementation sequence**

1. Add regression cases for these reproduced failures before changing behavior: quote polarity/numbers/signs; Unicode/case changes; stale sources; `\nocite{*}`; malformed/missing inputs; duplicate batch keys; outage classification; concurrent writes; cache-key collisions; MCP schema parity.
2. Define typed records for works, source snapshots, citation instances, atomic claims, evidence spans, judgments, and audit policy. Keep the MCP and CLI as thin wrappers around one engine.
3. Repair exact evidence matching, source/version binding, parse completeness, and transactional persistence. Default scientific verification to explicit incomplete/blocked outcomes rather than a misleading pass.
4. Make co-scientist compile against a current audit receipt; repair the unrelated compiler, CAS, installer, and co-writer defects as separate focused changes.
5. Adapt citation-needed's evaluation architecture for Claude, Codex, and Antigravity. Measure correctness, omissions, latency, registry calls, and cost. Use deterministic fixtures in CI and opt-in live-agent evaluations.
6. Add format lint, actionable correction reports, retraction/correction metadata, then PDF/inline-bibliography and optional prose adapters. Retraction detection is our additional recommendation, not a capability established in either comparison project. Add Semantic Scholar/PubMed/dblp only when their coverage improves actual workloads.

Acceptance should require that altered evidence and incomplete input cannot pass, concurrent calls cannot lose accepted results, source changes invalidate old judgments, and all three agents can discover and call the same typed interface.

**Validation and limits**

| Check | Result |
|---|---|
| cite-check offline suite | 42 passed |
| cite-check live suite, including its offline checks | 99 passed; includes ADS and GitHub |
| co-scientist CLI suite | 13 passed, including compilation |
| code-style pytest suite | 53 passed |
| CiteCheck upstream tests | 48 passed |
| citation-needed upstream tests | 37 passed |
| MCP initialize / list / ping | Both servers passed |
| Python syntax and undefined-name scan | 14 tracked Python files parsed; Ruff F821/F822/F823 passed |
| Shell syntax | All tracked shell scripts passed `bash -n` |
| Jupytext round-trip | Both notebook examples preserved cell sources |
| plot-style supplied example checker | Passed |
| plot-style runtime verification | Passed |
| jupytext example against plot-style | Failed: no style applied |
| Targeted adversarial probes | Confirmed the defects described above |

The 99 live checks include the 42 offline checks; do not add them together as independent tests. The co-scientist post-run validator was also invoked at the repository root, where no research-run artifacts exist; its expected missing-artifact diagnostics are not product test failures.

Logs are stored alongside this review. Reproductions involving mocked registry responses or synchronized concurrent reads are labeled in the text; they test deterministic failure paths rather than claiming those outages occurred live. Full user journeys in Claude/Antigravity, Windows/macOS execution, fresh dependency installs, and independent model-based accuracy benchmarking remain untested.
