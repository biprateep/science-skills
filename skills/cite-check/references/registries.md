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

## Identity and caching

- Canonical id for the ledger and caches: `doi:` first (it survives the
  preprint → journal transition), then `arXiv:`, `bibcode:`, `openalex:`,
  `inspire:`. `resolve_citation` cross-links: an arXiv record carries the DOI
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
| `CITE_CHECK_MAILTO` | overrides the stored contact address |
| `CITE_CHECK_KEYRING` | `auto` (default): keychain if present, else file · `file`: always the 0600 file · `off`: ignore stored keys, environment only |
| `CITE_CHECK_CACHE` | cache directory (default `$XDG_CACHE_HOME/cite-check` or `~/.cache/cite-check`) |
| `CITE_CHECK_TTL_DAYS` | metadata cache lifetime (default 14) |

Managing keys without the prompt:

```
python mcp/server.py keys list                    # what is configured, from where (values masked)
printf '%s' "$TOKEN" | python mcp/server.py keys set ads     # store (tested live first)
python mcp/server.py keys test ads                # re-test the stored token
python mcp/server.py keys delete ads              # forget it (keychain and file)
bash mcp/setup_mcp.sh --uninstall --purge-keys    # uninstall and forget every key
```

ADS BibTeX: `journal_format` 1 = AASTeX macros (`\apj`), 2 = abbreviations,
3 = full names. `fetch_bibtex` / `bib_add` pick 1 automatically when
`tex_path`'s `\documentclass` is an AASTeX/MNRAS/A&A/emulateapj class and 2
otherwise; pass the number to override. `max_author` (default 10) sets the
author cut-off in ADS exports.
