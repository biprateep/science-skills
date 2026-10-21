"""Export receipts detect edits without treating hashes as authority."""

import hashlib
import importlib
import json
import pathlib
import shutil
import tempfile
from typing import Any
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER
BIBLIOGRAPHY = importlib.import_module("cite_check_engine.bibliography")
PARSING = importlib.import_module("cite_check_engine.parsing")
PERSISTENCE = importlib.import_module("cite_check_engine.persistence")
RESOLUTION = importlib.import_module("cite_check_engine.resolution")
TRANSPORT = importlib.import_module("cite_check_engine.transport")
DOI = "doi:10.1234/provenance-fixture"
RAW_EXPORT = """@article{Registry_2020,
 title = {A measured &amp; calibrated relation},
 author = {Example, Jane},
 year = {2020},
 month = {September},
 doi = {10.1234/provenance-fixture},
 journal = {Fixture Journal}
}
"""


class ProvenanceFixture(unittest.TestCase):
    """Exercise the actual export and receipt path with an offline registry."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = pathlib.Path(self.temporary.name)
        self.cache = self.root / "cache"
        self.bib = self.root / "references.bib"
        self.manuscript = self.root / "main.tex"
        self.manuscript.write_text(r"\nocite{paper}", encoding="utf-8")
        self.record = SERVER._record(
            registry="crossref",
            doi=DOI.removeprefix("doi:"),
            title="A measured & calibrated relation",
            authors=["Example, Jane"],
            year=2020,
            venue="Fixture Journal",
        )
        for owner, name, options in (
            (SERVER, "CACHE_DIR", {"new": str(self.cache)}),
            (RESOLUTION, "_full_record", {"return_value": self.record}),
            (RESOLUTION, "_resolve_many", {"side_effect": self.resolved}),
            (SERVER, "_ads_token", {"return_value": None}),
            (PERSISTENCE, "_now_iso", {"return_value": "2026-10-21T01:00:00Z"}),
            (PERSISTENCE, "_today", {"return_value": "2026-10-20"}),
            (TRANSPORT, "_http", {"side_effect": self.export_response}),
        ):
            patch: Any = unittest.mock.patch.object(owner, name, **options)
            patch.start()
            self.addCleanup(patch.stop)

    def resolved(self, identifiers: list[str]) -> list[dict[str, Any]]:
        """Return authoritative identity data without a provenance verdict."""
        return [
            SERVER._public(self.record, value, "crossref")
            for value in identifiers
        ]

    def export_response(self, url: str, **_options: Any) -> tuple[int, str]:
        """Serve only the expected official export endpoint offline."""
        if not url.startswith(
            "https://api.crossref.org/works/"
        ) or not url.endswith("/transform/application/x-bibtex"):
            raise AssertionError("unexpected registry request")
        return 200, RAW_EXPORT

    def add(self, key: str = "paper", replace: bool = False) -> dict[str, Any]:
        """Use the real official export and bibliography transaction."""
        result = SERVER.bib_add(
            str(self.bib),
            [{"identifier": DOI, "key": key}],
            prefer=["crossref"],
            replace=replace,
        )
        self.assertTrue(result["ok"], result)
        return result

    def entry(self, key: str = "paper") -> dict[str, Any]:
        """Read the exact entry currently cited by the manuscript."""
        return PARSING._parse_bib(self.bib.read_text())["keys"][key]

    def check(self) -> dict[str, Any]:
        """Check the current entry independently of identity resolution."""
        entries = PARSING._parse_bib(self.bib.read_text())["entries"]
        return BIBLIOGRAPHY._check_export_provenance(entries[0], str(self.bib))

    def paths(self, result: dict[str, Any]) -> list[pathlib.Path]:
        """Return the documented local and global receipt candidates."""
        provenance = importlib.import_module(
            "cite_check_engine.export_provenance"
        )
        return [
            pathlib.Path(value)
            for value in provenance.candidate_paths(
                result["results"][0]["export_provenance"]["receipt"],
                str(self.bib),
            )
        ]

    def audit(self, policy: str = "submission-ready") -> dict[str, Any]:
        """Run real existence/provenance checks with no support requirement."""
        return SERVER.audit(str(self.manuscript), str(self.bib), policy=policy)


class OfficialExportTest(ProvenanceFixture):
    """Issue receipts through validated official-export transformations."""

    def test_official_raw_and_final_entry_have_distinct_exact_digests(
        self,
    ) -> None:
        result = SERVER.fetch_bibtex(DOI, key="paper", prefer=["crossref"])
        self.assertTrue(result["bibtex"], result)
        provenance = result["export_provenance"]
        self.assertEqual(provenance["policy"], "official-export-v1")
        self.assertEqual(
            provenance["raw_sha256"],
            hashlib.sha256(RAW_EXPORT.encode()).hexdigest(),
        )
        self.assertEqual(
            provenance["entry_sha256"],
            hashlib.sha256(result["bibtex"].encode()).hexdigest(),
        )
        self.assertNotEqual(
            provenance["raw_sha256"], provenance["entry_sha256"]
        )
        self.assertIn(r"measured \& calibrated", result["bibtex"])
        self.assertIn("= sep", result["bibtex"])
        self.assertIn("{paper,", result["bibtex"])
        self.assertTrue(pathlib.Path(provenance["path"]).is_file())
        self.assertIn(provenance["receipt"], result["provenance"])

    def test_bib_add_copies_receipt_beside_bibliography(self) -> None:
        result = self.add()
        paths = self.paths(result)
        self.assertEqual(len(paths), 2)
        self.assertEqual(paths[0].parent, self.root / ".cite-check" / "exports")
        self.assertTrue(all(path.is_file() for path in paths))
        self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())
        self.assertEqual(self.check()["status"], "VERIFIED")
        self.assertEqual(
            self.entry()["provenance"]["entry_sha256"],
            hashlib.sha256(self.entry()["raw"].encode()).hexdigest(),
        )

    def test_tool_requested_renaming_gets_a_new_valid_entry_receipt(
        self,
    ) -> None:
        first = SERVER.fetch_bibtex(DOI, key="one", prefer=["crossref"])
        second = SERVER.fetch_bibtex(DOI, key="two", prefer=["crossref"])
        self.assertEqual(
            first["export_provenance"]["raw_sha256"],
            second["export_provenance"]["raw_sha256"],
        )
        self.assertNotEqual(
            first["export_provenance"]["entry_sha256"],
            second["export_provenance"]["entry_sha256"],
        )
        self.assertNotEqual(
            first["export_provenance"]["receipt"],
            second["export_provenance"]["receipt"],
        )
        self.bib.write_text(second["provenance"] + "\n" + second["bibtex"])
        self.assertEqual(self.check()["status"], "VERIFIED")

    def test_wrong_identifier_export_cannot_get_an_accepted_receipt(
        self,
    ) -> None:
        raw = RAW_EXPORT.replace(
            "10.1234/provenance-fixture", "10.1234/other-work"
        )
        with unittest.mock.patch.object(
            TRANSPORT, "_http", return_value=(200, raw)
        ):
            result = SERVER.fetch_bibtex(DOI, prefer=["crossref"])
        self.assertFalse(result.get("bibtex"), result)
        self.assertFalse(result.get("export_provenance"), result)

    def test_multiple_or_malformed_registry_entries_are_refused(self) -> None:
        for body in (
            RAW_EXPORT + RAW_EXPORT.replace("Registry_2020", "Second"),
            RAW_EXPORT[:-3],
        ):
            with self.subTest(body=body[-30:]):
                with unittest.mock.patch.object(
                    TRANSPORT, "_http", return_value=(200, body)
                ):
                    result = SERVER.fetch_bibtex(DOI, prefer=["crossref"])
                self.assertFalse(result.get("bibtex"), result)
                self.assertFalse(result.get("export_provenance"), result)

    def test_oversized_registry_export_is_not_given_a_receipt(self) -> None:
        provenance = importlib.import_module(
            "cite_check_engine.export_provenance"
        )
        with unittest.mock.patch.object(provenance, "MAX_EXPORT_BYTES", 64):
            result = SERVER.fetch_bibtex(DOI, prefer=["crossref"])
        self.assertFalse(result.get("bibtex"), result)
        self.assertFalse(result.get("export_provenance"), result)

    def test_registry_title_cannot_inject_provenance_comment_fields(
        self,
    ) -> None:
        suffix = "; source=datacite; id=doi:10.1234/injected"
        self.record["title"] += suffix
        raw = RAW_EXPORT.replace(
            "A measured &amp; calibrated relation",
            "A measured &amp; calibrated relation" + suffix,
        )
        with unittest.mock.patch.object(
            TRANSPORT, "_http", return_value=(200, raw)
        ):
            result = SERVER.fetch_bibtex(DOI, key="paper", prefer=["crossref"])
        self.assertTrue(result["bibtex"], result)
        self.bib.write_text(result["provenance"] + "\n" + result["bibtex"])
        provenance = self.entry()["provenance"]
        self.assertEqual(provenance["source"], "crossref")
        self.assertEqual(provenance["id"], DOI)
        self.assertEqual(self.check()["status"], "VERIFIED")

    def test_same_export_is_reproducible_without_artifact_churn(self) -> None:
        first = SERVER.fetch_bibtex(DOI, key="paper", prefer=["crossref"])
        path = pathlib.Path(first["export_provenance"]["path"])
        before = path.read_bytes()
        second = SERVER.fetch_bibtex(DOI, key="paper", prefer=["crossref"])
        self.assertEqual(
            first["export_provenance"], second["export_provenance"]
        )
        self.assertEqual(path.read_bytes(), before)


class EditedBibliographyTest(ProvenanceFixture):
    """Copying or updating checksum fields cannot certify manual edits."""

    def test_content_key_and_internal_formatting_edits_are_detected(
        self,
    ) -> None:
        self.add()
        original = self.bib.read_text()
        entry = self.entry()["raw"]
        changed = [
            entry.replace("measured", "fabricated"),
            entry.replace("2020", "2021"),
            entry.replace("10.1234/provenance-fixture", "10.1234/other-work"),
            entry.replace("{paper,", "{renamed,"),
            entry.replace(" = ", "  = ", 1),
            entry.replace("\n", "\r\n"),
        ]
        for replacement in changed:
            with self.subTest(replacement=replacement[:60]):
                self.bib.write_bytes(
                    original.replace(entry, replacement).encode()
                )
                # Preserve newlines while checking exact bibliography bytes.
                report = SERVER.verify_bib(str(self.bib))
                self.assertTrue(report["entries"], report)
                self.assertNotEqual(
                    BIBLIOGRAPHY._check_export_provenance(
                        PARSING._parse_bib(self.bib.read_bytes().decode())[
                            "entries"
                        ][0],
                        str(self.bib),
                    )["status"],
                    "VERIFIED",
                )
                self.assertFalse(self.audit()["submission_ready"])

    def test_outer_whitespace_does_not_change_the_exact_entry(self) -> None:
        self.add()
        self.bib.write_text("\n\n" + self.bib.read_text() + "\n\n")
        self.assertEqual(self.check()["status"], "VERIFIED")
        self.assertTrue(self.audit()["submission_ready"])

    def test_recomputing_only_comment_digest_cannot_certify_an_edit(
        self,
    ) -> None:
        self.add()
        entry = self.entry()
        changed = entry["raw"].replace("measured", "fabricated")
        old_digest = entry["provenance"]["entry_sha256"]
        new_digest = hashlib.sha256(changed.encode()).hexdigest()
        self.bib.write_text(
            self.bib.read_text()
            .replace(entry["raw"], changed)
            .replace(old_digest, new_digest)
        )
        self.assertNotEqual(self.check()["status"], "VERIFIED")
        self.assertFalse(self.audit()["submission_ready"])

    def test_source_or_identity_declaration_cannot_be_substituted(self) -> None:
        self.add()
        original = self.bib.read_text()
        for old, new in (
            ("source=crossref", "source=datacite"),
            ("id=" + DOI, "id=doi:10.1234/other-work"),
        ):
            with self.subTest(new=new):
                self.bib.write_text(original.replace(old, new, 1))
                self.assertNotEqual(self.check()["status"], "VERIFIED")

    def test_reexport_with_replace_restores_edited_bibliography(self) -> None:
        self.add()
        self.bib.write_text(
            self.bib.read_text().replace("measured", "fabricated")
        )
        self.assertNotEqual(self.check()["status"], "VERIFIED")
        replaced = self.add(replace=True)
        self.assertEqual(replaced["results"][0]["status"], "replaced")
        self.assertEqual(self.check()["status"], "VERIFIED")
        self.assertTrue(self.audit()["submission_ready"])

    def test_rehashed_receipt_still_requires_replaying_official_transforms(
        self,
    ) -> None:
        result = self.add()
        original_bib = self.bib.read_text()
        original_entry = self.entry()
        original_receipt = json.loads(self.paths(result)[0].read_bytes())
        for field in ("entry", "raw_export"):
            with self.subTest(field=field):
                payload = dict(original_receipt)
                payload[field] = payload[field].replace(
                    "measured", "fabricated"
                )
                digest_field = (
                    "entry_sha256" if field == "entry" else "raw_sha256"
                )
                payload[digest_field] = hashlib.sha256(
                    payload[field].encode()
                ).hexdigest()
                encoded = json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                ).encode()
                receipt = hashlib.sha256(encoded).hexdigest()
                path = self.paths(result)[0].parent / (receipt + ".json")
                path.write_bytes(encoded)
                changed = original_bib.replace(
                    original_entry["provenance"]["receipt"], receipt
                )
                changed = changed.replace(
                    original_receipt[digest_field], payload[digest_field]
                )
                if field == "entry":
                    changed = changed.replace(
                        original_entry["raw"], payload[field]
                    )
                self.bib.write_text(changed)
                self.assertNotEqual(self.check()["status"], "VERIFIED")
                self.assertFalse(self.audit()["submission_ready"])


class ReceiptArtifactsTest(ProvenanceFixture):
    """Receipt availability, content and final audit snapshots stay bound."""

    def test_missing_receipts_block_strict_readiness(self) -> None:
        result = self.add()
        for path in self.paths(result):
            path.unlink()
        self.assertEqual(self.check()["status"], "MISSING")
        self.assertFalse(self.audit()["submission_ready"])

    def test_corrupt_local_receipt_does_not_fall_back_to_good_global(
        self,
    ) -> None:
        result = self.add()
        local, global_path = self.paths(result)
        self.assertTrue(global_path.is_file())
        for corrupt in (b"{bad JSON", b"[]", b'"scalar"', b"{}"):
            with self.subTest(corrupt=corrupt):
                local.write_bytes(corrupt)
                self.assertNotEqual(self.check()["status"], "VERIFIED")
                self.assertFalse(self.audit()["submission_ready"])

    def test_receipt_for_another_entry_cannot_be_substituted(self) -> None:
        result = self.add()
        other = SERVER.fetch_bibtex(DOI, key="different", prefer=["crossref"])
        self.paths(result)[0].write_bytes(
            pathlib.Path(other["export_provenance"]["path"]).read_bytes()
        )
        self.assertNotEqual(self.check()["status"], "VERIFIED")
        self.assertFalse(self.audit()["submission_ready"])

    def test_project_receipts_remain_valid_without_original_global_cache(
        self,
    ) -> None:
        result = self.add()
        self.paths(result)[1].unlink()
        moved = self.root / "moved"
        moved.mkdir()
        shutil.copy2(self.bib, moved / "references.bib")
        shutil.copytree(
            self.root / ".cite-check" / "exports",
            moved / ".cite-check" / "exports",
        )
        moved_entry = PARSING._parse_bib(
            (moved / "references.bib").read_text()
        )["entries"][0]
        with unittest.mock.patch.object(
            SERVER, "CACHE_DIR", str(self.root / "empty-cache")
        ):
            checked = BIBLIOGRAPHY._check_export_provenance(
                moved_entry, str(moved / "references.bib")
            )
        self.assertEqual(checked["status"], "VERIFIED")

    def test_changed_receipt_during_audit_invalidates_final_success(
        self,
    ) -> None:
        result = self.add()
        local = self.paths(result)[0]
        findings = importlib.import_module("cite_check_engine.findings")
        original = findings._correction_items

        def changed(*args: Any, **kwargs: Any) -> Any:
            items = original(*args, **kwargs)
            local.write_text("{}", encoding="utf-8")
            return items

        with unittest.mock.patch.object(
            findings, "_correction_items", side_effect=changed
        ):
            report = self.audit()
        self.assertFalse(report["submission_ready"], report)
        self.assertFalse(report["complete"], report)
        self.assertIn(
            "audit-stale", {row["type"] for row in report["failures"]}
        )

    def test_appearing_local_receipt_invalidates_global_fallback_snapshot(
        self,
    ) -> None:
        result = self.add()
        local, _ = self.paths(result)
        local.unlink()
        self.assertEqual(self.check()["status"], "VERIFIED")
        findings = importlib.import_module("cite_check_engine.findings")
        original = findings._correction_items

        def appeared(*args: Any, **kwargs: Any) -> Any:
            items = original(*args, **kwargs)
            local.write_text("{}", encoding="utf-8")
            return items

        with unittest.mock.patch.object(
            findings, "_correction_items", side_effect=appeared
        ):
            report = self.audit()
        self.assertFalse(report["submission_ready"], report)
        self.assertFalse(report["complete"], report)
        self.assertIn(
            "audit-stale", {row["type"] for row in report["failures"]}
        )

    def test_oversized_receipt_is_rejected_before_json_inspection(self) -> None:
        result = self.add()
        provenance = importlib.import_module(
            "cite_check_engine.export_provenance"
        )
        local = self.paths(result)[0]
        local.write_bytes(b"x" * 65)
        with unittest.mock.patch.object(provenance, "MAX_RECEIPT_BYTES", 64):
            self.assertNotEqual(self.check()["status"], "VERIFIED")

    def test_receipt_output_cannot_alias_the_bibliography(self) -> None:
        result = self.add()
        local = self.paths(result)[0]
        before = self.bib.read_bytes()
        local.unlink()
        local.symlink_to(self.bib)
        replacement = SERVER.bib_add(
            str(self.bib),
            [{"identifier": DOI, "key": "paper"}],
            prefer=["crossref"],
            replace=True,
        )
        self.assertFalse(replacement["ok"], replacement)
        self.assertEqual(self.bib.read_bytes(), before)


class PinnedSoftwareExportTest(ProvenanceFixture):
    """Software provenance records its generated-entry exception and pin."""

    def software_export(self, version: str = "v1.0") -> dict[str, Any]:
        """Export CFF-derived software from an immutable registry fixture."""
        record = SERVER._record(
            registry="github",
            github="owner/package",
            title="package",
            authors=["Project authors"],
            year=2020,
        )
        record["repo"] = {
            "full_name": "owner/package",
            "owner": "owner",
            "html_url": "https://github.com/owner/package",
            "default_branch": "main",
            "cff": {"title": "package", "authors": [("Project authors", True)]},
        }
        with (
            unittest.mock.patch.object(
                RESOLUTION, "_full_record", return_value=record
            ),
            unittest.mock.patch.object(
                SERVER,
                "_github_ref",
                return_value={
                    "found": True,
                    "sha": "a" * 40,
                    "date": "2020-01-02",
                },
            ),
            unittest.mock.patch.object(
                SERVER, "_github_get", return_value=record
            ),
        ):
            result = SERVER.fetch_bibtex(
                "github:owner/package",
                key="software",
                prefer=["github"],
                version=version,
            )
        self.assertTrue(result["bibtex"], result)
        self.bib.write_text(result["provenance"] + "\n" + result["bibtex"])
        return result

    def replace_receipt(
        self, result: dict[str, Any], payload: dict[str, Any]
    ) -> None:
        """Rehash a malicious receipt so semantic bindings must reject it."""
        for field, digest in (
            ("raw_export", "raw_sha256"),
            ("entry", "entry_sha256"),
        ):
            payload[digest] = hashlib.sha256(
                payload[field].encode()
            ).hexdigest()
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
        receipt = hashlib.sha256(encoded).hexdigest()
        path = pathlib.Path(result["export_provenance"]["path"]).parent / (
            receipt + ".json"
        )
        path.write_bytes(encoded)
        comment = result["provenance"]
        for field in ("raw_sha256", "entry_sha256"):
            comment = comment.replace(
                result["export_provenance"][field], payload[field]
            )
        comment = comment.replace(
            result["export_provenance"]["receipt"], receipt
        )
        self.bib.write_text(comment + "\n" + payload["entry"])

    def test_commit_text_in_title_cannot_replace_the_actual_url_pin(
        self,
    ) -> None:
        result = self.software_export()
        payload = json.loads(
            pathlib.Path(result["export_provenance"]["path"]).read_bytes()
        )
        sha = payload["record"]["pinned_sha"]
        raw = payload["raw_export"].replace(sha, "b" * 40)
        raw = raw.replace("{{package}}", "{{package " + sha + "}}")
        self.assertEqual(raw.count(sha), 1)
        payload["raw_export"] = raw
        raw_entry = PARSING._parse_bib(raw)["entries"][0]
        payload["entry"] = BIBLIOGRAPHY._rewrite_key(
            BIBLIOGRAPHY._sanitize_bibtex(raw_entry, payload["record"]),
            payload["key"],
        )
        self.replace_receipt(result, payload)
        self.assertNotEqual(self.check()["status"], "VERIFIED")

    def test_rehashed_explicit_version_must_match_the_recorded_pin(
        self,
    ) -> None:
        result = self.software_export()
        payload = json.loads(
            pathlib.Path(result["export_provenance"]["path"]).read_bytes()
        )
        self.assertEqual(payload["request"]["version"], "v1.0")
        payload["request"]["version"] = "v2.0"
        self.replace_receipt(result, payload)
        self.assertNotEqual(self.check()["status"], "VERIFIED")

    def test_semicolon_git_ref_survives_comment_round_trip(self) -> None:
        result = self.software_export(version="release;reviewed")
        self.assertIn("version=release%3Breviewed", result["provenance"])
        self.assertEqual(self.check()["status"], "VERIFIED")
        parsed = self.entry("software")["provenance"]
        self.assertNotIn("reviewed", parsed)

    def test_cff_and_github_exports_keep_origin_and_immutable_commit(
        self,
    ) -> None:
        sha = "a" * 40
        for with_cff in (True, False):
            with self.subTest(with_cff=with_cff):
                record = SERVER._record(
                    registry="github",
                    github="owner/package",
                    title="package",
                    authors=["Project authors"],
                    year=2020,
                )
                record["repo"] = {
                    "full_name": "owner/package",
                    "owner": "owner",
                    "html_url": "https://github.com/owner/package",
                    "default_branch": "main",
                }
                if with_cff:
                    record["repo"]["cff"] = {
                        "title": "package",
                        "authors": [("Project authors", True)],
                        "url": "https://github.com/owner/package",
                    }
                with (
                    unittest.mock.patch.object(
                        RESOLUTION, "_full_record", return_value=record
                    ),
                    unittest.mock.patch.object(
                        SERVER,
                        "_github_ref",
                        return_value={
                            "found": True,
                            "sha": sha,
                            "date": "2020-01-02",
                        },
                    ),
                    unittest.mock.patch.object(
                        SERVER, "_github_get", return_value=record
                    ),
                ):
                    result = SERVER.fetch_bibtex(
                        "github:owner/package",
                        key="software",
                        prefer=["github"],
                        version="v1.0",
                    )
                self.assertTrue(result["bibtex"], result)
                receipt = json.loads(
                    pathlib.Path(
                        result["export_provenance"]["path"]
                    ).read_bytes()
                )
                self.assertEqual(
                    receipt["origin"], "tool-generated-software-entry"
                )
                self.assertEqual(receipt["record"]["pinned_sha"], sha)
                self.assertEqual(
                    receipt["source"], "citation-cff" if with_cff else "github"
                )
                self.bib.write_text(
                    result["provenance"] + "\n" + result["bibtex"]
                )
                self.assertEqual(self.check()["status"], "VERIFIED")
                self.bib.write_text(
                    self.bib.read_text().replace(
                        "version=v1.0", "version=v2.0", 1
                    )
                )
                self.assertNotEqual(self.check()["status"], "VERIFIED")


class AuditAssuranceTest(ProvenanceFixture):
    """Distinguish declaration-only history from checked export provenance."""

    def test_verified_receipt_is_counted_separately_from_declaration(
        self,
    ) -> None:
        self.add()
        report = self.audit()
        self.assertTrue(report["submission_ready"], report)
        axis = report["coverage"]["provenance"]
        self.assertEqual(axis["declared"], 1)
        self.assertEqual(axis["verified"], 1)
        self.assertTrue(axis["assurance"].startswith("local-export-digest"))
        self.assertIn("not a registry signature", axis["assurance"])

    def test_legacy_comment_is_declared_but_never_digest_verified(self) -> None:
        exported = SERVER.fetch_bibtex(DOI, key="paper", prefer=["crossref"])
        legacy = (
            "@comment{cite-check: source=crossref; id="
            + DOI
            + '; fetched=2026-10-20; title="A measured relation"}'
        )
        self.bib.write_text(legacy + "\n" + exported["bibtex"])
        self.assertEqual(self.check()["status"], "DECLARED")
        strict = self.audit()
        exploratory = self.audit("exploratory")
        self.assertFalse(strict["submission_ready"], strict)
        self.assertTrue(exploratory["ok"], exploratory)
        self.assertEqual(strict["coverage"]["provenance"]["declared"], 1)
        self.assertEqual(strict["coverage"]["provenance"]["verified"], 0)
        self.assertTrue(exploratory["warnings"])


if __name__ == "__main__":
    unittest.main()
