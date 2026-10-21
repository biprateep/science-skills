"""Pure Markdown and inert HTML report rendering."""

import html
import json
import os
import re
from typing import Any


def _corrections_markdown(report: dict[str, Any]) -> str:
    """Render actionable findings while preserving exact quoted strings."""
    policy = report.get("policy")
    if policy not in ("exploratory", "submission-ready"):
        policy = "invalid"
    lines = [
        "# Citation correction report",
        "",
        (
            f"Policy: {policy}; submission ready: "
            f"{report.get('submission_ready', False)}."
        ),
        (
            "Proposals are unapproved drafts, not verified repl"
            "acements. No edits were applied."
        ),
        "",
    ]
    for item in report.get("corrections", []):
        location = item["location"]
        lines += [
            f"## {item['type']} — {item['finding_id'][:12]}",
            "",
            (
                f"Occurrence: {item['occurrence_id'] or 'unknown'}; "
                f"atom: {item['atom_id'] or 'none'}"
            ),
            "",
        ]
        # JSON string blocks preserve whitespace and cannot open raw HTML.
        for label, value in (
            ("Location", location),
            ("Bibliography locations", item["bibliography_locations"]),
            ("Assertion", item["assertion"]),
            ("Original sentence", item["claim"]),
            ("Context", item["context"]),
            ("Finding", item["detail"]),
            ("Publication status", item.get("publication_status")),
            ("Evidence", item["source_evidence"]),
            ("Unapproved proposal", item["proposed_correction"]),
        ):
            if value is not None:
                encoded = json.dumps(value, ensure_ascii=False, indent=2)
                fence = "`" * max(
                    3,
                    max(
                        (
                            len(match[0]) + 1
                            for match in re.finditer(r"`+", encoded)
                        ),
                        default=3,
                    ),
                )
                lines += [f"{label}:", f"{fence}json", encoded, fence, ""]
        lines += [item["next_action"]["instruction"], ""]
    return "\n".join(lines) + "\n"

def _corrections_html(report: dict[str, Any], sources: dict[str, str]) -> str:
    """Render escaped findings linked to unchanged source-line text."""
    blocks = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        (
            '<meta http-equiv="Content-Security-Policy" content'
            "=\"default-src 'none'; style-src 'unsafe-inline'; b"
            "ase-uri 'none'; form-action 'none'\">"
        ),
        "<title>Citation correction report</title>",
        (
            "<style>body{font:16px system-ui;max-width:1100px;m"
            "argin:2em auto;padding:0 1em}pre{white-space:pre-w"
            "rap;overflow-wrap:anywhere;background:#f4f4f4;padd"
            "ing:1em}.finding{border-left:4px solid #a64b00;pad"
            "ding:1em;margin:1em 0}.line{display:block}.marked{"
            "background:#fff1c9}.number{color:#666;display:inli"
            "ne-block;min-width:4em}.badge{font:12px system-ui;"
            "margin-right:1em}a{color:#704000}</style>"
        ),
        "</head><body><h1>Citation correction report</h1>",
        (
            "<p>No edits were applied. Proposed wording is unap"
            "proved and must be independently checked after app"
            "lication.</p>"
        ),
    ]
    indices = {path: index for index, path in enumerate(sources)}
    line_findings: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for item in report.get("corrections", []):
        blocks += [
            f'<section class="finding" id="finding-{item["finding_id"]}">',
            f"<h2>{html.escape(item['type'])}</h2>",
        ]
        locations = [("Manuscript", item["location"])] + [
            ("Bibliography", location)
            for location in item["bibliography_locations"]
        ]
        for label, location in locations:
            path, line = location["file"], location["line"]
            anchor = None
            if (
                path in indices
                and type(line) is int
                and 1 <= line <= len(sources[path].splitlines())
            ):
                anchor = f"source-{indices[path]}-line-{line}"
                line_findings.setdefault((path, line), []).append(item)
            where = html.escape(
                f"{label}: {path or 'unknown location'}:"
                f"{line or 'unknown line'}"
            )
            blocks.append(
                f'<p><a href="#{anchor}">{where}</a></p>'
                if anchor
                else f"<p>{where}</p>"
            )
        for label, value in (
            ("Disputed assertion", item["assertion"]),
            ("Original sentence", item["claim"]),
            ("Context", item["context"]),
            ("Finding", item["detail"]),
            ("Publication status", item.get("publication_status")),
            ("Next action", item["next_action"]["instruction"]),
        ):
            if value is not None:
                rendered = (
                    value
                    if isinstance(value, str)
                    else json.dumps(value, ensure_ascii=False, indent=2)
                )
                blocks += [
                    f"<h3>{label}</h3><pre>{html.escape(rendered)}</pre>"
                ]
        proposal = item["proposed_correction"]
        if proposal:
            blocks.append("<h3>Unapproved judge-authored proposal</h3>")
            blocks.append(
                "<pre>"
                + html.escape(
                    json.dumps(proposal, ensure_ascii=False, indent=2)
                )
                + "</pre>"
            )
        evidence = item["source_evidence"]
        if evidence:
            blocks += [
                "<h3>Source evidence</h3>",
                "<p>Bibliographic attribution: "
                + html.escape(evidence["attribution"])
                + "</p>",
            ]
            for quote in evidence["quotes"]:
                blocks.append(
                    "<pre>" + html.escape(quote["source_text"]) + "</pre>"
                )
        blocks += [
            (
                "<details><summary>Exact identifiers and evidence m"
                "etadata</summary><pre>"
            ),
            html.escape(json.dumps(item, ensure_ascii=False, indent=2)),
            "</pre></details></section>",
        ]
    for path, content in sources.items():
        index = indices[path]
        blocks += [f"<h2>{html.escape(path)}</h2><pre>"]
        for number, line in enumerate(content.splitlines(keepends=True), 1):
            findings = line_findings.get((path, number), [])
            css = "line marked" if findings else "line"
            blocks.append(
                f'<span class="{css}" id="source-{index}-line-{number}">'
                f'<span class="number">{number}</span>'
            )
            for item in findings:
                blocks.append(
                    f'<a class="badge" href="#finding-{item["finding_id"]}">'
                    f"{html.escape(item['type'])}</a>"
                )
            blocks.append(
                '<code class="source-text">'
                + html.escape(line)
                + "</code></span>"
            )
        blocks.append("</pre>")
    blocks.append("</body></html>")
    return "".join(blocks)

