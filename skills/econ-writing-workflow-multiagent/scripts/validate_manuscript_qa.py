#!/usr/bin/env python3
"""Fail-closed validator for exhaustive manuscript QA records.

The validator is deliberately deterministic and standard-library-only.  It
does not decide whether prose is true, well written, or faithful.  Instead it
checks that the semantic reviewers supplied a complete, fresh, internally
consistent audit trail for the exact manuscript and author-intent contract.

Review-result schema (version 1.0), abbreviated::

    {
      "schema_version": "1.0",
      "result_id": "...",
      "manifest_id": "...",
      "manifest_sha256": "...",
      "manuscript_sha256": "...",
      "contract_sha256": "...",
      "content_sha256": "...",
      "qa_contract_sha256": "...",
      "artifact_contract_sha256": "...", # when an artifact contract exists
      "packet_id": "...",
      "packet_sha256": "...",
      "revision_id": "...",                 # required after a patch
      "status": "complete",
      "reviewer": {
        "reviewer_id": "...",
        "role": "author_intent_coverage",
        "independence_key": "..."
      },
      "unit_reviews": [{
        "unit_id": "...", "criterion_id": "...", "verdict": "pass",
        "source_span": {"start": 0, "end": 10},
        "evidence": "...", "reason": "...",
        "severity": "none", "confidence": 1.0,
        "requires_author_action": false
      }],
      "ledgers": {
        "intent_to_text": [], "text_to_intent": [],
        "text_to_evidence": [], "definitions": [],
        "baseline_to_candidate": [], "revision_rechecks": []
      },
      "conflicts": []
    }

Directories passed with ``--review-result`` are scanned recursively for JSON
files.  A missing, malformed, stale, or incomplete record never degrades to a
warning: delivery remains blocked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    import prepare_manuscript_qa as qa_preparer
except ImportError:  # pragma: no cover - reported fail-closed at runtime
    qa_preparer = None

try:
    import audit_manuscript_conservation as conservation_auditor
except ImportError:  # pragma: no cover - reported fail-closed at runtime
    conservation_auditor = None


SCHEMA_VERSION = "1.0"
QA_MANIFEST_SCHEMA_ID = "qa-manifest/1.0"
CONSERVATION_SCHEMA_ID = "manuscript-conservation-audit/1.0"
CONSERVATION_GATE_TYPE = "manuscript_conservation"
ASSIGNMENT_SCHEMA_ID = "qa-assignment-registry/1.0"
MAIN_TEXT_SUFFICIENCY_SCHEMA_ID = "main-text-sufficiency-audit/1.0"
MAIN_TEXT_SUFFICIENCY_GATE_TYPE = "main_text_sufficiency_and_conservation"
ROLE_PROTOCOL_VERSION = "1.0"
MAX_UNITS_PER_PACKET_CEILING = 25
MAX_PACKET_BYTES_CEILING = 240_000
MIN_PACKET_BYTES = 10_000
TASK_STAGE_TO_QA_MODE = {
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
ARTIFACT_CONTRACT_REQUIRED_STAGES = {
    "full_draft",
    "proposal_draft",
    "document_translation",
    "document_compression",
    "major_revision",
    "major_restructure",
    "final_audit",
}
ARTIFACT_TASK_MODE_ALIASES = {
    "translation": "document_translation",
}
MAIN_TEXT_SUFFICIENCY_CHECKS = (
    "main_text_self_contained",
    "definitions_and_assumptions_sufficient",
    "data_model_sample_explained",
    "economic_interpretation_present",
    "required_content_in_main_text",
    "appendix_moves_authorized",
    "baseline_content_conserved",
    "length_and_depth_contract_satisfied",
)
REQUIRED_SEMANTIC_ROLES = (
    "author_intent_coverage",
    "evidence_claim_strength",
    "definitions_reader_sufficiency",
    "economic_logic_scope_qualifiers",
)
# Compatibility alias for internal callers.  Validation never delegates the
# minimum role universe to an author-supplied contract.
DEFAULT_QA_ROLES = REQUIRED_SEMANTIC_ROLES
ROLE_PROTOCOLS: dict[str, dict[str, Any]] = {
    "author_intent_coverage": {
        "required_criterion_ids": [
            "intent_coverage",
            "unauthorized_claim",
            "prohibited_implication",
            "qualifier_fidelity",
        ],
        "criterion_definitions": {
            "intent_coverage": "Check that required meaning and obligations are present in the authorized location without weakening or deletion.",
            "unauthorized_claim": "Map each substantive statement to frozen intent and reject additions or changed emphasis without authority.",
            "prohibited_implication": "Check must-not-claim, must-not-imply, and forbidden-frame constraints, including equivalent implications.",
            "qualifier_fidelity": "Check required qualifiers and consistency with dependent abstract/body/conclusion/caption/note statements.",
        },
    },
    "evidence_claim_strength": {
        "required_criterion_ids": [
            "evidence_support",
            "claim_strength",
            "causal_language",
            "numeric_fidelity",
        ],
        "criterion_definitions": {
            "evidence_support": "Check current inspected anchors, provenance, and support; reject invented facts or citations.",
            "claim_strength": "Check descriptive, associational, theoretical, mechanism, and normative wording against the evidence ceiling.",
            "causal_language": "Check identification and causal wording separately from association, heterogeneity, and mechanism evidence.",
            "numeric_fidelity": "Check values, samples, units, signs, magnitudes, comparisons, and uncertainty.",
        },
    },
    "definitions_reader_sufficiency": {
        "required_criterion_ids": [
            "definition_before_use",
            "definition_sufficiency",
            "term_consistency",
            "referent_clarity",
        ],
        "criterion_definitions": {
            "definition_before_use": "Check registered terms, symbols, acronyms, actors, samples, and model objects before first substantive use.",
            "definition_sufficiency": "Check that a definition supplies what a reader needs rather than merely naming the object.",
            "term_consistency": "Check canonical meanings, symbols, and allowed variants across the packet and dependencies.",
            "referent_clarity": "Check pronouns, comparisons, denominators, scopes, and references for an unambiguous interpretation.",
        },
    },
    "economic_logic_scope_qualifiers": {
        "required_criterion_ids": [
            "economic_logic",
            "mechanism_authorization",
            "scope_conditions",
            "comparison_direction",
            "qualifier_preservation",
        ],
        "criterion_definitions": {
            "economic_logic": "Check actor, constraint, behavior, outcome, and equilibrium or institutional links; flag missing steps.",
            "mechanism_authorization": "Check that mechanism statements are authorized and distinct from heterogeneity or suggestive interpretation.",
            "scope_conditions": "Check population, period, geography, domain, uncertainty, caveats, and exceptions.",
            "comparison_direction": "Check comparison group or model benchmark, sign/direction, sequence, and timing.",
            "qualifier_preservation": "Check negation, uncertainty, scope qualifiers, and the separation of association, causality, heterogeneity, and mechanism evidence.",
        },
    },
}
EXIT_CODES = {
    "pass": 0,
    "fail": 1,
    # Keep the conservation-audit exit codes stable when its gate is composed.
    "approval_required": 2,
    "metric_unavailable": 3,
    "audit_incomplete": 4,
    "clarification_required": 5,
    "evidence_conflict": 6,
}

# The first matching status wins.  Structural incompleteness outranks semantic
# findings because a pass/fail conclusion is not reproducible without a valid
# audit universe.  Known author/evidence blocks then outrank ordinary failures.
STATUS_PRIORITY = (
    "audit_incomplete",
    "metric_unavailable",
    "clarification_required",
    "evidence_conflict",
    "fail",
    "approval_required",
)
FIFTH_ROLE_STATUS_PRIORITY = (
    "fail",
    "approval_required",
    "metric_unavailable",
)

COMPLETE_RESULT_STATUSES = {"complete", "completed", "final"}
PASS_VERDICTS = {"pass", "not_applicable", "non_claim", "authorized_function"}
FAIL_VERDICTS = {"fail", "violation"}
UNCERTAIN_VERDICTS = {"uncertain", "needs_author", "clarification_required"}
EVIDENCE_VERDICTS = {"evidence_conflict", "unsupported", "contradicted"}
KNOWN_VERDICTS = PASS_VERDICTS | FAIL_VERDICTS | UNCERTAIN_VERDICTS | EVIDENCE_VERDICTS
LEDGER_PASS = {
    "pass",
    "covered",
    "satisfied",
    "verified",
    "authorized",
    "complete",
    "supported",
    "aligned",
    "bounded",
    "verified_absent",
    "compliant",
}
LEDGER_NONCLAIM = {"non_claim", "not_applicable", "authorized_function"}
KNOWN_LEDGER_STATUSES = (
    LEDGER_PASS
    | LEDGER_NONCLAIM
    | FAIL_VERDICTS
    | UNCERTAIN_VERDICTS
    | EVIDENCE_VERDICTS
    | {"unused", "not_used", "defined_before_use", "rechecked", "reviewed"}
)
HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def role_protocols_hash() -> str:
    return canonical_hash(
        {
            "role_protocol_version": ROLE_PROTOCOL_VERSION,
            "role_protocols": ROLE_PROTOCOLS,
        }
    )


def stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}_{sha256_text('|'.join(str(item) for item in parts))[:16]}"


def is_review_target(unit: dict[str, Any]) -> bool:
    """Return true only for units admitted to this manifest's review scope."""

    return bool(unit.get("review_target", True)) and unit.get(
        "selected_for_review", True
    ) is not False


def normalize_role(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict, tuple, set)):
        return bool(value)
    return True


def nested(mapping: Any, *keys: str) -> Any:
    current = mapping
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def first_present(mapping: Any, paths: Sequence[Sequence[str]]) -> Any:
    for path in paths:
        value = nested(mapping, *path)
        if value is not None:
            return value
    return None


