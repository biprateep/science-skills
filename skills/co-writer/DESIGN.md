# co-writer — design brief

Status: **pre-implementation, four decisions taken.** This is the output of a 13-agent
research and design pass (6 scouts, 3 competing architectures, 3 judges, 1 completeness
critic), amended by the decisions in §0. Nothing in `skills/co-writer/` is built yet.

Every number below was measured by an agent that ran the command, not recalled.

---

## 0. Decisions taken (2026-08-05)

1. **The corpus is user-curated. Nothing is harvested from disk.** He supplies PDFs of
   papers and applications he wrote, and certifies provenance himself. All contamination
   triage — date cutoffs, structural fingerprints, authorship denylists, deny-read paths,
   arXiv version pinning — is **deleted from the design**. The remaining residual risk is
   *joint* voice (co-authors, senior editors), not AI voice, and it is handled by asking
   him to mark each document rather than by inference.
2. **AI-use disclosure and provenance classification are out of scope.** No provenance
   classifier, no disclosure generator, no venue-policy table, no refusal condition tied to
   disclosure. co-writer restyles; what gets declared is his call, made outside the skill.
3. **Target register, corpus as rhythm only.** The corpus teaches *rhythm and mechanics*
   only. Register, stance, framing and self-positioning come from an interview, not from
   measurement. This splits the voice profile into two layers (§4.2).
4. **Non-native constructions are preserved; conflicts are flagged.** Any de-LLM marker
   that would fire on a construction attested in his corpus is demoted and logged to a
   running conflict register for his review.

What this does *not* change: every finding in §1.2–1.5 and §2 that concerns tools, APIs,
the literature, or methodology. Those were measured independently of his corpus and stand.
Every *number* describing his voice is void until recomputed from the curated set.

---

## 1. What the evidence changed about the plan

Five things came back that alter the five features as originally stated.

### 1.1 `applications/WRITING_STYLE.md` is contaminated and must be quarantined

It is the right *shape* — mechanisms, not adjectives — and it should be the template
for what a voice profile looks like. But it was derived from `Arizona_AstronomyxML_2025`
plus the two 2024 Schmidt statements, and its own §11 records that those documents carry
an APS AI-use disclosure. Then `rising_stars_2026/research_statement.tex` was generated
*from* it. The chain is:

> possibly-LLM document → style guide → new LLM document

with confidence rising at each step and no evidence added at any step.

Four of its headline claims are falsified by measurement against his genuine corpus:

| WRITING_STYLE.md claims | Measured in his pre-2025 documents |
|---|---|
| unspaced em-dashes are a signature | **0 em-dashes** in all six 2022–2024 documents; 0.30/1000 in his papers. AI corpus: 2.86/1000; Arizona: 5; rising_stars: 8 |
| "typical 28–38 words" per sentence | medians 18–25.5. The 28–38 band matches the **known-LLM** document (mean 31.8) |
| "never `I will develop` — always `my group will`" | `my group will` occurs **0 times** in all seven genuine documents; 6× in Arizona alone |
| `This will…` payoff closer + trailing tricolon | 5× in Arizona, **0×** in the entire 2023 corpus |

The direction of the error is the finding: a summarizer reading one contaminated
document did not merely fail to find his voice — it wrote down the assistant's voice
and labelled it his.

Under Decision 0.1 the file is **not a source** and the documents behind it are not in the
corpus. It survives here as the cautionary case, and as the template for what a voice
profile should look like structurally. If the recomputation against the curated set
reproduces this table, the four rules go to `rejected.md` with their counts (§3).

### 1.2 A lexical tic list is worse than nothing — measured both ways

- **False positives on his authentic voice.** His genuine, pre-ChatGPT 2021 capsule-network
  paper contains `leverage` ×2, `state-of-the-art` ×4, `crucial`, `robust` ×2, and the
  antithesis construction *"not just because its stellar population is intrinsically red
  but because it is a dusty edge-on spiral."* `leverage` also appears in his own unedited
  2026 typing.
- **Near-zero recall on steered output.** `rising_stars_2026`, which carries an explicit
  AI-assistance disclosure, scores **exactly 0.00 per 1000 words** on every tic family
  tested — *lower than his own genuine writing* — because it was steered by
  WRITING_STYLE.md to avoid those words.

