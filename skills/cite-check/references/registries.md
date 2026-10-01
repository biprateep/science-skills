# Registries — what each one is good for, and how the toolbox uses it

Every lookup in `mcp/server.py` goes to one of these. The notes below were
measured, not assumed (2026-09), and they shape the tool's design: **no
registry's own ranking is trusted**, every candidate is re-scored locally on
title similarity, first-author surname and year, and BibTeX is taken only
from an export endpoint, never composed.

| Registry | Coverage | Lookup by | Search | BibTeX export | Full text / abstract | Auth |
|---|---|---|---|---|---|---|
| **NASA ADS** | astronomy, astrophysics, physics | bibcode, DOI, arXiv id | fielded (`first_author:`, `year:`, `title:`, `abs:`) — the best for astronomy | `/export/bibtex` (journal macros or abbreviations, author cut-off) | abstract | **token required** |
| **arXiv** | preprints, all fields | id (batched `id_list`, 50 per call) | `ti:`, `au:`, `submittedDate:` | `arxiv.org/bibtex/<id>` (`@misc`) | HTML (most papers since late 2023, many older) or PDF; abstract | none; 3 s between calls |
| **Crossref** | every DOI-registered journal/book/proceedings | DOI | `query.bibliographic` + `query.author` + date filter — **noisy** | `/works/<doi>/transform/application/x-bibtex` | abstract sometimes; publisher PDF links (mostly paywalled) | none; `mailto` for the polite pool |
| **DataCite** | datasets, software (Zenodo…) | DOI | — | content negotiation (`Accept: application/x-bibtex`) | description | none |
| **OpenAlex** | broad graph of works | W-id, DOI | `search=` + year filter | none (→ Crossref/DataCite via DOI) | abstract for many paywalled papers; open-access PDF URLs | none; `mailto` polite pool |
| **INSPIRE-HEP** | high-energy physics | arXiv id, DOI, recid | `t "…" and a <surname> and date …` | `?format=bibtex` (INSPIRE keys) | abstract | none |
| **GitHub** | public software repositories | `owner/repo` (URL, `github:`, `git@github.com:` forms) | repository name/description — **opt-in** (`registries=["github"]`) | none: the repository's software DOI → DataCite/ADS; else `@software` laid out from `CITATION.cff` or the GitHub record (below) | README + description + `CITATION.cff` abstract (basis `readme`) | none; 60 requests/hour, 5000 with a token |

Not used: **Semantic Scholar** (HTTP 429 without a key), **DBLP** (behind an
anti-bot challenge; unusable from scripts), **Google Scholar** (no API).

## Measured failure modes the tool defends against

- **Registry ranking is wrong often enough to matter.** Crossref and OpenAlex
  both rank a fraudulent republication (`10.65215/…`, 2025) of *Attention Is
  All You Need* above the real 2017 paper; Crossref ranks a conference summary
  above the real *Planck 2015 results. XIII* paper and never returns the A&A
  article in its top ten; OpenAlex stores that paper's title truncated to
  "Planck 2015 results". `search_citation` therefore queries every enabled
  registry, merges duplicates (same DOI / arXiv id / title+first-author), and
  ranks by its own score: 100×title similarity, +30 first-author match (−10
  none), +15/+8/−15 year exact/±1/off, +4 per extra registry that knows the
  work, small bonuses for a DOI and for citation count. `confidence: high`
  needs title similarity ≥ 0.90 plus an agreeing author or year.
- **"The API returned something" is never a pass.** Crossref returns 177 000
  results for a nonsense title. Existence is decided by comparing the entry's
  own title, first author and year with the record its identifier resolves
  to (`verify_bib`): similarity ≥ 0.90 → VERIFIED; 0.75–0.90 → PROBABLE only if
  the first author agrees, else MISMATCH; < 0.75 → MISMATCH. A real DOI on the
  wrong title is the classic fabricated entry and is a failure.
- **Years drift legitimately** between the arXiv version and the journal
  version, so ±2 years is tolerated; more is flagged.
- **Titles need normalisation before comparison**: HTML tags (`<i>Planck</i>`),
  entities, LaTeX braces and commands, accents and punctuation are stripped;
  Crossref's separate `subtitle` is joined to the title. Word-order shuffles
  are accepted through token containment, discounted by length disparity so a
  shorter title that merely sits inside a longer one does not score 1.0.
- **ADS `link_gateway/<bibcode>/ABSTRACT` returns 302 for a fabricated
  bibcode** — it is a URL rewrite, not a lookup. Bibcodes are only resolved
  through the ADS search API, which needs a token; without one, `verify_bib`
  falls back to the entry's DOI or arXiv id and reports a bibcode-only entry as
  unresolvable rather than "checked".
