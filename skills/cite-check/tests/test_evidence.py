"""Regression tests for audit finding 1: exact evidence certification."""
import importlib
import importlib.util
import pathlib
import typing
import unittest
import unittest.mock

import engine_test_support

SPEC = importlib.util.spec_from_file_location(
    "cite_server", pathlib.Path(__file__).parents[1] / "mcp" / "server.py"
)
SERVER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SERVER)
SERVER = engine_test_support.LegacyServer(SERVER)


def source_intake(path: pathlib.Path) -> dict[str, typing.Any]:
    """Describe the complete local bytes used by a known-good test fixture."""
    quality = importlib.import_module("cite_check_engine.quality")
    return typing.cast(
        dict[str, typing.Any],
        quality.make_intake(path.read_bytes(), "local-text"),
    )


def official_export_fixture(
    raw: str, record: dict[str, typing.Any], source: str = "crossref"
) -> dict[str, typing.Any]:
    """Represent a synthetic registry response through the real sanitizer."""
    bibliography = importlib.import_module("cite_check_engine.bibliography")
    entry = SERVER._parse_bib(raw)["entries"][0]
    return {
        "bibtex": bibliography._sanitize_bibtex(entry, record),
        "raw_export": raw,
        "source": source,
        "origin": "tool-generated-software-entry"
        if source in {"github", "citation-cff"}
        else "registry-export-text",
        "tried": [],
    }


def official_bib_fixture(
    raw: str,
    record: dict[str, typing.Any],
    bib_path: pathlib.Path,
    source: str = "crossref",
) -> str:
    """Issue real receipts for synthetic data; never mock provenance checks."""
    bibliography = importlib.import_module("cite_check_engine.bibliography")
    got = official_export_fixture(raw, record, source)
    request = {
        "identifier": SERVER._canonical(record),
        "version": record.get("requested_version"),
        "prefer": ["github" if source == "citation-cff" else source],
        "journal_format": 2,
        "max_author": 10,
    }
    with unittest.mock.patch.object(
        SERVER, "CACHE_DIR", str(bib_path.parent / "fixture-export-cache")
    ):
        proof = bibliography._make_export_proof(
            record, got, got["bibtex"], request, str(bib_path)
        )
    return bibliography._prov_comment(record, source, proof) + "\n" + got["bibtex"]


class EvidenceTest(unittest.TestCase):
    """Quotes cannot alter scientific meaning through normalization."""

    def test_semantic_changes_are_rejected(self):
        pairs = [
            ("The treatment did not improve survival in the study.",
             "The treatment did improve survival in the study."),
            ("The measured velocity is -100 km/s.",
             "The measured velocity is +100 km/s."),
            ("The measured probability is 0.01.",
             "The measured probability is 0.91."),
            ("The measured parameter is α = X².",
             "The measured parameter is β = x2."),
        ]
        for source, quote in pairs:
            with self.subTest(quote=quote):
                self.assertFalse(SERVER._locate_quote(source, quote)["found"])

    def test_offsets_refer_to_original_source(self):
        source = "prefix\nThe ﬁtted\n  value is -100 km/s. suffix"
        result = SERVER._locate_quote(
            source, "The fitted value is -100 km/s."
        )
        self.assertTrue(result["found"])
        self.assertEqual(result["source_text"],
                         source[result["at"]:result["end"]])
        self.assertEqual(result["at"], source.index("The"))

    def test_superscripts_are_not_plain_digits(self):
        self.assertFalse(SERVER._locate_quote(
            "The total area is 100 m².", "The total area is 100 m2."
        )["found"])


if __name__ == "__main__":
    unittest.main()
