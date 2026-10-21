"""Additional manuscript formats preserve scope, identities and uncertainty."""

import collections.abc
import contextlib
import hashlib
import importlib.util
import pathlib
import tempfile
from typing import Any
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER
PYPDF: Any = (
    importlib.import_module("pypdf")
    if importlib.util.find_spec("pypdf") is not None
    else None
)
PDF_GENERIC: Any = importlib.import_module("pypdf.generic") if PYPDF else None


class InputFixture(unittest.TestCase):
    """Create isolated bibliography, source evidence and registry fixtures."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.path = self.root / "main.md"
        self.bib = self.root / "refs.bib"
        self.source = self.root / "evidence.txt"
        self.source.write_text(
            "The measurement rises by ten percent. "
            "The rate falls by five percent.",
            encoding="utf-8",
        )
        self.record = {"doi": "10.1234/example", "title": "Example"}
        self.metadata = {
            "id": "doi:10.1234/example",
            "basis": "fulltext",
            "path": str(self.source),
            "intake": test_evidence.source_intake(self.source),
            "source": "local:evidence.txt",
        }
        self.bib.write_text(
            "\n".join(
                test_evidence.official_bib_fixture(
                    f"@article{{{key},title={{Example}},"
                    "doi={10.1234/example},author={Doe, Jane},year={2020}}",
                    self.record, self.bib,
                ) for key in ("a", "b")
            ),
            encoding="utf-8",
        )
        for name, options in (
            ("_full_record", {"return_value": self.record}),
            ("_with_pin", {"side_effect": lambda record, *_: record}),
            ("_load_text_meta", {"return_value": self.metadata}),
            ("verify_bib", {"side_effect": self.verify}),
        ):
            patch = unittest.mock.patch.object(SERVER, name, **options)
            patch.start()
            self.addCleanup(patch.stop)

    def verify(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Return canonical own-ID records for selected fixture keys."""
        del args
        return {
            "entries": [
                {
                    "key": key,
                    "status": "VERIFIED",
                    "id": self.metadata["id"],
                    "ids": {"doi": "10.1234/example"},
                }
                for key in kwargs.get("keys", ["a", "b"])
            ]
        }

    def extract(self, text: str | None = None) -> dict[str, Any]:
        """Write optional UTF-8 source and extract its citation instances."""
        if text is not None:
            self.path.write_bytes(text.encode("utf-8"))
        return SERVER.extract_cites(str(self.path))

    def audit(self, **options: Any) -> dict[str, Any]:
        """Audit the current format with a real bibliography and ledger."""
        return SERVER.audit(str(self.path), str(self.bib), **options)

    def support_all(self) -> dict[str, Any]:
        """Register complete sentences and record source-bound support."""
        extracted = self.extract()
        self.assertTrue(extracted["complete"], extracted)
        for sentence in extracted["sentences"]:
            registration = SERVER.register_claims(
                str(self.path),
                sentence["sentence_id"],
                [
                    {
                        "start": 0,
                        "end": len(sentence["claim"]),
                        "citation_ids": sentence["citation_ids"],
                    }
                ],
            )
            self.assertTrue(registration["ok"], registration)
            for cite in extracted["cites"]:
                if cite["sentence_id"] != sentence["sentence_id"]:
                    continue
                recorded = SERVER.record_support(
                    str(self.root),
                    cite["key"],
                    cite["claim"],
                    "SUPPORTS",
                    "example",
                    context=cite["context"],
                    quotes=[self.source.read_text(encoding="utf-8")],
                    judge="independent-fixture-reader",
                    tex_path=str(self.path),
                    occurrence_id=cite["occurrence_id"],
                    atom_id=registration["atoms"][0]["atom_id"],
                )
                self.assertTrue(recorded["recorded"], recorded)
        return self.audit()

    def register(self, mappings: list[dict[str, Any]]) -> dict[str, Any]:
        """Register explicit observed markers without asserting completeness."""
        return SERVER.register_input(
            str(self.path),
            mappings,
            reason="The author mapped these observed citation markers.",
        )

    def map_marker(
        self, text: str, marker: str, key: str = "a"
    ) -> dict[str, Any]:
        """Build an exact character-span mapping for text input."""
        start = text.index(marker)
        return {
            "start": start,
            "end": start + len(marker),
            "key": key,
            "marker": marker,
        }


