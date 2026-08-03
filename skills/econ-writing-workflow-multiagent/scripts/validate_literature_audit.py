#!/usr/bin/env python3
"""Validate the independent literature-review assignment and audit result.

This standard-library gate does not judge the literature itself.  It verifies
the declared native-agent/task separation, replays the current deterministic
inputs, and checks that the reviewer returned a structurally consistent
``literature-coverage-audit/1.0`` result.  File artifacts can establish an
auditable independence attestation, not prove runtime isolation.  The
deterministic citation and QA-manifest artifacts are canonically replayed
before their passes are trusted.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

try:
    import audit_citation_integrity as citation_auditor
    import prepare_manuscript_qa as qa_preparer
except ImportError:  # pragma: no cover - converted to audit_incomplete below
    citation_auditor = None
    qa_preparer = None


SCHEMA_VERSION = "1.0"
VALIDATION_SCHEMA_ID = "literature-audit-validation/1.0"
GATE_TYPE = "literature_audit_acceptance"
ASSIGNMENT_SCHEMA_ID = "literature-audit-assignment/1.0"
LITERATURE_AUDIT_SCHEMA_ID = "literature-coverage-audit/1.0"
CITATION_REPORT_SCHEMA_ID = "citation-integrity-audit/1.0"
CORE_ASSIGNMENT_SCHEMA_ID = "qa-assignment-registry/1.0"
CORE_SEMANTIC_ROLES = {
    "author_intent_coverage",
    "evidence_claim_strength",
    "definitions_reader_sufficiency",
    "economic_logic_scope_qualifiers",
}
TASK_STAGE_QA_MODES = {
    "full_draft": "exhaustive",
    "proposal_draft": "exhaustive",
    "document_translation": "exhaustive",
    "document_compression": "exhaustive",
    "major_revision": "exhaustive",
    "major_restructure": "exhaustive",
    "final_audit": "exhaustive",
    "local_edit": "bounded_change",
    "local_polish": "bounded_change",
}
AUTHORITY_SCHEMAS = {
    "coverage_contract": "literature-coverage-contract/1.0",
    "reference_library_manifest": "reference-library-manifest/1.0",
    "literature_registry": "literature-registry/1.0",
    "text_to_evidence_ledger": "text-to-evidence-ledger/1.0",
}
EXIT_CODES = {
    "pass": 0,
    "fail": 1,
    "approval_required": 2,
    "metric_unavailable": 3,
    "audit_incomplete": 4,
    "clarification_required": 5,
    "evidence_conflict": 6,
}
STATUS_PRIORITY = (
    "audit_incomplete",
    "metric_unavailable",
    "clarification_required",
    "evidence_conflict",
    "fail",
    "approval_required",
)
FINDING_STATUS = {
    "coverage_gap": "fail",
    "unsupported_claim": "evidence_conflict",
    "unauthorized_nocite": "approval_required",
    "stale_or_invalid_input": "audit_incomplete",
    "metric_unavailable": "metric_unavailable",
    # ``other`` has no closed semantic meaning in version 1.0.  It therefore
    # cannot support delivery without a future schema revision.
    "other": "audit_incomplete",
}
REQUIRED_CHECKS = (
    "applicable_clusters_resolved",
    "source_count_policy_satisfied_or_not_configured",
    "inspected_and_admitted_sources_only",
    "claims_supported_at_stated_strength",
    "citekey_registry_ledger_closed",
)
FINAL_CHECK = "final_bibliography_closed"
CORE_ASSIGNMENT_KINDS = {"semantic_packet", "main_text_sufficiency"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_FUTURE_CLOCK_SKEW = timedelta(minutes=5)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalized_sha(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip().lower()
    return candidate if SHA256_RE.fullmatch(candidate) else ""


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def parse_timestamp(value: Any) -> datetime | None:
    if not nonempty_string(value):
        return None
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(
            candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
        )
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def timestamp_not_future(value: datetime | None) -> bool:
    return bool(
        value is not None
        and value.astimezone(timezone.utc)
        <= datetime.now(timezone.utc) + MAX_FUTURE_CLOCK_SKEW
    )


def resolved_path(value: str | Path, anchor: Path | None = None) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() and anchor is not None:
        path = anchor / path
    return path.resolve()


def input_record(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return {
        "path": str(path),
        "sha256": sha256_file(path) if path.is_file() else None,
    }


@dataclass
class GateAudit:
    findings: list[dict[str, Any]] = field(default_factory=list)

    def add(self, status: str, code: str, message: str, **context: Any) -> None:
        finding: dict[str, Any] = {
            "status": status,
            "code": code,
            "message": message,
        }
        finding.update(
            {key: value for key, value in context.items() if value is not None}
        )
        self.findings.append(finding)

    def status(self) -> str:
        present = {finding["status"] for finding in self.findings}
        for status in STATUS_PRIORITY:
            if status in present:
                return status
        return "pass"

    def sorted_findings(self) -> list[dict[str, Any]]:
        rank = {status: index for index, status in enumerate(STATUS_PRIORITY)}
        return sorted(
            self.findings,
            key=lambda item: (
                rank.get(item["status"], len(rank)),
                item["code"],
                json.dumps(item, ensure_ascii=False, sort_keys=True),
            ),
        )


def load_json(path: Path, label: str, audit: GateAudit) -> dict[str, Any] | None:
    if not path.is_file():
        audit.add(
            "audit_incomplete",
            "input_missing",
            f"Required {label} file is missing.",
            path=str(path),
        )
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        audit.add(
            "audit_incomplete",
            "invalid_json",
            f"Cannot read {label} as UTF-8 JSON: {exc}",
            path=str(path),
        )
        return None
    if not isinstance(payload, dict):
        audit.add(
            "audit_incomplete",
            "invalid_json_root",
            f"{label} must be a JSON object.",
            path=str(path),
        )
        return None
    return payload


def require_schema(
    payload: dict[str, Any] | None,
    expected: str,
    label: str,
    audit: GateAudit,
) -> bool:
    if payload is None:
        return False
    if (
        payload.get("schema_id") != expected
        or payload.get("schema_version") != SCHEMA_VERSION
    ):
        audit.add(
            "audit_incomplete",
            "schema_identity_invalid",
            f"{label} must use schema_id={expected} and schema_version={SCHEMA_VERSION}.",
            actual_schema_id=payload.get("schema_id"),
            actual_schema_version=payload.get("schema_version"),
        )
        return False
    return True


def require_input_hashes(
    raw: Any,
    expected: dict[str, str | None],
    label: str,
    audit: GateAudit,
) -> bool:
    if not isinstance(raw, dict):
        audit.add(
            "audit_incomplete",
            "input_hashes_missing",
            f"{label} requires an input_hashes/hashes object.",
        )
        return False
    valid = True
    mismatches: list[dict[str, Any]] = []
    for key, expected_hash in expected.items():
        actual = normalized_sha(raw.get(key))
        if expected_hash is None:
            if raw.get(key) not in (None, ""):
                mismatches.append(
                    {"field": key, "expected": None, "actual": raw.get(key)}
                )
                valid = False
        elif actual != expected_hash:
            mismatches.append(
                {"field": key, "expected": expected_hash, "actual": raw.get(key)}
            )
            valid = False
    if mismatches:
        audit.add(
            "audit_incomplete",
            "input_hash_binding_invalid",
            f"{label} does not bind every exact live input SHA-256.",
            mismatches=mismatches,
        )
    return valid


def validate_report_input_record(
    inputs: Any,
    key: str,
    expected_path: Path,
    audit: GateAudit,
) -> bool:
    if not isinstance(inputs, dict) or not isinstance(inputs.get(key), dict):
        audit.add(
            "audit_incomplete",
            "citation_report_input_missing",
            "Citation-integrity report is missing a required input record.",
            input_name=key,
        )
        return False
    record = inputs[key]
    raw_path = record.get("path")
    actual_path = (
        resolved_path(raw_path) if nonempty_string(raw_path) else None
    )
    actual_hash = normalized_sha(record.get("sha256"))
    expected_hash = sha256_file(expected_path) if expected_path.is_file() else ""
    if actual_path != expected_path or actual_hash != expected_hash:
        audit.add(
            "audit_incomplete",
            "citation_report_input_stale",
            "Citation-integrity report does not bind the exact current input.",
            input_name=key,
            expected_path=str(expected_path),
            actual_path=str(actual_path) if actual_path is not None else None,
            expected_sha256=expected_hash or None,
            actual_sha256=record.get("sha256"),
        )
        return False
    return True


def report_pointer_path(
    payload: dict[str, Any], key: str, report_path: Path
) -> Path | None:
    inputs = payload.get("inputs")
    record = inputs.get(key) if isinstance(inputs, dict) else None
    raw = record.get("path") if isinstance(record, dict) else None
    if not nonempty_string(raw):
        return None
    return resolved_path(raw, report_path.parent)


def validate_citation_report(
    payload: dict[str, Any] | None,
    report_path: Path,
    explicit_paths: dict[str, Path],
    expected_mode: str,
    audit: GateAudit,
) -> bool:
    if not require_schema(
        payload, CITATION_REPORT_SCHEMA_ID, "Citation-integrity report", audit
    ):
        return False
    assert payload is not None
    valid = True
    report_status = payload.get("status")
    if (
        payload.get("gate_type") != "citation_integrity"
        or payload.get("scope") != "citation_integrity_gate_only"
        or payload.get("mode") != expected_mode
        or report_status not in EXIT_CODES
        or payload.get("gate_local_status") != report_status
        or "delivery_status" in payload
        or payload.get("whole_manuscript_delivery_authorized") is not False
        or payload.get("exit_code") != EXIT_CODES.get(report_status)
    ):
        audit.add(
            "audit_incomplete",
            "citation_report_not_current_pass",
            "Citation-integrity report must be internally consistent for the same mode.",
            report_status=payload.get("status"),
            report_mode=payload.get("mode"),
        )
        valid = False

    for key, path in explicit_paths.items():
        if not validate_report_input_record(payload.get("inputs"), key, path, audit):
            valid = False

    report_hashes = payload.get("hashes")
    recorded_payload_hash = (
        normalized_sha(report_hashes.get("audit_payload_sha256"))
        if isinstance(report_hashes, dict)
        else ""
    )
    unsigned_payload = {key: value for key, value in payload.items() if key != "hashes"}
    if recorded_payload_hash != canonical_hash(unsigned_payload):
        audit.add(
            "audit_incomplete",
            "citation_report_payload_hash_invalid",
            "Citation-integrity report's canonical payload hash is invalid.",
        )
        valid = False

    findings = payload.get("findings")
    finding_statuses = (
        {item.get("status") for item in findings if isinstance(item, dict)}
        if isinstance(findings, list)
        else set()
    )
    findings_well_formed = isinstance(findings, list) and all(
        isinstance(item, dict) and item.get("status") in EXIT_CODES
        for item in findings
    )
    derived_status = "pass"
    for candidate in STATUS_PRIORITY:
        if candidate in finding_statuses:
            derived_status = candidate
            break
    if not findings_well_formed or derived_status != report_status:
        audit.add(
            "audit_incomplete",
            "citation_report_findings_inconsistent",
            "Citation-integrity report status must be derivable from its structured findings.",
            expected_status=derived_status,
            actual_status=report_status,
        )
        valid = False

    source_files = payload.get("manuscript", {}).get("source_files")
    if not isinstance(source_files, list) or not source_files:
        audit.add(
            "audit_incomplete",
            "citation_source_hashes_missing",
            "Citation-integrity report must enumerate the current manuscript source files.",
        )
        valid = False
    else:
        source_records_valid = True
        seen: set[Path] = set()
        for record in source_files:
            if not isinstance(record, dict) or not nonempty_string(record.get("path")):
                source_records_valid = False
                continue
            source = resolved_path(record["path"], report_path.parent)
            current_hash = sha256_file(source) if source.is_file() else ""
            if (
                source in seen
                or normalized_sha(record.get("sha256")) != current_hash
                or not current_hash
            ):
                source_records_valid = False
            seen.add(source)
        if explicit_paths["manuscript"] not in seen:
            source_records_valid = False
        if not source_records_valid:
            audit.add(
                "audit_incomplete",
                "citation_source_hashes_stale",
                "Citation-integrity report source-file hashes are missing, duplicate, or stale.",
            )
            valid = False

    # Canonical replay prevents a self-consistent edited JSON report from being
    # accepted as proof of a current deterministic run.
    if citation_auditor is None:
        audit.add(
            "audit_incomplete",
            "citation_replay_unavailable",
            "audit_citation_integrity.py could not be imported for canonical replay.",
        )
        return False
    qa_manifest = report_pointer_path(payload, "qa_manifest", report_path)
    visible = report_pointer_path(payload, "visible_bibliography", report_path)
    attestation = report_pointer_path(
        payload, "bibliography_build_attestation", report_path
    )
    project_root_raw = payload.get("project_root")
    project_root = (
        resolved_path(project_root_raw, report_path.parent)
        if nonempty_string(project_root_raw)
        else None
    )
    if qa_manifest is None or project_root is None:
        audit.add(
            "audit_incomplete",
            "citation_replay_inputs_missing",
            "Citation-integrity report lacks its QA-manifest or project-root replay input.",
        )
        return False
    if expected_mode == "final" and (visible is None or attestation is None):
        audit.add(
            "audit_incomplete",
            "citation_replay_final_inputs_missing",
            "Final citation replay requires visible bibliography and build attestation inputs.",
        )
        return False
    replay_records = {
        "qa_manifest": qa_manifest,
        "visible_bibliography": visible,
        "bibliography_build_attestation": attestation,
    }
    for key, path in replay_records.items():
        if path is None:
            continue
        if not validate_report_input_record(payload.get("inputs"), key, path, audit):
            valid = False
    try:
        replayed = citation_auditor.run(
            SimpleNamespace(
                mode=expected_mode,
                manuscript=str(explicit_paths["manuscript"]),
                project_root=str(project_root),
                reference_library_manifest=str(
                    explicit_paths["reference_library_manifest"]
                ),
                literature_registry=str(explicit_paths["literature_registry"]),
                coverage_contract=str(explicit_paths["coverage_contract"]),
                text_to_evidence_ledger=str(
                    explicit_paths["text_to_evidence_ledger"]
                ),
                qa_manifest=str(qa_manifest),
                visible_bibliography=str(visible) if visible is not None else None,
                bibliography_build_attestation=(
                    str(attestation) if attestation is not None else None
                ),
                report="",
            )
        )
    except Exception as exc:  # pragma: no cover - defensive fail-close
        audit.add(
            "audit_incomplete",
            "citation_replay_failed",
            f"Canonical citation-integrity replay failed: {exc}",
        )
        return False
    if replayed != payload:
        audit.add(
            "audit_incomplete",
            "citation_report_not_canonical_replay",
            "Citation-integrity report differs from a fresh replay over the live inputs.",
        )
        valid = False
    if valid and report_status != "pass":
        for finding in payload.get("findings", []):
            if not isinstance(finding, dict):
                continue
            source_status = finding.get("status")
            if source_status not in EXIT_CODES or source_status == "pass":
                continue
            source_context = {
                key: value
                for key, value in finding.items()
                if key not in {"status", "code", "message"}
            }
            audit.add(
                str(source_status),
                "citation_integrity_finding",
                str(
                    finding.get("message")
                    or "Deterministic citation-integrity blocker."
                ),
                source_finding_code=finding.get("code"),
                source_finding_context=source_context or None,
            )
        audit.add(
            str(report_status),
            "citation_integrity_gate_blocked",
            "Fresh deterministic citation-integrity audit returned a blocking status.",
            citation_integrity_status=report_status,
        )
    return valid


def validate_qa_manifest_replay(
    payload: dict[str, Any] | None,
    manifest_path: Path,
    manuscript_path: Path,
    audit: GateAudit,
) -> bool:
    """Rebuild the live QA manifest/packets with the shipped preparer."""

    if not require_schema(payload, "qa-manifest/1.0", "QA manifest", audit):
        return False
    assert payload is not None
    if qa_preparer is None:
        audit.add(
            "audit_incomplete",
            "qa_manifest_replay_unavailable",
            "prepare_manuscript_qa.py could not be imported for canonical replay.",
        )
        return False
    manuscript_record = payload.get("manuscript")
    source = payload.get("source")
    if not isinstance(manuscript_record, dict) or not isinstance(source, dict):
        audit.add(
            "audit_incomplete",
            "qa_manifest_replay_inputs_missing",
            "QA manifest lacks its canonical manuscript/source replay records.",
        )
        return False

    def source_path(key: str, required: bool = True) -> Path | None:
        record = source.get(key)
        raw = record.get("path") if isinstance(record, dict) else None
        if not nonempty_string(raw):
            if required:
                audit.add(
                    "audit_incomplete",
                    "qa_manifest_replay_inputs_missing",
                    "QA manifest lacks a required canonical replay source.",
                    input_name=key,
                )
            return None
        return resolved_path(raw, manifest_path.parent)

    recorded_manuscript = manuscript_record.get("path")
    project_root_raw = manuscript_record.get("project_root")
    recorded_path = (
        resolved_path(recorded_manuscript, manifest_path.parent)
        if nonempty_string(recorded_manuscript)
        else None
    )
    project_root = (
        resolved_path(project_root_raw, manifest_path.parent)
        if nonempty_string(project_root_raw)
        else None
    )
    intent_path = source_path("author_intent_contract")
    qa_contract_path = source_path("qa_contract")
    artifact_path = source_path("artifact_contract", required=False)
    if (
        recorded_path != manuscript_path
        or project_root is None
        or intent_path is None
        or qa_contract_path is None
    ):
        audit.add(
            "audit_incomplete",
            "qa_manifest_replay_binding_invalid",
            "QA manifest replay inputs do not bind the explicit live manuscript and contracts.",
        )
        return False

    try:
        with tempfile.TemporaryDirectory(
            prefix="econ-writing-qa-replay-"
        ) as temporary:
            output_dir = Path(temporary) / "qa"
            qa_preparer.prepare(
                SimpleNamespace(
                    manuscript=str(manuscript_path),
                    project_root=str(project_root),
                    author_intent_contract=str(intent_path),
                    qa_contract=str(qa_contract_path),
                    artifact_contract=(
                        str(artifact_path) if artifact_path is not None else None
                    ),
                    output_dir=str(output_dir),
                )
            )
            replay_path = output_dir / "qa_manifest.json"
            replay_payload = json.loads(replay_path.read_text(encoding="utf-8"))
            if replay_payload != payload:
                audit.add(
                    "audit_incomplete",
                    "qa_manifest_not_canonical_replay",
                    "Explicit QA manifest differs from a fresh preparer replay over its live sources.",
                )
                return False
            live_packets = payload.get("packets")
            replay_packets = replay_payload.get("packets")
            if not isinstance(live_packets, list) or live_packets != replay_packets:
                raise ValueError("packet registry mismatch")
            for record in live_packets:
                if not isinstance(record, dict) or not nonempty_string(
                    record.get("path")
                ):
                    raise ValueError("invalid packet record")
                live_packet = resolved_path(record["path"], manifest_path.parent)
                replay_packet = resolved_path(record["path"], replay_path.parent)
                if (
                    not live_packet.is_file()
                    or not replay_packet.is_file()
                    or live_packet.read_bytes() != replay_packet.read_bytes()
                ):
                    raise ValueError("packet bytes differ from canonical replay")
    except Exception as exc:
        audit.add(
            "audit_incomplete",
            "qa_manifest_replay_failed",
            f"Canonical QA-manifest replay failed: {exc}",
        )
        return False
    return True


def validate_core_registry(
    payload: dict[str, Any] | None,
    path: Path | None,
    qa_manifest: dict[str, Any] | None,
    qa_manifest_path: Path,
    audit: GateAudit,
) -> tuple[str | None, set[str], set[str], set[str], bool]:
    if path is None:
        audit.add(
            "audit_incomplete",
            "core_assignment_registry_required",
            "A current core QA assignment registry is required for every triggered paper-level literature audit.",
        )
        return None, set(), set(), set(), False
    registry_hash = sha256_file(path) if path.is_file() else None
    if not require_schema(
        payload, CORE_ASSIGNMENT_SCHEMA_ID, "Core QA assignment registry", audit
    ):
        return registry_hash, set(), set(), set(), False
    if not require_schema(qa_manifest, "qa-manifest/1.0", "QA manifest", audit):
        return registry_hash, set(), set(), set(), False
    assert payload is not None
    assert qa_manifest is not None
    valid = True
    qa_manifest_hash = (
        sha256_file(qa_manifest_path) if qa_manifest_path.is_file() else ""
    )
    qa_mode = qa_manifest.get("qa_mode")
    if (
        qa_manifest.get("status") != "prepared"
        or not nonempty_string(qa_manifest.get("manifest_id"))
        or qa_mode not in {"exhaustive", "bounded_change"}
        or payload.get("status") != "assigned"
        or payload.get("manifest_id") != qa_manifest.get("manifest_id")
        or normalized_sha(payload.get("manifest_sha256")) != qa_manifest_hash
    ):
        valid = False
        audit.add(
            "audit_incomplete",
            "core_assignment_registry_binding_invalid",
            "Core QA registry must bind the exact explicit live QA manifest ID and byte SHA-256.",
        )

    packet_records = qa_manifest.get("packets")
    expected_packets: dict[str, dict[str, str]] = {}
    packet_roles: set[str] = set()
    if not isinstance(packet_records, list) or not packet_records:
        valid = False
    else:
        for record in packet_records:
            if not isinstance(record, dict):
                valid = False
                continue
            packet_id = record.get("packet_id")
            packet_sha = normalized_sha(record.get("packet_sha256"))
            role = record.get("role")
            if (
                not nonempty_string(packet_id)
                or packet_id in expected_packets
                or not packet_sha
                or not nonempty_string(role)
                or role not in CORE_SEMANTIC_ROLES
            ):
                valid = False
                continue
            expected_packets[packet_id] = {
                "packet_sha256": packet_sha,
                "role": role.strip(),
            }
            packet_roles.add(role.strip())
    if packet_roles != CORE_SEMANTIC_ROLES:
        valid = False

    assignments = payload.get("assignments")
    derived_agents: set[str] = set()
    seen_assignment_ids: set[str] = set()
    seen_task_ids: set[str] = set()
    assigned_packets: set[str] = set()
    main_text_count = 0
    agent_roles: dict[str, set[str]] = {}
    if not isinstance(assignments, list) or not assignments:
        valid = False
    else:
        for record in assignments:
            if not isinstance(record, dict):
                valid = False
                continue
            assignment_id = record.get("assignment_id")
            native_agent_id = record.get("native_agent_id")
            task_id = record.get("task_id")
            kind = record.get("assignment_kind")
            assigned_at = parse_timestamp(record.get("assigned_at"))
            if (
                kind not in CORE_ASSIGNMENT_KINDS
                or not nonempty_string(assignment_id)
                or assignment_id != assignment_id.strip()
                or assignment_id in seen_assignment_ids
                or not nonempty_string(native_agent_id)
                or native_agent_id != native_agent_id.strip()
                or not nonempty_string(task_id)
                or task_id != task_id.strip()
                or task_id in seen_task_ids
                or not timestamp_not_future(assigned_at)
            ):
                valid = False
                continue
            assignment_id = assignment_id.strip()
            task_id = task_id.strip()
            seen_assignment_ids.add(assignment_id)
            seen_task_ids.add(task_id)
            native_agent_id = native_agent_id.strip()
            derived_agents.add(native_agent_id)
            if kind == "semantic_packet":
                packet_id = record.get("packet_id")
                expected = (
                    expected_packets.get(packet_id)
                    if isinstance(packet_id, str)
                    else None
                )
                role = record.get("role")
                if (
                    expected is None
                    or packet_id in assigned_packets
                    or record.get("target_id") != packet_id
                    or normalized_sha(record.get("target_sha256"))
                    != expected["packet_sha256"]
                    or normalized_sha(record.get("packet_sha256"))
                    != expected["packet_sha256"]
                    or role != expected["role"]
                ):
                    valid = False
                    continue
                assigned_packets.add(packet_id)
                agent_roles.setdefault(native_agent_id, set()).add(str(role))
            else:
                main_text_count += 1
                expanded_sha = normalized_sha(
                    qa_manifest.get("expanded_manuscript_sha256")
                )
                if (
                    qa_mode != "exhaustive"
                    or main_text_count != 1
                    or record.get("target_id") != "main-text-sufficiency"
                    or not expanded_sha
                    or normalized_sha(record.get("target_sha256"))
                    != expanded_sha
                ):
                    valid = False
                    continue
                agent_roles.setdefault(native_agent_id, set()).add(
                    "main_text_sufficiency"
                )
    if assigned_packets != set(expected_packets):
        valid = False
    if (qa_mode == "exhaustive" and main_text_count != 1) or (
        qa_mode == "bounded_change" and main_text_count != 0
    ):
        valid = False
    if any(len(roles) > 1 for roles in agent_roles.values()):
        valid = False
    if not valid:
        audit.add(
            "audit_incomplete",
            "core_assignment_registry_invalid",
            "Core QA registry must canonically cover every live manifest packet and the mode-applicable fifth role with valid unique identities and targets.",
        )
    return (
        registry_hash,
        derived_agents,
        seen_task_ids,
        seen_assignment_ids,
        valid,
    )


def validate_assignment(
    payload: dict[str, Any] | None,
    path: Path,
    live_hashes: dict[str, str],
    visible_hash: str | None,
    core_hash: str | None,
    core_agents: set[str],
    core_task_ids: set[str],
    core_assignment_ids: set[str],
    expected_mode: str,
    expected_task_stage: str,
    audit: GateAudit,
) -> dict[str, Any] | None:
    if not require_schema(
        payload, ASSIGNMENT_SCHEMA_ID, "Literature audit assignment", audit
    ):
        return None
    assert payload is not None
    valid = True
    required_strings = (
        "assignment_id",
        "controller_id",
        "native_agent_id",
        "task_id",
        "task_stage",
        "independence_basis",
    )
    if any(
        not nonempty_string(payload.get(key))
        or payload[key] != payload[key].strip()
        for key in required_strings
    ):
        valid = False
    assigned_at = parse_timestamp(payload.get("assigned_at"))
    if (
        payload.get("status") != "assigned"
        or not timestamp_not_future(assigned_at)
        or payload.get("mode") != expected_mode
        or payload.get("task_stage") != expected_task_stage
        or payload.get("independent_of_drafting_and_integration") is not True
    ):
        valid = False
    if not valid:
        audit.add(
            "audit_incomplete",
            "literature_assignment_invalid",
            "Literature assignment requires assigned status, a non-future timezone-aware time, exact mode/task stage, native agent/task/controller identities, and an explicit independence attestation.",
        )

    forbidden_raw = payload.get("forbidden_native_agent_ids")
    forbidden: set[str] = set()
    if not isinstance(forbidden_raw, list) or not forbidden_raw:
        audit.add(
            "audit_incomplete",
            "forbidden_agent_set_invalid",
            "Literature assignment requires a nonempty forbidden native-agent list.",
        )
        valid = False
    else:
        for item in forbidden_raw:
            if not nonempty_string(item) or item.strip() in forbidden:
                valid = False
                continue
            forbidden.add(item.strip())
        if len(forbidden) != len(forbidden_raw):
            audit.add(
                "audit_incomplete",
                "forbidden_agent_set_invalid",
                "Forbidden native-agent IDs must be unique nonempty strings.",
            )

    recorded_core_hash = normalized_sha(
        payload.get("core_qa_assignment_registry_sha256")
    )
    if core_hash is None or recorded_core_hash != core_hash:
        audit.add(
            "audit_incomplete",
            "core_registry_hash_stale",
            "Literature assignment does not bind the current core QA registry.",
        )
        valid = False
    missing_forbidden = sorted(core_agents - forbidden)
    if missing_forbidden:
        audit.add(
            "audit_incomplete",
            "core_agents_not_forbidden",
            "Every semantic and fifth-role native agent must be forbidden for the literature review.",
            native_agent_ids=missing_forbidden,
        )
        valid = False
    native_agent_id = payload.get("native_agent_id")
    controller_id = payload.get("controller_id")
    if nonempty_string(controller_id) and controller_id.strip() not in forbidden:
        audit.add(
            "audit_incomplete",
            "controller_not_forbidden",
            "controller_id is the controller native-agent identity and must be in the forbidden reviewer set.",
        )
        valid = False
    if nonempty_string(native_agent_id) and (
        native_agent_id.strip() in forbidden
        or native_agent_id.strip() in core_agents
        or (
            nonempty_string(controller_id)
            and native_agent_id.strip() == controller_id.strip()
        )
    ):
        audit.add(
            "audit_incomplete",
            "literature_reviewer_reused",
            "Literature reviewer reuses a forbidden drafting, integration, semantic, or fifth-role native agent.",
            native_agent_id=native_agent_id.strip(),
        )
        valid = False
    if nonempty_string(payload.get("task_id")) and payload["task_id"].strip() in core_task_ids:
        audit.add(
            "audit_incomplete",
            "literature_task_reused",
            "Literature review task_id must be distinct from every core QA task.",
        )
        valid = False
    if nonempty_string(payload.get("assignment_id")) and payload[
        "assignment_id"
    ].strip() in core_assignment_ids:
        audit.add(
            "audit_incomplete",
            "literature_assignment_id_reused",
            "Literature assignment_id must be distinct from every core QA assignment.",
        )
        valid = False

    expected = dict(live_hashes)
    expected["visible_bibliography_sha256"] = visible_hash
    if not require_input_hashes(
        payload.get("input_hashes"), expected, "Literature assignment", audit
    ):
        valid = False
    if payload.get("mode") == "final" and visible_hash is None:
        audit.add(
            "audit_incomplete",
            "final_visible_bibliography_missing",
            "Final literature assignment requires the live visible bibliography.",
        )
        valid = False
    if not valid:
        return None
    return {
        "assignment_id": payload["assignment_id"].strip(),
        "assignment_sha256": sha256_file(path),
        "native_agent_id": payload["native_agent_id"].strip(),
        "task_id": payload["task_id"].strip(),
        "mode": payload["mode"],
        "task_stage": payload["task_stage"].strip(),
        "assigned_at": assigned_at,
        "forbidden_native_agent_ids": forbidden,
    }


def role_gate_status(
    payload: dict[str, Any], mode: str, audit: GateAudit
) -> tuple[str, bool]:
    checks = payload.get("checks")
    required = list(REQUIRED_CHECKS) + ([FINAL_CHECK] if mode == "final" else [])
    checks_valid = True
    check_values: dict[str, bool] = {}
    if not isinstance(checks, dict):
        audit.add(
            "audit_incomplete",
            "literature_checks_invalid",
            "Literature audit requires a checks object.",
        )
        checks = {}
        checks_valid = False
    elif set(checks) != set(required):
        audit.add(
            "audit_incomplete",
            "literature_checks_scope_invalid",
            "Literature checks must contain exactly the closed key set for the selected mode.",
            required_checks=required,
            actual_checks=sorted(str(key) for key in checks),
        )
        checks_valid = False
    for key in required:
        value = checks.get(key)
        if not isinstance(value, bool):
            checks_valid = False
        else:
            check_values[key] = value
    if not checks_valid:
        audit.add(
            "audit_incomplete",
            "literature_checks_incomplete",
            "Every mode-applicable literature check must be an explicit boolean.",
            required_checks=required,
        )

    raw_findings = payload.get("findings")
    findings_valid = True
    mapped_statuses: set[str] = set()
    finding_types: set[str] = set()
    finding_ids: set[str] = set()
    if not isinstance(raw_findings, list):
        audit.add(
            "audit_incomplete",
            "literature_findings_invalid",
            "Literature audit findings must be an array.",
        )
        raw_findings = []
        findings_valid = False
    for finding in raw_findings:
        if not isinstance(finding, dict):
            findings_valid = False
            continue
        finding_id = finding.get("finding_id")
        finding_type = finding.get("finding_type")
        structurally_valid = (
            nonempty_string(finding_id)
            and finding_id not in finding_ids
            and finding_type in FINDING_STATUS
            and finding.get("evidence") not in (None, "", [], {})
            and nonempty_string(finding.get("reason"))
            and nonempty_string(finding.get("severity"))
            and isinstance(finding.get("requires_author_action"), bool)
        )
        if not structurally_valid:
            findings_valid = False
            continue
        finding_ids.add(finding_id)
        finding_types.add(finding_type)
        mapped_statuses.add(FINDING_STATUS[finding_type])
    if not findings_valid:
        audit.add(
            "audit_incomplete",
            "literature_findings_malformed",
            "Each finding requires a unique ID, closed type, evidence, reason, severity, and boolean author-action flag.",
        )

    valid = checks_valid and findings_valid

    false_checks = {key for key, value in check_values.items() if value is False}
    expected_types = {
        "applicable_clusters_resolved": {"coverage_gap", "metric_unavailable", "stale_or_invalid_input"},
        "source_count_policy_satisfied_or_not_configured": {"coverage_gap", "metric_unavailable", "stale_or_invalid_input"},
        "inspected_and_admitted_sources_only": {"coverage_gap", "unsupported_claim", "metric_unavailable", "stale_or_invalid_input"},
        "claims_supported_at_stated_strength": {"unsupported_claim", "metric_unavailable", "stale_or_invalid_input"},
        "citekey_registry_ledger_closed": {"unauthorized_nocite", "metric_unavailable", "stale_or_invalid_input"},
        "final_bibliography_closed": {"unauthorized_nocite", "metric_unavailable", "stale_or_invalid_input"},
    }
    unmapped_false = sorted(
        key
        for key in false_checks
        if not (expected_types.get(key, set()) & finding_types)
    )
    if unmapped_false:
        audit.add(
            "audit_incomplete",
            "false_check_without_finding",
            "Every failed literature check requires a structured finding that explains it.",
            checks=unmapped_false,
        )
        valid = False

    type_to_check = {
        "coverage_gap": {
            "applicable_clusters_resolved",
            "source_count_policy_satisfied_or_not_configured",
            "inspected_and_admitted_sources_only",
        },
        "unsupported_claim": {
            "claims_supported_at_stated_strength",
            "inspected_and_admitted_sources_only",
        },
        "unauthorized_nocite": {
            "citekey_registry_ledger_closed",
            "final_bibliography_closed",
        },
    }
    unexplained_types = sorted(
        finding_type
        for finding_type, related in type_to_check.items()
        if finding_type in finding_types and not (false_checks & related)
    )
    if unexplained_types:
        audit.add(
            "audit_incomplete",
            "finding_check_inconsistent",
            "Blocking literature findings must be reflected in their corresponding checks.",
            finding_types=unexplained_types,
        )
        valid = False

    if finding_types and not false_checks:
        audit.add(
            "audit_incomplete",
            "blocking_finding_without_failed_check",
            "A blocking literature finding cannot coexist with all checks marked true.",
            finding_types=sorted(finding_types),
        )
        valid = False

    if mapped_statuses:
        expected_status = "pass"
        for status in STATUS_PRIORITY:
            if status in mapped_statuses:
                expected_status = status
                break
    elif false_checks:
        expected_status = "audit_incomplete"
    else:
        expected_status = "pass"
    actual_status = payload.get("gate_status")
    if actual_status != expected_status:
        audit.add(
            "audit_incomplete",
            "literature_gate_status_inconsistent",
            "Literature gate_status does not match its checks and findings.",
            expected_gate_status=expected_status,
            actual_gate_status=actual_status,
        )
        valid = False
    return expected_status, valid


def validate_literature_audit(
    payload: dict[str, Any] | None,
    path: Path,
    assignment: dict[str, Any] | None,
    live_hashes: dict[str, str],
    visible_hash: str | None,
    expected_mode: str,
    expected_task_stage: str,
    audit: GateAudit,
) -> tuple[str, bool]:
    if not require_schema(
        payload, LITERATURE_AUDIT_SCHEMA_ID, "Literature role audit", audit
    ):
        return "audit_incomplete", False
    assert payload is not None
    valid = True
    generated_at = parse_timestamp(payload.get("generated_at"))
    if (
        payload.get("status") != "complete"
        or not nonempty_string(payload.get("audit_id"))
        or payload.get("mode") != expected_mode
        or payload.get("task_stage") != expected_task_stage
        or not timestamp_not_future(generated_at)
    ):
        audit.add(
            "audit_incomplete",
            "literature_audit_identity_invalid",
            "Literature audit requires complete status, audit ID, exact mode/task stage, and a non-future timezone-aware generation time.",
        )
        valid = False

    if assignment is None:
        audit.add(
            "audit_incomplete",
            "literature_assignment_unusable",
            "A valid current assignment is required before accepting the literature audit.",
        )
        valid = False
    else:
        if (
            payload.get("assignment_id") != assignment["assignment_id"]
            or normalized_sha(payload.get("assignment_sha256"))
            != assignment["assignment_sha256"]
            or payload.get("mode") != assignment["mode"]
            or payload.get("task_stage") != assignment["task_stage"]
        ):
            audit.add(
                "audit_incomplete",
                "literature_audit_assignment_stale",
                "Literature audit does not bind the exact current assignment and mode.",
            )
            valid = False
        if generated_at is not None and generated_at < assignment["assigned_at"]:
            audit.add(
                "audit_incomplete",
                "literature_audit_time_invalid",
                "Literature audit cannot predate its assignment.",
            )
            valid = False

    reviewer = payload.get("reviewer")
    if (
        not isinstance(reviewer, dict)
        or not nonempty_string(reviewer.get("reviewer_id"))
        or not nonempty_string(reviewer.get("native_agent_id"))
        or not nonempty_string(reviewer.get("task_id"))
    ):
        audit.add(
            "audit_incomplete",
            "literature_reviewer_missing",
            "Literature audit requires reviewer, native-agent, and task identities.",
        )
        valid = False
    elif assignment is not None and (
        reviewer["native_agent_id"].strip() != assignment["native_agent_id"]
        or reviewer["task_id"].strip() != assignment["task_id"]
        or reviewer["native_agent_id"].strip()
        in assignment["forbidden_native_agent_ids"]
    ):
        audit.add(
            "audit_incomplete",
            "literature_reviewer_assignment_mismatch",
            "Literature result reviewer/task must match the independent assignment and remain outside its forbidden set.",
        )
        valid = False

    expected = dict(live_hashes)
    expected["visible_bibliography_sha256"] = visible_hash
    if not require_input_hashes(
        payload.get("hashes"), expected, "Literature role audit", audit
    ):
        valid = False
    if assignment is not None and payload.get("mode") == "final" and visible_hash is None:
        valid = False

    expected_gate, gate_valid = role_gate_status(payload, expected_mode, audit)
    valid = valid and gate_valid
    if valid and expected_gate != "pass":
        for finding in payload.get("findings", []):
            finding_type = finding["finding_type"]
            audit.add(
                FINDING_STATUS[finding_type],
                "literature_role_finding",
                finding["reason"],
                finding_id=finding["finding_id"],
                finding_type=finding_type,
                evidence=finding["evidence"],
                severity=finding["severity"],
                requires_author_action=finding["requires_author_action"],
            )
        audit.add(
            expected_gate,
            "literature_role_gate_blocked",
            "Independent literature audit returned a current blocking gate status.",
            literature_gate_status=expected_gate,
            literature_audit_sha256=sha256_file(path),
        )
    return expected_gate, valid


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--mode", choices=("draft", "final"), required=True)
    cli.add_argument("--manuscript", required=True)
    cli.add_argument("--coverage-contract", required=True)
    cli.add_argument("--reference-library-manifest", required=True)
    cli.add_argument("--literature-registry", required=True)
    cli.add_argument("--text-to-evidence-ledger", required=True)
    cli.add_argument("--qa-manifest", required=True)
    cli.add_argument("--citation-integrity-report", required=True)
    cli.add_argument("--literature-assignment", required=True)
    cli.add_argument("--literature-audit", required=True)
    cli.add_argument("--visible-bibliography")
    cli.add_argument("--core-qa-assignment-registry", required=True)
    cli.add_argument("--report", required=True)
    return cli


def run(args: argparse.Namespace) -> dict[str, Any]:
    audit = GateAudit()
    paths: dict[str, Path] = {
        "manuscript": resolved_path(args.manuscript),
        "coverage_contract": resolved_path(args.coverage_contract),
        "reference_library_manifest": resolved_path(
            args.reference_library_manifest
        ),
        "literature_registry": resolved_path(args.literature_registry),
        "text_to_evidence_ledger": resolved_path(
            args.text_to_evidence_ledger
        ),
        "qa_manifest": resolved_path(args.qa_manifest),
        "citation_integrity_report": resolved_path(
            args.citation_integrity_report
        ),
        "literature_assignment": resolved_path(args.literature_assignment),
        "literature_audit": resolved_path(args.literature_audit),
    }
    visible_path = (
        resolved_path(args.visible_bibliography)
        if args.visible_bibliography
        else None
    )
    core_path = resolved_path(args.core_qa_assignment_registry)

    for key, path in paths.items():
        if not path.is_file():
            audit.add(
                "audit_incomplete",
                "input_missing",
                "Required literature validation input is missing.",
                input_name=key,
                path=str(path),
            )
    if visible_path is not None and not visible_path.is_file():
        audit.add(
            "audit_incomplete",
            "visible_bibliography_missing",
            "Supplied visible bibliography does not exist.",
            path=str(visible_path),
        )
    if not core_path.is_file():
        audit.add(
            "audit_incomplete",
            "core_assignment_registry_missing",
            "Supplied core QA assignment registry does not exist.",
            path=str(core_path),
        )

    coverage = load_json(paths["coverage_contract"], "coverage contract", audit)
    library = load_json(
        paths["reference_library_manifest"], "reference library manifest", audit
    )
    registry = load_json(paths["literature_registry"], "literature registry", audit)
    ledger = load_json(
        paths["text_to_evidence_ledger"], "text-to-evidence ledger", audit
    )
    qa_manifest = load_json(paths["qa_manifest"], "QA manifest", audit)
    citation_report = load_json(
        paths["citation_integrity_report"], "citation-integrity report", audit
    )
    assignment_payload = load_json(
        paths["literature_assignment"], "literature assignment", audit
    )
    literature_payload = load_json(
        paths["literature_audit"], "literature role audit", audit
    )
    core_payload = load_json(core_path, "core QA assignment registry", audit)

    authority_payloads = {
        "coverage_contract": coverage,
        "reference_library_manifest": library,
        "literature_registry": registry,
        "text_to_evidence_ledger": ledger,
    }
    for key, expected_schema in AUTHORITY_SCHEMAS.items():
        require_schema(authority_payloads[key], expected_schema, key, audit)
    qa_manifest_replay_valid = validate_qa_manifest_replay(
        qa_manifest,
        paths["qa_manifest"],
        paths["manuscript"],
        audit,
    )

    file_hashes = {
        key: sha256_file(path) if path.is_file() else ""
        for key, path in paths.items()
    }
    live_hashes = {
        "manuscript_sha256": file_hashes["manuscript"],
        "literature_coverage_contract_sha256": file_hashes["coverage_contract"],
        "reference_library_manifest_sha256": file_hashes[
            "reference_library_manifest"
        ],
        "literature_registry_sha256": file_hashes["literature_registry"],
        "text_to_evidence_ledger_sha256": file_hashes[
            "text_to_evidence_ledger"
        ],
        "citation_integrity_report_sha256": file_hashes[
            "citation_integrity_report"
        ],
        "qa_manifest_sha256": file_hashes["qa_manifest"],
        "core_qa_assignment_registry_sha256": (
            sha256_file(core_path) if core_path.is_file() else ""
        ),
    }
    visible_hash = (
        sha256_file(visible_path)
        if visible_path is not None and visible_path.is_file()
        else None
    )

    coverage_stage = (
        coverage.get("task_stage") if isinstance(coverage, dict) else None
    )
    qa_classification = (
        qa_manifest.get("task_classification")
        if isinstance(qa_manifest, dict)
        else None
    )
    qa_stage = (
        qa_classification.get("task_stage")
        if isinstance(qa_classification, dict)
        else None
    )
    expected_task_stage = coverage_stage if nonempty_string(coverage_stage) else ""
    expected_qa_mode = TASK_STAGE_QA_MODES.get(expected_task_stage)
    manifest_qa_mode = (
        qa_manifest.get("qa_mode") if isinstance(qa_manifest, dict) else None
    )
    classification_qa_mode = (
        qa_classification.get("qa_mode")
        if isinstance(qa_classification, dict)
        else None
    )
    if (
        not expected_task_stage
        or expected_qa_mode is None
        or qa_stage != expected_task_stage
        or manifest_qa_mode != expected_qa_mode
        or classification_qa_mode != expected_qa_mode
    ):
        audit.add(
            "audit_incomplete",
            "literature_task_stage_authority_mismatch",
            "Coverage contract and canonical QA manifest must use the same closed task_stage and its exact QA mode.",
            coverage_task_stage=coverage_stage,
            qa_task_stage=qa_stage,
            manifest_qa_mode=manifest_qa_mode,
            classification_qa_mode=classification_qa_mode,
            expected_qa_mode=expected_qa_mode,
        )
    if expected_task_stage == "final_audit" and args.mode != "final":
        audit.add(
            "audit_incomplete",
            "final_audit_mode_downgrade",
            "task_stage=final_audit requires final citation and literature-audit mode.",
        )
    if args.mode == "draft" and visible_path is not None:
        audit.add(
            "audit_incomplete",
            "draft_visible_bibliography_unexpected",
            "Draft mode must not bind a final visible bibliography.",
        )
    citation_explicit = {
        "manuscript": paths["manuscript"],
        "coverage_contract": paths["coverage_contract"],
        "reference_library_manifest": paths["reference_library_manifest"],
        "literature_registry": paths["literature_registry"],
        "text_to_evidence_ledger": paths["text_to_evidence_ledger"],
        "qa_manifest": paths["qa_manifest"],
    }
    if visible_path is not None:
        citation_explicit["visible_bibliography"] = visible_path
    validate_citation_report(
        citation_report,
        paths["citation_integrity_report"],
        citation_explicit,
        args.mode,
        audit,
    )

    (
        core_hash,
        core_agents,
        core_task_ids,
        core_assignment_ids,
        core_registry_valid,
    ) = (
        validate_core_registry(
            core_payload,
            core_path,
            qa_manifest,
            paths["qa_manifest"],
            audit,
        )
    )
    assignment = validate_assignment(
        assignment_payload,
        paths["literature_assignment"],
        live_hashes,
        visible_hash,
        core_hash,
        core_agents,
        core_task_ids,
        core_assignment_ids,
        args.mode,
        expected_task_stage,
        audit,
    )
    role_gate, role_valid = validate_literature_audit(
        literature_payload,
        paths["literature_audit"],
        assignment,
        live_hashes,
        visible_hash,
        args.mode,
        expected_task_stage,
        audit,
    )
    if not role_valid and role_gate != "audit_incomplete":
        # Structural invalidity always prevents semantic status from being
        # treated as an authenticated result.
        role_gate = "audit_incomplete"

    status = audit.status()
    findings = audit.sorted_findings()
    independence_attested = bool(
        qa_manifest_replay_valid
        and core_registry_valid
        and assignment is not None
        and role_valid
    )
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "schema_id": VALIDATION_SCHEMA_ID,
        "gate_type": GATE_TYPE,
        "scope": "literature_gate_only",
        "status": status,
        "gate_local_status": status,
        "whole_manuscript_delivery_authorized": False,
        "exit_code": EXIT_CODES[status],
        "literature_gate_status": role_gate,
        "inputs": {
            **{key: input_record(path) for key, path in sorted(paths.items())},
            "visible_bibliography": input_record(visible_path),
            "core_qa_assignment_registry": input_record(core_path),
        },
        "derived_forbidden_native_agent_ids": sorted(core_agents),
        "independence_assurance": {
            "attested": independence_attested,
            "proven": False,
            "status": (
                "structurally_consistent_file_attestation"
                if independence_attested
                else "unverified"
            ),
            "note": "Canonical file artifacts verify the internal consistency of declared identities and hash bindings; they cannot prove that the declared runtime actor list is complete or that agent isolation occurred.",
        },
        "finding_counts": {
            status_name: sum(
                1 for finding in findings if finding["status"] == status_name
            )
            for status_name in sorted({finding["status"] for finding in findings})
        },
        "findings": findings,
    }
    report["hashes"] = {
        "validation_payload_sha256": canonical_hash(report),
        "literature_assignment_sha256": file_hashes["literature_assignment"]
        or None,
        "literature_audit_sha256": file_hashes["literature_audit"] or None,
        "citation_integrity_report_sha256": file_hashes[
            "citation_integrity_report"
        ]
        or None,
        "qa_manifest_sha256": file_hashes["qa_manifest"] or None,
        "core_qa_assignment_registry_sha256": core_hash,
    }
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = run(args)
    except Exception as exc:  # pragma: no cover - final fail-closed boundary
        status = "audit_incomplete"
        report = {
            "schema_version": SCHEMA_VERSION,
            "schema_id": VALIDATION_SCHEMA_ID,
            "gate_type": GATE_TYPE,
            "scope": "literature_gate_only",
            "status": status,
            "gate_local_status": status,
            "whole_manuscript_delivery_authorized": False,
            "exit_code": EXIT_CODES[status],
            "literature_gate_status": status,
            "inputs": {},
            "derived_forbidden_native_agent_ids": [],
            "independence_assurance": {
                "attested": False,
                "proven": False,
                "status": "unverified",
                "note": "Validation failed before structural independence could be assessed.",
            },
            "finding_counts": {status: 1},
            "findings": [
                {
                    "status": status,
                    "code": "literature_validation_internal_error",
                    "message": str(exc),
                }
            ],
        }
        report["hashes"] = {"validation_payload_sha256": canonical_hash(report)}
    report_path = resolved_path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"literature audit validation: {report['status']}; report={report_path}")
    for finding in report.get("findings", []):
        if finding.get("status") != "pass":
            print(
                f"{str(finding.get('status')).upper()}: "
                f"{finding.get('code')}: {finding.get('message')}"
            )
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