def _audit_markdown(rep: dict[str, Any], ver: dict[str, Any], coverage: dict[str, Any]) -> str:
    label = (
        "SUBMISSION READY"
        if rep["submission_ready"]
        else "EXPLORATORY PROGRESS"
        if rep["ok"]
        else "NEEDS ATTENTION"
    )
    lines = [
        f"# cite-check audit — {label}",
        "",
        f"- policy: `{rep['policy']}`",
        f"- input complete: {rep['input_complete']}; "
        f"assessment complete: {rep['complete']}",
        f"- submission ready: {rep['submission_ready']}",
        f"- manuscript: `{rep['tex']}`",
        f"- bib: {', '.join('`%s`' % b for b in rep['bibs']) or '(none)'}",
        f"- citation instances: {rep['n_instances']} over {rep['n_keys']} keys",
        f"- existence: {rep['existence_counts']}",
        f"- support: {rep['support_counts']} "
        f"(missing: {rep['support_missing']})",
        f"- checked: {rep['checked']}",
        "",
    ]
    lines += [
        "## Coverage",
        "",
        "| axis | assessed / expected | outcomes |",
        "|---|---|---|",
    ]
    for name, axis in rep["coverage"].items():
        lines.append(
            f"| {name} | {axis['assessed']} / {axis['expected']} | "
            f"{axis['counts']} |"
        )
    lines += [
        "",
        "Assessment includes negative and inaccessible outcomes; "
        "it is not a readiness claim. Provenance verification checks local "
        "export receipts, not registry signatures.",
        "",
    ]
    for title, items in (
        ("Failures", rep["failures"]),
        ("Warnings", rep["warnings"]),
    ):
        lines += [f"## {title} ({len(items)})", ""]
        for it in items:
            where = (
                f" ({os.path.basename(it['file'])}:{it.get('line', '—')})"
                if it.get("file")
                else ""
            )
            lines.append(
                f"- **{it['type']}** `{it.get('key', '')}`{where}: "
                f"{it.get('status') or it.get('verdict') or ''} "
                f"{it.get('detail') or ''}".rstrip()
            )
            if it.get("claim"):
                lines.append(f"  > {it['claim']}")
            if it.get("atom"):
                lines.append(f"  Atom `{it['atom_id']}`: {it['atom']}")
        lines.append("")
    lines += [
        "## Per key",
        "",
        "| key | existence | id | support verdicts |",
        "|---|---|---|---|",
    ]
    for key in sorted(coverage):
        v = ver.get(key, {})
        lines.append(
            f"| `{key}` | {v.get('status', '—')} | "
            f"{v.get('id', '')} | {coverage[key]} |"
        )
    return "\n".join(lines) + "\n"
