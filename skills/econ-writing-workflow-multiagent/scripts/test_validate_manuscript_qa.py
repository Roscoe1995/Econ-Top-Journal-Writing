#!/usr/bin/env python3
"""Synthetic regression tests for validate_manuscript_qa.py."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import prepare_manuscript_qa as QA_PREPARER
import audit_manuscript_conservation as CONSERVATION_AUDITOR
from validate_manuscript_qa import (
    GateAudit,
    ROLE_PROTOCOLS,
    ROLE_PROTOCOL_VERSION,
    artifact_depth_question_specs,
    resolve_depth_question_candidate_sections,
    validate_authority_source_adapter,
    validate_conservation_canonical_replay,
    validate_depth_question_evidence_units,
    validate_formula_registry,
    validate_task_stage_artifact_mode,
)


SCRIPT = Path(__file__).with_name("validate_manuscript_qa.py")
PREPARE_SCRIPT = Path(__file__).with_name("prepare_manuscript_qa.py")
AUDIT_SCRIPT = Path(__file__).with_name("audit_manuscript_conservation.py")


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_text(value: str) -> str:
    return digest_bytes(value.encode("utf-8"))


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return digest_bytes(encoded)


class ManuscriptQAValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.candidate = self.write_text(
            "candidate.tex",
            "\\begin{document}\\section{Main}\n\n"
            "Treatment, the registered exposure, increases the outcome within the registered sample.\n"
            "Treatment is defined before the next discussion.\n"
            "\\appendix\n"
            "\\end{document}\n",
        )
        self.contract_payload = {
            "schema_version": "1.0",
            "author_intent_contract": {
                "schema_version": "1.0",
                "intent_contract_id": "contract-1",
                "intent_revision_id": "intent-r1",
                "intent_status": "frozen-current",
                "gate_status": "ready",
                "scope": {"level": "paper", "target_path_or_artifact": "candidate.tex"},
                "propositions": [
                    {
                        "intent_id": "intent-main",
                        "must_express": "Treatment, the registered exposure, increases the outcome within the registered sample.",
                        "claim_type": "associational",
                        "evidence_anchors": ["table-main"],
                    }
                ],
                "definition_registry": [
                    {
                        "definition_id": "definition-treatment",
                        "term": "Treatment",
                        "strictly_before_first_use": False,
                    }
                ],
                "unresolved_material_questions": [],
                "approval_record": {
                    "confirmed_by": "author",
                    "confirmed_at": "2026-08-03T10:00:00+08:00",
                    "confirmed_scope": "complete_author_intent",
                    "confirmation_source": "author message 42",
                    "freeze_authorized_by": "author",
                    "freeze_authorized_at": "2026-08-03T10:00:00+08:00",
                    "explicit_hold_reason": "",
                },
            },
        }
        self.contract = self.write_json("contract.json", self.contract_payload)
        self.contract_hash = digest_bytes(self.contract.read_bytes())
        self.qa_contract = self.write_json(
            "qa-contract.json",
            {
                "qa_contract": {
                    "schema_version": "1.0",
                    "gate_status": "ready",
                    "qa_mode": "exhaustive",
                    "manuscript_path": str(self.candidate),
                    "task_classification": {
                        "task_stage": "full_draft",
                        "qa_mode": "exhaustive",
                        "basis": "Synthetic full-manuscript QA fixture.",
                        "classified_by": "test-controller",
                        "classified_at": "2026-08-03T10:01:00+08:00",
                    },
                    "required_roles": [
                        "author_intent_coverage",
                        "evidence_claim_strength",
                        "definitions_reader_sufficiency",
                        "economic_logic_scope_qualifiers",
                    ],
                    "minimum_high_risk_independent_reviews": 2,
                }
            },
        )
        self.qa_contract_hash = digest_bytes(self.qa_contract.read_bytes())
        self.artifact_contract = self.write_json(
            "artifact-contract-base.json",
            {
                "schema_version": "1.0",
                "task_mode": "full_draft",
                "rewrite_mode": "patch_existing",
                "mature_baseline": False,
                "target_main_source_word_range": [1, 1000],
                "hard_main_text_floor": {"source_words": 1},
                "must_remain_main": [],
                "content_obligations": [
                    {
                        "obligation_id": "intent-main",
                        "content": "The registered positive estimate must remain in the main text.",
                    }
                ],
                "section_cards": [
                    {
                        "section_id": "main",
                        "section_name": "Main",
                        "optional": True,
                        "target_word_range": [1, 1000],
                        "must_remain_main": [
                            {"type": "obligation", "value": "intent-main"}
                        ],
                        "minimum_depth_questions": [
                            "Does the main text explain the registered estimate?"
                        ],
                    }
                ],
                "metric_status": "measured",
                "measurement_contract": {
                    "appendix_boundary": r"\appendix",
                    "source_word_method": "normalized_words",
                },
            },
        )
        self.artifact_contract_hash = digest_bytes(
            self.artifact_contract.read_bytes()
        )
        self.candidate_hash = digest_bytes(self.candidate.read_bytes())
        prepared_document = QA_PREPARER.expand_tex(self.candidate, self.root.resolve())
        self.content_hash = digest_text(prepared_document.text)
        self.unit_one_text = "Treatment, the registered exposure, increases the outcome within the registered sample."
        self.unit_two_text = "Treatment is defined before the next discussion."
        author = self.contract_payload["author_intent_contract"]
        qa = json.loads(self.qa_contract.read_text(encoding="utf-8"))["qa_contract"]
        obligations = QA_PREPARER.extract_obligations(author, qa, {})
        definitions = QA_PREPARER.extract_definitions(author, qa, {})
        prepared_units, prepared_appendix, prepared_formulas = (
            QA_PREPARER.prepare_units(
                prepared_document,
                "tex",
                self.root.resolve(),
                author,
                qa,
                obligations,
                definitions,
            )
        )
        QA_PREPARER.apply_review_scope(prepared_units, "exhaustive", "full_manuscript")
        self.unit_one_id = next(
            unit["unit_id"]
            for unit in prepared_units
            if unit.get("text") == self.unit_one_text and unit.get("type") == "sentence"
        )
        self.unit_two_id = next(
            unit["unit_id"]
            for unit in prepared_units
            if unit.get("text") == self.unit_two_text and unit.get("type") == "sentence"
        )
        self.main_section_id = next(
            unit["unit_id"]
            for unit in prepared_units
            if unit.get("type") == "section"
            and unit.get("section_title") == "Main"
            and unit.get("region") == "main_text"
        )
        role_protocols_sha = canonical_digest(
            {
                "role_protocol_version": ROLE_PROTOCOL_VERSION,
                "role_protocols": ROLE_PROTOCOLS,
            }
        )
        qa_bundle_sha = canonical_digest(
            {
                "author_intent_contract_sha256": self.contract_hash,
                "qa_contract_sha256": self.qa_contract_hash,
                "artifact_contract_sha256": self.artifact_contract_hash,
            }
        )
        identity = {
            "schema_version": "1.0",
            "manuscript_sha256": self.candidate_hash,
            "expanded_sha256": self.content_hash,
            "contract_sha256": self.contract_hash,
            "qa_bundle_sha256": qa_bundle_sha,
            "role_protocols_sha256": role_protocols_sha,
            "formula_registry_sha256": canonical_digest(prepared_formulas),
            "unit_ids_and_hashes": [
                [unit["unit_id"], unit["text_sha256"]]
                for unit in prepared_units
            ],
        }
        manifest_id = QA_PREPARER.stable_id(
            "qamanifest", canonical_digest(identity)
        )
        manuscript_record = {
            "path": str(self.candidate),
            "relative_path": self.candidate.name,
            "sha256": self.candidate_hash,
            "expanded_sha256": self.content_hash,
            "format": "tex",
            "project_root": str(self.root),
        }
        source_files = [
            {
                "path": self.candidate.name,
                "sha256": self.candidate_hash,
                "bytes": len(self.candidate.read_bytes()),
            }
        ]
        self.manifest_payload = {
            "schema_version": "1.0",
            "schema_id": "qa-manifest/1.0",
            "status": "prepared",
            "manifest_id": manifest_id,
            "manuscript_id": QA_PREPARER.stable_id(
                "manuscript", self.candidate_hash, self.content_hash
            ),
            "manuscript_sha256": self.candidate_hash,
            "contract_sha256": self.contract_hash,
            "qa_bundle_sha256": qa_bundle_sha,
            "author_intent_contract_sha256": self.contract_hash,
            "role_protocol_version": ROLE_PROTOCOL_VERSION,
            "role_protocols_sha256": role_protocols_sha,
            "role_protocols": copy.deepcopy(ROLE_PROTOCOLS),
            "formula_registry_sha256": canonical_digest(prepared_formulas),
            "formulas": copy.deepcopy(prepared_formulas),
            "appendix": copy.deepcopy(prepared_appendix),
            "expanded_manuscript_sha256": self.content_hash,
            "qa_contract_sha256": self.qa_contract_hash,
            "artifact_contract_sha256": self.artifact_contract_hash,
            "manuscript": copy.deepcopy(manuscript_record),
            "source": {
                "manuscript": copy.deepcopy(manuscript_record),
                "source_files": copy.deepcopy(source_files),
            },
            "source_files": copy.deepcopy(source_files),
            "inputs": {
                "manuscript": copy.deepcopy(manuscript_record),
                "contract": {
                    "path": str(self.contract),
                    "sha256": self.contract_hash,
                },
                "qa_contract": {
                    "path": str(self.qa_contract),
                    "sha256": self.qa_contract_hash,
                },
                "artifact_contract": {
                    "path": str(self.artifact_contract),
                    "sha256": self.artifact_contract_hash,
                },
            },
            "roles": {
                "author_intent_coverage": {"required": True},
                "evidence_claim_strength": {"required": True},
                "definitions_reader_sufficiency": {"required": True},
                "economic_logic_scope_qualifiers": {"required": True},
            },
            "units": copy.deepcopy(prepared_units),
            "artifact_contract_sha256": self.artifact_contract_hash,
            "evidence_registry_sha256": None,
            "evidence_registry": [],
            "content_obligations": copy.deepcopy(obligations),
            "definition_registry": copy.deepcopy(definitions),
            "content_conservation_ledger": [],
            "packets": [
                {
                    "packet_id": "packet-intent",
                    "role": "author_intent_coverage",
                    "unit_ids": [self.unit_one_id, self.unit_two_id],
                },
                {
                    "packet_id": "packet-evidence",
                    "role": "evidence_claim_strength",
                    "unit_ids": [self.unit_one_id],
                },
                {
                    "packet_id": "packet-definitions",
                    "role": "definitions_reader_sufficiency",
                    "unit_ids": [self.unit_one_id, self.unit_two_id],
                },
                {
                    "packet_id": "packet-economics",
                    "role": "economic_logic_scope_qualifiers",
                    "unit_ids": [self.unit_one_id, self.unit_two_id],
                },
            ],
            "qa_mode": "exhaustive",
            "revision_target_unit_ids": [],
            "review_policy": {
                "minimum_high_risk_independent_reviews": 2,
                "required_semantic_roles": [
                    "author_intent_coverage",
                    "evidence_claim_strength",
                    "definitions_reader_sufficiency",
                    "economic_logic_scope_qualifiers",
                ],
            },
        }
        self.packet_by_role = self.attach_packets(
            self.manifest_payload,
            artifact_contract_hash=self.artifact_contract_hash,
        )
        self.manifest = self.write_json("manifest.json", self.manifest_payload)
        self.manifest_hash = digest_bytes(self.manifest.read_bytes())
        self.base_conservation_gate = self.write_json(
            "base-conservation.json", self.candidate_only_conservation_payload()
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write_text(self, relative: str, value: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
        return path

    def write_json(self, relative: str, payload: dict) -> Path:
        return self.write_text(relative, json.dumps(payload, ensure_ascii=False, sort_keys=True))

    def candidate_only_conservation_payload(
        self,
        *,
        artifact_contract: Path | None = None,
        artifact_contract_hash: str | None = None,
        candidate: Path | None = None,
        candidate_hash: str | None = None,
        content_hash: str | None = None,
    ) -> dict:
        artifact_contract = artifact_contract or self.artifact_contract
        artifact_contract_hash = (
            artifact_contract_hash or self.artifact_contract_hash
        )
        candidate = candidate or self.candidate
        report = CONSERVATION_AUDITOR.audit(
            argparse.Namespace(
                baseline=None,
                candidate=str(candidate),
                project_root=str(self.root),
                contract=str(artifact_contract),
                appendix_marker=r"\appendix",
                word_metric=None,
                max_main_reduction=None,
                min_main_source_words=None,
                baseline_main_pdf_pages=None,
                candidate_main_pdf_pages=None,
                min_main_pdf_pages=None,
                report="unused",
            )
        )
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["inputs"]["contract_sha256"], artifact_contract_hash)
        if candidate_hash is not None:
            self.assertEqual(report["inputs"]["candidate_sha256"], candidate_hash)
        if content_hash is not None:
            self.assertEqual(
                report["inputs"]["candidate_expanded_sha256"], content_hash
            )
        return report

    def exact_conservation_ledger(
        self, baseline: Path, candidate: Path
    ) -> list[dict]:
        """Return a complete unchanged ledger for byte-equivalent fixtures."""

        def inventory(path: Path) -> list[dict]:
            expanded, _, fmt = CONSERVATION_AUDITOR.load_manuscript(
                path, self.root
            )
            main, appendix = CONSERVATION_AUDITOR.split_appendix(
                expanded, r"\appendix", "fixture", fmt
            )
            return (
                CONSERVATION_AUDITOR.substantive_block_inventory(
                    main, "main_text", fmt
                )
                + CONSERVATION_AUDITOR.substantive_block_inventory(
                    appendix, "appendix", fmt
                )
                + CONSERVATION_AUDITOR.substantive_object_inventory(
                    main, "main_text", fmt
                )
                + CONSERVATION_AUDITOR.substantive_object_inventory(
                    appendix, "appendix", fmt
                )
            )

        baseline_inventory = inventory(baseline)
        candidate_by_id = {
            item["block_id"]: item for item in inventory(candidate)
        }
        ledger: list[dict] = []
        for source in baseline_inventory:
            destination = candidate_by_id.get(source["block_id"])
            self.assertIsNotNone(destination)
            self.assertEqual(
                destination["content_sha256"], source["content_sha256"]
            )
            ledger.append(
                {
                    "source_block_id": source["block_id"],
                    "destination": destination["block_id"],
                    "disposition": "unchanged",
                    "status": "pass",
                }
            )
        return ledger

    def refresh_manifest_identity(
        self, manifest_payload: dict, qa_contract: dict
    ) -> None:
        manuscript_record = manifest_payload["inputs"]["manuscript"]
        manuscript_sha = manuscript_record["sha256"]
        expanded_sha = manuscript_record["expanded_sha256"]
        contract_sha = manifest_payload["inputs"]["contract"]["sha256"]
        qa_sha = manifest_payload["inputs"]["qa_contract"]["sha256"]
        artifact_input = manifest_payload["inputs"].get("artifact_contract")
        artifact_sha = (
            artifact_input.get("sha256")
            if isinstance(artifact_input, dict)
            else None
        )
        try:
            roles = QA_PREPARER.role_list(qa_contract)
        except QA_PREPARER.PreparationError:
            roles = list(ROLE_PROTOCOLS)
        role_protocols_sha = canonical_digest(
            {
                "role_protocol_version": ROLE_PROTOCOL_VERSION,
                "role_protocols": {
                    role: ROLE_PROTOCOLS[role] for role in roles
                },
            }
        )
        formula_sha = canonical_digest(manifest_payload.get("formulas", []))
        qa_bundle_sha = canonical_digest(
            {
                "author_intent_contract_sha256": contract_sha,
                "qa_contract_sha256": qa_sha,
                "artifact_contract_sha256": artifact_sha,
            }
        )
        identity = {
            "schema_version": "1.0",
            "manuscript_sha256": manuscript_sha,
            "expanded_sha256": expanded_sha,
            "contract_sha256": contract_sha,
            "qa_bundle_sha256": qa_bundle_sha,
            "role_protocols_sha256": role_protocols_sha,
            "formula_registry_sha256": formula_sha,
            "unit_ids_and_hashes": [
                [unit["unit_id"], unit["text_sha256"]]
                for unit in manifest_payload["units"]
            ],
        }
        manifest_payload.update(
            {
                "manifest_id": QA_PREPARER.stable_id(
                    "qamanifest", canonical_digest(identity)
                ),
                "manuscript_id": QA_PREPARER.stable_id(
                    "manuscript", manuscript_sha, expanded_sha
                ),
                "manuscript_sha256": manuscript_sha,
                "expanded_manuscript_sha256": expanded_sha,
                "contract_sha256": contract_sha,
                "author_intent_contract_sha256": contract_sha,
                "qa_contract_sha256": qa_sha,
                "artifact_contract_sha256": artifact_sha,
                "qa_bundle_sha256": qa_bundle_sha,
                "role_protocols_sha256": role_protocols_sha,
                "formula_registry_sha256": formula_sha,
                "revision_target_unit_ids": (
                    sorted(
                        unit["unit_id"]
                        for unit in manifest_payload["units"]
                        if unit.get("review_target")
                        and unit.get("selected_for_review")
                    )
                    if qa_contract.get("qa_mode") == "bounded_change"
                    else []
                ),
                "review_policy": {
                    "minimum_high_risk_independent_reviews": qa_contract.get(
                        "minimum_high_risk_independent_reviews", 2
                    ),
                    "required_semantic_roles": roles,
                },
            }
        )

    def attach_packets(
        self,
        manifest_payload: dict,
        directory: str = "packets",
        artifact_contract_hash: str | None = None,
    ) -> dict[str, dict]:
        if artifact_contract_hash is None:
            artifact_contract_hash = str(
                manifest_payload.get("artifact_contract_sha256", "")
            )
        records: list[dict] = []
        by_role: dict[str, dict] = {}
        inputs = manifest_payload.get("inputs", {})
        author_path = Path(inputs["contract"]["path"])
        qa_path = Path(inputs["qa_contract"]["path"])
        artifact_record = inputs.get("artifact_contract")
        live_artifact = None
        qa_contract: dict = {}
        try:
            author, _, intent_state = QA_PREPARER.load_contract(
                author_path, "author_intent_contract"
            )
            qa_contract, _, qa_state = QA_PREPARER.load_contract(
                qa_path, "qa_contract"
            )
            if isinstance(artifact_record, dict) and artifact_record.get("path"):
                live_artifact, _, artifact_state = QA_PREPARER.load_contract(
                    Path(artifact_record["path"]), "artifact_contract"
                )
            else:
                live_artifact, artifact_state = None, {}
            paper_state = QA_PREPARER.merge_paper_state_contexts(
                intent_state, qa_state, artifact_state
            )
            obligations = QA_PREPARER.extract_obligations(
                author, qa_contract, paper_state
            )
            definitions = QA_PREPARER.extract_definitions(
                author, qa_contract, paper_state
            )
            baseline_ledger = QA_PREPARER.conservation_ledger_entries(
                qa_contract, live_artifact, paper_state
            )
            expected_context = QA_PREPARER.contract_context(
                author,
                qa_contract,
                paper_state,
                live_artifact,
                obligations,
                definitions,
                baseline_ledger,
                manifest_payload.get("evidence_registry", []),
            )
            manifest_payload["content_obligations"] = copy.deepcopy(obligations)
            manifest_payload["definition_registry"] = copy.deepcopy(definitions)
            manifest_payload["content_conservation_ledger"] = copy.deepcopy(
                baseline_ledger
            )
        except QA_PREPARER.PreparationError:
            expected_context = {}
        self.refresh_manifest_identity(manifest_payload, qa_contract)
        evidence_source = inputs.get("evidence_registry")
        evidence_hash = (
            evidence_source.get("sha256")
            if isinstance(evidence_source, dict)
            else None
        )
        max_units_per_packet = int(qa_contract.get("max_units_per_packet", 25))
        max_packet_bytes = int(qa_contract.get("max_packet_bytes", 240_000))
        for role, role_settings in manifest_payload["roles"].items():
            if not role_settings.get("required", True):
                continue
            assigned = [
                copy.deepcopy(unit)
                for unit in manifest_payload["units"]
                if role in unit.get("required_roles", [])
                and unit.get("review_target", True)
                and unit.get("selected_for_review", True) is not False
            ]
            packet_id = f"packet-{role}"
            packet_payload = {
                "schema_version": "1.0",
                "schema_id": "qa-audit-packet/1.0",
                "packet_id": packet_id,
                "manifest_id": manifest_payload["manifest_id"],
                "manifest_sha256": None,
                "manuscript_sha256": self.candidate_hash,
                "content_sha256": self.content_hash,
                "contract_sha256": self.contract_hash,
                "qa_contract_sha256": manifest_payload[
                    "qa_contract_sha256"
                ],
                "role": role,
                "batch_index": 1,
                "batch_count": 1,
                "role_protocol_version": ROLE_PROTOCOL_VERSION,
                "role_protocol_sha256": canonical_digest(ROLE_PROTOCOLS[role]),
                "formula_registry_sha256": manifest_payload[
                    "formula_registry_sha256"
                ],
                "evidence_registry_sha256": evidence_hash,
                "evidence_registry_source": copy.deepcopy(evidence_source),
                "formula_context": [],
                "required_checks": copy.deepcopy(
                    ROLE_PROTOCOLS[role]["required_criterion_ids"]
                ),
                "role_protocol": copy.deepcopy(ROLE_PROTOCOLS[role]),
                "contract_context": copy.deepcopy(expected_context),
                "units": assigned,
            }
            if artifact_contract_hash:
                packet_payload["artifact_contract_sha256"] = artifact_contract_hash
                packet_payload["artifact_contract"] = copy.deepcopy(live_artifact)
            packet_hash = canonical_digest(packet_payload)
            packet_payload["packet_sha256"] = packet_hash
            packet_path = self.write_json(f"{directory}/{role}.json", packet_payload)
            packet_bytes = packet_path.stat().st_size
            record = {
                "packet_id": packet_id,
                "role": role,
                "batch_index": 1,
                "batch_count": 1,
                "path": str(packet_path.relative_to(self.root)),
                "packet_sha256": packet_hash,
                "packet_bytes": packet_bytes,
                "role_protocol_version": ROLE_PROTOCOL_VERSION,
                "role_protocol_sha256": canonical_digest(ROLE_PROTOCOLS[role]),
                "required_checks": copy.deepcopy(
                    ROLE_PROTOCOLS[role]["required_criterion_ids"]
                ),
                "unit_ids": [unit["unit_id"] for unit in assigned],
            }
            records.append(record)
            by_role[role] = record
        manifest_payload["packets"] = records
        manifest_payload["packetization"] = {
            "max_units_per_packet": max_units_per_packet,
            "max_packet_bytes": max_packet_bytes,
            "packet_count": len(records),
        }
        return by_role

    def unit_review(
        self,
        unit_id: str,
        verdict: str = "pass",
        requires_author_action: bool = False,
        revision_id: str | None = None,
        criterion_id: str = "intent_coverage",
    ) -> dict:
        unit = next(
            item for item in self.manifest_payload["units"] if item["unit_id"] == unit_id
        )
        result = {
            "unit_id": unit_id,
            "criterion_id": criterion_id,
            "verdict": verdict,
            "source_span": copy.deepcopy(
                unit.get("source")
                or {"unit_id": unit_id, "text_sha256": unit["text_sha256"]}
            ),
            "evidence": "frozen contract and current paragraph",
            "reason": "The recorded verdict follows from the supplied audit packet.",
            "severity": "none" if verdict == "pass" else "major",
            "confidence": 0.95,
            "requires_author_action": requires_author_action,
        }
        if revision_id is not None:
            result["revision_id"] = revision_id
        return result

    def result_payload(
        self,
        result_id: str,
        reviewer_id: str,
        role: str,
        independence_key: str,
        units: list[str],
        *,
        ledgers: dict | None = None,
        verdicts: dict[str, str] | None = None,
        revision_id: str | None = None,
        conflicts: list[dict] | None = None,
        manifest_hash: str | None = None,
    ) -> dict:
        verdicts = verdicts or {}
        payload = {
            "schema_version": "1.0",
            "result_id": result_id,
            "manifest_id": self.manifest_payload["manifest_id"],
            "manifest_sha256": manifest_hash or self.manifest_hash,
            "manuscript_sha256": self.candidate_hash,
            "content_sha256": self.content_hash,
            "contract_sha256": self.contract_hash,
            "qa_contract_sha256": self.qa_contract_hash,
            "artifact_contract_sha256": self.artifact_contract_hash,
            "packet_id": self.packet_by_role[role]["packet_id"],
            "packet_sha256": self.packet_by_role[role]["packet_sha256"],
            "status": "complete",
            "reviewer": {
                "reviewer_id": reviewer_id,
                "role": role,
                "independence_key": independence_key,
            },
            "unit_reviews": [
                self.unit_review(
                    unit_id,
                    verdicts.get(unit_id, "pass"),
                    revision_id=revision_id,
                    criterion_id=criterion_id,
                )
                for unit_id in units
                for criterion_id in ROLE_PROTOCOLS[role]["required_criterion_ids"]
            ],
            "ledgers": ledgers or {},
            "conflicts": conflicts or [],
        }
        if revision_id is not None:
            payload["revision_id"] = revision_id
        return payload

    def passing_result_paths(self, *, include_ledgers: bool = True) -> list[Path]:
        intent_ledgers = {}
        evidence_ledgers = {}
        definition_ledgers = {}
        if include_ledgers:
            intent_ledgers = {
                "intent_to_text": [
                    {
                        "intent_id": "intent-main",
                        "unit_ids": [self.unit_one_id],
                        "status": "covered",
                    }
                ],
                "text_to_intent": [
                    {
                        "unit_id": self.unit_one_id,
                        "intent_ids": ["intent-main"],
                        "status": "authorized",
                    },
                    {"unit_id": self.unit_two_id, "status": "non_claim"},
                    {"unit_id": self.main_section_id, "status": "non_claim"},
                ],
            }
            evidence_ledgers = {
                "text_to_evidence": [
                    {
                        "unit_id": self.unit_one_id,
                        "evidence_ids": ["table-main"],
                        "status": "supported",
                    }
                ],
            }
            definition_ledgers = {
                "definitions": [
                    {
                        "definition_id": "definition-treatment",
                        "definition_unit_id": self.unit_one_id,
                        "first_use_unit_id": self.unit_one_id,
                        "status": "verified",
                    }
                ],
            }
        first = self.write_json(
            "reviews/intent.json",
            self.result_payload(
                "result-intent",
                "reviewer-intent",
                "author_intent_coverage",
                "isolated-context-a",
                [self.unit_one_id, self.unit_two_id, self.main_section_id],
                ledgers=intent_ledgers,
            ),
        )
        second = self.write_json(
            "reviews/evidence.json",
            self.result_payload(
                "result-evidence",
                "reviewer-evidence",
                "evidence_claim_strength",
                "isolated-context-b",
                [self.unit_one_id, self.unit_two_id, self.main_section_id],
                ledgers=evidence_ledgers,
            ),
        )
        third = self.write_json(
            "reviews/definitions.json",
            self.result_payload(
                "result-definitions",
                "reviewer-definitions",
                "definitions_reader_sufficiency",
                "isolated-context-c",
                [self.unit_one_id, self.unit_two_id, self.main_section_id],
                ledgers=definition_ledgers,
            ),
        )
        fourth = self.write_json(
            "reviews/economic-logic.json",
            self.result_payload(
                "result-economic-logic",
                "reviewer-economic-logic",
                "economic_logic_scope_qualifiers",
                "isolated-context-d",
                [self.unit_one_id, self.unit_two_id, self.main_section_id],
            ),
        )
        return [first, second, third, fourth]

    def rebind_results(
        self,
        paths: list[Path],
        manifest: Path,
        *,
        contract_hash: str | None = None,
        qa_contract_hash: str | None = None,
        content_hash: str | None = None,
        artifact_contract_hash: str | None = None,
    ) -> list[Path]:
        manifest_hash = digest_bytes(manifest.read_bytes())
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        rebound: list[Path] = []
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            role = payload["reviewer"]["role"]
            payload["manifest_id"] = manifest_payload["manifest_id"]
            payload["manifest_sha256"] = manifest_hash
            payload["contract_sha256"] = contract_hash or self.contract_hash
            payload["qa_contract_sha256"] = qa_contract_hash or self.qa_contract_hash
            payload["content_sha256"] = content_hash or self.content_hash
            effective_artifact_hash = (
                self.artifact_contract_hash
                if artifact_contract_hash is None
                else artifact_contract_hash
            )
            if effective_artifact_hash:
                payload["artifact_contract_sha256"] = effective_artifact_hash
            else:
                payload.pop("artifact_contract_sha256", None)
            payload["packet_id"] = self.packet_by_role[role]["packet_id"]
            payload["packet_sha256"] = self.packet_by_role[role]["packet_sha256"]
            rebound.append(self.write_json(str(path.relative_to(self.root)), payload))
        return rebound

    def rewrite_packet(
        self,
        manifest_payload: dict,
        role: str,
        directory: str,
        transform,
    ) -> dict:
        """Rewrite one packet and keep its manifest record hash/size exact."""

        record = next(
            item for item in manifest_payload["packets"] if item["role"] == role
        )
        payload = json.loads(
            (self.root / record["path"]).read_text(encoding="utf-8")
        )
        transform(payload)
        scope = dict(payload)
        scope.pop("packet_sha256", None)
        packet_hash = canonical_digest(scope)
        payload["packet_sha256"] = packet_hash
        packet_path = self.write_json(
            f"{directory}/{role}.json", payload
        )
        record.update(
            {
                "path": str(packet_path.relative_to(self.root)),
                "packet_sha256": packet_hash,
                "packet_bytes": packet_path.stat().st_size,
            }
        )
        self.packet_by_role[role] = record
        return record

    def passing_result_paths_for_units(
        self, unit_ids: list[str], directory: str
    ) -> list[Path]:
        intent_ledgers = {
            "intent_to_text": [
                {
                    "intent_id": "intent-main",
                    "unit_ids": [self.unit_one_id],
                    "status": "covered",
                }
            ],
            "text_to_intent": [
                (
                    {
                        "unit_id": unit_id,
                        "intent_ids": ["intent-main"],
                        "status": "authorized",
                    }
                    if unit_id == self.unit_one_id
                    else {"unit_id": unit_id, "status": "non_claim"}
                )
                for unit_id in unit_ids
            ],
        }
        ledgers_by_role = {
            "author_intent_coverage": intent_ledgers,
            "evidence_claim_strength": {
                "text_to_evidence": [
                    {
                        "unit_id": self.unit_one_id,
                        "evidence_ids": ["table-main"],
                        "status": "supported",
                    }
                ]
            },
            "definitions_reader_sufficiency": {
                "definitions": [
                    {
                        "definition_id": "definition-treatment",
                        "definition_unit_id": self.unit_one_id,
                        "first_use_unit_id": self.unit_one_id,
                        "status": "verified",
                    }
                ]
            },
            "economic_logic_scope_qualifiers": {},
        }
        paths: list[Path] = []
        for index, role in enumerate(ROLE_PROTOCOLS, 1):
            packet_path = self.root / self.packet_by_role[role]["path"]
            packet_units = [
                unit["unit_id"]
                for unit in json.loads(
                    packet_path.read_text(encoding="utf-8")
                )["units"]
            ]
            payload = self.result_payload(
                f"result-{directory}-{index}",
                f"reviewer-{directory}-{role}",
                role,
                f"isolated-{directory}-{role}",
                packet_units,
                ledgers=ledgers_by_role[role],
            )
            paths.append(
                self.write_json(f"{directory}/{role}.json", payload)
            )
        return paths

    def split_author_packet_bundle(self) -> tuple[Path, list[Path]]:
        """Build two deterministic batches for one role and matching results."""

        original_paths = self.passing_result_paths()
        original_author = json.loads(original_paths[0].read_text(encoding="utf-8"))
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["packets"] = [
            item
            for item in manifest_payload["packets"]
            if item["role"] != "author_intent_coverage"
        ]
        base_author_packet = json.loads(
            (self.root / self.packet_by_role["author_intent_coverage"]["path"]).read_text(
                encoding="utf-8"
            )
        )
        author_records = []
        author_batches = (
            (self.unit_one_id, self.main_section_id),
            (self.unit_two_id,),
        )
        for index, unit_ids in enumerate(author_batches, 1):
            packet_units = [
                next(
                    item
                    for item in manifest_payload["units"]
                    if item["unit_id"] == unit_id
                )
                for unit_id in unit_ids
            ]
            packet_payload = {
                "schema_version": "1.0",
                "schema_id": "qa-audit-packet/1.0",
                "packet_id": f"packet-author-batch-{index}",
                "manifest_id": manifest_payload["manifest_id"],
                "manifest_sha256": None,
                "manuscript_sha256": self.candidate_hash,
                "content_sha256": self.content_hash,
                "contract_sha256": self.contract_hash,
                "qa_contract_sha256": self.qa_contract_hash,
                "artifact_contract_sha256": self.artifact_contract_hash,
                "artifact_contract": (
                    lambda value: value.get("artifact_contract", value)
                )(json.loads(self.artifact_contract.read_text(encoding="utf-8"))),
                "role": "author_intent_coverage",
                "batch_index": index,
                "batch_count": len(author_batches),
                "role_protocol_version": ROLE_PROTOCOL_VERSION,
                "role_protocol_sha256": canonical_digest(
                    ROLE_PROTOCOLS["author_intent_coverage"]
                ),
                "required_checks": copy.deepcopy(
                    ROLE_PROTOCOLS["author_intent_coverage"][
                        "required_criterion_ids"
                    ]
                ),
                "role_protocol": copy.deepcopy(
                    ROLE_PROTOCOLS["author_intent_coverage"]
                ),
                "formula_registry_sha256": manifest_payload[
                    "formula_registry_sha256"
                ],
                "evidence_registry_sha256": base_author_packet.get(
                    "evidence_registry_sha256"
                ),
                "evidence_registry_source": copy.deepcopy(
                    base_author_packet.get("evidence_registry_source")
                ),
                "formula_context": [],
                "contract_context": copy.deepcopy(
                    base_author_packet["contract_context"]
                ),
                "units": copy.deepcopy(packet_units),
            }
            packet_hash = canonical_digest(packet_payload)
            packet_payload["packet_sha256"] = packet_hash
            packet_path = self.write_json(
                f"split-packets/author-{index}.json", packet_payload
            )
            packet_bytes = packet_path.stat().st_size
            author_records.append(
                {
                    "packet_id": packet_payload["packet_id"],
                    "role": "author_intent_coverage",
                    "batch_index": index,
                    "batch_count": len(author_batches),
                    "path": str(packet_path.relative_to(self.root)),
                    "packet_sha256": packet_hash,
                    "packet_bytes": packet_bytes,
                    "role_protocol_version": ROLE_PROTOCOL_VERSION,
                    "role_protocol_sha256": canonical_digest(
                        ROLE_PROTOCOLS["author_intent_coverage"]
                    ),
                    "required_checks": copy.deepcopy(
                        ROLE_PROTOCOLS["author_intent_coverage"][
                            "required_criterion_ids"
                        ]
                    ),
                    "unit_ids": list(unit_ids),
                }
            )
        manifest_payload["packets"].extend(author_records)
        manifest_payload["packetization"]["packet_count"] = len(
            manifest_payload["packets"]
        )
        manifest = self.write_json("manifest-split-author.json", manifest_payload)
        manifest_hash = digest_bytes(manifest.read_bytes())

        results: list[Path] = []
        for index, (record, unit_ids) in enumerate(
            zip(author_records, author_batches), 1
        ):
            payload = copy.deepcopy(original_author)
            payload["result_id"] = f"result-intent-batch-{index}"
            payload["manifest_sha256"] = manifest_hash
            payload["packet_id"] = record["packet_id"]
            payload["packet_sha256"] = record["packet_sha256"]
            payload["unit_reviews"] = [
                item
                for item in payload["unit_reviews"]
                if item["unit_id"] in unit_ids
            ]
            if self.unit_one_id in unit_ids:
                payload["ledgers"]["text_to_intent"] = [
                    item
                    for item in payload["ledgers"]["text_to_intent"]
                    if item["unit_id"] in unit_ids
                ]
            else:
                payload["ledgers"] = {
                    "text_to_intent": [
                        item
                        for item in original_author["ledgers"]["text_to_intent"]
                        if item["unit_id"] in unit_ids
                    ]
                }
            results.append(self.write_json(f"split-reviews/author-{index}.json", payload))

        for path in original_paths[1:]:
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["manifest_sha256"] = manifest_hash
            results.append(
                self.write_json(f"split-reviews/{path.name}", payload)
            )
        return manifest, results

    def build_assignment_registry(
        self, manifest: Path
    ) -> tuple[Path, str, dict[str, dict], dict | None]:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        assignments: list[dict] = []
        packet_assignments: dict[str, dict] = {}
        role_agents: dict[str, str] = {}
        for index, packet in enumerate(payload.get("packets", []), 1):
            role = packet["role"]
            native_agent_id = role_agents.setdefault(role, f"native-agent-{role}")
            record = {
                "assignment_kind": "semantic_packet",
                "target_id": packet["packet_id"],
                "target_sha256": packet["packet_sha256"],
                "packet_id": packet["packet_id"],
                "packet_sha256": packet["packet_sha256"],
                "role": role,
                "assignment_id": f"assignment-{packet['packet_id']}",
                "native_agent_id": native_agent_id,
                "task_id": f"native-task-{index}-{packet['packet_id']}",
                "assigned_at": "2026-08-03T10:02:00+08:00",
            }
            assignments.append(record)
            packet_assignments[packet["packet_id"]] = record
        main_assignment: dict | None = None
        if payload.get("qa_mode") == "exhaustive":
            main_assignment = {
                "assignment_kind": "main_text_sufficiency",
                "target_id": "main-text-sufficiency",
                "target_sha256": payload["expanded_manuscript_sha256"],
                "assignment_id": "assignment-main-text-sufficiency",
                "native_agent_id": "native-agent-main-text-sufficiency",
                "task_id": "native-task-main-text-sufficiency",
                "assigned_at": "2026-08-03T10:02:30+08:00",
            }
            assignments.append(main_assignment)
        registry_payload = {
            "schema_version": "1.0",
            "schema_id": "qa-assignment-registry/1.0",
            "status": "assigned",
            "manifest_id": payload["manifest_id"],
            "manifest_sha256": digest_bytes(manifest.read_bytes()),
            "assignments": assignments,
        }
        path = self.write_json(
            f"runtime/{manifest.stem}-assignment-registry.json",
            registry_payload,
        )
        return path, digest_bytes(path.read_bytes()), packet_assignments, main_assignment

    def bind_review_assignments(
        self,
        review_paths: list[Path],
        registry_hash: str,
        packet_assignments: dict[str, dict],
    ) -> None:
        files: list[Path] = []
        for path in review_paths:
            if path.is_dir():
                files.extend(sorted(path.rglob("*.json")))
            else:
                files.append(path)
        for path in files:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            assignment = packet_assignments.get(payload.get("packet_id"))
            if assignment is None:
                continue
            payload["assignment_registry_sha256"] = registry_hash
            payload["assignment_id"] = assignment["assignment_id"]
            reviewer = payload.setdefault("reviewer", {})
            reviewer["native_agent_id"] = assignment["native_agent_id"]
            reviewer["task_id"] = assignment["task_id"]
            self.write_json(str(path.relative_to(self.root)), payload)

    def build_main_text_audit(
        self,
        manifest: Path,
        contract: Path,
        candidate: Path,
        registry_hash: str,
        main_assignment: dict,
        conservation_gate: Path | None,
    ) -> Path:
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        artifact_hash = manifest_payload.get("artifact_contract_sha256", "")
        artifact_record = manifest_payload.get("inputs", {}).get(
            "artifact_contract"
        )
        artifact_contract: dict = {}
        if isinstance(artifact_record, dict) and artifact_record.get("path"):
            artifact_contract, _, _ = QA_PREPARER.load_contract(
                Path(artifact_record["path"]), "artifact_contract"
            )
        question_specs = artifact_depth_question_specs(artifact_contract)
        evidence_unit = next(
            (
                unit
                for unit in manifest_payload.get("units", [])
                if unit.get("review_target")
                and unit.get("selected_for_review") is not False
            ),
            None,
        )
        payload = {
            "schema_version": "1.0",
            "schema_id": "main-text-sufficiency-audit/1.0",
            "gate_type": "main_text_sufficiency_and_conservation",
            "result_id": f"main-text-{manifest.stem}",
            "status": "pass",
            "reviewed_at": "2026-08-03T10:03:00+08:00",
            "manifest_id": manifest_payload["manifest_id"],
            "manifest_sha256": digest_bytes(manifest.read_bytes()),
            "candidate_sha256": digest_bytes(candidate.read_bytes()),
            "content_sha256": manifest_payload["expanded_manuscript_sha256"],
            "contract_sha256": digest_bytes(contract.read_bytes()),
            "qa_contract_sha256": manifest_payload["qa_contract_sha256"],
            "artifact_contract_sha256": artifact_hash,
            "assignment_registry_sha256": registry_hash,
            "assignment_id": main_assignment["assignment_id"],
            "conservation_gate_sha256": (
                digest_bytes(conservation_gate.read_bytes())
                if conservation_gate is not None
                else None
            ),
            "reviewer": {
                "reviewer_id": "reviewer-main-text-sufficiency",
                "role": "main_text_sufficiency_and_conservation",
                "independence_key": "isolated-context-main-text",
                "native_agent_id": main_assignment["native_agent_id"],
                "task_id": main_assignment["task_id"],
            },
            "checklist": {
                key: True
                for key in (
                    "main_text_self_contained",
                    "definitions_and_assumptions_sufficient",
                    "data_model_sample_explained",
                    "economic_interpretation_present",
                    "required_content_in_main_text",
                    "appendix_moves_authorized",
                    "baseline_content_conserved",
                    "length_and_depth_contract_satisfied",
                )
            },
            "question_reviews": [
                {
                    "card_id": question["card_id"],
                    "question_id": question["question_id"],
                    "question_sha256": question["question_sha256"],
                    "verdict": "pass",
                    "rationale": "The cited live manuscript unit answers this registered depth question.",
                    "evidence_units": [
                        {
                            "unit_id": evidence_unit["unit_id"],
                            "text_sha256": evidence_unit["text_sha256"],
                        }
                    ],
                }
                for question in question_specs
                if evidence_unit is not None
            ],
            "findings": [],
        }
        return self.write_json(f"runtime/{manifest.stem}-main-text.json", payload)

    def run_validator(
        self,
        review_paths: list[Path],
        *,
        manifest: Path | None = None,
        contract: Path | None = None,
        candidate: Path | None = None,
        extra: list[str] | None = None,
        auto_assurance: bool = True,
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        manifest = manifest or self.manifest
        contract = contract or self.contract
        candidate = candidate or self.candidate
        effective_extra = list(extra or [])
        gate_paths = [
            Path(effective_extra[index + 1]).expanduser().resolve()
            for index, value in enumerate(effective_extra[:-1])
            if value == "--upstream-gate"
        ]
        conservation_paths = []
        for path in gate_paths:
            if not path.is_file():
                continue
            try:
                gate_payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if gate_payload.get("schema_id") == "manuscript-conservation-audit/1.0":
                conservation_paths.append(path)
        current_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        if (
            not conservation_paths
            and current_manifest.get("artifact_contract_sha256")
            == self.artifact_contract_hash
        ):
            effective_extra.extend(
                ["--upstream-gate", str(self.base_conservation_gate)]
            )
            conservation_paths = [self.base_conservation_gate]
        if auto_assurance:
            (
                registry,
                registry_hash,
                packet_assignments,
                main_assignment,
            ) = self.build_assignment_registry(manifest)
            self.bind_review_assignments(
                review_paths, registry_hash, packet_assignments
            )
            effective_extra.extend(["--assignment-registry", str(registry)])
            if main_assignment is not None:
                main_audit = self.build_main_text_audit(
                    manifest,
                    contract,
                    candidate,
                    registry_hash,
                    main_assignment,
                    conservation_paths[0] if len(conservation_paths) == 1 else None,
                )
                effective_extra.extend(
                    ["--main-text-sufficiency-audit", str(main_audit)]
                )
        report = self.root / "report.json"
        command = [
            sys.executable,
            str(SCRIPT),
            "--manifest",
            str(manifest),
            "--contract",
            str(contract),
            "--candidate",
            str(candidate),
            "--report",
            str(report),
        ]
        for path in review_paths:
            command.extend(["--review-result", str(path)])
        command.extend(effective_extra)
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        self.assertTrue(report.is_file(), completed.stdout + completed.stderr)
        return completed, json.loads(report.read_text(encoding="utf-8"))

    def assert_status(self, completed: subprocess.CompletedProcess[str], report: dict, status: str) -> None:
        self.assertEqual(report["status"], status, json.dumps(report, ensure_ascii=False, indent=2))
        expected = {
            "pass": 0,
            "fail": 1,
            "approval_required": 2,
            "metric_unavailable": 3,
            "audit_incomplete": 4,
            "clarification_required": 5,
            "evidence_conflict": 6,
        }[status]
        self.assertEqual(completed.returncode, expected, completed.stdout + completed.stderr)
        self.assertEqual(report["exit_code"], expected)

    def test_complete_fresh_independent_audit_passes(self) -> None:
        completed, report = self.run_validator(self.passing_result_paths())
        self.assert_status(completed, report, "pass")
        self.assertEqual(report["coverage"]["reader_visible_units"], 4)
        self.assertEqual(report["coverage"]["valid_review_records"], 51)

    def test_missing_native_assignment_registry_and_fifth_role_fail_closed(self) -> None:
        completed, report = self.run_validator(
            self.passing_result_paths(), auto_assurance=False
        )
        self.assert_status(completed, report, "audit_incomplete")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("assignment_registry_missing", codes)
        self.assertIn("main_text_sufficiency_audit_missing", codes)
        self.assertFalse(report["independence_assurance"]["proven"])

    def test_fifth_role_assignment_is_independent_and_hash_bound(self) -> None:
        paths = self.passing_result_paths()
        registry, _, assignments, main_assignment = self.build_assignment_registry(
            self.manifest
        )
        registry_payload = json.loads(registry.read_text(encoding="utf-8"))
        packet_agent = registry_payload["assignments"][0]["native_agent_id"]
        registry_payload["assignments"][-1]["native_agent_id"] = packet_agent
        registry = self.write_json(
            "runtime/reused-agent-registry.json", registry_payload
        )
        registry_hash = digest_bytes(registry.read_bytes())
        main_assignment = registry_payload["assignments"][-1]
        self.bind_review_assignments(paths, registry_hash, assignments)
        main_audit = self.build_main_text_audit(
            self.manifest,
            self.contract,
            self.candidate,
            registry_hash,
            main_assignment,
            self.base_conservation_gate,
        )
        completed, report = self.run_validator(
            paths,
            auto_assurance=False,
            extra=[
                "--assignment-registry",
                str(registry),
                "--main-text-sufficiency-audit",
                str(main_audit),
            ],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "native_agent_independence_invalid",
            {item["code"] for item in report["findings"]},
        )

        registry, registry_hash, assignments, main_assignment = (
            self.build_assignment_registry(self.manifest)
        )
        self.bind_review_assignments(paths, registry_hash, assignments)
        main_audit = self.build_main_text_audit(
            self.manifest,
            self.contract,
            self.candidate,
            registry_hash,
            main_assignment,
            self.base_conservation_gate,
        )
        main_payload = json.loads(main_audit.read_text(encoding="utf-8"))
        main_payload["checklist"]["main_text_self_contained"] = False
        main_audit = self.write_json("runtime/main-text-failed.json", main_payload)
        completed, report = self.run_validator(
            paths,
            auto_assurance=False,
            extra=[
                "--assignment-registry",
                str(registry),
                "--main-text-sufficiency-audit",
                str(main_audit),
            ],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "main_text_sufficiency_checklist_incomplete",
            {item["code"] for item in report["findings"]},
        )

    def test_fifth_role_closed_nonpass_outcomes_preserve_every_finding(self) -> None:
        for outcome in ("fail", "approval_required", "metric_unavailable"):
            paths = self.passing_result_paths()
            registry, registry_hash, assignments, main_assignment = (
                self.build_assignment_registry(self.manifest)
            )
            self.assertIsNotNone(main_assignment)
            assert main_assignment is not None
            self.bind_review_assignments(paths, registry_hash, assignments)
            main_audit = self.build_main_text_audit(
                self.manifest,
                self.contract,
                self.candidate,
                registry_hash,
                main_assignment,
                self.base_conservation_gate,
            )
            payload = json.loads(main_audit.read_text(encoding="utf-8"))
            payload["status"] = outcome
            payload["checklist"]["main_text_self_contained"] = False
            payload["findings"] = [
                {
                    "status": outcome,
                    "code": f"{outcome}_blocker_one",
                    "message": "First independent main-text blocker.",
                    "section_id": "results",
                },
                {
                    "status": outcome,
                    "code": f"{outcome}_blocker_two",
                    "message": "Second independent main-text blocker.",
                    "severity": "major",
                },
            ]
            main_audit = self.write_json(
                f"runtime/main-text-{outcome}.json", payload
            )
            completed, report = self.run_validator(
                paths,
                auto_assurance=False,
                extra=[
                    "--upstream-gate",
                    str(self.base_conservation_gate),
                    "--assignment-registry",
                    str(registry),
                    "--main-text-sufficiency-audit",
                    str(main_audit),
                ],
            )
            self.assert_status(completed, report, outcome)
            codes = {item["code"] for item in report["findings"]}
            self.assertIn(f"{outcome}_blocker_one", codes)
            self.assertIn(f"{outcome}_blocker_two", codes)
            self.assertTrue(report["independence_assurance"]["attested"])

        paths = self.passing_result_paths()
        registry, registry_hash, assignments, main_assignment = (
            self.build_assignment_registry(self.manifest)
        )
        assert main_assignment is not None
        self.bind_review_assignments(paths, registry_hash, assignments)
        malformed = self.build_main_text_audit(
            self.manifest,
            self.contract,
            self.candidate,
            registry_hash,
            main_assignment,
            self.base_conservation_gate,
        )
        payload = json.loads(malformed.read_text(encoding="utf-8"))
        payload["status"] = "fail"
        payload["checklist"]["main_text_self_contained"] = False
        payload["findings"] = []
        malformed = self.write_json("runtime/main-text-malformed-nonpass.json", payload)
        completed, report = self.run_validator(
            paths,
            auto_assurance=False,
            extra=[
                "--upstream-gate",
                str(self.base_conservation_gate),
                "--assignment-registry",
                str(registry),
                "--main-text-sufficiency-audit",
                str(malformed),
            ],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "main_text_sufficiency_outcome_invalid",
            {item["code"] for item in report["findings"]},
        )

    def test_assignment_and_fifth_role_freshness_fields_fail_closed(self) -> None:
        paths = self.passing_result_paths()
        registry, _, assignments, main_assignment = self.build_assignment_registry(
            self.manifest
        )
        assert main_assignment is not None
        registry_payload = json.loads(registry.read_text(encoding="utf-8"))
        registry_payload["assignments"][0]["assigned_at"] = "not-a-timestamp"
        registry = self.write_json("runtime/assignment-bad-time.json", registry_payload)
        registry_hash = digest_bytes(registry.read_bytes())
        self.bind_review_assignments(paths, registry_hash, assignments)
        main_audit = self.build_main_text_audit(
            self.manifest,
            self.contract,
            self.candidate,
            registry_hash,
            main_assignment,
            self.base_conservation_gate,
        )
        completed, report = self.run_validator(
            paths,
            auto_assurance=False,
            extra=[
                "--upstream-gate",
                str(self.base_conservation_gate),
                "--assignment-registry",
                str(registry),
                "--main-text-sufficiency-audit",
                str(main_audit),
            ],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "assignment_registry_records_invalid",
            {item["code"] for item in report["findings"]},
        )

        paths = self.passing_result_paths()
        registry, registry_hash, assignments, main_assignment = (
            self.build_assignment_registry(self.manifest)
        )
        assert main_assignment is not None
        self.bind_review_assignments(paths, registry_hash, assignments)
        main_audit = self.build_main_text_audit(
            self.manifest,
            self.contract,
            self.candidate,
            registry_hash,
            main_assignment,
            self.base_conservation_gate,
        )
        payload = json.loads(main_audit.read_text(encoding="utf-8"))
        payload["qa_contract_sha256"] = "0" * 64
        payload["conservation_gate_sha256"] = "1" * 64
        main_audit = self.write_json("runtime/main-text-stale-bindings.json", payload)
        completed, report = self.run_validator(
            paths,
            auto_assurance=False,
            extra=[
                "--upstream-gate",
                str(self.base_conservation_gate),
                "--assignment-registry",
                str(registry),
                "--main-text-sufficiency-audit",
                str(main_audit),
            ],
        )
        self.assert_status(completed, report, "audit_incomplete")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("main_text_sufficiency_binding_invalid", codes)
        self.assertIn("main_text_conservation_gate_binding_invalid", codes)

    def test_full_draft_stage_cannot_omit_artifact_contract(self) -> None:
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload.pop("artifact_contract_sha256", None)
        manifest_payload["inputs"].pop("artifact_contract", None)
        self.packet_by_role = self.attach_packets(
            manifest_payload, "missing-artifact-packets", ""
        )
        manifest = self.write_json("manifest-missing-artifact.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, artifact_contract_hash=""
        )
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("required_artifact_contract_missing", codes)
        self.assertIn("artifact_contract_gate_missing", codes)

    def test_manifest_cannot_invent_evidence_id(self) -> None:
        contract_payload = copy.deepcopy(self.contract_payload)
        contract_payload["author_intent_contract"]["propositions"][0][
            "evidence_anchors"
        ] = []
        contract = self.write_json("contract-e-fake.json", contract_payload)
        contract_hash = digest_bytes(contract.read_bytes())
        self.contract_hash = contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["inputs"]["contract"] = {
            "path": str(contract),
            "sha256": contract_hash,
        }
        manifest_payload["evidence_registry"] = ["E_FAKE"]
        self.packet_by_role = self.attach_packets(
            manifest_payload, "e-fake-packets"
        )
        manifest = self.write_json("manifest-e-fake.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, contract_hash=contract_hash
        )
        evidence = json.loads(paths[1].read_text(encoding="utf-8"))
        evidence["ledgers"]["text_to_evidence"][0]["evidence_ids"] = [
            "E_FAKE"
        ]
        paths[1] = self.write_json("reviews/evidence.json", evidence)
        completed, report = self.run_validator(
            paths, manifest=manifest, contract=contract
        )
        self.assert_status(completed, report, "audit_incomplete")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("manifest_evidence_registry_unanchored", codes)
        self.assertIn("unknown_evidence_anchor", codes)

    def test_explicit_author_hold_controls_top_level_even_with_other_blockers(self) -> None:
        contract_payload = copy.deepcopy(self.contract_payload)
        contract_payload["author_intent_contract"]["approval_record"][
            "explicit_hold_reason"
        ] = "Author is reconsidering the claim."
        contract = self.write_json("contract-explicit-hold.json", contract_payload)
        contract_hash = digest_bytes(contract.read_bytes())
        self.contract_hash = contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["inputs"]["contract"] = {
            "path": str(contract),
            "sha256": contract_hash,
        }
        self.packet_by_role = self.attach_packets(
            manifest_payload, "explicit-hold-packets"
        )
        manifest = self.write_json("manifest-explicit-hold.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, contract_hash=contract_hash
        )
        completed, report = self.run_validator(
            paths[:1], manifest=manifest, contract=contract
        )
        self.assert_status(completed, report, "clarification_required")
        self.assertEqual(report["reason_code"], "explicit_author_hold")
        self.assertIn(
            "required_role_missing", {item["code"] for item in report["findings"]}
        )

    def test_definition_first_use_cannot_be_misreported_later(self) -> None:
        paths = self.passing_result_paths()
        definitions = json.loads(paths[2].read_text(encoding="utf-8"))
        definitions["ledgers"]["definitions"][0]["first_use_unit_id"] = self.unit_two_id
        paths[2] = self.write_json("reviews/definitions.json", definitions)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "definition_first_use_mismatch",
            {item["code"] for item in report["findings"]},
        )

    def test_formula_registry_raw_text_is_bound_to_live_source_span(self) -> None:
        source = self.write_text(
            "formula-source.tex",
            "\\begin{equation}\\beta>0\\label{eq:beta}\\end{equation}",
        )
        raw = source.read_text(encoding="utf-8")
        formula = {
            "formula_id": "formula_source_1",
            "format": "tex",
            "raw": raw,
            "normalized_math": raw,
            "raw_sha256": digest_text(raw),
            "normalized_sha256": digest_text(raw),
            "declared_labels": ["eq:beta"],
            "start_in_container": 0,
            "end_in_container": len(raw),
            "source_spans": [
                {
                    "path": source.name,
                    "start_offset": 0,
                    "end_offset": len(raw),
                    "start_line": 1,
                    "end_line": 1,
                }
            ],
        }
        unit = {
            "unit_id": "formula-unit",
            "review_target": True,
            "selected_for_review": True,
            "formula_ids": ["formula_source_1"],
            "text": "[FORMULA:formula_source_1]",
        }
        manifest = {
            "inputs": {"manuscript": {"project_root": str(self.root)}},
            "formulas": [formula],
            "formula_registry_sha256": canonical_digest([formula]),
        }
        audit = GateAudit()
        validate_formula_registry(manifest, self.manifest, [unit], audit)
        self.assertEqual(audit.status(), "pass")

        tampered = copy.deepcopy(formula)
        tampered["raw"] = "$\\beta<0$"
        tampered["normalized_math"] = tampered["raw"]
        tampered["raw_sha256"] = digest_text(tampered["raw"])
        tampered["normalized_sha256"] = digest_text(tampered["raw"])
        manifest["formulas"] = [tampered]
        manifest["formula_registry_sha256"] = canonical_digest([tampered])
        audit = GateAudit()
        validate_formula_registry(manifest, self.manifest, [unit], audit)
        self.assertEqual(audit.status(), "audit_incomplete")
        self.assertIn(
            "formula_registry_record_invalid",
            {item["code"] for item in audit.findings},
        )

        for case_name, labels in (
            ("deleted", []),
            ("forged", ["eq:forged"]),
            ("non-list", "eq:beta"),
        ):
            label_tampered = copy.deepcopy(formula)
            label_tampered["declared_labels"] = labels
            label_manifest = {
                "inputs": {"manuscript": {"project_root": str(self.root)}},
                "formulas": [label_tampered],
                "formula_registry_sha256": canonical_digest([label_tampered]),
            }
            audit = GateAudit()
            validate_formula_registry(label_manifest, self.manifest, [unit], audit)
            self.assertEqual(audit.status(), "audit_incomplete", case_name)
            self.assertIn(
                "formula_registry_record_invalid",
                {item["code"] for item in audit.findings},
                case_name,
            )

    def test_adapter_confirmation_timestamp_requires_timezone_iso(self) -> None:
        source = self.write_text(
            "adapter/author-intent.txt", "The frozen proposition.\n"
        )
        source_hash = digest_bytes(source.read_bytes())
        author_view = {
            "schema_version": "1.0",
            "intent_revision_id": "adapter-r1",
            "artifact_role": "qa_view",
            "authority_source": {
                "path": str(source),
                "sha256": source_hash,
                "format": "text",
            },
        }
        projection_hash = canonical_digest(author_view)
        author_view["adapter_confirmation"] = {
            "status": "confirmed",
            "confirmed_by": "author",
            "confirmed_at": "2026-08-03T10:00:00",
            "confirmed_scope": "complete_author_intent_projection",
            "confirmation_source": "author message 77",
            "authority_source_sha256": source_hash,
            "qa_view_projection_sha256": projection_hash,
            "intent_revision_id": "adapter-r1",
        }
        adapter = self.write_json(
            "adapter/author-view.json", {"author_intent_contract": author_view}
        )
        audit = GateAudit()
        validate_authority_source_adapter(
            {"author_intent_contract": author_view}, adapter, audit
        )
        self.assertEqual(audit.status(), "audit_incomplete")
        self.assertIn(
            "adapter_confirmation_timestamp_invalid",
            {item["code"] for item in audit.findings},
        )

        author_view["adapter_confirmation"]["confirmed_at"] = (
            "2026-08-03T10:00:00+08:00"
        )
        audit = GateAudit()
        validate_authority_source_adapter(
            {"author_intent_contract": author_view}, adapter, audit
        )
        self.assertEqual(audit.status(), "pass")

    def test_translation_alias_and_stage_artifact_mode_mapping_interoperate(self) -> None:
        audit = GateAudit()
        validate_task_stage_artifact_mode(
            {"task_classification": {"task_stage": "document_translation"}},
            {"task_mode": "translation"},
            audit,
        )
        self.assertEqual(audit.status(), "pass")

        audit = GateAudit()
        validate_task_stage_artifact_mode(
            {
                "task_classification": {
                    "task_stage": "final_audit",
                    "artifact_task_mode": "translation",
                }
            },
            {"task_mode": "document_translation"},
            audit,
        )
        self.assertEqual(audit.status(), "pass")

        audit = GateAudit()
        validate_task_stage_artifact_mode(
            {"task_classification": {"task_stage": "document_translation"}},
            {"task_mode": "major_revision"},
            audit,
        )
        self.assertEqual(audit.status(), "audit_incomplete")
        self.assertIn(
            "task_stage_artifact_mode_mismatch",
            {item["code"] for item in audit.findings},
        )

        audit = GateAudit()
        validate_task_stage_artifact_mode(
            {"task_classification": {"task_stage": "final_audit"}},
            {"task_mode": "translation"},
            audit,
        )
        self.assertEqual(audit.status(), "audit_incomplete")
        self.assertIn(
            "final_audit_artifact_mode_unbound",
            {item["code"] for item in audit.findings},
        )

    def test_review_directory_is_accepted(self) -> None:
        paths = self.passing_result_paths()
        completed, report = self.run_validator([paths[0].parent])
        self.assert_status(completed, report, "pass")

    def test_stale_candidate_hash_fails_closed(self) -> None:
        paths = self.passing_result_paths()
        stale = self.write_text("stale.txt", "changed manuscript")
        completed, report = self.run_validator(paths, candidate=stale)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("candidate_manifest_stale", {item["code"] for item in report["findings"]})

    def test_manifest_edit_with_reused_id_invalidates_reviews(self) -> None:
        paths = self.passing_result_paths()
        edited = copy.deepcopy(self.manifest_payload)
        edited["units"][0]["min_independent_reviews"] = 3
        edited_manifest = self.write_json("manifest-edited.json", edited)
        completed, report = self.run_validator(paths, manifest=edited_manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "review_manifest_content_stale",
            {item["code"] for item in report["findings"]},
        )

    def test_missing_independent_reviewer_fails_closed(self) -> None:
        paths = self.passing_result_paths()
        completed, report = self.run_validator([paths[0]])
        self.assert_status(completed, report, "audit_incomplete")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("required_role_missing", codes)
        self.assertIn("independent_review_count_insufficient", codes)

    def test_uncertain_cannot_be_outvoted(self) -> None:
        paths = self.passing_result_paths()
        evidence = json.loads(paths[1].read_text(encoding="utf-8"))
        evidence["unit_reviews"][0]["verdict"] = "uncertain"
        evidence["unit_reviews"][0]["severity"] = "major"
        paths[1] = self.write_json("reviews/evidence.json", evidence)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "clarification_required")

    def test_evidence_conflict_has_explicit_status(self) -> None:
        paths = self.passing_result_paths()
        evidence = json.loads(paths[1].read_text(encoding="utf-8"))
        evidence["unit_reviews"][0]["verdict"] = "evidence_conflict"
        evidence["unit_reviews"][0]["severity"] = "critical"
        paths[1] = self.write_json("reviews/evidence.json", evidence)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "evidence_conflict")

    def test_any_reviewer_failure_blocks_without_majority_vote(self) -> None:
        paths = self.passing_result_paths()
        evidence = json.loads(paths[1].read_text(encoding="utf-8"))
        evidence["unit_reviews"][0]["verdict"] = "fail"
        evidence["unit_reviews"][0]["severity"] = "critical"
        paths[1] = self.write_json("reviews/evidence.json", evidence)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "fail")

    def test_missing_intent_and_nonclaim_ledger_fails_closed(self) -> None:
        completed, report = self.run_validator(self.passing_result_paths(include_ledgers=False))
        self.assert_status(completed, report, "audit_incomplete")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("intent_obligation_unmapped", codes)
        self.assertIn("text_intent_mapping_missing", codes)

    def test_claim_without_text_to_evidence_mapping_fails_closed(self) -> None:
        paths = self.passing_result_paths()
        evidence = json.loads(paths[1].read_text(encoding="utf-8"))
        evidence["ledgers"].pop("text_to_evidence")
        paths[1] = self.write_json("reviews/evidence.json", evidence)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("text_evidence_mapping_missing", {item["code"] for item in report["findings"]})

    def test_definition_after_first_use_is_failure(self) -> None:
        paths = self.passing_result_paths()
        definition_result = json.loads(paths[2].read_text(encoding="utf-8"))
        definition = definition_result["ledgers"]["definitions"][0]
        definition["definition_unit_id"] = self.unit_two_id
        definition["first_use_unit_id"] = self.unit_one_id
        paths[2] = self.write_json("reviews/definitions.json", definition_result)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "fail")
        self.assertIn("definition_after_first_use", {item["code"] for item in report["findings"]})

    def test_revision_requires_hash_bound_reaudit_of_changed_and_dependency_units(self) -> None:
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["revision_scope"] = {
            "revision_id": "patch-2",
            "changed_unit_ids": [self.unit_one_id],
            "dependency_unit_ids": [self.unit_two_id],
        }
        manifest = self.write_json("manifest-revision.json", manifest_payload)
        revision_manifest_hash = digest_bytes(manifest.read_bytes())
        paths = self.passing_result_paths()
        for index, path in enumerate(paths):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["manifest_sha256"] = revision_manifest_hash
            paths[index] = self.write_json(str(path.relative_to(self.root)), payload)
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("revision_recheck_missing", {item["code"] for item in report["findings"]})

    def test_revision_passes_after_all_roles_reaudit_and_ledger_recheck(self) -> None:
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["revision_scope"] = {
            "revision_id": "patch-2",
            "changed_unit_ids": [self.unit_one_id],
            "dependency_unit_ids": [self.unit_two_id],
        }
        manifest = self.write_json("manifest-revision.json", manifest_payload)
        revision_manifest_hash = digest_bytes(manifest.read_bytes())
        paths = self.passing_result_paths()
        for index, path in enumerate(paths):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["manifest_sha256"] = revision_manifest_hash
            payload["revision_id"] = "patch-2"
            for record in payload["unit_reviews"]:
                record["revision_id"] = "patch-2"
            if index == 0:
                payload["ledgers"]["revision_rechecks"] = [
                    {
                        "unit_id": self.unit_one_id,
                        "revision_id": "patch-2",
                        "text_sha256": digest_text(self.unit_one_text),
                        "status": "rechecked",
                    },
                    {
                        "unit_id": self.unit_two_id,
                        "revision_id": "patch-2",
                        "text_sha256": digest_text(self.unit_two_text),
                        "status": "rechecked",
                    },
                ]
            paths[index] = self.write_json(str(path.relative_to(self.root)), payload)
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "pass")

    def test_revision_recheck_blocker_propagates_even_with_a_pass(self) -> None:
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["revision_scope"] = {
            "revision_id": "patch-blocked",
            "changed_unit_ids": [self.unit_one_id],
            "dependency_unit_ids": [],
        }
        manifest = self.write_json("manifest-revision-blocked.json", manifest_payload)
        paths = self.passing_result_paths()
        manifest_hash = digest_bytes(manifest.read_bytes())
        for index, path in enumerate(paths):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["manifest_sha256"] = manifest_hash
            payload["revision_id"] = "patch-blocked"
            for record in payload["unit_reviews"]:
                record["revision_id"] = "patch-blocked"
            if index == 0:
                payload["ledgers"]["revision_rechecks"] = [
                    {
                        "unit_id": self.unit_one_id,
                        "revision_id": "patch-blocked",
                        "text_sha256": digest_text(self.unit_one_text),
                        "status": "pass",
                    },
                    {
                        "unit_id": self.unit_one_id,
                        "revision_id": "patch-blocked",
                        "text_sha256": digest_text(self.unit_one_text),
                        "status": "fail",
                    },
                ]
            paths[index] = self.write_json(str(path.relative_to(self.root)), payload)
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "fail")
        self.assertIn("revision_recheck_failed", {item["code"] for item in report["findings"]})

    def test_manifest_footnote_dependency_expands_recheck_closure(self) -> None:
        manifest_payload = copy.deepcopy(self.manifest_payload)
        unit_one = next(
            unit for unit in manifest_payload["units"]
            if unit["unit_id"] == self.unit_one_id
        )
        unit_two = next(
            unit for unit in manifest_payload["units"]
            if unit["unit_id"] == self.unit_two_id
        )
        unit_one["footnote_target_unit_ids"] = [self.unit_two_id]
        unit_one["dependency_unit_ids"] = [self.unit_two_id]
        unit_two["referenced_by_unit_ids"] = [self.unit_one_id]
        unit_two["dependency_unit_ids"] = [self.unit_one_id]
        manifest_payload["revision_scope"] = {
            "revision_id": "patch-footnote",
            "changed_unit_ids": [self.unit_one_id],
            "dependency_unit_ids": [],
        }
        self.packet_by_role = self.attach_packets(
            manifest_payload, "footnote-dependency-packets"
        )
        manifest = self.write_json("manifest-footnote-dependency.json", manifest_payload)
        paths = self.rebind_results(self.passing_result_paths(), manifest)
        manifest_hash = digest_bytes(manifest.read_bytes())
        for index, path in enumerate(paths):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["manifest_sha256"] = manifest_hash
            payload["revision_id"] = "patch-footnote"
            for record in payload["unit_reviews"]:
                if record["unit_id"] == self.unit_one_id:
                    record["revision_id"] = "patch-footnote"
            if index == 0:
                payload["ledgers"]["revision_rechecks"] = [
                    {
                        "unit_id": self.unit_one_id,
                        "revision_id": "patch-footnote",
                        "text_sha256": digest_text(self.unit_one_text),
                        "status": "rechecked",
                    }
                ]
            paths[index] = self.write_json(str(path.relative_to(self.root)), payload)
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "live_unit_universe_mismatch",
            {item["code"] for item in report["findings"]},
        )

    def test_invalid_json_outranks_known_failure(self) -> None:
        paths = self.passing_result_paths()
        evidence = json.loads(paths[1].read_text(encoding="utf-8"))
        evidence["unit_reviews"][0]["verdict"] = "fail"
        paths[1] = self.write_json("reviews/evidence.json", evidence)
        invalid = self.write_text("reviews/broken.json", "{not valid json")
        completed, report = self.run_validator([*paths, invalid])
        self.assert_status(completed, report, "audit_incomplete")

    def test_unresolved_conflict_cannot_be_majority_voted_away(self) -> None:
        paths = self.passing_result_paths()
        intent = json.loads(paths[0].read_text(encoding="utf-8"))
        intent["conflicts"] = [
            {
                "conflict_id": "conflict-1",
                "type": "author_intent",
                "status": "open",
            }
        ]
        paths[0] = self.write_json("reviews/intent.json", intent)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "clarification_required")

    def test_closed_conflict_requires_nonvoting_authority_and_evidence(self) -> None:
        paths = self.passing_result_paths()
        intent = json.loads(paths[0].read_text(encoding="utf-8"))
        intent["conflicts"] = [
            {
                "conflict_id": "conflict-closed",
                "type": "author_intent",
                "status": "closed",
                "resolution_authority": "majority_vote",
                "resolution_evidence": "Two of three reviewers voted yes.",
                "resolution": "majority vote",
            }
        ]
        paths[0] = self.write_json("reviews/intent.json", intent)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("reviewer_self_closed_conflict", {item["code"] for item in report["findings"]})

        paths = self.passing_result_paths()
        intent = json.loads(paths[0].read_text(encoding="utf-8"))
        intent["conflicts"] = [
            {
                "conflict_id": "conflict-closed-valid",
                "type": "author_intent",
                "status": "open",
            }
        ]
        paths[0] = self.write_json("reviews/intent.json", intent)
        resolution = self.write_json(
            "conflict-resolution-valid.json",
            {
                "schema_version": "1.0",
                "schema_id": "qa-conflict-resolution/1.0",
                "status": "resolved",
                "resolution_id": "resolution-1",
                "conflict_id": "conflict-closed-valid",
                "conflict_sha256": canonical_digest(
                    {
                        "conflict_id": "conflict-closed-valid",
                        "type": "author_intent",
                        "status": "open",
                    }
                ),
                "manifest_id": self.manifest_payload["manifest_id"],
                "manifest_sha256": self.manifest_hash,
                "resolved_by": "controller-arbitrator",
                "resolved_at": "2026-08-03T10:04:00+08:00",
                "resolver_native_agent_id": "native-agent-arbitrator",
                "resolver_task_id": "native-task-arbitrator",
                "resolution_authority": "author_intent",
                "authority_artifact": {
                    "path": str(self.contract),
                    "sha256": self.contract_hash,
                    "revision_id": "intent-r1",
                },
                "resolution": "Apply the frozen author proposition.",
            },
        )
        completed, report = self.run_validator(
            paths, extra=["--conflict-resolution", str(resolution)]
        )
        self.assert_status(completed, report, "pass")

    def test_evidence_conflict_with_author_action_remains_evidence_conflict(self) -> None:
        paths = self.passing_result_paths()
        evidence = json.loads(paths[1].read_text(encoding="utf-8"))
        evidence["unit_reviews"][0]["verdict"] = "evidence_conflict"
        evidence["unit_reviews"][0]["requires_author_action"] = True
        evidence["unit_reviews"][0]["severity"] = "critical"
        paths[1] = self.write_json("reviews/evidence.json", evidence)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "evidence_conflict")
        self.assertNotIn("author_action_required", {item["code"] for item in report["findings"]})

    def test_empty_frozen_evidence_registry_rejects_arbitrary_anchor(self) -> None:
        contract_payload = copy.deepcopy(self.contract_payload)
        contract_payload["author_intent_contract"]["propositions"][0]["evidence_anchors"] = []
        contract = self.write_json("contract-no-evidence.json", contract_payload)
        contract_hash = digest_bytes(contract.read_bytes())
        self.contract_hash = contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["inputs"]["contract"] = {"path": str(contract), "sha256": contract_hash}
        self.packet_by_role = self.attach_packets(manifest_payload, "no-evidence-packets")
        manifest = self.write_json("manifest-no-evidence.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, contract_hash=contract_hash
        )
        completed, report = self.run_validator(paths, manifest=manifest, contract=contract)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("frozen_evidence_registry_empty", {item["code"] for item in report["findings"]})

    def test_negative_obligation_requires_author_intent_absence_attestation(self) -> None:
        negative_obligation = {
            "obligation_id": "negative-1",
            "obligation_type": "must_not_claim",
            "kind": "must_not_claim",
            "content": "The estimate proves the mechanism.",
        }
        contract_payload = copy.deepcopy(self.contract_payload)
        contract_payload["author_intent_contract"]["content_obligations"] = [
            copy.deepcopy(negative_obligation)
        ]
        contract = self.write_json("contract-negative.json", contract_payload)
        contract_hash = digest_bytes(contract.read_bytes())
        self.contract_hash = contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["inputs"]["contract"] = {
            "path": str(contract),
            "sha256": contract_hash,
        }
        manifest_payload["content_obligations"] = [copy.deepcopy(negative_obligation)]
        self.packet_by_role = self.attach_packets(manifest_payload, "negative-packets")
        manifest = self.write_json("manifest-negative.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, contract_hash=contract_hash
        )
        intent = json.loads(paths[0].read_text(encoding="utf-8"))
        intent["ledgers"]["intent_to_text"].append(
            {
                "intent_id": "negative-1",
                "status": "verified_absent",
                "packet_id": self.packet_by_role["author_intent_coverage"][
                    "packet_id"
                ],
                "packet_sha256": self.packet_by_role[
                    "author_intent_coverage"
                ]["packet_sha256"],
            }
        )
        paths[0] = self.write_json("reviews/intent.json", intent)
        completed, report = self.run_validator(
            paths, manifest=manifest, contract=contract
        )
        self.assert_status(completed, report, "pass")

        intent["ledgers"]["intent_to_text"] = [
            entry
            for entry in intent["ledgers"]["intent_to_text"]
            if entry.get("intent_id") != "negative-1"
        ]
        paths[0] = self.write_json("reviews/intent.json", intent)
        completed, report = self.run_validator(
            paths, manifest=manifest, contract=contract
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("negative_obligation_unverified", {item["code"] for item in report["findings"]})

    def test_negative_obligation_requires_attestation_from_every_author_packet(self) -> None:
        negative = {
            "obligation_id": "negative-all-packets",
            "obligation_type": "must_not_imply",
            "kind": "must_not_imply",
            "content": "The estimate establishes causality.",
        }
        contract_payload = copy.deepcopy(self.contract_payload)
        contract_payload["author_intent_contract"]["content_obligations"] = [
            negative
        ]
        contract = self.write_json("contract-negative-all.json", contract_payload)
        self.contract_hash = digest_bytes(contract.read_bytes())
        self.manifest_payload["inputs"]["contract"] = {
            "path": str(contract),
            "sha256": self.contract_hash,
        }
        self.manifest_payload["content_obligations"] = [copy.deepcopy(negative)]
        self.packet_by_role = self.attach_packets(
            self.manifest_payload, "negative-all-base-packets"
        )
        manifest, paths = self.split_author_packet_bundle()
        author_paths = [
            path
            for path in paths
            if json.loads(path.read_text(encoding="utf-8"))["reviewer"]["role"]
            == "author_intent_coverage"
        ]
        first = json.loads(author_paths[0].read_text(encoding="utf-8"))
        first.setdefault("ledgers", {}).setdefault("intent_to_text", []).append(
            {
                "intent_id": "negative-all-packets",
                "status": "verified_absent",
                "packet_id": first["packet_id"],
                "packet_sha256": first["packet_sha256"],
            }
        )
        self.write_json(str(author_paths[0].relative_to(self.root)), first)
        completed, report = self.run_validator(
            paths, manifest=manifest, contract=contract
        )
        self.assert_status(completed, report, "audit_incomplete")
        finding = next(
            item
            for item in report["findings"]
            if item["code"] == "negative_obligation_unverified"
        )
        self.assertEqual(len(finding["missing_packet_ids"]), 1)

        second = json.loads(author_paths[1].read_text(encoding="utf-8"))
        second.setdefault("ledgers", {}).setdefault("intent_to_text", []).append(
            {
                "intent_id": "negative-all-packets",
                "status": "verified_absent",
                "packet_id": second["packet_id"],
                "packet_sha256": second["packet_sha256"],
            }
        )
        self.write_json(str(author_paths[1].relative_to(self.root)), second)
        completed, report = self.run_validator(
            paths, manifest=manifest, contract=contract
        )
        self.assert_status(completed, report, "pass")

    def test_paper_state_cannot_shadow_frozen_author_obligation(self) -> None:
        author = copy.deepcopy(self.contract_payload["author_intent_contract"])
        wrapped = {
            "schema_version": "1.0",
            "paper_state": {
                "author_intent_contract": author,
                "content_obligations": [
                    {
                        "intent_id": "intent-main",
                        "required": False,
                        "required_meaning": "Disable the frozen proposition.",
                    }
                ],
            },
        }
        contract = self.write_json("contract-obligation-conflict.json", wrapped)
        contract_hash = digest_bytes(contract.read_bytes())
        self.contract_hash = contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["inputs"]["contract"] = {
            "path": str(contract),
            "sha256": contract_hash,
        }
        self.packet_by_role = self.attach_packets(manifest_payload, "obligation-conflict-packets")
        manifest = self.write_json("manifest-obligation-conflict.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, contract_hash=contract_hash
        )
        completed, report = self.run_validator(paths, manifest=manifest, contract=contract)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "obligation_authority_conflict",
            {item["code"] for item in report["findings"]},
        )

    def test_supplements_cannot_invent_author_intents_or_definitions(self) -> None:
        qa_payload = json.loads(self.qa_contract.read_text(encoding="utf-8"))
        invented_obligation = {
            "obligation_id": "AI_NEW",
            "intent_id": "AI_NEW",
            "required_meaning": "The estimate proves a newly invented mechanism.",
            "kind": "required",
        }
        qa_payload["qa_contract"]["content_obligations"] = [
            copy.deepcopy(invented_obligation)
        ]
        qa_contract = self.write_json("qa-invented-intent.json", qa_payload)
        qa_contract_hash = digest_bytes(qa_contract.read_bytes())
        self.qa_contract_hash = qa_contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["qa_contract_sha256"] = qa_contract_hash
        manifest_payload["inputs"]["qa_contract"] = {
            "path": str(qa_contract),
            "sha256": qa_contract_hash,
        }
        manifest_payload["content_obligations"] = [
            copy.deepcopy(invented_obligation)
        ]
        next(
            unit for unit in manifest_payload["units"]
            if unit["unit_id"] == self.unit_one_id
        )["intent_ids"].append("AI_NEW")
        self.packet_by_role = self.attach_packets(
            manifest_payload, "invented-intent-packets"
        )
        manifest = self.write_json("manifest-invented-intent.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(),
            manifest,
            qa_contract_hash=qa_contract_hash,
        )
        intent = json.loads(paths[0].read_text(encoding="utf-8"))
        intent["ledgers"]["intent_to_text"].append(
            {"intent_id": "AI_NEW", "unit_ids": [self.unit_one_id], "status": "covered"}
        )
        intent["ledgers"]["text_to_intent"][0]["intent_ids"].append("AI_NEW")
        paths[0] = self.write_json("reviews/intent.json", intent)
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("supplemental_obligation_unanchored", codes)
        self.assertIn("unknown_intent_mapping", codes)

        self.qa_contract_hash = digest_bytes(self.qa_contract.read_bytes())
        author = copy.deepcopy(self.contract_payload["author_intent_contract"])
        wrapped = {
            "schema_version": "1.0",
            "paper_state": {
                "author_intent_contract": author,
                "definition_registry": [
                    {
                        "definition_id": "AI_NEW_DEFINITION",
                        "term": "Invented mechanism",
                        "definition": "A definition absent from the author contract.",
                    }
                ],
            },
        }
        contract = self.write_json("contract-invented-definition.json", wrapped)
        contract_hash = digest_bytes(contract.read_bytes())
        self.contract_hash = contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["inputs"]["contract"] = {
            "path": str(contract),
            "sha256": contract_hash,
        }
        self.packet_by_role = self.attach_packets(
            manifest_payload, "invented-definition-packets"
        )
        manifest = self.write_json(
            "manifest-invented-definition.json", manifest_payload
        )
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, contract_hash=contract_hash
        )
        completed, report = self.run_validator(
            paths, manifest=manifest, contract=contract
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "supplemental_definition_unanchored",
            {item["code"] for item in report["findings"]},
        )

    def test_author_owned_paper_state_enrichment_passes(self) -> None:
        author = copy.deepcopy(self.contract_payload["author_intent_contract"])
        wrapped = {
            "schema_version": "1.0",
            "paper_state": {
                "author_intent_contract": author,
                "content_obligations": [
                    {
                        "intent_id": "intent-main",
                        "required": True,
                        "required_meaning": author["propositions"][0]["must_express"],
                        "allowed_locations": ["results"],
                    }
                ],
            },
        }
        contract = self.write_json("contract-author-enrichment.json", wrapped)
        contract_hash = digest_bytes(contract.read_bytes())
        self.contract_hash = contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["inputs"]["contract"] = {
            "path": str(contract),
            "sha256": contract_hash,
        }
        self.packet_by_role = self.attach_packets(
            manifest_payload, "author-enrichment-packets"
        )
        manifest = self.write_json("manifest-author-enrichment.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, contract_hash=contract_hash
        )
        completed, report = self.run_validator(
            paths, manifest=manifest, contract=contract
        )
        self.assert_status(completed, report, "pass")

    def test_contract_container_id_is_not_blanket_claim_authority(self) -> None:
        manifest_payload = copy.deepcopy(self.manifest_payload)
        next(
            unit for unit in manifest_payload["units"]
            if unit["unit_id"] == self.unit_one_id
        )["intent_ids"] = ["contract-1"]
        self.packet_by_role = self.attach_packets(
            manifest_payload, "contract-id-packets"
        )
        manifest = self.write_json("manifest-contract-id.json", manifest_payload)
        paths = self.rebind_results(self.passing_result_paths(), manifest)
        intent = json.loads(paths[0].read_text(encoding="utf-8"))
        intent["ledgers"]["intent_to_text"][0]["intent_id"] = "contract-1"
        intent["ledgers"]["text_to_intent"][0]["intent_ids"] = ["contract-1"]
        paths[0] = self.write_json("reviews/intent.json", intent)
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "unknown_intent_mapping",
            {item["code"] for item in report["findings"]},
        )

    def test_definition_registry_conflict_across_authority_layers_fails(self) -> None:
        author = copy.deepcopy(self.contract_payload["author_intent_contract"])
        wrapped = {
            "schema_version": "1.0",
            "paper_state": {
                "author_intent_contract": author,
                "definition_registry": [
                    {
                        "definition_id": "definition-treatment",
                        "term": "Control group",
                    }
                ],
            },
        }
        contract = self.write_json("contract-definition-conflict.json", wrapped)
        contract_hash = digest_bytes(contract.read_bytes())
        self.contract_hash = contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["inputs"]["contract"] = {
            "path": str(contract),
            "sha256": contract_hash,
        }
        self.packet_by_role = self.attach_packets(manifest_payload, "definition-conflict-packets")
        manifest = self.write_json("manifest-definition-conflict.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, contract_hash=contract_hash
        )
        completed, report = self.run_validator(paths, manifest=manifest, contract=contract)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "definition_authority_conflict",
            {item["code"] for item in report["findings"]},
        )

    def test_manifest_assigned_intent_cannot_be_marked_nonclaim(self) -> None:
        paths = self.passing_result_paths()
        intent = json.loads(paths[0].read_text(encoding="utf-8"))
        intent["ledgers"]["text_to_intent"][0] = {
            "unit_id": self.unit_one_id,
            "status": "non_claim",
        }
        paths[0] = self.write_json("reviews/intent.json", intent)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("assigned_intent_marked_nonclaim", {item["code"] for item in report["findings"]})

    def test_definition_units_require_definitions_role_review(self) -> None:
        paths = self.passing_result_paths()
        completed, report = self.run_validator(paths[:2])
        self.assert_status(completed, report, "audit_incomplete")
        self.assertTrue(
            {"definition_role_review_missing", "definition_audit_missing"}
            & {item["code"] for item in report["findings"]}
        )

    def test_contract_hash_change_invalidates_every_review(self) -> None:
        paths = self.passing_result_paths()
        changed = copy.deepcopy(self.contract_payload)
        changed["author_intent_contract"]["reader_takeaway"] = "Changed after review"
        changed_contract = self.write_json("contract-changed.json", changed)
        completed, report = self.run_validator(paths, contract=changed_contract)
        self.assert_status(completed, report, "audit_incomplete")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("contract_manifest_stale", codes)

    def test_qa_contract_file_and_review_hash_are_both_fresh(self) -> None:
        paths = self.passing_result_paths()
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
        payload.pop("qa_contract_sha256")
        paths[0] = self.write_json("reviews/intent.json", payload)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("review_qa_contract_stale", {item["code"] for item in report["findings"]})

        paths = self.passing_result_paths()
        self.qa_contract.write_text(
            json.dumps({"qa_contract": {"schema_version": "1.0", "gate_status": "ready", "changed": True}}),
            encoding="utf-8",
        )
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("qa_contract_file_stale", {item["code"] for item in report["findings"]})

    def test_non_target_container_requires_exact_child_coverage(self) -> None:
        completed, report = self.run_validator(self.passing_result_paths())
        self.assert_status(completed, report, "pass")
        self.assertEqual(report["coverage"]["review_target_units"], 3)

        broken = copy.deepcopy(self.manifest_payload)
        container = next(
            unit for unit in broken["units"] if unit.get("review_target") is False
        )
        container["child_text_sha256"] = "0" * 64
        self.packet_by_role = self.attach_packets(broken, "container-broken-packets")
        broken_manifest = self.write_json("manifest-container-broken.json", broken)
        paths = self.rebind_results(self.passing_result_paths(), broken_manifest)
        completed, report = self.run_validator(paths, manifest=broken_manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "container_child_text_hash_invalid",
            {item["code"] for item in report["findings"]},
        )

    def test_nonready_gate_status_requires_clarification(self) -> None:
        changed_contract = copy.deepcopy(self.contract_payload)
        # A ready wrapper must not mask a nested non-ready author-intent gate.
        changed_contract["gate_status"] = "ready"
        changed_contract["author_intent_contract"]["gate_status"] = "proposed"
        changed_contract["author_intent_contract"]["approval_record"][
            "explicit_hold_reason"
        ] = "Author paused drafting pending a scope decision."
        contract = self.write_json("contract-not-ready.json", changed_contract)
        contract_hash = digest_bytes(contract.read_bytes())
        self.contract_hash = contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["inputs"]["contract"] = {
            "path": str(contract),
            "sha256": contract_hash,
        }
        self.packet_by_role = self.attach_packets(manifest_payload, "not-ready-packets")
        manifest = self.write_json("manifest-not-ready.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, contract_hash=contract_hash
        )
        completed, report = self.run_validator(paths, manifest=manifest, contract=contract)
        self.assert_status(completed, report, "clarification_required")
        self.assertIn("author_intent_gate_not_ready", {item["code"] for item in report["findings"]})
        self.assertEqual(report["reason_code"], "explicit_author_hold")
        self.assertEqual(report["gate_local_status"], "clarification_required")
        self.assertEqual(report["delivery_status"], "clarification_required")

    def test_missing_gate_and_separate_freeze_event_fail_closed(self) -> None:
        missing_gate = copy.deepcopy(self.contract_payload)
        missing_gate["author_intent_contract"].pop("gate_status")
        contract = self.write_json("contract-gate-missing.json", missing_gate)
        contract_hash = digest_bytes(contract.read_bytes())
        self.contract_hash = contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["inputs"]["contract"] = {
            "path": str(contract),
            "sha256": contract_hash,
        }
        self.packet_by_role = self.attach_packets(
            manifest_payload, "gate-missing-packets"
        )
        manifest = self.write_json("manifest-gate-missing.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, contract_hash=contract_hash
        )
        completed, report = self.run_validator(
            paths, manifest=manifest, contract=contract
        )
        self.assert_status(completed, report, "clarification_required")
        self.assertIn(
            "author_intent_gate_not_ready",
            {item["code"] for item in report["findings"]},
        )

        separate_event = copy.deepcopy(self.contract_payload)
        approval = separate_event["author_intent_contract"]["approval_record"]
        approval["confirmed_scope"] = "paper"
        approval["freeze_authorized_by"] = "controller-agent"
        approval["freeze_authorized_at"] = "2026-08-03T10:05:00+08:00"
        contract = self.write_json("contract-separate-freeze.json", separate_event)
        contract_hash = digest_bytes(contract.read_bytes())
        self.contract_hash = contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["inputs"]["contract"] = {
            "path": str(contract),
            "sha256": contract_hash,
        }
        self.packet_by_role = self.attach_packets(
            manifest_payload, "separate-freeze-packets"
        )
        manifest = self.write_json("manifest-separate-freeze.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, contract_hash=contract_hash
        )
        completed, report = self.run_validator(
            paths, manifest=manifest, contract=contract
        )
        self.assert_status(completed, report, "audit_incomplete")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("approval_scope_incomplete", codes)
        self.assertIn("approval_freeze_event_mismatch", codes)

    def test_hash_bound_qa_mode_cannot_be_shadowed_by_manifest(self) -> None:
        changed_contract = copy.deepcopy(self.contract_payload)
        changed_contract["author_intent_contract"]["propositions"].append(
            {
                "intent_id": "intent-unmapped",
                "must_express": "A second proposition must appear.",
                "claim_type": "associational",
                "evidence_anchors": ["table-second"],
            }
        )
        contract = self.write_json("contract-two-intents.json", changed_contract)
        contract_hash = digest_bytes(contract.read_bytes())
        self.contract_hash = contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["qa_mode"] = "bounded_change"
        manifest_payload["inputs"]["contract"] = {
            "path": str(contract),
            "sha256": contract_hash,
        }
        self.packet_by_role = self.attach_packets(manifest_payload, "qa-mode-shadow-packets")
        manifest = self.write_json("manifest-qa-mode-shadow.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, contract_hash=contract_hash
        )
        completed, report = self.run_validator(paths, manifest=manifest, contract=contract)
        self.assert_status(completed, report, "audit_incomplete")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("qa_mode_manifest_mismatch", codes)
        self.assertIn("intent_obligation_unmapped", codes)

    def test_hash_bound_qa_role_universe_cannot_be_removed(self) -> None:
        original_paths = self.passing_result_paths()
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["roles"].pop("evidence_claim_strength")
        for unit in manifest_payload["units"]:
            if unit.get("review_target") is True:
                unit["required_roles"].remove("evidence_claim_strength")
        self.packet_by_role = self.attach_packets(manifest_payload, "qa-role-shadow-packets")
        manifest = self.write_json("manifest-qa-role-shadow.json", manifest_payload)
        paths = self.rebind_results(
            [original_paths[0], original_paths[2], original_paths[3]], manifest
        )
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "qa_required_roles_manifest_mismatch",
            {item["code"] for item in report["findings"]},
        )

    def test_hash_bound_qa_contract_cannot_remove_fixed_fourth_role(self) -> None:
        original_paths = self.passing_result_paths()
        qa_payload = json.loads(self.qa_contract.read_text(encoding="utf-8"))
        qa_payload["qa_contract"]["required_roles"].remove(
            "economic_logic_scope_qualifiers"
        )
        qa_contract = self.write_json("qa-three-roles.json", qa_payload)
        qa_contract_hash = digest_bytes(qa_contract.read_bytes())
        self.qa_contract_hash = qa_contract_hash

        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["qa_contract_sha256"] = qa_contract_hash
        manifest_payload["inputs"]["qa_contract"] = {
            "path": str(qa_contract),
            "sha256": qa_contract_hash,
        }
        manifest_payload["roles"].pop("economic_logic_scope_qualifiers")
        for unit in manifest_payload["units"]:
            if "economic_logic_scope_qualifiers" in unit.get("required_roles", []):
                unit["required_roles"].remove("economic_logic_scope_qualifiers")
        self.packet_by_role = self.attach_packets(
            manifest_payload, "qa-three-role-packets"
        )
        manifest = self.write_json("manifest-three-roles.json", manifest_payload)
        paths = self.rebind_results(
            original_paths[:3],
            manifest,
            qa_contract_hash=qa_contract_hash,
        )
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "qa_contract_semantic_roles_missing",
            {item["code"] for item in report["findings"]},
        )

    def test_bounded_change_requires_classification_and_matching_scope(self) -> None:
        changed_range = {"path": self.candidate.name, "start_line": 3, "end_line": 3}
        base_scope = {
            "revision_id": "bounded-r1",
            "changed_source_ranges": [changed_range],
            "dependency_source_ranges": [],
            "affected_intent_ids": ["intent-main"],
        }
        base_qa_payload = {
            "qa_contract": {
                "schema_version": "1.0",
                "gate_status": "ready",
                "qa_mode": "bounded_change",
                "manuscript_path": str(self.candidate),
                "minimum_high_risk_independent_reviews": 2,
                "task_classification": {
                    "task_stage": "local_edit",
                    "qa_mode": "bounded_change",
                    "basis": "One explicitly identified local source range changed.",
                    "changed_artifact_or_source_ranges": [changed_range],
                    "substantive_dependencies_checked": [],
                    "affected_intent_ids": ["intent-main"],
                    "classified_by": "test-controller",
                    "classified_at": "2026-08-03T10:02:00+08:00",
                },
                "revision_scope": base_scope,
                "required_roles": [
                    "author_intent_coverage",
                    "evidence_claim_strength",
                    "definitions_reader_sufficiency",
                    "economic_logic_scope_qualifiers",
                ],
            }
        }

        def run_case(
            name: str,
            qa_payload: dict,
            *,
            with_rechecks: bool = True,
            revision_target_attack: str | None = None,
        ) -> tuple[subprocess.CompletedProcess[str], dict]:
            qa_contract = self.write_json(f"qa-bounded-{name}.json", qa_payload)
            qa_contract_hash = digest_bytes(qa_contract.read_bytes())
            self.qa_contract_hash = qa_contract_hash
            manifest_payload = copy.deepcopy(self.manifest_payload)
            manifest_payload["qa_contract_sha256"] = qa_contract_hash
            manifest_payload["inputs"]["qa_contract"] = {
                "path": str(qa_contract),
                "sha256": qa_contract_hash,
            }
            manifest_payload["qa_mode"] = "bounded_change"
            manifest_payload.pop("artifact_contract_sha256", None)
            manifest_payload["inputs"].pop("artifact_contract", None)
            manifest_payload["revision_scope"] = copy.deepcopy(
                qa_payload["qa_contract"]["revision_scope"]
            )
            QA_PREPARER.apply_review_scope(
                manifest_payload["units"],
                "bounded_change",
                manifest_payload["revision_scope"],
            )
            self.packet_by_role = self.attach_packets(
                manifest_payload, f"bounded-packets-{name}", ""
            )
            if revision_target_attack == "duplicate":
                target_ids = manifest_payload["revision_target_unit_ids"]
                self.assertTrue(target_ids)
                manifest_payload["revision_target_unit_ids"] = [
                    target_ids[0],
                    target_ids[0],
                ]
            elif revision_target_attack == "empty":
                manifest_payload["revision_target_unit_ids"] = []
            manifest = self.write_json(f"manifest-bounded-{name}.json", manifest_payload)
            selected_unit_ids = [
                unit["unit_id"]
                for unit in manifest_payload["units"]
                if unit.get("review_target")
                and unit.get("selected_for_review") is not False
            ]
            paths = self.rebind_results(
                self.passing_result_paths_for_units(
                    selected_unit_ids, f"bounded-reviews-{name}"
                ),
                manifest,
                qa_contract_hash=qa_contract_hash,
                artifact_contract_hash="",
            )
            if with_rechecks:
                revision_id = manifest_payload["revision_scope"].get(
                    "revision_id"
                )
                target_ids = set(
                    manifest_payload["revision_target_unit_ids"]
                )
                for path in paths:
                    result_payload = json.loads(
                        path.read_text(encoding="utf-8")
                    )
                    result_payload["revision_id"] = revision_id
                    for record in result_payload["unit_reviews"]:
                        if record["unit_id"] in target_ids:
                            record["revision_id"] = revision_id
                    self.write_json(
                        str(path.relative_to(self.root)), result_payload
                    )
                first_payload = json.loads(paths[0].read_text(encoding="utf-8"))
                first_payload.setdefault("ledgers", {})[
                    "revision_rechecks"
                ] = [
                    {
                        "unit_id": unit_id,
                        "revision_id": revision_id,
                        "text_sha256": next(
                            unit["text_sha256"]
                            for unit in manifest_payload["units"]
                            if unit["unit_id"] == unit_id
                        ),
                        "status": "rechecked",
                    }
                    for unit_id in sorted(target_ids)
                ]
                self.write_json(
                    str(paths[0].relative_to(self.root)), first_payload
                )
            return self.run_validator(paths, manifest=manifest)

        completed, report = run_case(
            "source-range-no-recheck",
            copy.deepcopy(base_qa_payload),
            with_rechecks=False,
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "revision_recheck_missing",
            {item["code"] for item in report["findings"]},
        )

        completed, report = run_case("valid", copy.deepcopy(base_qa_payload))
        self.assert_status(completed, report, "pass")

        completed, report = run_case(
            "duplicate-revision-targets",
            copy.deepcopy(base_qa_payload),
            with_rechecks=False,
            revision_target_attack="duplicate",
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "revision_target_unit_ids_invalid",
            {item["code"] for item in report["findings"]},
        )

        completed, report = run_case(
            "missing-revision-targets",
            copy.deepcopy(base_qa_payload),
            with_rechecks=False,
            revision_target_attack="empty",
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "revision_target_unit_ids_mismatch",
            {item["code"] for item in report["findings"]},
        )

        missing_stage = copy.deepcopy(base_qa_payload)
        missing_stage["qa_contract"]["task_classification"].pop("task_stage")
        completed, report = run_case("missing-stage", missing_stage)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "task_classification_incomplete",
            {item["code"] for item in report["findings"]},
        )

        wrong_stage = copy.deepcopy(base_qa_payload)
        wrong_stage["qa_contract"]["task_classification"]["task_stage"] = (
            "document_translation"
        )
        completed, report = run_case("wrong-stage", wrong_stage)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "bounded_task_stage_invalid",
            {item["code"] for item in report["findings"]},
        )

        missing_mode = copy.deepcopy(base_qa_payload)
        missing_mode["qa_contract"]["task_classification"].pop("qa_mode")
        completed, report = run_case("missing-mode", missing_mode)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "task_classification_mode_mismatch",
            {item["code"] for item in report["findings"]},
        )

        missing_affected = copy.deepcopy(base_qa_payload)
        missing_affected["qa_contract"]["task_classification"].pop(
            "affected_intent_ids"
        )
        completed, report = run_case("missing-affected", missing_affected)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "bounded_classification_affected_intents_invalid",
            {item["code"] for item in report["findings"]},
        )

        mismatched_affected = copy.deepcopy(base_qa_payload)
        mismatched_affected["qa_contract"]["task_classification"][
            "affected_intent_ids"
        ] = ["different-intent"]
        completed, report = run_case(
            "mismatched-affected", mismatched_affected
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "bounded_affected_intents_mismatch",
            {item["code"] for item in report["findings"]},
        )

        partial_changes = copy.deepcopy(base_qa_payload)
        partial_changes["qa_contract"]["revision_scope"]["changed_source_ranges"].append(
            {"path": self.candidate.name, "start_line": 4, "end_line": 4}
        )
        completed, report = run_case("partial-changes", partial_changes)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "bounded_changed_scope_mismatch",
            {item["code"] for item in report["findings"]},
        )

    def test_paper_state_qa_wrapper_is_supported_but_conflicts_fail_closed(self) -> None:
        qa_inner = json.loads(self.qa_contract.read_text(encoding="utf-8"))["qa_contract"]
        nested_qa = self.write_json(
            "qa-paper-state.json",
            {"schema_version": "1.0", "paper_state": {"qa_contract": qa_inner}},
        )
        self.qa_contract_hash = digest_bytes(nested_qa.read_bytes())
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["qa_contract_sha256"] = self.qa_contract_hash
        manifest_payload["inputs"]["qa_contract"] = {
            "path": str(nested_qa),
            "sha256": self.qa_contract_hash,
        }
        self.packet_by_role = self.attach_packets(manifest_payload, "nested-qa-packets")
        manifest = self.write_json("manifest-nested-qa.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(), manifest, qa_contract_hash=self.qa_contract_hash
        )
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "pass")

        conflicting = copy.deepcopy(qa_inner)
        conflicting["gate_status"] = "proposed"
        conflict_file = self.write_json(
            "qa-paper-state-conflict.json",
            {
                "schema_version": "1.0",
                "qa_contract": conflicting,
                "paper_state": {"qa_contract": qa_inner},
            },
        )
        self.qa_contract_hash = digest_bytes(conflict_file.read_bytes())
        conflict_payload = copy.deepcopy(self.manifest_payload)
        conflict_payload["qa_contract_sha256"] = self.qa_contract_hash
        conflict_payload["inputs"]["qa_contract"] = {
            "path": str(conflict_file),
            "sha256": self.qa_contract_hash,
        }
        self.packet_by_role = self.attach_packets(
            conflict_payload, "conflicting-qa-packets"
        )
        conflict_manifest = self.write_json(
            "manifest-conflicting-qa.json", conflict_payload
        )
        conflict_paths = self.rebind_results(
            self.passing_result_paths(),
            conflict_manifest,
            qa_contract_hash=self.qa_contract_hash,
        )
        completed, report = self.run_validator(
            conflict_paths, manifest=conflict_manifest
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("contract_wrapper_conflict", {item["code"] for item in report["findings"]})

    def test_risk_or_role_escalation_requires_new_manifest(self) -> None:
        paths = self.passing_result_paths()
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
        payload["risk_or_role_escalation"] = {
            "unit_id": self.unit_two_id,
            "add_role": "evidence_claim_strength",
        }
        paths[0] = self.write_json("reviews/intent.json", payload)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "risk_or_role_escalation_requires_reprepare",
            {item["code"] for item in report["findings"]},
        )

    def test_unit_level_escalation_requires_new_manifest(self) -> None:
        paths = self.passing_result_paths()
        evidence = json.loads(paths[1].read_text(encoding="utf-8"))
        evidence["unit_reviews"][0]["risk_or_role_escalation"] = {
            "add_role": "economic_logic_scope_qualifiers"
        }
        paths[1] = self.write_json("reviews/evidence.json", evidence)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "unit_risk_or_role_escalation_requires_reprepare",
            {item["code"] for item in report["findings"]},
        )

    def test_review_span_and_severity_are_validated(self) -> None:
        paths = self.passing_result_paths()
        evidence = json.loads(paths[1].read_text(encoding="utf-8"))
        evidence["unit_reviews"][0]["source_span"] = {"garbage": "x"}
        paths[1] = self.write_json("reviews/evidence.json", evidence)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("unit_review_field_invalid", {item["code"] for item in report["findings"]})

        paths = self.passing_result_paths()
        evidence = json.loads(paths[1].read_text(encoding="utf-8"))
        evidence["unit_reviews"][0]["severity"] = "high"
        paths[1] = self.write_json("reviews/evidence.json", evidence)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("unit_review_field_invalid", {item["code"] for item in report["findings"]})

    def test_wrong_role_cannot_supply_specialist_ledger(self) -> None:
        paths = self.passing_result_paths()
        intent = json.loads(paths[0].read_text(encoding="utf-8"))
        evidence = json.loads(paths[1].read_text(encoding="utf-8"))
        intent["ledgers"]["text_to_evidence"] = evidence["ledgers"].pop(
            "text_to_evidence"
        )
        paths[0] = self.write_json("reviews/intent.json", intent)
        paths[1] = self.write_json("reviews/evidence.json", evidence)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "audit_incomplete")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("ledger_role_unauthorized", codes)
        self.assertIn("text_evidence_mapping_missing", codes)

    def test_approval_required_and_metric_unavailable_propagate(self) -> None:
        paths = self.passing_result_paths()
        approval_gate = self.write_json(
            "approval-gate.json",
            {
                "schema_version": "1.0",
                "status": "approval_required",
                "exit_code": 2,
                "inputs": {"candidate_sha256": self.candidate_hash},
            },
        )
        completed, report = self.run_validator(
            paths, extra=["--upstream-gate", str(approval_gate)]
        )
        self.assert_status(completed, report, "approval_required")
        self.assertEqual(report["gate_local_status"], "pass")
        self.assertEqual(report["delivery_status"], "approval_required")

        metric_gate = self.write_json(
            "metric-gate.json",
            {
                "schema_version": "1.0",
                "status": "metric_unavailable",
                "exit_code": 3,
                "inputs": {"candidate": str(self.candidate)},
            },
        )
        completed, report = self.run_validator(
            paths, extra=["--upstream-gate", str(metric_gate)]
        )
        self.assert_status(completed, report, "metric_unavailable")
        self.assertEqual(report["gate_local_status"], "pass")
        self.assertEqual(report["delivery_status"], "metric_unavailable")

    def test_failure_precedes_approval_but_all_findings_remain(self) -> None:
        paths = self.passing_result_paths()
        evidence = json.loads(paths[1].read_text(encoding="utf-8"))
        evidence["unit_reviews"][0]["verdict"] = "fail"
        evidence["unit_reviews"][0]["severity"] = "major"
        paths[1] = self.write_json("reviews/evidence.json", evidence)
        approval_gate = self.write_json(
            "approval-plus-fail.json",
            {
                "schema_version": "1.0",
                "status": "approval_required",
                "exit_code": 2,
                "inputs": {"candidate_sha256": self.candidate_hash},
            },
        )
        completed, report = self.run_validator(
            paths, extra=["--upstream-gate", str(approval_gate)]
        )
        self.assert_status(completed, report, "fail")
        self.assertEqual(report["gate_local_status"], "fail")
        self.assertEqual(report["delivery_status"], "fail")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("review_failure", codes)
        self.assertIn("upstream_gate_approval_required", codes)

    def test_artifact_contract_hash_is_bound_through_upstream_gate(self) -> None:
        baseline = self.write_text(
            "accepted-baseline.tex",
            self.candidate.read_text(encoding="utf-8"),
        )
        baseline_hash = digest_bytes(baseline.read_bytes())
        baseline_expanded, baseline_sources, _ = (
            CONSERVATION_AUDITOR.load_manuscript(baseline, self.root)
        )
        baseline_main, _ = CONSERVATION_AUDITOR.split_appendix(
            baseline_expanded, r"\appendix", "baseline", "tex"
        )
        baseline_main_words = CONSERVATION_AUDITOR.manuscript_metrics(
            baseline_main, "tex"
        )["normalized_words"]
        baseline_ledger = self.exact_conservation_ledger(
            baseline, self.candidate
        )
        artifact_contract = self.write_json(
            "artifact-contract.json",
            {
                "schema_version": "1.0",
                "task_mode": "major_revision",
                "rewrite_mode": "patch_existing",
                "mature_baseline": False,
                "metric_status": "measured",
                "baseline_main_source_words": baseline_main_words,
                "measurement_contract": {
                    "appendix_boundary": r"\appendix",
                    "source_word_method": "normalized_words",
                },
                "baseline_artifact": {
                    "path": str(baseline),
                    "sha256": baseline_hash,
                    "expanded_sha256": digest_text(baseline_expanded),
                    "source_files": CONSERVATION_AUDITOR.source_file_records(
                        baseline_sources
                    ),
                    "acceptance_status": "accepted",
                    "accepted_by": "author",
                },
                "section_cards": [
                    {
                        "section_id": "main",
                        "section_name": "Main",
                        "optional": True,
                        "target_word_range": [1, 1000],
                        "must_remain_main": [],
                        "minimum_depth_questions": [
                            "Is the registered estimate still explained?"
                        ],
                    }
                ],
                "content_conservation_ledger": baseline_ledger,
            },
        )
        artifact_hash = digest_bytes(artifact_contract.read_bytes())
        qa_payload = json.loads(self.qa_contract.read_text(encoding="utf-8"))
        qa_payload["qa_contract"]["task_classification"]["task_stage"] = (
            "major_revision"
        )
        qa_contract = self.write_json("qa-major-revision.json", qa_payload)
        qa_contract_hash = digest_bytes(qa_contract.read_bytes())
        self.qa_contract_hash = qa_contract_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["qa_contract_sha256"] = qa_contract_hash
        manifest_payload["inputs"]["qa_contract"] = {
            "path": str(qa_contract),
            "sha256": qa_contract_hash,
        }
        manifest_payload["inputs"]["artifact_contract"] = {
            "path": str(artifact_contract),
            "sha256": artifact_hash,
        }
        manifest_payload["artifact_contract_sha256"] = artifact_hash
        self.packet_by_role = self.attach_packets(
            manifest_payload, "artifact-packets", artifact_hash
        )
        manifest = self.write_json("manifest-artifact.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(),
            manifest,
            artifact_contract_hash=artifact_hash,
        )
        conservation_payload = CONSERVATION_AUDITOR.audit(
            argparse.Namespace(
                baseline=str(baseline),
                candidate=str(self.candidate),
                project_root=str(self.root),
                contract=str(artifact_contract),
                appendix_marker=r"\appendix",
                word_metric=None,
                max_main_reduction=None,
                min_main_source_words=None,
                baseline_main_pdf_pages=None,
                candidate_main_pdf_pages=None,
                min_main_pdf_pages=None,
                report="unused",
            )
        )
        self.assertEqual(
            conservation_payload["status"],
            "pass",
            json.dumps(conservation_payload, ensure_ascii=False, indent=2),
        )
        upstream = self.write_json("conservation.json", conservation_payload)
        completed, report = self.run_validator(
            paths,
            manifest=manifest,
            extra=["--upstream-gate", str(upstream)],
        )
        self.assert_status(completed, report, "pass")
        self.assertEqual(report["hashes"]["artifact_contract_sha256"], artifact_hash)

        baseline.write_text("Changed after acceptance.\n", encoding="utf-8")
        completed, report = self.run_validator(
            paths,
            manifest=manifest,
            extra=["--upstream-gate", str(upstream)],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("artifact_baseline_stale", {item["code"] for item in report["findings"]})
        baseline.write_text(
            self.candidate.read_text(encoding="utf-8"), encoding="utf-8"
        )

        no_ledger_payload = copy.deepcopy(manifest_payload)
        no_ledger_payload["content_conservation_ledger"] = []
        no_ledger_manifest = self.write_json("manifest-artifact-no-ledger.json", no_ledger_payload)
        no_ledger_paths = self.rebind_results(
            paths,
            no_ledger_manifest,
            artifact_contract_hash=artifact_hash,
        )
        completed, report = self.run_validator(
            no_ledger_paths,
            manifest=no_ledger_manifest,
            extra=["--upstream-gate", str(upstream)],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "baseline_conservation_ledger_missing",
            {item["code"] for item in report["findings"]},
        )

        broken = json.loads(upstream.read_text(encoding="utf-8"))
        broken["inputs"].pop("contract_sha256")
        broken_upstream = self.write_json("conservation-broken.json", broken)
        completed, report = self.run_validator(
            paths,
            manifest=manifest,
            extra=["--upstream-gate", str(broken_upstream)],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "upstream_artifact_contract_hash_missing",
            {item["code"] for item in report["findings"]},
        )

        missing_candidate = json.loads(upstream.read_text(encoding="utf-8"))
        missing_candidate["inputs"].pop("candidate_sha256")
        missing_candidate_gate = self.write_json(
            "conservation-no-candidate.json", missing_candidate
        )
        completed, report = self.run_validator(
            paths,
            manifest=manifest,
            extra=["--upstream-gate", str(missing_candidate_gate)],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("upstream_candidate_hash_missing", {item["code"] for item in report["findings"]})

    def test_new_draft_artifact_without_schema_or_baseline_does_not_invent_conservation(self) -> None:
        artifact = self.write_json(
            "new-draft-artifact.json",
            {"artifact_contract": {"task_mode": "full_draft"}},
        )
        artifact_hash = digest_bytes(artifact.read_bytes())
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["artifact_contract_sha256"] = artifact_hash
        manifest_payload["inputs"]["artifact_contract"] = {
            "path": str(artifact),
            "sha256": artifact_hash,
        }
        self.packet_by_role = self.attach_packets(
            manifest_payload, "new-draft-packets", artifact_hash
        )
        manifest = self.write_json("manifest-new-draft.json", manifest_payload)
        paths = self.rebind_results(
            self.passing_result_paths(),
            manifest,
            artifact_contract_hash=artifact_hash,
        )
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "artifact_contract_gate_missing",
            {item["code"] for item in report["findings"]},
        )
        artifact.write_text(
            json.dumps({"artifact_contract": {"task_mode": "full_draft", "changed": True}}),
            encoding="utf-8",
        )
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("artifact_contract_file_stale", {item["code"] for item in report["findings"]})

    def test_full_redraft_requires_scoped_recoverable_approval(self) -> None:
        def run_case(name: str, approval_record: dict | None) -> tuple[subprocess.CompletedProcess[str], dict]:
            contract = json.loads(self.artifact_contract.read_text(encoding="utf-8"))
            contract["rewrite_mode"] = "full_redraft"
            if approval_record is not None:
                contract["approval_record"] = approval_record
            artifact = self.write_json(
                f"full-redraft-artifact-{name}.json",
                {"artifact_contract": contract},
            )
            artifact_hash = digest_bytes(artifact.read_bytes())
            manifest_payload = copy.deepcopy(self.manifest_payload)
            manifest_payload["artifact_contract_sha256"] = artifact_hash
            manifest_payload["inputs"]["artifact_contract"] = {
                "path": str(artifact),
                "sha256": artifact_hash,
            }
            self.packet_by_role = self.attach_packets(
                manifest_payload, f"full-redraft-packets-{name}", artifact_hash
            )
            manifest = self.write_json(
                f"manifest-full-redraft-{name}.json", manifest_payload
            )
            paths = self.rebind_results(
                self.passing_result_paths(),
                manifest,
                artifact_contract_hash=artifact_hash,
            )
            gate = self.write_json(
                f"full-redraft-conservation-{name}.json",
                self.candidate_only_conservation_payload(
                    artifact_contract=artifact,
                    artifact_contract_hash=artifact_hash,
                ),
            )
            return self.run_validator(
                paths,
                manifest=manifest,
                extra=["--upstream-gate", str(gate)],
            )

        completed, report = run_case("missing", None)
        self.assert_status(completed, report, "approval_required")
        self.assertIn(
            "full_redraft_approval_required",
            {item["code"] for item in report["findings"]},
        )

        completed, report = run_case(
            "controller",
            {
                "approval_authority": "controller",
                "approved_by": "controller-agent",
                "approved_at": "2026-08-03T14:00:00+08:00",
                "approval_source": "controller decision log",
                "approved_scope": ["full_redraft"],
            },
        )
        self.assert_status(completed, report, "approval_required")
        self.assertIn(
            "full_redraft_approval_required",
            {item["code"] for item in report["findings"]},
        )

        completed, report = run_case(
            "author",
            {
                "approval_authority": "author",
                "approved_by": "named-author",
                "approved_at": "2026-08-03T14:01:00+08:00",
                "approval_source": "author message 57",
                "approved_scope": ["full_redraft"],
            },
        )
        self.assert_status(completed, report, "pass")

    def test_packet_file_and_result_binding_cannot_be_reused(self) -> None:
        paths = self.passing_result_paths()
        intent_packet = self.root / self.packet_by_role["author_intent_coverage"]["path"]
        original = json.loads(intent_packet.read_text(encoding="utf-8"))
        tampered = copy.deepcopy(original)
        tampered["units"][0]["text"] = "Tampered packet text"
        self.write_json(str(intent_packet.relative_to(self.root)), tampered)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("packet_hash_stale", {item["code"] for item in report["findings"]})

        self.write_json(str(intent_packet.relative_to(self.root)), original)
        payload = json.loads(paths[0].read_text(encoding="utf-8"))
        payload["packet_sha256"] = "0" * 64
        paths[0] = self.write_json("reviews/intent.json", payload)
        completed, report = self.run_validator(paths)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("review_packet_stale", {item["code"] for item in report["findings"]})

    def test_same_role_multiple_packet_batches_pass(self) -> None:
        manifest, paths = self.split_author_packet_bundle()
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "pass")

    def test_missing_packet_batch_fails_closed(self) -> None:
        manifest, paths = self.split_author_packet_bundle()
        completed, report = self.run_validator(paths[1:], manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "review_packet_result_missing",
            {item["code"] for item in report["findings"]},
        )

    def test_wrong_packet_batch_binding_fails_closed(self) -> None:
        manifest, paths = self.split_author_packet_bundle()
        first = json.loads(paths[0].read_text(encoding="utf-8"))
        second = json.loads(paths[1].read_text(encoding="utf-8"))
        second["packet_id"] = first["packet_id"]
        second["packet_sha256"] = first["packet_sha256"]
        paths[1] = self.write_json("split-reviews/author-2.json", second)
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        codes = {item["code"] for item in report["findings"]}
        self.assertIn("review_packet_result_duplicate", codes)

    def test_cross_batch_unit_review_fails_closed(self) -> None:
        manifest, paths = self.split_author_packet_bundle()
        first = json.loads(paths[0].read_text(encoding="utf-8"))
        second = json.loads(paths[1].read_text(encoding="utf-8"))
        first["unit_reviews"].append(copy.deepcopy(second["unit_reviews"][0]))
        paths[0] = self.write_json("split-reviews/author-1.json", first)
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "review_unit_outside_packet",
            {item["code"] for item in report["findings"]},
        )

    def test_cross_batch_ledger_unit_fails_closed(self) -> None:
        manifest, paths = self.split_author_packet_bundle()
        first = json.loads(paths[0].read_text(encoding="utf-8"))
        first["ledgers"]["intent_to_text"][0]["unit_ids"] = [self.unit_one_id, self.unit_two_id]
        paths[0] = self.write_json("split-reviews/author-1.json", first)
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "ledger_unit_outside_packet",
            {item["code"] for item in report["findings"]},
        )

    def test_packet_target_and_byte_budgets_are_hard_gates(self) -> None:
        original_qa = json.loads(self.qa_contract.read_text(encoding="utf-8"))
        attacks = (
            ("target", "max_units_per_packet", 1, "packet_target_budget_exceeded"),
            ("bytes", "max_packet_bytes", 10_000, "packet_byte_budget_invalid"),
        )
        for name, field, value, expected_code in attacks:
            with self.subTest(name=name):
                qa_payload = copy.deepcopy(original_qa)
                qa_payload["qa_contract"][field] = value
                qa_contract = self.write_json(
                    f"qa-packet-budget-{name}.json", qa_payload
                )
                self.qa_contract_hash = digest_bytes(qa_contract.read_bytes())
                manifest_payload = copy.deepcopy(self.manifest_payload)
                manifest_payload["inputs"]["qa_contract"] = {
                    "path": str(qa_contract),
                    "sha256": self.qa_contract_hash,
                }
                self.packet_by_role = self.attach_packets(
                    manifest_payload, f"packet-budget-{name}"
                )
                manifest = self.write_json(
                    f"manifest-packet-budget-{name}.json", manifest_payload
                )
                paths = self.rebind_results(
                    self.passing_result_paths(),
                    manifest,
                    qa_contract_hash=self.qa_contract_hash,
                )
                completed, report = self.run_validator(
                    paths, manifest=manifest
                )
                self.assert_status(completed, report, "audit_incomplete")
                self.assertIn(
                    expected_code, {item["code"] for item in report["findings"]}
                )

    def test_packet_batch_sequence_and_content_hash_are_canonical(self) -> None:
        manifest, paths = self.split_author_packet_bundle()
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        record = next(
            item
            for item in manifest_payload["packets"]
            if item["role"] == "author_intent_coverage"
            and item["batch_index"] == 2
        )
        packet_path = self.root / record["path"]
        packet = json.loads(packet_path.read_text(encoding="utf-8"))
        packet["batch_index"] = 3
        scope = dict(packet)
        scope.pop("packet_sha256", None)
        packet_hash = canonical_digest(scope)
        packet["packet_sha256"] = packet_hash
        packet_path = self.write_json("batch-sequence/author-3.json", packet)
        record.update(
            {
                "batch_index": 3,
                "path": str(packet_path.relative_to(self.root)),
                "packet_sha256": packet_hash,
                "packet_bytes": packet_path.stat().st_size,
            }
        )
        manifest = self.write_json("manifest-batch-sequence.json", manifest_payload)
        manifest_hash = digest_bytes(manifest.read_bytes())
        for index, path in enumerate(paths):
            result = json.loads(path.read_text(encoding="utf-8"))
            result["manifest_sha256"] = manifest_hash
            if result.get("packet_id") == record["packet_id"]:
                result["packet_sha256"] = packet_hash
            paths[index] = self.write_json(
                str(path.relative_to(self.root)), result
            )
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "packet_batch_sequence_invalid",
            {item["code"] for item in report["findings"]},
        )

        manifest_payload = copy.deepcopy(self.manifest_payload)
        self.rewrite_packet(
            manifest_payload,
            "author_intent_coverage",
            "packet-no-content-hash",
            lambda payload: payload.pop("content_sha256", None),
        )
        manifest = self.write_json(
            "manifest-no-content-hash.json", manifest_payload
        )
        paths = self.rebind_results(self.passing_result_paths(), manifest)
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "packet_content_hash_mismatch",
            {item["code"] for item in report["findings"]},
        )

    def test_packet_artifact_body_cannot_be_spoofed_behind_valid_hash(self) -> None:
        def spoof_mode(payload: dict) -> None:
            payload["artifact_contract"]["task_mode"] = "shorten"

        def spoof_section_card(payload: dict) -> None:
            payload["artifact_contract"]["section_cards"][0][
                "target_word_range"
            ] = [999, 1000]

        for name, transform in (
            ("task-mode", spoof_mode),
            ("section-card", spoof_section_card),
        ):
            with self.subTest(name=name):
                manifest_payload = copy.deepcopy(self.manifest_payload)
                self.rewrite_packet(
                    manifest_payload,
                    "economic_logic_scope_qualifiers",
                    f"packet-artifact-spoof-{name}",
                    transform,
                )
                manifest = self.write_json(
                    f"manifest-artifact-spoof-{name}.json", manifest_payload
                )
                paths = self.rebind_results(
                    self.passing_result_paths(), manifest
                )
                completed, report = self.run_validator(
                    paths, manifest=manifest
                )
                self.assert_status(completed, report, "audit_incomplete")
                self.assertIn(
                    "packet_artifact_contract_body_mismatch",
                    {item["code"] for item in report["findings"]},
                )

    def test_conservation_report_requires_exact_canonical_replay(self) -> None:
        attacks: list[tuple[str, dict, str]] = []
        forged_metric = json.loads(
            self.base_conservation_gate.read_text(encoding="utf-8")
        )
        forged_metric["metrics"]["candidate_main"]["normalized_words"] += 1
        attacks.append(
            ("forged-metric", forged_metric, "conservation_replay_mismatch")
        )
        missing_argument = json.loads(
            self.base_conservation_gate.read_text(encoding="utf-8")
        )
        missing_argument["audit_arguments"].pop("word_metric")
        attacks.append(
            (
                "missing-argument",
                missing_argument,
                "conservation_audit_arguments_invalid",
            )
        )
        unknown_argument = json.loads(
            self.base_conservation_gate.read_text(encoding="utf-8")
        )
        unknown_argument["audit_arguments"]["unregistered_choice"] = True
        attacks.append(
            (
                "unknown-argument",
                unknown_argument,
                "conservation_audit_arguments_invalid",
            )
        )
        deleted_inventory = json.loads(
            self.base_conservation_gate.read_text(encoding="utf-8")
        )
        deleted_inventory["conservation"]["candidate_block_inventory"] = []
        attacks.append(
            (
                "deleted-inventory-and-rehashed-file",
                deleted_inventory,
                "conservation_replay_mismatch",
            )
        )
        for name, payload, expected_code in attacks:
            with self.subTest(name=name):
                gate = self.write_json(f"gate-{name}.json", payload)
                completed, report = self.run_validator(
                    self.passing_result_paths(),
                    extra=["--upstream-gate", str(gate)],
                )
                self.assert_status(completed, report, "audit_incomplete")
                self.assertIn(
                    expected_code, {item["code"] for item in report["findings"]}
                )

    def test_manifest_identity_source_records_and_unit_subtree_are_replayed(self) -> None:
        identity_attack = copy.deepcopy(self.manifest_payload)
        identity_attack["qa_bundle_sha256"] = "0" * 64
        manifest = self.write_json("manifest-identity-forged.json", identity_attack)
        paths = self.rebind_results(self.passing_result_paths(), manifest)
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "qa_manifest_identity_mismatch",
            {item["code"] for item in report["findings"]},
        )

        source_attack = copy.deepcopy(self.manifest_payload)
        source_attack["source_files"][0]["bytes"] += 1
        source_attack["source"]["source_files"][0]["bytes"] += 1
        manifest = self.write_json("manifest-source-bytes-forged.json", source_attack)
        paths = self.rebind_results(self.passing_result_paths(), manifest)
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "live_source_file_record_mismatch",
            {item["code"] for item in report["findings"]},
        )

        other_root = self.root / "other-root"
        other_root.mkdir()
        completed, report = self.run_validator(
            self.passing_result_paths(),
            extra=["--project-root", str(other_root)],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "live_preparation_project_root_mismatch",
            {item["code"] for item in report["findings"]},
        )

        subtree_attack = copy.deepcopy(self.manifest_payload)
        subtree_attack["units"] = [
            unit
            for unit in subtree_attack["units"]
            if unit["unit_id"] != self.unit_two_id
        ]
        for unit in subtree_attack["units"]:
            if unit.get("child_unit_ids"):
                unit["child_unit_ids"] = [
                    child
                    for child in unit["child_unit_ids"]
                    if child != self.unit_two_id
                ]
                children = [
                    child
                    for child in subtree_attack["units"]
                    if child["unit_id"] in unit["child_unit_ids"]
                ]
                unit["child_text_sha256"] = canonical_digest(
                    [
                        [child["unit_id"], child["text_sha256"]]
                        for child in children
                    ]
                )
            context = unit.get("context")
            if isinstance(context, dict):
                if context.get("next_review_unit_id") == self.unit_two_id:
                    context["next_review_unit_id"] = None
                    context["next_review_text"] = None
                context["dependency_units"] = [
                    dependency
                    for dependency in context.get("dependency_units", [])
                    if dependency.get("unit_id") != self.unit_two_id
                ]
        self.packet_by_role = self.attach_packets(
            subtree_attack, "packets-subtree-forged"
        )
        manifest = self.write_json("manifest-subtree-forged.json", subtree_attack)
        paths = self.rebind_results(
            self.passing_result_paths_for_units(
                [self.unit_one_id], "reviews-subtree-forged"
            ),
            manifest,
        )
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "live_unit_universe_mismatch",
            {item["code"] for item in report["findings"]},
        )

    def test_fresh_nonpass_conservation_status_is_not_masked(self) -> None:
        variants = (
            ("fail", {"min_main_source_words": 1000}),
            ("metric_unavailable", {"candidate_main_pdf_pages": 10}),
        )
        for expected_status, overrides in variants:
            with self.subTest(status=expected_status):
                arguments = {
                    "baseline": None,
                    "candidate": str(self.candidate),
                    "project_root": str(self.root),
                    "contract": str(self.artifact_contract),
                    "appendix_marker": r"\appendix",
                    "word_metric": None,
                    "max_main_reduction": None,
                    "min_main_source_words": None,
                    "baseline_main_pdf_pages": None,
                    "candidate_main_pdf_pages": None,
                    "min_main_pdf_pages": None,
                    "report": "unused",
                }
                arguments.update(overrides)
                namespace = argparse.Namespace(**arguments)
                try:
                    gate_payload = CONSERVATION_AUDITOR.audit(namespace)
                except CONSERVATION_AUDITOR.MetricUnavailable as exc:
                    gate_payload = CONSERVATION_AUDITOR.unavailable_report(
                        namespace, exc
                    )
                self.assertEqual(gate_payload["status"], expected_status)
                gate = self.write_json(
                    f"conservation-{expected_status}.json", gate_payload
                )
                paths = self.passing_result_paths()
                registry, registry_hash, assignments, main_assignment = (
                    self.build_assignment_registry(self.manifest)
                )
                assert main_assignment is not None
                self.bind_review_assignments(paths, registry_hash, assignments)
                main_audit = self.build_main_text_audit(
                    self.manifest,
                    self.contract,
                    self.candidate,
                    registry_hash,
                    main_assignment,
                    gate,
                )
                main_payload = json.loads(
                    main_audit.read_text(encoding="utf-8")
                )
                main_payload["status"] = expected_status
                main_payload["checklist"]["length_and_depth_contract_satisfied"] = (
                    False
                )
                main_payload["findings"] = [
                    {
                        "status": expected_status,
                        "code": f"conservation_{expected_status}",
                        "message": "The fifth role preserves the deterministic conservation status.",
                    }
                ]
                main_audit = self.write_json(
                    f"runtime/main-text-{expected_status}-bound.json",
                    main_payload,
                )
                completed, report = self.run_validator(
                    paths,
                    auto_assurance=False,
                    extra=[
                        "--upstream-gate",
                        str(gate),
                        "--assignment-registry",
                        str(registry),
                        "--main-text-sufficiency-audit",
                        str(main_audit),
                    ],
                )
                self.assert_status(completed, report, expected_status)
                codes = {item["code"] for item in report["findings"]}
                self.assertNotIn("artifact_contract_gate_missing", codes)
                self.assertNotIn("main_text_conservation_gate_binding_invalid", codes)

    def test_fresh_nonpass_can_fail_fast_without_downstream_results(self) -> None:
        base_arguments = {
            "baseline": None,
            "candidate": str(self.candidate),
            "project_root": str(self.root),
            "contract": str(self.artifact_contract),
            "appendix_marker": r"\appendix",
            "word_metric": None,
            "max_main_reduction": None,
            "min_main_source_words": None,
            "baseline_main_pdf_pages": None,
            "candidate_main_pdf_pages": None,
            "min_main_pdf_pages": None,
            "report": "unused",
        }
        fail_payload = CONSERVATION_AUDITOR.audit(
            argparse.Namespace(
                **{**base_arguments, "min_main_source_words": 1000}
            )
        )
        metric_namespace = argparse.Namespace(
            **{**base_arguments, "candidate_main_pdf_pages": 10}
        )
        try:
            metric_payload = CONSERVATION_AUDITOR.audit(metric_namespace)
        except CONSERVATION_AUDITOR.MetricUnavailable as exc:
            metric_payload = CONSERVATION_AUDITOR.unavailable_report(
                metric_namespace, exc
            )
        self.assertEqual(fail_payload["status"], "fail")
        self.assertEqual(metric_payload["status"], "metric_unavailable")
        fail_gate = self.write_json("fail-fast-fail.json", fail_payload)
        metric_gate = self.write_json(
            "fail-fast-metric-unavailable.json", metric_payload
        )

        baseline = self.write_text(
            "fail-fast-approval-baseline.tex",
            self.candidate.read_text(encoding="utf-8"),
        )
        baseline_text, baseline_sources, _ = CONSERVATION_AUDITOR.load_manuscript(
            baseline, self.root
        )
        baseline_main, _ = CONSERVATION_AUDITOR.split_appendix(
            baseline_text, r"\appendix", "baseline", "tex"
        )
        approval_artifact = self.write_json(
            "fail-fast-approval-artifact.json",
            {
                "schema_version": "1.0",
                "task_mode": "major_revision",
                "rewrite_mode": "full_redraft",
                "mature_baseline": False,
                "metric_status": "measured",
                "baseline_main_source_words": CONSERVATION_AUDITOR.manuscript_metrics(
                    baseline_main, "tex"
                )["normalized_words"],
                "measurement_contract": {
                    "appendix_boundary": r"\appendix",
                    "source_word_method": "normalized_words",
                },
                "baseline_artifact": {
                    "path": str(baseline),
                    "sha256": digest_bytes(baseline.read_bytes()),
                    "expanded_sha256": digest_text(baseline_text),
                    "source_files": CONSERVATION_AUDITOR.source_file_records(
                        baseline_sources
                    ),
                    "acceptance_status": "accepted",
                    "accepted_by": "author",
                },
                "section_cards": [
                    {
                        "section_id": "main",
                        "section_name": "Main",
                        "optional": True,
                        "target_word_range": [1, 1000],
                        "must_remain_main": [],
                        "minimum_depth_questions": [
                            "Is the registered estimate still explained?"
                        ],
                    }
                ],
                "content_conservation_ledger": self.exact_conservation_ledger(
                    baseline, self.candidate
                ),
            },
        )
        approval_artifact_hash = digest_bytes(approval_artifact.read_bytes())
        approval_qa_payload = json.loads(
            self.qa_contract.read_text(encoding="utf-8")
        )
        approval_qa_payload["qa_contract"]["task_classification"][
            "task_stage"
        ] = "major_revision"
        approval_qa = self.write_json(
            "fail-fast-approval-qa.json", approval_qa_payload
        )
        approval_qa_hash = digest_bytes(approval_qa.read_bytes())
        approval_manifest_payload = copy.deepcopy(self.manifest_payload)
        approval_manifest_payload["qa_contract_sha256"] = approval_qa_hash
        approval_manifest_payload["artifact_contract_sha256"] = (
            approval_artifact_hash
        )
        approval_manifest_payload["inputs"]["qa_contract"] = {
            "path": str(approval_qa),
            "sha256": approval_qa_hash,
        }
        approval_manifest_payload["inputs"]["artifact_contract"] = {
            "path": str(approval_artifact),
            "sha256": approval_artifact_hash,
        }
        self.packet_by_role = self.attach_packets(
            approval_manifest_payload,
            "fail-fast-approval-packets",
            approval_artifact_hash,
        )
        approval_manifest = self.write_json(
            "fail-fast-approval-manifest.json", approval_manifest_payload
        )
        approval_payload = CONSERVATION_AUDITOR.audit(
            argparse.Namespace(
                baseline=str(baseline),
                candidate=str(self.candidate),
                project_root=str(self.root),
                contract=str(approval_artifact),
                appendix_marker=r"\appendix",
                word_metric=None,
                max_main_reduction=None,
                min_main_source_words=None,
                baseline_main_pdf_pages=None,
                candidate_main_pdf_pages=None,
                min_main_pdf_pages=None,
                report="unused",
            )
        )
        self.assertEqual(
            approval_payload["status"],
            "approval_required",
            json.dumps(approval_payload, ensure_ascii=False, indent=2),
        )
        approval_gate = self.write_json(
            "fail-fast-approval-required.json", approval_payload
        )

        cases = (
            ("fail", self.manifest, fail_gate),
            ("metric_unavailable", self.manifest, metric_gate),
            ("approval_required", approval_manifest, approval_gate),
        )
        for expected_status, manifest, gate in cases:
            with self.subTest(status=expected_status):
                registry, _, _, main_assignment = self.build_assignment_registry(
                    manifest
                )
                self.assertIsNotNone(main_assignment)
                completed, report = self.run_validator(
                    [],
                    manifest=manifest,
                    auto_assurance=False,
                    extra=[
                        "--upstream-gate",
                        str(gate),
                        "--assignment-registry",
                        str(registry),
                    ],
                )
                self.assert_status(completed, report, expected_status)
                codes = {item["code"] for item in report["findings"]}
                self.assertNotIn("no_review_results", codes)
                self.assertNotIn("main_text_sufficiency_audit_missing", codes)
                self.assertNotIn("required_role_result_missing", codes)
                self.assertEqual(report["coverage"]["valid_review_records"], 0)
                self.assertIsNone(
                    report["inputs"]["main_text_sufficiency_audit"]
                )
                self.assertFalse(report["independence_assurance"]["attested"])

        stale_payload = copy.deepcopy(fail_payload)
        stale_payload["metrics"]["candidate_main"]["normalized_words"] += 1
        stale_gate = self.write_json("fail-fast-stale-gate.json", stale_payload)
        registry, _, _, _ = self.build_assignment_registry(self.manifest)
        completed, report = self.run_validator(
            [],
            auto_assurance=False,
            extra=[
                "--upstream-gate",
                str(stale_gate),
                "--assignment-registry",
                str(registry),
            ],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "conservation_replay_mismatch",
            {item["code"] for item in report["findings"]},
        )

    def test_fifth_role_mixed_findings_use_protocol_priority(self) -> None:
        cases = (
            ("fail", ("fail", "metric_unavailable")),
            ("approval_required", ("approval_required", "metric_unavailable")),
        )
        for declared, statuses in cases:
            with self.subTest(declared=declared):
                paths = self.passing_result_paths()
                registry, registry_hash, assignments, main_assignment = (
                    self.build_assignment_registry(self.manifest)
                )
                assert main_assignment is not None
                self.bind_review_assignments(paths, registry_hash, assignments)
                main_audit = self.build_main_text_audit(
                    self.manifest,
                    self.contract,
                    self.candidate,
                    registry_hash,
                    main_assignment,
                    self.base_conservation_gate,
                )
                payload = json.loads(main_audit.read_text(encoding="utf-8"))
                payload["status"] = declared
                payload["checklist"]["main_text_self_contained"] = False
                payload["findings"] = [
                    {
                        "status": status,
                        "code": f"mixed_{declared}_{status}",
                        "message": "Independent mixed-status blocker.",
                    }
                    for status in statuses
                ]
                main_audit = self.write_json(
                    f"runtime/main-text-mixed-{declared}.json", payload
                )
                _, report = self.run_validator(
                    paths,
                    auto_assurance=False,
                    extra=[
                        "--upstream-gate",
                        str(self.base_conservation_gate),
                        "--assignment-registry",
                        str(registry),
                        "--main-text-sufficiency-audit",
                        str(main_audit),
                    ],
                )
                self.assertNotIn(
                    "main_text_sufficiency_outcome_invalid",
                    {item["code"] for item in report["findings"]},
                )

    def test_fifth_role_depth_questions_are_exact_and_evidenced(self) -> None:
        paths = self.passing_result_paths()
        registry, registry_hash, assignments, main_assignment = (
            self.build_assignment_registry(self.manifest)
        )
        assert main_assignment is not None
        self.bind_review_assignments(paths, registry_hash, assignments)
        main_audit = self.build_main_text_audit(
            self.manifest,
            self.contract,
            self.candidate,
            registry_hash,
            main_assignment,
            self.base_conservation_gate,
        )
        base_payload = json.loads(main_audit.read_text(encoding="utf-8"))
        self.assertEqual(len(base_payload["question_reviews"]), 1)
        completed, report = self.run_validator(
            paths,
            auto_assurance=False,
            extra=[
                "--upstream-gate",
                str(self.base_conservation_gate),
                "--assignment-registry",
                str(registry),
                "--main-text-sufficiency-audit",
                str(main_audit),
            ],
        )
        self.assert_status(completed, report, "pass")

        def missing_question(payload: dict) -> None:
            payload["question_reviews"] = []

        def stale_question_hash(payload: dict) -> None:
            payload["question_reviews"][0]["question_sha256"] = "0" * 64

        def missing_evidence(payload: dict) -> None:
            payload["question_reviews"][0]["evidence_units"] = []

        def stale_evidence(payload: dict) -> None:
            payload["question_reviews"][0]["evidence_units"][0][
                "text_sha256"
            ] = "0" * 64

        for name, mutate, expected_code in (
            (
                "missing-question",
                missing_question,
                "main_text_depth_question_coverage_invalid",
            ),
            (
                "stale-question-hash",
                stale_question_hash,
                "main_text_depth_question_hash_mismatch",
            ),
            (
                "missing-evidence",
                missing_evidence,
                "main_text_depth_question_evidence_invalid",
            ),
            (
                "stale-evidence",
                stale_evidence,
                "main_text_depth_question_evidence_invalid",
            ),
        ):
            with self.subTest(name=name):
                attacked = copy.deepcopy(base_payload)
                mutate(attacked)
                attacked_path = self.write_json(
                    f"runtime/main-text-depth-{name}.json", attacked
                )
                completed, report = self.run_validator(
                    paths,
                    auto_assurance=False,
                    extra=[
                        "--upstream-gate",
                        str(self.base_conservation_gate),
                        "--assignment-registry",
                        str(registry),
                        "--main-text-sufficiency-audit",
                        str(attacked_path),
                    ],
                )
                self.assert_status(completed, report, "audit_incomplete")
                self.assertIn(
                    expected_code,
                    {item["code"] for item in report["findings"]},
                )

        nonpass = copy.deepcopy(base_payload)
        nonpass["status"] = "fail"
        nonpass["checklist"]["main_text_self_contained"] = False
        nonpass["question_reviews"][0]["verdict"] = "fail"
        nonpass["findings"] = [
            {
                "status": "metric_unavailable",
                "code": "depth_support_metric_unavailable",
                "message": "A supporting depth metric is unavailable.",
            }
        ]
        nonpass_path = self.write_json(
            "runtime/main-text-depth-question-nonpass.json", nonpass
        )
        completed, report = self.run_validator(
            paths,
            auto_assurance=False,
            extra=[
                "--upstream-gate",
                str(self.base_conservation_gate),
                "--assignment-registry",
                str(registry),
                "--main-text-sufficiency-audit",
                str(nonpass_path),
            ],
        )
        # The fifth-role local priority is fail > approval_required >
        # metric_unavailable, while the composed delivery gate deliberately
        # keeps metric_unavailable above semantic fail.  The fail finding must
        # still survive composition instead of being hidden by the typed
        # structured finding.
        self.assert_status(completed, report, "metric_unavailable")
        codes = {item["code"] for item in report["findings"]}
        self.assertNotIn("main_text_sufficiency_outcome_invalid", codes)
        self.assertIn("main_text_depth_question_nonpass", codes)
        self.assertEqual(report["finding_counts"].get("fail"), 1)

    def test_depth_question_pass_evidence_is_bound_to_candidate_section(self) -> None:
        candidate = self.write_text(
            "depth-sections.tex",
            "\\begin{document}\n"
            "\\section{Results}\n\n"
            "The registered result is explained here.\n\n"
            "\\section{Discussion}\n\n"
            "This is unrelated discussion evidence.\n"
            "\\appendix\n"
            "\\section{Appendix Evidence}\n\n"
            "This evidence exists only in the appendix.\n"
            "\\end{document}\n",
        )
        qa = json.loads(self.qa_contract.read_text(encoding="utf-8"))[
            "qa_contract"
        ]
        qa["manuscript_path"] = str(candidate)
        author = self.contract_payload["author_intent_contract"]
        obligations = QA_PREPARER.extract_obligations(author, qa, {})
        definitions = QA_PREPARER.extract_definitions(author, qa, {})
        document = QA_PREPARER.expand_tex(candidate, self.root)
        units, _, _ = QA_PREPARER.prepare_units(
            document,
            "tex",
            self.root,
            author,
            qa,
            obligations,
            definitions,
        )
        QA_PREPARER.apply_review_scope(units, "exhaustive", "full_manuscript")
        by_id = {unit["unit_id"]: unit for unit in units}
        artifact = {
            "mature_baseline": False,
            "section_cards": [
                {
                    "card_id": "results-card",
                    "section_name": "Results",
                    "minimum_depth_questions": [
                        "Does Results explain the registered result?"
                    ],
                }
            ],
        }
        specs = artifact_depth_question_specs(artifact)
        audit = GateAudit()
        bindings, membership, valid = resolve_depth_question_candidate_sections(
            artifact, specs, by_id, {}, audit
        )
        self.assertTrue(valid, audit.findings)
        self.assertEqual(audit.status(), "pass")
        question_id = specs[0]["question_id"]

        def sentence(text: str) -> dict:
            return next(
                unit
                for unit in units
                if unit.get("type") == "sentence" and unit.get("text") == text
            )

        same_section = sentence("The registered result is explained here.")
        unrelated = sentence("This is unrelated discussion evidence.")
        appendix = sentence("This evidence exists only in the appendix.")

        same_audit = GateAudit()
        self.assertTrue(
            validate_depth_question_evidence_units(
                [
                    {
                        "unit_id": same_section["unit_id"],
                        "text_sha256": same_section["text_sha256"],
                    }
                ],
                "pass",
                bindings[question_id],
                membership,
                by_id,
                same_audit,
                question_id=question_id,
            )
        )
        self.assertEqual(same_audit.status(), "pass")

        for label, evidence in (
            ("unrelated-main", unrelated),
            ("appendix", appendix),
        ):
            with self.subTest(label=label):
                attack_audit = GateAudit()
                self.assertFalse(
                    validate_depth_question_evidence_units(
                        [
                            {
                                "unit_id": evidence["unit_id"],
                                "text_sha256": evidence["text_sha256"],
                            }
                        ],
                        "pass",
                        bindings[question_id],
                        membership,
                        by_id,
                        attack_audit,
                        question_id=question_id,
                    )
                )
                self.assertIn(
                    "main_text_depth_question_evidence_section_invalid",
                    {item["code"] for item in attack_audit.findings},
                )

        nonpass_audit = GateAudit()
        self.assertTrue(
            validate_depth_question_evidence_units(
                [
                    {
                        "unit_id": appendix["unit_id"],
                        "text_sha256": appendix["text_sha256"],
                    }
                ],
                "fail",
                bindings[question_id],
                membership,
                by_id,
                nonpass_audit,
                question_id=question_id,
            )
        )

        stale_artifact = copy.deepcopy(artifact)
        stale_artifact["section_cards"][0]["section_name"] = "Missing Results"
        stale_audit = GateAudit()
        _, _, stale_valid = resolve_depth_question_candidate_sections(
            stale_artifact,
            artifact_depth_question_specs(stale_artifact),
            by_id,
            {},
            stale_audit,
        )
        self.assertFalse(stale_valid)
        self.assertIn(
            "main_text_depth_question_section_unresolved",
            {item["code"] for item in stale_audit.findings},
        )

    def test_mature_omitted_selector_uses_actual_canonical_replay(self) -> None:
        manuscript_text = (
            "\\begin{document}\n"
            "\\section{Results}\n\n"
            "The mature result and qualifier remain fully explained.\n"
            "\\appendix\n"
            "Appendix material.\n"
            "\\end{document}\n"
        )
        baseline = self.write_text("mature/baseline.tex", manuscript_text)
        candidate = self.write_text("mature/candidate.tex", manuscript_text)
        baseline_text, baseline_sources, baseline_format = (
            CONSERVATION_AUDITOR.load_manuscript(baseline, self.root)
        )
        baseline_main, _ = CONSERVATION_AUDITOR.split_appendix(
            baseline_text, r"\appendix", "baseline", baseline_format
        )
        baseline_metrics = CONSERVATION_AUDITOR.manuscript_metrics(
            baseline_main, baseline_format
        )
        baseline_section = baseline_metrics["section_metrics"][0]
        artifact_payload = {
            "schema_version": "1.0",
            "task_mode": "major_revision",
            "rewrite_mode": "patch_existing",
            "mature_baseline": True,
            "metric_status": "measured",
            "baseline_main_source_words": baseline_metrics[
                "normalized_words"
            ],
            "measurement_contract": {
                "appendix_boundary": r"\appendix",
                "source_word_method": "normalized_words",
            },
            "baseline_artifact": {
                "path": str(baseline),
                "sha256": digest_bytes(baseline.read_bytes()),
                "expanded_sha256": digest_text(baseline_text),
                "source_files": CONSERVATION_AUDITOR.source_file_records(
                    baseline_sources
                ),
                "acceptance_status": "accepted",
                "accepted_by": "author",
            },
            "section_cards": [
                {
                    "card_id": "results-card",
                    "section_name": "Results",
                    "baseline_section_id": baseline_section["id"],
                    "baseline_section_name": baseline_section["title"],
                    "baseline_words": baseline_section["normalized_words"],
                    "target_word_range": [0, 1000],
                    "maximum_reduction_pct": 1.0,
                    "minimum_depth_questions": [
                        "Does Results retain the mature result and qualifier?"
                    ],
                    "must_remain_main": [
                        {"type": "section", "value": "Results"}
                    ],
                }
            ],
            "content_conservation_ledger": self.exact_conservation_ledger(
                baseline, candidate
            ),
        }
        self.assertNotIn(
            "candidate_section_id", artifact_payload["section_cards"][0]
        )
        self.assertNotIn(
            "candidate_section_name", artifact_payload["section_cards"][0]
        )
        artifact = self.write_json("mature/artifact.json", artifact_payload)
        namespace = argparse.Namespace(
            baseline=str(baseline),
            candidate=str(candidate),
            project_root=str(self.root),
            contract=str(artifact),
            appendix_marker=r"\appendix",
            word_metric=None,
            max_main_reduction=None,
            min_main_source_words=None,
            baseline_main_pdf_pages=None,
            candidate_main_pdf_pages=None,
            min_main_pdf_pages=None,
            report="unused",
        )
        report_payload = CONSERVATION_AUDITOR.audit(namespace)
        self.assertEqual(
            report_payload["status"],
            "pass",
            json.dumps(report_payload, ensure_ascii=False, indent=2),
        )
        report_path = self.write_json("mature/conservation.json", report_payload)
        replay_audit = GateAudit()
        replay = validate_conservation_canonical_replay(
            report_payload, report_path, replay_audit
        )
        self.assertIsInstance(replay, dict, replay_audit.findings)
        self.assertEqual(replay_audit.status(), "pass")

        qa = json.loads(self.qa_contract.read_text(encoding="utf-8"))[
            "qa_contract"
        ]
        qa["manuscript_path"] = str(candidate)
        author = self.contract_payload["author_intent_contract"]
        obligations = QA_PREPARER.extract_obligations(author, qa, {})
        definitions = QA_PREPARER.extract_definitions(author, qa, {})
        document = QA_PREPARER.expand_tex(candidate, self.root)
        units, _, _ = QA_PREPARER.prepare_units(
            document,
            "tex",
            self.root,
            author,
            qa,
            obligations,
            definitions,
        )
        QA_PREPARER.apply_review_scope(units, "exhaustive", "full_manuscript")
        specs = artifact_depth_question_specs(artifact_payload)
        resolution_audit = GateAudit()
        bindings, _, valid = resolve_depth_question_candidate_sections(
            artifact_payload,
            specs,
            {unit["unit_id"]: unit for unit in units},
            replay or {},
            resolution_audit,
        )
        self.assertTrue(valid, resolution_audit.findings)
        self.assertIn(specs[0]["question_id"], bindings)

        forged = copy.deepcopy(report_payload)
        forged["conservation"]["mature_section_budget"]["checks"][0][
            "candidate_section_id"
        ] = "forged-results#1"
        forged_path = self.write_json("mature/conservation-forged.json", forged)
        forged_audit = GateAudit()
        self.assertIsNone(
            validate_conservation_canonical_replay(
                forged, forged_path, forged_audit
            )
        )
        self.assertIn(
            "conservation_replay_mismatch",
            {item["code"] for item in forged_audit.findings},
        )

    def test_assignment_shape_and_task_classification_timestamp_fail_closed(self) -> None:
        for name, mutate in (
            (
                "missing-kind",
                lambda record: record.pop("assignment_kind", None),
            ),
            (
                "forged-target",
                lambda record: record.update(
                    {"target_id": "forged-packet-target"}
                ),
            ),
        ):
            with self.subTest(name=name):
                paths = self.passing_result_paths()
                registry, _, assignments, main_assignment = (
                    self.build_assignment_registry(self.manifest)
                )
                assert main_assignment is not None
                registry_payload = json.loads(
                    registry.read_text(encoding="utf-8")
                )
                mutate(registry_payload["assignments"][0])
                registry = self.write_json(
                    f"runtime/assignment-{name}.json", registry_payload
                )
                registry_hash = digest_bytes(registry.read_bytes())
                self.bind_review_assignments(paths, registry_hash, assignments)
                main_audit = self.build_main_text_audit(
                    self.manifest,
                    self.contract,
                    self.candidate,
                    registry_hash,
                    main_assignment,
                    self.base_conservation_gate,
                )
                completed, report = self.run_validator(
                    paths,
                    auto_assurance=False,
                    extra=[
                        "--upstream-gate",
                        str(self.base_conservation_gate),
                        "--assignment-registry",
                        str(registry),
                        "--main-text-sufficiency-audit",
                        str(main_audit),
                    ],
                )
                self.assert_status(completed, report, "audit_incomplete")
                self.assertIn(
                    "assignment_registry_records_invalid",
                    {item["code"] for item in report["findings"]},
                )

        qa_payload = json.loads(self.qa_contract.read_text(encoding="utf-8"))
        qa_payload["qa_contract"]["task_classification"]["classified_at"] = (
            "2026-08-03"
        )
        qa_contract = self.write_json("qa-bad-classified-at.json", qa_payload)
        self.qa_contract_hash = digest_bytes(qa_contract.read_bytes())
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["inputs"]["qa_contract"] = {
            "path": str(qa_contract),
            "sha256": self.qa_contract_hash,
        }
        self.packet_by_role = self.attach_packets(
            manifest_payload, "packets-bad-classified-at"
        )
        manifest = self.write_json(
            "manifest-bad-classified-at.json", manifest_payload
        )
        paths = self.rebind_results(
            self.passing_result_paths(),
            manifest,
            qa_contract_hash=self.qa_contract_hash,
        )
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "task_classification_timestamp_invalid",
            {item["code"] for item in report["findings"]},
        )

    def test_qa_contract_manuscript_path_is_bound_to_live_root(self) -> None:
        for name, replacement, expected_code in (
            ("missing", None, "qa_manuscript_path_missing"),
            (
                "mismatch",
                str(self.root / "different-manuscript.tex"),
                "qa_manuscript_path_mismatch",
            ),
        ):
            with self.subTest(name=name):
                qa_payload = json.loads(
                    self.qa_contract.read_text(encoding="utf-8")
                )
                if replacement is None:
                    qa_payload["qa_contract"].pop("manuscript_path", None)
                else:
                    qa_payload["qa_contract"]["manuscript_path"] = replacement
                qa_contract = self.write_json(
                    f"qa-manuscript-path-{name}.json", qa_payload
                )
                qa_hash = digest_bytes(qa_contract.read_bytes())
                self.qa_contract_hash = qa_hash
                manifest_payload = copy.deepcopy(self.manifest_payload)
                manifest_payload["qa_contract_sha256"] = qa_hash
                manifest_payload["inputs"]["qa_contract"] = {
                    "path": str(qa_contract),
                    "sha256": qa_hash,
                }
                self.packet_by_role = self.attach_packets(
                    manifest_payload, f"packets-qa-manuscript-path-{name}"
                )
                manifest = self.write_json(
                    f"manifest-qa-manuscript-path-{name}.json",
                    manifest_payload,
                )
                paths = self.rebind_results(
                    self.passing_result_paths(),
                    manifest,
                    qa_contract_hash=qa_hash,
                )
                completed, report = self.run_validator(
                    paths, manifest=manifest
                )
                self.assert_status(completed, report, "audit_incomplete")
                self.assertIn(
                    expected_code,
                    {item["code"] for item in report["findings"]},
                )

    def test_high_risk_review_minimum_is_explicit(self) -> None:
        qa_payload = json.loads(self.qa_contract.read_text(encoding="utf-8"))
        qa_payload["qa_contract"].pop(
            "minimum_high_risk_independent_reviews"
        )
        qa_contract = self.write_json("qa-minimum-missing.json", qa_payload)
        qa_hash = digest_bytes(qa_contract.read_bytes())
        self.qa_contract_hash = qa_hash
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload["inputs"]["qa_contract"] = {
            "path": str(qa_contract),
            "sha256": qa_hash,
        }
        self.packet_by_role = self.attach_packets(
            manifest_payload, "packets-qa-minimum-missing"
        )
        manifest = self.write_json(
            "manifest-qa-minimum-missing.json", manifest_payload
        )
        paths = self.rebind_results(
            self.passing_result_paths(),
            manifest,
            qa_contract_hash=qa_hash,
        )
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "qa_high_risk_review_minimum_invalid",
            {item["code"] for item in report["findings"]},
        )

    def test_review_policy_and_high_risk_unit_minimum_cannot_be_forged(self) -> None:
        def missing_policy(payload: dict) -> None:
            payload.pop("review_policy", None)

        def forged_policy(payload: dict) -> None:
            payload["review_policy"][
                "minimum_high_risk_independent_reviews"
            ] = 3

        def weakened_high_risk_unit(payload: dict) -> None:
            target = next(
                unit for unit in payload["units"] if unit.get("high_risk")
            )
            target["min_independent_reviews"] = 1

        for name, mutate, mutate_before_packets, expected_code in (
            (
                "missing-policy",
                missing_policy,
                False,
                "manifest_review_policy_mismatch",
            ),
            (
                "forged-policy",
                forged_policy,
                False,
                "manifest_review_policy_mismatch",
            ),
            (
                "weakened-high-risk-unit",
                weakened_high_risk_unit,
                True,
                "high_risk_unit_review_minimum_invalid",
            ),
        ):
            with self.subTest(name=name):
                manifest_payload = copy.deepcopy(self.manifest_payload)
                if mutate_before_packets:
                    mutate(manifest_payload)
                self.packet_by_role = self.attach_packets(
                    manifest_payload, f"packets-review-policy-{name}"
                )
                if not mutate_before_packets:
                    mutate(manifest_payload)
                manifest = self.write_json(
                    f"manifest-review-policy-{name}.json", manifest_payload
                )
                paths = self.rebind_results(
                    self.passing_result_paths(), manifest
                )
                completed, report = self.run_validator(
                    paths, manifest=manifest
                )
                self.assert_status(completed, report, "audit_incomplete")
                self.assertIn(
                    expected_code,
                    {item["code"] for item in report["findings"]},
                )

    def test_live_footnote_dependency_cannot_be_deleted_at_both_ends(self) -> None:
        candidate = self.write_text(
            "footnote-paper.tex",
            "\\begin{document}\n"
            "Treatment, the registered exposure, increases the outcome within the registered sample.\n\n"
            "Treatment is defined before the next discussion."
            "\\footnote{The footnote preserves a scope qualifier.}\n"
            "\\appendix\n"
            "\\end{document}\n",
        )
        self.candidate = candidate
        self.candidate_hash = digest_bytes(candidate.read_bytes())
        document = QA_PREPARER.expand_tex(candidate, self.root)
        self.content_hash = digest_text(document.text)
        author = self.contract_payload["author_intent_contract"]
        qa = json.loads(self.qa_contract.read_text(encoding="utf-8"))[
            "qa_contract"
        ]
        obligations = QA_PREPARER.extract_obligations(author, qa, {})
        definitions = QA_PREPARER.extract_definitions(author, qa, {})
        units, appendix, formulas = QA_PREPARER.prepare_units(
            document,
            "tex",
            self.root,
            author,
            qa,
            obligations,
            definitions,
        )
        QA_PREPARER.apply_review_scope(
            units, "exhaustive", "full_manuscript"
        )
        self.unit_one_id = next(
            unit["unit_id"]
            for unit in units
            if unit.get("text") == self.unit_one_text
            and unit.get("type") == "sentence"
        )
        self.unit_two_id = next(
            unit["unit_id"]
            for unit in units
            if str(unit.get("text", "")).startswith(
                "Treatment is defined before the next discussion"
            )
            and unit.get("type") == "sentence"
        )
        source_unit = next(
            unit for unit in units if unit.get("footnote_target_unit_ids")
        )
        target_ids = set(source_unit["footnote_target_unit_ids"])
        source_unit["footnote_reference_ids"] = []
        source_unit["footnote_target_unit_ids"] = []
        source_unit["dependency_unit_ids"] = []
        for unit in units:
            if unit["unit_id"] in target_ids or target_ids.intersection(
                set(unit.get("dependency_unit_ids", []))
            ):
                unit["referenced_by_unit_ids"] = []
                unit["dependency_unit_ids"] = []
            context = unit.get("context")
            if isinstance(context, dict):
                context["dependency_units"] = [
                    dependency
                    for dependency in context.get("dependency_units", [])
                    if dependency.get("unit_id") not in target_ids
                ]
        manuscript_record = {
            "path": str(candidate),
            "relative_path": candidate.name,
            "sha256": self.candidate_hash,
            "expanded_sha256": self.content_hash,
            "format": "tex",
            "project_root": str(self.root),
        }
        source_files = [
            {
                "path": candidate.name,
                "sha256": self.candidate_hash,
                "bytes": len(candidate.read_bytes()),
            }
        ]
        manifest_payload = copy.deepcopy(self.manifest_payload)
        manifest_payload.update(
            {
                "manuscript": copy.deepcopy(manuscript_record),
                "source_files": copy.deepcopy(source_files),
                "appendix": appendix,
                "formulas": formulas,
                "units": units,
            }
        )
        manifest_payload["inputs"]["manuscript"] = copy.deepcopy(
            manuscript_record
        )
        manifest_payload["source"]["manuscript"] = copy.deepcopy(
            manuscript_record
        )
        manifest_payload["source"]["source_files"] = copy.deepcopy(
            source_files
        )
        self.packet_by_role = self.attach_packets(
            manifest_payload, "packets-footnote-link-deleted"
        )
        self.manifest_payload = manifest_payload
        manifest = self.write_json(
            "manifest-footnote-link-deleted.json", manifest_payload
        )
        review_ids = [
            unit["unit_id"]
            for unit in units
            if unit.get("review_target")
            and unit.get("selected_for_review") is not False
        ]
        paths = self.rebind_results(
            self.passing_result_paths_for_units(
                review_ids, "reviews-footnote-link-deleted"
            ),
            manifest,
        )
        self.base_conservation_gate = self.write_json(
            "conservation-footnote.json",
            self.candidate_only_conservation_payload(
                candidate=candidate,
                candidate_hash=self.candidate_hash,
                content_hash=self.content_hash,
            ),
        )
        completed, report = self.run_validator(paths, manifest=manifest)
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "live_unit_universe_mismatch",
            {item["code"] for item in report["findings"]},
        )

    def test_real_prepare_to_synthetic_reviews_to_validate_interop(self) -> None:
        manuscript = self.write_text(
            "interop/paper.md",
            "# Results\nThe registered sample result appears.\n"
            "# Appendix\nSupplementary note.\n",
        )
        authority_source = self.write_text(
            "interop/author-intent.txt",
            "# Frozen author intent\nThe result is bounded to the registered sample.\n",
        )
        authority_source_hash = digest_bytes(authority_source.read_bytes())
        evidence_source = self.write_text(
            "interop/table-main.txt", "Registered-sample estimate: positive.\n"
        )
        evidence_registry = self.write_json(
            "interop/evidence-registry.json",
            {
                "schema_version": "1.0",
                "schema_id": "evidence-registry/1.0",
                "status": "frozen-current",
                "approval_record": {
                    "confirmed_by": "author",
                    "confirmed_at": "2026-08-03T11:59:00+08:00",
                    "confirmation_source": "author evidence freeze",
                },
                "evidence": [
                    {
                        "source_id": "E1",
                        "source": str(evidence_source),
                        "source_sha256": digest_bytes(evidence_source.read_bytes()),
                        "description": "Registered-sample result table",
                    }
                ],
            },
        )
        evidence_registry_hash = digest_bytes(evidence_registry.read_bytes())
        author_view = {
            "schema_version": "1.0",
            "gate_status": "ready",
            "intent_contract_id": "interop-intent",
            "intent_revision_id": "r1",
            "intent_status": "frozen-current",
            "artifact_role": "qa_view",
            "authority_source": {
                "path": str(authority_source),
                "sha256": authority_source_hash,
                "format": "text",
            },
            "propositions": [
                {
                    "intent_id": "I1",
                    "must_express": "The result is bounded to the registered sample.",
                    "claim_type": "associational",
                    "evidence_anchors": ["E1"],
                }
            ],
            "unresolved_material_questions": [],
            "approval_record": {
                "confirmed_by": "author",
                "confirmed_at": "2026-08-03T12:00:00+08:00",
                "confirmed_scope": "complete_author_intent",
                "confirmation_source": "interop fixture",
                "freeze_authorized_by": "author",
                "freeze_authorized_at": "2026-08-03T12:00:00+08:00",
            },
        }
        projection_hash = canonical_digest(author_view)
        author_view["adapter_confirmation"] = {
            "status": "confirmed",
            "confirmed_by": "author",
            "confirmed_at": "2026-08-03T12:00:00+08:00",
            "confirmed_scope": "complete_author_intent_projection",
            "confirmation_source": "author message 99",
            "authority_source_sha256": authority_source_hash,
            "qa_view_projection_sha256": projection_hash,
            "intent_revision_id": "r1",
        }
        author = self.write_json(
            "interop/author.json",
            {"author_intent_contract": author_view},
        )
        qa = self.write_json(
            "interop/qa.json",
            {
                "qa_contract": {
                    "schema_version": "1.0",
                    "gate_status": "ready",
                    "qa_mode": "exhaustive",
                    "manuscript_path": str(manuscript),
                    "task_classification": {
                        "task_stage": "full_draft",
                        "qa_mode": "exhaustive",
                        "basis": "Interop full-manuscript QA fixture.",
                        "classified_by": "test-controller",
                        "classified_at": "2026-08-03T12:01:00+08:00",
                    },
                    "required_roles": [
                        "author_intent_coverage",
                        "evidence_claim_strength",
                        "definitions_reader_sufficiency",
                        "economic_logic_scope_qualifiers",
                    ],
                    "minimum_high_risk_independent_reviews": 2,
                    "evidence_registry_source": {
                        "path": "evidence-registry.json",
                        "sha256": evidence_registry_hash,
                    },
                }
            },
        )
        interop_artifact = self.write_json(
            "interop/artifact.json",
            {
                "artifact_contract": {
                    "schema_version": "1.0",
                    "artifact_id": "interop-full-draft",
                    "task_mode": "full_draft",
                    "rewrite_mode": "patch_existing",
                    "mature_baseline": False,
                    "target_main_source_word_range": [1, 1000],
                    "hard_main_text_floor": {"source_words": 1},
                    "must_remain_main": [],
                    "content_obligations": [
                        {
                            "obligation_id": "I1",
                            "intent_id": "I1",
                            "obligation_type": "must_express",
                            "kind": "required",
                            "must_express": "The result is bounded to the registered sample.",
                            "claim_type": "associational",
                            "evidence_anchors": ["E1"],
                        }
                    ],
                    "section_cards": [
                        {
                            "section_id": "results",
                            "section_name": "Results",
                            "target_word_range": [1, 1000],
                            "must_remain_main": [
                                {"type": "obligation", "value": "I1"}
                            ],
                            "minimum_depth_questions": [
                                "Is the registered-sample scope explicit?"
                            ],
                        }
                    ],
                    "metric_status": "measured",
                    "measurement_contract": {
                        "appendix_boundary": r"\appendix",
                        "source_word_method": "normalized_words",
                    },
                }
            },
        )
        output = self.root / "interop/out"
        prepared = subprocess.run(
            [
                sys.executable,
                str(PREPARE_SCRIPT),
                "--manuscript",
                str(manuscript),
                "--project-root",
                str(self.root),
                "--author-intent-contract",
                str(author),
                "--qa-contract",
                str(qa),
                "--artifact-contract",
                str(interop_artifact),
                "--output-dir",
                str(output),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
        manifest = output / "qa_manifest.json"
        manifest_payload = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(
            manifest_payload["inputs"]["evidence_registry"]["sha256"],
            evidence_registry_hash,
        )
        self.assertEqual(manifest_payload["evidence_registry"][0]["source_id"], "E1")
        interop_gate = self.root / "interop/conservation.json"
        audited = subprocess.run(
            [
                sys.executable,
                str(AUDIT_SCRIPT),
                "--candidate",
                str(manuscript),
                "--project-root",
                str(self.root),
                "--contract",
                str(interop_artifact),
                "--report",
                str(interop_gate),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(audited.returncode, 0, audited.stdout + audited.stderr)
        target_units = [
            unit
            for unit in manifest_payload["units"]
            if unit["review_target"] and unit["selected_for_review"]
        ]
        sentence = next(unit for unit in target_units if unit["type"] == "sentence")
        units_by_id = {unit["unit_id"]: unit for unit in target_units}
        result_paths = []
        for index, packet in enumerate(manifest_payload["packets"], 1):
            role = packet["role"]
            packet_units = [units_by_id[unit_id] for unit_id in packet["unit_ids"]]
            ledgers = {
                "intent_to_text": [],
                "text_to_intent": [],
                "text_to_evidence": [],
                "definitions": [],
                "revision_rechecks": [],
            }
            if role == "author_intent_coverage":
                ledgers["intent_to_text"] = [
                    {"intent_id": "I1", "unit_ids": [sentence["unit_id"]], "status": "covered"}
                ]
                ledgers["text_to_intent"] = [
                    (
                        {
                            "unit_id": unit["unit_id"],
                            "intent_ids": ["I1"],
                            "status": "authorized",
                        }
                        if unit["unit_id"] == sentence["unit_id"]
                        else {"unit_id": unit["unit_id"], "status": "non_claim"}
                    )
                    for unit in packet_units
                ]
                ledgers["authority_projection_verified"] = [
                    {
                        "status": "pass",
                        "authority_source_sha256": authority_source_hash,
                        "qa_view_projection_sha256": projection_hash,
                        "intent_revision_id": "r1",
                    }
                ]
            if role == "evidence_claim_strength":
                ledgers["text_to_evidence"] = [
                    {
                        "unit_id": sentence["unit_id"],
                        "evidence_ids": ["E1"],
                        "status": "supported",
                    }
                ]
            result = {
                "schema_version": "1.0",
                "result_id": f"interop-result-{index}",
                "manifest_id": manifest_payload["manifest_id"],
                "manifest_sha256": digest_bytes(manifest.read_bytes()),
                "manuscript_sha256": manifest_payload["manuscript_sha256"],
                "content_sha256": manifest_payload["expanded_manuscript_sha256"],
                "contract_sha256": manifest_payload["author_intent_contract_sha256"],
                "qa_contract_sha256": manifest_payload["qa_contract_sha256"],
                "artifact_contract_sha256": manifest_payload[
                    "artifact_contract_sha256"
                ],
                "packet_id": packet["packet_id"],
                "packet_sha256": packet["packet_sha256"],
                "status": "complete",
                "reviewer": {
                    "reviewer_id": f"interop-reviewer-{role}",
                    "role": role,
                    "independence_key": f"interop-isolation-{role}",
                },
                "risk_or_role_escalation": [],
                "unit_reviews": [
                    {
                        "unit_id": unit["unit_id"],
                        "criterion_id": criterion_id,
                        "verdict": "pass",
                        "source_span": unit.get("source")
                        or {
                            "unit_id": unit["unit_id"],
                            "text_sha256": unit["text_sha256"],
                        },
                        "evidence": "Frozen intent and full paragraph context.",
                        "reason": "No semantic deviation was found.",
                        "severity": "none",
                        "confidence": 0.95,
                        "requires_author_action": False,
                    }
                    for unit in packet_units
                    for criterion_id in ROLE_PROTOCOLS[role][
                        "required_criterion_ids"
                    ]
                ],
                "ledgers": ledgers,
                "conflicts": [],
            }
            result_paths.append(self.write_json(f"interop/result-{index}.json", result))
        completed, report = self.run_validator(
            result_paths,
            manifest=manifest,
            contract=author,
            candidate=manuscript,
            extra=[
                "--project-root",
                str(self.root),
                "--upstream-gate",
                str(interop_gate),
            ],
        )
        self.assert_status(completed, report, "pass")
        author_result_path = next(
            path
            for path in result_paths
            if json.loads(path.read_text(encoding="utf-8"))["reviewer"]["role"]
            == "author_intent_coverage"
        )
        author_result = json.loads(author_result_path.read_text(encoding="utf-8"))
        without_projection = copy.deepcopy(author_result)
        without_projection["ledgers"].pop("authority_projection_verified")
        self.write_json(str(author_result_path.relative_to(self.root)), without_projection)
        completed, report = self.run_validator(
            result_paths,
            manifest=manifest,
            contract=author,
            candidate=manuscript,
            extra=["--project-root", str(self.root), "--upstream-gate", str(interop_gate)],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "authority_projection_review_missing",
            {item["code"] for item in report["findings"]},
        )
        wrong_revision = copy.deepcopy(author_result)
        wrong_revision["ledgers"]["authority_projection_verified"][0][
            "intent_revision_id"
        ] = "wrong-revision"
        self.write_json(str(author_result_path.relative_to(self.root)), wrong_revision)
        completed, report = self.run_validator(
            result_paths,
            manifest=manifest,
            contract=author,
            candidate=manuscript,
            extra=["--project-root", str(self.root), "--upstream-gate", str(interop_gate)],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.write_json(str(author_result_path.relative_to(self.root)), author_result)

        missing_confirmation_view = copy.deepcopy(author_view)
        missing_confirmation_view.pop("adapter_confirmation")
        self.write_json(
            str(author.relative_to(self.root)),
            {"author_intent_contract": missing_confirmation_view},
        )
        completed, report = self.run_validator(
            result_paths,
            manifest=manifest,
            contract=author,
            candidate=manuscript,
            extra=["--project-root", str(self.root), "--upstream-gate", str(interop_gate)],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "adapter_confirmation_incomplete",
            {item["code"] for item in report["findings"]},
        )
        wrong_confirmation_view = copy.deepcopy(author_view)
        wrong_confirmation_view["adapter_confirmation"]["intent_revision_id"] = "wrong"
        self.write_json(
            str(author.relative_to(self.root)),
            {"author_intent_contract": wrong_confirmation_view},
        )
        completed, report = self.run_validator(
            result_paths,
            manifest=manifest,
            contract=author,
            candidate=manuscript,
            extra=["--project-root", str(self.root), "--upstream-gate", str(interop_gate)],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn(
            "adapter_confirmation_revision_mismatch",
            {item["code"] for item in report["findings"]},
        )
        self.write_json(
            str(author.relative_to(self.root)),
            {"author_intent_contract": author_view},
        )
        authority_source.write_text("Changed authority.\n", encoding="utf-8")
        completed, report = self.run_validator(
            result_paths,
            manifest=manifest,
            contract=author,
            candidate=manuscript,
            extra=["--project-root", str(self.root), "--upstream-gate", str(interop_gate)],
        )
        self.assert_status(completed, report, "audit_incomplete")
        self.assertIn("authority_source_stale", {item["code"] for item in report["findings"]})


if __name__ == "__main__":
    unittest.main()
