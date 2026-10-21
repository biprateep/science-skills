# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---
"""Publication notices retain direction and limited coverage claims."""

# %%
import copy
import importlib
import pathlib
import tempfile
from typing import Any
import unittest
import unittest.mock
import urllib.parse

import test_audit_policies
import test_evidence

SERVER = test_evidence.SERVER
STATUS = importlib.import_module("cite_check_engine.publication_status")
REGISTRY = importlib.import_module("cite_check_engine.registry_clients")
RESOLUTION = importlib.import_module("cite_check_engine.resolution")
TRANSPORT = importlib.import_module("cite_check_engine.transport")
DOI = "10.1234/example"
NOTICE_DOI = "10.1234/notice"


def crossref_message(**extra: Any) -> dict[str, Any]:
    """Provide realistic Crossref work metadata without making a request."""
    result = {
        "DOI": DOI,
        "title": ["Example"],
        "type": "journal-article",
        "issued": {"date-parts": [[2020]]},
    }
    result.update(extra)
    return result


def event(
    kind: str = "retraction",
    doi: str = NOTICE_DOI,
    source: str = "publisher",
) -> dict[str, Any]:
    """Provide the Crossref relation shape, including publisher provenance."""
    return {
        "DOI": doi,
        "type": kind,
        "label": kind.replace("-", " ").title(),
        "source": source,
        "updated": {
            "date-parts": [[2024, 2, 3]],
            "date-time": "2024-02-03T00:00:00Z",
            "timestamp": 1706918400000,
        },
    }