class TextManuscriptInputsTest(InputFixture):
    """Exercise explicit text keys, unknown syntax and manual input mappings."""

    def test_native_markdown_repeated_keys_preserve_exact_source_spans(
        self,
    ) -> None:
        text = "α measurement rises [@a; @b].\r\n\r\nIt rises [@a].\r\n"
        extracted = self.extract(text)
        self.assertTrue(extracted["complete"], extracted)
        self.assertTrue(extracted["scope_complete"])
        self.assertFalse(extracted["review_only"])
        self.assertEqual(extracted["n_instances"], 3)
        self.assertEqual(extracted["keys"], ["a", "b"])
        self.assertEqual(
            len({cite["occurrence_id"] for cite in extracted["cites"]}), 3
        )
        raw = text.encode("utf-8")
        self.assertEqual(
            extracted["source_digests"][str(self.path)],
            hashlib.sha256(raw).hexdigest(),
        )
        for cite in extracted["cites"]:
            self.assertEqual(
                text[cite["source_start"] : cite["source_end"]],
                cite["source_command"],
            )
            self.assertEqual(
                raw[cite["source_byte_start"] : cite["source_byte_end"]],
                cite["source_command"].encode("utf-8"),
            )
        self.assertEqual(extracted["cites"][-1]["line"], 3)

    def test_native_markdown_and_text_use_existing_atomic_strict_gate(
        self,
    ) -> None:
        for suffix in (".md", ".markdown", ".txt"):
            with self.subTest(suffix=suffix):
                self.path = self.root / ("main" + suffix)
                self.extract("The measurement rises [@a].")
                report = self.support_all()
                self.assertTrue(report["input_complete"], report)
                self.assertTrue(report["complete"], report)
                self.assertTrue(report["submission_ready"], report)
                self.assertEqual(report["support_counts"], {"SUPPORTS": 1})

    def test_code_comments_urls_and_math_do_not_create_citation_instances(
        self,
    ) -> None:
        text = (
            "`[@inline]`\n\n"
            "```python\nvalue = '[@fenced]'\n```\n\n"
            "<!-- [@comment] and [99] -->\n\n"
            "https://example.org/[@url]\n\n"
            "$x=[@math]$\n\n"
            "The measurement rises [@a].\n"
        )
        extracted = self.extract(text)
        self.assertTrue(extracted["complete"], extracted)
        self.assertTrue(extracted["scope_complete"], extracted)
        self.assertEqual(extracted["keys"], ["a"])
        self.assertEqual(extracted["n_instances"], 1)

    def test_scientific_math_survives_claim_extraction(self) -> None:
        extracted = self.extract("The value is $x=-1$ and $y=+2$ [@a].")
        self.assertEqual(extracted["n_instances"], 1)
        self.assertIn("$x=-1$", extracted["cites"][0]["claim"])
        self.assertIn("$y=+2$", extracted["cites"][0]["claim"])

    def test_inline_code_wording_survives_claim_extraction(self) -> None:
        extracted = self.extract(
            "The option `mode=fast` raises throughput by ten percent [@a]."
        )
        self.assertEqual(extracted["keys"], ["a"])
        self.assertIn("`mode=fast`", extracted["cites"][0]["claim"])

    def test_narrative_explicit_keys_exclude_sentence_punctuation(self) -> None:
        extracted = self.extract("The measurement rises @a, and it rises @b.")
        self.assertTrue(extracted["scope_complete"], extracted)
        self.assertEqual(extracted["keys"], ["a", "b"])
        self.assertEqual(
            [cite["source_command"] for cite in extracted["cites"]],
            ["@a", "@b"],
        )

    def test_year_bearing_explicit_keys_have_known_scope(self) -> None:
        for marker, keys in (
            ("[@Smith2020]", ["Smith2020"]),
            ("[@first2020; @second2021]", ["first2020", "second2021"]),
        ):
            with self.subTest(marker=marker):
                extracted = self.extract(f"The measurement rises {marker}.")
                self.assertTrue(extracted["complete"], extracted)
                self.assertTrue(extracted["scope_complete"], extracted)
                self.assertFalse(extracted["review_only"], extracted)
                self.assertEqual(extracted["keys"], keys)
                self.assertEqual(extracted["diagnostics"], [])

    def test_code_fence_with_trailing_text_does_not_end_exclusion(self) -> None:
        extracted = self.extract(
            "```markdown\ncode\n```still code\n[@hidden]\n```\n\n"
            "The measurement rises [@a]."
        )
        self.assertEqual(extracted["keys"], ["a"])
        self.assertTrue(extracted["scope_complete"], extracted)

    def test_unknown_numeric_and_author_year_scope_cannot_be_zero_pass(
        self,
    ) -> None:
        for text in (
            "The measurement rises [1].",
            "The measurement rises (Smith, 2020).",
            "The measurement rises (Smith 2020).",
            "The measurement rises (Smith, 2020.",
            "The measurement rises [Smith, 2020.",
            "Smith (2020) measured this rise.",
            "Smith et al. (2020) measured this rise.",
            "The measurement rises [1, 2].",
            "The measurement rises [1–3].",
        ):
            with self.subTest(text=text):
                extracted = self.extract(text)
                self.assertFalse(extracted["scope_complete"], extracted)
                self.assertTrue(extracted["diagnostics"])
                report = self.audit()
                self.assertFalse(report["input_complete"], report)
                self.assertFalse(report["complete"])
                self.assertFalse(report["submission_ready"])
                self.assertIsNone(report["coverage"]["existence"]["expected"])
                self.assertEqual(
                    report["coverage"]["existence"]["observed_expected"], 0
                )

    def test_reference_link_labels_are_not_silently_hidden(self) -> None:
        for text in (
            "The measurement rises [1](#reference-one).",
            "The measurement rises [Smith (2020)](https://example.org/work).",
        ):
            with self.subTest(text=text):
                extracted = self.extract(text)
                self.assertFalse(
                    extracted.get("scope_complete", False), extracted
                )
                self.assertTrue(extracted.get("diagnostics"), extracted)
                self.assertFalse(self.audit()["submission_ready"])

    def test_malformed_native_marker_leaves_unknown_scope(self) -> None:
        for text in ("Result [@a.", "Result [@].", "Result [@a;]."):
            with self.subTest(text=text):
                extracted = self.extract(text)
                self.assertFalse(
                    extracted.get("scope_complete", False), extracted
                )
                self.assertFalse(self.audit()["submission_ready"])

    def test_explicit_keys_do_not_hide_other_uncertain_citations(self) -> None:
        extracted = self.extract("Known result [@a]. Other result [7].")
        self.assertEqual(extracted["keys"], ["a"])
        self.assertFalse(extracted["scope_complete"])
        report = self.audit()
        self.assertFalse(report["submission_ready"])
        self.assertIsNone(report["coverage"]["existence"]["expected"])
        self.assertEqual(
            report["coverage"]["existence"]["observed_expected"], 1
        )

    def test_ordinary_citation_free_text_has_known_empty_scope(self) -> None:
        extracted = self.extract("This introduction contains no citations.")
        self.assertTrue(extracted["scope_complete"], extracted)
        self.assertEqual(extracted["n_instances"], 0)
        report = self.audit()
        self.assertTrue(report["submission_ready"], report)
        self.assertEqual(report["coverage"]["existence"]["expected"], 0)

    def test_numeric_mapping_creates_observed_occurrence_but_not_readiness(
        self,
    ) -> None:
        text = "The measurement rises [1]."
        self.extract(text)
        mapped = self.register([self.map_marker(text, "[1]")])
        self.assertTrue(mapped["registered"], mapped)
        extracted = self.extract()
        self.assertEqual(extracted["keys"], ["a"])
        self.assertTrue(extracted["review_only"])
        report = self.support_all()
        self.assertFalse(report["submission_ready"], report)
        self.assertEqual(report["support_counts"], {"SUPPORTS": 1})

    def test_same_exact_marker_can_explicitly_map_to_multiple_keys(
        self,
    ) -> None:
        text = "The measurement rises [1, 2]."
        self.extract(text)
        first = self.map_marker(text, "[1, 2]")
        result = self.register([first, dict(first, key="b")])
        self.assertTrue(result["registered"], result)
        extracted = self.extract()
        self.assertEqual(extracted["keys"], ["a", "b"])
        self.assertEqual(extracted["n_instances"], 2)
        self.assertEqual(
            len({cite["occurrence_id"] for cite in extracted["cites"]}), 2
        )

    def test_invalid_mapping_shapes_and_exact_spans_are_refused(self) -> None:
        text = "The measurement rises [1]."
        self.extract(text)
        mapping = self.map_marker(text, "[1]")
        for value in (
            dict(mapping, start=True),
            dict(mapping, end=-1),
            dict(mapping, end=len(text) + 1),
            dict(mapping, marker="[2]"),
            dict(mapping, page=1),
            dict(mapping, key=""),
            dict(mapping, unexpected="value"),
        ):
            with self.subTest(value=value):
                result = self.register([value])
                self.assertFalse(result["registered"], result)
        self.assertFalse(
            SERVER.register_input(str(self.path), [mapping], "short")[
                "registered"
            ]
        )

    def test_duplicate_partial_overlap_and_native_override_are_refused(
        self,
    ) -> None:
        text = "The measurement rises [1, 2]."
        self.extract(text)
        mapping = self.map_marker(text, "[1, 2]")
        partial = dict(mapping, key="b", end=mapping["end"] - 1, marker="[1, 2")
        for values in ([mapping, mapping], [mapping, partial]):
            with self.subTest(values=values):
                self.assertFalse(self.register(values)["registered"])
        native = "The measurement rises [@a]."
        self.extract(native)
        self.assertFalse(
            self.register([self.map_marker(native, "[@a]", "b")])["registered"]
        )

    def test_source_edit_stales_manual_mapping(self) -> None:
        text = "The measurement rises [1]."
        self.extract(text)
        result = self.register([self.map_marker(text, "[1]")])
        self.assertTrue(result["registered"], result)
        self.path.write_text("Changed context. " + text, encoding="utf-8")
        extracted = self.extract()
        self.assertFalse(extracted.get("scope_complete", False), extracted)
        self.assertNotIn("a", extracted.get("keys", []))
        self.assertFalse(self.audit()["submission_ready"])

    def test_mapping_manifest_change_invalidates_verification_job(self) -> None:
        self.extract("The measurement rises [@a].")
        job = SERVER.verification_job(
            str(self.path), bib_path=str(self.bib), budget={"max_requests": 0}
        )
        self.assertTrue(job["ok"], job)
        self.assertTrue(self.register([])["registered"])
        resumed = SERVER.verification_job(str(self.path), job_id=job["job_id"])
        self.assertFalse(resumed["ok"], resumed)
        self.assertTrue(resumed["rescan_required"])

    def test_mapping_manifest_revision_stales_existing_support(self) -> None:
        text = "The measurement rises [1]."
        self.extract(text)
        mapping = self.map_marker(text, "[1]")
        self.assertTrue(self.register([mapping])["registered"])
        self.assertEqual(self.support_all()["support_counts"], {"SUPPORTS": 1})
        revised = SERVER.register_input(
            str(self.path),
            [mapping],
            reason="A later independent pass confirmed this explicit mapping.",
        )
        self.assertTrue(revised["registered"], revised)
        report = self.audit()
        self.assertEqual(report.get("support_counts", {}).get("SUPPORTS", 0), 0)
        self.assertFalse(report["submission_ready"])

    def test_corrupt_mapping_manifest_fails_closed(self) -> None:
        text = "The measurement rises [1]."
        self.extract(text)
        result = self.register([self.map_marker(text, "[1]")])
        self.assertTrue(result["registered"], result)
        pathlib.Path(result["manifest_path"]).write_text(
            "{invalid", encoding="utf-8"
        )
        extracted = self.extract()
        self.assertFalse(extracted.get("scope_complete", False), extracted)
        self.assertFalse(self.audit()["submission_ready"])

    def test_oversized_mapping_replacement_preserves_saved_input(self) -> None:
        text = "The measurement rises [1]."
        self.extract(text)
        mapping = self.map_marker(text, "[1]")
        saved = self.register([mapping])
        self.assertTrue(saved["registered"], saved)
        manifest = pathlib.Path(saved["manifest_path"])
        manifest_before = manifest.read_bytes()
        source_before = self.path.read_bytes()
        rejected = SERVER.register_input(
            str(self.path), [mapping], reason="x" * (1024 * 1024 + 1)
        )
        self.assertFalse(rejected["registered"], rejected)
        self.assertEqual(manifest.read_bytes(), manifest_before)
        self.assertEqual(self.path.read_bytes(), source_before)
        self.assertEqual(self.extract()["keys"], ["a"])

    def test_manifest_symlink_cannot_overwrite_source(self) -> None:
        text = "The measurement rises [1]."
        self.extract(text)
        result = self.register([self.map_marker(text, "[1]")])
        manifest = pathlib.Path(result["manifest_path"])
        manifest.unlink()
        manifest.symlink_to(self.path)
        before = self.path.read_bytes()
        refused = self.register([self.map_marker(text, "[1]")])
        self.assertFalse(refused["registered"], refused)
        self.assertEqual(self.path.read_bytes(), before)

    def test_symlinked_mapping_directory_is_refused_before_writes(self) -> None:
        text = "The measurement rises [1]."
        self.extract(text)
        destination = self.root / "elsewhere"
        destination.mkdir()
        (self.root / ".cite-check").rename(self.root / "original-cite-check")
        (self.root / ".cite-check").symlink_to(
            destination, target_is_directory=True
        )
        before = self.path.read_bytes()
        result = self.register([self.map_marker(text, "[1]")])
        self.assertFalse(result["registered"], result)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(destination.iterdir()), [])

    def test_manifest_lock_hardlink_preserves_unknown_sidecar(self) -> None:
        text = "The measurement rises [1]."
        self.extract(text)
        mapping = self.map_marker(text, "[1]")
        saved = self.register([mapping])
        self.assertTrue(saved["registered"], saved)
        manifest = pathlib.Path(saved["manifest_path"])
        manifest_before = manifest.read_bytes()
        sidecar = self.root / "unrelated.bib"
        sidecar.write_bytes(b"Important sidecar content remains unchanged.")
        sidecar_before = sidecar.read_bytes()
        lock = pathlib.Path(str(manifest) + ".lock")
        lock.unlink(missing_ok=True)
        lock.hardlink_to(sidecar)
        refused = self.register([mapping])
        self.assertFalse(refused["registered"], refused)
        self.assertEqual(sidecar.read_bytes(), sidecar_before)
        self.assertEqual(manifest.read_bytes(), manifest_before)
        self.assertEqual(self.path.read_bytes(), text.encode("utf-8"))

    def test_markdown_annotation_preserves_and_escapes_source(self) -> None:
        text = "The <script>alert(1)</script> measurement rises [@a]."
        self.extract(text)
        before = self.path.read_bytes()
        result = SERVER.correction_report(
            str(self.path), str(self.bib), annotated=True
        )
        self.assertTrue(result["report_written"], result)
        rendered = (self.root / ".cite-check" / "corrections.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>alert", rendered)
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_utf8_text_is_not_replacement_decoded(self) -> None:
        self.path.write_bytes(b"Claim [@a].\xff")
        extracted = self.extract()
        self.assertFalse(extracted.get("complete", False), extracted)
        self.assertFalse(self.audit()["submission_ready"])

    def test_printed_text_references_cannot_be_certified_by_same_key_sidecar(
        self,
    ) -> None:
        references = [
            "[@a]: An unrelated printed work, DOI 10.9999/unrelated.",
            "[a]: An unrelated printed work, DOI 10.9999/unrelated.",
            "[@a]: https://doi.org/10.9999/unrelated",
            "[a]: https://doi.org/10.9999/unrelated",
            "## References\n\n"
            "An unrelated printed work, DOI 10.9999/unrelated.",
        ]
        references.extend(
            f"---\n{key}:\n  - id: a\n"
            "    title: An unrelated printed work\n"
            "    DOI: 10.9999/unrelated\n---\n"
            for key in ("references", '"references"', "'references'")
        )
        for reference in references:
            with self.subTest(reference=reference):
                prose = "The measurement rises [@a].\n\n"
                extracted = self.extract(
                    reference + prose
                    if reference.startswith("---\n")
                    else prose + reference
                )
                self.assertTrue(extracted["review_only"], extracted)
                self.assertTrue(extracted["inline_bibliography"], extracted)
                self.assertEqual(extracted["n_instances"], 1)
                self.assertTrue(
                    any(
                        "10.9999/unrelated" in entry["raw"]
                        for entry in extracted["inline_bibliography"]
                    )
                )
                report = self.support_all()
                self.assertFalse(report["submission_ready"], report)

    def test_unused_url_definition_does_not_become_a_bibliography(self) -> None:
        extracted = self.extract(
            "The measurement rises [@a].\n\n"
            "[home]: https://example.org/project\n"
        )
        self.assertEqual(extracted["keys"], ["a"])
        self.assertTrue(extracted["scope_complete"], extracted)
        self.assertFalse(extracted["review_only"], extracted)
        self.assertEqual(extracted["inline_bibliography"], [])
        self.assertTrue(self.support_all()["submission_ready"])


