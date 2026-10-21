# Additional literature sources

`search_citation` can query Semantic Scholar, PubMed and dblp when the caller
explicitly selects them. The default registry list is unchanged. These
adapters broaden discovery coverage; their search results do not establish
citation identity, official-export provenance or scientific support.

```json
{
  "title": "the title or topic to investigate",
  "author": "Surname",
  "year": 2020,
  "registries": ["semanticscholar", "pubmed", "dblp"],
  "max_results": 8
}
```

Each source uses a bounded first page. Results are locally ranked using the
existing title, author, year and context scoring. A high ranking is a search
match, not a verified citation. Errors from one source remain visible without
hiding successful responses from the others. A rate limit, access challenge,
malformed response or failed lookup is not evidence that a paper does not
exist. These searches are not exhaustive literature reviews.

Each adapter requests at most 10 records. `max_results` must be an integer
from 1 to 100 and limits the combined returned list. Unknown registry names
and an empty `registries` list are errors, so a typo cannot silently select
the default sources. The source list is deduplicated before requests.

## Candidate boundaries

New-source candidates carry `discovery_only: true`,
`verification_status: "unverified"`, a provider-qualified native `id`, and
provenance identifying the source record. The native locator is separate
from `suggested_ids`, which contains any syntactically valid DOI/arXiv
identifiers reported by that source. Suggested aliases remain unverified.

For example, `pmid:12345678` identifies a PubMed search record; it is not an
official BibTeX export identifier accepted by this adapter. Semantic Scholar
paper IDs and dblp record keys have the same discovery-only role. The tool
does not invent a DOI when a record lacks one.

Keep each source's record separate. The new adapters do not splice fields
into a canonical work by matching its title or author, and do not write
search records into the canonical-record or alias caches. HTTP response
caching still applies, so a result need not represent a fresh live lookup.
The same work can appear as separate candidates from several sources.

To use a candidate:

1. Review its metadata and provenance, then resolve a suggested official
   identifier with the ordinary `resolve_citation` workflow.
2. Compare the resolved work with the intended citation. Obtain its entry
   through `fetch_bibtex` / `bib_add`; existing official-export rules apply.
3. Retrieve the actual source/version and independently judge every attached
   claim. Search snippets, abstracts, citation counts and graph membership
   do not substitute for the support check.

A candidate without a usable official identifier remains visible for further
investigation. Search the established registries or obtain the correct
identifier from the work itself; a native discovery ID cannot be used to
bypass `no-official-bibtex`. No new export source is authorized by this
feature.

## Service behavior

| Source | Request scope | Intended coverage |
|---|---|---|
| Semantic Scholar | One bounded paper-search request; optional API key | Broad scientific literature |
| PubMed | Bounded ESearch IDs, followed by one batched ESummary | Biomedical literature |
| dblp | One bounded publication-search JSON request | Computer science publications |

Requests use the existing HTTP cache, retries, host throttles and active
request/time budgets. A PubMed search uses two HTTP requests when it finds
IDs; one source search does not mean one network request. Automatic retries
are also physical requests. The adapters do not crawl graph neighbors or
page through an unbounded result set.

The three public API hosts use the existing declared zero-service-fee
estimate for budget admission. This is not measured billing; actual cost
remains unknown. Request, search and time limits still apply, and an unknown
host's price is not silently treated as zero.

PubMed uses public access without an API key in the URL. Semantic Scholar
credentials, when configured, are sent in the service's `x-api-key` header;
never put them into a query, manuscript, log or harness configuration.
Service outages and rate limits remain possible, including with a key.

The existing key manager recognizes `semanticscholar`; installation prompts
discover it automatically. Environment overrides are
`SEMANTIC_SCHOLAR_API_KEY` and `S2_API_KEY`. The key follows the same OS
keychain or protected-file storage as other secret keys. Key validation
performs a small authenticated search, reports status without echoing the
credential, and does not imply that later searches will avoid rate limits.
Requests carrying this key refuse redirects, including same-origin ones.
A redirect is reported as a source failure instead of forwarding a secret.

The implementation follows the official [Semantic Scholar API
reference](https://api.semanticscholar.org/api-docs/), [NCBI E-utilities
reference](https://www.ncbi.nlm.nih.gov/books/NBK25499/), and [dblp search API
reference](https://dblp.org/faq/How+to+use+the+dblp+search+API.html). These
interfaces provide discovery metadata; cite-check applies its own validation
and citation policy to their responses.