# %%
class PublicationNormalizationTest(unittest.TestCase):
    """Registry relation direction is independent of identifier existence."""

    def test_incoming_retraction_preserves_provenance_and_date(self) -> None:
        result = STATUS.normalize(crossref_message(**{"updated-by": [event()]}))
        self.assertEqual(result["state"], "RETRACTED")
        self.assertTrue(result["complete"])
        self.assertEqual(result["source"], "crossref")
        self.assertIn(urllib.parse.quote(DOI, safe=""), result["source_url"])
        update = result["updates"][0]
        self.assertEqual(update["doi"], NOTICE_DOI)
        self.assertEqual(update["source"], "publisher")
        self.assertEqual(update["date"], "2024-02-03")
        self.assertEqual(update["url"], "https://doi.org/" + NOTICE_DOI)
        self.assertTrue(result["observed_at"])
        self.assertGreater(result["metadata_cache_ttl_seconds"], 0)

    def test_outgoing_retraction_marks_notice_not_retracted_article(
        self,
    ) -> None:
        result = STATUS.normalize(crossref_message(**{"update-to": [event()]}))
        self.assertEqual(result["state"], "NOTICE")
        self.assertEqual(result["updates"], [])
        self.assertEqual(result["notices_for"][0]["doi"], NOTICE_DOI)

    def test_notice_can_itself_have_an_incoming_retraction(self) -> None:
        result = STATUS.normalize(
            crossref_message(
                **{
                    "update-to": [event(doi="10.1234/original")],
                    "updated-by": [event(doi="10.1234/retracted-notice")],
                }
            )
        )
        self.assertEqual(result["state"], "RETRACTED")
        self.assertEqual(len(result["updates"]), 1)
        self.assertEqual(len(result["notices_for"]), 1)

    def test_incoming_types_have_separate_review_states(self) -> None:
        for kind, state in (
            ("correction", "CORRECTED"),
            ("expression-of-concern", "EXPRESSION_OF_CONCERN"),
            ("new-version", "UPDATED"),
        ):
            with self.subTest(kind=kind):
                result = STATUS.normalize(
                    crossref_message(**{"updated-by": [event(kind)]})
                )
                self.assertEqual(result["state"], state)

    def test_absent_updates_never_claims_certified_clear(self) -> None:
        result = STATUS.normalize(crossref_message())
        self.assertEqual(result["state"], "NO_UPDATES_REPORTED")
        self.assertNotIn(result["state"], {"CLEAR", "VERIFIED", "CURRENT"})
        self.assertIn("does not certify", result["detail"])

    def test_title_words_do_not_infer_a_retraction(self) -> None:
        message = crossref_message(title=["Retraction notices in medicine"])
        result = STATUS.normalize(message)
        self.assertEqual(result["state"], "NO_UPDATES_REPORTED")

    def test_invalid_work_is_unknown(self) -> None:
        values: tuple[Any, ...] = (None, [], {}, {"DOI": "not-a-doi"})
        for value in values:
            with self.subTest(value=value):
                result = STATUS.normalize(value)
                self.assertEqual(result["state"], "UNKNOWN")
                self.assertFalse(result["complete"])

    def test_malformed_relation_container_cannot_be_clear(self) -> None:
        values: tuple[Any, ...] = (None, {}, "retracted", [None], ["retracted"])
        for value in values:
            with self.subTest(value=value):
                result = STATUS.normalize(
                    crossref_message(**{"updated-by": value})
                )
                self.assertEqual(result["state"], "UNKNOWN")
                self.assertFalse(result["complete"])

    def test_known_retraction_survives_other_malformed_events(self) -> None:
        result = STATUS.normalize(
            crossref_message(**{"updated-by": [None, event(), {"DOI": "bad"}]})
        )
        self.assertEqual(result["state"], "RETRACTED")
        self.assertFalse(result["complete"])

    def test_invalid_event_identifiers_and_types_never_infer_retraction(
        self,
    ) -> None:
        variants: tuple[dict[str, Any], ...] = (
            {"DOI": "javascript:alert(1)"},
            {"DOI": "https://evil.example/10.1234/x"},
            {"type": None},
            {"type": []},
            {"DOI": 123},
        )
        for change in variants:
            with self.subTest(change=change):
                malformed = event()
                malformed.update(change)
                result = STATUS.normalize(
                    crossref_message(**{"updated-by": [malformed]})
                )
                self.assertEqual(result["state"], "UNKNOWN")
                self.assertFalse(result["complete"])

    def test_exact_duplicates_collapse_but_independent_sources_survive(
        self,
    ) -> None:
        publisher = event()
        result = STATUS.normalize(
            crossref_message(
                **{
                    "updated-by": [
                        publisher,
                        copy.deepcopy(publisher),
                        event(source="retraction-watch"),
                    ]
                }
            )
        )
        self.assertEqual(len(result["updates"]), 2)
        self.assertEqual(
            {row["source"] for row in result["updates"]},
            {"publisher", "retraction-watch"},
        )

    def test_self_retraction_retains_adverse_status_and_review_context(
        self,
    ) -> None:
        result = STATUS.normalize(
            crossref_message(**{"updated-by": [event(doi=DOI)]})
        )
        self.assertEqual(result["state"], "RETRACTED")
        self.assertTrue(result["updates"][0]["self_relation"])
        self.assertTrue(result["reasons"])

    def test_relation_limit_is_bounded_and_marks_incomplete(self) -> None:
        rows = [event(doi=f"10.1234/notice-{index}") for index in range(101)]
        result = STATUS.normalize(crossref_message(**{"updated-by": rows}))
        self.assertLessEqual(len(result["updates"]), 100)
        self.assertFalse(result["complete"])
        self.assertEqual(result["state"], "RETRACTED")

    def test_invalid_optional_label_and_source_keep_known_retraction(
        self,
    ) -> None:
        for field, value in (
            ("label", {}),
            ("source", ["publisher"]),
            ("label", []),
            ("source", 0),
            ("source", False),
            ("label", "x" * 300),
        ):
            with self.subTest(field=field, value=value):
                update = event()
                update[field] = value
                result = STATUS.normalize(
                    crossref_message(**{"updated-by": [update]})
                )
                self.assertEqual(result["state"], "RETRACTED")
                self.assertFalse(result["complete"])
                self.assertEqual(result["updates"][0]["doi"], NOTICE_DOI)

    def test_malformed_persisted_status_becomes_unknown(self) -> None:
        good = STATUS.normalize(crossref_message(**{"updated-by": [event()]}))
        variants: tuple[dict[str, Any], ...] = (
            {"detail": None},
            {"updates": [None]},
            {"updates": [{"type": "retraction"}]},
            {"notices_for": "invalid"},
            {"complete": "yes"},
        )
        for change in variants:
            with self.subTest(change=change):
                bad = dict(good, **change)
                result = STATUS.available(bad)
                self.assertEqual(result["state"], "UNKNOWN")
                self.assertFalse(result["complete"])

    def test_input_is_not_mutated(self) -> None:
        message = crossref_message(**{"updated-by": [event()]})
        before = copy.deepcopy(message)
        STATUS.normalize(message)
        self.assertEqual(message, before)

    def test_partial_dates_preserve_available_precision(self) -> None:
        for parts, expected in (([2024], "2024"), ([2024, 2], "2024-02")):
            with self.subTest(parts=parts):
                update = event()
                update["updated"] = {"date-parts": [parts]}
                result = STATUS.normalize(
                    crossref_message(**{"updated-by": [update]})
                )
                self.assertEqual(result["updates"][0]["date"], expected)

    def test_invalid_date_does_not_hide_known_retraction(self) -> None:
        update = event()
        update["updated"] = {"date-parts": [[2024, 2, 31]]}
        result = STATUS.normalize(crossref_message(**{"updated-by": [update]}))
        self.assertEqual(result["state"], "RETRACTED")
        self.assertFalse(result["complete"])
        self.assertIsNone(result["updates"][0]["date"])