def normalized_sha(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip().lower()
    return candidate if HEX_SHA256_RE.fullmatch(candidate) else ""


def valid_iso8601_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = value.strip()
    try:
        parsed = datetime.fromisoformat(
            candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
        )
    except ValueError:
        return False
    return parsed.tzinfo is not None


@dataclass
class GateAudit:
    findings: list[dict[str, Any]] = field(default_factory=list)

    def add(self, status: str, code: str, message: str, **context: Any) -> None:
        finding: dict[str, Any] = {
            "status": status,
            "code": code,
            "message": message,
        }
        finding.update({key: value for key, value in context.items() if value is not None})
        self.findings.append(finding)

    def status(self) -> str:
        present = {item["status"] for item in self.findings}
        for status in STATUS_PRIORITY:
            if status in present:
                return status
        return "pass"


def load_json_object(path: Path, audit: GateAudit, label: str) -> dict[str, Any] | None:
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


def require_schema(payload: dict[str, Any], audit: GateAudit, label: str, path: Path) -> bool:
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        audit.add(
            "audit_incomplete",
            "unsupported_schema_version",
            f"{label} schema_version must be {SCHEMA_VERSION!r}; found {version!r}.",
            path=str(path),
        )
        return False
    return True


def expand_review_paths(values: Sequence[str], audit: GateAudit) -> list[Path]:
    paths: list[Path] = []
    for raw in values:
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            found = sorted(item for item in path.rglob("*.json") if item.is_file())
            if not found:
                audit.add(
                    "audit_incomplete",
                    "empty_review_directory",
                    "Review-result directory contains no JSON files.",
                    path=str(path),
                )
            paths.extend(found)
        elif path.is_file():
            paths.append(path)
        else:
            audit.add(
                "audit_incomplete",
                "review_path_missing",
                "Review-result path does not exist.",
                path=str(path),
            )
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        if path not in seen:
            seen.add(path)
            unique.append(path)
    if not unique:
        audit.add(
            "audit_incomplete",
            "no_review_results",
            "At least one review-result JSON file is required.",
        )
    return unique


def resolve_bound_path(raw: Any, base: Path) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def artifact_baseline_binding(
    artifact_contract: dict[str, Any], contract_path: Path | None
) -> tuple[Path | None, str, str, str]:
    for key in (
        "baseline_source",
        "baseline_path",
        "baseline_manuscript",
        "baseline_artifact",
    ):
        value = artifact_contract.get(key)
        raw_path: Any = value
        raw_hash: Any = None
        accepted_by: Any = None
        acceptance_status: Any = None
        if isinstance(value, dict):
            raw_path = first_present(value, (("path",), ("source",), ("manuscript",)))
            raw_hash = first_present(
                value, (("sha256",), ("hash",), ("version_or_hash",))
            )
            accepted_by = value.get("accepted_by")
            acceptance_status = first_present(
                value,
                (("acceptance_status",), ("status",), ("artifact_status",)),
            )
        if nonempty(raw_path):
            base = contract_path.parent if contract_path is not None else Path.cwd()
            return (
                resolve_bound_path(raw_path, base),
                normalized_sha(raw_hash),
                str(accepted_by).strip() if isinstance(accepted_by, str) else "",
                (
                    str(acceptance_status).strip().lower()
                    if isinstance(acceptance_status, str)
                    else ""
                ),
            )
    return None, "", "", ""


def validate_conservation_structure(
    payload: dict[str, Any], path: Path, audit: GateAudit
) -> bool:
    valid = True
    required_objects = {
        "inputs": (),
        "measurement": (
            "word_metric_for_contract",
            "baseline_comparison_applicable",
            "cross_language_length_metric",
            "verified_page_attestation",
            "page_metric_note",
        ),
        "metrics": (
            "baseline_main",
            "candidate_main",
            "baseline_appendix",
            "candidate_appendix",
            "word_reduction_pct",
            "cumulative_reduction_pct",
            "structural_delta",
            "section_changes",
        ),
        "conservation": (
            "ledger_required",
            "candidate_only_full_draft_contract",
            "two_pass_restructure",
            "expected_baseline_block_ids",
            "baseline_block_inventory",
            "candidate_block_inventory",
            "ledger_validation",
            "whole_sections_missing_or_moved",
            "labels_moved_to_appendix",
            "labels_missing_entirely",
            "must_remain_main_missing",
        ),
        "findings": ("failures", "approval_triggers", "warnings"),
    }
    for field_name, required_keys in required_objects.items():
        value = payload.get(field_name)
        if not isinstance(value, dict):
            audit.add(
                "audit_incomplete",
                "conservation_report_structure_invalid",
                "Typed conservation report is missing a required object.",
                path=str(path),
                field=field_name,
            )
            valid = False
            continue
        missing = [key for key in required_keys if key not in value]
        if missing:
            audit.add(
                "audit_incomplete",
                "conservation_report_structure_invalid",
                "Typed conservation report is missing required fields.",
                path=str(path),
                field=field_name,
                missing_fields=missing,
            )
            valid = False
    findings = payload.get("findings")
    if isinstance(findings, dict):
        for key in ("failures", "approval_triggers", "warnings"):
            if key in findings and not isinstance(findings[key], list):
                audit.add(
                    "audit_incomplete",
                    "conservation_findings_invalid",
                    "Conservation finding collections must be lists.",
                    path=str(path),
                    field=key,
                )
                valid = False
    status = str(payload.get("status", "")).strip().lower()
    if isinstance(findings, dict):
        if status == "pass" and (
            findings.get("failures") or findings.get("approval_triggers")
        ):
            audit.add(
                "audit_incomplete",
                "conservation_status_findings_mismatch",
                "Passing conservation report cannot contain failures or approval triggers.",
                path=str(path),
            )
            valid = False
        elif status == "fail" and not findings.get("failures"):
            audit.add(
                "audit_incomplete",
                "conservation_status_findings_mismatch",
                "Failing conservation report requires at least one failure finding.",
                path=str(path),
            )
            valid = False
        elif status == "approval_required" and not findings.get("approval_triggers"):
            audit.add(
                "audit_incomplete",
                "conservation_status_findings_mismatch",
                "approval_required conservation report requires an approval trigger.",
                path=str(path),
            )
            valid = False
    return valid


def numeric_range(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    low, high = value
    if (
        isinstance(low, bool)
        or not isinstance(low, (int, float))
        or isinstance(high, bool)
        or not isinstance(high, (int, float))
    ):
        return None
    low_value = float(low)
    high_value = float(high)
    if low_value < 0 or high_value < low_value:
        return None
    return low_value, high_value


def artifact_collection_count(value: Any) -> int:
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return 1 if isinstance(value, str) and value.strip() else 0


def validate_candidate_only_contract_summary(
    payload: dict[str, Any],
    path: Path,
    artifact_contract: dict[str, Any],
    require_baseline: bool,
    audit: GateAudit,
) -> bool:
    """Cross-check the full-draft depth summary against the live contract."""

    conservation = payload.get("conservation")
    summary = (
        conservation.get("candidate_only_full_draft_contract")
        if isinstance(conservation, dict)
        else None
    )
    task_mode = str(artifact_contract.get("task_mode", "")).strip().lower()
    required = not require_baseline and task_mode == "full_draft"
    if not isinstance(summary, dict):
        audit.add(
            "audit_incomplete",
            "candidate_only_contract_summary_invalid",
            "Conservation report requires a typed candidate-only contract summary.",
            path=str(path),
        )
        return False
    if not required:
        valid = summary.get("required") is False and str(
            summary.get("status", "")
        ).strip().lower() == "not_applicable"
        if not valid:
            audit.add(
                "audit_incomplete",
                "candidate_only_contract_summary_mismatch",
                "Non-candidate-only audits must mark the full-draft contract summary not_applicable.",
                path=str(path),
            )
        return valid

    valid = True
    if summary.get("required") is not True or str(
        summary.get("status", "")
    ).strip().lower() != "pass":
        valid = False

    word_range = numeric_range(
        artifact_contract.get("target_main_source_word_range")
    )
    page_range = numeric_range(artifact_contract.get("target_main_pdf_page_range"))
    expected_target_kind = "source_words" if word_range is not None else (
        "verified_main_text_pages" if page_range is not None else None
    )
    if summary.get("global_target_kind") != expected_target_kind:
        valid = False

    section_cards = artifact_contract.get("section_cards")
    if isinstance(section_cards, (list, dict)):
        expected_card_count = len(section_cards)
    else:
        expected_card_count = 0
    if summary.get("section_card_count") != expected_card_count or expected_card_count < 1:
        valid = False

    obligations = artifact_contract.get("content_obligations")
    expected_obligation_count = artifact_collection_count(obligations)
    if (
        summary.get("content_obligation_count") != expected_obligation_count
        or expected_obligation_count < 1
    ):
        valid = False

    section_checks = summary.get("section_budget_checks")
    reference_checks = summary.get("must_remain_reference_checks")
    if not isinstance(section_checks, list) or any(
        not isinstance(item, dict)
        or str(item.get("status", "")).strip().lower() != "pass"
        for item in section_checks
    ):
        valid = False
    if not isinstance(reference_checks, list) or any(
        not isinstance(item, dict)
        or str(item.get("status", "")).strip().lower()
        != "verified_reference"
        for item in reference_checks
    ):
        valid = False
    if (
        summary.get("requires_main_text_sufficiency_role") is not True
        or summary.get("minimum_depth_questions_semantically_verified") is not False
    ):
        valid = False

    metrics = payload.get("metrics")
    candidate_main = metrics.get("candidate_main") if isinstance(metrics, dict) else None
    measurement = payload.get("measurement")
    metric_name = (
        measurement.get("word_metric_for_contract")
        if isinstance(measurement, dict)
        else None
    )
    observed_words = (
        candidate_main.get(metric_name)
        if isinstance(candidate_main, dict) and isinstance(metric_name, str)
        else None
    )
    if word_range is not None:
        if (
            isinstance(observed_words, bool)
            or not isinstance(observed_words, (int, float))
            or not word_range[0] <= float(observed_words) <= word_range[1]
        ):
            valid = False
    floor = artifact_contract.get("hard_main_text_floor")
    floor_words: Any = None
    if isinstance(floor, dict):
        floor_words = floor.get("source_words")
    elif isinstance(floor, (int, float)) and not isinstance(floor, bool):
        floor_words = floor
    if floor_words is not None:
        if (
            isinstance(floor_words, bool)
            or not isinstance(floor_words, (int, float))
            or float(floor_words) < 0
            or isinstance(observed_words, bool)
            or not isinstance(observed_words, (int, float))
            or float(observed_words) < float(floor_words)
        ):
            valid = False

    if not valid:
        audit.add(
            "audit_incomplete",
            "candidate_only_contract_summary_mismatch",
            "Passing candidate-only conservation summary does not match the live full-draft artifact contract and its reported metrics.",
            path=str(path),
        )
    return valid


def validate_two_pass_restructure_summary(
    payload: dict[str, Any],
    path: Path,
    artifact_contract: dict[str, Any],
    artifact_contract_path: Path | None,
    expected_content_hash: str,
    audit: GateAudit,
) -> bool:
    """Cross-check the typed two-pass summary; do not accept a parallel schema."""

    conservation = payload.get("conservation")
    summary = (
        conservation.get("two_pass_restructure")
        if isinstance(conservation, dict)
        else None
    )
    task_mode = str(artifact_contract.get("task_mode", "")).strip().lower()
    rewrite_mode = str(artifact_contract.get("rewrite_mode", "")).strip().lower()
    mature = artifact_contract.get("mature_baseline") is True
    required = bool(
        mature
        and rewrite_mode != "full_redraft"
        and (
            task_mode == "restructure"
            or (task_mode == "major_revision" and rewrite_mode == "reorder_existing_blocks")
        )
    )
    if not isinstance(summary, dict):
        audit.add(
            "audit_incomplete",
            "two_pass_restructure_summary_invalid",
            "Conservation report requires a typed two-pass-restructure summary.",
            path=str(path),
        )
        return False
    if not required:
        valid = summary.get("required") is False and str(
            summary.get("status", "")
        ).strip().lower() == "not_applicable"
        if not valid:
            audit.add(
                "audit_incomplete",
                "two_pass_restructure_summary_mismatch",
                "Tasks outside the two-pass gate must mark it not_applicable.",
                path=str(path),
            )
        return valid

    raw = artifact_contract.get("two_pass_restructure")
    architecture = raw.get("architecture_pass") if isinstance(raw, dict) else None
    compression = raw.get("compression_pass") if isinstance(raw, dict) else None
    if not isinstance(architecture, dict) or not isinstance(compression, dict):
        audit.add(
            "audit_incomplete",
            "two_pass_restructure_contract_invalid",
            "Live artifact contract lacks the required architecture and compression passes.",
            path=str(artifact_contract_path) if artifact_contract_path else None,
        )
        return False

    valid = summary.get("required") is True and str(
        summary.get("status", "")
    ).strip().lower() == "pass"
    architecture_mode = str(architecture.get("mode", "")).strip().lower()
    compression_mode = str(compression.get("mode", "")).strip().lower()
    architecture_expanded_hash = normalized_sha(architecture.get("expanded_sha256"))
    if (
        architecture_mode != "reorder_existing_blocks"
        or summary.get("architecture_mode") != architecture_mode
        or normalized_sha(summary.get("architecture_expanded_sha256"))
        != architecture_expanded_hash
        or str(summary.get("architecture_ledger_status", "")).strip().lower()
        != "pass"
    ):
        valid = False

    base = artifact_contract_path.parent if artifact_contract_path else Path.cwd()
    architecture_path = resolve_bound_path(architecture.get("artifact_path"), base)
    summary_architecture_path = resolve_bound_path(
        summary.get("architecture_artifact"), path.parent
    )
    architecture_file_hash = normalized_sha(architecture.get("artifact_sha256"))
    if (
        architecture_path is None
        or not architecture_path.is_file()
        or not architecture_file_hash
        or sha256_file(architecture_path) != architecture_file_hash
        or summary_architecture_path != architecture_path
    ):
        valid = False

    architecture_ledger = architecture.get("content_conservation_ledger")
    if (
        not isinstance(architecture_ledger, list)
        or not architecture_ledger
        or normalized_sha(summary.get("architecture_ledger_sha256"))
        != canonical_hash(architecture_ledger)
    ):
        valid = False

    if (
        compression_mode not in {"none", "limited_compression"}
        or summary.get("compression_mode") != compression_mode
        or normalized_sha(compression.get("source_expanded_sha256"))
        != architecture_expanded_hash
        or normalized_sha(compression.get("candidate_expanded_sha256"))
        != expected_content_hash
        or normalized_sha(summary.get("candidate_expanded_sha256"))
        != expected_content_hash
        or not nonempty(architecture.get("completed_by"))
        or not nonempty(architecture.get("completed_at"))
        or not nonempty(compression.get("completed_by"))
        or not nonempty(compression.get("completed_at"))
    ):
        valid = False

    if compression_mode == "none":
        if (
            architecture_expanded_hash != expected_content_hash
            or str(summary.get("compression_ledger_status", "")).strip().lower()
            != "not_applicable"
            or summary.get("compression_ledger_sha256") not in (None, "")
        ):
            valid = False
    else:
        approved_scope = compression.get("approved_scope", compression.get("scope"))
        compression_ledger = compression.get("content_conservation_ledger")
        if (
            not nonempty(approved_scope)
            or canonical_hash(summary.get("compression_approved_scope"))
            != canonical_hash(approved_scope)
            or not isinstance(compression_ledger, list)
            or not compression_ledger
            or normalized_sha(summary.get("compression_ledger_sha256"))
            != canonical_hash(compression_ledger)
            or str(summary.get("compression_ledger_status", "")).strip().lower()
            != "pass"
        ):
            valid = False

    if not valid:
        audit.add(
            "audit_incomplete",
            "two_pass_restructure_summary_mismatch",
            "Passing conservation report does not prove the live baseline-to-architecture-to-candidate sequence.",
            path=str(path),
        )
    return valid


def validate_conservation_block_binding(
    payload: dict[str, Any],
    path: Path,
    require_baseline: bool,
    audit: GateAudit,
) -> dict[str, dict[str, Any]] | None:
    """Validate the report's complete baseline block universe and dispositions."""

    conservation = payload.get("conservation")
    if not isinstance(conservation, dict):
        return None
    ledger_required = conservation.get("ledger_required")
    expected_raw = conservation.get("expected_baseline_block_ids")
    baseline_inventory = conservation.get("baseline_block_inventory")
    candidate_inventory = conservation.get("candidate_block_inventory")
    ledger_validation = conservation.get("ledger_validation")
    valid = True
    if not isinstance(ledger_required, bool):
        valid = False
    if not all(
        isinstance(value, list)
        for value in (
            expected_raw,
            baseline_inventory,
            candidate_inventory,
            ledger_validation,
        )
    ):
        audit.add(
            "audit_incomplete",
            "conservation_block_schema_invalid",
            "Conservation block inventories, expected IDs, and ledger_validation must be arrays.",
            path=str(path),
        )
        return None

    def inventory_by_id(
        records: list[Any], label: str
    ) -> dict[str, dict[str, Any]]:
        nonlocal valid
        output: dict[str, dict[str, Any]] = {}
        required_fields = {
            "block_id",
            "content_sha256",
            "section_id",
            "section",
            "normalized_section",
            "region",
            "normalized_words",
        }
        for record in records:
            if not isinstance(record, dict):
                valid = False
                continue
            block_id = record.get("block_id")
            if (
                not isinstance(block_id, str)
                or not block_id
                or block_id in output
                or not required_fields.issubset(record)
                or not normalized_sha(record.get("content_sha256"))
                or record.get("region") not in {"main_text", "appendix"}
                or isinstance(record.get("normalized_words"), bool)
                or not isinstance(record.get("normalized_words"), int)
                or record.get("normalized_words") < 0
            ):
                valid = False
                continue
            output[block_id] = record
        if len(output) != len(records):
            audit.add(
                "audit_incomplete",
                "conservation_block_inventory_invalid",
                "Conservation block inventory contains malformed or duplicate records.",
                path=str(path),
                inventory=label,
            )
        return output

    baseline_by_id = inventory_by_id(baseline_inventory, "baseline")
    candidate_by_id = inventory_by_id(candidate_inventory, "candidate")
    expected_ids = [value for value in expected_raw if isinstance(value, str) and value]
    if len(expected_ids) != len(expected_raw) or len(set(expected_ids)) != len(expected_ids):
        valid = False
        audit.add(
            "audit_incomplete",
            "conservation_expected_block_ids_invalid",
            "expected_baseline_block_ids must contain unique nonempty strings.",
            path=str(path),
        )

    if not require_baseline:
        if ledger_required is not False or expected_ids or baseline_inventory or ledger_validation:
            audit.add(
                "audit_incomplete",
                "candidate_only_conservation_ledger_invalid",
                "Candidate-only audit must explicitly disable the baseline ledger and leave baseline inventory/validation empty.",
                path=str(path),
            )
            valid = False
        return {} if valid else None

    if ledger_required is not True:
        audit.add(
            "audit_incomplete",
            "conservation_ledger_requirement_mismatch",
            "A baseline comparison must declare ledger_required=true.",
            path=str(path),
        )
        valid = False
    if not baseline_by_id:
        audit.add(
            "audit_incomplete",
            "conservation_baseline_inventory_empty",
            "Baseline comparison requires a nonempty substantive block inventory.",
            path=str(path),
        )
        valid = False
    if set(expected_ids) != set(baseline_by_id):
        audit.add(
            "audit_incomplete",
            "conservation_expected_inventory_mismatch",
            "Expected baseline block IDs must exactly equal the baseline inventory.",
            path=str(path),
            missing_ids=sorted(set(baseline_by_id) - set(expected_ids)),
            unknown_ids=sorted(set(expected_ids) - set(baseline_by_id)),
        )
        valid = False

    validation_by_source: dict[str, dict[str, Any]] = {}
    for record in ledger_validation:
        if not isinstance(record, dict):
            valid = False
            continue
        source_id = record.get("source_block_id")
        disposition = normalize_role(record.get("disposition"))
        destination_id = record.get("destination_block_id")
        if (
            not isinstance(source_id, str)
            or not source_id
            or source_id in validation_by_source
            or str(record.get("status", "")).strip().lower() != "pass"
            or as_list(record.get("reasons"))
            or not disposition
        ):
            valid = False
            continue
        if disposition not in {"deleted", "delete", "removed", "omitted"}:
            if not isinstance(destination_id, str) or destination_id not in candidate_by_id:
                valid = False
                continue
        elif destination_id not in (None, ""):
            valid = False
            continue
        validation_by_source[source_id] = {
            "source_block_id": source_id,
            "destination_block_id": destination_id or None,
            "disposition": disposition,
        }
    if len(validation_by_source) != len(ledger_validation):
        audit.add(
            "audit_incomplete",
            "conservation_ledger_validation_invalid",
            "Each upstream ledger-validation record must be unique, passing, reason-free, and bound to a verifiable destination.",
            path=str(path),
        )
        valid = False
    if set(validation_by_source) != set(expected_ids):
        audit.add(
            "audit_incomplete",
            "conservation_ledger_validation_coverage_mismatch",
            "Upstream ledger_validation must cover every expected baseline block exactly once and no others.",
            path=str(path),
            missing_ids=sorted(set(expected_ids) - set(validation_by_source)),
            unknown_ids=sorted(set(validation_by_source) - set(expected_ids)),
        )
        valid = False
    return validation_by_source if valid else None


def validate_gate_source_bindings(
    gate_inputs: dict[str, Any],
    report_path: Path,
    label: str,
    expected_bindings: dict[str, str] | None,
    audit: GateAudit,
) -> bool:
    records = gate_inputs.get(f"{label}_source_files")
    if not isinstance(records, list) or not records:
        audit.add(
            "audit_incomplete",
            "conservation_source_files_missing",
            "Typed conservation report must record every expanded TeX source with SHA-256.",
            path=str(report_path),
            input_kind=label,
        )
        return False
    actual_bindings: dict[str, str] = {}
    valid = True
    for record in records:
        if not isinstance(record, dict):
            valid = False
            continue
        source_path = resolve_bound_path(record.get("path"), report_path.parent)
        expected_hash = normalized_sha(record.get("sha256"))
        if source_path is None or not expected_hash or not source_path.is_file():
            valid = False
            continue
        actual_hash = sha256_file(source_path)
        actual_bindings[str(source_path)] = expected_hash
        if actual_hash != expected_hash:
            audit.add(
                "audit_incomplete",
                "conservation_source_file_stale",
                "A TeX source used by the conservation report changed.",
                path=str(source_path),
                input_kind=label,
                expected_sha256=expected_hash,
                actual_sha256=actual_hash,
            )
            valid = False
    if not valid:
        audit.add(
            "audit_incomplete",
            "conservation_source_files_invalid",
            "Typed conservation report contains invalid source-file bindings.",
            path=str(report_path),
            input_kind=label,
        )
    if expected_bindings is not None and actual_bindings != expected_bindings:
        audit.add(
            "audit_incomplete",
            "conservation_candidate_source_set_mismatch",
            "Conservation candidate source set differs from the QA manifest source set.",
            path=str(report_path),
            missing_sources=sorted(set(expected_bindings) - set(actual_bindings)),
            unexpected_sources=sorted(set(actual_bindings) - set(expected_bindings)),
        )
        valid = False
    return valid


def validate_conservation_canonical_replay(
    payload: dict[str, Any], report_path: Path, audit: GateAudit
) -> dict[str, Any] | None:
    """Re-run the co-shipped conservation auditor with the recorded decisions."""

    if conservation_auditor is None:
        audit.add(
            "audit_incomplete",
            "conservation_replay_unavailable",
            "The co-shipped conservation auditor is unavailable for deterministic replay.",
            path=str(report_path),
        )
        return None
    argument_keys = {
        "appendix_marker",
        "word_metric",
        "max_main_reduction",
        "min_main_source_words",
        "baseline_main_pdf_pages",
        "candidate_main_pdf_pages",
        "min_main_pdf_pages",
    }
    recorded = payload.get("audit_arguments")
    numeric_keys = argument_keys - {"appendix_marker", "word_metric"}
    arguments_valid = (
        isinstance(recorded, dict)
        and set(recorded) == argument_keys
        and isinstance(recorded.get("appendix_marker"), str)
        and bool(recorded.get("appendix_marker"))
        and recorded.get("word_metric")
        in {None, "raw_source_words", "normalized_words"}
        and all(
            recorded.get(key) is None
            or (
                not isinstance(recorded.get(key), bool)
                and isinstance(recorded.get(key), (int, float))
            )
            for key in numeric_keys
        )
    )
    if not arguments_valid:
        audit.add(
            "audit_incomplete",
            "conservation_audit_arguments_invalid",
            "Conservation report must record exactly every decision needed for deterministic replay.",
            path=str(report_path),
        )
        return None
    inputs = payload.get("inputs")
    if not isinstance(inputs, dict):
        audit.add(
            "audit_incomplete",
            "conservation_replay_input_invalid",
            "Conservation replay requires the report's typed inputs object.",
            path=str(report_path),
        )
        return None

    def resolved_optional(raw: Any) -> str | None:
        if raw in (None, ""):
            return None
        resolved = resolve_bound_path(raw, report_path.parent)
        return str(resolved) if resolved is not None else None

    candidate = resolved_optional(inputs.get("candidate"))
    if candidate is None:
        audit.add(
            "audit_incomplete",
            "conservation_replay_input_invalid",
            "Conservation replay requires a candidate path.",
            path=str(report_path),
        )
        return None
    namespace = argparse.Namespace(
        baseline=resolved_optional(inputs.get("baseline")),
        candidate=candidate,
        project_root=resolved_optional(inputs.get("project_root")),
        contract=resolved_optional(inputs.get("contract")),
        appendix_marker=recorded["appendix_marker"],
        word_metric=recorded["word_metric"],
        max_main_reduction=recorded["max_main_reduction"],
        min_main_source_words=recorded["min_main_source_words"],
        baseline_main_pdf_pages=recorded["baseline_main_pdf_pages"],
        candidate_main_pdf_pages=recorded["candidate_main_pdf_pages"],
        min_main_pdf_pages=recorded["min_main_pdf_pages"],
        report=str(report_path),
    )
    try:
        try:
            replayed = conservation_auditor.audit(namespace)
        except conservation_auditor.MetricUnavailable as exc:
            replayed = conservation_auditor.unavailable_report(namespace, exc)
    except Exception as exc:
        audit.add(
            "audit_incomplete",
            "conservation_replay_failed",
            "The co-shipped conservation auditor could not replay the recorded gate.",
            path=str(report_path),
            error=str(exc),
        )
        return None
    if canonical_hash(replayed) != canonical_hash(payload):
        audit.add(
            "audit_incomplete",
            "conservation_replay_mismatch",
            "Conservation report differs from a same-version replay over the live bound inputs.",
            path=str(report_path),
            recorded_sha256=canonical_hash(payload),
            replayed_sha256=canonical_hash(replayed),
        )
        return None
    return replayed


def validate_upstream_gates(
    values: Sequence[str],
    candidate_hash: str,
    expected_candidate_path: Path | None,
    expected_content_hash: str,
    expected_candidate_sources: dict[str, str],
    expected_artifact_contract_hash: str,
    expected_artifact_contract_path: Path | None,
    artifact_contract: dict[str, Any],
    require_gate: bool,
    require_baseline: bool,
    audit: GateAudit,
) -> tuple[
    list[Path],
    bool,
    dict[str, dict[str, Any]],
    str,
    str,
    dict[str, Any],
]:
    paths: list[Path] = []
    passing_conservation_gate = False
    passing_block_binding: dict[str, dict[str, Any]] = {}
    passing_conservation_gate_hash = ""
    fresh_conservation_gate_status = ""
    fresh_conservation_gate_hash = ""
    fresh_conservation_replay: dict[str, Any] = {}
    (
        expected_baseline_path,
        expected_baseline_hash,
        expected_baseline_accepted_by,
        expected_baseline_acceptance_status,
    ) = artifact_baseline_binding(
        artifact_contract, expected_artifact_contract_path
    )
    if require_baseline and expected_baseline_path is None:
        audit.add(
            "audit_incomplete",
            "artifact_baseline_binding_missing",
            "Mature revision artifact contract must identify the accepted baseline path.",
        )
    elif require_baseline and expected_baseline_path is not None:
        if not expected_baseline_hash:
            audit.add(
                "audit_incomplete",
                "artifact_baseline_hash_missing",
                "Accepted baseline must carry an exact frozen SHA-256 in the artifact contract.",
                path=str(expected_baseline_path),
            )
        if not expected_baseline_accepted_by:
            audit.add(
                "audit_incomplete",
                "artifact_baseline_acceptance_missing",
                "Accepted baseline must record who accepted it in the artifact contract.",
                path=str(expected_baseline_path),
            )
        if expected_baseline_acceptance_status not in {
            "accepted",
            "author_accepted",
            "confirmed",
            "frozen_current",
            "frozen-ready",
            "frozen_ready",
        }:
            audit.add(
                "audit_incomplete",
                "artifact_baseline_acceptance_status_invalid",
                "Accepted baseline must carry an explicit accepted/frozen status in the artifact contract.",
                path=str(expected_baseline_path),
                acceptance_status=expected_baseline_acceptance_status or None,
            )
        if not expected_baseline_path.is_file():
            audit.add(
                "audit_incomplete",
                "artifact_baseline_missing",
                "Accepted baseline recorded by the artifact contract is unavailable.",
                path=str(expected_baseline_path),
            )
        else:
            live_baseline_hash = sha256_file(expected_baseline_path)
            if expected_baseline_hash and expected_baseline_hash != live_baseline_hash:
                audit.add(
                    "audit_incomplete",
                    "artifact_baseline_stale",
                    "Accepted baseline differs from the hash frozen in the artifact contract.",
                    path=str(expected_baseline_path),
                    expected_sha256=expected_baseline_hash,
                    actual_sha256=live_baseline_hash,
                )
    for raw in values:
        path = Path(raw).expanduser().resolve()
        if not path.is_file():
            audit.add(
                "audit_incomplete",
                "upstream_gate_missing",
                "Upstream gate report does not exist.",
                path=str(path),
            )
            continue
        paths.append(path)
        payload = load_json_object(path, audit, "upstream gate")
        if payload is None or not require_schema(payload, audit, "Upstream gate", path):
            continue
        status = str(payload.get("status", "")).strip().lower()
        if status not in EXIT_CODES:
            audit.add(
                "audit_incomplete",
                "upstream_gate_status_invalid",
                "Upstream gate has an unknown status.",
                path=str(path),
                upstream_status=status or None,
            )
            continue
        exit_code = payload.get("exit_code")
        if isinstance(exit_code, bool) or exit_code != EXIT_CODES[status]:
            audit.add(
                "audit_incomplete",
                "upstream_exit_code_mismatch",
                "Upstream gate exit_code does not match its status.",
                path=str(path),
                upstream_status=status,
                exit_code=exit_code,
            )
        gate_inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
        conservation_marked = any(
            key in payload for key in ("schema_id", "gate_type", "conservation")
        )
        is_conservation = (
            payload.get("schema_id") == CONSERVATION_SCHEMA_ID
            and payload.get("gate_type") == CONSERVATION_GATE_TYPE
        )
        gate_fresh = True
        if conservation_marked and not is_conservation:
            audit.add(
                "audit_incomplete",
                "conservation_gate_identity_invalid",
                "Conservation report requires the exact schema_id and gate_type.",
                path=str(path),
                schema_id=payload.get("schema_id"),
                gate_type=payload.get("gate_type"),
            )
            gate_fresh = False
        if is_conservation and not validate_conservation_structure(payload, path, audit):
            gate_fresh = False
        canonical_replay: dict[str, Any] | None = None
        if is_conservation:
            canonical_replay = validate_conservation_canonical_replay(
                payload, path, audit
            )
            if canonical_replay is None:
                gate_fresh = False
        block_binding: dict[str, dict[str, Any]] | None = None
        if is_conservation:
            if status == "metric_unavailable":
                # Canonical replay plus live source/contract bindings prove the
                # unavailable result; measurements and ledger projections are
                # intentionally absent and cannot be required as if measured.
                block_binding = {}
            else:
                if not validate_candidate_only_contract_summary(
                    payload,
                    path,
                    artifact_contract,
                    require_baseline,
                    audit,
                ):
                    gate_fresh = False
                if not validate_two_pass_restructure_summary(
                    payload,
                    path,
                    artifact_contract,
                    expected_artifact_contract_path,
                    expected_content_hash,
                    audit,
                ):
                    gate_fresh = False
                block_binding = validate_conservation_block_binding(
                    payload, path, require_baseline, audit
                )
                if block_binding is None:
                    gate_fresh = False
        if is_conservation:
            candidate_expanded_hash = normalized_sha(
                gate_inputs.get("candidate_expanded_sha256")
            )
            if (
                not candidate_expanded_hash
                or candidate_expanded_hash != expected_content_hash
            ):
                audit.add(
                    "audit_incomplete",
                    "conservation_candidate_expanded_hash_mismatch",
                    "Conservation report is not bound to the manifest's expanded manuscript content.",
                    path=str(path),
                    expected_sha256=expected_content_hash or None,
                    upstream_sha256=candidate_expanded_hash or None,
                )
                gate_fresh = False
            if not validate_gate_source_bindings(
                gate_inputs,
                path,
                "candidate",
                expected_candidate_sources,
                audit,
            ):
                gate_fresh = False
            if require_baseline and not validate_gate_source_bindings(
                gate_inputs, path, "baseline", None, audit
            ):
                gate_fresh = False
        recorded_candidate_hash = normalized_sha(
            first_present(
                payload,
                (
                    ("inputs", "candidate_sha256"),
                    ("inputs", "candidate", "sha256"),
                    ("candidate_sha256",),
                ),
            )
        )
        if is_conservation and not recorded_candidate_hash:
            audit.add(
                "audit_incomplete",
                "upstream_candidate_hash_missing",
                "Conservation gate must record candidate_sha256.",
                path=str(path),
            )
            gate_fresh = False
        elif recorded_candidate_hash and candidate_hash and recorded_candidate_hash != candidate_hash:
            audit.add(
                "audit_incomplete",
                "upstream_gate_stale",
                "Upstream gate was computed for a different candidate manuscript.",
                path=str(path),
                expected_sha256=candidate_hash,
                upstream_sha256=recorded_candidate_hash,
            )
            gate_fresh = False
        raw_candidate_path = gate_inputs.get("candidate")
        if is_conservation:
            candidate_input_path = resolve_bound_path(raw_candidate_path, path.parent)
            if candidate_input_path is None:
                audit.add(
                    "audit_incomplete",
                    "upstream_candidate_path_missing",
                    "Conservation gate must record the candidate path.",
                    path=str(path),
                )
                gate_fresh = False
            elif not candidate_input_path.is_file():
                audit.add(
                    "audit_incomplete",
                    "upstream_input_missing",
                    "Candidate used by the conservation gate is unavailable.",
                    path=str(candidate_input_path),
                    input_kind="candidate",
                )
                gate_fresh = False
            else:
                actual_candidate_hash = sha256_file(candidate_input_path)
                if actual_candidate_hash != recorded_candidate_hash:
                    audit.add(
                        "audit_incomplete",
                        "upstream_input_stale",
                        "Candidate changed after the conservation gate ran.",
                        path=str(candidate_input_path),
                        input_kind="candidate",
                        expected_sha256=recorded_candidate_hash or None,
                        actual_sha256=actual_candidate_hash,
                    )
                    gate_fresh = False
                if (
                    expected_candidate_path is not None
                    and candidate_input_path != expected_candidate_path
                ):
                    audit.add(
                        "audit_incomplete",
                        "upstream_candidate_path_mismatch",
                        "Conservation gate used a different candidate path.",
                        path=str(path),
                        expected_candidate_path=str(expected_candidate_path),
                        upstream_candidate_path=str(candidate_input_path),
                    )
                    gate_fresh = False
        raw_contract_path = gate_inputs.get("contract")
        recorded_contract_hash = normalized_sha(gate_inputs.get("contract_sha256"))
        if is_conservation and expected_artifact_contract_hash:
            if raw_contract_path in (None, ""):
                audit.add(
                    "audit_incomplete",
                    "upstream_artifact_contract_path_missing",
                    "Conservation gate must record the artifact-contract path.",
                    path=str(path),
                )
                gate_fresh = False
            if not recorded_contract_hash:
                audit.add(
                    "audit_incomplete",
                    "upstream_artifact_contract_hash_missing",
                    "Manifest declares an artifact contract, but the upstream gate does not hash it.",
                    path=str(path),
                )
                gate_fresh = False
            elif recorded_contract_hash != expected_artifact_contract_hash:
                audit.add(
                    "audit_incomplete",
                    "upstream_artifact_contract_hash_mismatch",
                    "Upstream gate used a different artifact contract from the QA manifest.",
                    path=str(path),
                    expected_sha256=expected_artifact_contract_hash,
                    upstream_sha256=recorded_contract_hash,
                )
                gate_fresh = False
        if raw_contract_path not in (None, ""):
            if not recorded_contract_hash:
                audit.add(
                    "audit_incomplete",
                    "upstream_input_hash_missing",
                    "An upstream gate must hash the artifact contract it used.",
                    path=str(path),
                    input_kind="contract",
                )
                gate_fresh = False
            else:
                contract_input_path = Path(str(raw_contract_path)).expanduser()
                if not contract_input_path.is_absolute():
                    contract_input_path = path.parent / contract_input_path
                contract_input_path = contract_input_path.resolve()
                if not contract_input_path.is_file():
                    audit.add(
                        "audit_incomplete",
                        "upstream_input_missing",
                        "An artifact contract used by the upstream gate is no longer available.",
                        path=str(contract_input_path),
                        input_kind="contract",
                    )
                    gate_fresh = False
                else:
                    actual_hash = sha256_file(contract_input_path)
                    if actual_hash != recorded_contract_hash:
                        audit.add(
                            "audit_incomplete",
                            "upstream_input_stale",
                            "The artifact contract changed after the upstream gate ran.",
                            path=str(contract_input_path),
                            input_kind="contract",
                            expected_sha256=recorded_contract_hash,
                            actual_sha256=actual_hash,
                        )
                        gate_fresh = False
                    if (
                        is_conservation
                        and expected_artifact_contract_path is not None
                        and contract_input_path != expected_artifact_contract_path
                    ):
                        audit.add(
                            "audit_incomplete",
                            "upstream_artifact_contract_path_mismatch",
                            "Conservation gate used a different artifact-contract path.",
                            path=str(path),
                            expected_contract_path=str(expected_artifact_contract_path),
                            upstream_contract_path=str(contract_input_path),
                        )
                        gate_fresh = False
        if is_conservation and require_baseline:
            raw_baseline_path = gate_inputs.get("baseline")
            recorded_baseline_hash = normalized_sha(gate_inputs.get("baseline_sha256"))
            baseline_input_path = resolve_bound_path(raw_baseline_path, path.parent)
            if baseline_input_path is None:
                audit.add(
                    "audit_incomplete",
                    "upstream_baseline_path_missing",
                    "Conservation gate must record the accepted baseline path.",
                    path=str(path),
                )
                gate_fresh = False
            if not recorded_baseline_hash:
                audit.add(
                    "audit_incomplete",
                    "upstream_baseline_hash_missing",
                    "Conservation gate must record baseline_sha256.",
                    path=str(path),
                )
                gate_fresh = False
            if baseline_input_path is not None:
                if not baseline_input_path.is_file():
                    audit.add(
                        "audit_incomplete",
                        "upstream_input_missing",
                        "Baseline used by the conservation gate is unavailable.",
                        path=str(baseline_input_path),
                        input_kind="baseline",
                    )
                    gate_fresh = False
                else:
                    actual_baseline_hash = sha256_file(baseline_input_path)
                    if actual_baseline_hash != recorded_baseline_hash:
                        audit.add(
                            "audit_incomplete",
                            "upstream_input_stale",
                            "Baseline changed after the conservation gate ran.",
                            path=str(baseline_input_path),
                            input_kind="baseline",
                            expected_sha256=recorded_baseline_hash or None,
                            actual_sha256=actual_baseline_hash,
                        )
                        gate_fresh = False
                    if expected_baseline_hash and actual_baseline_hash != expected_baseline_hash:
                        audit.add(
                            "audit_incomplete",
                            "upstream_baseline_hash_mismatch",
                            "Conservation gate used a baseline different from the artifact contract.",
                            path=str(path),
                            expected_sha256=expected_baseline_hash,
                            upstream_sha256=actual_baseline_hash,
                        )
                        gate_fresh = False
                if expected_baseline_path is not None and baseline_input_path != expected_baseline_path:
                    audit.add(
                        "audit_incomplete",
                        "upstream_baseline_path_mismatch",
                        "Conservation gate used a different baseline path from the artifact contract.",
                        path=str(path),
                        expected_baseline_path=str(expected_baseline_path),
                        upstream_baseline_path=str(baseline_input_path),
                    )
                    gate_fresh = False
        if is_conservation and gate_fresh:
            if fresh_conservation_gate_status:
                audit.add(
                    "audit_incomplete",
                    "conservation_gate_duplicate",
                    "Exactly one fresh conservation gate may define the deterministic delivery state.",
                    path=str(path),
                )
                gate_fresh = False
            else:
                fresh_conservation_gate_status = status
                fresh_conservation_gate_hash = sha256_file(path)
                fresh_conservation_replay = canonical_replay or {}
                if status == "pass":
                    passing_block_binding = block_binding or {}
        if is_conservation and status == "pass" and gate_fresh:
            passing_conservation_gate = True
            passing_conservation_gate_hash = fresh_conservation_gate_hash
        if status != "pass" and (not is_conservation or gate_fresh):
            audit.add(
                status,
                f"upstream_gate_{status}",
                "An upstream deterministic gate blocks delivery.",
                path=str(path),
                upstream_status=status,
            )
    if require_gate and not fresh_conservation_gate_status:
        audit.add(
            "audit_incomplete",
            "artifact_contract_gate_missing",
            "Artifact contract requires a deterministic audit, but no fresh typed gate is bound to its path and SHA-256.",
            expected_sha256=expected_artifact_contract_hash,
        )
    return (
        paths,
        passing_conservation_gate,
        passing_block_binding,
        fresh_conservation_gate_hash or passing_conservation_gate_hash,
        fresh_conservation_gate_status,
        fresh_conservation_replay,
    )


def artifact_requires_conservation(artifact_contract: dict[str, Any]) -> bool:
    task_mode = normalize_artifact_task_mode(artifact_contract.get("task_mode"))
    baseline_declared = any(
        nonempty(artifact_contract.get(key))
        for key in (
            "baseline_source",
            "baseline_path",
            "baseline_manuscript",
            "baseline_artifact",
        )
    )
    return (
        artifact_contract.get("mature_baseline") is True
        or (bool(artifact_contract) and task_mode != "full_draft")
        or baseline_declared
    )


def artifact_requires_deterministic_gate(artifact_contract: dict[str, Any]) -> bool:
    budget_fields = (
        "target_main_source_word_range",
        "target_main_pdf_page_range",
        "hard_main_text_floor",
        "must_remain_main",
    )
    return artifact_requires_conservation(artifact_contract) or any(
        nonempty(artifact_contract.get(field_name)) for field_name in budget_fields
    )


def qa_task_stage(qa_contract: dict[str, Any]) -> str:
    classification = qa_contract.get("task_classification")
    if not isinstance(classification, dict):
        return ""
    return str(classification.get("task_stage", "")).strip().lower()


def normalize_artifact_task_mode(value: Any) -> str:
    """Return the one canonical artifact task-mode vocabulary."""

    normalized = str(value or "").strip().lower()
    return ARTIFACT_TASK_MODE_ALIASES.get(normalized, normalized)


def task_stage_requires_artifact_contract(qa_contract: dict[str, Any]) -> bool:
    return qa_task_stage(qa_contract) in ARTIFACT_CONTRACT_REQUIRED_STAGES


def validate_task_stage_artifact_mode(
    qa_contract: dict[str, Any],
    artifact_contract: dict[str, Any],
    audit: GateAudit,
) -> None:
    if not artifact_contract:
        return
    task_stage = qa_task_stage(qa_contract)
    artifact_mode = normalize_artifact_task_mode(artifact_contract.get("task_mode"))
    fixed_mapping = {
        "full_draft": "full_draft",
        "proposal_draft": "full_draft",
        "document_translation": "document_translation",
        "document_compression": "shorten",
        "major_revision": "major_revision",
        "major_restructure": "restructure",
        "local_edit": "local_edit",
        "local_polish": "local_edit",
    }
    if task_stage == "final_audit":
        classification = qa_contract.get("task_classification")
        classification = classification if isinstance(classification, dict) else {}
        underlying = normalize_artifact_task_mode(
            classification.get("artifact_task_mode")
        )
        allowed_modes = {
            "full_draft",
            "major_revision",
            "restructure",
            "shorten",
            "local_edit",
            "document_translation",
        }
        if underlying not in allowed_modes or underlying != artifact_mode:
            audit.add(
                "audit_incomplete",
                "final_audit_artifact_mode_unbound",
                "final_audit requires task_classification.artifact_task_mode to exactly bind the live artifact_contract.task_mode.",
                classification_artifact_task_mode=underlying or None,
                artifact_task_mode=artifact_mode or None,
            )
        return
    expected_mode = fixed_mapping.get(task_stage)
    if expected_mode is not None and artifact_mode != expected_mode:
        audit.add(
            "audit_incomplete",
            "task_stage_artifact_mode_mismatch",
            "Semantic QA task_stage and artifact_contract.task_mode must follow the deterministic mode mapping.",
            task_stage=task_stage,
            expected_artifact_mode=expected_mode,
            artifact_task_mode=artifact_mode or None,
        )


def validate_artifact_rewrite_approval(
    artifact_contract: dict[str, Any], audit: GateAudit
) -> None:
    if (
        artifact_contract.get("mature_baseline") is True
        and str(artifact_contract.get("task_mode", "")).strip().lower()
        == "full_draft"
    ):
        audit.add(
            "fail",
            "artifact_contract_mode_conflict",
            "mature_baseline=true conflicts with task_mode=full_draft.",
        )
    if str(artifact_contract.get("rewrite_mode", "")).strip().lower() != "full_redraft":
        return
    record = artifact_contract.get("approval_record")
    if not isinstance(record, dict):
        record = {}
    scope = record.get("approved_scope", [])
    if isinstance(scope, str):
        scope = [scope]
    scopes = {
        str(value).strip().lower()
        for value in scope
        if str(value).strip()
    } if isinstance(scope, list) else set()
    authority = str(
        record.get("approval_authority", record.get("authority", ""))
    ).strip().lower()
    valid_authority = authority in {"author", "recorded_human_delegate"}
    if not (
        nonempty(record.get("approved_by"))
        and valid_iso8601_timestamp(record.get("approved_at"))
        and nonempty(record.get("approval_source"))
        and valid_authority
        and {"all", "full_redraft"} & scopes
    ):
        audit.add(
            "approval_required",
            "full_redraft_approval_required",
            "full_redraft requires recoverable human approval with approval_authority=author or recorded_human_delegate, approved_by, approved_at, approval_source, and a full_redraft scope.",
            approval_authority=authority or None,
        )


def contract_views(
    raw: dict[str, Any], audit: GateAudit | None = None, path: Path | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    state = raw.get("paper_state", raw)
    if not isinstance(state, dict):
        state = raw
    top_author = raw.get("author_intent_contract")
    nested_author = state.get("author_intent_contract") if state is not raw else None
    if (
        isinstance(top_author, dict)
        and isinstance(nested_author, dict)
        and canonical_hash(top_author) != canonical_hash(nested_author)
        and audit is not None
    ):
        audit.add(
            "audit_incomplete",
            "contract_wrapper_conflict",
            "Top-level and paper_state author_intent_contract objects disagree.",
            path=str(path) if path is not None else None,
            contract_name="author_intent_contract",
        )
    author = nested_author if isinstance(nested_author, dict) else top_author
    if not isinstance(author, dict):
        author = state
    if not isinstance(author, dict):
        author = {}
    return state, author


def validate_authority_source_adapter(
    raw: dict[str, Any], adapter_path: Path, audit: GateAudit
) -> dict[str, Any]:
    state = raw.get("paper_state")
    top = raw.get("authority_source")
    nested_source = state.get("authority_source") if isinstance(state, dict) else None
    _, author_view = contract_views(raw)
    author_source = author_view.get("authority_source")
    if (
        isinstance(top, dict)
        and isinstance(nested_source, dict)
        and canonical_hash(top) != canonical_hash(nested_source)
    ):
        audit.add(
            "audit_incomplete",
            "authority_source_wrapper_conflict",
            "Top-level and paper_state authority_source records disagree.",
            path=str(adapter_path),
        )
    wrapper_record = nested_source if isinstance(nested_source, dict) else top
    if (
        isinstance(wrapper_record, dict)
        and isinstance(author_source, dict)
        and canonical_hash(wrapper_record) != canonical_hash(author_source)
    ):
        audit.add(
            "audit_incomplete",
            "authority_source_wrapper_conflict",
            "Wrapper and author-intent QA view authority_source records disagree.",
            path=str(adapter_path),
        )
    record = author_source if isinstance(author_source, dict) else wrapper_record
    if record is None:
        return {}
    if not isinstance(record, dict):
        audit.add(
            "audit_incomplete",
            "authority_source_invalid",
            "authority_source adapter record must be an object.",
            path=str(adapter_path),
        )
        return {}
    raw_path = record.get("path")
    expected_hash = normalized_sha(record.get("sha256"))
    source_format = str(record.get("format", "")).strip().lower()
    allowed_formats = {
        "md": {".md", ".markdown"},
        "markdown": {".md", ".markdown"},
        "yaml": {".yaml", ".yml"},
        "yml": {".yaml", ".yml"},
        "txt": {".txt", ".text"},
        "text": {".txt", ".text"},
    }
    if source_format not in allowed_formats:
        audit.add(
            "audit_incomplete",
            "authority_source_format_invalid",
            "authority_source.format must identify Markdown, YAML, or plain text.",
            path=str(adapter_path),
            source_format=source_format or None,
        )
    if str(author_view.get("artifact_role", "")).strip().lower() != "qa_view":
        audit.add(
            "audit_incomplete",
            "authority_adapter_role_invalid",
            "A non-JSON authority source requires artifact_role=qa_view.",
            path=str(adapter_path),
        )
    source_path = resolve_bound_path(raw_path, adapter_path.parent)
    if source_path is None or not expected_hash:
        audit.add(
            "audit_incomplete",
            "authority_source_binding_invalid",
            "authority_source requires path, sha256, and format.",
            path=str(adapter_path),
        )
        return {}
    if (
        source_format in allowed_formats
        and source_path.suffix.lower() not in allowed_formats[source_format]
    ):
        audit.add(
            "audit_incomplete",
            "authority_source_format_suffix_mismatch",
            "authority_source.format must agree with the bound file suffix.",
            path=str(source_path),
            source_format=source_format,
            source_suffix=source_path.suffix.lower() or None,
        )
    if source_path == adapter_path.resolve():
        audit.add(
            "audit_incomplete",
            "authority_source_self_reference",
            "authority_source must differ from its JSON QA view.",
            path=str(source_path),
        )
    if not source_path.is_file():
        audit.add(
            "audit_incomplete",
            "authority_source_missing",
            "The frozen Markdown/YAML/plain-text authority source is unavailable.",
            path=str(source_path),
        )
        return {}
    actual_hash = sha256_file(source_path)
    if actual_hash != expected_hash:
        audit.add(
            "audit_incomplete",
            "authority_source_stale",
            "The frozen Markdown/YAML authority source changed after the JSON QA view was prepared.",
            path=str(source_path),
            expected_sha256=expected_hash,
            actual_sha256=actual_hash,
        )
    author = author_view
    confirmation = author.get("adapter_confirmation")
    required_confirmation_fields = (
        "status",
        "confirmed_by",
        "confirmed_at",
        "confirmed_scope",
        "confirmation_source",
        "authority_source_sha256",
        "qa_view_projection_sha256",
        "intent_revision_id",
    )
    if not isinstance(confirmation, dict):
        missing = list(required_confirmation_fields)
        confirmation = {}
    else:
        missing = [
            field_name
            for field_name in required_confirmation_fields
            if not nonempty(confirmation.get(field_name))
        ]
    if missing:
        audit.add(
            "audit_incomplete",
            "adapter_confirmation_incomplete",
            "Authority adapter requires a recoverable author-confirmed projection record.",
            path=str(adapter_path),
            missing_fields=missing,
        )
    if nonempty(confirmation.get("confirmed_at")) and not valid_iso8601_timestamp(
        confirmation.get("confirmed_at")
    ):
        audit.add(
            "audit_incomplete",
            "adapter_confirmation_timestamp_invalid",
            "adapter_confirmation.confirmed_at must be an ISO-8601 timestamp with timezone.",
            path=str(adapter_path),
            confirmed_at=confirmation.get("confirmed_at"),
        )
    if normalized_sha(confirmation.get("authority_source_sha256")) != expected_hash:
        audit.add(
            "audit_incomplete",
            "adapter_confirmation_source_stale",
            "adapter_confirmation is not bound to the current authority-source SHA-256.",
            path=str(adapter_path),
        )
    projection = dict(author)
    projection.pop("adapter_confirmation", None)
    projection_hash = canonical_hash(projection)
    if (
        str(confirmation.get("status", "")).strip().lower() != "confirmed"
        or confirmation.get("confirmed_scope") != "complete_author_intent_projection"
        or normalized_sha(confirmation.get("qa_view_projection_sha256"))
        != projection_hash
    ):
        audit.add(
            "audit_incomplete",
            "adapter_confirmation_projection_mismatch",
            "adapter_confirmation must confirm the complete canonical QA-view projection.",
            path=str(adapter_path),
            expected_projection_sha256=projection_hash,
        )
    if confirmation.get("intent_revision_id") != author.get("intent_revision_id"):
        audit.add(
            "audit_incomplete",
            "adapter_confirmation_revision_mismatch",
            "adapter_confirmation intent_revision_id differs from the QA view.",
            path=str(adapter_path),
        )
    return {
        "path": str(source_path),
        "sha256": expected_hash,
        "format": source_format,
        "intent_revision_id": author.get("intent_revision_id"),
        "qa_view_projection_sha256": projection_hash,
        "adapter_confirmation": confirmation,
    }


def validate_contract(
    raw: dict[str, Any], path: Path, audit: GateAudit
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    authority_binding = validate_authority_source_adapter(raw, path, audit)
    state, author = contract_views(raw, audit, path)
    version = author.get("schema_version", raw.get("schema_version"))
    if version != SCHEMA_VERSION:
        audit.add(
            "audit_incomplete",
            "unsupported_contract_schema",
            f"Author-intent contract schema_version must be {SCHEMA_VERSION!r}; found {version!r}.",
            path=str(path),
        )

    for field_name in ("intent_contract_id", "intent_revision_id"):
        if not nonempty(author.get(field_name)):
            audit.add(
                "audit_incomplete",
                "contract_identifier_missing",
                f"Author-intent contract is missing {field_name}.",
                field=field_name,
            )

    intent_status = str(author.get("intent_status", "")).strip().lower()
    unresolved = as_list(author.get("unresolved_material_questions"))
    approval = author.get("approval_record")
    hold_reason = nested(approval, "explicit_hold_reason") if isinstance(approval, dict) else None
    gate_status = explicit_gate_status(raw, state, author)

    if gate_status != "ready":
        audit.add(
            "clarification_required",
            "author_intent_gate_not_ready",
            "Author-intent contract/state must explicitly record gate_status=ready.",
            gate_status=gate_status or "unset",
        )

    if intent_status != "frozen-current":
        audit.add(
            "clarification_required",
            "intent_not_frozen",
            "Claim-bearing QA requires one frozen-current author-intent contract.",
            intent_status=intent_status or None,
        )
    if unresolved:
        audit.add(
            "clarification_required",
            "unresolved_material_questions",
            "The author-intent contract still contains unresolved material questions.",
            count=len(unresolved),
        )
    if nonempty(hold_reason):
        audit.add(
            "clarification_required",
            "explicit_author_hold",
            "The contract records an explicit hold on drafting or delivery.",
            hold_reason=hold_reason,
        )
    recorded_evidence_conflict = first_present(
        author,
        (("evidence_conflicts",), ("evidence_conflict",), ("gate_status",)),
    )
    if (
        recorded_evidence_conflict is True
        or isinstance(recorded_evidence_conflict, (list, dict))
        and bool(recorded_evidence_conflict)
        or isinstance(recorded_evidence_conflict, str)
        and recorded_evidence_conflict.strip().lower() == "evidence_conflict"
    ):
        audit.add(
            "evidence_conflict",
            "contract_evidence_conflict",
            "The author-intent contract records an unresolved evidence conflict.",
        )

    required_approval_fields = (
        "confirmed_by",
        "confirmed_at",
        "confirmed_scope",
        "confirmation_source",
        "freeze_authorized_by",
        "freeze_authorized_at",
    )
    if intent_status == "frozen-current":
        if not isinstance(approval, dict):
            audit.add(
                "audit_incomplete",
                "approval_record_missing",
                "A frozen-current contract must contain a recoverable approval_record.",
            )
        else:
            missing = [name for name in required_approval_fields if not nonempty(approval.get(name))]
            if missing:
                audit.add(
                    "audit_incomplete",
                    "approval_record_incomplete",
                    "The frozen contract's approval record is incomplete.",
                    missing_fields=missing,
                )
            invalid_timestamps = [
                field_name
                for field_name in ("confirmed_at", "freeze_authorized_at")
                if nonempty(approval.get(field_name))
                and not valid_iso8601_timestamp(approval.get(field_name))
            ]
            if invalid_timestamps:
                audit.add(
                    "audit_incomplete",
                    "approval_timestamp_invalid",
                    "Author confirmation/freeze timestamps must be ISO-8601 with a UTC offset or Z.",
                    invalid_fields=invalid_timestamps,
                )
            confirmed_scope = normalize_role(approval.get("confirmed_scope"))
            if confirmed_scope not in {
                "complete",
                "complete_author_intent",
                "complete_author_intent_contract",
            }:
                audit.add(
                    "audit_incomplete",
                    "approval_scope_incomplete",
                    "Author confirmation must cover the complete author-intent contract.",
                    confirmed_scope=confirmed_scope or None,
                )
            if (
                nonempty(approval.get("confirmed_by"))
                and nonempty(approval.get("freeze_authorized_by"))
                and approval.get("confirmed_by")
                != approval.get("freeze_authorized_by")
            ) or (
                nonempty(approval.get("confirmed_at"))
                and nonempty(approval.get("freeze_authorized_at"))
                and approval.get("confirmed_at")
                != approval.get("freeze_authorized_at")
            ):
                audit.add(
                    "audit_incomplete",
                    "approval_freeze_event_mismatch",
                    "Complete author confirmation and intent freeze must be the same recorded authorization event.",
                )
    return state, author, authority_binding


def extract_manifest_hashes(manifest: dict[str, Any]) -> tuple[str, str]:
    manuscript_hash = normalized_sha(
        first_present(
            manifest,
            (
                ("inputs", "manuscript", "sha256"),
                ("inputs", "manuscript_sha256"),
                ("manuscript", "sha256"),
                ("manuscript_sha256",),
            ),
        )
    )
    contract_hash = normalized_sha(
        first_present(
            manifest,
            (
                ("inputs", "contract", "sha256"),
                ("inputs", "author_intent_contract", "sha256"),
                ("inputs", "contract_sha256"),
                ("contracts", "author_intent_contract", "sha256"),
                ("contract_sha256",),
            ),
        )
    )
    return manuscript_hash, contract_hash


def extract_artifact_contract_hash(manifest: dict[str, Any]) -> str:
    return normalized_sha(
        first_present(
            manifest,
            (
                ("inputs", "artifact_contract", "sha256"),
                ("inputs", "artifact_contract_sha256"),
                ("contracts", "artifact_contract", "sha256"),
                ("artifact_contract_sha256",),
            ),
        )
    )


def extract_qa_contract_hash(manifest: dict[str, Any]) -> str:
    return normalized_sha(
        first_present(
            manifest,
            (
                ("inputs", "qa_contract", "sha256"),
                ("inputs", "qa_contract_sha256"),
                ("contracts", "qa_contract", "sha256"),
                ("qa_contract_sha256",),
            ),
        )
    )


def extract_content_hash(manifest: dict[str, Any]) -> str:
    return normalized_sha(
        first_present(
            manifest,
            (
                ("inputs", "manuscript", "expanded_sha256"),
                ("manuscript", "expanded_sha256"),
                ("expanded_manuscript_sha256",),
                ("content_sha256",),
            ),
        )
    )


def manifest_input_record(manifest: dict[str, Any], name: str) -> dict[str, Any] | None:
    for container_name in ("inputs", "source"):
        container = manifest.get(container_name)
        if isinstance(container, dict) and isinstance(container.get(name), dict):
            return container[name]
    return None


def unwrap_contract(
    payload: dict[str, Any],
    name: str,
    audit: GateAudit | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    """Resolve direct/top-level/paper_state wrappers without silent shadowing."""

    state = payload.get("paper_state")
    top = payload.get(name)
    nested_contract = state.get(name) if isinstance(state, dict) else None
    if (
        isinstance(top, dict)
        and isinstance(nested_contract, dict)
        and canonical_hash(top) != canonical_hash(nested_contract)
        and audit is not None
    ):
        audit.add(
            "audit_incomplete",
            "contract_wrapper_conflict",
            f"Top-level and paper_state {name} objects disagree.",
            path=str(path) if path is not None else None,
            contract_name=name,
        )
    if isinstance(nested_contract, dict):
        return nested_contract
    if isinstance(top, dict):
        return top
    return payload


def explicit_gate_status(*objects: Any) -> str:
    ready_seen = False
    for value in objects:
        if isinstance(value, dict) and "gate_status" in value:
            raw = value.get("gate_status")
            status = str(raw).strip().lower() if raw is not None else ""
            if status != "ready":
                return status or "unset"
            ready_seen = True
    return "ready" if ready_seen else ""


def verify_manifest_contract_file(
    manifest: dict[str, Any],
    manifest_path: Path,
    name: str,
    expected_hash: str,
    audit: GateAudit,
    *,
    required: bool,
) -> tuple[Path | None, dict[str, Any]]:
    record = manifest_input_record(manifest, name)
    if record is None:
        if required or expected_hash:
            audit.add(
                "audit_incomplete",
                f"manifest_{name}_input_missing",
                f"Manifest must record the {name} path and SHA-256.",
            )
        return None, {}
    raw_path = record.get("path")
    recorded_hash = normalized_sha(record.get("sha256"))
    if not isinstance(raw_path, str) or not raw_path.strip() or not recorded_hash:
        audit.add(
            "audit_incomplete",
            f"manifest_{name}_input_invalid",
            f"Manifest {name} input requires path and SHA-256.",
        )
        return None, {}
    if expected_hash and recorded_hash != expected_hash:
        audit.add(
            "audit_incomplete",
            f"manifest_{name}_hash_inconsistent",
            f"Manifest {name} top-level and input hashes disagree.",
            expected_sha256=expected_hash,
            input_sha256=recorded_hash,
        )
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = manifest_path.parent / path
    path = path.resolve()
    if not path.is_file():
        audit.add(
            "audit_incomplete",
            f"{name}_file_missing",
            f"Current {name} file is missing.",
            path=str(path),
        )
        return path, {}
    actual_hash = sha256_file(path)
    if actual_hash != recorded_hash:
        audit.add(
            "audit_incomplete",
            f"{name}_file_stale",
            f"Current {name} file changed after manifest preparation.",
            path=str(path),
            expected_sha256=recorded_hash,
            actual_sha256=actual_hash,
        )
    payload = load_json_object(path, audit, name)
    if payload is None:
        return path, {}
    contract = unwrap_contract(payload, name, audit, path)
    version = contract.get("schema_version", payload.get("schema_version"))
    if version != SCHEMA_VERSION and not (name == "artifact_contract" and version is None):
        audit.add(
            "audit_incomplete",
            f"unsupported_{name}_schema",
            f"{name} schema_version must be {SCHEMA_VERSION!r}; found {version!r}.",
            path=str(path),
        )
    gate_status = explicit_gate_status(payload, contract, payload.get("paper_state"))
    if gate_status and gate_status != "ready":
        audit.add(
            "clarification_required",
            f"{name}_gate_not_ready",
            f"{name} records a non-ready gate_status.",
            path=str(path),
            gate_status=gate_status,
        )
    return path, contract


def candidate_hash_from_args(args: argparse.Namespace, audit: GateAudit) -> tuple[str, Path | None]:
    supplied: list[tuple[str, str]] = []
    candidate_path: Path | None = None
    if args.candidate:
        candidate_path = Path(args.candidate).expanduser().resolve()
        if not candidate_path.is_file():
            audit.add(
                "audit_incomplete",
                "candidate_missing",
                "Candidate manuscript does not exist.",
                path=str(candidate_path),
            )
        else:
            supplied.append(("candidate", sha256_file(candidate_path)))
    if args.candidate_sha256:
        digest = normalized_sha(args.candidate_sha256)
        if not digest:
            audit.add(
                "audit_incomplete",
                "invalid_candidate_hash",
                "--candidate-sha256 must contain exactly 64 hexadecimal characters.",
            )
        else:
            supplied.append(("candidate_sha256", digest))
    if args.candidate_sha256_file:
        hash_path = Path(args.candidate_sha256_file).expanduser().resolve()
        try:
            first_token = hash_path.read_text(encoding="utf-8").strip().split()[0]
        except (OSError, UnicodeDecodeError, IndexError) as exc:
            audit.add(
                "audit_incomplete",
                "candidate_hash_file_invalid",
                f"Cannot read candidate hash file: {exc}",
                path=str(hash_path),
            )
        else:
            digest = normalized_sha(first_token)
            if not digest:
                audit.add(
                    "audit_incomplete",
                    "candidate_hash_file_invalid",
                    "Candidate hash file does not begin with a SHA-256 digest.",
                    path=str(hash_path),
                )
            else:
                supplied.append(("candidate_sha256_file", digest))
    if not supplied:
        audit.add(
            "audit_incomplete",
            "candidate_hash_source_missing",
            "Supply --candidate, --candidate-sha256, or --candidate-sha256-file.",
        )
        return "", candidate_path
    distinct = {digest for _, digest in supplied}
    if len(distinct) != 1:
        audit.add(
            "audit_incomplete",
            "candidate_hash_sources_disagree",
            "The supplied candidate hash sources do not agree.",
            sources=[{"source": label, "sha256": digest} for label, digest in supplied],
        )
        return "", candidate_path
    return supplied[0][1], candidate_path


def verify_source_files(
    manifest: dict[str, Any], manifest_path: Path, project_root: Path | None, audit: GateAudit
) -> dict[str, str]:
    bindings: dict[str, str] = {}
    source_files = first_present(
        manifest,
        (("inputs", "source_files"), ("source_files",)),
    )
    if source_files is None:
        return bindings
    if not isinstance(source_files, list):
        audit.add(
            "audit_incomplete",
            "source_file_manifest_invalid",
            "inputs.source_files must be a list when present.",
        )
        return bindings
    root = project_root or manifest_path.parent
    for item in source_files:
        if not isinstance(item, dict):
            audit.add(
                "audit_incomplete",
                "source_file_manifest_invalid",
                "Each source_files entry must be an object.",
            )
            continue
        raw_path = item.get("path")
        expected = normalized_sha(item.get("sha256"))
        if not isinstance(raw_path, str) or not expected:
            audit.add(
                "audit_incomplete",
                "source_file_manifest_invalid",
                "Each source_files entry requires path and sha256.",
                entry=item,
            )
            continue
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        bindings[str(path)] = expected
        if not path.is_file():
            audit.add(
                "audit_incomplete",
                "source_file_missing",
                "A source file recorded by the manifest is missing.",
                path=str(path),
            )
            continue
        actual = sha256_file(path)
        if actual != expected:
            audit.add(
                "audit_incomplete",
                "source_file_stale",
                "A manuscript source file changed after QA preparation.",
                path=str(path),
                expected_sha256=expected,
                actual_sha256=actual,
            )
    return bindings


def live_review_target_projection(unit: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize only reader-visible targets; container IDs are internal."""

    region = str(unit.get("region", "")).strip().lower()
    if not region:
        region = "appendix" if unit.get("appendix") is True else "main_text"
    roles = sorted(
        {
            role
            for role in (
                normalize_role(value)
                for value in as_list(unit.get("required_roles"))
            )
            if role
        }
    )
    return {
        "type": str(unit.get("type", unit.get("kind", ""))).strip().lower(),
        "kind": str(unit.get("kind", unit.get("type", ""))).strip().lower(),
        "text": unit.get("text"),
        "text_sha256": normalized_sha(unit.get("text_sha256")),
        "reader_visible": bool(unit.get("reader_visible", True)),
        "review_target": bool(unit.get("review_target", True)),
        "selected_for_review": is_review_target(unit),
        "region": region,
        "required_roles": roles,
        "formula_ids": [
            value
            for value in as_list(unit.get("formula_ids"))
            if isinstance(value, str) and value
        ],
        "citation_keys": [
            value
            for value in as_list(unit.get("citation_keys"))
            if isinstance(value, str) and value
        ],
        "reference_labels": [
            value
            for value in as_list(unit.get("reference_labels"))
            if isinstance(value, str) and value
        ],
        "declared_labels": [
            value
            for value in as_list(unit.get("declared_labels"))
            if isinstance(value, str) and value
        ],
        "footnote_reference_ids": [
            value
            for value in as_list(unit.get("footnote_reference_ids"))
            if isinstance(value, str) and value
        ],
        "external_links": [
            value
            for value in as_list(unit.get("external_links"))
            if isinstance(value, str) and value
        ],
    }


def validate_live_preparation_projection(
    manifest: dict[str, Any],
    manifest_path: Path,
    project_root: Path | None,
    author: dict[str, Any],
    qa_contract: dict[str, Any],
    qa_contract_path: Path | None,
    units: list[dict[str, Any]],
    manifest_source_bindings: dict[str, str],
    audit: GateAudit,
) -> None:
    """Replay preparation from live sources and reject a forged unit universe."""

    if manifest.get("schema_id") != QA_MANIFEST_SCHEMA_ID:
        audit.add(
            "audit_incomplete",
            "qa_manifest_schema_identity_invalid",
            f"QA manifest must use schema_id={QA_MANIFEST_SCHEMA_ID}.",
            schema_id=manifest.get("schema_id"),
        )
    if qa_preparer is None:
        audit.add(
            "audit_incomplete",
            "live_preparation_replay_unavailable",
            "The co-shipped preparation module is unavailable, so source coverage cannot be replayed.",
        )
        return
    manuscript_record = first_present(
        manifest,
        (("inputs", "manuscript"), ("manuscript",), ("source", "manuscript")),
    )
    if not isinstance(manuscript_record, dict):
        audit.add(
            "audit_incomplete",
            "live_preparation_replay_input_invalid",
            "Manifest must bind the live manuscript path and project root for deterministic replay.",
        )
        return
    recorded_root = resolve_bound_path(
        manuscript_record.get("project_root"), manifest_path.parent
    )
    if recorded_root is None or not recorded_root.is_dir():
        audit.add(
            "audit_incomplete",
            "live_preparation_project_root_invalid",
            "Canonical replay requires an existing project_root frozen in the manifest manuscript record.",
        )
        return
    recorded_root = recorded_root.resolve()
    if project_root is not None and project_root.resolve() != recorded_root:
        audit.add(
            "audit_incomplete",
            "live_preparation_project_root_mismatch",
            "--project-root must exactly equal the project root frozen by canonical preparation.",
            recorded_project_root=str(recorded_root),
            supplied_project_root=str(project_root.resolve()),
        )
    replay_root = recorded_root
    manuscript_path = resolve_bound_path(
        manuscript_record.get("path"), replay_root
    )
    if manuscript_path is None or not manuscript_path.is_file():
        audit.add(
            "audit_incomplete",
            "live_preparation_replay_input_invalid",
            "The live manuscript recorded by the manifest is unavailable.",
            path=str(manuscript_path) if manuscript_path is not None else None,
        )
        return
    qa_manuscript_path = (
        resolve_bound_path(
            qa_contract.get("manuscript_path"), qa_contract_path.parent
        )
        if qa_contract_path is not None
        else None
    )
    if qa_manuscript_path is None:
        audit.add(
            "audit_incomplete",
            "qa_manuscript_path_missing",
            "qa_contract.manuscript_path must identify the exact live manuscript.",
        )
    elif qa_manuscript_path != manuscript_path.resolve():
        audit.add(
            "audit_incomplete",
            "qa_manuscript_path_mismatch",
            "qa_contract.manuscript_path must resolve to the same root manuscript replayed from the manifest.",
            qa_contract_path=str(qa_manuscript_path),
            live_manuscript_path=str(manuscript_path.resolve()),
        )
    try:
        qa_preparer.ensure_within_root(manuscript_path.resolve(), replay_root)
    except Exception as exc:
        audit.add(
            "audit_incomplete",
            "live_manuscript_outside_project_root",
            "Root manuscript must remain inside the frozen project root.",
            path=str(manuscript_path),
            project_root=str(replay_root),
            error=str(exc),
        )
        return
    suffix = manuscript_path.suffix.lower()
    if suffix not in {".tex", ".md", ".txt"}:
        audit.add(
            "audit_incomplete",
            "live_preparation_replay_input_invalid",
            "Live preparation replay supports only .tex, .md, and .txt manuscripts.",
            path=str(manuscript_path),
        )
        return
    try:
        document = (
            qa_preparer.expand_tex(manuscript_path, replay_root)
            if suffix == ".tex"
            else qa_preparer.single_file_document(
                manuscript_path, strip_html_comments=suffix == ".md"
            )
        )
        expected_units, expected_appendix, expected_formulas = (
            qa_preparer.prepare_units(
                document,
                suffix[1:],
                replay_root,
                author,
                qa_contract,
                manifest.get("content_obligations", []),
                manifest.get("definition_registry", []),
            )
        )
        qa_mode = str(qa_contract.get("qa_mode", "")).strip().lower()
        revision_scope = qa_contract.get(
            "revision_scope",
            qa_contract.get(
                "review_scope", "full_manuscript" if qa_mode == "exhaustive" else None
            ),
        )
        qa_preparer.apply_review_scope(expected_units, qa_mode, revision_scope)
    except Exception as exc:
        audit.add(
            "audit_incomplete",
            "live_preparation_replay_failed",
            "The co-shipped preparer could not reproduce the live manuscript projection.",
            error=str(exc),
        )
        return

    manifest_units_exact = [
        {key: value for key, value in unit.items() if key != "_order"}
        for unit in units
    ]
    if canonical_hash(manifest_units_exact) != canonical_hash(expected_units):
        audit.add(
            "audit_incomplete",
            "live_unit_universe_mismatch",
            "Manifest units must exactly equal the complete canonical unit graph re-extracted from the live manuscript.",
            expected_unit_count=len(expected_units),
            manifest_unit_count=len(manifest_units_exact),
            expected_projection_sha256=canonical_hash(expected_units),
            manifest_projection_sha256=canonical_hash(manifest_units_exact),
        )

    if canonical_hash(manifest.get("formulas")) != canonical_hash(expected_formulas):
        audit.add(
            "audit_incomplete",
            "live_formula_registry_mismatch",
            "Manifest formulas differ from formulas re-extracted from the live source spans.",
        )
    if canonical_hash(manifest.get("appendix")) != canonical_hash(expected_appendix):
        audit.add(
            "audit_incomplete",
            "live_appendix_projection_mismatch",
            "Manifest appendix boundary differs from the boundary re-extracted from the live manuscript.",
        )
    expected_source_bindings = {
        str(path.resolve()): digest
        for path, digest in document.source_hashes.items()
    }
    if manifest_source_bindings != expected_source_bindings:
        audit.add(
            "audit_incomplete",
            "live_source_file_universe_mismatch",
            "Manifest source-file bindings differ from the live include graph reconstructed by the preparer.",
            missing_sources=sorted(
                set(expected_source_bindings) - set(manifest_source_bindings)
            ),
            unexpected_sources=sorted(
                set(manifest_source_bindings) - set(expected_source_bindings)
            ),
        )

    canonical_source_files = [
        {
            "path": str(path.relative_to(replay_root)),
            "sha256": digest,
            "bytes": len(document.source_texts[path].encode("utf-8")),
        }
        for path, digest in sorted(
            document.source_hashes.items(), key=lambda item: str(item[0])
        )
    ]
    source_container = manifest.get("source")
    exact_manuscript_records = {
        "manuscript": manifest.get("manuscript"),
        "inputs.manuscript": nested(manifest, "inputs", "manuscript"),
        "source.manuscript": (
            source_container.get("manuscript")
            if isinstance(source_container, dict)
            else None
        ),
    }

    root_path = replay_root.resolve()
    manuscript_path = manuscript_path.resolve()
    raw_source = document.source_texts.get(manuscript_path)
    if raw_source is None:
        audit.add(
            "audit_incomplete",
            "live_root_manuscript_missing",
            "Canonical preparation replay did not retain the root manuscript source.",
            path=str(manuscript_path),
        )
        return
    raw_manuscript_sha = sha256_text(raw_source)
    expanded_sha = sha256_text(document.text)
    try:
        relative_path = str(manuscript_path.relative_to(root_path))
    except ValueError:
        audit.add(
            "audit_incomplete",
            "live_manuscript_project_root_invalid",
            "Manifest manuscript path is outside its frozen project root.",
            path=str(manuscript_path),
            project_root=str(root_path),
        )
        return
    expected_manuscript_record = {
        "path": str(manuscript_path),
        "relative_path": relative_path,
        "sha256": raw_manuscript_sha,
        "expanded_sha256": expanded_sha,
        "format": suffix[1:],
        "project_root": str(root_path),
    }
    mismatched_records = [
        name
        for name, record in exact_manuscript_records.items()
        if canonical_hash(record) != canonical_hash(expected_manuscript_record)
    ]
    if mismatched_records:
        audit.add(
            "audit_incomplete",
            "live_manuscript_binding_mismatch",
            "Manifest must bind the canonical root path, project root, format, raw hash, and expanded hash reproduced from live sources.",
            expected=expected_manuscript_record,
            mismatched_records=mismatched_records,
        )
    source_file_records = {
        "source_files": manifest.get("source_files"),
        "source.source_files": (
            source_container.get("source_files")
            if isinstance(source_container, dict)
            else None
        ),
    }
    mismatched_source_records = [
        name
        for name, records in source_file_records.items()
        if canonical_hash(records) != canonical_hash(canonical_source_files)
    ]
    if mismatched_source_records:
        audit.add(
            "audit_incomplete",
            "live_source_file_record_mismatch",
            "Manifest source-file records must exactly reproduce canonical relative paths, hashes, and UTF-8 byte counts.",
            mismatched_records=mismatched_source_records,
            expected_source_files=canonical_source_files,
        )

    _, contract_sha = extract_manifest_hashes(manifest)
    qa_contract_sha = extract_qa_contract_hash(manifest)
    artifact_contract_sha = extract_artifact_contract_hash(manifest) or None
    try:
        replay_roles = qa_preparer.role_list(qa_contract)
        replay_role_protocols = {
            role: qa_preparer.ROLE_PROTOCOLS[role] for role in replay_roles
        }
        replay_role_protocols_sha = canonical_hash(
            {
                "role_protocol_version": qa_preparer.ROLE_PROTOCOL_VERSION,
                "role_protocols": replay_role_protocols,
            }
        )
    except Exception as exc:
        audit.add(
            "audit_incomplete",
            "live_role_protocol_replay_failed",
            "Canonical role protocol projection could not be reproduced.",
            error=str(exc),
        )
        return
    qa_bundle_sha = canonical_hash(
        {
            "author_intent_contract_sha256": contract_sha,
            "qa_contract_sha256": qa_contract_sha,
            "artifact_contract_sha256": artifact_contract_sha,
        }
    )
    identity = {
        "schema_version": SCHEMA_VERSION,
        "manuscript_sha256": raw_manuscript_sha,
        "expanded_sha256": expanded_sha,
        "contract_sha256": contract_sha,
        "qa_bundle_sha256": qa_bundle_sha,
        "role_protocols_sha256": replay_role_protocols_sha,
        "formula_registry_sha256": canonical_hash(expected_formulas),
        "unit_ids_and_hashes": [
            [unit["unit_id"], unit["text_sha256"]]
            for unit in expected_units
        ],
    }
    expected_manifest_id = qa_preparer.stable_id(
        "qamanifest", canonical_hash(identity)
    )
    expected_top_level = {
        "manifest_id": expected_manifest_id,
        "manuscript_id": qa_preparer.stable_id(
            "manuscript", raw_manuscript_sha, expanded_sha
        ),
        "manuscript_sha256": raw_manuscript_sha,
        "expanded_manuscript_sha256": expanded_sha,
        "contract_sha256": contract_sha,
        "author_intent_contract_sha256": contract_sha,
        "qa_contract_sha256": qa_contract_sha,
        "artifact_contract_sha256": artifact_contract_sha,
        "qa_bundle_sha256": qa_bundle_sha,
        "role_protocols_sha256": replay_role_protocols_sha,
        "formula_registry_sha256": canonical_hash(expected_formulas),
    }
    identity_mismatches = [
        field_name
        for field_name, expected in expected_top_level.items()
        if manifest.get(field_name) != expected
    ]
    if identity_mismatches:
        audit.add(
            "audit_incomplete",
            "qa_manifest_identity_mismatch",
            "Manifest identity and top-level hashes must exactly equal the canonical preparation replay.",
            mismatched_fields=identity_mismatches,
            expected_manifest_id=expected_manifest_id,
        )


def manifest_units(
    manifest: dict[str, Any], audit: GateAudit
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    raw_units = manifest.get("units")
    if not isinstance(raw_units, list) or not raw_units:
        audit.add(
            "audit_incomplete",
            "manifest_units_missing",
            "QA manifest must contain a nonempty units list.",
        )
        return [], {}
    units: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(raw_units):
        if not isinstance(item, dict):
            audit.add(
                "audit_incomplete",
                "manifest_unit_invalid",
                "Every manifest unit must be an object.",
                unit_index=index,
            )
            continue
        unit_id = item.get("unit_id", item.get("id"))
        if not isinstance(unit_id, str) or not unit_id.strip():
            audit.add(
                "audit_incomplete",
                "manifest_unit_id_missing",
                "Every manifest unit requires a nonempty unit_id.",
                unit_index=index,
            )
            continue
        unit_id = unit_id.strip()
        if unit_id in by_id:
            audit.add(
                "audit_incomplete",
                "duplicate_manifest_unit_id",
                "Manifest unit IDs must be unique.",
                unit_id=unit_id,
            )
            continue
        item = dict(item)
        item["unit_id"] = unit_id
        item["_order"] = len(units)
        text_hash = normalized_sha(item.get("text_sha256"))
        if not text_hash:
            audit.add(
                "audit_incomplete",
                "unit_text_hash_missing",
                "Every reader-visible unit requires text_sha256.",
                unit_id=unit_id,
            )
        elif isinstance(item.get("text"), str) and sha256_text(item["text"]) != text_hash:
            audit.add(
                "audit_incomplete",
                "unit_text_hash_invalid",
                "Unit text does not match its recorded text_sha256.",
                unit_id=unit_id,
            )
        units.append(item)
        by_id[unit_id] = item
    return units, by_id


def validate_container_coverage(
    units: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    audit: GateAudit,
) -> None:
    """Prove that non-target reader-visible containers are covered by children."""

    for parent in units:
        if not parent.get("reader_visible", True) or bool(parent.get("review_target", True)):
            continue
        parent_id = parent["unit_id"]
        parent_text = parent.get("text")
        child_ids = parent.get("child_unit_ids")
        if not isinstance(parent_text, str) or not isinstance(child_ids, list) or not child_ids:
            audit.add(
                "audit_incomplete",
                "container_child_manifest_missing",
                "Reader-visible non-target container requires text and child_unit_ids.",
                unit_id=parent_id,
            )
            continue
        if not all(isinstance(value, str) and value for value in child_ids):
            audit.add(
                "audit_incomplete",
                "container_child_id_invalid",
                "Every child_unit_id must be a nonempty string.",
                unit_id=parent_id,
            )
        string_child_ids = [value for value in child_ids if isinstance(value, str)]
        if len(string_child_ids) != len(set(string_child_ids)):
            audit.add(
                "audit_incomplete",
                "container_child_ids_duplicate",
                "Container child_unit_ids must be unique.",
                unit_id=parent_id,
            )
        children: list[dict[str, Any]] = []
        structural_error = False
        for child_id in child_ids:
            child = by_id.get(child_id) if isinstance(child_id, str) else None
            if child is None:
                audit.add(
                    "audit_incomplete",
                    "container_child_missing",
                    "Container references a child absent from the manifest.",
                    unit_id=parent_id,
                    child_unit_id=child_id,
                )
                structural_error = True
                continue
            children.append(child)
            if child.get("parent_id") != parent_id:
                audit.add(
                    "audit_incomplete",
                    "container_child_parent_mismatch",
                    "Child parent_id does not point back to its container.",
                    unit_id=parent_id,
                    child_unit_id=child_id,
                )
                structural_error = True
            if not bool(child.get("review_target", False)):
                audit.add(
                    "audit_incomplete",
                    "container_child_not_review_target",
                    "Every child that covers a non-target container must be a review target.",
                    unit_id=parent_id,
                    child_unit_id=child_id,
                )
                structural_error = True

        expected_child_hash = canonical_hash(
            [[child["unit_id"], child.get("text_sha256")] for child in children]
        )
        if normalized_sha(parent.get("child_text_sha256")) != expected_child_hash:
            audit.add(
                "audit_incomplete",
                "container_child_text_hash_invalid",
                "Container child_text_sha256 does not match its ordered child IDs and hashes.",
                unit_id=parent_id,
            )

        covered = [False] * len(parent_text)
        for child in children:
            source = child.get("source") if isinstance(child.get("source"), dict) else {}
            start = child.get("text_start_in_parent", source.get("text_start_in_parent"))
            end = child.get("text_end_in_parent", source.get("text_end_in_parent"))
            if (
                isinstance(start, bool)
                or isinstance(end, bool)
                or not isinstance(start, int)
                or not isinstance(end, int)
                or start < 0
                or end <= start
                or end > len(parent_text)
            ):
                audit.add(
                    "audit_incomplete",
                    "container_child_span_invalid",
                    "Child requires a valid nonempty normalized span inside its parent.",
                    unit_id=parent_id,
                    child_unit_id=child.get("unit_id"),
                )
                structural_error = True
                continue
            child_text = child.get("text")
            if not isinstance(child_text, str) or parent_text[start:end] != child_text:
                audit.add(
                    "audit_incomplete",
                    "container_child_span_text_mismatch",
                    "Child text does not equal the recorded parent substring.",
                    unit_id=parent_id,
                    child_unit_id=child.get("unit_id"),
                )
                structural_error = True
            for index in range(start, end):
                if covered[index] and not parent_text[index].isspace():
                    audit.add(
                        "audit_incomplete",
                        "container_child_span_overlap",
                        "Child sentence spans overlap on a non-whitespace parent character.",
                        unit_id=parent_id,
                        child_unit_id=child.get("unit_id"),
                    )
                    structural_error = True
                    break
                covered[index] = True
        if not structural_error:
            uncovered = [
                index
                for index, character in enumerate(parent_text)
                if not character.isspace() and not covered[index]
            ]
            if uncovered:
                audit.add(
                    "audit_incomplete",
                    "container_child_coverage_incomplete",
                    "Child spans do not cover every non-whitespace parent character.",
                    unit_id=parent_id,
                    first_uncovered_index=uncovered[0],
                    uncovered_characters=len(uncovered),
                )


def referenced_formula_ids(value: Any) -> set[str]:
    identifiers: set[str] = set()
    if isinstance(value, str):
        identifiers.update(re.findall(r"\[FORMULA:([^\]]+)\]", value))
    elif isinstance(value, list):
        for item in value:
            identifiers.update(referenced_formula_ids(item))
    elif isinstance(value, dict):
        for item in value.values():
            identifiers.update(referenced_formula_ids(item))
    return identifiers


def validate_formula_registry(
    manifest: dict[str, Any],
    manifest_path: Path,
    units: list[dict[str, Any]],
    audit: GateAudit,
) -> tuple[str, dict[str, dict[str, Any]]]:
    formulas = manifest.get("formulas")
    registry_hash = normalized_sha(manifest.get("formula_registry_sha256"))
    if not isinstance(formulas, list) or registry_hash != canonical_hash(formulas):
        audit.add(
            "audit_incomplete",
            "formula_registry_binding_invalid",
            "Manifest must carry an array-valued formula registry and its exact canonical SHA-256.",
        )
        return registry_hash, {}
    by_formula: dict[str, dict[str, Any]] = {}
    malformed = False
    manuscript_record = first_present(
        manifest,
        (("inputs", "manuscript"), ("manuscript",)),
    )
    project_root_raw = (
        manuscript_record.get("project_root")
        if isinstance(manuscript_record, dict)
        else None
    )
    project_root = resolve_bound_path(project_root_raw, manifest_path.parent)
    if project_root is None:
        project_root = manifest_path.parent
    for record in formulas:
        if not isinstance(record, dict):
            malformed = True
            continue
        formula_id = record.get("formula_id")
        raw = record.get("raw")
        normalized = record.get("normalized_math")
        spans = record.get("source_spans")
        declared_labels = record.get("declared_labels")
        expected_labels = (
            list(
                dict.fromkeys(
                    normalized_label
                    for value in re.findall(r"\\label\s*\{([^{}]+)\}", raw)
                    if (normalized_label := re.sub(r"\s+", " ", value).strip())
                )
            )
            if isinstance(raw, str)
            else []
        )
        if (
            not isinstance(formula_id, str)
            or not formula_id.startswith("formula_")
            or formula_id in by_formula
            or not isinstance(raw, str)
            or not raw
            or not isinstance(normalized, str)
            or normalized != re.sub(r"\s+", " ", raw).strip()
            or normalized_sha(record.get("raw_sha256")) != sha256_text(raw)
            or normalized_sha(record.get("normalized_sha256"))
            != sha256_text(normalized)
            or not isinstance(declared_labels, list)
            or declared_labels != expected_labels
            or not isinstance(spans, list)
            or not spans
        ):
            malformed = True
            continue
        reconstructed: list[str] = []
        spans_valid = True
        for span in spans:
            if not isinstance(span, dict):
                spans_valid = False
                break
            source_path = resolve_bound_path(span.get("path"), project_root)
            start = span.get("start_offset")
            end = span.get("end_offset")
            if (
                source_path is None
                or not source_path.is_file()
                or isinstance(start, bool)
                or not isinstance(start, int)
                or isinstance(end, bool)
                or not isinstance(end, int)
            ):
                spans_valid = False
                break
            try:
                source_text = source_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                spans_valid = False
                break
            if start < 0 or end <= start or end > len(source_text):
                spans_valid = False
                break
            reconstructed.append(source_text[start:end])
        if not spans_valid or "".join(reconstructed) != raw:
            malformed = True
            continue
        by_formula[formula_id] = record
    if malformed or len(by_formula) != len(formulas):
        audit.add(
            "audit_incomplete",
            "formula_registry_record_invalid",
            "Formula records require unique IDs, source-matched raw text, whitespace-only normalization, and exact hashes.",
        )
    target_references: set[str] = set()
    selected_references: set[str] = set()
    for unit in units:
        if not bool(unit.get("review_target", True)):
            continue
        unit_references = {
            value
            for value in as_list(unit.get("formula_ids"))
            if isinstance(value, str) and value
        }
        unit_references.update(referenced_formula_ids(unit.get("context")))
        unit_references.update(referenced_formula_ids(unit.get("text")))
        target_references.update(unit_references)
        if is_review_target(unit):
            selected_references.update(unit_references)
    unknown = (target_references | selected_references) - set(by_formula)
    unreviewed = set(by_formula) - target_references
    if unknown or unreviewed:
        audit.add(
            "audit_incomplete",
            "formula_review_scope_invalid",
            "Every formula must be referenced by a selected review target, and every target formula ID must exist in the registry.",
            unknown_formula_ids=sorted(unknown),
            unreviewed_formula_ids=sorted(unreviewed),
        )
    return registry_hash, by_formula


def validate_dependency_contexts(
    units: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    audit: GateAudit,
) -> None:
    for unit in units:
        if not bool(unit.get("review_target", True)):
            continue
        dependency_ids = [
            value
            for value in as_list(unit.get("dependency_unit_ids"))
            if isinstance(value, str) and value
        ]
        context = unit.get("context")
        context = context if isinstance(context, dict) else {}
        dependency_context = context.get("dependency_units", [])
        if not isinstance(dependency_context, list):
            dependency_context = []
        expected: list[dict[str, Any]] = []
        missing_ids: list[str] = []
        for dependency_id in dependency_ids:
            dependency = by_id.get(dependency_id)
            if dependency is None:
                missing_ids.append(dependency_id)
                continue
            expected.append(
                {
                    "unit_id": dependency["unit_id"],
                    "type": dependency.get("type"),
                    "text": dependency.get("text"),
                    "text_sha256": dependency.get("text_sha256"),
                    "child_unit_ids": dependency.get("child_unit_ids", []),
                    "source_spans": dependency.get("source_spans", []),
                }
            )
        if missing_ids or canonical_hash(dependency_context) != canonical_hash(expected):
            audit.add(
                "audit_incomplete",
                "unit_dependency_context_invalid",
                "Unit context must include an exact live projection of every declared dependency unit.",
                unit_id=unit.get("unit_id"),
                missing_dependency_ids=missing_ids,
            )


def validate_qa_derived_state(
    manifest: dict[str, Any],
    qa_contract: dict[str, Any],
    author: dict[str, Any],
    units: list[dict[str, Any]],
    audit: GateAudit,
) -> str:
    """Bind manifest routing/scope state to the live, hash-bound QA contract."""

    protocol_version = str(manifest.get("role_protocol_version", "")).strip()
    manifest_protocols = manifest.get("role_protocols")
    manifest_protocol_hash = normalized_sha(manifest.get("role_protocols_sha256"))
    if (
        protocol_version != ROLE_PROTOCOL_VERSION
        or not isinstance(manifest_protocols, dict)
        or canonical_hash(manifest_protocols) != canonical_hash(ROLE_PROTOCOLS)
        or manifest_protocol_hash != role_protocols_hash()
    ):
        audit.add(
            "audit_incomplete",
            "role_protocol_manifest_invalid",
            "Manifest must bind the fixed role-protocol version, definitions, and canonical SHA-256.",
            role_protocol_version=protocol_version or None,
        )

    expected_mode = str(qa_contract.get("qa_mode", "")).strip().lower()
    actual_mode = str(manifest.get("qa_mode", "")).strip().lower()
    if expected_mode not in {"exhaustive", "bounded_change"}:
        audit.add(
            "audit_incomplete",
            "qa_contract_mode_invalid",
            "qa_contract.qa_mode must be exhaustive or bounded_change.",
            qa_mode=expected_mode or None,
        )
    if actual_mode != expected_mode:
        audit.add(
            "audit_incomplete",
            "qa_mode_manifest_mismatch",
            "Manifest qa_mode does not match the current hash-bound QA contract.",
            manifest_qa_mode=actual_mode or None,
            contract_qa_mode=expected_mode or None,
        )

    raw_revision_targets = manifest.get("revision_target_unit_ids")
    revision_targets_valid = (
        isinstance(raw_revision_targets, list)
        and all(
            isinstance(value, str) and value.strip()
            for value in raw_revision_targets
        )
        and raw_revision_targets
        == sorted({value.strip() for value in raw_revision_targets})
    )
    if not revision_targets_valid:
        audit.add(
            "audit_incomplete",
            "revision_target_unit_ids_invalid",
            "manifest.revision_target_unit_ids must be an explicit sorted, unique list of nonempty unit IDs.",
        )
        normalized_revision_targets: list[str] = []
    else:
        normalized_revision_targets = list(raw_revision_targets)
    expected_revision_targets = (
        sorted(
            str(unit["unit_id"])
            for unit in units
            if unit.get("review_target")
            and unit.get("selected_for_review")
        )
        if expected_mode == "bounded_change"
        else []
    )
    if normalized_revision_targets != expected_revision_targets:
        audit.add(
            "audit_incomplete",
            "revision_target_unit_ids_mismatch",
            "manifest.revision_target_unit_ids must exactly equal the live selected review-target universe for bounded QA and [] for exhaustive QA.",
            expected_unit_ids=expected_revision_targets,
            recorded_unit_ids=normalized_revision_targets,
        )

    raw_high_risk_minimum = qa_contract.get(
        "minimum_high_risk_independent_reviews"
    )
    high_risk_minimum_valid = (
        not isinstance(raw_high_risk_minimum, bool)
        and isinstance(raw_high_risk_minimum, int)
        and 2 <= raw_high_risk_minimum <= 4
    )
    if not high_risk_minimum_valid:
        audit.add(
            "audit_incomplete",
            "qa_high_risk_review_minimum_invalid",
            "qa_contract.minimum_high_risk_independent_reviews must be an explicit integer from 2 through 4.",
            recorded_value=raw_high_risk_minimum,
        )
        high_risk_minimum = 2
    else:
        high_risk_minimum = raw_high_risk_minimum

    classification = qa_contract.get("task_classification")
    required_base_classification_fields = (
        "task_stage",
        "qa_mode",
        "basis",
        "classified_by",
        "classified_at",
    )
    if not isinstance(classification, dict):
        audit.add(
            "audit_incomplete",
            "task_classification_missing",
            "qa_contract requires a recoverable task_classification object.",
        )
        classification = {}
    missing_base_classification = [
        field_name
        for field_name in required_base_classification_fields
        if not nonempty(classification.get(field_name))
    ]
    if missing_base_classification:
        audit.add(
            "audit_incomplete",
            "task_classification_incomplete",
            "task_classification is missing required provenance or routing fields.",
            missing_fields=missing_base_classification,
        )
    if nonempty(classification.get("classified_at")) and not valid_iso8601_timestamp(
        classification.get("classified_at")
    ):
        audit.add(
            "audit_incomplete",
            "task_classification_timestamp_invalid",
            "task_classification.classified_at must be an ISO-8601 timestamp with timezone.",
            classified_at=classification.get("classified_at"),
        )
    classification_mode = str(classification.get("qa_mode", "")).strip().lower()
    if classification_mode != expected_mode:
        audit.add(
            "audit_incomplete",
            "task_classification_mode_mismatch",
            "task_classification.qa_mode must exactly match qa_contract.qa_mode.",
            classification_qa_mode=classification_mode or None,
            contract_qa_mode=expected_mode or None,
        )
    task_stage = str(classification.get("task_stage", "")).strip().lower()
    expected_stage_mode = TASK_STAGE_TO_QA_MODE.get(task_stage)
    if expected_stage_mode is None:
        audit.add(
            "audit_incomplete",
            "task_stage_invalid",
            "task_classification.task_stage must use the fixed stage vocabulary.",
            task_stage=task_stage or None,
            allowed_task_stages=sorted(TASK_STAGE_TO_QA_MODE),
        )
    elif expected_stage_mode != expected_mode:
        audit.add(
            "audit_incomplete",
            "task_stage_mode_mismatch",
            "task_classification.task_stage is incompatible with qa_contract.qa_mode.",
            task_stage=task_stage,
            expected_qa_mode=expected_stage_mode,
            contract_qa_mode=expected_mode or None,
        )

    scope_explicit = "revision_scope" in qa_contract or "review_scope" in qa_contract
    expected_scope = qa_contract.get(
        "revision_scope",
        qa_contract.get("review_scope", "full_manuscript" if expected_mode == "exhaustive" else None),
    )
    if expected_mode == "bounded_change" or scope_explicit:
        if canonical_hash(manifest.get("revision_scope")) != canonical_hash(expected_scope):
            audit.add(
                "audit_incomplete",
                "qa_revision_scope_manifest_mismatch",
                "Manifest revision_scope does not match the current hash-bound QA contract.",
            )
    if expected_mode == "bounded_change":
        if not isinstance(expected_scope, dict):
            audit.add(
                "audit_incomplete",
                "bounded_revision_scope_invalid",
                "bounded_change requires an object-valued revision_scope.",
            )
        else:
            changed = expected_scope.get("changed_unit_ids") or expected_scope.get(
                "changed_source_ranges"
            )
            dependency_recorded = (
                "dependency_unit_ids" in expected_scope
                or "dependency_source_ranges" in expected_scope
            )
            if not nonempty(changed) or not dependency_recorded:
                audit.add(
                    "audit_incomplete",
                    "bounded_revision_scope_incomplete",
                    "bounded_change requires a nonempty changed selector and an explicit dependency selector.",
                )
            affected_intents = expected_scope.get("affected_intent_ids")
            classification_affected = classification.get("affected_intent_ids")
            scope_affected_valid = (
                isinstance(affected_intents, list)
                and bool(affected_intents)
                and all(
                    isinstance(value, str) and value.strip()
                    for value in affected_intents
                )
                and len(affected_intents)
                == len({value.strip() for value in affected_intents})
            )
            classification_affected_valid = (
                isinstance(classification_affected, list)
                and bool(classification_affected)
                and all(
                    isinstance(value, str) and value.strip()
                    for value in classification_affected
                )
                and len(classification_affected)
                == len({value.strip() for value in classification_affected})
            )
            if not scope_affected_valid:
                audit.add(
                    "audit_incomplete",
                    "bounded_affected_intents_missing",
                    "bounded_change revision_scope requires a nonempty, duplicate-free affected_intent_ids list anchored in frozen author intent.",
                )
            if not classification_affected_valid:
                audit.add(
                    "audit_incomplete",
                    "bounded_classification_affected_intents_invalid",
                    "bounded_change task_classification requires a nonempty, duplicate-free affected_intent_ids list.",
                )
            if scope_affected_valid and classification_affected_valid:
                scope_affected_set = {
                    value.strip() for value in affected_intents
                }
                classification_affected_set = {
                    value.strip() for value in classification_affected
                }
                if scope_affected_set != classification_affected_set:
                    audit.add(
                        "audit_incomplete",
                        "bounded_affected_intents_mismatch",
                        "task_classification.affected_intent_ids must exactly equal revision_scope.affected_intent_ids as a set.",
                        task_classification_ids=sorted(
                            classification_affected_set
                        ),
                        revision_scope_ids=sorted(scope_affected_set),
                    )
                try:
                    authoritative_records = qa_preparer.extract_obligations(
                        author, {}, {}
                    )
                    authoritative_intent_ids = {
                        str(
                            item.get("intent_id")
                            or item.get("obligation_id")
                            or item.get("id")
                        ).strip()
                        for item in authoritative_records
                        if isinstance(item, dict)
                        and (
                            item.get("intent_id")
                            or item.get("obligation_id")
                            or item.get("id")
                        )
                    }
                except Exception as exc:
                    authoritative_intent_ids = set()
                    audit.add(
                        "audit_incomplete",
                        "bounded_author_intent_replay_failed",
                        "Cannot replay the frozen author-owned intent universe for bounded QA.",
                        error=str(exc),
                    )
                unknown_affected = sorted(
                    scope_affected_set - authoritative_intent_ids
                )
                if unknown_affected:
                    audit.add(
                        "audit_incomplete",
                        "bounded_affected_intent_unknown",
                        "Every bounded affected_intent_id must belong to the frozen author-intent authority.",
                        unknown_intent_ids=unknown_affected,
                    )
            if scope_affected_valid:
                affected_set = {value.strip() for value in affected_intents}
                omitted_intent_units = sorted(
                    unit.get("unit_id")
                    for unit in units
                    if bool(unit.get("review_target", True))
                    and affected_set
                    & {
                        value
                        for value in as_list(unit.get("intent_ids"))
                        if isinstance(value, str)
                    }
                    and not is_review_target(unit)
                )
                if omitted_intent_units:
                    audit.add(
                        "audit_incomplete",
                        "bounded_affected_intent_scope_incomplete",
                        "Every manifest unit carrying an affected intent must be selected for bounded review.",
                        unit_ids=omitted_intent_units,
                    )

                selected_units = [
                    unit
                    for unit in units
                    if bool(unit.get("review_target", True))
                    and is_review_target(unit)
                ]
                selected_ids = {
                    str(unit.get("unit_id")) for unit in selected_units
                }
                review_targets = {
                    str(unit.get("unit_id")): unit
                    for unit in units
                    if bool(unit.get("review_target", True))
                }
                required_closure = set(selected_ids)
                required_closure.update(
                    unit_id
                    for unit_id, unit in review_targets.items()
                    if affected_set
                    & {
                        value
                        for value in as_list(unit.get("intent_ids"))
                        if isinstance(value, str)
                    }
                )
                changed_closure = True
                while changed_closure:
                    changed_closure = False
                    active = [
                        review_targets[unit_id]
                        for unit_id in required_closure
                        if unit_id in review_targets
                    ]
                    active_paragraphs = {
                        str(unit.get("paragraph_id"))
                        for unit in active
                        if nonempty(unit.get("paragraph_id"))
                    }
                    active_intents = {
                        value
                        for unit in active
                        for value in as_list(unit.get("intent_ids"))
                        if isinstance(value, str) and value
                    }
                    active_definitions = {
                        value
                        for unit in active
                        for value in as_list(unit.get("definition_ids"))
                        if isinstance(value, str) and value
                    }
                    active_dependencies = {
                        value
                        for unit in active
                        for value in as_list(unit.get("dependency_unit_ids"))
                        if isinstance(value, str) and value
                    }
                    active_parents = {
                        str(unit.get("parent_id"))
                        for unit in active
                        if nonempty(unit.get("parent_id"))
                    }
                    additions: set[str] = set(active_dependencies)
                    for unit_id, unit in review_targets.items():
                        unit_intents = {
                            value
                            for value in as_list(unit.get("intent_ids"))
                            if isinstance(value, str) and value
                        }
                        unit_definitions = {
                            value
                            for value in as_list(unit.get("definition_ids"))
                            if isinstance(value, str) and value
                        }
                        unit_dependencies = {
                            value
                            for value in as_list(unit.get("dependency_unit_ids"))
                            if isinstance(value, str) and value
                        }
                        if (
                            str(unit.get("paragraph_id")) in active_paragraphs
                            or bool(unit_intents & active_intents)
                            or bool(unit_definitions & active_definitions)
                            or bool(unit_dependencies & required_closure)
                            or str(unit.get("parent_id")) in active_parents
                            or unit_id in active_parents
                        ):
                            additions.add(unit_id)
                    additions &= set(review_targets)
                    if not additions.issubset(required_closure):
                        required_closure.update(additions)
                        changed_closure = True
                missing_closure = sorted(required_closure - selected_ids)
                if missing_closure:
                    audit.add(
                        "audit_incomplete",
                        "bounded_dependency_closure_incomplete",
                        "Bounded scope must include the recomputed paragraph, intent, definition, dependency, and parent/child closure.",
                        unit_ids=missing_closure,
                    )
        required_classification_fields = (
            "task_stage",
            "qa_mode",
            "basis",
            "changed_artifact_or_source_ranges",
            "substantive_dependencies_checked",
            "affected_intent_ids",
            "classified_by",
            "classified_at",
        )
        if not classification:
            missing_classification = list(required_classification_fields)
        else:
            missing_classification = [
                field_name
                for field_name in required_classification_fields
                if field_name != "substantive_dependencies_checked"
                and not nonempty(classification.get(field_name))
            ]
            if "substantive_dependencies_checked" not in classification:
                missing_classification.append("substantive_dependencies_checked")
        if missing_classification:
            audit.add(
                "audit_incomplete",
                "bounded_task_classification_incomplete",
                "bounded_change requires a recoverable task_classification record.",
                missing_fields=missing_classification,
            )
        if isinstance(classification, dict) and isinstance(expected_scope, dict):
            task_stage = str(classification.get("task_stage", "")).strip().lower()
            classification_mode = str(classification.get("qa_mode", "")).strip().lower()
            if task_stage not in {"local_edit", "local_polish"}:
                audit.add(
                    "audit_incomplete",
                    "bounded_task_stage_invalid",
                    "bounded_change task_classification.task_stage must be local_edit or local_polish.",
                    task_stage=task_stage or None,
                )
            if classification_mode != expected_mode:
                audit.add(
                    "audit_incomplete",
                    "bounded_classification_mode_mismatch",
                    "task_classification.qa_mode must exactly match qa_contract.qa_mode.",
                    classification_qa_mode=classification_mode or None,
                    contract_qa_mode=expected_mode,
                )
            classified_changes = as_list(
                classification.get("changed_artifact_or_source_ranges")
            )
            changed_selector_keys = [
                key
                for key in ("changed_unit_ids", "changed_source_ranges")
                if nonempty(expected_scope.get(key))
            ]
            dependency_selector_keys = [
                key
                for key in ("dependency_unit_ids", "dependency_source_ranges")
                if key in expected_scope
            ]
            if len(changed_selector_keys) != 1 or len(dependency_selector_keys) != 1:
                audit.add(
                    "audit_incomplete",
                    "bounded_selector_types_invalid",
                    "bounded_change requires exactly one changed selector type and one explicit dependency selector type.",
                    changed_selector_keys=changed_selector_keys,
                    dependency_selector_keys=dependency_selector_keys,
                )
            target_by_id = {
                str(unit.get("unit_id")): unit
                for unit in units
                if bool(unit.get("review_target", True))
            }

            def selector_range_matches(raw_range: Any) -> set[str] | None:
                if not isinstance(raw_range, dict):
                    return None
                raw_path = raw_range.get("path")
                start_line = raw_range.get("start_line")
                end_line = raw_range.get("end_line")
                if (
                    not isinstance(raw_path, str)
                    or not raw_path.strip()
                    or isinstance(start_line, bool)
                    or not isinstance(start_line, int)
                    or isinstance(end_line, bool)
                    or not isinstance(end_line, int)
                    or start_line < 1
                    or end_line < start_line
                ):
                    return None
                normalized_path = Path(raw_path).as_posix().lstrip("./")
                matches: set[str] = set()
                for unit_id, unit in target_by_id.items():
                    raw_spans = unit.get("source_spans")
                    if not isinstance(raw_spans, list):
                        raw_spans = [unit.get("source")]
                    for span in raw_spans:
                        if not isinstance(span, dict):
                            continue
                        span_path = span.get("path")
                        span_start = span.get("start_line")
                        span_end = span.get("end_line")
                        if (
                            not isinstance(span_path, str)
                            or isinstance(span_start, bool)
                            or not isinstance(span_start, int)
                            or isinstance(span_end, bool)
                            or not isinstance(span_end, int)
                        ):
                            continue
                        if (
                            Path(span_path).as_posix().lstrip("./")
                            == normalized_path
                            and start_line <= span_end
                            and span_start <= end_line
                        ):
                            matches.add(unit_id)
                return matches

            for selector_key in [*changed_selector_keys, *dependency_selector_keys]:
                selector_values = as_list(expected_scope.get(selector_key))
                for selector in selector_values:
                    if selector_key.endswith("unit_ids"):
                        valid_selector = (
                            isinstance(selector, str)
                            and selector in target_by_id
                        )
                        matched_ids = {selector} if valid_selector else set()
                    else:
                        range_matches = selector_range_matches(selector)
                        valid_selector = bool(range_matches)
                        matched_ids = range_matches or set()
                    if not valid_selector:
                        audit.add(
                            "audit_incomplete",
                            "bounded_selector_invalid",
                            "Every bounded selector must independently resolve to at least one known review target.",
                            selector_type=selector_key,
                            selector=selector,
                        )
                        continue
                    omitted_matches = sorted(
                        unit_id
                        for unit_id in matched_ids
                        if not is_review_target(target_by_id[unit_id])
                    )
                    if omitted_matches:
                        audit.add(
                            "audit_incomplete",
                            "bounded_selector_seed_unselected",
                            "Every unit matched by an explicit bounded selector must be selected.",
                            selector_type=selector_key,
                            unit_ids=omitted_matches,
                        )
            scoped_changes = (
                as_list(expected_scope.get(changed_selector_keys[0]))
                if len(changed_selector_keys) == 1
                else []
            )
            classified_keys = {canonical_hash(normalized_slot(item)) for item in classified_changes}
            scoped_keys = {canonical_hash(normalized_slot(item)) for item in scoped_changes}
            if classified_keys != scoped_keys:
                audit.add(
                    "audit_incomplete",
                    "bounded_changed_scope_mismatch",
                    "task_classification changed selectors must exactly equal revision_scope changed selectors.",
                )
            checked_dependencies = classification.get("substantive_dependencies_checked")
            scoped_dependencies = (
                as_list(expected_scope.get(dependency_selector_keys[0]))
                if len(dependency_selector_keys) == 1
                else []
            )
            if isinstance(checked_dependencies, (list, str)):
                checked_keys = {
                    canonical_hash(normalized_slot(item))
                    for item in as_list(checked_dependencies)
                }
                dependency_keys = {
                    canonical_hash(normalized_slot(item))
                    for item in scoped_dependencies
                }
                if checked_keys != dependency_keys:
                    audit.add(
                        "audit_incomplete",
                        "bounded_dependency_scope_mismatch",
                        "task_classification dependencies must exactly equal revision_scope dependency selectors.",
                    )
            else:
                audit.add(
                    "audit_incomplete",
                    "bounded_dependency_check_invalid",
                    "substantive_dependencies_checked must be an explicit list or string selector record.",
                )

    raw_expected_roles = qa_contract.get(
        "required_roles", list(REQUIRED_SEMANTIC_ROLES)
    )
    if isinstance(raw_expected_roles, str):
        raw_expected_roles = [raw_expected_roles]
    expected_roles = {
        role
        for role in (
            normalize_role(value)
            for value in raw_expected_roles
        )
        if role
    } if isinstance(raw_expected_roles, list) else set()
    raw_manifest_roles = manifest.get("roles")
    if isinstance(raw_manifest_roles, dict):
        manifest_roles = {
            role for role in (normalize_role(value) for value in raw_manifest_roles) if role
        }
    elif isinstance(raw_manifest_roles, list):
        manifest_roles = {
            role for role in (normalize_role(value) for value in raw_manifest_roles) if role
        }
    else:
        manifest_roles = set()
    if not expected_roles:
        audit.add(
            "audit_incomplete",
            "qa_contract_roles_invalid",
            "qa_contract.required_roles must contain at least one usable role.",
        )
    missing_required_roles = set(REQUIRED_SEMANTIC_ROLES) - expected_roles
    if missing_required_roles:
        audit.add(
            "audit_incomplete",
            "qa_contract_semantic_roles_missing",
            "qa_contract.required_roles must include all four fixed semantic QA roles.",
            missing_roles=sorted(missing_required_roles),
        )
    if manifest_roles != expected_roles:
        audit.add(
            "audit_incomplete",
            "qa_required_roles_manifest_mismatch",
            "Manifest role universe does not match qa_contract.required_roles.",
            missing_roles=sorted(expected_roles - manifest_roles),
            unexpected_roles=sorted(manifest_roles - expected_roles),
        )
    try:
        canonical_role_order = qa_preparer.role_list(qa_contract)
    except Exception:
        canonical_role_order = [
            normalize_role(value)
            for value in raw_expected_roles
            if normalize_role(value)
        ] if isinstance(raw_expected_roles, list) else []
    expected_review_policy = {
        "minimum_high_risk_independent_reviews": high_risk_minimum,
        "required_semantic_roles": canonical_role_order,
    }
    if (
        not high_risk_minimum_valid
        or canonical_hash(manifest.get("review_policy"))
        != canonical_hash(expected_review_policy)
    ):
        audit.add(
            "audit_incomplete",
            "manifest_review_policy_mismatch",
            "manifest.review_policy must exactly reproduce the live canonical high-risk minimum and semantic-role order.",
            expected_review_policy=expected_review_policy,
        )
    for unit in units:
        unknown = {
            role
            for role in (
                normalize_role(value) for value in as_list(unit.get("required_roles"))
            )
            if role and role not in expected_roles
        }
        if unknown:
            audit.add(
                "audit_incomplete",
                "unit_role_outside_qa_contract",
                "Unit routing names roles absent from qa_contract.required_roles.",
                unit_id=unit["unit_id"],
                unexpected_roles=sorted(unknown),
            )
        risk = unit.get("risk") if isinstance(unit.get("risk"), dict) else {}
        high_risk = bool(
            unit.get(
                "high_risk",
                unit.get("is_high_risk", risk.get("is_high_risk", False)),
            )
        )
        if high_risk:
            raw_unit_minimum = unit.get("min_independent_reviews")
            if (
                isinstance(raw_unit_minimum, bool)
                or not isinstance(raw_unit_minimum, int)
                or raw_unit_minimum < high_risk_minimum
            ):
                audit.add(
                    "audit_incomplete",
                    "high_risk_unit_review_minimum_invalid",
                    "Every high-risk manifest unit must carry an integer min_independent_reviews no lower than the canonical QA-contract minimum.",
                    unit_id=unit.get("unit_id"),
                    required_minimum=high_risk_minimum,
                    recorded_minimum=raw_unit_minimum,
                )
    for packet in as_list(manifest.get("packets")):
        if isinstance(packet, dict):
            role = normalize_role(packet.get("role"))
            if role and role not in expected_roles:
                audit.add(
                    "audit_incomplete",
                    "packet_role_outside_qa_contract",
                    "Packet role is absent from qa_contract.required_roles.",
                    packet_id=packet.get("packet_id"),
                    role=role,
                )
    if expected_mode == "exhaustive":
        omitted = sorted(
            unit["unit_id"]
            for unit in units
            if bool(unit.get("review_target", True))
            and unit.get("selected_for_review", True) is False
        )
        if omitted:
            audit.add(
                "audit_incomplete",
                "exhaustive_review_target_omitted",
                "Exhaustive QA cannot deselect a review-target unit.",
                unit_ids=omitted,
            )
    return expected_mode


def required_roles_by_unit(
    manifest: dict[str, Any], units: list[dict[str, Any]], audit: GateAudit
) -> tuple[set[str], dict[str, set[str]]]:
    global_roles: set[str] = set()
    raw_roles = manifest.get("roles")
    if isinstance(raw_roles, dict):
        for raw_role, settings in raw_roles.items():
            if not isinstance(settings, dict) or settings.get("required", True):
                role = normalize_role(raw_role)
                if role:
                    global_roles.add(role)
    elif isinstance(raw_roles, list):
        global_roles.update(filter(None, (normalize_role(value) for value in raw_roles)))

    qa_contract = first_present(
        manifest,
        (("contracts", "qa_contract", "payload"), ("qa_contract",)),
    )
    if isinstance(qa_contract, dict):
        global_roles.update(
            filter(None, (normalize_role(value) for value in as_list(qa_contract.get("required_roles"))))
        )

    packet_roles: dict[str, set[str]] = defaultdict(set)
    packets = manifest.get("packets", [])
    if isinstance(packets, list):
        for packet in packets:
            if not isinstance(packet, dict):
                audit.add(
                    "audit_incomplete",
                    "packet_invalid",
                    "Every packet entry must be an object.",
                )
                continue
            role = normalize_role(packet.get("role"))
            for unit_id in as_list(packet.get("unit_ids")):
                if isinstance(unit_id, str) and role:
                    packet_roles[unit_id].add(role)

    required: dict[str, set[str]] = {}
    fixed_roles = set(REQUIRED_SEMANTIC_ROLES)
    for unit in units:
        unit_id = unit["unit_id"]
        if not is_review_target(unit):
            required[unit_id] = set()
            continue
        explicit = set(
            filter(None, (normalize_role(value) for value in as_list(unit.get("required_roles"))))
        )
        if explicit != fixed_roles:
            audit.add(
                "audit_incomplete",
                "unit_required_roles_invalid",
                "Every selected v1 review target must declare exactly the fixed four semantic roles.",
                unit_id=unit_id,
                expected_roles=sorted(fixed_roles),
                declared_roles=sorted(explicit),
            )
        roles = set(fixed_roles)
        required[unit_id] = roles
        global_roles.update(roles)
        if unit.get("reader_visible", True) and not roles:
            audit.add(
                "audit_incomplete",
                "required_roles_missing",
                "Reader-visible unit has no required reviewer role assignment.",
                unit_id=unit_id,
            )
    if not any(is_review_target(unit) for unit in units):
        audit.add(
            "audit_incomplete",
            "review_target_missing",
            "Manifest selects no review-target unit.",
        )
    if not global_roles:
        audit.add(
            "audit_incomplete",
            "qa_roles_missing",
            "Manifest does not define any required semantic-review roles.",
        )
    return global_roles, required


def derive_expected_packet_contract_context(
    contract_path: Path,
    qa_contract_path: Path | None,
    artifact_contract_path: Path | None,
    author: dict[str, Any],
    qa_contract: dict[str, Any],
    artifact_contract: dict[str, Any],
    manifest: dict[str, Any],
    evidence_view: dict[str, Any],
    audit: GateAudit,
) -> dict[str, Any] | None:
    """Rebuild the packet authority context from live, hash-bound inputs."""

    if qa_preparer is None or qa_contract_path is None:
        audit.add(
            "audit_incomplete",
            "packet_context_derivation_unavailable",
            "Packet context cannot be verified without the co-shipped preparation module and live QA contract.",
        )
        return None
    try:
        live_author, _, intent_state = qa_preparer.load_contract(
            contract_path, "author_intent_contract"
        )
        live_qa, _, qa_state = qa_preparer.load_contract(
            qa_contract_path, "qa_contract"
        )
        if artifact_contract_path is not None:
            live_artifact, _, artifact_state = qa_preparer.load_contract(
                artifact_contract_path, "artifact_contract"
            )
        else:
            live_artifact, artifact_state = None, {}
        paper_state = qa_preparer.merge_paper_state_contexts(
            intent_state, qa_state, artifact_state
        )
        qa_preparer.validate_author_intent_for_preparation(
            live_author,
            paper_state,
            contract_path,
            sha256_file(contract_path),
        )
        obligations = qa_preparer.extract_obligations(
            live_author, live_qa, paper_state
        )
        definitions = qa_preparer.extract_definitions(
            live_author, live_qa, paper_state
        )
        baseline_ledger = qa_preparer.conservation_ledger_entries(
            live_qa, live_artifact, paper_state
        )
        expected = qa_preparer.contract_context(
            live_author,
            live_qa,
            paper_state,
            live_artifact,
            obligations,
            definitions,
            baseline_ledger,
            evidence_view.get("records", []),
        )
    except Exception as exc:  # fail closed on preparation-schema drift
        reason_code = str(getattr(exc, "reason_code", "")).strip()
        blocked_status = str(getattr(exc, "status", "")).strip()
        if blocked_status in {"clarification_required", "evidence_conflict"}:
            if not any(
                finding.get("code") == reason_code
                for finding in audit.findings
            ):
                audit.add(
                    blocked_status,
                    reason_code or "packet_context_prerequisite_blocked",
                    "Live author-intent prerequisites block reviewer-packet context derivation.",
                    error=str(exc),
                )
            return None
        audit.add(
            "audit_incomplete",
            reason_code or "packet_context_derivation_failed",
            "Cannot deterministically rebuild reviewer packet authority context from live inputs.",
            error=str(exc),
        )
        return None
    if (
        canonical_hash(live_author) != canonical_hash(author)
        or canonical_hash(live_qa) != canonical_hash(qa_contract)
        or canonical_hash(live_artifact or {}) != canonical_hash(artifact_contract)
    ):
        audit.add(
            "audit_incomplete",
            "packet_context_live_contract_mismatch",
            "Packet-context derivation disagrees with the already verified live contract views.",
        )
    projections = {
        "content_obligations": obligations,
        "definition_registry": definitions,
        "content_conservation_ledger": baseline_ledger,
        "evidence_registry": evidence_view.get("records", []),
    }
    mismatched = [
        key
        for key, value in projections.items()
        if canonical_hash(manifest.get(key)) != canonical_hash(value)
    ]
    if mismatched:
        audit.add(
            "audit_incomplete",
            "manifest_contract_projection_mismatch",
            "Manifest contract projections must exactly equal values derived from live governing contracts.",
            mismatched_fields=mismatched,
        )
    return expected


def validate_packets(
    manifest: dict[str, Any],
    manifest_path: Path,
    manuscript_hash: str,
    content_hash: str,
    contract_hash: str,
    qa_contract_hash: str,
    artifact_contract_hash: str,
    artifact_contract: dict[str, Any],
    qa_contract: dict[str, Any],
    authority_binding: dict[str, Any],
    expected_contract_context: dict[str, Any] | None,
    evidence_view: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    required_by_unit: dict[str, set[str]],
    formula_registry_hash: str,
    formulas_by_id: dict[str, dict[str, Any]],
    audit: GateAudit,
) -> dict[str, dict[str, Any]]:
    raw_packets = manifest.get("packets")
    if not isinstance(raw_packets, list) or not raw_packets:
        audit.add(
            "audit_incomplete",
            "packet_manifest_missing",
            "QA manifest must record at least one reviewer packet.",
        )
        return {}
    manifest_id = manifest.get("manifest_id")
    raw_unit_limit = qa_contract.get(
        "max_units_per_packet", MAX_UNITS_PER_PACKET_CEILING
    )
    raw_byte_limit = qa_contract.get(
        "max_packet_bytes", MAX_PACKET_BYTES_CEILING
    )
    limits_valid = (
        not isinstance(raw_unit_limit, bool)
        and isinstance(raw_unit_limit, int)
        and 1 <= raw_unit_limit <= MAX_UNITS_PER_PACKET_CEILING
        and not isinstance(raw_byte_limit, bool)
        and isinstance(raw_byte_limit, int)
        and MIN_PACKET_BYTES <= raw_byte_limit <= MAX_PACKET_BYTES_CEILING
    )
    if not limits_valid:
        audit.add(
            "audit_incomplete",
            "packet_budget_contract_invalid",
            "QA packet limits must stay within the v1 ceilings of 25 targets and 240000 UTF-8 JSON bytes.",
            max_units_per_packet=raw_unit_limit,
            max_packet_bytes=raw_byte_limit,
        )
    unit_limit = (
        raw_unit_limit
        if isinstance(raw_unit_limit, int) and not isinstance(raw_unit_limit, bool)
        else MAX_UNITS_PER_PACKET_CEILING
    )
    byte_limit = (
        raw_byte_limit
        if isinstance(raw_byte_limit, int) and not isinstance(raw_byte_limit, bool)
        else MAX_PACKET_BYTES_CEILING
    )
    packetization = manifest.get("packetization")
    if (
        not isinstance(packetization, dict)
        or packetization.get("max_units_per_packet") != raw_unit_limit
        or packetization.get("max_packet_bytes") != raw_byte_limit
        or packetization.get("packet_count") != len(raw_packets)
    ):
        audit.add(
            "audit_incomplete",
            "packetization_manifest_invalid",
            "Manifest packetization must exactly bind the live QA limits and packet count.",
        )
    by_packet: dict[str, dict[str, Any]] = {}
    packet_ids: set[str] = set()
    assignments: dict[tuple[str, str], list[str]] = defaultdict(list)
    role_batches: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for record in raw_packets:
        if not isinstance(record, dict):
            audit.add("audit_incomplete", "packet_record_invalid", "Packet record must be an object.")
            continue
        packet_id = record.get("packet_id")
        role = normalize_role(record.get("role"))
        raw_path = record.get("path")
        expected_hash = normalized_sha(record.get("packet_sha256"))
        unit_ids = record.get("unit_ids")
        batch_index = record.get("batch_index")
        batch_count = record.get("batch_count")
        recorded_packet_bytes = record.get("packet_bytes")
        if (
            not isinstance(packet_id, str)
            or not packet_id
            or not role
            or not isinstance(raw_path, str)
            or not expected_hash
            or not isinstance(unit_ids, list)
            or not unit_ids
            or not all(isinstance(value, str) for value in unit_ids)
            or isinstance(batch_index, bool)
            or not isinstance(batch_index, int)
            or isinstance(batch_count, bool)
            or not isinstance(batch_count, int)
            or batch_index < 1
            or batch_count < 1
            or isinstance(recorded_packet_bytes, bool)
            or not isinstance(recorded_packet_bytes, int)
            or recorded_packet_bytes < 1
        ):
            audit.add(
                "audit_incomplete",
                "packet_record_invalid",
                "Packet record requires packet_id, role, path, packet_sha256, and unit_ids.",
                packet_id=packet_id,
            )
            continue
        if len(unit_ids) > unit_limit:
            audit.add(
                "audit_incomplete",
                "packet_target_budget_exceeded",
                "Reviewer packet exceeds the live target-count limit.",
                packet_id=packet_id,
                target_count=len(unit_ids),
                max_units_per_packet=unit_limit,
            )
        role_batches[role].append((batch_index, batch_count))
        if packet_id in packet_ids:
            audit.add(
                "audit_incomplete",
                "packet_identity_duplicate",
                "Packet IDs must be unique; a role may have multiple deterministic batches.",
                packet_id=packet_id,
                role=role,
            )
            continue
        packet_ids.add(packet_id)
        path = Path(raw_path).expanduser()
        if not path.is_absolute():
            path = manifest_path.parent / path
        path = path.resolve()
        payload = load_json_object(path, audit, "review packet") if path.is_file() else None
        if payload is None:
            if not path.is_file():
                audit.add(
                    "audit_incomplete",
                    "packet_file_missing",
                    "Reviewer packet file is missing.",
                    path=str(path),
                    packet_id=packet_id,
                )
            continue
        actual_packet_bytes = path.stat().st_size
        if (
            recorded_packet_bytes != actual_packet_bytes
            or actual_packet_bytes > byte_limit
        ):
            audit.add(
                "audit_incomplete",
                "packet_byte_budget_invalid",
                "Packet byte count must equal the live file size and stay within the live UTF-8 JSON byte limit.",
                packet_id=packet_id,
                recorded_packet_bytes=recorded_packet_bytes,
                actual_packet_bytes=actual_packet_bytes,
                max_packet_bytes=byte_limit,
            )
        if payload.get("schema_version") != SCHEMA_VERSION:
            audit.add(
                "audit_incomplete",
                "packet_schema_invalid",
                "Reviewer packet schema_version must be 1.0.",
                path=str(path),
            )
        if payload.get("schema_id") != "qa-audit-packet/1.0":
            audit.add(
                "audit_incomplete",
                "packet_schema_identity_invalid",
                "Reviewer packet must use schema_id=qa-audit-packet/1.0.",
                path=str(path),
                packet_id=packet_id,
            )
        scope = dict(payload)
        embedded_hash = normalized_sha(scope.pop("packet_sha256", None))
        actual_scope_hash = canonical_hash(scope)
        if expected_hash != actual_scope_hash or embedded_hash != actual_scope_hash:
            audit.add(
                "audit_incomplete",
                "packet_hash_stale",
                "Packet canonical scope hash does not match packet file and manifest record.",
                packet_id=packet_id,
                expected_sha256=expected_hash,
                actual_sha256=actual_scope_hash,
            )
        checks = {
            "packet_id": packet_id,
            "manifest_id": manifest_id,
            "role": role,
            "manuscript_sha256": manuscript_hash,
            "contract_sha256": contract_hash,
            "qa_contract_sha256": qa_contract_hash,
            "batch_index": batch_index,
            "batch_count": batch_count,
        }
        for field_name, expected in checks.items():
            actual = normalize_role(payload.get(field_name)) if field_name == "role" else payload.get(field_name)
            if actual != expected:
                audit.add(
                    "audit_incomplete",
                    "packet_binding_mismatch",
                    "Packet identity, role, or contract/manuscript hash does not match its manifest.",
                    packet_id=packet_id,
                    field=field_name,
                )
        expected_protocol = ROLE_PROTOCOLS.get(role)
        expected_protocol_hash = (
            canonical_hash(expected_protocol)
            if isinstance(expected_protocol, dict)
            else ""
        )
        expected_required_checks = (
            expected_protocol.get("required_criterion_ids", [])
            if isinstance(expected_protocol, dict)
            else []
        )
        if (
            record.get("role_protocol_version") != ROLE_PROTOCOL_VERSION
            or normalized_sha(record.get("role_protocol_sha256"))
            != expected_protocol_hash
            or record.get("required_checks") != expected_required_checks
            or payload.get("role_protocol_version") != ROLE_PROTOCOL_VERSION
            or normalized_sha(payload.get("role_protocol_sha256"))
            != expected_protocol_hash
            or payload.get("required_checks") != expected_required_checks
            or canonical_hash(payload.get("role_protocol"))
            != canonical_hash(expected_protocol)
        ):
            audit.add(
                "audit_incomplete",
                "packet_role_protocol_invalid",
                "Packet and manifest record must bind the fixed role protocol and exact required-check list.",
                packet_id=packet_id,
                role=role,
            )
        packet_content_hash = normalized_sha(
            payload.get("content_sha256", payload.get("expanded_manuscript_sha256"))
        )
        if not packet_content_hash or packet_content_hash != content_hash:
            audit.add(
                "audit_incomplete",
                "packet_content_hash_mismatch",
                "Packet content hash differs from the manifest.",
                packet_id=packet_id,
            )
        if artifact_contract_hash:
            if normalized_sha(payload.get("artifact_contract_sha256")) != artifact_contract_hash:
                audit.add(
                    "audit_incomplete",
                    "packet_artifact_contract_hash_mismatch",
                    "Packet lacks the current artifact-contract SHA-256.",
                    packet_id=packet_id,
                )
        if canonical_hash(payload.get("artifact_contract") or {}) != canonical_hash(
            artifact_contract or {}
        ):
            audit.add(
                "audit_incomplete",
                "packet_artifact_contract_body_mismatch",
                "Reviewer packet must contain the exact live artifact-contract body, not merely its declared SHA-256.",
                packet_id=packet_id,
            )
        if expected_contract_context is not None and canonical_hash(
            payload.get("contract_context")
        ) != canonical_hash(expected_contract_context):
            audit.add(
                "audit_incomplete",
                "packet_contract_context_invalid",
                "Reviewer packet contract_context must exactly equal the context derived from live author, QA, artifact, and evidence authorities.",
                packet_id=packet_id,
            )
        expected_evidence_source = evidence_view.get("source")
        expected_evidence_hash = str(evidence_view.get("sha256", ""))
        if (
            normalized_sha(payload.get("evidence_registry_sha256"))
            != expected_evidence_hash
            or canonical_hash(payload.get("evidence_registry_source"))
            != canonical_hash(expected_evidence_source)
        ):
            audit.add(
                "audit_incomplete",
                "packet_evidence_registry_binding_invalid",
                "Reviewer packet must bind the exact live evidence-registry source, hash, and record projection.",
                packet_id=packet_id,
            )
        if authority_binding:
            packet_authority = payload.get("author_intent_authority_source")
            if not isinstance(packet_authority, dict):
                packet_authority = payload.get("authority_source")
            if not isinstance(packet_authority, dict):
                packet_authority = nested(payload, "contract_context", "authority_source")
            packet_confirmation = (
                packet_authority.get("adapter_confirmation")
                if isinstance(packet_authority, dict)
                else None
            )
            if (
                not isinstance(packet_authority, dict)
                or packet_authority.get("path") != authority_binding["path"]
                or normalized_sha(packet_authority.get("sha256"))
                != authority_binding["sha256"]
                or normalized_sha(
                    packet_authority.get("qa_view_projection_sha256")
                )
                != authority_binding["qa_view_projection_sha256"]
                or not isinstance(packet_confirmation, dict)
                or canonical_hash(packet_confirmation)
                != canonical_hash(authority_binding["adapter_confirmation"])
            ):
                audit.add(
                    "audit_incomplete",
                    "packet_authority_projection_binding_missing",
                    "Adapter-backed packet must include the exact authority source and confirmation.",
                    packet_id=packet_id,
                )
        packet_units = payload.get("units")
        payload_unit_ids = [
            item.get("unit_id")
            for item in packet_units
            if isinstance(item, dict)
        ] if isinstance(packet_units, list) else []
        if payload_unit_ids != unit_ids or any(value not in by_id for value in unit_ids):
            audit.add(
                "audit_incomplete",
                "packet_unit_scope_mismatch",
                "Packet unit scope differs from the manifest record or references unknown units.",
                packet_id=packet_id,
            )
        elif any(
            canonical_hash(packet_unit)
            != canonical_hash(
                {
                    key: value
                    for key, value in by_id[packet_unit["unit_id"]].items()
                    if key != "_order"
                }
            )
            for packet_unit in packet_units
            if isinstance(packet_unit, dict) and packet_unit.get("unit_id") in by_id
        ):
            audit.add(
                "audit_incomplete",
                "packet_unit_content_stale",
                "Packet unit content or routing fields differ from the current manifest.",
                packet_id=packet_id,
            )
        packet_formula_ids: set[str] = set()
        for unit_id in unit_ids:
            unit = by_id.get(unit_id, {})
            packet_formula_ids.update(
                value
                for value in as_list(unit.get("formula_ids"))
                if isinstance(value, str) and value
            )
            packet_formula_ids.update(referenced_formula_ids(unit.get("context")))
            packet_formula_ids.update(referenced_formula_ids(unit.get("text")))
        expected_formula_context = [
            record
            for formula_id, record in formulas_by_id.items()
            if formula_id in packet_formula_ids
        ]
        if (
            normalized_sha(payload.get("formula_registry_sha256"))
            != formula_registry_hash
            or canonical_hash(payload.get("formula_context"))
            != canonical_hash(expected_formula_context)
            or packet_formula_ids - set(formulas_by_id)
        ):
            audit.add(
                "audit_incomplete",
                "packet_formula_context_invalid",
                "Packet must bind the global formula registry and include the exact formula subset referenced by its units and context.",
                packet_id=packet_id,
            )
        for unit_id in unit_ids:
            if unit_id in by_id:
                assignments[(unit_id, role)].append(packet_id)
                if not is_review_target(by_id[unit_id]):
                    audit.add(
                        "audit_incomplete",
                        "packet_contains_unselected_unit",
                        "Reviewer packet contains a unit outside the selected review scope.",
                        packet_id=packet_id,
                        unit_id=unit_id,
                    )
                if role not in required_by_unit.get(unit_id, set()):
                    audit.add(
                        "audit_incomplete",
                        "packet_unit_role_unassigned",
                        "Reviewer packet assigns a role not required for that unit.",
                        packet_id=packet_id,
                        unit_id=unit_id,
                        role=role,
                    )
        by_packet[packet_id] = {
            "packet_id": packet_id,
            "packet_sha256": expected_hash,
            "role": role,
            "unit_ids": set(unit_ids),
            "required_checks": set(expected_required_checks),
            "path": str(path),
        }
    for unit_id, roles in required_by_unit.items():
        if unit_id not in by_id or not is_review_target(by_id[unit_id]):
            continue
        for role in roles:
            batch_ids = assignments.get((unit_id, role), [])
            if len(batch_ids) != 1:
                audit.add(
                    "audit_incomplete",
                    "packet_unit_role_coverage_invalid",
                    "Every selected unit-role assignment must appear in exactly one packet batch.",
                    unit_id=unit_id,
                    role=role,
                    packet_ids=batch_ids,
                )
    for role, batches in role_batches.items():
        declared_counts = {count for _, count in batches}
        indices = sorted(index for index, _ in batches)
        expected = list(range(1, len(batches) + 1))
        if declared_counts != {len(batches)} or indices != expected:
            audit.add(
                "audit_incomplete",
                "packet_batch_sequence_invalid",
                "Each role's packet batches must have one consistent batch_count and contiguous 1-based batch_index values.",
                role=role,
                batches=[{"batch_index": index, "batch_count": count} for index, count in batches],
            )
    return by_packet


def result_hash(payload: dict[str, Any], kind: str) -> str:
    if kind == "manuscript":
        paths = (
            ("manuscript_sha256",),
            ("inputs", "manuscript_sha256"),
            ("inputs", "manuscript", "sha256"),
        )
    elif kind == "contract":
        paths = (
            ("contract_sha256",),
            ("inputs", "contract_sha256"),
            ("inputs", "contract", "sha256"),
        )
    elif kind == "content":
        paths = (
            ("content_sha256",),
            ("expanded_manuscript_sha256",),
            ("inputs", "content_sha256"),
            ("inputs", "manuscript", "expanded_sha256"),
        )
    elif kind == "qa_contract":
        paths = (
            ("qa_contract_sha256",),
            ("inputs", "qa_contract_sha256"),
            ("inputs", "qa_contract", "sha256"),
        )
    elif kind == "artifact_contract":
        paths = (
            ("artifact_contract_sha256",),
            ("inputs", "artifact_contract_sha256"),
            ("inputs", "artifact_contract", "sha256"),
        )
    else:
        return ""
    return normalized_sha(first_present(payload, paths))


def validate_assignment_registry(
    raw_path: str | None,
    manifest_id: str,
    manifest_hash: str,
    content_hash: str,
    packets_by_id: dict[str, dict[str, Any]],
    require_main_text_assignment: bool,
    audit: GateAudit,
) -> tuple[Path | None, str, dict[str, dict[str, Any]], dict[str, Any] | None, bool]:
    """Validate native-agent dispatch records before accepting semantic results."""

    if not isinstance(raw_path, str) or not raw_path.strip():
        audit.add(
            "audit_incomplete",
            "assignment_registry_missing",
            "A filled, hash-bound native-agent assignment registry is required; the prepare-time template is not an assignment.",
        )
        return None, "", {}, None, False
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        audit.add(
            "audit_incomplete",
            "assignment_registry_missing",
            "The native-agent assignment registry does not exist.",
            path=str(path),
        )
        return path, "", {}, None, False
    payload = load_json_object(path, audit, "assignment registry")
    registry_hash = sha256_file(path)
    if payload is None:
        return path, registry_hash, {}, None, False
    valid = require_schema(payload, audit, "Assignment registry", path)
    if (
        payload.get("schema_id") != ASSIGNMENT_SCHEMA_ID
        or str(payload.get("status", "")).strip().lower() != "assigned"
        or payload.get("manifest_id") != manifest_id
        or normalized_sha(payload.get("manifest_sha256")) != manifest_hash
    ):
        audit.add(
            "audit_incomplete",
            "assignment_registry_binding_invalid",
            "Assignment registry must be assigned and bound to the exact manifest ID and byte SHA-256.",
            path=str(path),
        )
        valid = False
    raw_assignments = payload.get("assignments")
    if not isinstance(raw_assignments, list):
        audit.add(
            "audit_incomplete",
            "assignment_registry_records_invalid",
            "Assignment registry requires an assignments array.",
            path=str(path),
        )
        return path, registry_hash, {}, None, False

    packet_assignments: dict[str, dict[str, Any]] = {}
    main_assignment: dict[str, Any] | None = None
    assignment_ids: set[str] = set()
    task_ids: set[str] = set()
    agent_roles: dict[str, set[str]] = defaultdict(set)
    malformed = False
    unexpected_main_assignment = False
    for record in raw_assignments:
        if not isinstance(record, dict):
            malformed = True
            continue
        assignment_id = record.get("assignment_id")
        native_agent_id = record.get("native_agent_id")
        task_id = record.get("task_id")
        assigned_at = record.get("assigned_at")
        if (
            not all(
                isinstance(value, str) and value.strip()
                for value in (assignment_id, native_agent_id, task_id)
            )
            or not valid_iso8601_timestamp(assigned_at)
        ):
            malformed = True
            continue
        assignment_id = assignment_id.strip()
        native_agent_id = native_agent_id.strip()
        task_id = task_id.strip()
        if assignment_id in assignment_ids or task_id in task_ids:
            malformed = True
            continue
        assignment_ids.add(assignment_id)
        task_ids.add(task_id)
        kind = str(record.get("assignment_kind", "")).strip().lower()
        if kind == "main_text_sufficiency":
            role = "main_text_sufficiency_and_conservation"
            if not require_main_text_assignment:
                unexpected_main_assignment = True
                malformed = True
                continue
            if (
                main_assignment is not None
                or record.get("target_id") != "main-text-sufficiency"
                or normalized_sha(record.get("target_sha256")) != content_hash
            ):
                malformed = True
                continue
            main_assignment = dict(record)
            main_assignment["assignment_id"] = assignment_id
            main_assignment["native_agent_id"] = native_agent_id
            main_assignment["task_id"] = task_id
        else:
            packet_id = record.get("packet_id")
            packet = packets_by_id.get(packet_id) if isinstance(packet_id, str) else None
            role = normalize_role(record.get("role"))
            if (
                kind != "semantic_packet"
                or packet is None
                or packet_id in packet_assignments
                or record.get("target_id") != packet_id
                or normalized_sha(record.get("target_sha256"))
                != packet["packet_sha256"]
                or normalized_sha(record.get("packet_sha256"))
                != packet["packet_sha256"]
                or role != packet["role"]
            ):
                malformed = True
                continue
            normalized = dict(record)
            normalized["assignment_id"] = assignment_id
            normalized["native_agent_id"] = native_agent_id
            normalized["task_id"] = task_id
            normalized["role"] = role
            packet_assignments[packet_id] = normalized
        agent_roles[native_agent_id].add(role)

    missing_packets = sorted(set(packets_by_id) - set(packet_assignments))
    extra_or_duplicate_count = len(raw_assignments) - len(packet_assignments) - (
        1 if main_assignment is not None else 0
    )
    reused_agents = sorted(
        agent for agent, roles in agent_roles.items() if len(roles) > 1
    )
    if unexpected_main_assignment:
        audit.add(
            "audit_incomplete",
            "bounded_main_text_assignment_unexpected",
            "Bounded-change QA must not assign the whole-manuscript fifth role.",
            path=str(path),
        )
    if (
        malformed
        or missing_packets
        or extra_or_duplicate_count
        or (require_main_text_assignment and main_assignment is None)
    ):
        audit.add(
            "audit_incomplete",
            "assignment_registry_records_invalid",
            (
                "Registry must contain exactly one valid assignment per semantic packet plus one main-text-sufficiency assignment."
                if require_main_text_assignment
                else "Bounded-change registry must contain exactly one valid assignment per semantic packet and no whole-manuscript fifth-role assignment."
            ),
            path=str(path),
            missing_packet_ids=missing_packets,
            main_text_assignment_present=main_assignment is not None,
            unrecognized_or_duplicate_records=max(0, extra_or_duplicate_count),
        )
        valid = False
    if reused_agents:
        audit.add(
            "audit_incomplete",
            "native_agent_independence_invalid",
            "One native agent cannot serve different semantic roles or the fifth sufficiency role in the same audit.",
            native_agent_ids=reused_agents,
        )
        valid = False
    return path, registry_hash, packet_assignments, main_assignment, valid


def artifact_depth_question_specs(
    artifact_contract: dict[str, Any],
) -> list[dict[str, Any]]:
    """Derive stable fifth-role question identities from the live artifact contract."""

    raw_cards = artifact_contract.get("section_cards")
    cards: list[tuple[str | None, dict[str, Any]]] = []
    if isinstance(raw_cards, list):
        cards = [
            (None, card)
            for card in raw_cards
            if isinstance(card, dict)
        ]
    elif isinstance(raw_cards, dict):
        cards = [
            (str(key), card)
            for key, card in raw_cards.items()
            if isinstance(card, dict)
        ]
    output: list[dict[str, Any]] = []
    for card_index, (mapping_key, card) in enumerate(cards, 1):
        card_id = str(
            card.get("card_id")
            or card.get("section_id")
            or mapping_key
            or f"card-{card_index}"
        ).strip()
        raw_questions = card.get("minimum_depth_questions")
        questions = (
            [raw_questions]
            if isinstance(raw_questions, str)
            else raw_questions
            if isinstance(raw_questions, list)
            else []
        )
        for question_index, question_text in enumerate(questions, 1):
            if not isinstance(question_text, str) or not question_text.strip():
                continue
            question_sha = canonical_hash(
                {
                    "card_id": card_id,
                    "question_index": question_index,
                    "question_text": question_text,
                }
            )
            output.append(
                {
                    "card_id": card_id,
                    "question_index": question_index,
                    "question_text": question_text,
                    "question_sha256": question_sha,
                    "question_id": f"depth-question-{question_sha[:20]}",
                    "section_name": card.get("section_name"),
                    "candidate_section_id": card.get(
                        "candidate_section_id"
                    ),
                    "candidate_section_name": card.get(
                        "candidate_section_name"
                    ),
                    "candidate_section_id_present": (
                        card.get("candidate_section_id") is not None
                    ),
                    "candidate_section_name_present": (
                        card.get("candidate_section_name") is not None
                    ),
                }
            )
    return output


def normalize_depth_section_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    if conservation_auditor is not None:
        return conservation_auditor.normalize_identifier(value)
    cleaned = re.sub(r"\\[A-Za-z@]+\*?", " ", value)
    cleaned = re.sub(r"[{}~]", " ", cleaned)
    return re.sub(
        r"[^a-z0-9\u3400-\u4dbf\u4e00-\u9fff]+",
        " ",
        cleaned.lower(),
    ).strip()


def live_depth_section_index(
    by_id: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[str, str],
]:
    """Index live primary main-text sections and each unit's section membership."""

    ordered = sorted(
        by_id.values(),
        key=lambda unit: (
            unit.get("order")
            if isinstance(unit.get("order"), int)
            else 10**12,
            str(unit.get("unit_id", "")),
        ),
    )
    section_units = [
        unit
        for unit in ordered
        if unit.get("type") == "section"
        and unit.get("region") == "main_text"
        and unit.get("main_text") is True
    ]
    tex_levels = {
        "part",
        "chapter",
        "section",
        "subsection",
        "subsubsection",
        "paragraph",
        "subparagraph",
    }
    tex_style = any(
        str(unit.get("level", "")).strip().lower() in tex_levels
        for unit in section_units
    )
    primary_sections = [
        unit
        for unit in section_units
        if not tex_style or str(unit.get("level", "")).strip().lower() == "section"
    ]
    occurrences: dict[str, int] = defaultdict(int)
    by_selector_id: dict[str, dict[str, Any]] = {}
    by_normalized_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    primary_by_unit_id: dict[str, dict[str, Any]] = {}
    for unit in primary_sections:
        normalized = normalize_depth_section_name(
            unit.get("section_title", unit.get("text"))
        )
        if not normalized:
            continue
        occurrences[normalized] += 1
        record = {
            "manifest_section_unit_id": str(unit.get("unit_id")),
            "candidate_section_id": (
                f"{normalized}#{occurrences[normalized]}"
            ),
            "candidate_section_name": str(
                unit.get("section_title", unit.get("text", ""))
            ),
            "normalized_section_name": normalized,
        }
        by_selector_id[record["candidate_section_id"]] = record
        by_normalized_name[normalized].append(record)
        primary_by_unit_id[record["manifest_section_unit_id"]] = record

    membership: dict[str, str] = {}
    current_section_unit_id = ""
    for unit in ordered:
        unit_id = str(unit.get("unit_id", ""))
        if unit_id in primary_by_unit_id:
            current_section_unit_id = unit_id
        if (
            current_section_unit_id
            and unit.get("region") == "main_text"
            and unit.get("main_text") is True
        ):
            membership[unit_id] = current_section_unit_id
    return by_selector_id, dict(by_normalized_name), membership


def resolve_depth_question_candidate_sections(
    artifact_contract: dict[str, Any],
    question_specs: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    conservation_replay: dict[str, Any],
    audit: GateAudit,
    path: Path | None = None,
) -> tuple[dict[str, str], dict[str, str], bool]:
    """Resolve every depth question to one live candidate main-text section."""

    by_selector_id, by_name, membership = live_depth_section_index(by_id)
    resolved_by_question: dict[str, str] = {}
    valid = True
    mature = artifact_contract.get("mature_baseline") is True

    replay_checks: list[Any] = []
    if mature:
        conservation = conservation_replay.get("conservation")
        budget = (
            conservation.get("mature_section_budget")
            if isinstance(conservation, dict)
            else None
        )
        if (
            isinstance(budget, dict)
            and budget.get("required") is True
            and str(budget.get("status", "")).strip().lower() == "pass"
            and isinstance(budget.get("checks"), list)
        ):
            replay_checks = budget["checks"]

    resolved_by_card: dict[str, str] = {}
    card_selector_fingerprints: dict[str, str] = {}
    for spec in question_specs:
        card_id = str(spec.get("card_id", ""))
        selector_fingerprint = canonical_hash(
            {
                "section_name": spec.get("section_name"),
                "candidate_section_id": spec.get("candidate_section_id"),
                "candidate_section_name": spec.get("candidate_section_name"),
                "candidate_section_id_present": spec.get(
                    "candidate_section_id_present"
                ),
                "candidate_section_name_present": spec.get(
                    "candidate_section_name_present"
                ),
            }
        )
        if card_id in card_selector_fingerprints:
            if card_selector_fingerprints[card_id] != selector_fingerprint:
                audit.add(
                    "audit_incomplete",
                    "main_text_depth_question_section_unresolved",
                    "One depth-question card ID cannot identify conflicting candidate sections.",
                    path=str(path) if path is not None else None,
                    card_id=card_id,
                )
                valid = False
            target = resolved_by_card.get(card_id)
            if target:
                resolved_by_question[str(spec["question_id"])] = target
            continue
        card_selector_fingerprints[card_id] = selector_fingerprint

        selected: dict[str, Any] | None = None
        selector_source = ""
        failure_reason = ""
        if not mature:
            selector_source = "artifact_contract.section_name"
            raw_name = spec.get("section_name")
            normalized_name = normalize_depth_section_name(raw_name)
            matches = by_name.get(normalized_name, []) if normalized_name else []
            if len(matches) == 1:
                selected = matches[0]
            elif not normalized_name:
                failure_reason = "candidate-only card requires a nonempty section_name"
            elif len(matches) > 1:
                failure_reason = "section_name matches multiple live candidate sections"
            else:
                failure_reason = "section_name does not match a live candidate section"
        else:
            explicit_id = spec.get("candidate_section_id")
            explicit_name = spec.get("candidate_section_name")
            id_present = spec.get("candidate_section_id_present") is True
            name_present = spec.get("candidate_section_name_present") is True
            if id_present or name_present:
                selector_source = "artifact_contract.explicit_candidate_selector"
                id_match: dict[str, Any] | None = None
                name_match: dict[str, Any] | None = None
                if id_present:
                    if isinstance(explicit_id, str) and explicit_id.strip():
                        id_match = by_selector_id.get(explicit_id.strip())
                    if id_match is None:
                        failure_reason = "explicit candidate_section_id is stale or invalid"
                if name_present:
                    normalized_name = normalize_depth_section_name(explicit_name)
                    matches = by_name.get(normalized_name, []) if normalized_name else []
                    if len(matches) == 1:
                        name_match = matches[0]
                    elif not normalized_name:
                        failure_reason = "explicit candidate_section_name is invalid"
                    elif len(matches) > 1:
                        failure_reason = "explicit candidate_section_name is ambiguous"
                    else:
                        failure_reason = "explicit candidate_section_name is stale"
                if not failure_reason:
                    if id_match is not None and name_match is not None and (
                        id_match["manifest_section_unit_id"]
                        != name_match["manifest_section_unit_id"]
                    ):
                        failure_reason = "explicit candidate section ID and name disagree"
                    else:
                        selected = id_match or name_match
            else:
                selector_source = (
                    "fresh_canonical_conservation_replay."
                    "conservation.mature_section_budget.checks"
                )
                matches = [
                    check
                    for check in replay_checks
                    if isinstance(check, dict)
                    and check.get("section_card_id") == card_id
                ]
                if len(matches) != 1:
                    failure_reason = (
                        "fresh mature-section replay does not contain exactly one card check"
                    )
                else:
                    check = matches[0]
                    candidate_section_id = check.get("candidate_section_id")
                    if (
                        str(check.get("status", "")).strip().lower() != "pass"
                        or not isinstance(candidate_section_id, str)
                        or not candidate_section_id.strip()
                    ):
                        failure_reason = (
                            "fresh mature-section replay does not resolve a passing candidate section"
                        )
                    else:
                        selected = by_selector_id.get(candidate_section_id.strip())
                        if selected is None:
                            failure_reason = (
                                "fresh mature-section replay selector is stale against the live manifest"
                            )

        if selected is None:
            audit.add(
                "audit_incomplete",
                "main_text_depth_question_section_unresolved",
                "A depth-question card must resolve uniquely to its live candidate main-text section.",
                path=str(path) if path is not None else None,
                card_id=card_id,
                selector_source=selector_source or None,
                reason=failure_reason or "candidate section is unresolved",
            )
            valid = False
            continue
        target_unit_id = str(selected["manifest_section_unit_id"])
        resolved_by_card[card_id] = target_unit_id
        resolved_by_question[str(spec["question_id"])] = target_unit_id
    return resolved_by_question, membership, valid


def validate_depth_question_evidence_units(
    evidence_units: Any,
    verdict: str,
    target_section_unit_id: str | None,
    unit_section_membership: dict[str, str],
    by_id: dict[str, dict[str, Any]],
    audit: GateAudit,
    *,
    path: Path | None = None,
    question_id: str | None = None,
) -> bool:
    """Bind evidence to live hashes and, for pass, the question's own section."""

    evidence_valid = (
        isinstance(evidence_units, list)
        and bool(evidence_units)
        and all(
            isinstance(evidence, dict)
            and isinstance(evidence.get("unit_id"), str)
            and evidence.get("unit_id") in by_id
            and normalized_sha(evidence.get("text_sha256"))
            == normalized_sha(by_id[evidence["unit_id"]].get("text_sha256"))
            for evidence in evidence_units
        )
    )
    if not evidence_valid:
        audit.add(
            "audit_incomplete",
            "main_text_depth_question_evidence_invalid",
            "Every depth-question review must cite at least one live manifest unit ID and its exact current text SHA-256.",
            path=str(path) if path is not None else None,
            question_id=question_id,
        )
        return False
    if verdict != "pass":
        return True
    outside_target = [
        str(evidence["unit_id"])
        for evidence in evidence_units
        if by_id[str(evidence["unit_id"])].get("region") != "main_text"
        or by_id[str(evidence["unit_id"])].get("main_text") is not True
        or not target_section_unit_id
        or unit_section_membership.get(str(evidence["unit_id"]))
        != target_section_unit_id
    ]
    if outside_target:
        audit.add(
            "audit_incomplete",
            "main_text_depth_question_evidence_section_invalid",
            "A passing depth-question review may cite only current main-text units in that card's resolved candidate section; untyped cross-section evidence is not accepted.",
            path=str(path) if path is not None else None,
            question_id=question_id,
            target_section_unit_id=target_section_unit_id,
            invalid_evidence_unit_ids=sorted(outside_target),
        )
        return False
    return True


def validate_main_text_sufficiency_audit(
    raw_path: str | None,
    required: bool,
    manifest_id: str,
    manifest_hash: str,
    candidate_hash: str,
    content_hash: str,
    contract_hash: str,
    qa_contract_hash: str,
    artifact_contract_hash: str,
    assignment_registry_hash: str,
    main_assignment: dict[str, Any] | None,
    conservation_gate_hash: str,
    conservation_gate_status: str,
    conservation_gate_required: bool,
    artifact_contract: dict[str, Any],
    conservation_replay: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    audit: GateAudit,
) -> tuple[Path | None, str, bool]:
    """Validate the independent fifth role's typed, freshness-bound result."""

    if not required:
        if isinstance(raw_path, str) and raw_path.strip():
            audit.add(
                "audit_incomplete",
                "bounded_main_text_sufficiency_audit_unexpected",
                "Bounded-change QA must not claim a whole-manuscript sufficiency audit.",
                path=str(Path(raw_path).expanduser().resolve()),
            )
            return Path(raw_path).expanduser().resolve(), "", False
        return None, "", True
    if not isinstance(raw_path, str) or not raw_path.strip():
        audit.add(
            "audit_incomplete",
            "main_text_sufficiency_audit_missing",
            "The independent Main-Text Sufficiency and Conservation audit is required.",
        )
        return None, "", False
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        audit.add(
            "audit_incomplete",
            "main_text_sufficiency_audit_missing",
            "The independent Main-Text Sufficiency and Conservation result is unavailable.",
            path=str(path),
        )
        return path, "", False
    payload = load_json_object(path, audit, "main-text sufficiency audit")
    result_hash_value = sha256_file(path)
    if payload is None:
        return path, result_hash_value, False
    valid = require_schema(payload, audit, "Main-text sufficiency audit", path)
    outcome_status = str(payload.get("status", "")).strip().lower()
    allowed_outcomes = {"pass", "fail", "approval_required", "metric_unavailable"}
    if (
        payload.get("schema_id") != MAIN_TEXT_SUFFICIENCY_SCHEMA_ID
        or payload.get("gate_type") != MAIN_TEXT_SUFFICIENCY_GATE_TYPE
        or outcome_status not in allowed_outcomes
        or not nonempty(payload.get("result_id"))
        or not valid_iso8601_timestamp(payload.get("reviewed_at"))
    ):
        audit.add(
            "audit_incomplete",
            "main_text_sufficiency_identity_invalid",
            "Fifth-role audit must use the fixed schema/gate identity, a closed outcome status, and an ISO-8601 timestamp with timezone.",
            path=str(path),
        )
        valid = False
    exact_bindings = {
        "manifest_id": (payload.get("manifest_id"), manifest_id),
        "manifest_sha256": (
            normalized_sha(payload.get("manifest_sha256")),
            manifest_hash,
        ),
        "candidate_sha256": (
            normalized_sha(payload.get("candidate_sha256")),
            candidate_hash,
        ),
        "content_sha256": (
            normalized_sha(payload.get("content_sha256")),
            content_hash,
        ),
        "contract_sha256": (
            normalized_sha(payload.get("contract_sha256")),
            contract_hash,
        ),
        "qa_contract_sha256": (
            normalized_sha(payload.get("qa_contract_sha256")),
            qa_contract_hash,
        ),
        "artifact_contract_sha256": (
            normalized_sha(payload.get("artifact_contract_sha256")),
            artifact_contract_hash,
        ),
        "assignment_registry_sha256": (
            normalized_sha(payload.get("assignment_registry_sha256")),
            assignment_registry_hash,
        ),
    }
    mismatches = [
        field_name
        for field_name, (actual, expected) in exact_bindings.items()
        if actual != expected
    ]
    if mismatches:
        audit.add(
            "audit_incomplete",
            "main_text_sufficiency_binding_invalid",
            "Fifth-role result is stale or is not bound to every governing artifact.",
            path=str(path),
            mismatched_fields=mismatches,
        )
        valid = False
    if (
        conservation_gate_status in {
            "fail",
            "approval_required",
            "metric_unavailable",
        }
        and outcome_status != conservation_gate_status
    ):
        audit.add(
            "audit_incomplete",
            "main_text_conservation_status_mismatch",
            "Fifth-role outcome must preserve the exact status of a fresh nonpassing conservation gate.",
            path=str(path),
            conservation_status=conservation_gate_status,
            fifth_role_status=outcome_status or None,
        )
        valid = False
    recorded_gate_hash = normalized_sha(payload.get("conservation_gate_sha256"))
    if conservation_gate_required:
        if not conservation_gate_hash or recorded_gate_hash != conservation_gate_hash:
            audit.add(
                "audit_incomplete",
                "main_text_conservation_gate_binding_invalid",
                "Fifth-role result must bind the exact fresh passing conservation report SHA-256.",
                path=str(path),
            )
            valid = False
    elif recorded_gate_hash:
        audit.add(
            "audit_incomplete",
            "main_text_conservation_gate_unexpected",
            "Fifth-role result cites a conservation report not composed by this validator run.",
            path=str(path),
        )
        valid = False
    reviewer = payload.get("reviewer")
    reviewer = reviewer if isinstance(reviewer, dict) else {}
    if (
        main_assignment is None
        or payload.get("assignment_id") != main_assignment.get("assignment_id")
        or reviewer.get("native_agent_id") != main_assignment.get("native_agent_id")
        or reviewer.get("task_id") != main_assignment.get("task_id")
        or reviewer.get("role") != "main_text_sufficiency_and_conservation"
        or not nonempty(reviewer.get("reviewer_id"))
        or not nonempty(reviewer.get("independence_key"))
    ):
        audit.add(
            "audit_incomplete",
            "main_text_sufficiency_assignment_invalid",
            "Fifth-role reviewer must match its native assignment and remain distinct from semantic packet roles.",
            path=str(path),
        )
        valid = False
    checklist = payload.get("checklist")
    if (
        not isinstance(checklist, dict)
        or set(checklist) != set(MAIN_TEXT_SUFFICIENCY_CHECKS)
        or any(not isinstance(checklist.get(key), bool) for key in MAIN_TEXT_SUFFICIENCY_CHECKS)
    ):
        audit.add(
            "audit_incomplete",
            "main_text_sufficiency_checklist_incomplete",
            "Every fixed main-text sufficiency/conservation check must have an explicit boolean result.",
            path=str(path),
        )
        valid = False
    expected_questions = artifact_depth_question_specs(artifact_contract)
    (
        question_section_bindings,
        unit_section_membership,
        section_bindings_valid,
    ) = resolve_depth_question_candidate_sections(
        artifact_contract,
        expected_questions,
        by_id,
        conservation_replay,
        audit,
        path,
    )
    if not section_bindings_valid:
        valid = False
    expected_by_id = {
        item["question_id"]: item for item in expected_questions
    }
    if len(expected_by_id) != len(expected_questions):
        audit.add(
            "audit_incomplete",
            "artifact_depth_question_identity_duplicate",
            "Live artifact section cards produce duplicate deterministic depth-question identities.",
            path=str(path),
        )
        valid = False
    raw_question_reviews = payload.get("question_reviews")
    if not isinstance(raw_question_reviews, list):
        audit.add(
            "audit_incomplete",
            "main_text_depth_question_coverage_invalid",
            "Fifth-role result requires a question_reviews array exactly covering every live minimum-depth question.",
            path=str(path),
        )
        raw_question_reviews = []
        valid = False
    seen_question_ids: set[str] = set()
    question_verdicts: dict[str, str] = {}
    extra_question_ids: list[str] = []
    duplicate_question_ids: list[str] = []
    for raw_review in raw_question_reviews:
        if not isinstance(raw_review, dict):
            audit.add(
                "audit_incomplete",
                "main_text_depth_question_review_invalid",
                "Every depth-question review must be an object with a typed verdict and nonempty rationale.",
                path=str(path),
            )
            valid = False
            continue
        question_id = raw_review.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            audit.add(
                "audit_incomplete",
                "main_text_depth_question_review_invalid",
                "Every depth-question review requires a nonempty deterministic question_id.",
                path=str(path),
            )
            valid = False
            continue
        question_id = question_id.strip()
        if question_id in seen_question_ids:
            duplicate_question_ids.append(question_id)
            valid = False
            continue
        seen_question_ids.add(question_id)
        expected_question = expected_by_id.get(question_id)
        if expected_question is None:
            extra_question_ids.append(question_id)
            valid = False
            continue
        if (
            raw_review.get("card_id") != expected_question["card_id"]
            or normalized_sha(raw_review.get("question_sha256"))
            != expected_question["question_sha256"]
        ):
            audit.add(
                "audit_incomplete",
                "main_text_depth_question_hash_mismatch",
                "Depth-question review does not bind the exact live card ID and canonical question hash.",
                path=str(path),
                question_id=question_id,
            )
            valid = False
        verdict = str(raw_review.get("verdict", "")).strip().lower()
        if verdict not in allowed_outcomes or not (
            isinstance(raw_review.get("rationale"), str)
            and raw_review["rationale"].strip()
        ):
            audit.add(
                "audit_incomplete",
                "main_text_depth_question_review_invalid",
                "Depth-question verdict must use the closed outcome vocabulary and include a nonempty rationale.",
                path=str(path),
                question_id=question_id,
            )
            valid = False
        else:
            question_verdicts[question_id] = verdict
        evidence_units = raw_review.get("evidence_units")
        if not validate_depth_question_evidence_units(
            evidence_units,
            verdict,
            question_section_bindings.get(question_id),
            unit_section_membership,
            by_id,
            audit,
            path=path,
            question_id=question_id,
        ):
            valid = False
    missing_question_ids = sorted(set(expected_by_id) - seen_question_ids)
    if missing_question_ids or extra_question_ids or duplicate_question_ids:
        audit.add(
            "audit_incomplete",
            "main_text_depth_question_coverage_invalid",
            "question_reviews must cover every deterministic live depth question exactly once, with no extra records.",
            path=str(path),
            missing_question_ids=missing_question_ids,
            extra_question_ids=sorted(extra_question_ids),
            duplicate_question_ids=sorted(duplicate_question_ids),
        )
        valid = False
    findings = payload.get("findings")
    if outcome_status == "pass":
        if not isinstance(checklist, dict) or any(
            checklist.get(key) is not True for key in MAIN_TEXT_SUFFICIENCY_CHECKS
        ):
            audit.add(
                "audit_incomplete",
                "main_text_sufficiency_checklist_incomplete",
                "A passing fifth-role audit requires every fixed check to be true.",
                path=str(path),
            )
            valid = False
        nonpassing_questions = sorted(
            question_id
            for question_id, verdict in question_verdicts.items()
            if verdict != "pass"
        )
        if (
            set(question_verdicts) != set(expected_by_id)
            or nonpassing_questions
        ):
            audit.add(
                "audit_incomplete",
                "main_text_depth_question_pass_invalid",
                "A passing fifth-role audit requires every live depth question to have an exact passing review.",
                path=str(path),
                nonpassing_question_ids=nonpassing_questions,
            )
            valid = False
        if not isinstance(findings, list) or findings:
            audit.add(
                "audit_incomplete",
                "main_text_sufficiency_findings_unresolved",
                "A passing fifth-role audit requires an explicit empty findings array.",
                path=str(path),
            )
            valid = False
    elif outcome_status in allowed_outcomes - {"pass"}:
        allowed_finding_statuses = allowed_outcomes - {"pass"}
        structured_findings = isinstance(findings, list) and bool(findings) and all(
            isinstance(item, dict)
            and nonempty(item.get("code"))
            and nonempty(item.get("message"))
            and str(item.get("status", "")).strip().lower()
            in allowed_finding_statuses
            for item in findings
        )
        finding_statuses = {
            str(item.get("status", "")).strip().lower()
            for item in findings
            if isinstance(item, dict)
        }
        finding_statuses.update(
            verdict for verdict in question_verdicts.values() if verdict != "pass"
        )
        derived_outcome = next(
            (
                status
                for status in FIFTH_ROLE_STATUS_PRIORITY
                if status in finding_statuses and status in allowed_finding_statuses
            ),
            "",
        )
        at_least_one_failed_check = isinstance(checklist, dict) and any(
            checklist.get(key) is False for key in MAIN_TEXT_SUFFICIENCY_CHECKS
        )
        if (
            not structured_findings
            or not at_least_one_failed_check
            or derived_outcome != outcome_status
        ):
            audit.add(
                "audit_incomplete",
                "main_text_sufficiency_outcome_invalid",
                "A nonpassing fifth-role audit requires at least one false check, typed blocker findings, and an overall status equal to their fail-closed priority.",
                path=str(path),
                outcome_status=outcome_status or None,
            )
            valid = False
        elif valid:
            for question_id, verdict in sorted(question_verdicts.items()):
                if verdict == "pass":
                    continue
                audit.add(
                    verdict,
                    "main_text_depth_question_nonpass",
                    "A registered main-text depth question did not pass.",
                    path=str(path),
                    source_role="main_text_sufficiency_and_conservation",
                    source_result_id=payload.get("result_id"),
                    question_id=question_id,
                )
            for item in findings:
                source_context = {
                    key: value
                    for key, value in item.items()
                    if key not in {"status", "code", "message"}
                }
                audit.add(
                    str(item["status"]).strip().lower(),
                    str(item["code"]),
                    str(item["message"]),
                    path=str(path),
                    source_role="main_text_sufficiency_and_conservation",
                    source_result_id=payload.get("result_id"),
                    source_finding_context=(source_context or None),
                )
    return path, result_hash_value, valid


def extract_reviewer(payload: dict[str, Any]) -> tuple[str, str, str]:
    reviewer = payload.get("reviewer")
    if not isinstance(reviewer, dict):
        reviewer = {}
    reviewer_id = reviewer.get("reviewer_id", payload.get("reviewer_id"))
    role = reviewer.get("role", payload.get("role"))
    independence = reviewer.get(
        "independence_key",
        reviewer.get(
            "independence_group",
            payload.get("independence_key", payload.get("independence_group")),
        ),
    )
    return (
        reviewer_id.strip() if isinstance(reviewer_id, str) else "",
        normalize_role(role),
        independence.strip() if isinstance(independence, str) else "",
    )


def review_records(payload: dict[str, Any]) -> Any:
    if "unit_reviews" in payload:
        return payload["unit_reviews"]
    if "reviews" in payload:
        return payload["reviews"]
    return None


def validate_review_record(
    record: Any,
    path: Path,
    reviewer_id: str,
    role: str,
    independence_key: str,
    result_revision_id: Any,
    by_id: dict[str, dict[str, Any]],
    audit: GateAudit,
) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        audit.add(
            "audit_incomplete",
            "unit_review_invalid",
            "Each unit review must be an object.",
            path=str(path),
        )
        return None
    required_fields = (
        "unit_id",
        "criterion_id",
        "verdict",
        "source_span",
        "evidence",
        "reason",
        "severity",
        "confidence",
        "requires_author_action",
    )
    missing = [name for name in required_fields if name not in record]
    if missing:
        audit.add(
            "audit_incomplete",
            "unit_review_fields_missing",
            "Unit review is missing required audit fields.",
            path=str(path),
            unit_id=record.get("unit_id"),
            missing_fields=missing,
        )
        return None
    unit_id = record.get("unit_id")
    if not isinstance(unit_id, str) or unit_id not in by_id:
        audit.add(
            "audit_incomplete",
            "unit_review_unknown_unit",
            "Unit review references a unit absent from the manifest.",
            path=str(path),
            unit_id=unit_id,
        )
        return None
    criterion = record.get("criterion_id")
    verdict = str(record.get("verdict", "")).strip().lower()
    confidence = record.get("confidence")
    valid = True
    if not isinstance(criterion, str) or not criterion.strip():
        valid = False
    if verdict not in KNOWN_VERDICTS:
        valid = False
    if not nonempty(record.get("source_span")):
        valid = False
    if not nonempty(record.get("evidence")):
        valid = False
    if not isinstance(record.get("reason"), str) or not record["reason"].strip():
        valid = False
    if not isinstance(record.get("severity"), str) or not record["severity"].strip():
        valid = False
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        valid = False
    if not isinstance(record.get("requires_author_action"), bool):
        valid = False
    source_span = record.get("source_span")
    unit = by_id[unit_id]
    manifest_anchor = unit.get("source")
    if not isinstance(source_span, dict):
        valid = False
    elif isinstance(manifest_anchor, dict) and manifest_anchor:
        # A reviewer must quote the exact current manifest anchor.  The packet
        # and manifest hashes bind that anchor to the reviewed manuscript.
        if canonical_hash(source_span) != canonical_hash(manifest_anchor):
            valid = False
    elif not (
        source_span.get("unit_id") == unit_id
        and source_span.get("text_sha256") == unit.get("text_sha256")
    ):
        # Synthetic/adapter manifests without a source object must still bind
        # the review to both stable identity and exact unit text.
        valid = False
    severity = str(record.get("severity", "")).strip().lower()
    if severity not in {"critical", "major", "minor", "none"}:
        valid = False
    if not valid:
        audit.add(
            "audit_incomplete",
            "unit_review_field_invalid",
            "Unit review contains an invalid criterion, verdict, source span, evidence, reason, severity, confidence, or author-action flag.",
            path=str(path),
            unit_id=unit_id,
        )
        return None
    if nonempty(record.get("risk_or_role_escalation")):
        audit.add(
            "audit_incomplete",
            "unit_risk_or_role_escalation_requires_reprepare",
            "Unit-level risk or role escalation requires a new manifest and review packet.",
            path=str(path),
            unit_id=unit_id,
            escalation=record.get("risk_or_role_escalation"),
        )
        return None
    result = dict(record)
    result["unit_id"] = unit_id
    result["criterion_id"] = criterion.strip()
    result["verdict"] = verdict
    result["reviewer_id"] = reviewer_id
    result["role"] = role
    result["independence_key"] = independence_key
    result["revision_id"] = record.get("revision_id", result_revision_id)
    result["_path"] = str(path)
    return result


def ledger_entries(payload: dict[str, Any], key: str, aliases: Sequence[str] = ()) -> list[Any]:
    ledgers = payload.get("ledgers", payload.get("ledger", {}))
    if not isinstance(ledgers, dict):
        return []
    for name in (key, *aliases):
        if name in ledgers:
            value = ledgers[name]
            return value if isinstance(value, list) else [value]
    return []


def ledger_scoped_unit_ids(key: str, entry: dict[str, Any]) -> set[str]:
    if key == "intent_to_text":
        values = entry.get("unit_ids", entry.get("draft_unit_ids"))
    elif key in {"text_to_intent", "text_to_evidence"}:
        values = entry.get("unit_id")
    elif key == "definitions":
        values = [entry.get("definition_unit_id"), entry.get("first_use_unit_id")]
    else:
        return set()
    return {
        value for value in as_list(values) if isinstance(value, str) and value
    }


def load_results(
    paths: list[Path],
    manifest_id: str,
    manifest_hash: str,
    manuscript_hash: str,
    contract_hash: str,
    content_hash: str,
    qa_contract_hash: str,
    artifact_contract_hash: str,
    by_id: dict[str, dict[str, Any]],
    packets_by_id: dict[str, dict[str, Any]],
    assignment_registry_hash: str,
    packet_assignments: dict[str, dict[str, Any]],
    audit: GateAudit,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, list[Any]]]:
    valid_results: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    ledgers: dict[str, list[Any]] = defaultdict(list)
    result_ids: set[str] = set()
    reviewer_identity: dict[str, tuple[str, str]] = {}
    result_packet_ids: set[str] = set()

    for path in paths:
        payload = load_json_object(path, audit, "review result")
        if payload is None:
            continue
        valid = require_schema(payload, audit, "Review result", path)
        result_id = payload.get("result_id", payload.get("review_id"))
        if not isinstance(result_id, str) or not result_id.strip():
            audit.add(
                "audit_incomplete",
                "result_id_missing",
                "Review result requires a nonempty result_id.",
                path=str(path),
            )
            valid = False
        elif result_id in result_ids:
            audit.add(
                "audit_incomplete",
                "duplicate_result_id",
                "Review result IDs must be unique.",
                result_id=result_id,
                path=str(path),
            )
            valid = False
        else:
            result_ids.add(result_id)

        reviewer_id, role, independence_key = extract_reviewer(payload)
        if not reviewer_id or not role:
            audit.add(
                "audit_incomplete",
                "reviewer_identity_missing",
                "Review result requires reviewer_id and role.",
                path=str(path),
            )
            valid = False
        if reviewer_id:
            previous_identity = reviewer_identity.get(reviewer_id)
            if previous_identity is not None and previous_identity != (role, independence_key):
                audit.add(
                    "audit_incomplete",
                    "reviewer_independence_inconsistent",
                    "One reviewer_id may span same-role batches only with one independence_key.",
                    reviewer_id=reviewer_id,
                )
                valid = False
            reviewer_identity.setdefault(reviewer_id, (role, independence_key))

        result_packet_id = payload.get("packet_id")
        packet = packets_by_id.get(result_packet_id) if isinstance(result_packet_id, str) else None
        assignment = (
            packet_assignments.get(result_packet_id)
            if isinstance(result_packet_id, str)
            else None
        )
        if packet is None:
            audit.add(
                "audit_incomplete",
                "review_packet_missing",
                "Review result does not identify a fresh validated packet batch.",
                path=str(path),
                role=role or None,
                packet_id=result_packet_id,
            )
            valid = False
        else:
            if packet["role"] != role or normalized_sha(payload.get("packet_sha256")) != packet[
                "packet_sha256"
            ]:
                audit.add(
                    "audit_incomplete",
                    "review_packet_stale",
                    "Review result does not reference the exact assigned packet role and SHA-256.",
                    path=str(path),
                    role=role,
                )
                valid = False
            if packet["packet_id"] in result_packet_ids:
                audit.add(
                    "audit_incomplete",
                    "review_packet_result_duplicate",
                    "Each packet batch must have exactly one review result.",
                    path=str(path),
                    packet_id=packet["packet_id"],
                )
                valid = False
            else:
                result_packet_ids.add(packet["packet_id"])
        reviewer = payload.get("reviewer")
        reviewer = reviewer if isinstance(reviewer, dict) else {}
        if (
            not assignment_registry_hash
            or normalized_sha(payload.get("assignment_registry_sha256"))
            != assignment_registry_hash
            or assignment is None
            or payload.get("assignment_id") != assignment.get("assignment_id")
            or reviewer.get("native_agent_id") != assignment.get("native_agent_id")
            or reviewer.get("task_id") != assignment.get("task_id")
        ):
            audit.add(
                "audit_incomplete",
                "review_assignment_binding_invalid",
                "Review result must bind the filled assignment-registry SHA-256 and exact native assignment identity.",
                path=str(path),
                packet_id=result_packet_id,
            )
            valid = False

        result_status = str(payload.get("status", "")).strip().lower()
        if result_status not in COMPLETE_RESULT_STATUSES:
            audit.add(
                "audit_incomplete",
                "review_result_incomplete",
                "Review result status must be complete.",
                path=str(path),
                result_status=result_status or None,
            )
            valid = False

        if payload.get("manifest_id") != manifest_id:
            audit.add(
                "audit_incomplete",
                "review_manifest_stale",
                "Review result does not reference the current manifest_id.",
                path=str(path),
            )
            valid = False
        if normalized_sha(payload.get("manifest_sha256")) != manifest_hash:
            audit.add(
                "audit_incomplete",
                "review_manifest_content_stale",
                "Review result does not reference the exact current manifest SHA-256.",
                path=str(path),
            )
            valid = False
        if result_hash(payload, "manuscript") != manuscript_hash:
            audit.add(
                "audit_incomplete",
                "review_manuscript_stale",
                "Review result does not reference the current manuscript SHA-256.",
                path=str(path),
            )
            valid = False
        if result_hash(payload, "contract") != contract_hash:
            audit.add(
                "audit_incomplete",
                "review_contract_stale",
                "Review result does not reference the current contract SHA-256.",
                path=str(path),
            )
            valid = False
        if not content_hash or result_hash(payload, "content") != content_hash:
            audit.add(
                "audit_incomplete",
                "review_content_stale",
                "Review result does not reference the current expanded/content SHA-256.",
                path=str(path),
            )
            valid = False
        if not qa_contract_hash or result_hash(payload, "qa_contract") != qa_contract_hash:
            audit.add(
                "audit_incomplete",
                "review_qa_contract_stale",
                "Review result does not reference the current QA-contract SHA-256.",
                path=str(path),
            )
            valid = False
        if result_hash(payload, "artifact_contract") != artifact_contract_hash:
            audit.add(
                "audit_incomplete",
                "review_artifact_contract_stale",
                "Review result does not reference the manifest's artifact-contract SHA-256.",
                path=str(path),
            )
            valid = False
        escalation = payload.get("risk_or_role_escalation")
        if nonempty(escalation):
            audit.add(
                "audit_incomplete",
                "risk_or_role_escalation_requires_reprepare",
                "Reviewer escalated risk or role requirements; prepare a new manifest and rerun every affected review.",
                path=str(path),
                escalation=escalation,
            )
            valid = False

        raw_records = review_records(payload)
        if not isinstance(raw_records, list):
            audit.add(
                "audit_incomplete",
                "unit_reviews_missing",
                "Review result must contain a unit_reviews list.",
                path=str(path),
            )
            valid = False
            raw_records = []

        parsed_records: list[dict[str, Any]] = []
        for raw_record in raw_records:
            parsed = validate_review_record(
                raw_record,
                path,
                reviewer_id,
                role,
                independence_key,
                payload.get("revision_id"),
                by_id,
                audit,
            )
            if parsed is None:
                valid = False
            else:
                parsed_records.append(parsed)
        if packet is not None:
            outside_packet = sorted(
                {
                    record["unit_id"]
                    for record in parsed_records
                    if record["unit_id"] not in packet["unit_ids"]
                }
            )
            if outside_packet:
                audit.add(
                    "audit_incomplete",
                    "review_unit_outside_packet",
                    "Review result covers units outside its assigned packet.",
                    path=str(path),
                    unit_ids=outside_packet,
                )
                valid = False
            reviewed_packet_units = {record["unit_id"] for record in parsed_records}
            missing_packet_units = sorted(packet["unit_ids"] - reviewed_packet_units)
            if missing_packet_units:
                audit.add(
                    "audit_incomplete",
                    "review_packet_unit_missing",
                    "Review result omits one or more units from its packet batch.",
                    path=str(path),
                    packet_id=packet["packet_id"],
                    unit_ids=missing_packet_units,
                )
                valid = False
            expected_pairs = {
                (unit_id, criterion_id)
                for unit_id in packet["unit_ids"]
                for criterion_id in packet.get("required_checks", set())
            }
            actual_pairs = [
                (record["unit_id"], record["criterion_id"])
                for record in parsed_records
                if record["unit_id"] in packet["unit_ids"]
            ]
            actual_pair_set = set(actual_pairs)
            duplicate_pairs = sorted(
                pair for pair in actual_pair_set if actual_pairs.count(pair) != 1
            )
            if (
                actual_pair_set != expected_pairs
                or duplicate_pairs
                or len(actual_pairs) != len(expected_pairs)
            ):
                audit.add(
                    "audit_incomplete",
                    "role_criterion_coverage_invalid",
                    "Review result must contain exactly one record for every packet unit x fixed role criterion pair; use not_applicable rather than omission.",
                    path=str(path),
                    packet_id=packet["packet_id"],
                    missing_pairs=[list(pair) for pair in sorted(expected_pairs - actual_pair_set)],
                    unexpected_pairs=[list(pair) for pair in sorted(actual_pair_set - expected_pairs)],
                    duplicate_pairs=[list(pair) for pair in duplicate_pairs],
                )
                valid = False

        if valid:
            payload = dict(payload)
            payload["_path"] = str(path)
            payload["_reviewer_id"] = reviewer_id
            payload["_role"] = role
            payload["_independence_key"] = independence_key
            payload["_native_agent_id"] = reviewer.get("native_agent_id")
            payload["_task_id"] = reviewer.get("task_id")
            valid_results.append(payload)
            records.extend(parsed_records)
            for key, aliases in (
                ("intent_to_text", ("intent_coverage",)),
                ("text_to_intent", ("claim_authorization",)),
                ("text_to_evidence", ("evidence_mapping", "claim_evidence")),
                ("baseline_to_candidate", ("conservation", "content_conservation")),
                ("definitions", ("definition_order", "definition_registry")),
                ("revision_rechecks", ("rechecks",)),
                ("authority_projection_verified", ("authority_projection",)),
            ):
                for entry in ledger_entries(payload, key, aliases):
                    if isinstance(entry, dict):
                        scoped_ids = ledger_scoped_unit_ids(key, entry)
                        if packet is not None and not scoped_ids.issubset(
                            packet["unit_ids"]
                        ):
                            audit.add(
                                "audit_incomplete",
                                "ledger_unit_outside_packet",
                                "Reviewer ledger cites a unit outside its packet batch.",
                                path=str(path),
                                packet_id=packet["packet_id"],
                                ledger=key,
                                unit_ids=sorted(scoped_ids - packet["unit_ids"]),
                            )
                            continue
                        enriched = dict(entry)
                        enriched["_reviewer_id"] = reviewer_id
                        enriched["_role"] = role
                        enriched["_path"] = str(path)
                        enriched["_packet_id"] = (
                            packet.get("packet_id") if packet is not None else None
                        )
                        enriched["_packet_sha256"] = (
                            packet.get("packet_sha256") if packet is not None else None
                        )
                        ledgers[key].append(enriched)
                    else:
                        audit.add(
                            "audit_incomplete",
                            "ledger_entry_invalid",
                            f"{key} ledger entries must be objects.",
                            path=str(path),
                        )
            for conflict in as_list(payload.get("conflicts")):
                if isinstance(conflict, dict):
                    enriched = dict(conflict)
                    enriched["_path"] = str(path)
                    ledgers["conflicts"].append(enriched)
                else:
                    audit.add(
                        "audit_incomplete",
                        "conflict_entry_invalid",
                        "Conflict entries must be objects.",
                        path=str(path),
                    )
    for packet_id in sorted(set(packets_by_id) - result_packet_ids):
        audit.add(
            "audit_incomplete",
            "review_packet_result_missing",
            "A prepared packet batch has no submitted review result.",
            packet_id=packet_id,
            role=packets_by_id[packet_id]["role"],
        )
    return valid_results, records, ledgers


def apply_review_verdicts(records: list[dict[str, Any]], audit: GateAudit) -> None:
    for record in records:
        verdict = record["verdict"]
        context = {
            "unit_id": record["unit_id"],
            "criterion_id": record["criterion_id"],
            "reviewer_id": record["reviewer_id"],
            "role": record["role"],
        }
        if verdict in FAIL_VERDICTS:
            audit.add(
                "fail",
                "review_failure",
                "A reviewer recorded a contract or quality-gate failure.",
                **context,
            )
        elif verdict in UNCERTAIN_VERDICTS:
            audit.add(
                "clarification_required",
                "review_uncertain",
                "An uncertain reviewer finding cannot be outvoted or treated as a pass.",
                **context,
            )
        elif verdict in EVIDENCE_VERDICTS:
            audit.add(
                "evidence_conflict",
                "review_evidence_conflict",
                "A reviewer recorded an unresolved evidence conflict.",
                **context,
            )
        if record.get("requires_author_action") and verdict not in EVIDENCE_VERDICTS:
            audit.add(
                "clarification_required",
                "author_action_required",
                "A reviewer explicitly requires author adjudication.",
                **context,
            )


def validate_authority_projection_review(
    authority_binding: dict[str, Any],
    results: list[dict[str, Any]],
    ledgers: dict[str, list[Any]],
    audit: GateAudit,
) -> None:
    if not authority_binding:
        return
    candidates: list[dict[str, Any]] = [
        entry
        for entry in ledgers.get("authority_projection_verified", [])
        if isinstance(entry, dict)
    ]
    for result in results:
        value = result.get("authority_projection_verified")
        if isinstance(value, dict):
            enriched = dict(value)
            enriched.setdefault("_role", result.get("_role"))
            candidates.append(enriched)
    accepted = False
    for entry in candidates:
        if normalize_role(entry.get("_role")) != "author_intent_coverage":
            continue
        if (
            ledger_status(entry) in LEDGER_PASS
            and normalized_sha(
                entry.get("authority_source_sha256", entry.get("source_sha256"))
            )
            == authority_binding["sha256"]
            and normalized_sha(entry.get("qa_view_projection_sha256"))
            == authority_binding["qa_view_projection_sha256"]
            and entry.get("intent_revision_id")
            == authority_binding.get("intent_revision_id")
        ):
            accepted = True
            break
    if not accepted:
        audit.add(
            "audit_incomplete",
            "authority_projection_review_missing",
            "Author-Intent reviewer must verify the adapter projection against the current authority source and intent revision.",
            authority_source_sha256=authority_binding["sha256"],
            intent_revision_id=authority_binding.get("intent_revision_id"),
        )


def validate_role_and_unit_coverage(
    units: list[dict[str, Any]],
    required_roles: set[str],
    required_by_unit: dict[str, set[str]],
    results: list[dict[str, Any]],
    records: list[dict[str, Any]],
    audit: GateAudit,
) -> dict[str, Any]:
    complete_roles = {result["_role"] for result in results}
    for role in sorted(required_roles - complete_roles):
        audit.add(
            "audit_incomplete",
            "required_role_missing",
            "A required reviewer role did not submit a complete, fresh result.",
            role=role,
        )

    by_unit_role: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    by_unit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_unit_role[(record["unit_id"], record["role"])].append(record)
        by_unit[record["unit_id"]].append(record)

    targets = [
        unit
        for unit in units
        if unit.get("reader_visible", True) and is_review_target(unit)
    ]
    for unit in targets:
        unit_id = unit["unit_id"]
        if not by_unit[unit_id]:
            audit.add(
                "audit_incomplete",
                "reader_visible_unit_unreviewed",
                "Reader-visible unit has no valid review record.",
                unit_id=unit_id,
            )
        for role in sorted(required_by_unit.get(unit_id, set())):
            if not by_unit_role[(unit_id, role)]:
                audit.add(
                    "audit_incomplete",
                    "required_unit_role_unreviewed",
                    "Reader-visible unit is missing review by an assigned role.",
                    unit_id=unit_id,
                    role=role,
                )

        risk = unit.get("risk") if isinstance(unit.get("risk"), dict) else {}
        high_risk = bool(
            unit.get("high_risk", unit.get("is_high_risk", risk.get("is_high_risk", False)))
        )
        raw_minimum = unit.get(
            "min_independent_reviews",
            risk.get("min_independent_reviews", 2 if high_risk else 1),
        )
        try:
            minimum = int(raw_minimum)
        except (TypeError, ValueError):
            minimum = 0
            audit.add(
                "audit_incomplete",
                "invalid_independent_review_minimum",
                "min_independent_reviews must be an integer.",
                unit_id=unit_id,
            )
        if high_risk:
            minimum = max(2, minimum)
        if minimum > 1:
            reviewer_ids = {record["reviewer_id"] for record in by_unit[unit_id]}
            independence_keys = {
                record["independence_key"]
                for record in by_unit[unit_id]
                if record["independence_key"]
            }
            missing_key_reviewers = sorted(
                {
                    record["reviewer_id"]
                    for record in by_unit[unit_id]
                    if not record["independence_key"]
                }
            )
            if missing_key_reviewers:
                audit.add(
                    "audit_incomplete",
                    "independence_key_missing",
                    "High-risk review cannot prove reviewer isolation without independence_key.",
                    unit_id=unit_id,
                    reviewer_ids=missing_key_reviewers,
                )
            if len(reviewer_ids) < minimum or len(independence_keys) < minimum:
                audit.add(
                    "audit_incomplete",
                    "independent_review_count_insufficient",
                    "High-risk unit lacks the required number of independent reviewers.",
                    unit_id=unit_id,
                    required=minimum,
                    distinct_reviewers=len(reviewer_ids),
                    distinct_independence_keys=len(independence_keys),
                )

    return {
        "reader_visible_units": sum(
            bool(unit.get("reader_visible", True)) for unit in units
        ),
        "review_target_units": len(targets),
        "valid_review_records": len(records),
        "required_roles": sorted(required_roles),
        "complete_roles": sorted(complete_roles),
    }


def list_entries(value: Any, audit: GateAudit, label: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        output: list[dict[str, Any]] = []
        for key, item in value.items():
            if isinstance(item, dict):
                enriched = dict(item)
                enriched.setdefault("id", key)
                output.append(enriched)
            else:
                output.append({"id": key, "value": item})
        return output
    if isinstance(value, list):
        output = []
        for item in value:
            if isinstance(item, dict):
                output.append(item)
            else:
                audit.add(
                    "audit_incomplete",
                    "contract_entry_invalid",
                    f"{label} entries require stable object IDs.",
                    entry=item,
                )
        return output
    audit.add(
        "audit_incomplete",
        "contract_collection_invalid",
        f"{label} must be a list or object.",
    )
    return []


def normalized_slot(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, list):
        return sorted(
            (normalized_slot(item) for item in value),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    if isinstance(value, dict):
        return {key: normalized_slot(item) for key, item in sorted(value.items())}
    return value


def collection_records_conflict(
    left: dict[str, Any], right: dict[str, Any], collection_kind: str
) -> bool:
    """Detect authority-relevant contradictions without treating enrichment as conflict."""

    if collection_kind == "obligation":
        if bool(left.get("required", True)) != bool(right.get("required", True)):
            return True
        slots = (
            ("kind", ("kind", "obligation_type", "type")),
            ("meaning", ("must_express", "required_meaning", "meaning", "proposition", "text")),
            ("claim_type", ("claim_type",)),
            ("evidence", ("evidence_anchors", "evidence_ids")),
        )
    else:
        for field_name, default in (
            ("strictly_before_first_use", False),
            ("must_precede", False),
            ("allow_unused", False),
            ("optional", False),
        ):
            if bool(left.get(field_name, default)) != bool(right.get(field_name, default)):
                return True
        slots = (
            ("term", ("canonical_term", "canonical", "term")),
            ("definition", ("canonical_definition", "definition", "meaning")),
            ("allowed_variants", ("allowed_variants",)),
        )
    for _, aliases in slots:
        left_value = first_present(left, tuple((name,) for name in aliases))
        right_value = first_present(right, tuple((name,) for name in aliases))
        if nonempty(left_value) and nonempty(right_value):
            if canonical_hash(normalized_slot(left_value)) != canonical_hash(
                normalized_slot(right_value)
            ):
                return True
    ignored = {
        "obligation_id",
        "intent_id",
        "definition_id",
        "term_id",
        "id",
        "_id",
    }
    for key in (set(left) & set(right)) - ignored:
        if canonical_hash(normalized_slot(left[key])) != canonical_hash(
            normalized_slot(right[key])
        ):
            return True
    return False


def load_authoritative_evidence_registry(
    qa_contract: dict[str, Any],
    qa_contract_path: Path | None,
    manifest: dict[str, Any],
    manifest_path: Path,
    audit: GateAudit,
) -> dict[str, Any]:
    """Load the live registry and verify every manifest projection exactly."""

    empty_view: dict[str, Any] = {
        "ids": set(),
        "records": [],
        "source": None,
        "sha256": "",
    }

    source = qa_contract.get("evidence_registry_source")
    inputs = manifest.get("inputs")
    manifest_source = (
        inputs.get("evidence_registry") if isinstance(inputs, dict) else None
    )
    manifest_registry_hash = normalized_sha(manifest.get("evidence_registry_sha256"))
    legacy_source = manifest.get("source")
    legacy_projection = (
        legacy_source.get("evidence_registry")
        if isinstance(legacy_source, dict)
        else None
    )
    if legacy_projection not in (None, {}, ""):
        audit.add(
            "audit_incomplete",
            "evidence_registry_projection_location_invalid",
            "Evidence-registry provenance has one canonical location: manifest.inputs.evidence_registry.",
        )
    if source is None:
        if manifest_source not in (None, {}, "") or manifest_registry_hash:
            audit.add(
                "audit_incomplete",
                "evidence_registry_authority_missing",
                "Manifest cannot introduce evidence-registry provenance absent from the hash-bound QA contract.",
            )
        if manifest.get("evidence_registry") not in (None, []):
            audit.add(
                "audit_incomplete",
                "manifest_evidence_registry_unexpected",
                "Manifest evidence_registry must be empty when no authoritative registry is bound.",
            )
        return empty_view
    if not isinstance(source, dict):
        audit.add(
            "audit_incomplete",
            "evidence_registry_source_invalid",
            "qa_contract.evidence_registry_source must bind a JSON path and SHA-256.",
        )
        return empty_view
    authority_base = (
        qa_contract_path.parent if qa_contract_path is not None else manifest_path.parent
    )
    path = resolve_bound_path(source.get("path"), authority_base)
    expected_hash = normalized_sha(source.get("sha256"))
    if path is None or not expected_hash or not path.is_file():
        audit.add(
            "audit_incomplete",
            "evidence_registry_source_invalid",
            "Authoritative evidence registry requires an available path and exact SHA-256.",
            path=str(path) if path is not None else None,
        )
        return empty_view
    if manifest_registry_hash != expected_hash:
        audit.add(
            "audit_incomplete",
            "evidence_registry_manifest_hash_mismatch",
            "manifest.evidence_registry_sha256 must exactly equal the canonical inputs.evidence_registry/live registry hash.",
            expected_sha256=expected_hash,
            manifest_sha256=manifest_registry_hash or None,
        )
        return empty_view
    live_hash = sha256_file(path)
    manifest_binding_ok = isinstance(manifest_source, dict) and (
        resolve_bound_path(manifest_source.get("path"), manifest_path.parent) == path
        and normalized_sha(manifest_source.get("sha256")) == expected_hash
        and manifest_source.get("schema_id") == "evidence-registry/1.0"
        and str(manifest_source.get("status", "")).strip().lower()
        in {"frozen-current", "accepted"}
    )
    if live_hash != expected_hash or not manifest_binding_ok:
        audit.add(
            "audit_incomplete",
            "evidence_registry_binding_stale",
            "Evidence registry must match both its live bytes and the manifest projection.",
            path=str(path),
            expected_sha256=expected_hash,
            actual_sha256=live_hash,
        )
        return empty_view
    payload = load_json_object(path, audit, "authoritative evidence registry")
    if payload is None:
        return empty_view
    approval = payload.get("approval_record")
    approval = approval if isinstance(approval, dict) else {}
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("schema_id") != "evidence-registry/1.0"
        or str(payload.get("status", "")).strip().lower()
        not in {"frozen-current", "accepted"}
        or not nonempty(approval.get("confirmed_by"))
        or not valid_iso8601_timestamp(approval.get("confirmed_at"))
        or not nonempty(approval.get("confirmation_source"))
        or not isinstance(manifest_source, dict)
        or str(manifest_source.get("status", "")).strip().lower()
        != str(payload.get("status", "")).strip().lower()
    ):
        audit.add(
            "audit_incomplete",
            "evidence_registry_authority_invalid",
            "Evidence registry must be a frozen/accepted evidence-registry/1.0 artifact with recoverable confirmation.",
            path=str(path),
        )
        return empty_view
    records = payload.get("evidence")
    if not isinstance(records, list):
        audit.add(
            "audit_incomplete",
            "evidence_registry_records_invalid",
            "Evidence registry requires an evidence array.",
            path=str(path),
        )
        return empty_view
    identifiers: set[str] = set()
    malformed = False
    for record in records:
        if not isinstance(record, dict):
            malformed = True
            continue
        evidence_id = first_present(
            record,
            (("evidence_id",), ("source_id",), ("anchor_id",), ("id",)),
        )
        source_hash = normalized_sha(
            first_present(record, (("source_sha256",), ("sha256",)))
        )
        source_reference = first_present(record, (("source",), ("path",)))
        if (
            not isinstance(evidence_id, str)
            or not evidence_id.strip()
            or evidence_id.strip() in identifiers
            or not source_hash
            or not nonempty(source_reference)
        ):
            malformed = True
            continue
        identifiers.add(evidence_id.strip())
    if malformed:
        audit.add(
            "audit_incomplete",
            "evidence_registry_records_invalid",
            "Each evidence record requires a unique evidence/source ID, a nonempty source/path reference, and source SHA-256.",
            path=str(path),
        )
    manifest_records = manifest.get("evidence_registry")
    if canonical_hash(manifest_records) != canonical_hash(records):
        audit.add(
            "audit_incomplete",
            "manifest_evidence_registry_projection_mismatch",
            "Manifest evidence_registry must exactly project the live registry records, not merely reuse their IDs.",
            path=str(path),
        )
    return {
        "ids": identifiers,
        "records": records,
        "source": {
            "path": str(path),
            "sha256": expected_hash,
            "schema_id": "evidence-registry/1.0",
            "status": str(payload.get("status", "")).strip().lower(),
        },
        "sha256": expected_hash,
    }


def contract_collections(
    state: dict[str, Any],
    author: dict[str, Any],
    qa_contract: dict[str, Any],
    manifest: dict[str, Any],
    manifest_path: Path,
    evidence_view: dict[str, Any],
    audit: GateAudit,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[str], set[str]]:
    author_policy_obligations: list[dict[str, Any]] = []
    for key in (
        "must_preserve",
        "must_not_claim",
        "must_not_imply",
        "forbidden_terms_or_frames",
    ):
        values = author.get(key, [])
        if values is None:
            continue
        values = values if isinstance(values, list) else [values]
        for index, value in enumerate(values, 1):
            author_policy_obligations.append(
                {
                    "obligation_id": stable_id(
                        "obl", key, index, canonical_hash(value)
                    ),
                    "obligation_type": key,
                    "kind": key,
                    "content": value,
                }
            )
    author_obligation_sources: list[tuple[str, Any]] = [
        ("author.propositions", author.get("propositions")),
        ("author.content_obligations", author.get("content_obligations")),
        ("author.policy_obligations", author_policy_obligations),
    ]
    supplemental_obligation_sources: list[tuple[str, Any]] = [
        ("paper_state.content_obligations", state.get("content_obligations")),
        ("qa_contract.content_obligations", qa_contract.get("content_obligations")),
        ("manifest.content_obligations", manifest.get("content_obligations")),
    ]
    obligations: list[dict[str, Any]] = []
    seen: dict[str, tuple[dict[str, Any], str]] = {}
    authoritative_intents: set[str] = set()
    authority_records: dict[str, tuple[dict[str, Any], str]] = {}
    for source_name, source in author_obligation_sources:
        for item in list_entries(source, audit, "content obligations"):
            item_id = first_present(
                item,
                (("obligation_id",), ("intent_id",), ("id",)),
            )
            if not isinstance(item_id, str) or not item_id.strip():
                audit.add(
                    "audit_incomplete",
                    "obligation_id_missing",
                    "Every content obligation requires obligation_id or intent_id.",
                )
                continue
            item_id = item_id.strip()
            if item_id not in seen:
                enriched = dict(item)
                enriched["_id"] = item_id
                obligations.append(enriched)
                seen[item_id] = (dict(item), source_name)
            else:
                previous, previous_source = seen[item_id]
                if collection_records_conflict(previous, item, "obligation"):
                    audit.add(
                        "audit_incomplete",
                        "obligation_authority_conflict",
                        "The same obligation ID has conflicting definitions across authority layers.",
                        obligation_id=item_id,
                        sources=[previous_source, source_name],
                    )
            aliases = {
                str(value).strip()
                for value in (
                    item.get("obligation_id"),
                    item.get("intent_id"),
                    item.get("id"),
                )
                if isinstance(value, str) and value.strip()
            }
            authoritative_intents.update(aliases)
            for alias in aliases:
                authority_records.setdefault(alias, (dict(item), source_name))

    for source_name, source in supplemental_obligation_sources:
        for item in list_entries(source, audit, "content obligations"):
            raw_id = first_present(
                item, (("obligation_id",), ("intent_id",), ("id",))
            )
            trace_candidates = [
                str(value).strip()
                for value in (item.get("intent_id"), raw_id)
                if isinstance(value, str) and value.strip()
            ]
            trace_id = next(
                (value for value in trace_candidates if value in authority_records),
                None,
            )
            if trace_id is None:
                audit.add(
                    "audit_incomplete",
                    "supplemental_obligation_unanchored",
                    "A paper-state or manifest obligation cannot create a new author intent; it must trace to a specific author-owned proposition or obligation ID.",
                    obligation_id=raw_id,
                    source=source_name,
                )
                continue
            authority_record, authority_source = authority_records[trace_id]
            if collection_records_conflict(authority_record, item, "obligation"):
                audit.add(
                    "audit_incomplete",
                    "obligation_authority_conflict",
                    "A supplemental obligation conflicts with the author-owned intent it claims to enrich.",
                    obligation_id=trace_id,
                    sources=[authority_source, source_name],
                )

    raw_author_definitions = author.get(
        "definition_registry", author.get("terminology", [])
    )
    if isinstance(raw_author_definitions, dict):
        normalized_author_definitions: Any = [
            {
                "definition_id": stable_id("def", key),
                "term": key,
                "definition": value,
            }
            for key, value in raw_author_definitions.items()
        ]
    elif isinstance(raw_author_definitions, list):
        normalized_author_definitions = []
        for index, value in enumerate(raw_author_definitions, 1):
            if isinstance(value, dict):
                record = dict(value)
                record.setdefault(
                    "definition_id", record.get("term_id") or f"definition_{index}"
                )
            else:
                record = {"definition_id": f"definition_{index}", "term": value}
            normalized_author_definitions.append(record)
    else:
        normalized_author_definitions = raw_author_definitions
    author_definition_source = (
        "author.definition_registry",
        normalized_author_definitions,
    )
    supplemental_definition_sources = (
        ("paper_state.definition_registry", state.get("definition_registry")),
        ("qa_contract.definition_registry", qa_contract.get("definition_registry")),
        ("manifest.definition_registry", manifest.get("definition_registry")),
    )
    definitions: list[dict[str, Any]] = []
    definition_seen: dict[str, tuple[dict[str, Any], str]] = {}
    source_name, source = author_definition_source
    for item in list_entries(source, audit, "definition registry"):
        item_id = first_present(item, (("definition_id",), ("term_id",), ("id",)))
        if not isinstance(item_id, str) or not item_id.strip():
            audit.add(
                "audit_incomplete",
                "definition_id_missing",
                "Every definition-registry entry requires definition_id or term_id.",
            )
            continue
        item_id = item_id.strip()
        if item_id not in definition_seen:
            enriched = dict(item)
            enriched["_id"] = item_id
            definitions.append(enriched)
            definition_seen[item_id] = (dict(item), source_name)
        else:
            previous, previous_source = definition_seen[item_id]
            if collection_records_conflict(previous, item, "definition"):
                audit.add(
                    "audit_incomplete",
                    "definition_authority_conflict",
                    "The same author-owned definition ID has conflicting definitions.",
                    definition_id=item_id,
                    sources=[previous_source, source_name],
                )

    for source_name, source in supplemental_definition_sources:
        for item in list_entries(source, audit, "definition registry"):
            item_id = first_present(item, (("definition_id",), ("term_id",), ("id",)))
            if not isinstance(item_id, str) or not item_id.strip():
                audit.add(
                    "audit_incomplete",
                    "definition_id_missing",
                    "Every definition-registry entry requires definition_id or term_id.",
                )
                continue
            item_id = item_id.strip()
            if item_id not in definition_seen:
                audit.add(
                    "audit_incomplete",
                    "supplemental_definition_unanchored",
                    "A paper-state or manifest definition cannot introduce a term absent from the author-owned definition registry.",
                    definition_id=item_id,
                    source=source_name,
                )
                continue
            previous, previous_source = definition_seen[item_id]
            if collection_records_conflict(previous, item, "definition"):
                audit.add(
                    "audit_incomplete",
                    "definition_authority_conflict",
                    "A supplemental definition conflicts with its author-owned definition.",
                    definition_id=item_id,
                    sources=[previous_source, source_name],
                )

    # Whole-contract IDs are provenance identifiers, not blanket authorization
    # for arbitrary claims.  Only specific IDs declared in author-owned
    # propositions/content obligations may authorize claim-bearing text.
    known_intents = set(authoritative_intents)

    known_evidence: set[str] = set()

    def add_evidence(values: Any) -> None:
        for value in as_list(values):
            if isinstance(value, str) and value.strip():
                known_evidence.add(value.strip())
            elif isinstance(value, dict):
                identifier = first_present(
                    value,
                    (("evidence_id",), ("anchor_id",), ("id",), ("path",)),
                )
                if isinstance(identifier, str) and identifier.strip():
                    known_evidence.add(identifier.strip())

    source_context = author.get("source_context")
    if isinstance(source_context, dict):
        add_evidence(source_context.get("evidence_anchors"))
    for source in (author.get("propositions"), author.get("content_obligations")):
        for item in list_entries(source, audit, "evidence-bearing obligations"):
            add_evidence(item.get("evidence_anchors", item.get("evidence_ids")))
    known_evidence.update(
        value
        for value in evidence_view.get("ids", set())
        if isinstance(value, str) and value
    )
    manifest_evidence: set[str] = set()
    for value in as_list(manifest.get("evidence_registry")):
        if isinstance(value, str) and value.strip():
            manifest_evidence.add(value.strip())
        elif isinstance(value, dict):
            identifier = first_present(
                value,
                (("evidence_id",), ("source_id",), ("anchor_id",), ("id",)),
            )
            if isinstance(identifier, str) and identifier.strip():
                manifest_evidence.add(identifier.strip())
    unauthorized_projection = manifest_evidence - known_evidence
    if unauthorized_projection:
        audit.add(
            "audit_incomplete",
            "manifest_evidence_registry_unanchored",
            "Manifest evidence_registry may only project IDs from author-owned anchors or the live hash-bound authoritative evidence registry.",
            unknown_evidence_ids=sorted(unauthorized_projection),
        )
    return obligations, definitions, known_intents, known_evidence


def ledger_status(entry: dict[str, Any]) -> str:
    return str(entry.get("status", entry.get("verdict", ""))).strip().lower()


def ledger_blockers(
    entries: Iterable[dict[str, Any]], code_prefix: str, audit: GateAudit
) -> None:
    for entry in entries:
        status = ledger_status(entry)
        if status not in KNOWN_LEDGER_STATUSES:
            audit.add(
                "audit_incomplete",
                f"{code_prefix}_status_invalid",
                "Ledger entry has a missing or unknown status.",
                ledger_entry_id=entry.get("intent_id", entry.get("unit_id", entry.get("definition_id"))),
                ledger_status=status or None,
            )
        elif status in FAIL_VERDICTS:
            audit.add(
                "fail",
                f"{code_prefix}_failed",
                "A ledger entry explicitly records failure.",
                ledger_entry_id=entry.get("intent_id", entry.get("unit_id", entry.get("definition_id"))),
            )
        elif status in UNCERTAIN_VERDICTS:
            audit.add(
                "clarification_required",
                f"{code_prefix}_uncertain",
                "A ledger entry requires author clarification.",
                ledger_entry_id=entry.get("intent_id", entry.get("unit_id", entry.get("definition_id"))),
            )
        elif status in EVIDENCE_VERDICTS:
            audit.add(
                "evidence_conflict",
                f"{code_prefix}_evidence_conflict",
                "A ledger entry records an evidence conflict.",
                ledger_entry_id=entry.get("intent_id", entry.get("unit_id", entry.get("definition_id"))),
            )


def authorized_ledger_entries(
    entries: list[dict[str, Any]],
    expected_role: str,
    ledger_name: str,
    audit: GateAudit,
) -> list[dict[str, Any]]:
    authorized: list[dict[str, Any]] = []
    for entry in entries:
        if normalize_role(entry.get("_role")) != expected_role:
            audit.add(
                "audit_incomplete",
                "ledger_role_unauthorized",
                "Ledger entry was supplied by a role without authority for that ledger.",
                ledger=ledger_name,
                expected_role=expected_role,
                actual_role=normalize_role(entry.get("_role")) or None,
                unit_id=entry.get("unit_id"),
                intent_id=entry.get("intent_id"),
                definition_id=entry.get("definition_id"),
            )
            continue
        authorized.append(entry)
    return authorized


def deletion_is_authorized(
    authorization: Any,
    artifact_contract: dict[str, Any],
    source_block_id: str,
) -> bool:
    if not isinstance(authorization, dict):
        return False
    status = str(authorization.get("status", "")).strip().lower()
    explicitly_approved = authorization.get("approved") is True or status in {
        "approved",
        "authorized",
    }
    approver = first_present(
        authorization,
        (("approved_by",), ("authorized_by",), ("confirmed_by",), ("author",)),
    )
    approved_at = first_present(
        authorization,
        (("approved_at",), ("authorized_at",), ("confirmed_at",)),
    )
    source = first_present(
        authorization,
        (("confirmation_source",), ("authorization_source",), ("source",)),
    )
    scope = authorization.get("approved_scope", authorization.get("scope", []))
    if isinstance(scope, str):
        scope = [scope]
    scopes = {
        str(value).strip().lower()
        for value in scope
        if str(value).strip()
    } if isinstance(scope, list) else set()
    scoped = bool(
        {"all", "delete", "deletion", f"delete:{source_block_id.lower()}"} & scopes
        or source_block_id.lower() in scopes
    )
    artifact_approval = artifact_contract.get("approval_record")
    if not isinstance(artifact_approval, dict):
        return False
    approval_id = authorization.get("approval_id")
    artifact_approval_id = artifact_approval.get("approval_id")
    same_record = canonical_hash(authorization) == canonical_hash(artifact_approval)
    same_id = nonempty(approval_id) and approval_id == artifact_approval_id
    return bool(
        explicitly_approved
        and nonempty(approver)
        and nonempty(approved_at)
        and nonempty(source)
        and scoped
        and (same_record or same_id)
    )


def validate_baseline_conservation(
    artifact_contract: dict[str, Any],
    ledgers: dict[str, list[Any]],
    fresh_conservation_gate_status: str,
    upstream_block_binding: dict[str, dict[str, Any]],
    audit: GateAudit,
) -> None:
    if not artifact_requires_conservation(artifact_contract):
        return
    if fresh_conservation_gate_status and fresh_conservation_gate_status != "pass":
        # A fresh canonical non-pass report is already the authoritative
        # delivery blocker.  Do not mask it with downstream pass-path checks.
        return
    entries = [
        entry for entry in ledgers["baseline_to_candidate"] if isinstance(entry, dict)
    ]
    ledger_blockers(entries, "baseline_to_candidate", audit)
    if not entries:
        audit.add(
            "audit_incomplete",
            "baseline_conservation_ledger_missing",
            "Mature revision requires a nonempty baseline_to_candidate conservation ledger.",
        )
    entries_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        source_id = entry.get("source_block_id")
        if isinstance(source_id, str) and source_id:
            entries_by_source[source_id].append(entry)
    expected_ids = set(upstream_block_binding)
    actual_ids = set(entries_by_source)
    duplicates = sorted(
        source_id
        for source_id, source_entries in entries_by_source.items()
        if len(source_entries) != 1
    )
    if duplicates or actual_ids != expected_ids:
        audit.add(
            "audit_incomplete",
            "baseline_conservation_coverage_mismatch",
            "Manifest/reviewer baseline ledger must cover the upstream baseline block universe exactly once and no others.",
            missing_ids=sorted(expected_ids - actual_ids),
            unknown_ids=sorted(actual_ids - expected_ids),
            duplicate_ids=duplicates,
        )
    for entry in entries:
        status = ledger_status(entry)
        if status not in LEDGER_PASS:
            continue
        source_block_id = entry.get("source_block_id")
        disposition = normalize_role(entry.get("disposition"))
        if not nonempty(source_block_id) or not disposition:
            audit.add(
                "audit_incomplete",
                "baseline_conservation_entry_invalid",
                "Passing baseline ledger entry requires source_block_id and disposition.",
                source_block_id=source_block_id,
            )
            continue
        deletion = disposition in {"deleted", "delete", "removed", "omitted"}
        destination = first_present(
            entry,
            (
                ("destination_block_id",),
                ("destination",),
                ("destination_unit_ids",),
                ("candidate_unit_ids",),
            ),
        )
        upstream = upstream_block_binding.get(str(source_block_id))
        disposition_aliases = {
            "preserved": "unchanged",
            "retained": "retained",
            "delete": "deleted",
            "removed": "deleted",
            "omitted": "deleted",
            "move_appendix": "moved_appendix",
            "moved_to_appendix": "moved_appendix",
        }
        normalized_disposition = disposition_aliases.get(disposition, disposition)
        if upstream is not None and (
            normalized_disposition != upstream.get("disposition")
            or (destination or None) != upstream.get("destination_block_id")
        ):
            audit.add(
                "audit_incomplete",
                "baseline_conservation_upstream_mismatch",
                "Manifest/reviewer ledger disposition must exactly match the fresh deterministic block validation.",
                source_block_id=source_block_id,
            )
        deletion_authority = first_present(
            entry,
            (
                ("deletion_authorization",),
                ("authorization_evidence",),
                ("approval_record",),
                ("author_approval",),
            ),
        )
        if deletion and not deletion_is_authorized(
            deletion_authority, artifact_contract, str(source_block_id)
        ):
            audit.add(
                "audit_incomplete",
                "baseline_deletion_unauthorized",
                "Deleted baseline block requires explicit, scoped, recoverable author approval bound to the artifact contract.",
                source_block_id=source_block_id,
            )
        elif not deletion and not nonempty(destination):
            audit.add(
                "audit_incomplete",
                "baseline_destination_missing",
                "Preserved, reordered, or moved baseline block requires a candidate destination.",
                source_block_id=source_block_id,
            )
    if fresh_conservation_gate_status != "pass":
        audit.add(
            "audit_incomplete",
            "mature_conservation_gate_missing",
            "Mature revision requires a fresh passing deterministic conservation gate.",
        )


def validate_intent_ledgers(
    obligations: list[dict[str, Any]],
    known_intents: set[str],
    units: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    ledgers: dict[str, list[Any]],
    qa_mode: str,
    affected_intent_ids: set[str],
    packets_by_id: dict[str, dict[str, Any]],
    audit: GateAudit,
) -> None:
    intent_entries = authorized_ledger_entries(
        [item for item in ledgers["intent_to_text"] if isinstance(item, dict)],
        "author_intent_coverage",
        "intent_to_text",
        audit,
    )
    text_entries = authorized_ledger_entries(
        [item for item in ledgers["text_to_intent"] if isinstance(item, dict)],
        "author_intent_coverage",
        "text_to_intent",
        audit,
    )
    ledger_blockers(intent_entries, "intent_to_text", audit)
    ledger_blockers(text_entries, "text_to_intent", audit)

    by_intent: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in intent_entries:
        intent_id = entry.get("intent_id", entry.get("obligation_id"))
        if isinstance(intent_id, str):
            by_intent[intent_id].append(entry)
        else:
            audit.add(
                "audit_incomplete",
                "intent_ledger_id_missing",
                "intent_to_text entry requires intent_id or obligation_id.",
            )

    target_units = [unit for unit in units if is_review_target(unit)]
    assigned_intents = {
        value
        for unit in target_units
        for value in as_list(unit.get("intent_ids"))
        if isinstance(value, str)
    }
    negative_kinds = {
        "prohibited",
        "must_not_claim",
        "must_not_imply",
        "forbidden",
        "forbidden_terms_or_frames",
        "negative",
    }
    for obligation in obligations:
        if obligation.get("required", True) is False:
            continue
        kind = str(
            obligation.get(
                "kind",
                obligation.get("obligation_type", obligation.get("type", "required")),
            )
        ).lower()
        intent_id = obligation["_id"]
        if kind in negative_kinds:
            author_packets = {
                packet_id: packet
                for packet_id, packet in packets_by_id.items()
                if packet.get("role") == "author_intent_coverage"
            }
            verified_packets: set[str] = set()
            for entry in by_intent.get(intent_id, []):
                if (
                    ledger_status(entry) not in {"verified_absent", "compliant"}
                    or normalize_role(entry.get("_role"))
                    != "author_intent_coverage"
                ):
                    continue
                packet_id = entry.get("_packet_id")
                packet = author_packets.get(packet_id)
                if packet is None:
                    continue
                explicit_binding = (
                    entry.get("packet_id") == packet_id
                    and normalized_sha(entry.get("packet_sha256"))
                    == packet.get("packet_sha256")
                )
                scoped_units = {
                    value
                    for value in as_list(entry.get("unit_ids"))
                    if isinstance(value, str) and value
                }
                full_packet_scope = scoped_units == set(packet.get("unit_ids", set()))
                if explicit_binding or full_packet_scope:
                    verified_packets.add(str(packet_id))
            missing_packets = sorted(set(author_packets) - verified_packets)
            if missing_packets:
                audit.add(
                    "audit_incomplete",
                    "negative_obligation_unverified",
                    "Every Author-Intent packet must explicitly attest that the prohibited meaning is absent across its complete packet scope.",
                    intent_id=intent_id,
                    missing_packet_ids=missing_packets,
                )
            continue
        if (
            qa_mode != "exhaustive"
            and intent_id not in assigned_intents
            and intent_id not in affected_intent_ids
        ):
            continue
        candidates = [entry for entry in by_intent.get(intent_id, []) if ledger_status(entry) in LEDGER_PASS]
        if not candidates:
            audit.add(
                "audit_incomplete",
                "intent_obligation_unmapped",
                "Required content obligation lacks a passing intent-to-text location.",
                intent_id=intent_id,
            )
            continue
        valid_location = False
        for entry in candidates:
            unit_ids = as_list(entry.get("unit_ids", entry.get("draft_unit_ids")))
            if unit_ids and all(isinstance(value, str) and value in by_id for value in unit_ids):
                valid_location = True
            else:
                audit.add(
                    "audit_incomplete",
                    "intent_location_invalid",
                    "intent_to_text location must contain valid manifest unit IDs.",
                    intent_id=intent_id,
                )
        if not valid_location:
            audit.add(
                "audit_incomplete",
                "intent_obligation_location_missing",
                "Required content obligation has no valid draft location.",
                intent_id=intent_id,
            )

    unknown_affected = affected_intent_ids - known_intents
    if unknown_affected:
        audit.add(
            "audit_incomplete",
            "bounded_affected_intent_unknown",
            "affected_intent_ids must refer to author-owned intent or obligation IDs.",
            unknown_intent_ids=sorted(unknown_affected),
        )
    for intent_id in sorted(affected_intent_ids & known_intents):
        valid_units = {
            unit_id
            for entry in by_intent.get(intent_id, [])
            if ledger_status(entry) in LEDGER_PASS
            for unit_id in as_list(entry.get("unit_ids", entry.get("draft_unit_ids")))
            if isinstance(unit_id, str)
            and unit_id in by_id
            and is_review_target(by_id[unit_id])
        }
        if not valid_units:
            audit.add(
                "audit_incomplete",
                "bounded_affected_intent_unreviewed",
                "Every affected author intent requires a passing intent-to-text location in the selected bounded review scope.",
                intent_id=intent_id,
            )

    by_unit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in text_entries:
        unit_id = entry.get("unit_id")
        if isinstance(unit_id, str) and unit_id in by_id:
            by_unit[unit_id].append(entry)
        else:
            audit.add(
                "audit_incomplete",
                "text_intent_unit_invalid",
                "text_to_intent entry requires a valid manifest unit_id.",
                unit_id=unit_id,
            )

    for unit in units:
        if (
            not unit.get("reader_visible", True)
            or not is_review_target(unit)
            or unit.get("requires_intent_mapping", True) is False
        ):
            continue
        unit_id = unit["unit_id"]
        candidates = [
            entry
            for entry in by_unit.get(unit_id, [])
            if ledger_status(entry) in LEDGER_PASS | LEDGER_NONCLAIM
        ]
        if not candidates:
            audit.add(
                "audit_incomplete",
                "text_intent_mapping_missing",
                "Every reader-visible unit must be authorized or explicitly classified as non-claim.",
                unit_id=unit_id,
            )
            continue
        valid = False
        expected_ids = {
            value for value in as_list(unit.get("intent_ids")) if isinstance(value, str)
        }
        for entry in candidates:
            status = ledger_status(entry)
            mapped_ids = {
                value
                for value in as_list(entry.get("intent_ids", entry.get("intent_id")))
                if isinstance(value, str) and value.strip()
            }
            if status in LEDGER_NONCLAIM:
                if expected_ids:
                    audit.add(
                        "audit_incomplete",
                        "assigned_intent_marked_nonclaim",
                        "Unit with manifest-assigned intent_ids cannot be classified as non_claim.",
                        unit_id=unit_id,
                        assigned_intent_ids=sorted(expected_ids),
                    )
                    continue
                valid = True
                continue
            if not mapped_ids:
                audit.add(
                    "audit_incomplete",
                    "authorized_text_without_intent",
                    "Authorized text_to_intent entry must identify at least one intent ID.",
                    unit_id=unit_id,
                )
                continue
            unknown = mapped_ids - known_intents
            if unknown:
                audit.add(
                    "audit_incomplete",
                    "unknown_intent_mapping",
                    "text_to_intent entry references unknown intent IDs.",
                    unit_id=unit_id,
                    unknown_intent_ids=sorted(unknown),
                )
                continue
            if expected_ids and not expected_ids.issubset(mapped_ids):
                audit.add(
                    "audit_incomplete",
                    "manifest_intent_mapping_missing",
                    "text_to_intent entry omits an intent ID assigned by the manifest.",
                    unit_id=unit_id,
                    missing_intent_ids=sorted(expected_ids - mapped_ids),
                )
                continue
            valid = True
        if not valid:
            audit.add(
                "audit_incomplete",
                "text_intent_mapping_invalid",
                "Reader-visible unit has no valid text-to-intent authorization record.",
                unit_id=unit_id,
            )


def unit_requires_evidence(unit: dict[str, Any]) -> bool:
    explicit = unit.get("requires_evidence_mapping")
    if isinstance(explicit, bool):
        return explicit
    explicit_claim = unit.get("claim_bearing")
    if isinstance(explicit_claim, bool):
        return explicit_claim
    if any(
        isinstance(value, str) and value.strip()
        for value in as_list(unit.get("intent_ids"))
    ):
        return True
    risk = unit.get("risk") if isinstance(unit.get("risk"), dict) else {}
    categories = {
        normalize_role(value)
        for value in as_list(risk.get("categories", unit.get("risk_flags")))
        if isinstance(value, str)
    }
    evidence_categories = {
        "claim",
        "causal",
        "causal_claim",
        "mechanism",
        "mechanism_claim",
        "numeric",
        "number",
        "quantitative",
        "factual",
        "fact",
        "evidence",
        "contract_marked",
        "definition_claim",
    }
    return bool(categories & evidence_categories)


def validate_evidence_ledger(
    units: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
    ledgers: dict[str, list[Any]],
    known_evidence: set[str],
    audit: GateAudit,
) -> None:
    entries = authorized_ledger_entries(
        [item for item in ledgers["text_to_evidence"] if isinstance(item, dict)],
        "evidence_claim_strength",
        "text_to_evidence",
        audit,
    )
    ledger_blockers(entries, "text_to_evidence", audit)
    by_unit: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        unit_id = entry.get("unit_id")
        if isinstance(unit_id, str) and unit_id in by_id:
            by_unit[unit_id].append(entry)
        else:
            audit.add(
                "audit_incomplete",
                "text_evidence_unit_invalid",
                "text_to_evidence entry requires a valid manifest unit_id.",
                unit_id=unit_id,
            )

    review_roles_by_unit: dict[str, set[str]] = defaultdict(set)
    for record in records:
        review_roles_by_unit[record["unit_id"]].add(record["role"])

    for unit in units:
        if (
            not unit.get("reader_visible", True)
            or not is_review_target(unit)
            or not unit_requires_evidence(unit)
        ):
            continue
        unit_id = unit["unit_id"]
        if not known_evidence:
            audit.add(
                "audit_incomplete",
                "frozen_evidence_registry_empty",
                "Evidence-requiring unit cannot accept arbitrary anchors when the frozen evidence registry is empty.",
                unit_id=unit_id,
            )
        candidates = [
            entry
            for entry in by_unit.get(unit_id, [])
            if ledger_status(entry) in LEDGER_PASS
        ]
        if not candidates:
            audit.add(
                "audit_incomplete",
                "text_evidence_mapping_missing",
                "Evidence-requiring claim unit lacks a passing text-to-evidence ledger entry.",
                unit_id=unit_id,
            )
        valid_mapping = False
        for entry in candidates:
            raw_anchors = first_present(
                entry,
                (("evidence_ids",), ("evidence_anchors",), ("evidence_id",), ("anchors",)),
            )
            anchors = {
                value.strip()
                for value in as_list(raw_anchors)
                if isinstance(value, str) and value.strip()
            }
            if not anchors:
                audit.add(
                    "audit_incomplete",
                    "text_evidence_anchor_missing",
                    "Passing text_to_evidence entry must identify at least one evidence anchor.",
                    unit_id=unit_id,
                )
                continue
            unknown = anchors - known_evidence
            if unknown:
                audit.add(
                    "audit_incomplete",
                    "unknown_evidence_anchor",
                    "text_to_evidence entry references anchors absent from the frozen contract/registry.",
                    unit_id=unit_id,
                    unknown_evidence_ids=sorted(unknown),
                )
                continue
            valid_mapping = True
        if candidates and not valid_mapping:
            audit.add(
                "audit_incomplete",
                "text_evidence_mapping_invalid",
                "Evidence-requiring claim unit has no valid evidence mapping.",
                unit_id=unit_id,
            )
        if not any("evidence" in role for role in review_roles_by_unit.get(unit_id, set())):
            audit.add(
                "audit_incomplete",
                "evidence_role_review_missing",
                "Evidence-requiring claim unit lacks a fresh Evidence and Claim Strength review.",
                unit_id=unit_id,
            )


def validate_definitions(
    definitions: list[dict[str, Any]],
    by_id: dict[str, dict[str, Any]],
    records: list[dict[str, Any]],
    ledgers: dict[str, list[Any]],
    qa_mode: str,
    audit: GateAudit,
) -> None:
    entries = authorized_ledger_entries(
        [item for item in ledgers["definitions"] if isinstance(item, dict)],
        "definitions_reader_sufficiency",
        "definitions",
        audit,
    )
    ledger_blockers(entries, "definition", audit)
    by_definition: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in entries:
        definition_id = first_present(entry, (("definition_id",), ("term_id",), ("id",)))
        if isinstance(definition_id, str):
            by_definition[definition_id].append(entry)
        else:
            audit.add(
                "audit_incomplete",
                "definition_ledger_id_missing",
                "Definition ledger entry requires definition_id or term_id.",
            )

    target_definition_ids = {
        value
        for unit in by_id.values()
        if is_review_target(unit)
        for value in as_list(unit.get("definition_ids"))
        if isinstance(value, str)
    }
    definition_role_units = {
        record["unit_id"]
        for record in records
        if record.get("role") == "definitions_reader_sufficiency"
    }
    definition_passes: dict[tuple[str, str], bool] = defaultdict(bool)
    for record in records:
        if (
            record.get("role") == "definitions_reader_sufficiency"
            and record.get("criterion_id")
            in {"definition_before_use", "definition_sufficiency"}
            and record.get("verdict") == "pass"
        ):
            definition_passes[
                (record["unit_id"], record["criterion_id"])
            ] = True
    for definition in definitions:
        definition_id = definition["_id"]
        if qa_mode != "exhaustive" and definition_id not in target_definition_ids:
            continue
        candidates = by_definition.get(definition_id, [])
        use_units = sorted(
            (
                unit
                for unit in by_id.values()
                if is_review_target(unit)
                and definition_id
                in {
                    value
                    for value in as_list(unit.get("definition_ids"))
                    if isinstance(value, str)
                }
            ),
            key=lambda item: item["_order"],
        )
        deterministic_first_use_id = (
            use_units[0]["unit_id"] if use_units else None
        )
        if not candidates:
            audit.add(
                "audit_incomplete",
                "definition_audit_missing",
                "Definition-registry entry lacks a deterministic first-use audit record.",
                definition_id=definition_id,
            )
            continue
        accepted = False
        deterministically_closed = False
        for entry in candidates:
            status = ledger_status(entry)
            if status in {"unused", "not_used"}:
                if deterministic_first_use_id is not None:
                    audit.add(
                        "audit_incomplete",
                        "definition_unused_claim_false",
                        "Definition ledger marks a term unused even though the manifest records a selected use.",
                        definition_id=definition_id,
                        first_use_unit_id=deterministic_first_use_id,
                    )
                elif definition.get("allow_unused", definition.get("optional", False)):
                    accepted = True
                    deterministically_closed = True
                else:
                    audit.add(
                        "audit_incomplete",
                        "required_definition_marked_unused",
                        "A required definition cannot be closed as unused.",
                        definition_id=definition_id,
                )
                continue
            if status not in LEDGER_PASS | {"defined_before_use"}:
                if status in FAIL_VERDICTS | UNCERTAIN_VERDICTS | EVIDENCE_VERDICTS:
                    deterministically_closed = True
                continue
            definition_unit_id = entry.get("definition_unit_id")
            first_use_unit_id = entry.get("first_use_unit_id")
            if definition_unit_id not in by_id or first_use_unit_id not in by_id:
                audit.add(
                    "audit_incomplete",
                    "definition_unit_mapping_invalid",
                    "Definition ledger must identify valid definition and first-use units.",
                    definition_id=definition_id,
                )
                continue
            if first_use_unit_id != deterministic_first_use_id:
                audit.add(
                    "audit_incomplete",
                    "definition_first_use_mismatch",
                    "Definition ledger first_use_unit_id must equal the earliest selected manifest unit carrying that definition ID.",
                    definition_id=definition_id,
                    reported_first_use_unit_id=first_use_unit_id,
                    expected_first_use_unit_id=deterministic_first_use_id,
                )
                continue
            definition_unit_ids = {
                value
                for value in as_list(by_id[definition_unit_id].get("definition_ids"))
                if isinstance(value, str)
            }
            if definition_id not in definition_unit_ids:
                audit.add(
                    "audit_incomplete",
                    "definition_unit_marker_missing",
                    "Reported definition unit does not carry the manifest's definition marker.",
                    definition_id=definition_id,
                    definition_unit_id=definition_unit_id,
                )
                continue
            deterministically_closed = True
            definition_order = by_id[definition_unit_id]["_order"]
            first_use_order = by_id[first_use_unit_id]["_order"]
            missing_role_units = {
                definition_unit_id,
                first_use_unit_id,
            } - definition_role_units
            if missing_role_units:
                audit.add(
                    "audit_incomplete",
                    "definition_role_review_missing",
                    "Definition and first-use units both require Definitions and Reader Sufficiency review.",
                    definition_id=definition_id,
                    unit_ids=sorted(missing_role_units),
                )
                continue
            if not (
                definition_passes[(definition_unit_id, "definition_sufficiency")]
                and definition_passes[(first_use_unit_id, "definition_before_use")]
            ):
                audit.add(
                    "audit_incomplete",
                    "definition_criterion_review_missing",
                    "Definition unit and deterministic first-use unit require explicit passing sufficiency/before-use criteria.",
                    definition_id=definition_id,
                    definition_unit_id=definition_unit_id,
                    first_use_unit_id=first_use_unit_id,
                )
                continue
            strict = bool(
                definition.get("strictly_before_first_use", definition.get("must_precede", False))
            )
            ordered = definition_order < first_use_order if strict else definition_order <= first_use_order
            if not ordered:
                audit.add(
                    "fail",
                    "definition_after_first_use",
                    "Definition ledger places a required definition after its first use.",
                    definition_id=definition_id,
                    definition_unit_id=definition_unit_id,
                    first_use_unit_id=first_use_unit_id,
                )
                continue
            accepted = True
        if not accepted and not deterministically_closed:
            audit.add(
                "audit_incomplete",
                "definition_audit_not_closed",
                "Definition-registry entry has no valid, passing first-use record.",
                definition_id=definition_id,
            )


def revision_scope(
    manifest: dict[str, Any]
) -> tuple[str, set[str], set[str]]:
    revision = first_present(
        manifest,
        (("revision_scope",), ("revision",), ("change_control",)),
    )
    if not isinstance(revision, dict):
        return "", set(), set()
    revision_id = first_present(
        revision,
        (("revision_id",), ("current_revision_id",), ("patch_id",)),
    )
    changed = {
        value
        for value in as_list(revision.get("changed_unit_ids", revision.get("changed_units")))
        if isinstance(value, str)
    }
    dependencies = {
        value
        for value in as_list(
            revision.get("dependency_unit_ids", revision.get("dependent_unit_ids"))
        )
        if isinstance(value, str)
    }
    return revision_id if isinstance(revision_id, str) else "", changed, dependencies


def validate_revision_rechecks(
    manifest: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    required_by_unit: dict[str, set[str]],
    records: list[dict[str, Any]],
    ledgers: dict[str, list[Any]],
    audit: GateAudit,
) -> None:
    revision_id, changed, dependencies = revision_scope(manifest)
    bounded_mode = str(manifest.get("qa_mode", "")).strip().lower() == "bounded_change"
    targets = (
        {
            value
            for value in as_list(manifest.get("revision_target_unit_ids"))
            if isinstance(value, str) and value
        }
        if bounded_mode
        else set(changed | dependencies)
    )
    dependency_graph: dict[str, set[str]] = defaultdict(set)
    for unit_id, unit in by_id.items():
        declared_dependencies = {
            value
            for field_name in (
                "dependency_unit_ids",
                "footnote_target_unit_ids",
                "referenced_by_unit_ids",
            )
            for value in as_list(unit.get(field_name))
            if isinstance(value, str) and value
        }
        unknown_dependencies = declared_dependencies - set(by_id)
        if unknown_dependencies:
            audit.add(
                "audit_incomplete",
                "manifest_dependency_unit_unknown",
                "Manifest unit dependency references an unknown unit.",
                unit_id=unit_id,
                dependency_unit_ids=sorted(unknown_dependencies),
            )
        for dependency_id in declared_dependencies & set(by_id):
            dependency_graph[unit_id].add(dependency_id)
            dependency_graph[dependency_id].add(unit_id)
    frontier = [] if bounded_mode else list(targets)
    while frontier:
        unit_id = frontier.pop()
        for dependency_id in dependency_graph.get(unit_id, set()):
            if dependency_id not in targets:
                targets.add(dependency_id)
                frontier.append(dependency_id)
    if not targets:
        return
    if not revision_id:
        audit.add(
            "audit_incomplete",
            "revision_id_missing",
            "Changed/dependency units require a current revision_id.",
        )
    unknown = targets - set(by_id)
    if unknown:
        audit.add(
            "audit_incomplete",
            "revision_unit_unknown",
            "Revision scope references units absent from the current manifest.",
            unit_ids=sorted(unknown),
        )

    rechecks: dict[str, list[dict[str, Any]]] = defaultdict(list)
    recheck_entries = [
        entry for entry in ledgers["revision_rechecks"] if isinstance(entry, dict)
    ]
    ledger_blockers(recheck_entries, "revision_recheck", audit)
    for entry in recheck_entries:
        if isinstance(entry, dict) and isinstance(entry.get("unit_id"), str):
            rechecks[entry["unit_id"]].append(entry)
    records_by_unit_role: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        records_by_unit_role[(record["unit_id"], record["role"])].append(record)

    for unit_id in sorted(targets & set(by_id)):
        unit = by_id[unit_id]
        passing_rechecks = []
        current_entries = []
        for entry in rechecks.get(unit_id, []):
            if entry.get("revision_id") != revision_id:
                continue
            if normalized_sha(entry.get("text_sha256")) != normalized_sha(unit.get("text_sha256")):
                continue
            current_entries.append(entry)
            status = ledger_status(entry)
            if status not in LEDGER_PASS | {"rechecked", "reviewed"}:
                continue
            passing_rechecks.append(entry)
        has_blocker = any(
            ledger_status(entry)
            in FAIL_VERDICTS | UNCERTAIN_VERDICTS | EVIDENCE_VERDICTS
            for entry in current_entries
        )
        if not passing_rechecks and not has_blocker:
            audit.add(
                "audit_incomplete",
                "revision_recheck_missing",
                "Changed or dependent unit lacks a recheck for its current text hash and revision.",
                unit_id=unit_id,
                revision_id=revision_id or None,
            )
        for role in sorted(required_by_unit.get(unit_id, set())):
            fresh = [
                record
                for record in records_by_unit_role[(unit_id, role)]
                if record.get("revision_id") == revision_id
            ]
            if not fresh:
                audit.add(
                    "audit_incomplete",
                    "revision_role_reaudit_missing",
                    "Changed or dependent unit was not re-audited by every assigned role.",
                    unit_id=unit_id,
                    role=role,
                    revision_id=revision_id or None,
                )


def load_conflict_resolutions(
    values: Sequence[str],
    manifest_id: str,
    manifest_hash: str,
    contract_path: Path,
    contract_hash: str,
    intent_revision_id: Any,
    qa_contract: dict[str, Any],
    qa_contract_path: Path | None,
    upstream_gate_paths: list[Path],
    results: list[dict[str, Any]],
    packet_assignments: dict[str, dict[str, Any]],
    main_assignment: dict[str, Any] | None,
    audit: GateAudit,
) -> dict[str, dict[str, Any]]:
    resolutions: dict[str, dict[str, Any]] = {}
    reviewer_agents = {
        value
        for result in results
        for value in (result.get("_native_agent_id"), result.get("_task_id"))
        if isinstance(value, str) and value
    }
    for assignment in [*packet_assignments.values(), main_assignment]:
        if not isinstance(assignment, dict):
            continue
        reviewer_agents.update(
            value
            for value in (
                assignment.get("native_agent_id"),
                assignment.get("task_id"),
            )
            if isinstance(value, str) and value
        )
    evidence_source = qa_contract.get("evidence_registry_source")
    evidence_path = (
        resolve_bound_path(
            evidence_source.get("path"),
            qa_contract_path.parent if qa_contract_path is not None else Path.cwd(),
        )
        if isinstance(evidence_source, dict)
        else None
    )
    evidence_hash = (
        normalized_sha(evidence_source.get("sha256"))
        if isinstance(evidence_source, dict)
        else ""
    )
    upstream_bindings = {str(path): sha256_file(path) for path in upstream_gate_paths}
    for raw in values:
        path = Path(raw).expanduser().resolve()
        payload = (
            load_json_object(path, audit, "conflict-resolution artifact")
            if path.is_file()
            else None
        )
        if payload is None:
            if not path.is_file():
                audit.add(
                    "audit_incomplete",
                    "conflict_resolution_artifact_missing",
                    "Conflict-resolution artifact is unavailable.",
                    path=str(path),
                )
            continue
        conflict_id = payload.get("conflict_id")
        valid = require_schema(payload, audit, "Conflict resolution", path)
        if (
            payload.get("schema_id") != "qa-conflict-resolution/1.0"
            or str(payload.get("status", "")).strip().lower() != "resolved"
            or not isinstance(conflict_id, str)
            or not conflict_id.strip()
            or not nonempty(payload.get("resolution_id"))
            or payload.get("manifest_id") != manifest_id
            or normalized_sha(payload.get("manifest_sha256")) != manifest_hash
            or not normalized_sha(payload.get("conflict_sha256"))
            or not nonempty(payload.get("resolved_by"))
            or not valid_iso8601_timestamp(payload.get("resolved_at"))
            or not nonempty(payload.get("resolver_native_agent_id"))
            or not nonempty(payload.get("resolver_task_id"))
            or not nonempty(payload.get("resolution"))
        ):
            valid = False
        if (
            payload.get("resolver_native_agent_id") in reviewer_agents
            or payload.get("resolver_task_id") in reviewer_agents
        ):
            valid = False
        authority = normalize_role(payload.get("resolution_authority"))
        authority_record = payload.get("authority_artifact")
        authority_record = authority_record if isinstance(authority_record, dict) else {}
        authority_path = resolve_bound_path(
            authority_record.get("path"), path.parent
        )
        authority_hash = normalized_sha(authority_record.get("sha256"))
        authority_live = (
            authority_path is not None
            and authority_path.is_file()
            and authority_hash
            and sha256_file(authority_path) == authority_hash
        )
        if authority in {"author", "author_intent", "definition"}:
            authority_valid = (
                authority_live
                and authority_path == contract_path
                and authority_hash == contract_hash
                and authority_record.get("revision_id") == intent_revision_id
            )
        elif authority == "evidence":
            authority_valid = (
                authority_live
                and evidence_path is not None
                and authority_path == evidence_path
                and authority_hash == evidence_hash
            )
        elif authority == "deterministic_gate":
            authority_valid = bool(
                authority_live
                and authority_path is not None
                and upstream_bindings.get(str(authority_path)) == authority_hash
            )
        else:
            authority_valid = False
        resolution_text = json.dumps(
            payload.get("resolution"), ensure_ascii=False, sort_keys=True
        )
        if re.search(
            r"\b(?:majority|vote|voting|consensus[- ]?count)\b|多数票|投票|票决",
            f"{authority} {resolution_text}",
            flags=re.IGNORECASE,
        ):
            authority_valid = False
        if not valid or not authority_valid:
            audit.add(
                "audit_incomplete",
                "conflict_resolution_artifact_invalid",
                "Conflict closure requires an independent, manifest-bound resolution artifact backed by a live authoritative artifact.",
                path=str(path),
                conflict_id=conflict_id,
            )
            continue
        if conflict_id in resolutions:
            audit.add(
                "audit_incomplete",
                "conflict_resolution_duplicate",
                "Each conflict may have exactly one external resolution artifact.",
                conflict_id=conflict_id,
            )
            continue
        payload = dict(payload)
        payload["_path"] = str(path)
        resolutions[conflict_id] = payload
    return resolutions


def validate_conflicts(
    conflicts: list[Any],
    resolutions: dict[str, dict[str, Any]],
    audit: GateAudit,
) -> None:
    conflict_ids: set[str] = set()
    for entry in conflicts:
        if not isinstance(entry, dict):
            continue
        conflict_id = entry.get("conflict_id", entry.get("id"))
        if not isinstance(conflict_id, str) or not conflict_id.strip():
            audit.add(
                "audit_incomplete",
                "conflict_id_missing",
                "Every conflict record requires conflict_id.",
            )
            continue
        if conflict_id in conflict_ids:
            audit.add(
                "audit_incomplete",
                "duplicate_conflict_id",
                "Conflict IDs must be unique across review results.",
                conflict_id=conflict_id,
            )
            continue
        conflict_ids.add(conflict_id)
        status = str(entry.get("status", "")).strip().lower()
        if status in {"closed", "resolved"}:
            audit.add(
                "audit_incomplete",
                "reviewer_self_closed_conflict",
                "Reviewer findings cannot close their own conflict; closure must be a separate independent resolution artifact.",
                conflict_id=conflict_id,
            )
            continue
        if conflict_id in resolutions:
            public_conflict = {
                key: value
                for key, value in entry.items()
                if not str(key).startswith("_")
            }
            resolution = resolutions[conflict_id]
            if normalized_sha(resolution.get("conflict_sha256")) != canonical_hash(
                public_conflict
            ):
                audit.add(
                    "audit_incomplete",
                    "conflict_resolution_stale",
                    "Conflict resolution is not bound to the exact current conflict object.",
                    conflict_id=conflict_id,
                    path=resolution.get("_path"),
                )
            else:
                continue
        conflict_type = str(entry.get("type", entry.get("conflict_type", ""))).lower()
        if "evidence" in conflict_type:
            gate_status = "evidence_conflict"
        else:
            gate_status = "clarification_required"
        audit.add(
            gate_status,
            "unresolved_conflict",
            "An unresolved reviewer conflict blocks delivery; it cannot be settled by majority vote.",
            conflict_id=conflict_id,
            conflict_type=conflict_type or None,
        )
    unknown_resolutions = sorted(set(resolutions) - conflict_ids)
    if unknown_resolutions:
        audit.add(
            "audit_incomplete",
            "conflict_resolution_unknown_conflict",
            "Resolution artifact references a conflict absent from reviewer findings.",
            conflict_ids=unknown_resolutions,
        )


def build_report(
    audit: GateAudit,
    args: argparse.Namespace,
    manifest: dict[str, Any] | None,
    manifest_hash: str,
    contract_hash: str,
    content_hash: str,
    qa_contract_hash: str,
    artifact_contract_hash: str,
    candidate_hash: str,
    review_paths: list[Path],
    upstream_gate_paths: list[Path],
    coverage: dict[str, Any],
    assignment_registry_path: Path | None,
    assignment_registry_hash: str,
    assignment_registry_valid: bool,
    main_text_audit_path: Path | None,
    main_text_audit_hash: str,
    main_text_audit_valid: bool,
) -> dict[str, Any]:
    status = audit.status()
    local_audit = GateAudit(
        findings=[
            finding
            for finding in audit.findings
            if finding.get("gate_scope") != "upstream"
        ]
    )
    gate_local_status = local_audit.status()
    explicit_author_hold = any(
        finding.get("code") == "explicit_author_hold"
        for finding in audit.findings
    )
    reason_code = (
        "explicit_author_hold"
        if explicit_author_hold
        else None
    )
    # A recorded author hold is an intentional terminal state, not a generic
    # broken-audit label.  Retain every simultaneous blocker for diagnosis but
    # serialize the top-level state as clarification_required.
    if explicit_author_hold:
        status = "clarification_required"
        gate_local_status = "clarification_required"
    counts: dict[str, int] = defaultdict(int)
    for finding in audit.findings:
        counts[finding["status"]] += 1
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "gate_local_status": gate_local_status,
        "delivery_status": status,
        "reason_code": reason_code,
        "exit_code": EXIT_CODES[status],
        "manifest_id": manifest.get("manifest_id") if isinstance(manifest, dict) else None,
        "hashes": {
            "manifest_sha256": manifest_hash or None,
            "contract_sha256": contract_hash or None,
            "content_sha256": content_hash or None,
            "qa_contract_sha256": qa_contract_hash or None,
            "artifact_contract_sha256": artifact_contract_hash or None,
            "candidate_sha256": candidate_hash or None,
            "assignment_registry_sha256": assignment_registry_hash or None,
            "main_text_sufficiency_audit_sha256": main_text_audit_hash or None,
        },
        "inputs": {
            "manifest": str(Path(args.manifest).expanduser().resolve()),
            "contract": str(Path(args.contract).expanduser().resolve()),
            "candidate": str(Path(args.candidate).expanduser().resolve()) if args.candidate else None,
            "review_results": [str(path) for path in review_paths],
            "upstream_gates": [str(path) for path in upstream_gate_paths],
            "conflict_resolutions": [
                str(Path(value).expanduser().resolve())
                for value in args.conflict_resolutions
            ],
            "assignment_registry": (
                str(assignment_registry_path)
                if assignment_registry_path is not None
                else None
            ),
            "main_text_sufficiency_audit": (
                str(main_text_audit_path)
                if main_text_audit_path is not None
                else None
            ),
        },
        "independence_assurance": {
            "attested": bool(assignment_registry_valid and main_text_audit_valid),
            "proven": False,
            "status": (
                "structurally_verified_native_assignments"
                if assignment_registry_valid and main_text_audit_valid
                else "unverified"
            ),
            "note": (
                "The deterministic validator verifies assignment/report structure, hashes, and identity attestations; it cannot prove runtime reviewer isolation."
            ),
        },
        "coverage": coverage,
        "finding_counts": dict(sorted(counts.items())),
        "findings": audit.findings,
    }


def write_report(report: dict[str, Any], path: Path | None) -> None:
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        sys.stdout.write(rendered)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--manifest", required=True, help="QA manifest JSON")
    result.add_argument("--contract", required=True, help="Author-intent contract JSON")
    result.add_argument(
        "--assignment-registry",
        help="Filled qa-assignment-registry/1.0 JSON binding native agent/task assignments",
    )
    result.add_argument(
        "--main-text-sufficiency-audit",
        help="Independent main-text-sufficiency-audit/1.0 result JSON",
    )
    result.add_argument(
        "--review-result",
        "--reviews",
        dest="review_results",
        action="append",
        default=[],
        help="Review-result JSON file or directory; repeat as needed",
    )
    result.add_argument("--candidate", help="Candidate manuscript whose bytes must match the manifest")
    result.add_argument("--candidate-sha256", help="Trusted candidate SHA-256 digest")
    result.add_argument("--candidate-sha256-file", help="File beginning with a candidate SHA-256 digest")
    result.add_argument("--project-root", help="Base directory for relative source_files paths")
    result.add_argument(
        "--upstream-gate",
        action="append",
        default=[],
        help="Fresh deterministic gate report to compose; repeat as needed",
    )
    result.add_argument(
        "--conflict-resolution",
        dest="conflict_resolutions",
        action="append",
        default=[],
        help="Independent qa-conflict-resolution/1.0 artifact; repeat as needed",
    )
    result.add_argument(
        "--report",
        "--json-output",
        dest="report",
        help="Write JSON report here; omit to emit JSON on stdout",
    )
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    audit = GateAudit()
    upstream_audit = GateAudit()
    manifest_path = Path(args.manifest).expanduser().resolve()
    contract_path = Path(args.contract).expanduser().resolve()
    report_path = Path(args.report).expanduser().resolve() if args.report else None

    manifest = load_json_object(manifest_path, audit, "QA manifest")
    contract_raw = load_json_object(contract_path, audit, "author-intent contract")
    manifest_hash = sha256_file(manifest_path) if manifest_path.is_file() else ""
    contract_hash = sha256_file(contract_path) if contract_path.is_file() else ""
    candidate_hash, candidate_path = candidate_hash_from_args(args, audit)
    review_paths: list[Path] = []
    artifact_contract_hash = extract_artifact_contract_hash(manifest) if manifest else ""
    qa_contract_hash = extract_qa_contract_hash(manifest) if manifest else ""
    content_hash = extract_content_hash(manifest) if manifest else ""
    qa_contract_path: Path | None = None
    qa_contract: dict[str, Any] = {}
    artifact_contract_path: Path | None = None
    artifact_contract: dict[str, Any] = {}
    stage_requires_artifact = False
    project_root = Path(args.project_root).expanduser().resolve() if args.project_root else None
    manifest_source_bindings: dict[str, str] = {}
    if manifest is not None:
        qa_contract_path, qa_contract = verify_manifest_contract_file(
            manifest,
            manifest_path,
            "qa_contract",
            qa_contract_hash,
            audit,
            required=True,
        )
        stage_requires_artifact = task_stage_requires_artifact_contract(qa_contract)
        artifact_contract_path, artifact_contract = verify_manifest_contract_file(
            manifest,
            manifest_path,
            "artifact_contract",
            artifact_contract_hash,
            audit,
            required=stage_requires_artifact,
        )
        if stage_requires_artifact and not artifact_contract_hash:
            audit.add(
                "audit_incomplete",
                "required_artifact_contract_missing",
                "This hash-bound QA task stage requires an artifact contract and deterministic conservation/depth gate.",
                task_stage=qa_task_stage(qa_contract) or None,
            )
        validate_task_stage_artifact_mode(
            qa_contract, artifact_contract, upstream_audit
        )
        validate_artifact_rewrite_approval(artifact_contract, upstream_audit)
        manifest_source_bindings = verify_source_files(
            manifest, manifest_path, project_root, audit
        )
    (
        upstream_gate_paths,
        passing_conservation_gate,
        upstream_block_binding,
        fresh_conservation_gate_hash,
        fresh_conservation_gate_status,
        fresh_conservation_replay,
    ) = validate_upstream_gates(
        args.upstream_gate,
        candidate_hash,
        candidate_path,
        content_hash,
        manifest_source_bindings,
        artifact_contract_hash,
        artifact_contract_path,
        artifact_contract,
        stage_requires_artifact
        or artifact_requires_deterministic_gate(artifact_contract),
        artifact_requires_conservation(artifact_contract),
        upstream_audit,
    )
    for finding in upstream_audit.findings:
        finding.setdefault("gate_scope", "upstream")
        audit.findings.append(finding)
    fresh_conservation_nonpass = fresh_conservation_gate_status in {
        "fail",
        "approval_required",
        "metric_unavailable",
    }
    if not fresh_conservation_nonpass:
        review_paths = expand_review_paths(args.review_results, audit)
    coverage: dict[str, Any] = {
        "reader_visible_units": 0,
        "valid_review_records": 0,
        "required_roles": [],
        "complete_roles": [],
    }
    assignment_registry_path: Path | None = None
    assignment_registry_hash = ""
    assignment_registry_valid = False
    packet_assignments: dict[str, dict[str, Any]] = {}
    main_assignment: dict[str, Any] | None = None
    main_text_audit_path: Path | None = None
    main_text_audit_hash = ""
    main_text_audit_valid = False

    if manifest is not None and contract_raw is not None:
        require_schema(manifest, audit, "QA manifest", manifest_path)
        state, author, authority_binding = validate_contract(
            contract_raw, contract_path, audit
        )
        manifest_id = manifest.get("manifest_id")
        if not isinstance(manifest_id, str) or not manifest_id.strip():
            audit.add(
                "audit_incomplete",
                "manifest_id_missing",
                "QA manifest requires a nonempty manifest_id.",
            )
            manifest_id = ""

        expected_manuscript_hash, expected_contract_hash = extract_manifest_hashes(manifest)
        if not content_hash:
            audit.add(
                "audit_incomplete",
                "manifest_content_hash_missing",
                "QA manifest lacks a valid expanded/content SHA-256.",
            )
        if not qa_contract_hash:
            audit.add(
                "audit_incomplete",
                "manifest_qa_contract_hash_missing",
                "QA manifest lacks a valid QA-contract SHA-256.",
            )
        if not expected_manuscript_hash:
            audit.add(
                "audit_incomplete",
                "manifest_manuscript_hash_missing",
                "QA manifest lacks a valid manuscript SHA-256.",
            )
        elif candidate_hash and candidate_hash != expected_manuscript_hash:
            audit.add(
                "audit_incomplete",
                "candidate_manifest_stale",
                "Candidate manuscript changed after QA preparation.",
                expected_sha256=expected_manuscript_hash,
                actual_sha256=candidate_hash,
            )
        if not expected_contract_hash:
            audit.add(
                "audit_incomplete",
                "manifest_contract_hash_missing",
                "QA manifest lacks a valid author-intent contract SHA-256.",
            )
        elif contract_hash != expected_contract_hash:
            audit.add(
                "audit_incomplete",
                "contract_manifest_stale",
                "Author-intent contract changed after QA preparation.",
                expected_sha256=expected_contract_hash,
                actual_sha256=contract_hash,
            )

        evidence_view = load_authoritative_evidence_registry(
            qa_contract, qa_contract_path, manifest, manifest_path, audit
        )
        expected_packet_contract_context = derive_expected_packet_contract_context(
            contract_path,
            qa_contract_path,
            artifact_contract_path,
            author,
            qa_contract,
            artifact_contract,
            manifest,
            evidence_view,
            audit,
        )

        units, by_id = manifest_units(manifest, audit)
        validate_live_preparation_projection(
            manifest,
            manifest_path,
            project_root,
            author,
            qa_contract,
            qa_contract_path,
            units,
            manifest_source_bindings,
            audit,
        )
        validate_container_coverage(units, by_id, audit)
        validate_dependency_contexts(units, by_id, audit)
        formula_registry_hash, formulas_by_id = validate_formula_registry(
            manifest, manifest_path, units, audit
        )
        qa_mode = validate_qa_derived_state(
            manifest, qa_contract, author, units, audit
        )
        required_roles, required_by_unit = required_roles_by_unit(manifest, units, audit)
        packets_by_id = validate_packets(
            manifest,
            manifest_path,
            expected_manuscript_hash,
            content_hash,
            expected_contract_hash,
            qa_contract_hash,
            artifact_contract_hash,
            artifact_contract,
            qa_contract,
            authority_binding,
            expected_packet_contract_context,
            evidence_view,
            by_id,
            required_by_unit,
            formula_registry_hash,
            formulas_by_id,
            audit,
        )
        (
            assignment_registry_path,
            assignment_registry_hash,
            packet_assignments,
            main_assignment,
            assignment_registry_valid,
        ) = validate_assignment_registry(
            args.assignment_registry,
            manifest_id,
            manifest_hash,
            content_hash,
            packets_by_id,
            qa_mode == "exhaustive",
            audit,
        )
        conservation_required = (
            stage_requires_artifact
            or artifact_requires_deterministic_gate(artifact_contract)
        )
        if not fresh_conservation_nonpass:
            fifth_role_required = qa_mode == "exhaustive"
            (
                main_text_audit_path,
                main_text_audit_hash,
                main_text_audit_valid,
            ) = validate_main_text_sufficiency_audit(
                args.main_text_sufficiency_audit,
                fifth_role_required,
                manifest_id,
                manifest_hash,
                candidate_hash,
                content_hash,
                expected_contract_hash,
                qa_contract_hash,
                artifact_contract_hash,
                assignment_registry_hash,
                main_assignment,
                fresh_conservation_gate_hash,
                fresh_conservation_gate_status,
                conservation_required and bool(fresh_conservation_gate_hash),
                artifact_contract,
                fresh_conservation_replay,
                by_id,
                audit,
            )

            valid_results, records, ledgers = load_results(
                review_paths,
                manifest_id,
                manifest_hash,
                expected_manuscript_hash,
                expected_contract_hash,
                content_hash,
                qa_contract_hash,
                artifact_contract_hash,
                by_id,
                packets_by_id,
                assignment_registry_hash,
                packet_assignments,
                audit,
            )
            manifest_ledgers = manifest.get("ledgers")
            manifest_baseline_sources: list[Any] = []
            if isinstance(manifest_ledgers, dict):
                manifest_baseline_sources.extend(
                    as_list(manifest_ledgers.get("baseline_to_candidate"))
                )
            for key in ("baseline_to_candidate", "content_conservation_ledger"):
                if key in manifest:
                    manifest_baseline_sources.extend(as_list(manifest.get(key)))
            for entry in manifest_baseline_sources:
                if isinstance(entry, dict):
                    enriched = dict(entry)
                    enriched.setdefault("_role", "manifest")
                    enriched.setdefault("_path", str(manifest_path))
                    ledgers["baseline_to_candidate"].append(enriched)
                else:
                    audit.add(
                        "audit_incomplete",
                        "baseline_ledger_entry_invalid",
                        "Manifest baseline_to_candidate entries must be objects.",
                    )
            validate_authority_projection_review(
                authority_binding, valid_results, ledgers, audit
            )
            apply_review_verdicts(records, audit)
            coverage = validate_role_and_unit_coverage(
                units,
                required_roles,
                required_by_unit,
                valid_results,
                records,
                audit,
            )
            obligations, definitions, known_intents, known_evidence = contract_collections(
                state,
                author,
                qa_contract,
                manifest,
                manifest_path,
                evidence_view,
                audit,
            )
            validate_intent_ledgers(
                obligations,
                known_intents,
                units,
                by_id,
                ledgers,
                qa_mode,
                {
                    value
                    for value in as_list(
                        nested(qa_contract, "revision_scope", "affected_intent_ids")
                    )
                    if isinstance(value, str) and value
                },
                packets_by_id,
                audit,
            )
            validate_evidence_ledger(
                units, by_id, records, ledgers, known_evidence, audit
            )
            validate_definitions(definitions, by_id, records, ledgers, qa_mode, audit)
            validate_revision_rechecks(
                manifest, by_id, required_by_unit, records, ledgers, audit
            )
            conflict_resolutions = load_conflict_resolutions(
                args.conflict_resolutions,
                manifest_id,
                manifest_hash,
                contract_path,
                contract_hash,
                author.get("intent_revision_id"),
                qa_contract,
                qa_contract_path,
                upstream_gate_paths,
                valid_results,
                packet_assignments,
                main_assignment,
                audit,
            )
            validate_conflicts(ledgers["conflicts"], conflict_resolutions, audit)
            validate_baseline_conservation(
                artifact_contract,
                ledgers,
                fresh_conservation_gate_status,
                upstream_block_binding,
                audit,
            )

    report = build_report(
        audit,
        args,
        manifest,
        manifest_hash,
        contract_hash,
        content_hash,
        qa_contract_hash,
        artifact_contract_hash,
        candidate_hash,
        review_paths,
        upstream_gate_paths,
        coverage,
        assignment_registry_path,
        assignment_registry_hash,
        assignment_registry_valid,
        main_text_audit_path,
        main_text_audit_hash,
        main_text_audit_valid,
    )
    write_report(report, report_path)
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