This is structurally the same defect the repo already shipped once: co-scientist v0.2's
step-skip detector used `grep -ic "a|b|c"` without `-E`, so the `|` was a literal
character and the check **never fired** — and printed "No step-skipping language
detected" on every run. A check that never fires is indistinguishable in the output from
a check that always passes.

### 1.3 Most distributional markers also fail to separate on *his* corpus

The MVP designer tested the marker scout's recommendations on 7 known-human + 2
known-LLM documents of his:

| Marker | Human range | LLM range | Verdict |
|---|---|---|---|
| sentence-length CV | 0.410–0.673 | 0.475–0.717 | full overlap |
| tricolon /1k | 0.00–2.86 | 2.08–4.76 | overlap — his genuine 2024 statement (2.86) scores *above* the LLM one (2.10) |
| gzip prefix-compression slope | −6.06 to −1.40 | −4.88 to −3.83 | not separating; confounded by length |
| significance-claim rate | 1.25–2.15/1k | **0.00** | *inverted* |
| specificity density | 1.78–10.60/100w | 3.21–7.90 | LLM sits entirely inside the human range |
| em-dash /1k | 0.00 (6/6 docs) | 4.86–13.10 | **clean separation** — but one system-prompt line drives Claude to 0.19, so it cannot be an output gate |

A judge independently re-ran the gzip route on longer documents and found the known-LLM
document sitting *between* two human ones (−5.26 vs −3.84 and −5.82).

**Consequence: co-writer must steer generation, not score output.** There is no
defensible "humanness score" to emit. Emitting one is the machine-epsilon tell again.

### 1.4 The citation gate, as everyone wrote it, does not run

- `resolve_citation('dey2022')` → `{"resolved": false, "reason": "unrecognized identifier"}`.
  It takes arXiv ids / DOIs / OpenAlex ids, **not bibkeys**. All three designs gated on
  passing it a bibkey; taken literally, that blocks every document ever written. The
  missing step — parse the `.bib`, extract the `doi`/`eprint` field, resolve *that* — was
  specified by none of them.
- **13 of 43 entries (30%) in his real `n2n/report.bib` carry no DOI, eprint, or
  archiveprefix at all.** The unresolvable set includes `vaheb2026astrosure`,
  `martincalle2026raman`, `luhn2026exposure` — 2026 papers, the highest-fabrication-risk
  class in the document. The check is strongest on famous papers nobody hallucinates and
  absent on recent ones everybody does.
- **Two citation checks are measurably vacuous.** ADS
  `link_gateway/<bibcode>/ABSTRACT` returned **HTTP 302 for the fabricated bibcode
  `2023ApJ...999..999X`** — it is a pure URL rewrite with no lookup. (`/PUB_HTML` 404s on
  the same input and is the real test.) And Crossref `query.bibliographic` on the nonsense
  string *"Zorbulon quasi-tachyonic redshift manifold of Blergh"* returned **177,126
  results**. "The API returned something" is never a valid pass condition; normalized title
  similarity is (measured 1.000 real / 0.253 real-DOI-wrong-title / ~0.1 nonsense).
- **"It compiles" is near-vacuous.** A planted test document with an undefined `\ref`, an
  undefined `\cite`, a missing `.bib` entry and a 185pt overfull hbox **compiled to a valid
  PDF**. co-scientist's `compile_report` filters only lines starting with `!`, so all four
  were invisible. The gate must be on *warning-class set difference* against a pre-edit
  baseline, not on exit status.

### 1.5 The preservation contract, as asked for, protects errors

Feature 1 guarantees the source's content survived. Applied to a co-scientist report
that guarantee covers a fabricated citation, an overclaimed result, or a number from an
unverified checkpoint — and *promoting it to MUST makes it harder to drop*, then puts it
in his voice under his name.

co-scientist's manifest already records which checkpoints are `verified`. Missing rule:
**an atom traceable to an unverified checkpoint may not be tiered MUST**, and must
surface at the review gate as "unverified claim about to enter a submission."

---

## 2. What is actually learnable

### Papers — partially, and honestly labelled

Three signatures survived a genre-matched control test (his 3 pre-LLM first-author papers
vs 5 same-topic, same-era papers by other first authors):

