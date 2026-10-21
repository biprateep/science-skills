"""Atomic judgments preserve complete sentences and individual occurrences."""

import concurrent.futures
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

import test_evidence

SERVER = test_evidence.SERVER


class AtomicClaimsTest(unittest.TestCase):
    """Exercise coverage, source binding and transactional atom persistence."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = pathlib.Path(self.directory.name)
        self.tex = self.root / "main.tex"
        self.bib = self.root / "refs.bib"
        self.bib.write_text("@article{a,title={A}}\n@article{b,title={B}}")
        self.source = self.root / "source.txt"
        self.source.write_text(
            "The measured value is α = -1. "
            "The treatment does not improve survival."
        )
        metadata = {
            "id": "doi:10.1/example",
            "basis": "fulltext",
            "source": "local:source.txt",
            "path": str(self.source),
            "intake": test_evidence.source_intake(self.source),
            "extraction_version": SERVER.TEXT_EXTRACTION_VERSION,
        }
        self.record_mock = unittest.mock.patch.object(
            SERVER, "_full_record", return_value={"doi": "10.1/example"}
        )
        self.metadata_mock = unittest.mock.patch.object(
            SERVER, "_load_text_meta", return_value=metadata
        )
        self.record_mock.start()
        self.metadata_mock.start()
        self.addCleanup(self.record_mock.stop)
        self.addCleanup(self.metadata_mock.stop)
        self.extract(
            r"The value is α = -1 \cite{a}, and survival improves \cite{b}."
        )

    def extract(self, text: str) -> dict:
        """Write a manuscript and retain its current extraction."""
        self.tex.write_text(text, encoding="utf-8")
        self.extracted = SERVER.extract_cites(str(self.tex))
        self.sentence = self.extracted["sentences"][0]
        return self.extracted

    def spans(self) -> list[dict]:
        """Split this fixture at its conjunction with explicit scope."""
        split = self.sentence["claim"].index(" and ")
        cites = self.extracted["cites"]
        return [
            {
                "start": 0,
                "end": split,
                "citation_ids": [cites[0]["occurrence_id"]],
            },
            {
                "start": split,
                "end": len(self.sentence["claim"]),
                "citation_ids": [cites[-1]["occurrence_id"]],
            },
        ]

    def register(self, spans: list[dict] | None = None) -> dict:
        """Register a complete partition and assert success."""
        result = SERVER.register_claims(
            str(self.tex),
            self.sentence["sentence_id"],
            self.spans() if spans is None else spans,
        )
        self.assertTrue(result["ok"], result)
        return result

    def record(
        self,
        cite: dict,
        atom: dict | None = None,
        verdict: str = "SUPPORTS",
        legacy: bool = False,
    ) -> dict:
        """Record real source evidence for a current fixture occurrence."""
        options = (
            {}
            if legacy
            else {
                "tex_path": str(self.tex),
                "occurrence_id": cite["occurrence_id"],
                "atom_id": atom["atom_id"] if atom else None,
            }
        )
        return SERVER.record_support(
            str(self.root),
            cite["key"],
            cite["claim"],
            verdict,
            "example",
            context=cite["context"],
            quotes=[self.source.read_text()],
            note="The source explicitly states the opposite survival result.",
            **options,
        )

    def audit(self) -> dict:
        """Audit without external registry requests."""
        return SERVER.audit(str(self.tex), str(self.bib), verify=False, policy="exploratory")

    def test_supported_and_contradicted_atoms_remain_separate(self) -> None:
        registered = self.register()
        for cite, atom, verdict in zip(
            self.extracted["cites"],
            registered["atoms"],
            ["SUPPORTS", "CONTRADICTS"],
            strict=True,
        ):
            self.assertTrue(self.record(cite, atom, verdict)["recorded"])
        report = self.audit()
        self.assertFalse(report["ok"])
        self.assertEqual(
            report["support_counts"], {"SUPPORTS": 1, "CONTRADICTS": 1}
        )
        self.assertEqual(report["n_atomic_requirements"], 2)
        self.assertEqual(report["support_missing"], 0)
        self.assertEqual(
            report["failures"][0]["atom"], registered["atoms"][1]["text"]
        )
        self.assertIn("Atom `", pathlib.Path(report["report"]).read_text())

    def test_one_atom_does_not_satisfy_another(self) -> None:
        registered = self.register()
        self.assertTrue(
            self.record(self.extracted["cites"][0], registered["atoms"][0])[
                "recorded"
            ]
        )
        report = self.audit()
        self.assertEqual(report["support_missing"], 1)
        self.assertEqual(
            report["failures"][0]["atom_id"], registered["atoms"][1]["atom_id"]
        )
        self.assertFalse(self.record(self.extracted["cites"][0])["recorded"])
        self.assertTrue(
            self.record(self.extracted["cites"][1], legacy=True)["recorded"]
        )
        self.assertEqual(self.audit()["support_missing"], 1)

    def test_independent_sources_do_not_need_cross_claim_verdicts(self) -> None:
        registered = self.register()
        for cite, atom in zip(
            self.extracted["cites"], registered["atoms"], strict=True
        ):
            self.assertTrue(self.record(cite, atom)["recorded"])
        self.assertTrue(self.audit()["ok"])
        self.assertFalse(
            self.record(self.extracted["cites"][0], registered["atoms"][1])[
                "recorded"
            ]
        )

    def test_a_trailing_citation_can_attach_to_both_atoms(self) -> None:
        self.extract(r"The value is α = -1 and survival improves \cite{a}.")
        registered = self.register()
        cite = self.extracted["cites"][0]
        self.record(cite, registered["atoms"][0])
        self.assertEqual(self.audit()["support_missing"], 1)
        self.record(cite, registered["atoms"][1])
        self.assertTrue(self.audit()["ok"])

    def test_invalid_partitions_and_lost_attachments_are_rejected(self) -> None:
        valid = self.spans()
        variants = [[], valid[:1], valid[1:]]
        for index, field, value in [
            (0, "start", 1),
            (0, "start", False),
            (0, "end", 10**6),
            (0, "end", valid[0]["end"] - 1),
            (1, "start", valid[1]["start"] - 1),
            (1, "citation_ids", []),
            (1, "citation_ids", ["unknown"]),
            (1, "citation_ids", valid[0]["citation_ids"]),
        ]:
            changed = [dict(atom) for atom in valid]
            changed[index][field] = value
            variants.append(changed)
        marker = self.extracted["cites"][0]["marker_start"]
        variants.append(
            [
                {**valid[0], "end": marker + 1},
                {**valid[1], "start": marker + 1},
            ]
        )
        for atoms in variants:
            with self.subTest(atoms=atoms):
                result = SERVER.register_claims(
                    str(self.tex), self.sentence["sentence_id"], atoms
                )
                self.assertFalse(result["ok"], result)

    def test_marker_only_atoms_are_rejected(self) -> None:
        self.extract(r"A result \cite{a}.")
        cite = self.extracted["cites"][0]
        spans = [
            {
                "start": 0,
                "end": cite["marker_start"],
                "citation_ids": [cite["occurrence_id"]],
            },
            {
                "start": cite["marker_start"],
                "end": len(cite["claim"]),
                "citation_ids": [cite["occurrence_id"]],
            },
        ]
        self.assertFalse(
            SERVER.register_claims(
                str(self.tex), self.sentence["sentence_id"], spans
            )["ok"]
        )

    def test_identical_occurrences_have_distinct_ids_and_legacy_is_ambiguous(
        self,
    ) -> None:
        self.extract(r"This result holds \cite{a}. This result holds \cite{a}.")
        first, second = self.extracted["cites"]
        self.assertEqual(first["claim"], second["claim"])
        self.assertNotEqual(first["occurrence_id"], second["occurrence_id"])
        self.assertTrue(self.record(first, legacy=True)["recorded"])
        self.assertEqual(self.audit()["support_missing"], 2)
        self.assertTrue(self.record(first)["recorded"])
        self.assertEqual(self.audit()["support_missing"], 1)
        self.assertTrue(self.record(second)["recorded"])
        self.assertTrue(self.audit()["ok"])

    def test_unambiguous_legacy_sentence_is_backward_compatible(self) -> None:
        self.extract(r"This result holds \cite{a}.")
        self.assertTrue(
            self.record(self.extracted["cites"][0], legacy=True)["recorded"]
        )
        self.assertTrue(self.audit()["ok"])

    def test_registration_revisions_invalidate_even_if_reverted(self) -> None:
        first = self.register()
        self.record(self.extracted["cites"][0], first["atoms"][0])
        self.register()
        self.assertEqual(self.audit()["support_missing"], 1)
        self.register(
            [
                {
                    "start": 0,
                    "end": len(self.sentence["claim"]),
                    "citation_ids": self.sentence["citation_ids"],
                }
            ]
        )
        self.assertEqual(self.audit()["support_missing"], 2)
        self.register()
        self.assertEqual(self.audit()["support_missing"], 2)
        self.assertEqual(
            SERVER.ledger_read(str(self.root))["ledger"]["entries"], {}
        )

    def test_context_or_sentence_changes_fail_closed(self) -> None:
        for suffix in (" Context changed.", ""):
            with self.subTest(suffix=suffix):
                self.extract(
                    r"The value is α = -1 \cite{a}, "
                    r"and survival improves \cite{b}."
                )
                registered = self.register()
                self.record(self.extracted["cites"][0], registered["atoms"][0])
                old_cite = self.extracted["cites"][0]
                new_text = self.tex.read_text() + suffix
                if not suffix:
                    new_text = new_text.replace("α = -1", "β = +1")
                self.extract(new_text)
                report = self.audit()
                self.assertTrue(
                    any(
                        item["type"] == "decomposition-stale"
                        for item in report["failures"]
                    )
                )
                self.assertFalse(
                    self.record(old_cite, registered["atoms"][0])["recorded"]
                )
                self.register()
                self.assertEqual(self.audit()["support_missing"], 2)

    def test_source_changes_invalidate_atomic_evidence(self) -> None:
        registered = self.register()
        for cite, atom in zip(
            self.extracted["cites"], registered["atoms"], strict=True
        ):
            self.record(cite, atom)
        self.source.write_text(self.source.read_text() + " A correction.")
        report = self.audit()
        self.assertEqual(
            {item["type"] for item in report["failures"]}, {"support-stale"}
        )

    def test_exact_symbols_character_and_byte_offsets_are_preserved(
        self,
    ) -> None:
        raw = (
            "% comment α\r\nThe value is α = -1 \\cite{a}, "
            "and survival improves \\cite{b}."
        )
        self.tex.write_bytes(raw.encode("utf-8"))
        self.extracted = SERVER.extract_cites(str(self.tex))
        self.sentence = self.extracted["sentences"][0]
        registered = self.register()
        claim = self.sentence["claim"]
        self.assertEqual(
            "".join(atom["text"] for atom in registered["atoms"]), claim
        )
        for atom in registered["atoms"]:
            self.assertEqual(claim[atom["start"] : atom["end"]], atom["text"])
            self.assertEqual(
                claim.encode("utf-8")[
                    atom["byte_start"] : atom["byte_end"]
                ].decode("utf-8"),
                atom["text"],
            )
        for cite in self.extracted["cites"]:
            self.assertEqual(
                raw[cite["source_start"] : cite["source_end"]],
                cite["source_command"],
            )
            self.assertEqual(
                self.tex.read_bytes()[
                    cite["source_byte_start"] : cite["source_byte_end"]
                ].decode("utf-8"),
                cite["source_command"],
            )
        self.assertIn("α = -1", registered["atoms"][0]["text"])

    def test_registration_during_fetch_refuses_obsolete_atom(self) -> None:
        registered = self.register()

        def revise(*args: object, **kwargs: object) -> dict:
            del args, kwargs
            self.register(
                [
                    {
                        "start": 0,
                        "end": len(self.sentence["claim"]),
                        "citation_ids": self.sentence["citation_ids"],
                    }
                ]
            )
            return {"doi": "10.1/example"}

        with unittest.mock.patch.object(
            SERVER, "_full_record", side_effect=revise
        ):
            result = self.record(
                self.extracted["cites"][0], registered["atoms"][0]
            )
        self.assertFalse(result["recorded"])
        self.assertEqual(
            SERVER.ledger_read(str(self.root))["ledger"]["entries"], {}
        )

    def test_concurrent_registration_and_support_persist_all_entries(
        self,
    ) -> None:
        registered = self.register()

        def write(index: int) -> bool:
            self.register()
            position = index % 2
            return self.record(
                self.extracted["cites"][position], registered["atoms"][position]
            )["recorded"]

        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            self.assertTrue(all(pool.map(write, range(24))))
        ledger = SERVER.ledger_read(str(self.root))["ledger"]
        self.assertEqual(len(ledger["entries"]), 2)
        self.assertEqual(len(ledger["decompositions"]), 1)
        self.assertTrue(self.audit()["ok"])

    def test_cli_registers_same_schema_and_preserves_state(self) -> None:
        arguments = {
            "tex_path": str(self.tex),
            "sentence_id": self.sentence["sentence_id"],
            "atoms": self.spans(),
        }
        process = subprocess.run(
            [
                sys.executable,
                SERVER.__file__,
                "call",
                "register_claims",
                json.dumps(arguments),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        result = json.loads(process.stdout)
        self.assertTrue(result["ok"])
        self.assertEqual(result, self.register())
        self.assertEqual(self.audit()["support_missing"], 2)

    def test_uncited_scope_is_explicit_preserved_and_never_verified(
        self,
    ) -> None:
        self.extract(r"We measure α = -1, and Smith reports survival \cite{a}.")
        spans = self.spans()
        spans[0].update(
            kind="uncited",
            citation_ids=[],
            reason="This clause reports the authors' own measurement.",
        )
        registered = self.register(spans)
        self.record(self.extracted["cites"][0], registered["atoms"][1])
        report = self.audit()
        self.assertTrue(report["ok"])
        self.assertEqual(report["n_atomic_requirements"], 1)
        self.assertEqual(report["n_uncited_atoms"], 1)
        self.assertFalse(report["uncited_atoms"][0]["verified"])
        self.assertEqual(
            report["uncited_atoms"][0]["atom"], registered["atoms"][0]["text"]
        )
        self.assertTrue(
            any(item["type"] == "uncited-atom" for item in report["warnings"])
        )
        for changes in [
            {"reason": "short"},
            {"kind": "cited"},
            {"citation_ids": self.sentence["citation_ids"]},
        ]:
            invalid = [dict(spans[0], **changes), spans[1]]
            self.assertFalse(
                SERVER.register_claims(
                    str(self.tex), self.sentence["sentence_id"], invalid
                )["ok"]
            )

    def test_math_expressions_cannot_be_split(self) -> None:
        for math in ("$α=-1$", r"\(α=-1\)", r"\[α=-1\]", "$$α=-1$$"):
            with self.subTest(math=math):
                self.extract(f"The value is {math} and it agrees \\cite{{a}}.")
                spans = self.spans()
                split = self.sentence["claim"].index("-1")
                spans[0]["end"] = split
                spans[1]["start"] = split
                self.assertFalse(
                    SERVER.register_claims(
                        str(self.tex), self.sentence["sentence_id"], spans
                    )["ok"]
                )

    def test_displaced_registration_survives_new_registration(self) -> None:
        original = (
            "Earlier background.\n\nMiddle background.\n\n"
            r"Alpha rises and beta falls \cite{a}."
            "\n\nLater background."
        )
        self.extract(original)
        self.register()
        self.extract(r"Previously reported \cite{b}." + "\n\n" + original)
        displaced = next(
            cite for cite in self.extracted["cites"] if cite["key"] == "a"
        )
        self.assertTrue(
            any(
                item["type"] == "decomposition-stale" and item["key"] == "a"
                for item in self.audit()["failures"]
            )
        )
        self.register(
            [
                {
                    "start": 0,
                    "end": len(self.sentence["claim"]),
                    "citation_ids": self.sentence["citation_ids"],
                }
            ]
        )
        self.record(self.extracted["cites"][0])  # Requires its registered atom.
        self.assertTrue(
            any(
                item["type"] == "decomposition-stale" and item["key"] == "a"
                for item in self.audit()["failures"]
            )
        )
        self.assertFalse(self.record(displaced)["recorded"])
        self.sentence = next(
            sentence
            for sentence in self.extracted["sentences"]
            if sentence["sentence_id"] == displaced["sentence_id"]
        )
        split = self.sentence["claim"].index(" and ")
        registered = self.register(
            [
                {
                    "start": 0,
                    "end": split,
                    "citation_ids": [displaced["occurrence_id"]],
                },
                {
                    "start": split,
                    "end": len(self.sentence["claim"]),
                    "citation_ids": [displaced["occurrence_id"]],
                },
            ]
        )
        self.assertEqual(self.audit()["n_atomic_requirements"], 3)
        # Removing the preceding citation and restoring the original source
        # must not revive any historical sentence or atom judgments.
        self.extract(original)
        self.assertEqual(self.audit()["support_missing"], 2)
        self.assertNotEqual(
            registered["sentence_id"], self.sentence["sentence_id"]
        )

    def test_reordered_citations_retain_atomic_obligations(self) -> None:
        first = r"Alpha rises and beta falls \cite{a}."
        second = r"Gamma rises and delta falls \cite{b}."
        self.extract(first + "\n\n" + second)
        for sentence in self.extracted["sentences"]:
            split = sentence["claim"].index(" and ")
            self.assertTrue(
                SERVER.register_claims(
                    str(self.tex),
                    sentence["sentence_id"],
                    [
                        {
                            "start": 0,
                            "end": split,
                            "citation_ids": sentence["citation_ids"],
                        },
                        {
                            "start": split,
                            "end": len(sentence["claim"]),
                            "citation_ids": sentence["citation_ids"],
                        },
                    ],
                )["ok"]
            )
        self.extract(second + "\n\n" + first)
        self.assertEqual(
            sum(
                item["type"] == "decomposition-stale"
                for item in self.audit()["failures"]
            ),
            2,
        )

    def test_manuscripts_sharing_input_have_separate_occurrence_identity(
        self,
    ) -> None:
        included = self.root / "included.tex"
        included.write_text(r"An included result \cite{a}.")
        self.extract(r"\input{included}")
        other = self.root / "other.tex"
        other.write_text(r"\input{included}")
        second = SERVER.extract_cites(str(other))
        self.assertNotEqual(
            self.extracted["cites"][0]["occurrence_id"],
            second["cites"][0]["occurrence_id"],
        )

    def test_registration_during_audit_cannot_publish_stale_success(
        self,
    ) -> None:
        registered = self.register()
        for cite, atom in zip(
            self.extracted["cites"], registered["atoms"], strict=True
        ):
            self.record(cite, atom)
        original = SERVER._current_source_identity
        revised = False

        def revise(identifier: str) -> dict | None:
            nonlocal revised
            if not revised:
                revised = True
                self.register(
                    [
                        {
                            "start": 0,
                            "end": len(self.sentence["claim"]),
                            "citation_ids": self.sentence["citation_ids"],
                        }
                    ]
                )
            return original(identifier)

        with unittest.mock.patch.object(
            SERVER, "_current_source_identity", side_effect=revise
        ):
            report = self.audit()
        self.assertFalse(report["ok"])
        self.assertTrue(
            any(item["type"] == "audit-stale" for item in report["failures"])
        )
        self.assertFalse(
            json.loads((self.root / ".cite-check" / "audit.json").read_text())[
                "ok"
            ]
        )

    def test_non_utf8_source_fails_closed(self) -> None:
        self.tex.write_bytes(b"Invalid \xff text \\cite{a}.")
        result = SERVER.extract_cites(str(self.tex))
        self.assertFalse(result["complete"])
        self.assertIn("error", result)

    def test_atomic_mode_survives_move_edit_and_cross_file_transfer(
        self,
    ) -> None:
        registered = self.register()
        for cite, atom in zip(
            self.extracted["cites"], registered["atoms"], strict=True
        ):
            self.record(cite, atom)
        original = self.tex.read_text()
        included = self.root / "moved.tex"
        included.write_text(original.replace("α = -1", "β = +1"))
        self.extract(r"A new result \cite{b}." + "\n\n" + r"\input{moved}")
        requirements = SERVER._support_requirements(
            self.extracted, SERVER.ledger_read(str(self.root))["ledger"]
        )
        self.assertEqual(len(requirements), 3)
        self.assertTrue(
            all(item.get("decomposition_stale") for item in requirements)
        )
        self.assertFalse(self.record(self.extracted["cites"][-1])["recorded"])

    def test_changed_sentence_registration_does_not_resurrect_old_verdicts(
        self,
    ) -> None:
        registered = self.register()
        for cite, atom in zip(
            self.extracted["cites"], registered["atoms"], strict=True
        ):
            self.record(cite, atom)
        original = self.tex.read_text()
        self.extract(original.replace("α = -1", "β = +1"))
        self.register()
        self.assertEqual(
            SERVER.ledger_read(str(self.root))["ledger"]["entries"], {}
        )
        self.extract(original)
        self.assertEqual(self.audit()["support_missing"], 2)

    def test_literal_marker_text_cannot_move_citation_attachment(self) -> None:
        self.extract(
            r"The literal marker ⟨cite:a⟩ precedes the real result \cite{a}."
        )
        cite = self.extracted["cites"][0]
        self.assertEqual(cite["marker_start"], cite["claim"].rindex("⟨cite:a⟩"))
