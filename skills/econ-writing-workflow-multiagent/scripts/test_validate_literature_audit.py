#!/usr/bin/env python3
"""Regression tests for the independent literature-audit acceptance gate."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import audit_citation_integrity as citation_auditor
import prepare_manuscript_qa as qa_preparer
import validate_literature_audit as validator


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def complete_coverage_clusters() -> list[dict[str, Any]]:
    functions = (
        "recent_frontier",
        "closest_contribution",
        "theory_mechanism",
        "data_measurement_institution",
        "method_identification_model",
        "contrary_evidence_alternative_explanation",
    )
    records: list[dict[str, Any]] = []
    for function in functions:
        applicable = function == "recent_frontier"
        records.append(
            {
                "cluster_id": function,
                "function": function,
                "applicable": applicable,
                "rationale": (
                    "Current frontier is applicable to the fixture."
                    if applicable
                    else "Not applicable to this synthetic fixture."
                ),
                "gap_disposition": "resolved" if applicable else "not_applicable",
                "minimum_verified_sources": 1 if applicable else 0,
            }
        )
    return records


class LiteratureFixture:
    def __init__(
        self,
        root: Path,
        *,
        mode: str = "draft",
        with_core_registry: bool = True,
        task_stage: str = "full_draft",
    ) -> None:
        self.root = root
        self.mode = mode
        self.with_core_registry = with_core_registry
        self.task_stage = task_stage
        self.manuscript = root / "paper.md"
        self.bib = root / "references.bib"
        self.library = root / "reference_library_manifest.json"
        self.registry = root / "literature_registry.json"
        self.coverage = root / "literature_coverage_contract.json"
        self.intent = root / "author_intent.json"
        self.qa_contract = root / "qa_contract.json"
        self.artifact_contract = root / "artifact_contract.json"
        self.qa_output = root / "qa_bundle"
        self.qa_manifest = self.qa_output / "qa_manifest.json"
        self.ledger = root / "text_to_evidence_ledger.json"
        self.visible = root / "paper.bbl"
        self.attestation = root / "bibliography_build_attestation.json"
        self.citation_report = root / "citation_integrity_report.json"
        self.core_registry = root / "qa_assignment_registry.json"
        self.assignment = root / "literature_assignment.json"
        self.literature_audit = root / "literature_audit.json"
        self.report = root / "literature_validation.json"
        self.core_agents = [
            "native-author-intent",
            "native-evidence",
            "native-definitions",
            "native-economic-logic",
            "native-main-text",
        ]
        self.semantic_roles = [
            "author_intent_coverage",
            "evidence_claim_strength",
            "definitions_reader_sufficiency",
            "economic_logic_scope_qualifiers",
        ]
        self._build_authorities()
        self._build_core_registry()
        self._build_citation_report()
        self._build_assignment_and_audit()

    def _build_authorities(self) -> None:
        self.manuscript.write_text(
            "# Results\n\nThe estimate is consistent with prior evidence [@Smith2024].\n",
            encoding="utf-8",
        )
        self.bib.write_text(
            "@article{Smith2024,\n"
            "  author = {Smith, Alice},\n"
            "  title = {A Current Result},\n"
            "  year = {2024},\n"
            "  doi = {10.1000/smith}\n"
            "}\n",
            encoding="utf-8",
        )
        write_json(
            self.library,
            {
                "schema_version": "1.0",
                "schema_id": "reference-library-manifest/1.0",
                "library_id": "library-fixture",
                "library_revision": "1",
                "libraries": [
                    {
                        "path": self.bib.name,
                        "sha256": citation_auditor.sha256_file(self.bib),
                    }
                ],
            },
        )
        library_hash = citation_auditor.sha256_file(self.library)
        write_json(
            self.registry,
            {
                "schema_version": "1.0",
                "schema_id": "literature-registry/1.0",
                "registry_id": "registry-fixture",
                "registry_revision": "1",
                "library_id": "library-fixture",
                "library_revision": "1",
                "reference_library_manifest_sha256": library_hash,
                "entries": [
                    {
                        "citekey": "Smith2024",
                        "status": "admitted",
                        "coverage_roles": ["recent_frontier"],
                        "inspection_evidence": "inspected full source",
                    }
                ],
            },
        )
        registry_hash = citation_auditor.sha256_file(self.registry)
        write_json(
            self.coverage,
            {
                "schema_version": "1.0",
                "schema_id": "literature-coverage-contract/1.0",
                "contract_id": "coverage-fixture",
                "contract_revision": "1",
                "task_stage": self.task_stage,
                "search_scope": {
                    "databases_or_closed_corpus": ["synthetic fixture corpus"],
                    "languages": ["English"],
                    "coverage_end_date": "2026-08-03",
                    "source_types": ["journal article"],
                    "inclusion_criteria": ["fixture records"],
                    "exclusion_criteria": ["non-fixture records"],
                },
                "stop_condition": "All applicable fixture clusters inspected.",
                "unresolved_gaps": [],
                "approval_record": {
                    "confirmed_by": "fixture-author",
                    "confirmed_at": "2020-08-03T12:00:00+08:00",
                },
                "reference_library_manifest_sha256": library_hash,
                "literature_registry_sha256": registry_hash,
                "coverage_clusters": complete_coverage_clusters(),
            },
        )
        write_json(
            self.intent,
            {
                "author_intent_contract": {
                    "schema_version": "1.0",
                    "intent_contract_id": "intent-fixture",
                    "intent_revision_id": "r1",
                    "intent_status": "frozen-current",
                    "gate_status": "ready",
                    "unresolved_material_questions": [],
                    "approval_record": {
                        "confirmed_by": "fixture-author",
                        "confirmed_at": "2020-08-03T12:00:00+08:00",
                        "confirmed_scope": "complete_author_intent_contract",
                        "confirmation_source": "fixture",
                        "freeze_authorized_by": "fixture-author",
                        "freeze_authorized_at": "2020-08-03T12:00:00+08:00",
                    },
                    "reader_takeaway": "The estimate is consistent with prior evidence.",
                    "propositions": [
                        {
                            "intent_id": "I1",
                            "must_express": "The estimate is consistent with prior evidence.",
                            "claim_type": "associational",
                            "evidence_anchors": ["Smith2024"],
                        }
                    ],
                    "must_not_claim": ["unsupported causality"],
                    "definition_registry": [],
                }
            },
        )
        classification: dict[str, Any] = {
            "task_stage": self.task_stage,
            "qa_mode": "exhaustive",
            "basis": "The complete fixture manuscript requires semantic acceptance.",
            "classified_by": "controller-fixture",
            "classified_at": "2020-08-03T12:00:00+08:00",
        }
        if self.task_stage == "final_audit":
            classification["artifact_task_mode"] = "full_draft"
        write_json(
            self.qa_contract,
            {
                "qa_contract": {
                    "schema_version": "1.0",
                    "review_scope": "full_manuscript",
                    "qa_mode": "exhaustive",
                    "manuscript_path": str(self.manuscript),
                    "task_classification": classification,
                    "minimum_high_risk_independent_reviews": 2,
                    "content_obligations": [
                        {
                            "obligation_id": "Q1",
                            "intent_id": "I1",
                            "obligation_type": "must_express",
                            "content": "The estimate is consistent with prior evidence.",
                        }
                    ],
                    "definition_registry": [],
                }
            },
        )
        write_json(
            self.artifact_contract,
            {
                "artifact_contract": {
                    "schema_version": "1.0",
                    "task_mode": "full_draft",
                    "mature_baseline": False,
                    "metric_status": "measured",
                    "measurement_contract": {
                        "appendix_boundary": "\\appendix",
                        "source_word_method": "normalized_words",
                    },
                }
            },
        )
        qa_preparer.prepare(
            SimpleNamespace(
                manuscript=str(self.manuscript),
                project_root=str(self.root),
                author_intent_contract=str(self.intent),
                qa_contract=str(self.qa_contract),
                artifact_contract=str(self.artifact_contract),
                output_dir=str(self.qa_output),
            )
        )
        qa_manifest_payload = read_json(self.qa_manifest)
        citation_units = [
            unit
            for unit in qa_manifest_payload.get("units", [])
            if isinstance(unit, dict)
            and unit.get("type") == "sentence"
            and "Smith2024" in unit.get("citation_keys", [])
        ]
        if len(citation_units) != 1:
            raise AssertionError("fixture requires exactly one citation-bearing unit")
        self.citation_unit_id = citation_units[0]["unit_id"]
        expanded, _, _ = citation_auditor.load_manuscript(
            self.manuscript, self.root
        )
        write_json(
            self.ledger,
            {
                "schema_version": "1.0",
                "schema_id": "text-to-evidence-ledger/1.0",
                "ledger_id": "ledger-fixture",
                "ledger_revision": "1",
                "qa_manifest_sha256": citation_auditor.sha256_file(
                    self.qa_manifest
                ),
                "manuscript_sha256": citation_auditor.sha256_file(
                    self.manuscript
                ),
                "expanded_manuscript_sha256": citation_auditor.sha256_text(
                    expanded
                ),
                "literature_registry_sha256": registry_hash,
                "entries": [
                    {
                        "claim_id": "claim-fixture-1",
                        "unit_id": self.citation_unit_id,
                        "claim_type": "literature_support",
                        "citekeys": ["Smith2024"],
                        "support_role": "direct_support",
                        "support_strength": "consistent_with",
                        "source_locator": "synthetic full-source inspection",
                        "status": "supported",
                    }
                ],
            },
        )
        self.visible.write_text(
            "\\bibitem{Smith2024} Smith (2024).\n", encoding="utf-8"
        )
        write_json(
            self.attestation,
            {
                "schema_version": "1.0",
                "schema_id": "bibliography-build-attestation/1.0",
                "status": "complete",
                "expanded_manuscript_sha256": citation_auditor.sha256_text(
                    expanded
                ),
                "reference_library_manifest_sha256": library_hash,
                "qa_manifest_sha256": citation_auditor.sha256_file(
                    self.qa_manifest
                ),
                "visible_bibliography_sha256": citation_auditor.sha256_file(
                    self.visible
                ),
                "reference_library_files": [
                    {
                        "path": str(self.bib),
                        "sha256": citation_auditor.sha256_file(self.bib),
                    }
                ],
                "build_timestamp": "2020-08-03T12:01:00+08:00",
                "build_tool": "fixture-builder",
            },
        )

    def _build_core_registry(self) -> None:
        if not self.with_core_registry:
            return
        assignments: list[dict[str, Any]] = []
        manifest = read_json(self.qa_manifest)
        packets = manifest["packets"]
        for index, (agent, packet) in enumerate(
            zip(self.core_agents[:-1], packets), 1
        ):
            assignments.append(
                {
                    "assignment_kind": "semantic_packet",
                    "target_id": packet["packet_id"],
                    "target_sha256": packet["packet_sha256"],
                    "packet_id": packet["packet_id"],
                    "packet_sha256": packet["packet_sha256"],
                    "role": packet["role"],
                    "assignment_id": f"core-assignment-{index}",
                    "native_agent_id": agent,
                    "task_id": f"core-task-{index}",
                    "assigned_at": "2020-08-03T12:02:00+08:00",
                }
            )
        assignments.append(
            {
                "assignment_kind": "main_text_sufficiency",
                "target_id": "main-text-sufficiency",
                "target_sha256": manifest["expanded_manuscript_sha256"],
                "assignment_id": "core-assignment-5",
                "native_agent_id": self.core_agents[-1],
                "task_id": "core-task-5",
                "assigned_at": "2020-08-03T12:02:00+08:00",
            }
        )
        write_json(
            self.core_registry,
            {
                "schema_version": "1.0",
                "schema_id": "qa-assignment-registry/1.0",
                "status": "assigned",
                "manifest_id": manifest["manifest_id"],
                "manifest_sha256": citation_auditor.sha256_file(
                    self.qa_manifest
                ),
                "assignments": assignments,
            },
        )

    def _build_citation_report(self, expected_code: int = 0) -> None:
        argv = [
            "--mode",
            self.mode,
            "--manuscript",
            str(self.manuscript),
            "--project-root",
            str(self.root),
            "--reference-library-manifest",
            str(self.library),
            "--literature-registry",
            str(self.registry),
            "--coverage-contract",
            str(self.coverage),
            "--text-to-evidence-ledger",
            str(self.ledger),
            "--qa-manifest",
            str(self.qa_manifest),
            "--report",
            str(self.citation_report),
        ]
        if self.mode == "final":
            argv.extend(
                [
                    "--visible-bibliography",
                    str(self.visible),
                    "--bibliography-build-attestation",
                    str(self.attestation),
                ]
            )
        with contextlib.redirect_stdout(io.StringIO()):
            code = citation_auditor.main(argv)
        if code != expected_code:
            raise AssertionError(
                f"citation fixture returned {code}, expected {expected_code}: "
                f"{self.citation_report.read_text()}"
            )

    def live_hashes(self) -> dict[str, Any]:
        return {
            "manuscript_sha256": citation_auditor.sha256_file(self.manuscript),
            "literature_coverage_contract_sha256": citation_auditor.sha256_file(
                self.coverage
            ),
            "reference_library_manifest_sha256": citation_auditor.sha256_file(
                self.library
            ),
            "literature_registry_sha256": citation_auditor.sha256_file(
                self.registry
            ),
            "text_to_evidence_ledger_sha256": citation_auditor.sha256_file(
                self.ledger
            ),
            "citation_integrity_report_sha256": citation_auditor.sha256_file(
                self.citation_report
            ),
            "qa_manifest_sha256": citation_auditor.sha256_file(
                self.qa_manifest
            ),
            "core_qa_assignment_registry_sha256": (
                citation_auditor.sha256_file(self.core_registry)
                if self.core_registry.is_file()
                else ""
            ),
            "visible_bibliography_sha256": (
                citation_auditor.sha256_file(self.visible)
                if self.mode == "final"
                else None
            ),
        }

    def _build_assignment_and_audit(self) -> None:
        assignment_payload: dict[str, Any] = {
            "schema_version": "1.0",
            "schema_id": "literature-audit-assignment/1.0",
            "assignment_id": "literature-assignment-1",
            "status": "assigned",
            "assigned_at": "2020-08-03T12:03:00+08:00",
            "controller_id": "native-controller-fixture",
            "native_agent_id": "native-literature-reviewer",
            "task_id": "literature-task-1",
            "independent_of_drafting_and_integration": True,
            "forbidden_native_agent_ids": sorted(
                set(self.core_agents if self.with_core_registry else [])
                | {"native-drafting-agent", "native-controller-fixture"}
            ),
            "independence_basis": "Separate native task after deterministic citation pass.",
            "mode": self.mode,
            "task_stage": self.task_stage,
            "input_hashes": self.live_hashes(),
        }
        if self.with_core_registry:
            assignment_payload["core_qa_assignment_registry_sha256"] = (
                citation_auditor.sha256_file(self.core_registry)
            )
        write_json(self.assignment, assignment_payload)
        checks = {
            "applicable_clusters_resolved": True,
            "source_count_policy_satisfied_or_not_configured": True,
            "inspected_and_admitted_sources_only": True,
            "claims_supported_at_stated_strength": True,
            "citekey_registry_ledger_closed": True,
        }
        if self.mode == "final":
            checks["final_bibliography_closed"] = True
        write_json(
            self.literature_audit,
            {
                "schema_version": "1.0",
                "schema_id": "literature-coverage-audit/1.0",
                "audit_id": "literature-audit-1",
                "status": "complete",
                "assignment_id": assignment_payload["assignment_id"],
                "assignment_sha256": citation_auditor.sha256_file(
                    self.assignment
                ),
                "mode": self.mode,
                "task_stage": self.task_stage,
                "generated_at": "2020-08-03T12:04:00+08:00",
                "reviewer": {
                    "reviewer_id": "literature-reviewer-1",
                    "native_agent_id": assignment_payload["native_agent_id"],
                    "task_id": assignment_payload["task_id"],
                },
                "hashes": self.live_hashes(),
                "checks": checks,
                "findings": [],
                "gate_status": "pass",
            },
        )

    def rebind_assignment_and_audit(self) -> None:
        assignment = read_json(self.assignment)
        assignment["input_hashes"] = self.live_hashes()
        if self.with_core_registry:
            assignment["core_qa_assignment_registry_sha256"] = (
                citation_auditor.sha256_file(self.core_registry)
            )
        write_json(self.assignment, assignment)
        role_audit = read_json(self.literature_audit)
        role_audit["assignment_id"] = assignment["assignment_id"]
        role_audit["assignment_sha256"] = citation_auditor.sha256_file(
            self.assignment
        )
        role_audit["mode"] = assignment["mode"]
        role_audit["hashes"] = self.live_hashes()
        write_json(self.literature_audit, role_audit)

    def set_role_finding(
        self, finding_type: str, expected_status: str, false_check: str
    ) -> None:
        payload = read_json(self.literature_audit)
        payload["checks"][false_check] = False
        payload["findings"] = [
            {
                "finding_id": f"finding-{finding_type}",
                "finding_type": finding_type,
                "cluster_id": "recent_frontier",
                "citekey": "Smith2024",
                "unit_id": self.citation_unit_id,
                "evidence": "Current reviewer evidence.",
                "reason": f"Synthetic {finding_type} finding.",
                "severity": "blocking",
                "requires_author_action": True,
            }
        ]
        payload["gate_status"] = expected_status
        write_json(self.literature_audit, payload)

    def argv(
        self,
        *,
        report: Path | None = None,
        include_visible: bool = True,
        include_core: bool | None = None,
        visible_override: Path | None = None,
    ) -> list[str]:
        output = report or self.report
        argv = [
            "--mode",
            self.mode,
            "--manuscript",
            str(self.manuscript),
            "--coverage-contract",
            str(self.coverage),
            "--reference-library-manifest",
            str(self.library),
            "--literature-registry",
            str(self.registry),
            "--text-to-evidence-ledger",
            str(self.ledger),
            "--qa-manifest",
            str(self.qa_manifest),
            "--citation-integrity-report",
            str(self.citation_report),
            "--literature-assignment",
            str(self.assignment),
            "--literature-audit",
            str(self.literature_audit),
            "--core-qa-assignment-registry",
            str(self.core_registry),
            "--report",
            str(output),
        ]
        if self.mode == "final" and include_visible:
            argv.extend(
                [
                    "--visible-bibliography",
                    str(visible_override or self.visible),
                ]
            )
        return argv

    def run(self, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        output = kwargs.get("report") or self.report
        with contextlib.redirect_stdout(io.StringIO()):
            code = validator.main(self.argv(**kwargs))
        return code, read_json(output)


class LiteratureAuditValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def finding_codes(report: dict[str, Any]) -> set[str]:
        return {finding["code"] for finding in report["findings"]}

    def test_current_draft_audit_passes(self) -> None:
        fixture = LiteratureFixture(self.root)
        code, report = fixture.run()
        self.assertEqual(code, 0)
        self.assertEqual(report["gate_local_status"], "pass")
        self.assertNotIn("delivery_status", report)
        self.assertFalse(report["whole_manuscript_delivery_authorized"])
        self.assertEqual(
            report["independence_assurance"],
            {
                "attested": True,
                "proven": False,
                "status": "structurally_consistent_file_attestation",
                "note": "Canonical file artifacts verify the internal consistency of declared identities and hash bindings; they cannot prove that the declared runtime actor list is complete or that agent isolation occurred.",
            },
        )
        self.assertEqual(
            report["derived_forbidden_native_agent_ids"],
            sorted(fixture.core_agents),
        )

    def test_current_final_audit_passes(self) -> None:
        fixture = LiteratureFixture(self.root, mode="final")
        code, report = fixture.run()
        self.assertEqual(code, 0)
        self.assertEqual(report["gate_local_status"], "pass")

    def test_missing_core_registry_is_audit_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root, with_core_registry=False)
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertEqual(report["gate_local_status"], "audit_incomplete")
        self.assertIn(
            "core_assignment_registry_missing", self.finding_codes(report)
        )

    def test_missing_reviewer_is_audit_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root)
        payload = read_json(fixture.literature_audit)
        payload.pop("reviewer")
        write_json(fixture.literature_audit, payload)
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertEqual(report["gate_local_status"], "audit_incomplete")
        self.assertIn("literature_reviewer_missing", self.finding_codes(report))

    def test_stale_manuscript_is_audit_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root)
        fixture.manuscript.write_text(
            fixture.manuscript.read_text(encoding="utf-8") + "New sentence.\n",
            encoding="utf-8",
        )
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertEqual(report["gate_local_status"], "audit_incomplete")

    def test_punctuation_change_makes_every_prior_hash_stale(self) -> None:
        fixture = LiteratureFixture(self.root)
        fixture.manuscript.write_text(
            fixture.manuscript.read_text(encoding="utf-8").replace(".", "!", 1),
            encoding="utf-8",
        )
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertEqual(report["gate_local_status"], "audit_incomplete")
        self.assertIn("citation_report_input_stale", self.finding_codes(report))

    def test_core_reviewer_reuse_is_audit_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root)
        assignment = read_json(fixture.assignment)
        assignment["native_agent_id"] = fixture.core_agents[0]
        write_json(fixture.assignment, assignment)
        role_audit = read_json(fixture.literature_audit)
        role_audit["reviewer"]["native_agent_id"] = fixture.core_agents[0]
        write_json(fixture.literature_audit, role_audit)
        fixture.rebind_assignment_and_audit()
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn("literature_reviewer_reused", self.finding_codes(report))

    def test_forged_core_registry_is_audit_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root)
        core = read_json(fixture.core_registry)
        core["manifest_id"] = "forged-manifest"
        core["manifest_sha256"] = "0" * 64
        core["assignments"][0]["target_id"] = "forged-packet"
        write_json(fixture.core_registry, core)
        fixture.rebind_assignment_and_audit()
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn(
            "core_assignment_registry_binding_invalid",
            self.finding_codes(report),
        )
        self.assertFalse(report["independence_assurance"]["attested"])

    def test_forged_qa_manifest_is_not_a_canonical_replay(self) -> None:
        fixture = LiteratureFixture(self.root)
        manifest = read_json(fixture.qa_manifest)
        manifest["qa_mode"] = "bounded_change"
        manifest["task_classification"]["qa_mode"] = "bounded_change"
        manifest["packets"] = [
            {
                "packet_id": "attacker-packet",
                "packet_sha256": "a" * 64,
                "role": "attacker_invented_role",
            }
        ]
        write_json(fixture.qa_manifest, manifest)
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn(
            "qa_manifest_not_canonical_replay", self.finding_codes(report)
        )
        self.assertFalse(report["independence_assurance"]["attested"])

    def test_controller_cannot_be_literature_reviewer(self) -> None:
        fixture = LiteratureFixture(self.root)
        assignment = read_json(fixture.assignment)
        assignment["native_agent_id"] = assignment["controller_id"]
        write_json(fixture.assignment, assignment)
        role_audit = read_json(fixture.literature_audit)
        role_audit["reviewer"]["native_agent_id"] = assignment[
            "controller_id"
        ]
        write_json(fixture.literature_audit, role_audit)
        fixture.rebind_assignment_and_audit()
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn("literature_reviewer_reused", self.finding_codes(report))

    def test_core_task_id_cannot_be_reused(self) -> None:
        fixture = LiteratureFixture(self.root)
        assignment = read_json(fixture.assignment)
        assignment["task_id"] = "core-task-1"
        write_json(fixture.assignment, assignment)
        role_audit = read_json(fixture.literature_audit)
        role_audit["reviewer"]["task_id"] = "core-task-1"
        write_json(fixture.literature_audit, role_audit)
        fixture.rebind_assignment_and_audit()
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn("literature_task_reused", self.finding_codes(report))

    def test_core_assignment_id_cannot_be_reused(self) -> None:
        fixture = LiteratureFixture(self.root)
        assignment = read_json(fixture.assignment)
        assignment["assignment_id"] = "core-assignment-1"
        write_json(fixture.assignment, assignment)
        fixture.rebind_assignment_and_audit()
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn(
            "literature_assignment_id_reused", self.finding_codes(report)
        )

    def test_invalid_json_is_audit_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root)
        fixture.literature_audit.write_text("{not-json", encoding="utf-8")
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn("invalid_json", self.finding_codes(report))

    def test_invalid_schema_is_audit_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root)
        payload = read_json(fixture.literature_audit)
        payload["schema_version"] = "2.0"
        write_json(fixture.literature_audit, payload)
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn("schema_identity_invalid", self.finding_codes(report))

    def test_assignment_input_hash_mismatch_is_audit_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root)
        assignment = read_json(fixture.assignment)
        assignment["input_hashes"]["manuscript_sha256"] = "0" * 64
        write_json(fixture.assignment, assignment)
        role_audit = read_json(fixture.literature_audit)
        role_audit["assignment_sha256"] = citation_auditor.sha256_file(
            fixture.assignment
        )
        write_json(fixture.literature_audit, role_audit)
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn("input_hash_binding_invalid", self.finding_codes(report))

    def test_audit_assignment_hash_stale_is_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root)
        assignment = read_json(fixture.assignment)
        assignment["independence_basis"] += " Updated."
        write_json(fixture.assignment, assignment)
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn(
            "literature_audit_assignment_stale", self.finding_codes(report)
        )

    def test_reviewer_task_mismatch_is_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root)
        payload = read_json(fixture.literature_audit)
        payload["reviewer"]["task_id"] = "another-task"
        write_json(fixture.literature_audit, payload)
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn(
            "literature_reviewer_assignment_mismatch",
            self.finding_codes(report),
        )

    def test_audit_cannot_predate_assignment(self) -> None:
        fixture = LiteratureFixture(self.root)
        payload = read_json(fixture.literature_audit)
        payload["generated_at"] = "2020-08-03T12:02:59+08:00"
        write_json(fixture.literature_audit, payload)
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn("literature_audit_time_invalid", self.finding_codes(report))

    def test_future_assignment_and_audit_are_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root)
        assignment = read_json(fixture.assignment)
        assignment["assigned_at"] = "2099-08-03T12:03:00+08:00"
        write_json(fixture.assignment, assignment)
        role_audit = read_json(fixture.literature_audit)
        role_audit["generated_at"] = "2099-08-03T12:04:00+08:00"
        write_json(fixture.literature_audit, role_audit)
        fixture.rebind_assignment_and_audit()
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn("literature_assignment_invalid", self.finding_codes(report))

    def test_unknown_task_stage_is_audit_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root)
        coverage = read_json(fixture.coverage)
        coverage["task_stage"] = "totally_unknown_stage"
        write_json(fixture.coverage, coverage)
        manifest = read_json(fixture.qa_manifest)
        manifest["task_classification"]["task_stage"] = (
            "totally_unknown_stage"
        )
        write_json(fixture.qa_manifest, manifest)
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn(
            "literature_task_stage_authority_mismatch",
            self.finding_codes(report),
        )

    def test_core_identity_whitespace_is_rejected(self) -> None:
        fixture = LiteratureFixture(self.root)
        core = read_json(fixture.core_registry)
        core["assignments"][0]["task_id"] += " "
        core["assignments"][1]["assignment_id"] += " "
        write_json(fixture.core_registry, core)
        fixture.rebind_assignment_and_audit()
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn("core_assignment_registry_invalid", self.finding_codes(report))

    def test_final_audit_cannot_downgrade_to_draft_mode(self) -> None:
        fixture = LiteratureFixture(
            self.root, mode="draft", task_stage="final_audit"
        )
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn("final_audit_mode_downgrade", self.finding_codes(report))

    def test_role_task_stage_must_match_authorities(self) -> None:
        fixture = LiteratureFixture(self.root)
        payload = read_json(fixture.literature_audit)
        payload["task_stage"] = "local_edit"
        write_json(fixture.literature_audit, payload)
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn(
            "literature_audit_identity_invalid", self.finding_codes(report)
        )

    def test_draft_rejects_extra_final_check(self) -> None:
        fixture = LiteratureFixture(self.root)
        payload = read_json(fixture.literature_audit)
        payload["checks"]["final_bibliography_closed"] = False
        write_json(fixture.literature_audit, payload)
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn(
            "literature_checks_scope_invalid", self.finding_codes(report)
        )
        self.assertNotIn(
            "literature_findings_malformed", self.finding_codes(report)
        )

    def test_coverage_gap_maps_to_fail(self) -> None:
        fixture = LiteratureFixture(self.root)
        fixture.set_role_finding(
            "coverage_gap", "fail", "applicable_clusters_resolved"
        )
        code, report = fixture.run()
        self.assertEqual(code, 1)
        self.assertEqual(report["gate_local_status"], "fail")

    def test_fresh_deterministic_and_role_coverage_gap_propagates_fail(self) -> None:
        fixture = LiteratureFixture(self.root)
        coverage = read_json(fixture.coverage)
        coverage["coverage_clusters"][0]["minimum_verified_sources"] = 2
        write_json(fixture.coverage, coverage)
        fixture._build_citation_report(expected_code=1)
        fixture.rebind_assignment_and_audit()
        fixture.set_role_finding(
            "coverage_gap", "fail", "applicable_clusters_resolved"
        )
        code, report = fixture.run()
        self.assertEqual(code, 1)
        self.assertEqual(report["gate_local_status"], "fail")
        self.assertIn(
            "citation_integrity_gate_blocked", self.finding_codes(report)
        )
        copied_codes = {
            finding.get("source_finding_code")
            for finding in report["findings"]
            if finding["code"] == "citation_integrity_finding"
        }
        self.assertIn("coverage_cluster_gap", copied_codes)

    def test_empty_coverage_universe_blocks_combined_validation(self) -> None:
        fixture = LiteratureFixture(self.root)
        coverage = read_json(fixture.coverage)
        coverage["coverage_clusters"] = []
        write_json(fixture.coverage, coverage)
        fixture._build_citation_report(expected_code=4)
        fixture.rebind_assignment_and_audit()
        code, report = fixture.run()
        self.assertEqual((code, report["gate_local_status"]), (4, "audit_incomplete"))
        self.assertIn(
            "citation_integrity_gate_blocked", self.finding_codes(report)
        )
        copied_codes = {
            finding.get("source_finding_code")
            for finding in report["findings"]
            if finding["code"] == "citation_integrity_finding"
        }
        self.assertIn("coverage_cluster_universe_missing", copied_codes)
        self.assertIn(
            "coverage_cluster_function_declarations_missing", copied_codes
        )

    def test_unsupported_claim_maps_to_evidence_conflict(self) -> None:
        fixture = LiteratureFixture(self.root)
        fixture.set_role_finding(
            "unsupported_claim",
            "evidence_conflict",
            "claims_supported_at_stated_strength",
        )
        code, report = fixture.run()
        self.assertEqual(code, 6)
        self.assertEqual(report["gate_local_status"], "evidence_conflict")

    def test_combined_report_preserves_every_role_blocker(self) -> None:
        fixture = LiteratureFixture(self.root)
        payload = read_json(fixture.literature_audit)
        payload["checks"]["applicable_clusters_resolved"] = False
        payload["checks"]["claims_supported_at_stated_strength"] = False
        payload["findings"] = [
            {
                "finding_id": "finding-coverage",
                "finding_type": "coverage_gap",
                "evidence": "A required cluster remains empty.",
                "reason": "Synthetic coverage blocker.",
                "severity": "blocking",
                "requires_author_action": True,
            },
            {
                "finding_id": "finding-claim",
                "finding_type": "unsupported_claim",
                "evidence": "The cited source does not support the claim strength.",
                "reason": "Synthetic claim blocker.",
                "severity": "blocking",
                "requires_author_action": True,
            },
        ]
        payload["gate_status"] = "evidence_conflict"
        write_json(fixture.literature_audit, payload)
        code, report = fixture.run()
        self.assertEqual((code, report["gate_local_status"]), (6, "evidence_conflict"))
        copied = {
            finding.get("finding_id")
            for finding in report["findings"]
            if finding["code"] == "literature_role_finding"
        }
        self.assertEqual(copied, {"finding-coverage", "finding-claim"})

    def test_unauthorized_nocite_maps_to_approval_required(self) -> None:
        fixture = LiteratureFixture(self.root)
        fixture.set_role_finding(
            "unauthorized_nocite",
            "approval_required",
            "citekey_registry_ledger_closed",
        )
        code, report = fixture.run()
        self.assertEqual(code, 2)
        self.assertEqual(report["gate_local_status"], "approval_required")

    def test_metric_finding_maps_to_metric_unavailable(self) -> None:
        fixture = LiteratureFixture(self.root)
        fixture.set_role_finding(
            "metric_unavailable",
            "metric_unavailable",
            "applicable_clusters_resolved",
        )
        code, report = fixture.run()
        self.assertEqual(code, 3)
        self.assertEqual(report["gate_local_status"], "metric_unavailable")

    def test_stale_input_finding_maps_to_audit_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root)
        fixture.set_role_finding(
            "stale_or_invalid_input",
            "audit_incomplete",
            "citekey_registry_ledger_closed",
        )
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertEqual(report["gate_local_status"], "audit_incomplete")

    def test_gate_status_must_match_checks_and_findings(self) -> None:
        fixture = LiteratureFixture(self.root)
        fixture.set_role_finding(
            "coverage_gap", "pass", "applicable_clusters_resolved"
        )
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn(
            "literature_gate_status_inconsistent", self.finding_codes(report)
        )

    def test_citation_report_nonpass_is_audit_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root)
        payload = read_json(fixture.citation_report)
        payload["status"] = "fail"
        payload["gate_local_status"] = "fail"
        payload["exit_code"] = 1
        payload["hashes"]["audit_payload_sha256"] = citation_auditor.canonical_hash(
            {key: value for key, value in payload.items() if key != "hashes"}
        )
        write_json(fixture.citation_report, payload)
        fixture.rebind_assignment_and_audit()
        code, report = fixture.run()
        self.assertEqual(code, 4)
        self.assertIn(
            "citation_report_not_canonical_replay", self.finding_codes(report)
        )

    def test_citation_report_cannot_claim_whole_delivery(self) -> None:
        fixture = LiteratureFixture(self.root)
        payload = read_json(fixture.citation_report)
        payload["delivery_status"] = "pass"
        payload["hashes"]["audit_payload_sha256"] = citation_auditor.canonical_hash(
            {key: value for key, value in payload.items() if key != "hashes"}
        )
        write_json(fixture.citation_report, payload)
        fixture.rebind_assignment_and_audit()
        code, report = fixture.run()
        self.assertEqual((code, report["gate_local_status"]), (4, "audit_incomplete"))
        self.assertIn("citation_report_not_current_pass", self.finding_codes(report))

    def test_final_mode_without_visible_bibliography_is_incomplete(self) -> None:
        fixture = LiteratureFixture(self.root, mode="final")
        code, report = fixture.run(include_visible=False)
        self.assertEqual(code, 4)
        self.assertIn(
            "final_visible_bibliography_missing", self.finding_codes(report)
        )

    def test_final_visible_bibliography_must_match_citation_replay(self) -> None:
        fixture = LiteratureFixture(self.root, mode="final")
        other = self.root / "other.bbl"
        other.write_text("\\bibitem{Other2024} Other.\n", encoding="utf-8")
        code, report = fixture.run(visible_override=other)
        self.assertEqual(code, 4)
        self.assertIn("citation_report_input_stale", self.finding_codes(report))

    def test_repeated_validation_is_deterministic(self) -> None:
        fixture = LiteratureFixture(self.root)
        first = self.root / "first.json"
        second = self.root / "second.json"
        first_code, first_report = fixture.run(report=first)
        second_code, second_report = fixture.run(report=second)
        self.assertEqual(first_code, 0)
        self.assertEqual(second_code, 0)
        self.assertEqual(first_report, second_report)
        self.assertEqual(first.read_bytes(), second.read_bytes())


if __name__ == "__main__":
    unittest.main(verbosity=2)
