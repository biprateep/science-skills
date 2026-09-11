#!/usr/bin/env bash
# ==============================================================================
# Smoke-test the cite-check MCP toolbox (CLI mode — no MCP client needed).
#
#   bash tests/verify_mcp.sh [--network]
#
# Offline checks parse the fixture manuscript, verify quote matching and the
# ledger rules, and run the audit without registry lookups. --network adds
# live resolution, search, official BibTeX export, verify_bib and a full
# audit; ADS checks run only when a token is configured.
# Uses mcp/.venv if present, else system python3. The cache is redirected to
# a temporary directory so tests never touch ~/.cache/cite-check.
# ==============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$HERE/../mcp/server.py"
PY="$HERE/../mcp/.venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"
W="$(mktemp -d)"
trap 'rm -rf "$W"' EXIT
export CITE_CHECK_CACHE="$W/cache"
XDG_CONFIG_HOME_REAL="${XDG_CONFIG_HOME:-$HOME/.config}"
export XDG_CONFIG_HOME="$W/config"      # key store under test, never the real one
export CITE_CHECK_KEYRING=file
unset ADS_API_TOKEN ADS_DEV_KEY ADS_TOKEN CITE_CHECK_MAILTO
cp "$HERE"/fixtures/* "$W/"

PASS=0; FAIL=0
check() {  # check <name> <expected_exit> <cmd...>
    local name="$1" expected="$2"; shift 2
    "$@" >"$W/last.json" 2>"$W/last.err"
    local got=$?
    if [ "$got" -eq "$expected" ]; then
        echo "PASS  $name"; PASS=$((PASS+1))
    else
        echo "FAIL  $name (exit $got, expected $expected)"; FAIL=$((FAIL+1))
        head -c 600 "$W/last.json" "$W/last.err" 2>/dev/null | sed 's/^/      /'
    fi
}
field() {  # field <python expr over r> — evaluated on the last JSON result
    "$PY" -c "import json,sys; r=json.load(open(sys.argv[1])); print($1)" "$W/last.json"
}
expect() {  # expect <name> <python expr that must be truthy>
    if [ "$(field "$1")" = "True" ]; then echo "PASS  $2"; PASS=$((PASS+1)); else echo "FAIL  $2 ($1 -> $(field "$1"))"; FAIL=$((FAIL+1)); fi
}

CLAIM1='Attention-based sequence models dispense with recurrence entirely and rely on self-attention alone ⟨cite:vaswani2017⟩.'
CLAIM2='Transformers were trained on WMT 2014 English-German data ⟨cite:vaswani2017,einstein1935⟩.'

check "ping" 0 "$PY" "$SERVER" call ping '{}'
expect 'r["ads_token"] is False and r["ads_token_source"] == "none" and r["keyring"] == "file"' "ping: no key configured, file backend forced"

# --- API key store (file backend, isolated config dir) -------------------------
check "keys: names" 0 "$PY" "$SERVER" keys names
check "keys: store a token without the live test" 0 bash -c "printf 'FAKETOKEN1234567890abcdefghij' | \"$PY\" \"$SERVER\" keys set ads --no-test"
check "keys: token with whitespace refused" 1 bash -c "printf 'bad token' | \"$PY\" \"$SERVER\" keys set ads --no-test"
check "keys: empty value refused" 1 bash -c "printf '' | \"$PY\" \"$SERVER\" keys set ads --no-test"
check "keys: malformed e-mail refused" 1 bash -c "printf 'nope' | \"$PY\" \"$SERVER\" keys set mailto"
check "keys: e-mail stored" 0 bash -c "printf 'someone@example.org' | \"$PY\" \"$SERVER\" keys set mailto"
check "keys: file is 0600 in a 0700 dir" 0 bash -c "[ \"\$(stat -c %a \"$W/config/cite-check/keys/ads\")\" = 600 ] && [ \"\$(stat -c %a \"$W/config/cite-check/keys\")\" = 700 ] && [ \"\$(stat -c %a \"$W/config/cite-check\")\" = 700 ]"
check "keys: list --json" 0 "$PY" "$SERVER" keys list --json
expect 'r[0]["source"] == "file" and r[0]["masked"] == "…ghij" and r[1]["source"] == "config" and r[1]["masked"] == "someone@example.org"' "keys: list reports sources with the token masked"
check "ping: stored key is picked up" 0 "$PY" "$SERVER" call ping '{}'
expect 'r["ads_token"] is True and r["ads_token_source"] == "file" and r["mailto"] == "someone@example.org"' "ping: token from file, e-mail from config"
check "keys: environment overrides the store" 0 env ADS_API_TOKEN=ENVTOKEN0000000000 "$PY" "$SERVER" keys list --json
expect 'r[0]["source"] == "env:ADS_API_TOKEN" and r[0]["masked"] == "…0000"' "keys: env source reported"
check "keys: loose permissions are flagged" 0 bash -c "chmod 644 \"$W/config/cite-check/keys/ads\" && \"$PY\" \"$SERVER\" keys list | grep -q WARNING; s=\$?; chmod 600 \"$W/config/cite-check/keys/ads\"; exit \$s"
check "keys: delete all" 0 "$PY" "$SERVER" keys delete --all
check "keys: nothing left on disk" 0 bash -c "[ ! -e \"$W/config/cite-check/keys/ads\" ]"
check "ping: no key again" 0 "$PY" "$SERVER" call ping '{}'
expect 'r["ads_token"] is False' "ping: token gone after delete"

check "extract: fixture parses" 0 "$PY" "$SERVER" call extract_cites "{\"tex_path\": \"$W/sample.tex\"}"
expect 'r["n_instances"] == 9 and r["n_keys"] == 6' "extract: 9 instances over 6 keys (follows \\input, skips comments)"
expect 'any(c["cmd"] == "nocite" and c["nocite"] for c in r["cites"])' "extract: \\nocite flagged"
expect 'r["documentclass"] == "aastex631" and r["bib_files"][0].endswith("sample.bib")' "extract: documentclass and .bib discovered"
expect 'all("⟨cite:" in c["claim"] for c in r["cites"])' "extract: every claim carries its cite placeholder"

# Seed the (temporary) record cache so the ledger and audit checks run with no
# network: the fixture text is ingested under the real arXiv id of the paper.
mkdir -p "$W/cache/records"
"$PY" - "$W/cache/records" <<'PYEOF'
import json, sys, os
d = sys.argv[1]
rec = {"registry": "arxiv", "registries": ["arxiv"], "title": "Attention Is All You Need",
       "authors": ["Ashish Vaswani", "Noam Shazeer"], "year": 2017, "venue": "arXiv", "doi": None,
       "arxiv": "1706.03762", "bibcode": None, "openalex": None, "inspire": None, "abstract": "x",
       "type": "preprint", "url": "https://arxiv.org/abs/1706.03762", "citation_count": None, "pdf_urls": []}
json.dump(rec, open(os.path.join(d, "arXiv_1706.03762.json"), "w"))
json.dump({"id": "arXiv:1706.03762"}, open(os.path.join(d, "alias_arxiv_1706.03762.json"), "w"))
epr = dict(rec, registry="crossref", registries=["crossref"], title="Can Quantum-Mechanical Description of Physical Reality Be Considered Complete?",
           authors=["Einstein, A.", "Podolsky, B.", "Rosen, N."], year=1935, venue="Physical Review",
           doi="10.1103/physrev.47.777", arxiv=None, abstract="", url="https://doi.org/10.1103/PhysRev.47.777")
json.dump(epr, open(os.path.join(d, "doi_10.1103_physrev.47.777.json"), "w"))
json.dump({"id": "doi:10.1103/physrev.47.777"}, open(os.path.join(d, "alias_doi_10.1103_physrev.47.777.json"), "w"))
PYEOF

check "text: ingest local copy" 0 "$PY" "$SERVER" call fetch_text "{\"identifier\": \"arXiv:1706.03762\", \"text_path\": \"$W/sample_paper.txt\"}"
expect 'r["basis"] == "fulltext" and r["source"].startswith("local:")' "text: local ingest recorded as fulltext"
check "passages: ranked" 0 "$PY" "$SERVER" call find_passages "{\"identifier\": \"arXiv:1706.03762\", \"claims\": [\"$CLAIM2\"]}"
expect '"WMT 2014" in r["results"][0]["passages"][0]["text"]' "passages: top passage carries the claim's content"

check "ledger: SUPPORTS with verbatim quote" 0 "$PY" "$SERVER" call record_support "{\"workdir\": \"$W\", \"key\": \"vaswani2017\", \"identifier\": \"arXiv:1706.03762\", \"claim\": \"$CLAIM1\", \"verdict\": \"SUPPORTS\", \"quotes\": [\"dispensing with recurrence and convolutions entirely\"]}"
check "ledger: SUPPORTS with paraphrase refused" 1 "$PY" "$SERVER" call record_support "{\"workdir\": \"$W\", \"key\": \"vaswani2017\", \"identifier\": \"arXiv:1706.03762\", \"claim\": \"$CLAIM2\", \"verdict\": \"SUPPORTS\", \"quotes\": [\"the model was trained on ImageNet\"]}"
check "ledger: UNVERIFIABLE refused when text exists" 1 "$PY" "$SERVER" call record_support "{\"workdir\": \"$W\", \"key\": \"vaswani2017\", \"identifier\": \"arXiv:1706.03762\", \"claim\": \"$CLAIM2\", \"verdict\": \"UNVERIFIABLE\", \"note\": \"could not obtain the text\"}"
check "ledger: UNSUPPORTED without note refused" 1 "$PY" "$SERVER" call record_support "{\"workdir\": \"$W\", \"key\": \"einstein1935\", \"identifier\": \"10.1103/PhysRev.47.777\", \"claim\": \"$CLAIM2\", \"verdict\": \"UNSUPPORTED\"}"
check "ledger: UNSUPPORTED with note" 0 "$PY" "$SERVER" call record_support "{\"workdir\": \"$W\", \"key\": \"einstein1935\", \"identifier\": \"10.1103/PhysRev.47.777\", \"claim\": \"$CLAIM2\", \"verdict\": \"UNSUPPORTED\", \"note\": \"EPR is about quantum mechanics, not machine translation\"}"
check "ledger: read" 0 "$PY" "$SERVER" call ledger_read "{\"workdir\": \"$W\"}"
expect 'len(r["ledger"]["entries"]) == 2' "ledger: two verdicts recorded"

check "audit (offline, verify=false): fails on unjudged instances" 1 "$PY" "$SERVER" call audit "{\"tex_path\": \"$W/sample.tex\", \"verify\": false}"
expect 'sum(1 for f in r["failures"] if f["type"] == "support-missing") == 6 and any(f["type"] == "support" for f in r["failures"])' "audit: 6 missing + 1 UNSUPPORTED failure"
check "audit (offline, no support required): recorded UNSUPPORTED still fails" 1 "$PY" "$SERVER" call audit "{\"tex_path\": \"$W/sample.tex\", \"verify\": false, \"require_support\": false}"
expect 'not any(f["type"] == "support-missing" for f in r["failures"]) and any(f["type"] == "support" for f in r["failures"])' "audit: missing verdicts demoted to warnings, UNSUPPORTED kept"
check "audit: report written" 0 test -s "$W/.cite-check/audit.md"

if [ "${1:-}" != "--network" ]; then
    echo "SKIP  registry checks (pass --network to enable)"
    echo ""
    echo "$PASS passed, $FAIL failed"
    exit $((FAIL > 0))
fi

check "resolve: real arXiv id" 0 "$PY" "$SERVER" call resolve_citation '{"identifier": "arXiv:1706.03762"}'
expect 'r["ids"]["arxiv"] == "1706.03762" and r["year"] == 2017' "resolve: arXiv metadata correct"
check "resolve: real DOI" 0 "$PY" "$SERVER" call resolve_citation '{"identifier": "10.1103/PhysRev.47.777"}'
expect 'r["year"] == 1935 and "Einstein" in r["authors"][0]' "resolve: Crossref metadata correct"
check "resolve: OpenAlex id" 0 "$PY" "$SERVER" call resolve_citation '{"identifier": "W1986407511"}'
check "resolve: INSPIRE id" 0 "$PY" "$SERVER" call resolve_citation '{"identifier": "inspire:2702854"}'
check "resolve: fake arXiv id rejected" 1 "$PY" "$SERVER" call resolve_citation '{"identifier": "2599.99999"}'
check "resolve: fake DOI rejected" 1 "$PY" "$SERVER" call resolve_citation '{"identifier": "10.1234/no-such-doi-xyz"}'
check "resolve: batch" 0 "$PY" "$SERVER" call resolve_citation '{"identifier": ["hep-th/9711200", "10.5281/zenodo.3509134"]}'
expect 'r["n"] == 2 and r["results"][0]["ids"].get("doi") and r["results"][1]["registries"] == ["datacite"]' "resolve: batch cross-links arXiv→DOI, DataCite fallback"

check "search: by title/author/year" 0 "$PY" "$SERVER" call search_citation '{"title": "Attention is all you need", "author": "Vaswani", "year": 2017}'
expect 'r["candidates"][0]["id"] == "arXiv:1706.03762" and r["candidates"][0]["confidence"] == "high"' "search: real paper outranks the bogus republication"
check "search: nonsense title" 0 "$PY" "$SERVER" call search_citation '{"title": "Zorbulon quasi-tachyonic redshift manifolds resolve the Hubble tension", "author": "Blergh", "year": 2023}'
expect 'not any(c["confidence"] == "high" for c in r["candidates"])' "search: nonsense yields no high-confidence candidate"
check "search: hint + context" 0 "$PY" "$SERVER" call search_citation '{"hint": "vaswani2017attention", "context": "Transformers made attention central in language modelling."}'
expect 'r["candidates"][0]["id"] == "arXiv:1706.03762"' "search: author-year hint with context finds the paper"

check "bibtex: Crossref export" 0 "$PY" "$SERVER" call fetch_bibtex '{"identifier": "10.1103/PhysRev.47.777", "key": "einstein1935"}'
expect 'r["source"] == "crossref" and r["bibtex"].startswith("@ARTICLE{einstein1935,")' "bibtex: official Crossref entry, key rewritten"
check "bibtex: arXiv-only paper" 0 "$PY" "$SERVER" call fetch_bibtex '{"identifier": "arXiv:1706.03762", "key": "vaswani2017"}'
expect 'r["source"] in ("inspire", "arxiv") and "1706.03762" in r["bibtex"]' "bibtex: arXiv paper exported by INSPIRE or arXiv"
check "bibtex: fake id has none" 1 "$PY" "$SERVER" call fetch_bibtex '{"identifier": "2599.99999"}'

check "verify_bib: fixture" 1 "$PY" "$SERVER" call verify_bib "{\"bib_path\": \"$W/sample.bib\", \"tex_path\": \"$W/sample.tex\"}"
expect 'dict((e["key"], e["status"]) for e in r["entries"]) == {"vaswani2017": "VERIFIED", "einstein1935": "VERIFIED", "planck2015": "FOUND", "wrongdoi2020": "MISMATCH", "fake2023": "UNRESOLVED", "unused1": "UNRESOLVED"}' "verify_bib: VERIFIED / FOUND-by-search / MISMATCH (real DOI, wrong title) / UNRESOLVED as designed"

check "bib_add: replace hand-written entry + add by DOI" 0 "$PY" "$SERVER" call bib_add "{\"bib_path\": \"$W/sample.bib\", \"tex_path\": \"$W/sample.tex\", \"replace\": true, \"items\": [{\"identifier\": \"10.1051/0004-6361/201525830\", \"key\": \"planck2015\"}, {\"identifier\": \"arXiv:1706.03762\", \"key\": \"dup\"}]}"
expect '[x["status"] for x in r["results"]] == ["replaced", "added"]' "bib_add: statuses"
check "bib_add: provenance comment written" 0 grep -q '@comment{cite-check: source=crossref; id=doi:10.1051/0004-6361/201525830' "$W/sample.bib"
check "bib_add: collaboration author restored" 0 grep -q 'author = {{Planck Collaboration} and Ade' "$W/sample.bib"
check "bib_add: duplicate detected" 0 "$PY" "$SERVER" call bib_add "{\"bib_path\": \"$W/sample.bib\", \"items\": [{\"identifier\": \"arXiv:1706.03762\", \"key\": \"another\"}]}"
expect 'r["results"][0]["status"] == "duplicate" and r["results"][0]["existing_key"] == "vaswani2017"' "bib_add: reports the existing key"

check "audit: fails on the fixture" 1 "$PY" "$SERVER" call audit "{\"tex_path\": \"$W/sample.tex\"}"
expect 'any(f["type"] == "existence" and f["key"] == "wrongdoi2020" for f in r["failures"])' "audit: MISMATCH entry is a failure"
expect 'any(f["type"] == "support" and f["key"] == "einstein1935" for f in r["failures"])' "audit: UNSUPPORTED verdict is a failure"
expect 'sum(1 for f in r["failures"] if f["type"] == "support-missing") == 6' "audit: unjudged instances are failures"
expect 'r["support_counts"].get("SUPPORTS") == 1' "audit: SUPPORTS verdict counted"
check "audit: no-support mode still fails on existence" 1 "$PY" "$SERVER" call audit "{\"tex_path\": \"$W/sample.tex\", \"require_support\": false}"

check "keys: bogus ADS token rejected live and not stored" 1 bash -c "printf 'ZZZZnotarealtoken000000000000000000000000' | \"$PY\" \"$SERVER\" keys set ads"
check "keys: nothing stored after rejection" 0 bash -c "[ ! -e \"$W/config/cite-check/keys/ads\" ]"

# ADS live checks use the real key store, not the test one
if XDG_CONFIG_HOME="${XDG_CONFIG_HOME_REAL:-$HOME/.config}" CITE_CHECK_KEYRING=auto "$PY" "$SERVER" call ping '{}' | grep -q '"ads_token": true'; then
    export XDG_CONFIG_HOME="${XDG_CONFIG_HOME_REAL:-$HOME/.config}" CITE_CHECK_KEYRING=auto
    check "ads: bibcode resolves" 0 "$PY" "$SERVER" call resolve_citation '{"identifier": "2016A&A...594A..13P"}'
    check "ads: official export" 0 "$PY" "$SERVER" call fetch_bibtex '{"identifier": "2016A&A...594A..13P", "key": "planck2015", "prefer": ["ads"], "journal_format": 1}'
    expect 'r["source"] == "ads" and "adsurl" in r["bibtex"]' "ads: export carries adsurl"
else
    echo "SKIP  ADS checks (no token)"
fi

echo ""
echo "$PASS passed, $FAIL failed"
exit $((FAIL > 0))