# %%
class PublicationPropagationTest(unittest.TestCase):
    """Status survives conversion independently of existence results."""

    def test_crossref_work_and_public_resolution_keep_status(self) -> None:
        record = REGISTRY._cr_record(
            crossref_message(
                **{"updated-by": [event(source="retraction-watch")]}
            )
        )
        self.assertEqual(record["publication_status"]["state"], "RETRACTED")
        public = RESOLUTION._public(record, "doi:" + DOI, "doi")
        self.assertTrue(public["resolved"])
        self.assertEqual(
            public["publication_status"], record["publication_status"]
        )

    def test_other_registry_without_crossref_metadata_is_unknown(self) -> None:
        for registry in ("datacite", "arxiv", "github", "ads", "openalex"):
            with self.subTest(registry=registry):
                record = SERVER._record(
                    registry=registry, doi=DOI, title="Example"
                )
                public = RESOLUTION._public(record, "doi:" + DOI, "doi")
                self.assertTrue(public["resolved"])
                self.assertEqual(
                    public["publication_status"]["state"], "UNKNOWN"
                )

    def test_same_doi_merge_preserves_crossref_status(self) -> None:
        original = REGISTRY._cr_record(
            crossref_message(**{"updated-by": [event()]})
        )
        base = SERVER._record(registry="ads", doi=DOI, title="Example")
        merged = RESOLUTION._merge_records(base, original)
        self.assertEqual(merged["publication_status"]["state"], "RETRACTED")
        self.assertEqual(merged["registry"], "ads")

    def test_different_doi_merge_never_transfers_retraction(self) -> None:
        original = REGISTRY._cr_record(
            crossref_message(**{"updated-by": [event()]})
        )
        base = SERVER._record(
            registry="ads", doi="10.1234/other", title="Example"
        )
        merged = RESOLUTION._merge_records(base, original)
        public = RESOLUTION._public(merged, "doi:10.1234/other", "doi")
        self.assertEqual(public["publication_status"]["state"], "UNKNOWN")

    def test_search_projection_does_not_silently_drop_update_metadata(
        self,
    ) -> None:
        message = crossref_message(**{"updated-by": [event()]})
        with unittest.mock.patch.object(
            TRANSPORT,
            "_get_json",
            return_value=(200, {"message": {"items": [message]}}),
        ) as request:
            records = REGISTRY._crossref_search(title="Example")
        url = request.call_args.args[0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        if "select" in query:
            selected = set(query["select"][0].split(","))
            self.assertFalse({"updated-by", "update-to"} <= selected)
        self.assertEqual(records[0]["publication_status"]["state"], "UNKNOWN")
        self.assertIn("projection", records[0]["publication_status"]["detail"])

    def test_verification_remains_verified_while_reporting_retraction(
        self,
    ) -> None:
        record = REGISTRY._cr_record(
            crossref_message(**{"updated-by": [event()]})
        )
        public = RESOLUTION._public(record, "doi:" + DOI, "doi")
        with tempfile.TemporaryDirectory() as directory:
            bib = pathlib.Path(directory) / "refs.bib"
            bib.write_text("@article{a,title={Example},doi={10.1234/example}}")
            with unittest.mock.patch.object(
                SERVER, "_resolve_many", return_value=[public]
            ):
                result = SERVER.verify_bib(str(bib), search_unresolved=False)
        self.assertTrue(result["ok"])
        row = result["entries"][0]
        self.assertEqual(row["status"], "VERIFIED")
        self.assertEqual(row["publication_status"]["state"], "RETRACTED")


# %%
class PublicationAuditTest(unittest.TestCase):
    """Retraction policy does not erase independently verified identity."""

    setUp: Any = test_audit_policies.AuditPoliciesTest.setUp
    verify: Any = test_audit_policies.AuditPoliciesTest.verify
    write_bib: Any = test_audit_policies.AuditPoliciesTest.write_bib
    support: Any = test_audit_policies.AuditPoliciesTest.support
    audit: Any = test_audit_policies.AuditPoliciesTest.audit
    verification: list[dict[str, Any]]
    tex: pathlib.Path
    bib: pathlib.Path

    def status(
        self, relation: str | None, direction: str = "updated-by"
    ) -> None:
        """Attach realistic resolved metadata to an otherwise verified entry."""
        message = crossref_message()
        if relation:
            message[direction] = [event(relation)]
        self.verification[0]["publication_status"] = STATUS.normalize(message)

    def test_strict_retraction_blocks_ready_without_losing_existence(
        self,
    ) -> None:
        self.support()
        self.status("retraction")
        report = self.audit()
        self.assertFalse(report["ok"])
        self.assertFalse(report["submission_ready"])
        self.assertEqual(
            report["coverage"]["existence"]["counts"], {"VERIFIED": 1}
        )
        self.assertEqual(
            report["publication_status"]["a"]["state"], "RETRACTED"
        )
        self.assertTrue(
            any(
                item["type"] == "publication-status"
                for item in report["failures"]
            )
        )

    def test_exploratory_retraction_is_explicit_warning(self) -> None:
        self.support()
        self.status("retraction")
        report = self.audit(policy="exploratory")
        self.assertTrue(report["ok"])
        self.assertFalse(report["submission_ready"])
        self.assertTrue(
            any(
                item["type"] == "publication-status"
                for item in report["warnings"]
            )
        )

    def test_correction_and_concern_require_explicit_review_warning(
        self,
    ) -> None:
        self.support()
        for kind in ("correction", "expression-of-concern"):
            with self.subTest(kind=kind):
                self.status(kind)
                report = self.audit()
                self.assertTrue(report["ok"])
                self.assertTrue(
                    any(
                        item["type"] == "publication-status"
                        for item in report["warnings"]
                    )
                )
                self.assertIn("review", str(report["warnings"]).lower())

    def test_outgoing_notice_never_fails_retraction_policy(self) -> None:
        self.support()
        self.status("retraction", direction="update-to")
        report = self.audit()
        self.assertTrue(report["ok"])
        self.assertEqual(report["publication_status"]["a"]["state"], "NOTICE")
        self.assertFalse(
            any(
                item["type"] == "publication-status"
                for item in report["failures"]
            )
        )

    def test_unsupported_status_is_unknown_with_visible_warning(self) -> None:
        self.support()
        report = self.audit()
        self.assertTrue(report["ok"])
        self.assertEqual(report["publication_status"]["a"]["state"], "UNKNOWN")
        self.assertTrue(
            any(
                item["type"] == "publication-status"
                for item in report["warnings"]
            )
        )

    def test_report_preserves_retraction_notice_url_and_provenance(
        self,
    ) -> None:
        self.support()
        self.status("retraction")
        result = SERVER.correction_report(str(self.tex), str(self.bib))
        self.assertTrue(result["report_written"])
        self.assertEqual(
            result["publication_status"]["a"]["state"], "RETRACTED"
        )
        rendered = pathlib.Path(result["artifacts"]["markdown"]).read_text()
        self.assertIn("RETRACTED", rendered)
        self.assertIn(NOTICE_DOI, rendered)
        self.assertIn("publisher", rendered)
        self.assertIn("2024-02-03", rendered)


# %%
if __name__ == "__main__":
    unittest.main()