- **Crossref's BibTeX export is official but dirty**: HTML entities and tags in
  titles, line-wrapped values, `month=Sept` (not a BibTeX macro), and
  collaboration authors dropped (`author = { and Ade, …}`). `_sanitize_bibtex`
  repairs the encoding and puts the dropped first author back from the same
  registry's JSON record, then lays the entry out canonically. It never adds a
  field the registry did not supply.
- **arXiv DOIs** (`10.48550/arXiv.<id>`, minted by DataCite) are folded into the
  arXiv id so a paper never has two identities.

## GitHub repositories

A public repository is cited as software. `resolve_citation` reads, per
repository: the REST record (`/repos/owner/repo`, which follows renames),
`CITATION.cff` and `CITATION.bib` from the default branch
(`raw.githubusercontent.com`, outside the API quota), the README (rendered
HTML, so Markdown and reStructuredText read alike), and the owner's display
name when `CITATION.cff` lists no authors. About three API requests per
repository on a cold cache, cached like every other lookup.

What the record carries, and where it comes from:

| Field | Source | Notes |
|---|---|---|
| title, authors, year, version | `CITATION.cff` (`title`, `authors`, `date-released`, `version`), else repository name and owner | persons as `Family, Given`; entities braced |
| software DOI | `CITATION.cff` `doi` / `identifiers`, else a Zenodo DOI in the README **only if** DataCite says it is `Software` related to this repository | a README badge alone is not trusted — it may be a dataset or another project |
| `preferred_citation` | `CITATION.cff` `preferred-citation`, else the first entry of `CITATION.bib` | the paper the authors ask for; its DOI/arXiv id is resolved like any other |
| `readme_ids` | DOIs and arXiv ids the README links (badge image suffixes stripped) | hints only; `verify_bib` resolves them to recognise a paper filed under its repository's URL |
| `archived`, `fork` (+ `parent`), `moved_from`, `private` | REST record | a private repository is refused even with a token that can see it |

**Identity.** A repository's canonical id is always `github:owner/repo`
(lowercase), even when it has a software DOI: the DOI is a field. This keeps
the DataCite record of that DOI from overwriting the repository's cached
record, and makes `bib_add` treat the DOI and the repository as one work
(duplicate detection runs on `doi`, `arxiv`, `bibcode` and `github`).

**BibTeX** (`fetch_bibtex` / `bib_add`), in order: the usual registries
when the repository has a software DOI (ADS indexes Zenodo software records;
DataCite exports them), then `source=citation-cff` — `@software` laid out
field for field from `CITATION.cff` — then `source=github` — `@software`
from the REST record with the latest release tag as `version`, or, with no
release, the default branch's commit pinned in `note`. `version=` (or a
`/tree/<ref>`, `/releases/tag/<ref>`, `/commit/<sha>` URL) pins a specific
tag, branch or commit; it must exist (a `v` prefix is tolerated either way),
and when it is given only the GitHub source is used, because a concept DOI's
export names the latest version, not the one asked for. Provenance records
`version=` when pinned. Values are LaTeX-escaped (`_ % # $ &`); the URL is
not.

**Existence** (`verify_bib`). An entry gets the repository route when its
`url`, `howpublished` or `repository` field (or `note`, for software-like
entry types) is a GitHub repository URL and it has no DOI / arXiv id /
bibcode — or when its provenance comment says `bib_add` filed it as a
repository. The entry's title is compared with the repository's own
(`CITATION.cff` title, name, `owner/name`, description, name +
description):

| Outcome | Status |
|---|---|
| title similarity ≥ 0.90, or the title names the repository as a whole word run (`corner.py: Scatterplot matrices…`) | VERIFIED |
| the title is a paper the repository declares or its README links (resolved, similarity ≥ 0.90) | FOUND — replace with that paper's official entry |
| an article-type entry whose title search finds the paper (its `url` is its code) | FOUND (search) |
| title similarity 0.75–0.90 | PROBABLE |
| otherwise — a real repository on the wrong work | MISMATCH, even if a work with that title exists elsewhere |
| first author contradicts the declared authors and owner | PROBABLE |
| cited `version` (field or URL ref) is not a tag, branch or commit | PROBABLE |
| no public repository at the URL | NOT_FOUND |
| the lookup itself failed (rate limit, network) | UNRESOLVED — retry, never call it a fabrication |

Measured on real repositories (2026-10): `dfm/emcee` has no `CITATION.cff`
and links its paper from the README; `numpy/numpy` ships only
`CITATION.bib`; `astropy/astropy` and `matplotlib/matplotlib` declare a
preferred paper in `CITATION.cff`, and Astropy a Zenodo concept DOI whose
DataCite export is `@misc` with the current year. `api.github.com` answers
a spent quota with HTTP 403 and a "rate limit" message, which the toolbox
reports as a failed lookup.

