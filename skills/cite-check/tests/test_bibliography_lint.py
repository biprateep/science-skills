"""Advisory bibliography lint cannot replace identity or support checks."""

import hashlib
import json
import pathlib
import tempfile
from typing import Any
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER


class BibliographyLintTest(unittest.TestCase):
    """Exercise formatting advice from exact source bytes, without network."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.bib = self.root / "refs.bib"
        self.record: dict[str, Any] = {
            "resolved": True,
            "input": "doi:10.1234/example",
            "id": "doi:10.1234/example",
            "ids": {"doi": "10.1234/example"},
            "title": "An example result",
            "authors": ["Doe, Jane"],
            "year": 2020,
            "venue": "Example Journal",
            "type": "journal-article",
            "registries": ["crossref"],
        }
        patch = unittest.mock.patch.object(
            SERVER, "_resolve_many", side_effect=self.resolve
        )
        self.resolver = patch.start()
        self.addCleanup(patch.stop)
        for name in ("verify_bib", "search_citation", "fetch_bibtex"):
            patch = unittest.mock.patch.object(
                SERVER,
                name,
                side_effect=AssertionError("lint attempted unrelated workflow"),
            )
            patch.start()
            self.addCleanup(patch.stop)
        self.write_article()

    def resolve(self, identifiers: list[str]) -> list[dict[str, Any]]:
        """Return independent copies of one mock registry record."""
        return [dict(self.record, input=value) for value in identifiers]

    def write_article(self, **overrides: str | None) -> None:
        """Write a complete fixture article with literal field values."""
        fields: dict[str, str | None] = {
            "title": "An example result",
            "author": "Doe, Jane",
            "year": "2020",
            "journal": "Example Journal",
            "volume": "12",
            "pages": "3--8",
            "doi": "10.1234/example",
        }
        fields.update(overrides)
        text = (
            "@article{a,\n"
            + ",\n".join(
                f"  {name}={{{value}}}"
                for name, value in fields.items()
                if value is not None
            )
            + "\n}\n"
        )
        self.bib.write_text(text, encoding="utf-8")

    def lint(self, **kwargs: Any) -> dict[str, Any]:
        """Call the public advisory tool on the fixture file."""
        return SERVER.lint_bib(str(self.bib), **kwargs)

    def codes(self, report: dict[str, Any]) -> set[str]:
        """Return stable diagnostic codes without matching prose."""
        return {issue["code"] for issue in report["issues"]}

    def test_default_is_offline_and_never_certifies_readiness(self) -> None:
        before = self.bib.read_bytes()
        report = self.lint()
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["input_complete"])
        self.assertTrue(report["advisory_only"])
        self.assertFalse(report["submission_ready"])
        self.assertIsNone(report["comparison_complete"])
        self.assertTrue(report["advisory_clean"])
        self.assertEqual(report["issues"], [])
        self.resolver.assert_not_called()
        self.assertEqual(self.bib.read_bytes(), before)
        self.assertFalse((self.root / ".cite-check").exists())

    def test_missing_article_fields_are_advice_not_input_failure(self) -> None:
        self.write_article(title=None, author=None, year=None, journal=None)
        report = self.lint()
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["input_complete"])
        self.assertFalse(report["advisory_clean"])
        self.assertFalse(report["submission_ready"])
        fields = {
            issue["field"]
            for issue in report["issues"]
            if issue["code"] == "missing-field"
        }
        self.assertTrue({"title", "author"} <= fields, fields)
        self.assertTrue(
            any(field in fields for field in ("year", "date")), fields
        )
        self.assertTrue(
            any(
                field in fields
                for field in ("journal", "journaltitle", "venue")
            ),
            fields,
        )
        self.assertEqual(
            {issue["severity"] for issue in report["issues"]}, {"advisory"}
        )

    def test_known_entry_types_use_their_own_field_rules(self) -> None:
        examples = [
            "@book{k,title={A book},author={Doe, Jane},year={2020},"
            "publisher={Example Press}}",
            "@inproceedings{k,title={A paper},author={Doe, Jane},year={2020},"
            "booktitle={Proceedings of an Example Meeting}}",
            "@software{k,title={Package},author={Example Team},date={2020},"
            "version={1.2},url={https://github.com/example/package}}",
            "@online{k,title={Web resource},author={Example Team},date={2020},"
            "url={https://example.org/resource},urldate={2021-01-01}}",
            "@misc{k,title={A resource},author={Example Team},year={2020},"
            "howpublished={Public resource}}",
        ]
        for text in examples:
            with self.subTest(text=text):
                self.bib.write_text(text, encoding="utf-8")
                report = self.lint()
                self.assertTrue(report["ok"], report)
                self.assertNotIn("unknown-entry-type", self.codes(report))
                self.assertFalse(
                    any(
                        issue["code"] == "missing-field"
                        and issue["field"]
                        in {"journal", "journaltitle", "venue"}
                        for issue in report["issues"]
                    ),
                    report,
                )

    def test_unknown_entry_type_is_explicit_advice(self) -> None:
        self.bib.write_text(
            "@unrecognized{k,title={Something},author={Doe, Jane},year={2020}}",
            encoding="utf-8",
        )
        report = self.lint()
        self.assertTrue(report["ok"], report)
        self.assertIn("unknown-entry-type", self.codes(report))
        self.assertFalse(report["advisory_clean"])

    def test_date_and_journaltitle_are_valid_biblatex_alternatives(
        self,
    ) -> None:
        self.write_article(
            year=None,
            date="2020-03-12",
            journal=None,
            journaltitle="Example Journal",
        )
        report = self.lint()
        self.assertNotIn("invalid-year", self.codes(report))
        self.assertFalse(
            any(
                issue["code"] == "missing-field"
                and issue["field"] in {"year", "journal"}
                for issue in report["issues"]
            ),
            report,
        )

    def test_year_validation_distinguishes_invalid_and_future(self) -> None:
        for year in ("twenty twenty", "20", "2020garbage"):
            with self.subTest(year=year):
                self.write_article(year=year)
                self.assertIn("invalid-year", self.codes(self.lint()))
        self.write_article(year="9999")
        report = self.lint()
        self.assertIn("future-year", self.codes(report))
        self.assertTrue(report["ok"])
        self.assertFalse(report["submission_ready"])

    def test_extended_biblatex_dates_are_not_asserted_invalid(self) -> None:
        for date in ("2020", "2020-03", "2020/2021", "2020?", "2020~"):
            with self.subTest(date=date):
                self.write_article(year=None, date=date)
                report = self.lint()
                self.assertTrue(report["ok"], report)
                self.assertNotIn("invalid-year", self.codes(report))

    def test_macro_fields_are_deferred_without_false_missing_or_year_error(
        self,
    ) -> None:
        self.bib.write_text(
            "@string{journalname = {Example Journal}}\n"
            "@article{a,title={An example result},author={Doe, Jane},"
            "year=publicationyear,journal=journalname}",
            encoding="utf-8",
        )
        report = self.lint()
        self.assertTrue(report["ok"], report)
        self.assertIn("field-macro-unexpanded", self.codes(report))
        self.assertNotIn("invalid-year", self.codes(report))
        self.assertFalse(
            any(
                issue["code"] == "missing-field"
                and issue["field"] in {"year", "journal"}
                for issue in report["issues"]
            ),
            report,
        )
        self.assertFalse(report["advisory_clean"])

    def test_literal_concatenation_does_not_become_invalid_year(self) -> None:
        self.bib.write_text(
            "@article{a,title={An example result},author={Doe, Jane},"
            "year={20} # {20},journal={Example } # {Journal}}",
            encoding="utf-8",
        )
        report = self.lint()
        self.assertTrue(report["ok"], report)
        self.assertNotIn("invalid-year", self.codes(report))

    def test_field_like_text_inside_values_is_not_a_macro_assignment(
        self,
    ) -> None:
        self.write_article(
            title="A study of year = strange tokens and journal = absent",
            journal=None,
            journaltitle="Real Journal",
        )
        report = self.lint()
        self.assertTrue(report["ok"], report)
        self.assertNotIn("field-macro-unexpanded", self.codes(report))
        self.assertNotIn("invalid-year", self.codes(report))
        self.assertFalse(
            any(
                issue["code"] == "missing-field"
                and issue["field"] in {"year", "journal"}
                for issue in report["issues"]
            ),
            report,
        )

    def test_inheritance_is_deferred_instead_of_false_missing_advice(
        self,
    ) -> None:
        for field in ("crossref", "xdata"):
            with self.subTest(field=field):
                self.bib.write_text(
                    f"@inproceedings{{a,title={{Child}},"
                    f"{field}={{parent}}}}\n"
                    "@proceedings{parent,title={Proceedings},year={2020},"
                    "editor={Doe, Jane},publisher={Example Press}}",
                    encoding="utf-8",
                )
                report = self.lint(keys=["a"])
                self.assertTrue(report["ok"], report)
                self.assertIn("inheritance-not-expanded", self.codes(report))
                self.assertFalse(
                    any(
                        issue["code"] == "missing-field"
                        for issue in report["issues"]
                    ),
                    report,
                )

    def test_selected_keys_limit_advice_to_requested_entries(self) -> None:
        self.bib.write_text(
            self.bib.read_text(encoding="utf-8")
            + "\n@article{bad,title={Bad}}",
            encoding="utf-8",
        )
        report = self.lint(keys=["a"])
        self.assertTrue(report["advisory_clean"], report)
        self.assertEqual([entry["key"] for entry in report["entries"]], ["a"])
        missing = self.lint(keys=["missing"])
        self.assertFalse(missing["ok"])
        self.assertFalse(missing["input_complete"])
        self.assertFalse(missing["advisory_clean"])
        self.assertEqual(missing["issues"], [])

    def test_inheritance_helpers_are_not_treated_as_unidentified_works(
        self,
    ) -> None:
        self.bib.write_text(
            "@xdata{shared,publisher={Example Press},date={2020}}\n"
            "@set{group,entryset={one,two}}",
            encoding="utf-8",
        )
        report = self.lint(verify=True)
        self.assertTrue(report["ok"], report)
        self.assertTrue(report["advisory_clean"])
        self.assertTrue(report["comparison_complete"])
        self.assertFalse(report["submission_ready"])
        self.assertEqual(report["issues"], [])
        self.resolver.assert_not_called()

    def test_parse_errors_and_duplicate_keys_fail_before_registry_lookup(
        self,
    ) -> None:
        for text in (
            "@article{a,title={unfinished}",
            "@article{a,title={A}}\n@book{a,title={B}}",
            "@article{a,title=}",
        ):
            with self.subTest(text=text):
                self.bib.write_text(text, encoding="utf-8")
                report = self.lint(verify=True)
                self.assertFalse(report["ok"], report)
                self.assertFalse(report["input_complete"])
                self.assertEqual(report["issues"], [])
                self.assertFalse(report["advisory_clean"])
        self.resolver.assert_not_called()

    def test_invalid_selected_keys_fail_without_lookup(self) -> None:
        for keys in ("a", [17], [""], [None]):
            with self.subTest(keys=keys):
                report = self.lint(keys=keys, verify=True)
                self.assertFalse(report["ok"], report)
                self.assertFalse(report["input_complete"])
                self.assertFalse(report["advisory_clean"])
        self.resolver.assert_not_called()

    def test_invalid_utf8_is_refused_without_replacement_decoding(self) -> None:
        self.bib.write_bytes(b"@article{a,title={Bad\xff}}")
        report = self.lint()
        self.assertFalse(report["ok"], report)
        self.assertFalse(report["input_complete"])
        self.assertEqual(report["issues"], [])

    def test_oversized_input_is_refused(self) -> None:
        self.bib.write_bytes(b"%" + b"x" * (4 * 1024 * 1024))
        report = self.lint()
        self.assertFalse(report["ok"], report)
        self.assertFalse(report["input_complete"])

    def test_entry_limit_is_refused_without_partial_clean_result(self) -> None:
        self.bib.write_text(
            "\n".join(
                f"@misc{{k{index},title={{Entry}}}}" for index in range(2001)
            ),
            encoding="utf-8",
        )
        report = self.lint()
        self.assertFalse(report["ok"], report)
        self.assertFalse(report["input_complete"])
        self.assertFalse(report["advisory_clean"])

    def test_issue_locations_bind_exact_crlf_unicode_entry_bytes(self) -> None:
        first = "% α scientific bibliography\r\n"
        entry = "@article{a,\r\n title={Étude of stars},\r\n year={2020}\r\n}"
        raw = (first + entry + "\r\n").encode("utf-8")
        self.bib.write_bytes(raw)
        report = self.lint()
        self.assertTrue(report["ok"], report)
        self.assertEqual(
            report["input_sha256"], hashlib.sha256(raw).hexdigest()
        )
        self.assertTrue(report["issues"])
        for issue in report["issues"]:
            location = issue["location"]
            self.assertEqual(location["scope"], "entry")
            self.assertEqual(location["file"], str(self.bib))
            self.assertEqual(location["line"], 2)
            self.assertEqual(location["end_line"], 5)
            self.assertEqual(
                raw[location["byte_start"] : location["byte_end"]],
                entry.encode("utf-8"),
            )
            self.assertEqual(
                raw.decode("utf-8")[location["start"] : location["end"]], entry
            )
            self.assertIsInstance(issue["action"], str)
        self.assertEqual(self.bib.read_bytes(), raw)

    def test_optional_registry_comparison_uses_own_ids_only(self) -> None:
        report = self.lint(verify=True)
        self.assertTrue(report["ok"], report)
        self.resolver.assert_called_once_with(["doi:10.1234/example"])
        self.assertTrue(report["comparison_complete"])
        self.assertEqual(
            report["comparison"]["identifiers_requested"],
            ["doi:10.1234/example"],
        )
        self.assertFalse(report["submission_ready"])

    def test_missing_identifier_does_not_trigger_title_search(self) -> None:
        self.write_article(doi=None)
        report = self.lint(verify=True)
        self.resolver.assert_not_called()
        self.assertIn("registry-comparison-unavailable", self.codes(report))
        self.assertFalse(report["comparison_complete"])
        self.assertFalse(report["advisory_clean"])

    def test_macro_locator_is_not_resolved_as_a_guessed_identifier(
        self,
    ) -> None:
        for name, prefix in (
            ("doi", "10.1234/"),
            ("url", "https://doi.org/10.1234/"),
        ):
            with self.subTest(name=name):
                self.write_article(doi=None)
                source = self.bib.read_text(encoding="utf-8").rstrip()
                self.bib.write_text(
                    source[:-1] + f',\n{name}="{prefix}" # suffix\n}}',
                    encoding="utf-8",
                )
                report = self.lint(verify=True)
                self.resolver.assert_not_called()
                self.assertFalse(report["comparison_complete"])
                self.assertIn(
                    "registry-comparison-unavailable", self.codes(report)
                )

    def test_incidental_note_doi_is_not_used_as_the_entry_identity(
        self,
    ) -> None:
        self.write_article(
            doi=None, note="For background, see DOI 10.1234/unrelated."
        )
        report = self.lint(verify=True)
        self.resolver.assert_not_called()
        self.assertFalse(report["comparison_complete"])
        self.assertIn("registry-comparison-unavailable", self.codes(report))

    def test_old_verify_artifact_is_not_trusted(self) -> None:
        directory = self.root / ".cite-check"
        directory.mkdir()
        artifact = directory / "verify.json"
        artifact.write_text(
            json.dumps({"entries": [{"key": "a", "status": "VERIFIED"}]}),
            encoding="utf-8",
        )
        before = artifact.read_bytes()
        self.record = {"resolved": False, "reason": "registry unavailable"}
        report = self.lint(verify=True)
        self.resolver.assert_called_once()
        self.assertFalse(report["comparison_complete"])
        self.assertFalse(report["advisory_clean"])
        self.assertEqual(artifact.read_bytes(), before)

    def test_confirmed_year_difference_remains_advisory(self) -> None:
        self.record["year"] = 2021
        report = self.lint(verify=True)
        self.assertTrue(report["ok"], report)
        self.assertIn("registry-year-difference", self.codes(report))
        self.assertFalse(report["advisory_clean"])
        self.assertFalse(report["submission_ready"])
        self.assertIn("2020", self.bib.read_text(encoding="utf-8"))

    def test_unconfirmed_identity_cannot_suggest_registry_year(self) -> None:
        for update in (
            {"title": "A completely unrelated publication"},
            {"year": 2025},
        ):
            with self.subTest(update=update):
                original = dict(self.record)
                self.record.update(update)
                report = self.lint(verify=True)
                self.assertIn(
                    "registry-identity-unconfirmed", self.codes(report)
                )
                self.assertNotIn("registry-year-difference", self.codes(report))
                self.assertFalse(report["comparison_complete"])
                self.record = original

    def test_misrouted_registry_identity_cannot_supply_year_advice(
        self,
    ) -> None:
        self.record.update(
            id="doi:10.1234/different",
            ids={"doi": "10.1234/different"},
            year=2021,
        )
        report = self.lint(verify=True)
        self.assertNotIn("registry-year-difference", self.codes(report))
        self.assertFalse(report["comparison_complete"])
        self.assertFalse(report["advisory_clean"])

    def test_date_only_entry_does_not_bypass_identity_year_comparison(
        self,
    ) -> None:
        self.write_article(year=None, date="2020-03-12")
        self.record["year"] = 2025
        report = self.lint(verify=True)
        self.assertNotIn("registry-year-difference", self.codes(report))
        self.assertFalse(report["comparison_complete"])
        self.assertFalse(report["advisory_clean"])

    def test_explicit_publication_crosslink_is_required_for_preprint_advice(
        self,
    ) -> None:
        self.write_article(
            doi=None,
            eprint="2201.00001",
            archiveprefix="arXiv",
            journal="arXiv e-prints",
        )
        self.record.update(
            input="arxiv:2201.00001",
            id="arxiv:2201.00001",
            ids={"arxiv": "2201.00001"},
            venue="arXiv",
            type="preprint",
        )
        before = self.lint(verify=True)
        self.assertNotIn("preprint-publication-review", self.codes(before))
        self.record.update(
            id="doi:10.1234/published",
            ids={"arxiv": "2201.00001", "doi": "10.1234/published"},
            venue="Published Journal",
            type="journal-article",
        )
        after = self.lint(verify=True)
        self.assertIn("preprint-publication-review", self.codes(after))
        self.assertFalse(after["submission_ready"])
        self.assertIn("2201.00001", self.bib.read_text(encoding="utf-8"))

    def test_versioned_preprint_is_not_silently_compared_to_latest(
        self,
    ) -> None:
        self.write_article(
            doi=None,
            eprint="2201.00001v2",
            archiveprefix="arXiv",
            journal="arXiv e-prints",
        )
        report = self.lint(verify=True)
        self.resolver.assert_not_called()
        self.assertIn("registry-version-unchecked", self.codes(report))
        self.assertFalse(report["comparison_complete"])
        self.assertFalse(report["advisory_clean"])

    def test_preprint_doi_is_not_itself_evidence_of_journal_publication(
        self,
    ) -> None:
        self.write_article(
            doi=None,
            eprint="2201.00001",
            archiveprefix="arXiv",
            journal="arXiv e-prints",
        )
        self.record.update(
            input="arxiv:2201.00001",
            id="doi:10.1234/preprint",
            ids={"arxiv": "2201.00001", "doi": "10.1234/preprint"},
            venue="Example Open Repository",
            type="preprint",
        )
        report = self.lint(verify=True)
        self.assertNotIn("preprint-publication-review", self.codes(report))

    def test_arxiv_journal_reference_can_link_a_preprint_to_publication(
        self,
    ) -> None:
        self.write_article(
            doi=None,
            eprint="2201.00001",
            archiveprefix="arXiv",
            journal="arXiv e-prints",
        )
        self.record.update(
            input="arxiv:2201.00001",
            id="doi:10.1234/published",
            ids={"arxiv": "2201.00001", "doi": "10.1234/published"},
            venue="Published Journal",
            type="preprint",
            registries=["arxiv"],
        )
        report = self.lint(verify=True)
        self.assertIn("preprint-publication-review", self.codes(report))

    def test_malformed_registry_provenance_cannot_certify_publication(
        self,
    ) -> None:
        self.write_article(
            doi=None,
            eprint="2201.00001",
            archiveprefix="arXiv",
            journal="arXiv e-prints",
        )
        self.record.update(
            input="arxiv:2201.00001",
            id="doi:10.1234/published",
            ids={"arxiv": "2201.00001", "doi": "10.1234/published"},
            venue="Published Journal",
            type="preprint",
        )
        for registries in (17, {"arxiv": True}, "arxiv"):
            with self.subTest(registries=registries):
                self.record["registries"] = registries
                report = self.lint(verify=True)
                self.assertNotIn(
                    "preprint-publication-review", self.codes(report)
                )
                self.assertFalse(report["comparison_complete"])
                self.assertFalse(report["advisory_clean"])

    def test_lookup_exception_is_advisory_not_identity_evidence(self) -> None:
        with unittest.mock.patch.object(
            SERVER, "_resolve_many", side_effect=RuntimeError("registry outage")
        ):
            report = self.lint(verify=True)
        self.assertTrue(report["ok"], report)
        self.assertFalse(report["comparison_complete"])
        self.assertIn("registry-comparison-unavailable", self.codes(report))
        self.assertFalse(report["advisory_clean"])

    def test_malformed_lookup_rows_fail_closed(self) -> None:
        for rows in (
            None,
            [],
            [None],
            [{"resolved": True}],
            [dict(self.record, id="not-a-canonical-identifier")],
            [dict(self.record, year={"invalid": True})],
        ):
            with (
                self.subTest(rows=rows),
                unittest.mock.patch.object(
                    SERVER, "_resolve_many", return_value=rows
                ),
            ):
                report = self.lint(verify=True)
                self.assertFalse(report["advisory_clean"], report)
                self.assertFalse(report["comparison_complete"])
                self.assertFalse(report["submission_ready"])

    def test_source_change_during_lookup_invalidates_advice(self) -> None:
        def changed(identifiers: list[str]) -> list[dict[str, Any]]:
            self.bib.write_bytes(self.bib.read_bytes() + b"\n% concurrent edit")
            return self.resolve(identifiers)

        with unittest.mock.patch.object(
            SERVER, "_resolve_many", side_effect=changed
        ):
            report = self.lint(verify=True)
        self.assertFalse(report["ok"], report)
        self.assertFalse(report["input_complete"])
        self.assertFalse(report["advisory_clean"])
        self.assertFalse(report["submission_ready"])
        self.assertIn("stale", report["error"].lower())


if __name__ == "__main__":
    unittest.main()