- **Sentence length** — mean 24.6 vs 20.7, Mann-Whitney p = 9.1e-25, bootstrap CI on the
  difference [3.10, 4.75]. Per-document GOLD [24.04, 25.17] is disjoint from CTRL
  [19.13, 23.09].
- **Missing short-sentence tail** — 8.6% under 12 words vs 14.6%, non-overlapping Wilson CIs.
- **Display-equation density** — [1.14, 3.14] per 1000 vs [0.00, 0.68], disjoint.
- (Suggestive) **comma budget** — his three papers cluster in a 1.8-wide band [35.3, 37.1].

**The single most useful result is not about him.** Control papers and LLM text are
statistically *indistinguishable* on sentence length (p = 0.79, rank-biserial −0.010),
while he differs from both. LLM prose does not regress toward "human writing" — it
regresses toward **the generic mean of the genre**, and he is an outlier from that mean.
The achievable target is therefore *"restore the outlier rhythm"*, which is measurable.

### Two honest negatives

- **Burrows's Delta fails to identify him.** Over the 120 most frequent function words,
  his 2019 paper's nearest neighbour is Levy 2019 and his 2021 paper's is Pasquet 2018 —
  both cross-group. Only 1 of his 3 papers picks another of his own. Standard authorship
  attribution does not find a "Dey" signal in this corpus.
- **The in-sample fingerprint test looked great and was circular.** Features selected
  because they separated gave GOLD [3.31, 3.70, 4.63] vs CTRL [−0.52, −0.39, 0.91]. The
  honest leave-one-out version *fails*: Pasquet 2018 scores 3.62, above held-out Dey 2019
  at 1.41. Going from 3 controls to 5 collapsed the separating metrics from 6 to 3. The
  agent caught this in its own analysis — it is exactly the pattern from the n2n post-mortem.

**Any voice-match score must be validated leave-one-out against genre-matched controls,
or it manufactures confidence.**

### The literature ceiling, stated up front

