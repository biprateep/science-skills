# Citation engine architecture

The CLI and native MCP server use the same `cite_check_engine` package under
`mcp/`. `server.py` remains the supported entry point for installations,
other skills and direct commands. It bootstraps the package and dispatches
the existing tools, key commands or isolated PDF worker.

This refactor preserves public tool names, argument defaults, JSON output
contracts, evidence rules and stored identity calculations. A module move
does not turn an unchecked candidate into a verified citation, alter an
atomic claim or weaken strict audit readiness.

## Module ownership

| Layer | Modules | Responsibility |
|---|---|---|
| Shared contracts and state | `models`, `config`, `budgets` | Wire shapes, public request dataclasses, configuration and the request-budget context/controller |
| Low-level operations | `identifiers`, `text`, `parsing`, `persistence` | Identifier normalization, text utilities, BibTeX parsing, locks and atomic file operations |
| Network and credentials | `transport`, `network_pool`, `credentials` | HTTP/cache/retry/throttle behavior, pooled connections and secret access/storage |
| Registry work | `registry_clients`, `resolution`, `discovery`, `bibliography` | Provider adapters, canonical identity/version resolution, candidate ranking, official exports and bibliography checks |
| Manuscripts and evidence | `manuscripts`, `acquisition`, `evidence` | Input extraction/mappings, source retrieval/snapshots, atomic claims and stored independent judgments |
| Audit and reports | `findings`, `reports`, `freshness`, `audit`, `reporting`, `jobs` | Finding construction, pure rendering, snapshot checks, audit/report orchestration and resumable verification |
| Entry points | `api`, `admin` | Static tool registration, CLI/native MCP dispatch, ping and key-management commands |

Cross-module calls refer to the owner module rather than copying a mutable
setting or a function reference into several modules. Request-budget state,
HTTP throttle state, cache configuration and request model classes each have
one owner. A worker thread must receive the current request context through
the existing propagation helper.

Parsing and persistence sit below the workflows that use them. Report
renderers consume results; they do not perform registry lookups or decide
whether a manuscript is ready. Audit and report orchestration own those
checks, including the final snapshot comparison before publishing results.
Package modules do not import the server entry point.

## Shared types and runtime checks

`models` defines shared `Work`, `CitationInstance`, `Claim`, `SourceSnapshot`
and `Judgment` mapping shapes. Engine constructors and function signatures
use these contracts at record, manuscript, source and judgment boundaries.
They preserve the existing dictionary/JSON representation rather than
introducing a new serialization format.

Python `TypedDict` expresses a static contract; it does not validate an
untrusted dictionary at runtime. Registry response validators, exact marker
and atom validation, quote checks, ledger validation and snapshot checks
remain responsible for runtime acceptance. Do not replace those checks with
a type annotation or an unchecked cast.

Public request dataclasses also have a single definition. Both MCP SDK
versions therefore see the same model identities and nested validation
rules. Keep the existing strict fields, defaults and extra-field rules when
extending a request model.

## Running and installing

Existing commands remain valid:

```sh
python <skills>/cite-check/mcp/server.py call ping '{}'
python <skills>/cite-check/mcp/server.py call audit '<audit JSON>'
python <skills>/cite-check/mcp/server.py keys list
```

The entry point resolves its installed location, so a supported symlink or
an unrelated working directory does not select a second copy of the engine.
The isolated PDF worker launches the resolved server entry point explicitly;
it does not try to execute an internal module file as a standalone script.

Keep the `cite_check_engine` directory with `server.py` when distributing or
moving the tool. Copying only `server.py` is no longer a complete deployment.
The repository installer already installs the skill directory; native MCP
registrations continue to point to `server.py`. No harness configuration
migration is required.

## Regression seams

The production entry point exposes the supported public tools. Legacy tests
that patched private monolith globals use a test-only owner map/proxy to
patch the actual module where a helper or mutable setting now lives. This
compatibility layer is not part of the installed runtime or its API.

When adding a new test, prefer the owning module directly. A patch to a
copied function alias may leave the real call path unchanged, producing a
misleading passing test. Test public CLI/native MCP behavior as well as
internal validators when changing their contracts.

The compatibility checks cover public schemas, module ownership, entry-point
imports, symlink/arbitrary-directory execution and the PDF worker. Existing
citation regressions continue to cover the scientific and persistence rules.