class InlineBibliographyInputsTest(InputFixture):
    """Inline reference prose stays distinguishable from official exports."""

    def setUp(self) -> None:
        super().setUp()
        self.path = self.root / "main.tex"

    def test_inline_records_have_exact_spans_and_are_not_claims(self) -> None:
        text = (
            "% α heading\r\n\\begin{document}\r\n"
            "The measurement rises \\cite{a}.\r\n"
            "\\begin{thebibliography}{9}\r\n"
            "\\bibitem{a} Different reference prose with \\cite{b}.\r\n"
            "\\end{thebibliography}\r\n\\end{document}\r\n"
        )
        extracted = self.extract(text)
        self.assertTrue(extracted["complete"], extracted)
        self.assertTrue(extracted["review_only"])
        self.assertEqual(extracted["keys"], ["a"])
        self.assertEqual(len(extracted["inline_bibliography"]), 1)
        entry = extracted["inline_bibliography"][0]
        self.assertEqual(entry["key"], "a")
        self.assertEqual(entry["kind"], "inline-bibliography-entry")
        self.assertEqual(entry["file"], str(self.path))
        self.assertEqual(entry["line"], 5)
        self.assertEqual(text[entry["start"] : entry["end"]], entry["raw"])
        raw = text.encode("utf-8")
        self.assertEqual(
            raw[entry["source_byte_start"] : entry["source_byte_end"]],
            entry["raw"].encode("utf-8"),
        )
        self.assertNotIn("Different reference", extracted["cites"][0]["claim"])

    def test_valid_same_key_sidecar_cannot_certify_different_inline_reference(
        self,
    ) -> None:
        self.extract(
            "The measurement rises \\cite{a}.\n"
            "\\begin{thebibliography}{9}\n"
            "\\bibitem{a} An unrelated reference written by hand.\n"
            "\\end{thebibliography}"
        )
        report = self.support_all()
        self.assertFalse(report["submission_ready"], report)
        self.assertTrue(
            any("inline" in str(item) for item in report["failures"]), report
        )

    def test_duplicate_and_unterminated_inline_blocks_remain_uncertain(
        self,
    ) -> None:
        for text in (
            "Result \\cite{a}. \\begin{thebibliography}{9}\\bibitem{a} First."
            "\\bibitem{a} Second.\\end{thebibliography}",
            "Result \\cite{a}. \\begin{thebibliography}{9}\\bibitem{a} First.",
            "Result \\cite{a}. \\begin{thebibliography}{9}\\bibitem a First."
            "\\end{thebibliography}",
            "Result \\cite{a}. \\begin{thebibliography}{9}\\bibitem{a} First."
            "\\bibitem b Second.\\end{thebibliography}",
        ):
            with self.subTest(text=text):
                extracted = self.extract(text)
                self.assertFalse(
                    extracted.get("scope_complete", False), extracted
                )
                self.assertFalse(self.audit()["submission_ready"])