On the one benchmark that measures authorship fingerprint rather than instruction-following,
**no inference-time method reaches the human cross-author floor** (LUAR 0.484–0.508 vs a
floor of 0.626) — personalized output is more distant from the target author than random
humans are from each other. Separately, LLM-judge trait-match rated a style-profile method
*above the real human author* (0.542 vs the author's own) while authorship verification
showed no advantage. LUAR, LLM-judge and function-word cosine correlated at |r| < 0.07 on
the same outputs: three green lights are three different constructs, not three confirmations.

So the honest deliverable is **"a draft close enough that his edit pass is short,"** plus
an auditable record of what was preserved — not "indistinguishable from him."

---

## 3. The corpus — user-curated

**Decision 0.1 replaces everything the scouts built here.** He supplies the documents and
certifies them. The skill's job is to record what he attested, not to second-guess it.

### What the skill needs supplied, per document

| Field | Why |
|---|---|
| the file (PDF fine, **`.tex` better** where it exists) | markup-aware stripping separates prose from equations, citations and floats far more cleanly than `pdftotext` |
| doc type | `paper` / `research_statement` / `cover_letter` / `proposal` / `talk_abstract` / other |
| **how much of the prose is his** | `all mine` / `mine, lightly edited by co-authors` / `substantially co-written` |
| approximate date | only to order the profile, never to filter |

The third field is the one that still matters. His first-author papers pass through senior
co-authors — `2112.03939` gained 845 words between v1 and publication — so a document that
is genuinely his by attestation can still be a *joint* voice sample. That is his call to
make per document, not the skill's to infer.

### Sizes the statistics actually need

- **Per document:** ≥ ~500 words / ~25 sentences. Below that, rate markers are
  Poisson-dominated and the profile builder must **abstain**, not emit a confident number.
- **Per doc type:** ideally ≥ 5 independent documents. Distributional tests on 2–3 give
  effect sizes that shrink as more data arrives — the pilot watched separating metrics
  collapse from 6 to 3 when controls went from 3 to 5.
- **Deduplicate before counting.** Retargets of one statement are one document's worth of
  signal however many files they span. Report unique-word count, not file count.

### Still needed, and not replaceable by curation

**Genre-matched controls** — papers and statements by *other* people in the same subfield
and era. Without them there is no way to tell "his voice" from "how astronomers write."
This is the single mechanism that killed four of WRITING_STYLE.md's rules, and the pilot's
sharpest result (LLM prose ≈ generic genre prose at p = 0.79 while he differs from both)
is only computable against controls. These need no curation and no provenance — public
arXiv sources by other first authors are fine.

### The rules list he supplies

Treat each supplied rule as a **candidate**, and adjudicate it into one of four buckets:

| Verdict | Meaning |
|---|---|
| **adopt (measured)** | attested in the curated corpus with counts; goes in Layer 1 |
| **adopt (register)** | not measurable, but he asserts it as intent; goes in Layer 2 with an `attested-by: user` provenance stamp |
| **advisory** | plausible, weak or conflicting corpus support; reported, never blocking |
| **reject (with evidence)** | contradicted by the corpus; recorded in a `rejected.md` with the counts that killed it and the date |

Rejections are kept, not deleted — a rule that comes back needs to beat the evidence that
killed it. `rejected.md` is also where WRITING_STYLE.md's four falsified rules go if the
recomputation reproduces §1.1 against the curated set.

## 4. Recommended architecture

Judges split: **workflow** won voice-fidelity (7.5) and verification (8); **MVP** won
maintainability (8) decisively — "science-skills is 17 commits, one maintainer, two
skills. co-scientist earned its 621-line server over five releases; co-writer has to earn
its first."

**Take MVP's skeleton, workflow's joints, rigor's spine.**

### 4.1 Skeleton — nine files, no second MCP server

```
skills/co-writer/
├── SKILL.md
├── references/
│   ├── protocols/
│   │   ├── preservation_contract.md   # F1: atom taxonomy, tiering, sealed readback
│   │   ├── voice_profile.md           # F3 (ONE-TIME): derivation + circularity guard
│   │   ├── de_llmification.md         # F2: generation-side steering; the no-score rule
│   │   ├── latex_mechanics.md         # F4: compile-delta, .bib→identifier, limits
│   │   └── corpus_admission.md        # ONE-TIME: buckets, denylist, deny-read paths
│   └── doctypes/{paper,research_statement,cover_letter,proposal}.md
├── scripts/contract.py                # the one new executable
├── scripts/build_corpus.sh            # ONE-TIME
└── tests/verify_co_writer.sh          # with committed failing fixtures
```

Private, never in the repo:

```
~/.co-writer/
├── corpus/{papers,applications,raw}/ + MANIFEST.json
├── voice/profile_<doctype>.md
├── voice/pairs/<id>.md
└── voice/PROVENANCE.json     # corpus commit, drafting model id, derivation date, version
```

Growth path is real, not aspirational: when contract enforcement proves load-bearing, add
`contract_check` **as a tool inside co-scientist's existing server** — its `TOOLS` registry
is a flat dict; one function, one entry, zero new infrastructure. No second venv, no
spacy/sentence-transformers dependency (both verified **absent** from his python3).

**Fallback that no design wrote:** co-scientist's `mcp/.venv` is gitignored and only exists
after `setup_mcp.sh` runs. co-writer must discover it, and fall back to direct
`<web-fetch>` on the arXiv/Crossref APIs when it is missing — not silently skip.

### 4.2 The voice profile — two layers, because the corpus only teaches one

**Decision 0.3.** The corpus is a rhythm instrument, not a register model.

**Layer 1 — rhythm and mechanics. Measured, by code, from the curated corpus.**
Sentence-length distribution (not just the mean — the histogram, the short-sentence share,
the long tail), paragraph shape, comma/semicolon/colon/em-dash rates per 1000 words,
display-vs-inline equation density, citation density, connective inventory, passive rate.
Every rule carries its supporting instances and counts; **a Layer-1 rule with zero corpus
support is rejected at build time.** This is the mechanism that killed four of
WRITING_STYLE.md's claims and it is the only defence against a profile that drifts back
toward the model's own voice.

**Layer 2 — register, stance and framing. Interviewed, not measured.**
Pronoun grammar (`I` vs `my group will` vs `we`), how strongly he claims a result, how he
positions himself against prior work, seniority signals, audience (astronomy vs statistics),
what he will and will not say about himself. `my group will` appears **0 times** in the
historical corpus, so measurement cannot supply this and must not be asked to. Layer 2
rules carry `attested-by: user` instead of counts, and the build-time corpus-support
requirement **does not apply to them** — that constraint is Layer-1 only.

The interview is short, run once per doc type, and its answers are stored with a date. When
the register shifts again — the next career step, a new field — Layer 2 is re-interviewed
and Layer 1 is left alone.

**Why the split matters mechanically:** it prevents the single most likely failure, which
is a measured statistic being used to justify a register claim it cannot support. The
Arizona statement is exactly that error running in the other direction — a register
document treated as a measurement.

### 4.2a Non-native constructions — the conflict register

**Decision 0.4.** Preserve by default; flag on conflict.

Concretely: when a de-LLM marker would fire on a construction that is **attested in his
Layer-1 corpus**, the marker is demoted to advisory for that construction and an entry is
appended to `~/.co-writer/voice/conflicts.md` — the construction, the marker that objected,
the corpus count, and an example. He reviews the register when he chooses; each entry
resolves to *keep* (marker permanently suppressed for that pattern) or *normalize* (marker
promoted back). Nothing is silently rewritten either way.

This is the concrete answer to the 61.3% non-native false-positive problem: the corpus, not
the marker list, is the authority on what counts as his.

### 4.3 Modes — journey-named, because the description field is the trigger

| Mode | Trigger | Runs |
|---|---|---|
| **Touch-up** | a paragraph pasted inline | retrieve exemplars, rewrite, return with a two-line rationale. No files, no gates |
| **Restyle** | a short complete document, no hard limit | contract auto-extracted and ratified in one line, single pass, full check battery, unified diff |
| **Fit** | **a hard page/word limit is in play** | budget allocation is the primary design act; compression exemplars from the CCAPP→KIPAC→IAS triple; `budget_check` compiles and counts *real* pages, never estimates |
| **Distill** | a long agent artifact (the 45k-word co-scientist report) | section-by-section with re-anchoring, cross-section drift check, cutting-room floor, run manifest, resumable |

Gate on the **kind of artifact and whether it carries external constraints** — never on a
guessed word count. (co-scientist v0.2's "delegate anything >500 lines" was deleted in v0.3
as unknowable.)

There is no auto mode that rewrites a long document without the outline gate. **The
45k→8k selection decision is his.**

### 4.4 The four checks that are actually real

Ordered by how much they carry.

**(a) Sealed readback — the content check that the rewriter cannot satisfy.**
Generate comprehension questions *from the source*, **seal them before the rewrite
exists**, then have an agent that never sees the source answer them from the rewrite
alone. Calibrate against the **source's own readback score as the ceiling**, not against
100%. This is the only proposed check whose questions cannot be influenced by the text
being graded, and the only one that establishes what a passing score means.
*It encodes the n2n lesson directly: preserving tokens is the MSE; whether a reader
reaches the same conclusions is the science metric.*

**(b) Modality ledger.** Every claim carries an ordinal in
`{negated, speculative, hedged, suggested, asserted}` and the rewrite must satisfy
`modality(rewrite) ≤ modality(source)` — never strengthened. *"We cannot rule out X"* →
*"we show X"* is the exact silent-damage mode of the MSE post-mortem, and it survives
paraphrase in a way string matching does not.

**(c) Citation-set preservation, which needs no resolution at all.**
`keys_in_output − keys_in_source ≠ ∅` is a fabrication **regardless of whether it
resolves** — and it is robust to the 30% of his bib with no identifier. Pair with
claim–citation *pairing*: no citation may attach to a claim it did not attach to in the
source. Then, separately, the resolution chain: parse `.bib` → extract `doi`/`eprint`/
`bibcode` → resolve → **compare normalized title similarity**, with ADS `link_gateway/
PUB_HTML` (not `/ABSTRACT`) as the no-token fallback and an explicit evidence tier in the
output.

**(d) LaTeX warning-class set difference.** Compile before and after; fail on any *new
warning class* — undefined reference, undefined citation, multiply-defined label, missing
`.bib` entry from the `.blg`. Not on exit status, which is meaningless.

Plus one the judges found missing from all three designs, trivial and genuinely
falsifiable: **exemplar content-leak.** Flag any 8-gram in the output that appears in the
retrieved exemplars but is absent from the source. With CCAPP↔Buckeye containment at
0.982, the research-statement exemplar pool is effectively one document's paragraphs
saturated with photo-z/DESI/Cal-PIT framings — retrieve those into a 2026 faculty
statement and the model imports content the source never asked for. Every design enforced
that *source* content survived; none enforced that *exemplar* content did not intrude.
(This is also the self-plagiarism guard, with a different threshold for papers, where
verbatim reuse from his published work is an iThenticate exposure, than for applications,
where recycling is legitimate.)

### 4.5 The kill-test registry — the spine

Every blocking check ships with an executable **kill test**: a mutation of known-good
input that the check *must* reject. A check whose kill test fails or is absent is
**automatically demoted to advisory** and structurally cannot gate the output.

This is the user's own post-mortem rule made executable and CI-verifiable instead of
remembered — and it is already the shape of `tests/verify_mcp.sh`, where **7 of 16
assertions expect a non-zero exit**: the gate is tested by proving it blocks, *then*
proving it unblocks.

Decisive co-writer fixtures:
- preservation: a rewrite with one numeric claim removed → exit 1; `0.847` → "about 0.85"
  → exit 1; **the identity rewrite (output == source) → exit 0** (a preservation checker
  that fails on identity is broken)
- voice: his **held-out real writing** → exit 0; a raw LLM draft on the same topic → exit 1
- the mutation set must be **regenerated adversarially per profile version**, or the kill
  tests become the thing that is taught to

### 4.6 The harvester — what keeps it alive in year two

`capture_edit`: after delivery, diff his accepted version against what co-writer produced
and file it as a new contrastive pair. **When edits cluster — the same operation applied
3+ times — surface a proposed voice-card amendment for approval.** This is the only
improvement path that costs him zero dedicated time, and aligned edit data (not knowledge
of his style) is the actual scarce resource.

It also yields the **only cross-version metric aligned with the goal**: normalized
token-level edit distance between what co-writer delivered and what he accepted, per
doctype, on a **fixed held-out set of ~5 sources re-run at every profile version**. v2
beats v1 iff he changes less. Every other proposed eval measures the classifier.

### 4.7 Hard rules

- **`<HARD-GATE>` no humanness score, voice-match score, or AI-detection probability is
  ever emitted.** §1.3 is why. Report the per-marker vector with reference percentiles,
  reference *n*, and abstentions — or report nothing.
- Style statistics are **diagnostics that flag outliers for a human**, never targets the
  rewrite optimizes. "Reduce mean sentence length 20%", "≤2 em-dashes per page",
  "burstiness above X" are all satisfiable by text that still reads unmistakably as LLM
  output — and co-scientist v0.2's "N steps ⇒ N equation blocks" was reverted in v0.3 for
  exactly this reason.
- **Abstain below ~500 words / ~25 sentences.** Rate markers on short text are
  Poisson-dominated.
- **Never `<web-fetch>`-free.** Derive voice rules from the corpus by code, never from
  the model's recollection of "how he writes."
- The corpus and profile are **read-only inputs**. Derived artifacts are regenerated from
  source by a script, never edited in place.
- Bypasses are allowed but **never silent** — hard word limits force real cuts, so
  `allow_content_loss=true` must return the explicit list of dropped contract items and
  surface it as "these 6 claims did not fit."
- **Voice rules must be interpolated verbatim into every rewriter prompt**, plus 2–4
  selected pairs matched to the doctype. A prompt saying "follow `voice_profile.md`"
  silently degrades — this is exactly what the co-scientist pedagogy commit fixed.
- **A rule with zero corpus support is rejected at build time.** Every voice rule carries
  its supporting instances and counts. This is the mechanism that kills all four falsified
  WRITING_STYLE.md rules.

### 4.8 The baseline arm nobody proposed

Before building any of this: paste three of his paragraphs into a prompt and say *"write
like this."* One hour. It determines whether the corpus/profile/calibration apparatus
earns its maintenance cost at all.

---

## 5. Integrity — out of scope, with two carve-outs

**Decision 0.2.** No provenance classifier, no disclosure generator, no venue-policy table.
What gets declared on a submission is his call, made outside the skill. The critic's finding
stands on the record — his standing APS wording (*"solely to polish, condense, and edit my
original ideas"*) is not accurate for a Distill run over a co-scientist report — but acting
on it is not co-writer's job.

Two things survive, because they are correctness issues rather than disclosure issues:

- **The contract must not protect errors.** co-scientist's manifest records which
  checkpoints are `verified`. An atom traceable to an unverified checkpoint may not be
  tiered MUST, and must surface at the review gate. Without this, Distill mode makes a
  fabricated citation *harder* to drop by promoting it to must-preserve.
- **Exemplar content-leak / text recycling.** Verbatim reuse from his published papers into
  a new manuscript is an iThenticate exposure at submission. The 8-gram leak check (§4.4)
  covers it, with a stricter threshold for papers than for applications, where recycling
  across his own statements is legitimate and measured at 0.982 containment.

Also unresolved and worth a later decision, not blocking: **student and co-author drafts.**
He is corresponding author on at least two student-first-author papers. "Make it sound like
Biprateep" applied to a student's draft erases the student. Until decided, co-writer should
simply decline to load a voice profile for any document he did not write himself.

## 6. Build order

0. **Baseline arm** (§4.8). One hour, before anything: paste three of his paragraphs into
   a prompt, say *"write like this"*, and see what the apparatus has to beat.
1. **Ingest the curated set** — `build_corpus.sh` reduces to: extract text (`.tex`-aware
   where source exists, else `pdftotext -layout`), strip letterhead and running heads,
   dedup, record the attested metadata from §3, write `MANIFEST.json`. No triage, no
   filtering, no inference. Deterministic and re-runnable.
2. **Fetch genre-matched controls** from public arXiv — other first authors, same subfield
   and era. Without these, step 3 cannot distinguish his voice from the genre's.
3. **Derive Layer 1 by measurement; interview for Layer 2.** Then adjudicate his supplied
   rules into adopt / adopt-register / advisory / reject-with-evidence (§3), and — if it is
   still of interest — diff the result against `WRITING_STYLE.md` to quantify how much
   assistant style had been mislabelled as his.
4. **`contract.py`** — extract | check | limits | residue — plus the kill-test fixtures.
   Ship the checks in §4.4 only.
5. **SKILL.md** with the four modes, the hard gates, and a `description:` field written
   against co-scientist's (see below).
6. `capture_edit` + `conflicts.md` + the fixed held-out eval set.

**The `description:` field is the entire trigger mechanism and no design drafted it.**
co-scientist already claims *"write this up as a scientific report"* and its Phase 10
assembles LaTeX. On *"turn this into a paper"* both match and which fires is luck. The
over-trigger surface is also enormous — "polish this", "rewrite this paragraph", "make
this sound like me" covers most writing requests. This needs deliberate drafting with an
explicit `NOT for…` clause, and probably a matching amendment to co-scientist's.

Shipping co-writer is a **MINOR** bump per `VERSIONING.md`. Frontmatter is exactly
`name` / `description` (`>-` block scalar) / `license: MIT` / `metadata.version: "0.1.0"` —
no `allowed-tools` (added v0.3, removed v0.4 as rejected by VS Code-style agents).

---

## 7. Remaining questions

Four of the original seven are answered in §0. What is left:

1. **Which registers in the next 12 months?** Referee reports, response-to-referee letters,
   recommendation letters, student-draft edits, talk abstracts. Rank them — the doc-type
   files in `references/doctypes/` are cheap to add and expensive to guess at. Note that the
   real axis is not *paper vs application* but (who is the reader) × (hard limit or not) ×
   (LaTeX/citations or not) × **who owns the words**, and it is the fourth that carries the
   integrity risk.
2. **Student and co-author drafts** — in scope later, or never? (§5)
3. **What makes v2 better than v1?** Proposal: normalized token-level edit distance between
   what co-writer delivers and what he accepts, per doc type, on a **fixed** five-source set
   re-run at every profile version. v2 wins iff he changes less. Every other candidate
   metric measures the classifier rather than the product. If that is not the criterion,
   it needs naming before the first profile is built, not after.
4. **Genre-matched controls** — he curates his own documents, but the controls (other
   people's papers and statements, same subfield and era) are not his to supply and are not
   optional. Confirm it is fine to pull those from public arXiv.