## Identity and caching

- Canonical id for the ledger and caches: `doi:` first (it survives the
  preprint → journal transition), then `arXiv:`, `bibcode:`, `openalex:`,
  `inspire:`; a GitHub repository is always `github:owner/repo`. `resolve_citation` cross-links: an arXiv record carries the DOI
  arXiv knows; with an ADS token every record also gains its bibcode.
- HTTP responses are cached under `~/.cache/cite-check/http` (override with
  `CITE_CHECK_CACHE`); successful lookups for 14 days (`CITE_CHECK_TTL_DAYS`),
  404s for one day. Fetched paper texts live in `…/text/<canonical id>.txt`
  and are reused across manuscripts. Nothing project-specific goes in the
  global cache; the ledger and audit live in `<manuscript dir>/.cite-check/`.
- Per-host politeness intervals are enforced across threads (arXiv 3 s, others
  0.15–0.5 s); 429/5xx responses are retried with backoff honouring
  `Retry-After`.

## Configuration — API keys and contact address

`bash mcp/setup_mcp.sh` (called by `scripts/install.sh`) asks for each of
these during installation; `bash mcp/setup_mcp.sh --keys` asks again any
time. Input is not echoed. Press Enter to skip one: that source stays
disabled and the other registries keep working. Without a terminal (CI, an
agent's shell) the questions are skipped automatically; `--skip-keys` skips
them explicitly.

| Key | Enables | Where to get it |
|---|---|---|
| **NASA ADS API token** | ADS search, bibcode resolution, ADS BibTeX export | <https://ui.adsabs.harvard.edu/user/settings/token> (free account) |
| **contact e-mail** | Crossref's and OpenAlex's "polite pools": faster, more reliable answers | any address you own; it is sent only in the User-Agent / `mailto` parameter of those two APIs |
| **GitHub token** | 5000 GitHub API requests/hour instead of 60 (≈ 15 repositories on a cold cache) | <https://github.com/settings/personal-access-tokens/new> — fine-grained, public repositories read-only, no permissions; tested against `/rate_limit` before it is kept |

**Where secrets live.** A token is tested against ADS before it is stored
(a rejected token is not kept), then written to the OS keychain when there
is one — macOS Keychain (service `cite-check`, account `ads`) or Linux
Secret Service via `secret-tool` — and otherwise to
`~/.config/cite-check/keys/<name>` with mode 0600 inside a 0700 directory
(`$XDG_CONFIG_HOME` is honoured). The value reaches the store on stdin,
never on a command line (argv is visible in `ps`), and is never written into
a harness's MCP configuration, a log, or this repository. The contact
address is not a secret and goes to `~/.config/cite-check/config.json`
(also 0600).

**Lookup order at run time** (first hit wins): environment variable →
keychain → 0600 file → legacy files (`~/.ads/dev_key`, the `ads` package
convention) → not configured. `ping` reports `ads_token_source` and
`keyring`, and warns if the key file is readable by others.

| Variable | Effect |
|---|---|
| `ADS_API_TOKEN` (also `ADS_DEV_KEY`, `ADS_TOKEN`) | overrides the stored ADS token for this process |
| `GITHUB_TOKEN` (also `GH_TOKEN`) | overrides the stored GitHub token for this process |
| `CITE_CHECK_MAILTO` | overrides the stored contact address |
| `CITE_CHECK_KEYRING` | `auto` (default): keychain if present, else file · `file`: always the 0600 file · `off`: ignore stored keys, environment only |
| `CITE_CHECK_CACHE` | cache directory (default `$XDG_CACHE_HOME/cite-check` or `~/.cache/cite-check`) |
| `CITE_CHECK_TTL_DAYS` | metadata cache lifetime (default 14) |

Managing keys without the prompt:

```
python mcp/server.py keys list                    # what is configured, from where (values masked)
printf '%s' "$TOKEN" | python mcp/server.py keys set ads     # store (tested live first)
python mcp/server.py keys test ads                # re-test the stored token (also: test github)
python mcp/server.py keys delete ads              # forget it (keychain and file)
bash mcp/setup_mcp.sh --uninstall --purge-keys    # uninstall and forget every key
```

ADS BibTeX: `journal_format` 1 = AASTeX macros (`\apj`), 2 = abbreviations,
3 = full names. `fetch_bibtex` / `bib_add` pick 1 automatically when
`tex_path`'s `\documentclass` is an AASTeX/MNRAS/A&A/emulateapj class and 2
otherwise; pass the number to override. `max_author` (default 10) sets the
author cut-off in ADS exports.