@unittest.skipUnless(PYPDF is not None, "pypdf manuscript dependency missing")
class PdfManuscriptInputsTest(InputFixture):
    """Use original tiny PDF fixtures, including real extraction workers."""

    def setUp(self) -> None:
        super().setUp()
        self.path = self.root / "main.pdf"

    def write_pdf(self, pages: list[str], encrypted: bool = False) -> None:
        """Write original Helvetica text streams through pypdf only."""
        writer = PYPDF.PdfWriter()
        for text in pages:
            page = writer.add_blank_page(width=400, height=300)
            font = PDF_GENERIC.DictionaryObject(
                {
                    PDF_GENERIC.NameObject("/Type"): PDF_GENERIC.NameObject(
                        "/Font"
                    ),
                    PDF_GENERIC.NameObject("/Subtype"): PDF_GENERIC.NameObject(
                        "/Type1"
                    ),
                    PDF_GENERIC.NameObject("/BaseFont"): PDF_GENERIC.NameObject(
                        "/Helvetica"
                    ),
                }
            )
            page[PDF_GENERIC.NameObject("/Resources")] = (
                PDF_GENERIC.DictionaryObject(
                    {
                        PDF_GENERIC.NameObject(
                            "/Font"
                        ): PDF_GENERIC.DictionaryObject(
                            {
                                PDF_GENERIC.NameObject("/F1"): font,
                            }
                        ),
                    }
                )
            )
            escaped = (
                text.replace("\\", "\\\\")
                .replace("(", "\\(")
                .replace(")", "\\)")
            )
            stream = PDF_GENERIC.DecodedStreamObject()
            stream.set_data(
                f"BT /F1 12 Tf 20 260 Td ({escaped}) Tj ET".encode("ascii")
            )
            page[PDF_GENERIC.NameObject("/Contents")] = writer._add_object(
                stream
            )
        if encrypted:
            writer.encrypt("private-fixture")
        with self.path.open("wb") as output:
            writer.write(output)

    @contextlib.contextmanager
    def extractor(
        self, result: dict[str, Any]
    ) -> collections.abc.Iterator[None]:
        """Model a matching installed extractor and its page-text response."""
        with (
            unittest.mock.patch.object(
                SERVER, "_input_pdf_extract", return_value=result
            ),
            unittest.mock.patch.object(
                SERVER, "_input_pdf_backend", return_value=result["extractor"]
            ),
        ):
            yield

    def test_pdf_pages_preserve_occurrences_without_binary_offsets(
        self,
    ) -> None:
        self.write_pdf(["The measurement rises [@a].", "The rate falls [@a]."])
        before = self.path.read_bytes()
        extracted = self.extract()
        self.assertTrue(extracted["complete"], extracted)
        self.assertEqual(extracted["input_format"], "pdf")
        self.assertTrue(extracted["review_only"])
        self.assertFalse(extracted["scope_complete"])
        self.assertEqual(extracted["n_instances"], 2)
        self.assertEqual([cite["page"] for cite in extracted["cites"]], [1, 2])
        self.assertEqual(
            len({cite["occurrence_id"] for cite in extracted["cites"]}), 2
        )
        for cite in extracted["cites"]:
            self.assertIsNone(cite["source_byte_start"])
            self.assertIsNone(cite["source_byte_end"])
            self.assertEqual(cite["source_command"], "[@a]")
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(
            extracted["source_digests"][str(self.path)],
            hashlib.sha256(before).hexdigest(),
        )

    def test_pdf_mapping_uses_page_local_text_offsets_and_is_review_only(
        self,
    ) -> None:
        pages = ["The measurement rises [1].", "The rate falls [2]."]
        self.write_pdf(pages)
        mappings = [
            dict(self.map_marker(text, f"[{index}]"), page=index)
            for index, text in enumerate(pages, 1)
        ]
        result = self.register(mappings)
        self.assertTrue(result["registered"], result)
        extracted = self.extract()
        self.assertEqual(extracted["n_instances"], 2)
        self.assertEqual([cite["page"] for cite in extracted["cites"]], [1, 2])
        report = self.support_all()
        self.assertFalse(report["submission_ready"], report)
        self.assertFalse(report["input_complete"])
        self.assertEqual(report["support_counts"], {"SUPPORTS": 2})

    def test_pdf_mapping_requires_real_page_and_exact_marker(self) -> None:
        text = "The measurement rises [1]."
        self.write_pdf([text])
        mapping = self.map_marker(text, "[1]")
        for value in (
            mapping,
            dict(mapping, page=0),
            dict(mapping, page=2),
            dict(mapping, page=True),
            dict(mapping, page=1, marker="[2]"),
        ):
            with self.subTest(value=value):
                self.assertFalse(self.register([value])["registered"])

    def test_pdf_extractor_fingerprint_change_stales_manual_mapping(
        self,
    ) -> None:
        text = "The measurement rises [1]."
        self.write_pdf([text])
        extraction: dict[str, Any] = {
            "pages": [{"page": 1, "text": text}],
            "extractor": {
                "name": "pypdf",
                "version": "fixture-v1",
                "policy": "fixture",
            },
        }
        with self.extractor(extraction):
            mapped = self.register([dict(self.map_marker(text, "[1]"), page=1)])
            self.assertTrue(mapped["registered"], mapped)
        changed = dict(
            extraction,
            extractor=dict(extraction["extractor"], version="fixture-v2"),
        )
        with self.extractor(changed):
            extracted = self.extract()
            self.assertNotIn("a", extracted.get("keys", []))
            self.assertFalse(self.audit()["submission_ready"])

    def test_pdf_page_text_change_stales_mapping_even_with_same_binary(
        self,
    ) -> None:
        text = "The measurement rises [1]."
        self.write_pdf([text])
        extraction: dict[str, Any] = {
            "pages": [{"page": 1, "text": text}],
            "extractor": {
                "name": "pypdf",
                "version": "fixture",
                "policy": "fixture",
            },
        }
        with self.extractor(extraction):
            mapped = self.register([dict(self.map_marker(text, "[1]"), page=1)])
            self.assertTrue(mapped["registered"], mapped)
        changed = dict(
            extraction, pages=[{"page": 1, "text": "Changed. " + text}]
        )
        with self.extractor(changed):
            extracted = self.extract()
            self.assertNotIn("a", extracted.get("keys", []))
            self.assertFalse(extracted.get("scope_complete", False))

    def test_pdf_extractor_revision_stales_native_key_judgments(self) -> None:
        text = "The measurement rises [@a]."
        self.write_pdf([text])
        extraction: dict[str, Any] = {
            "pages": [{"page": 1, "text": text}],
            "extractor": {
                "name": "pypdf",
                "version": "fixture-v1",
                "policy": "fixture",
            },
        }
        with self.extractor(extraction):
            self.assertEqual(
                self.support_all()["support_counts"], {"SUPPORTS": 1}
            )
        changed = dict(
            extraction,
            extractor=dict(extraction["extractor"], version="fixture-v2"),
        )
        with self.extractor(changed):
            report = self.audit()
        self.assertEqual(report.get("support_counts", {}).get("SUPPORTS", 0), 0)
        self.assertFalse(report["submission_ready"])

    def test_pdf_worker_metadata_must_match_installed_extractor(self) -> None:
        self.write_pdf(["The measurement rises [@a]."])
        wrong = {
            "pages": [{"page": 1, "text": "The measurement rises [@a]."}],
            "extractor": {"name": "unrecognized", "version": "invented"},
        }
        with unittest.mock.patch.object(
            SERVER, "_input_pdf_extract", return_value=wrong
        ):
            extracted = self.extract()
        self.assertFalse(extracted.get("complete", False), extracted)

    def test_blank_or_scanned_page_never_establishes_empty_clean_scope(
        self,
    ) -> None:
        self.write_pdf([""])
        extracted = self.extract()
        self.assertFalse(extracted.get("scope_complete", False), extracted)
        self.assertTrue(extracted.get("diagnostics") or extracted.get("error"))
        report = self.audit()
        self.assertFalse(report["submission_ready"])
        self.assertFalse(report["input_complete"])

    def test_encrypted_pdf_is_diagnostic_not_empty_success(self) -> None:
        self.write_pdf(["The measurement rises [@a]."], encrypted=True)
        before = self.path.read_bytes()
        extracted = self.extract()
        self.assertFalse(extracted.get("complete", False), extracted)
        self.assertTrue(extracted.get("error") or extracted.get("diagnostics"))
        self.assertFalse(self.audit()["submission_ready"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_truncated_and_oversized_pdf_fail_closed(self) -> None:
        for raw in (
            b"%PDF-1.7\ntruncated",
            b"%PDF-1.7\n" + b" " * (20 * 1024 * 1024),
        ):
            with self.subTest(size=len(raw)):
                self.path.write_bytes(raw)
                extracted = self.extract()
                self.assertFalse(extracted.get("complete", False), extracted)
                self.assertFalse(self.audit()["submission_ready"])

    def test_pdf_annotated_copy_renders_extracted_pages_without_changing_binary(
        self,
    ) -> None:
        self.write_pdf(
            ["The <script>alert(1)</script> result [@a].", "More text [@b]."]
        )
        before = self.path.read_bytes()
        report = SERVER.correction_report(
            str(self.path), str(self.bib), annotated=True
        )
        self.assertTrue(report["report_written"], report)
        rendered = (self.root / ".cite-check" / "corrections.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("&lt;script&gt;", rendered)
        self.assertNotIn("<script>alert", rendered)
        self.assertIn("More text", rendered)
        self.assertFalse(report["submission_ready"])
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
