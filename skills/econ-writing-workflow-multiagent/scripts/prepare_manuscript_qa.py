#!/usr/bin/env python3
"""Prepare deterministic, reviewer-ready QA packets for a manuscript.

The program deliberately does no semantic grading.  It expands a bounded
manuscript, enumerates reader-visible units, attaches deterministic risk flags
and context, and writes packets for independent native-agent reviewers.

Supported inputs are UTF-8 ``.tex``, ``.md``, and ``.txt`` files.  The LaTeX
reader is intentionally conservative: it handles ordinary ``input/include``
trees and common prose commands, but fails closed on malformed balanced
arguments, include cycles, missing includes, and paths outside project_root.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable


SCHEMA_VERSION = "1.0"
SCHEMA_ID = "qa-manifest/1.0"
PACKET_SCHEMA_VERSION = "1.0"
PACKET_SCHEMA_ID = "qa-audit-packet/1.0"
DEFAULT_ROLES = (
    "author_intent_coverage",
    "evidence_claim_strength",
    "definitions_reader_sufficiency",
    "economic_logic_scope_qualifiers",
)
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
TASK_STAGE_ARTIFACT_MODES = {
    "full_draft": "full_draft",
    "proposal_draft": "full_draft",
    "document_translation": "document_translation",
    "document_compression": "shorten",
    "major_revision": "major_revision",
    "major_restructure": "restructure",
    "local_edit": "local_edit",
    "local_polish": "local_edit",
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
ARTIFACT_TASK_MODES = {
    "full_draft",
    "major_revision",
    "restructure",
    "shorten",
    "local_edit",
    "document_translation",
}
ROLE_PROTOCOL_VERSION = "1.0"
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
            "scope_conditions": "Check whether population, period, geography, domain, uncertainty, caveats, and exceptions are accurate and stated only where they materially change interpretation; flag both missing boundaries and unchanged no-information repetition.",
            "comparison_direction": "Check comparison group or model benchmark, sign/direction, sequence, and timing.",
            "qualifier_preservation": "Check that negation, uncertainty, scope qualifiers, and association/causality/heterogeneity/mechanism distinctions remain semantically intact after consolidation; calibrated verbs may satisfy the boundary without a standalone disclaimer.",
        },
    },
}
REVIEW_RESULT_REQUIRED_FIELDS = (
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
DEFAULT_MAX_UNITS_PER_PACKET = 25
DEFAULT_MAX_PACKET_BYTES = 240_000
MAX_UNITS_PER_PACKET = 25
MIN_PACKET_BYTES = 10_000
MAX_PACKET_BYTES = 240_000
EXIT_OK = 0
EXIT_PREPARATION_ERROR = 2
EXIT_METRIC_UNAVAILABLE = 3
EXIT_AUDIT_INCOMPLETE = 4
EXIT_CLARIFICATION_REQUIRED = 5
EXIT_EVIDENCE_CONFLICT = 6


class PreparationError(RuntimeError):
    """A deterministic preparation invariant could not be satisfied."""


class PreparationBlocked(PreparationError):
    """A typed prerequisite gate blocks packet generation."""

    def __init__(self, status: str, reason_code: str, message: str, exit_code: int):
        super().__init__(message)
        self.status = status
        self.reason_code = reason_code
        self.exit_code = exit_code


@dataclass(frozen=True)
class SourcePoint:
    path: Path
    offset: int


@dataclass
class ExpandedDocument:
    text: str
    points: list[SourcePoint | None]
    source_texts: dict[Path, str]
    source_hashes: dict[Path, str]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256_bytes(encoded)


def stable_id(prefix: str, *parts: Any) -> str:
    return f"{prefix}_{sha256_text('|'.join(str(item) for item in parts))[:16]}"


def ensure_within_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise PreparationError(f"path escapes project root: {path}") from exc


def read_utf8(path: Path) -> str:
    try:
        return path.read_bytes().decode("utf-8")
    except FileNotFoundError as exc:
        raise PreparationError(f"file not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise PreparationError(f"file is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise PreparationError(f"cannot read file {path}: {exc}") from exc


def strip_tex_comments_preserve_offsets(text: str) -> str:
    """Replace unescaped TeX comments with spaces while retaining newlines."""

    output: list[str] = []
    for line in text.splitlines(keepends=True):
        cut: int | None = None
        for index, character in enumerate(line):
            if character != "%":
                continue
            backslashes = 0
            cursor = index - 1
            while cursor >= 0 and line[cursor] == "\\":
                backslashes += 1
                cursor -= 1
            if backslashes % 2 == 0:
                cut = index
                break
        if cut is None:
            output.append(line)
        else:
            output.append(
                line[:cut]
                + "".join(
                    char if char in "\r\n" else " " for char in line[cut:]
                )
            )
    return "".join(output)


INPUT_COMMAND_RE = re.compile(r"(?<!\\)\\(?P<name>input|include)(?![A-Za-z@])")
UNSUPPORTED_INCLUDE_COMMAND_RE = re.compile(
    r"(?<!\\)\\(?:subfile|import|subimport|includefrom|inputfrom|subincludefrom)"
    r"(?![A-Za-z@])",
    re.IGNORECASE,
)
SAFE_BARE_INCLUDE_RE = re.compile(r"[A-Za-z0-9_./-]+")


def include_argument(text: str, position: int, current: Path) -> tuple[str, int]:
    """Read a static braced or bare TeX include target and fail closed otherwise."""

    cursor = position
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    if cursor >= len(text):
        raise PreparationError(f"missing include target in {current}")
    if text[cursor] == "{":
        arg_start, arg_end = parse_balanced(text, cursor, "{", "}")
        return text[arg_start:arg_end], arg_end + 1
    match = SAFE_BARE_INCLUDE_RE.match(text, cursor)
    if match is None:
        raise PreparationError(
            f"unsupported dynamic or malformed include target in {current} at offset {cursor}"
        )
    return match.group(0), match.end()


def resolve_include(raw: str, current: Path, project_root: Path) -> Path:
    value = raw.strip()
    if not value or "\x00" in value:
        raise PreparationError(f"invalid include target in {current}")
    child = Path(value)
    if not child.suffix:
        child = child.with_suffix(".tex")
    if not child.is_absolute():
        child = current.parent / child
    child = child.resolve()
    ensure_within_root(child, project_root)
    if not child.is_file():
        raise PreparationError(f"included file not found: {child}")
    return child


def expand_tex(
    path: Path,
    project_root: Path,
    stack: tuple[Path, ...] = (),
    source_texts: dict[Path, str] | None = None,
    source_hashes: dict[Path, str] | None = None,
) -> ExpandedDocument:
    path = path.resolve()
    ensure_within_root(path, project_root)
    if path in stack:
        chain = " -> ".join(str(item) for item in (*stack, path))
        raise PreparationError(f"cyclic LaTeX include: {chain}")
    if source_texts is None:
        source_texts = {}
    if source_hashes is None:
        source_hashes = {}
    raw = read_utf8(path)
    source_texts[path] = raw
    source_hashes[path] = sha256_text(raw)
    cleaned = strip_tex_comments_preserve_offsets(raw)
    unsupported = UNSUPPORTED_INCLUDE_COMMAND_RE.search(cleaned)
    if unsupported is not None:
        raise PreparationError(
            f"unsupported LaTeX include command {unsupported.group(0)} in {path}; "
            "expand it before QA preparation"
        )

    texts: list[str] = []
    points: list[SourcePoint | None] = []
    position = 0
    for match in INPUT_COMMAND_RE.finditer(cleaned):
        fragment = cleaned[position : match.start()]
        texts.append(fragment)
        points.extend(SourcePoint(path, index) for index in range(position, match.start()))
        raw_target, command_end = include_argument(cleaned, match.end(), path)
        child = resolve_include(raw_target, path, project_root)
        expanded = expand_tex(
            child,
            project_root,
            (*stack, path),
            source_texts,
            source_hashes,
        )
        texts.append(expanded.text)
        points.extend(expanded.points)
        position = command_end
    texts.append(cleaned[position:])
    points.extend(SourcePoint(path, index) for index in range(position, len(cleaned)))
    return ExpandedDocument("".join(texts), points, source_texts, source_hashes)


def single_file_document(path: Path, strip_html_comments: bool = False) -> ExpandedDocument:
    raw = read_utf8(path)
    text = raw
    if strip_html_comments:
        def blank_comment(match: re.Match[str]) -> str:
            return "".join(
                char if char in "\r\n" else " " for char in match.group(0)
            )

        text = re.sub(r"<!--.*?-->", blank_comment, text, flags=re.DOTALL)
    return ExpandedDocument(
        text=text,
        points=[SourcePoint(path, index) for index in range(len(text))],
        source_texts={path: raw},
        source_hashes={path: sha256_text(raw)},
    )


def load_contract(
    path: Path, wrapper: str
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    raw = read_utf8(path)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PreparationError(f"contract is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PreparationError(f"contract must be a JSON object: {path}")
    candidates: list[dict[str, Any]] = []
    direct = payload.get(wrapper)
    if isinstance(direct, dict):
        candidates.append(direct)
    paper_state = payload.get("paper_state")
    if isinstance(paper_state, dict):
        state_value = paper_state.get(wrapper)
        if isinstance(state_value, dict):
            candidates.append(state_value)
    if len({canonical_hash(item) for item in candidates}) > 1:
        raise PreparationError(
            f"conflicting top-level and paper_state {wrapper} objects: {path}"
        )
    nested = candidates[0] if candidates else payload
    if not isinstance(nested, dict):
        raise PreparationError(f"{wrapper} must be a JSON object: {path}")
    return nested, sha256_text(raw), paper_state if isinstance(paper_state, dict) else {}


def merge_paper_state_contexts(*contexts: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for context in contexts:
        if not isinstance(context, dict):
            continue
        for key, value in context.items():
            if key not in merged:
                merged[key] = value
            elif canonical_hash(merged[key]) != canonical_hash(value):
                raise PreparationError(
                    f"conflicting paper_state field across contract inputs: {key}"
                )
    return merged


def verify_authority_source(
    author: dict[str, Any], adapter_path: Path
) -> dict[str, Any] | None:
    """Verify a JSON QA view against its non-JSON authoritative intent source."""

    raw = author.get("authority_source")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise PreparationError("author_intent_contract.authority_source must be an object")
    if str(author.get("artifact_role", "")).strip().lower() != "qa_view":
        raise PreparationError(
            "an authority_source requires author_intent_contract.artifact_role=qa_view"
        )
    raw_path = raw.get("path")
    expected_hash = str(raw.get("sha256", "")).strip().lower()
    source_format = str(raw.get("format", "")).strip().lower()
    format_suffixes = {
        "md": {".md", ".markdown"},
        "markdown": {".md", ".markdown"},
        "yaml": {".yaml", ".yml"},
        "yml": {".yaml", ".yml"},
        "txt": {".txt", ".text"},
        "text": {".txt", ".text"},
    }
    if not isinstance(raw_path, str) or not raw_path.strip() or not re.fullmatch(
        r"[0-9a-f]{64}", expected_hash
    ):
        raise PreparationError("authority_source requires path and SHA-256")
    source_path = Path(raw_path).expanduser()
    if not source_path.is_absolute():
        source_path = adapter_path.parent / source_path
    source_path = source_path.resolve()
    if source_format not in format_suffixes:
        raise PreparationError(
            "authority_source.format must be one of md, markdown, yaml, yml, txt, or text"
        )
    if source_path.suffix.lower() not in format_suffixes[source_format]:
        raise PreparationError(
            "authority_source.format does not match the authority source path suffix"
        )
    if source_path == adapter_path.resolve():
        raise PreparationError("authority_source must differ from its JSON QA view")
    if not source_path.is_file():
        raise PreparationError(f"authoritative intent source not found: {source_path}")
    actual_hash = sha256_bytes(source_path.read_bytes())
    if actual_hash != expected_hash:
        raise PreparationError(
            "authoritative intent source changed after the JSON QA view was created"
        )
    confirmation = author.get("adapter_confirmation")
    if not isinstance(confirmation, dict):
        raise PreparationError(
            "a non-JSON authority requires an explicit adapter_confirmation"
        )
    required_confirmation_fields = (
        "confirmed_by",
        "confirmed_at",
        "confirmation_source",
    )
    if any(
        not isinstance(confirmation.get(field), str)
        or not confirmation[field].strip()
        for field in required_confirmation_fields
    ):
        raise PreparationError(
            "adapter_confirmation requires confirmed_by, confirmed_at, and confirmation_source"
        )
    require_iso8601_timestamp(
        confirmation, "confirmed_at", "author_intent_contract.adapter_confirmation"
    )
    if str(confirmation.get("status", "")).strip().lower() != "confirmed":
        raise PreparationError("adapter_confirmation.status must be confirmed")
    if (
        str(confirmation.get("confirmed_scope", "")).strip().lower()
        != "complete_author_intent_projection"
    ):
        raise PreparationError(
            "adapter_confirmation.confirmed_scope must be complete_author_intent_projection"
        )
    intent_revision_id = str(author.get("intent_revision_id", "")).strip()
    if not intent_revision_id or str(
        confirmation.get("intent_revision_id", "")
    ).strip() != intent_revision_id:
        raise PreparationError(
            "adapter_confirmation.intent_revision_id must match the QA view"
        )
    if str(confirmation.get("authority_source_sha256", "")).strip().lower() != actual_hash:
        raise PreparationError(
            "adapter_confirmation.authority_source_sha256 must match the authority source"
        )
    projection = dict(author)
    projection.pop("adapter_confirmation", None)
    projection_hash = canonical_hash(projection)
    if (
        str(confirmation.get("qa_view_projection_sha256", "")).strip().lower()
        != projection_hash
    ):
        raise PreparationError(
            "adapter_confirmation.qa_view_projection_sha256 must match the JSON QA view"
        )
    return {
        "path": str(source_path),
        "sha256": actual_hash,
        "format": source_format,
        "adapter_path": str(adapter_path.resolve()),
        "adapter_sha256": sha256_bytes(adapter_path.read_bytes()),
        "qa_view_projection_sha256": projection_hash,
        "adapter_confirmation": confirmation,
        "artifact_role": "qa_view",
    }


def load_authoritative_evidence_registry(
    qa: dict[str, Any], qa_path: Path
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Verify and project the live evidence authority bound by the QA contract."""

    source = qa.get("evidence_registry_source")
    if source is None:
        return None, []
    if not isinstance(source, dict):
        raise PreparationError(
            "qa_contract.evidence_registry_source must be an object"
        )
    raw_path = source.get("path")
    expected_hash = str(source.get("sha256", "")).strip().lower()
    if not isinstance(raw_path, str) or not raw_path.strip() or not re.fullmatch(
        r"[0-9a-f]{64}", expected_hash
    ):
        raise PreparationError(
            "qa_contract.evidence_registry_source requires path and SHA-256"
        )
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = qa_path.parent / path
    path = path.resolve()
    if not path.is_file():
        raise PreparationError(f"authoritative evidence registry not found: {path}")
    raw_bytes = path.read_bytes()
    actual_hash = sha256_bytes(raw_bytes)
    if actual_hash != expected_hash:
        raise PreparationError(
            "authoritative evidence registry changed after the QA contract was frozen"
        )
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PreparationError(
            f"authoritative evidence registry is not valid UTF-8 JSON: {path}"
        ) from exc
    if not isinstance(payload, dict):
        raise PreparationError("authoritative evidence registry must be a JSON object")
    approval = payload.get("approval_record")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("schema_id") != "evidence-registry/1.0"
        or str(payload.get("status", "")).strip().lower()
        not in {"frozen-current", "accepted"}
        or not isinstance(approval, dict)
    ):
        raise PreparationError(
            "evidence registry must be a frozen/accepted evidence-registry/1.0 artifact"
        )
    require_nonempty_string(
        approval, "confirmed_by", "evidence_registry.approval_record"
    )
    require_iso8601_timestamp(
        approval, "confirmed_at", "evidence_registry.approval_record"
    )
    require_nonempty_string(
        approval, "confirmation_source", "evidence_registry.approval_record"
    )
    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        raise PreparationError("evidence registry requires an evidence array")
    records: list[dict[str, Any]] = []
    identifiers: set[str] = set()
    for index, raw_record in enumerate(evidence, 1):
        if not isinstance(raw_record, dict):
            raise PreparationError(
                f"evidence registry entry {index} must be an object"
            )
        identifier = next(
            (
                raw_record.get(key)
                for key in ("evidence_id", "source_id", "anchor_id", "id")
                if raw_record.get(key) not in (None, "")
            ),
            None,
        )
        evidence_id = identifier.strip() if isinstance(identifier, str) else ""
        source_hash = next(
            (
                str(raw_record.get(key, "")).strip().lower()
                for key in ("source_sha256", "sha256")
                if raw_record.get(key) not in (None, "")
            ),
            "",
        )
        source_reference = raw_record.get("source", raw_record.get("path"))
        if (
            not evidence_id
            or evidence_id in identifiers
            or not re.fullmatch(r"[0-9a-f]{64}", source_hash)
            or source_reference in (None, "", {})
        ):
            raise PreparationError(
                "each evidence registry entry requires a unique evidence/source ID, "
                "a source/path reference, and a source SHA-256"
            )
        identifiers.add(evidence_id)
        records.append(dict(raw_record))
    return (
        {
            "path": str(path),
            "sha256": actual_hash,
            "schema_id": "evidence-registry/1.0",
            "status": str(payload.get("status")).strip().lower(),
        },
        records,
    )


def validate_author_intent_for_preparation(
    author: dict[str, Any],
    paper_state: dict[str, Any],
    intent_path: Path,
    intent_sha256: str,
) -> None:
    """Stop before packet creation unless one recoverably frozen intent is ready."""

    for field in ("intent_contract_id", "intent_revision_id"):
        if not isinstance(author.get(field), str) or not author[field].strip():
            raise PreparationBlocked(
                "audit_incomplete",
                "author_intent_identifier_missing",
                f"author-intent contract requires {field}",
                EXIT_AUDIT_INCOMPLETE,
            )
    status = str(author.get("intent_status", "")).strip().lower()
    if status != "frozen-current":
        raise PreparationBlocked(
            "clarification_required",
            "intent_not_frozen",
            "QA packet preparation requires intent_status=frozen-current",
            EXIT_CLARIFICATION_REQUIRED,
        )
    unresolved = author.get("unresolved_material_questions", [])
    unresolved_items = unresolved if isinstance(unresolved, list) else [unresolved]
    if any(item not in (None, "", [], {}) for item in unresolved_items):
        raise PreparationBlocked(
            "clarification_required",
            "unresolved_material_questions",
            "author-intent contract still has unresolved material questions",
            EXIT_CLARIFICATION_REQUIRED,
        )

    state_pointer = paper_state.get("author_intent_contract")
    if isinstance(state_pointer, dict) and canonical_hash(state_pointer) != canonical_hash(author):
        expected_pointer = {
            "intent_contract_id": str(author.get("intent_contract_id", "")).strip(),
            "intent_revision_id": str(author.get("intent_revision_id", "")).strip(),
            "intent_status": str(author.get("intent_status", "")).strip().lower(),
            "gate_status": str(author.get("gate_status", "")).strip().lower(),
        }
        for field, expected in expected_pointer.items():
            actual = str(state_pointer.get(field, "")).strip()
            if field in {"intent_status", "gate_status"}:
                actual = actual.lower()
            if actual != expected:
                raise PreparationBlocked(
                    "audit_incomplete",
                    "author_intent_pointer_mismatch",
                    f"paper_state.author_intent_contract.{field} does not match the live authority",
                    EXIT_AUDIT_INCOMPLETE,
                )
        pointer_sha = str(state_pointer.get("sha256", "")).strip().lower()
        if pointer_sha != intent_sha256.lower():
            raise PreparationBlocked(
                "audit_incomplete",
                "author_intent_pointer_mismatch",
                "paper_state.author_intent_contract.sha256 does not match the live authority bytes",
                EXIT_AUDIT_INCOMPLETE,
            )
        authority_ref = str(
            state_pointer.get("authoritative_path_or_artifact_id", "")
        ).strip()
        intent_id = expected_pointer["intent_contract_id"]
        revision_id = expected_pointer["intent_revision_id"]
        opaque_ids = {intent_id, f"{intent_id}@{revision_id}"}
        path_matches = False
        if authority_ref:
            candidate_path = Path(authority_ref).expanduser()
            if not candidate_path.is_absolute():
                candidate_path = intent_path.parent / candidate_path
            path_matches = candidate_path.resolve() == intent_path.resolve()
        if authority_ref not in opaque_ids and not path_matches:
            raise PreparationBlocked(
                "audit_incomplete",
                "author_intent_pointer_mismatch",
                "paper_state.author_intent_contract.authoritative_path_or_artifact_id "
                "must resolve to the live contract or equal its stable contract ID",
                EXIT_AUDIT_INCOMPLETE,
            )
    gate_values = [author.get("gate_status")]
    if isinstance(state_pointer, dict):
        gate_values.append(state_pointer.get("gate_status"))
    declared_gates = [
        str(value).strip().lower()
        for value in gate_values
        if value not in (None, "")
    ]
    if not declared_gates or any(value != "ready" for value in declared_gates):
        status_value = next(
            (value for value in declared_gates if value != "ready"), "unset"
        )
        if status_value == "evidence_conflict":
            raise PreparationBlocked(
                "evidence_conflict",
                "contract_evidence_conflict",
                "author-intent gate records an unresolved evidence conflict",
                EXIT_EVIDENCE_CONFLICT,
            )
        raise PreparationBlocked(
            "clarification_required",
            "author_intent_gate_not_ready",
            f"author-intent gate_status must be ready; found {status_value}",
            EXIT_CLARIFICATION_REQUIRED,
        )

    evidence_conflict = author.get(
        "evidence_conflicts", author.get("evidence_conflict")
    )
    if evidence_conflict not in (None, False, "", [], {}):
        raise PreparationBlocked(
            "evidence_conflict",
            "contract_evidence_conflict",
            "author-intent contract records an unresolved evidence conflict",
            EXIT_EVIDENCE_CONFLICT,
        )

    approval = author.get("approval_record")
    if not isinstance(approval, dict):
        raise PreparationBlocked(
            "audit_incomplete",
            "approval_record_missing",
            "frozen-current author intent requires a recoverable approval_record",
            EXIT_AUDIT_INCOMPLETE,
        )
    hold_reason = approval.get("explicit_hold_reason")
    if hold_reason not in (None, "", [], {}):
        raise PreparationBlocked(
            "clarification_required",
            "explicit_author_hold",
            "author-intent approval record contains an explicit writing hold",
            EXIT_CLARIFICATION_REQUIRED,
        )
    approval_fields = (
        "confirmed_by",
        "confirmed_at",
        "confirmed_scope",
        "confirmation_source",
        "freeze_authorized_by",
        "freeze_authorized_at",
    )
    missing = [
        field
        for field in approval_fields
        if not isinstance(approval.get(field), str) or not approval[field].strip()
    ]
    if missing:
        raise PreparationBlocked(
            "audit_incomplete",
            "approval_record_incomplete",
            "author-intent approval_record is missing: " + ", ".join(missing),
            EXIT_AUDIT_INCOMPLETE,
        )
    confirmed_scope = re.sub(
        r"[^a-z0-9]+", "_", str(approval.get("confirmed_scope", "")).strip().lower()
    ).strip("_")
    if confirmed_scope not in {
        "complete",
        "complete_author_intent",
        "complete_author_intent_contract",
    }:
        raise PreparationBlocked(
            "audit_incomplete",
            "approval_scope_incomplete",
            "author confirmation must cover the complete author-intent contract",
            EXIT_AUDIT_INCOMPLETE,
        )
    try:
        require_iso8601_timestamp(
            approval, "confirmed_at", "author_intent_contract.approval_record"
        )
        require_iso8601_timestamp(
            approval,
            "freeze_authorized_at",
            "author_intent_contract.approval_record",
        )
    except PreparationError as exc:
        raise PreparationBlocked(
            "audit_incomplete",
            "approval_record_invalid",
            str(exc),
            EXIT_AUDIT_INCOMPLETE,
        ) from exc
    if (
        approval["confirmed_by"] != approval["freeze_authorized_by"]
        or approval["confirmed_at"] != approval["freeze_authorized_at"]
    ):
        raise PreparationBlocked(
            "audit_incomplete",
            "approval_freeze_event_mismatch",
            "complete author confirmation and intent freeze must be the same recorded authorization event",
            EXIT_AUDIT_INCOMPLETE,
        )


def mask_ranges(text: str, ranges: Iterable[tuple[int, int]]) -> str:
    characters = list(text)
    for start, end in ranges:
        for index in range(max(0, start), min(len(characters), end)):
            if characters[index] not in "\r\n":
                characters[index] = " "
    return "".join(characters)


def parse_balanced(text: str, start: int, opener: str, closer: str) -> tuple[int, int]:
    if start >= len(text) or text[start] != opener:
        raise PreparationError(f"expected balanced {opener}{closer} argument at offset {start}")
    depth = 0
    index = start
    while index < len(text):
        character = text[index]
        if character == "\\":
            index += 2
            continue
        if character == opener:
            depth += 1
        elif character == closer:
            depth -= 1
            if depth == 0:
                return start + 1, index
        index += 1
    raise PreparationError(f"unclosed balanced {opener}{closer} argument at offset {start}")


def next_argument(
    text: str, position: int, *, skip_optional: bool = True
) -> tuple[int, int, int]:
    _, arg_start, arg_end, command_end = command_argument_details(
        text, position, skip_optional=skip_optional
    )
    return arg_start, arg_end, command_end


def command_argument_details(
    text: str, position: int, *, skip_optional: bool = True
) -> tuple[list[str], int, int, int]:
    cursor = position
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    optional_arguments: list[str] = []
    while skip_optional and cursor < len(text) and text[cursor] == "[":
        optional_start, optional_end = parse_balanced(text, cursor, "[", "]")
        optional_arguments.append(text[optional_start:optional_end])
        cursor = optional_end + 1
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
    if cursor >= len(text) or text[cursor] != "{":
        raise PreparationError(f"missing required command argument at offset {position}")
    arg_start, arg_end = parse_balanced(text, cursor, "{", "}")
    return optional_arguments, arg_start, arg_end, arg_end + 1


def document_body_mask(text: str) -> tuple[str, list[tuple[int, int]]]:
    begin_matches = list(re.finditer(r"\\begin\s*\{document\}", text))
    end_matches = list(re.finditer(r"\\end\s*\{document\}", text))
    if not begin_matches and not end_matches:
        return text, []
    if len(begin_matches) != 1 or len(end_matches) != 1:
        raise PreparationError(
            "LaTeX source requires exactly one begin{document} and one end{document}"
        )
    begin, end = begin_matches[0], end_matches[0]
    if begin.end() > end.start():
        raise PreparationError("end{document} appears before begin{document}")
    ranges = [(0, begin.end()), (end.start(), len(text))]
    return mask_ranges(text, ranges), ranges


SECTION_COMMAND_RE = re.compile(
    r"\\(part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?"
    r"(?![A-Za-z@])"
)


def extract_tex_sections(text: str) -> tuple[list[dict[str, Any]], list[tuple[int, int]]]:
    records: list[dict[str, Any]] = []
    ranges: list[tuple[int, int]] = []
    for match in SECTION_COMMAND_RE.finditer(text):
        arg_start, arg_end, command_end = next_argument(text, match.end())
        records.append(
            {
                "kind": "section",
                "level": match.group(1),
                "start": match.start(),
                "end": command_end,
                "content_start": arg_start,
                "content_end": arg_end,
                "raw": text[arg_start:arg_end],
            }
        )
        ranges.append((match.start(), command_end))
    return records, ranges


SPECIAL_COMMAND_RE = re.compile(
    r"\\(captionof|caption|footnotetext|footnote|thanks|tablenote|figurenote|notes?|source)\*?"
    r"(?![A-Za-z@])"
)


def extract_tex_specials(text: str) -> tuple[list[dict[str, Any]], list[tuple[int, int]]]:
    records: list[dict[str, Any]] = []
    ranges: list[tuple[int, int]] = []
    occupied: set[tuple[int, int, str]] = set()
    for match in SPECIAL_COMMAND_RE.finditer(text):
        name = match.group(1).lower()
        first_start, first_end, command_end = next_argument(text, match.end())
        if name == "captionof":
            content_start, content_end, command_end = next_argument(
                text, command_end, skip_optional=True
            )
        else:
            content_start, content_end = first_start, first_end
        kind = "caption" if name.startswith("caption") else (
            "footnote" if name in {"footnote", "footnotetext", "thanks"} else "note"
        )
        key = (match.start(), command_end, kind)
        if key in occupied:
            continue
        occupied.add(key)
        records.append(
            {
                "kind": kind,
                "command": name,
                "start": match.start(),
                "end": command_end,
                "content_start": content_start,
                "content_end": content_end,
                "raw": text[content_start:content_end],
                "footnote_reference_id": (
                    stable_id(
                        "fnref",
                        match.start(),
                        sha256_text(text[content_start:content_end]),
                    )
                    if name in {"footnote", "thanks"}
                    else None
                ),
            }
        )
        ranges.append((match.start(), command_end))

    for env_match in re.finditer(r"\\begin\s*\{(tablenotes|figurenotes)\}", text):
        name = env_match.group(1)
        end_match = re.search(rf"\\end\s*\{{{re.escape(name)}\}}", text[env_match.end():])
        if end_match is None:
            raise PreparationError(f"unclosed {name} environment")
        content_start = env_match.end()
        content_end = env_match.end() + end_match.start()
        block_end = env_match.end() + end_match.end()
        records.append(
            {
                "kind": "note",
                "start": env_match.start(),
                "end": block_end,
                "content_start": content_start,
                "content_end": content_end,
                "raw": text[content_start:content_end],
            }
        )
        ranges.append((env_match.start(), block_end))
    return records, ranges


def extract_tex_maketitle_records(
    text: str, body_text: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Materialize static title metadata that ``maketitle`` makes visible."""

    maketitles = list(re.finditer(r"\\maketitle(?![A-Za-z@])", body_text))
    if not maketitles:
        return [], []
    if len(maketitles) != 1:
        raise PreparationError("LaTeX source requires at most one maketitle command")
    display_start = maketitles[0].start()
    begin_document = re.search(r"\\begin\s*\{document\}", text)
    preamble_end = begin_document.start() if begin_document else display_start
    preamble = text[:preamble_end]

    parent_records: list[dict[str, Any]] = []
    metadata_commands = (
        ("title", "section", "title", False),
        ("subtitle", "section", "subtitle", False),
        ("author", "note", "title_author_metadata", False),
        ("date", "note", "title_date_metadata", False),
        ("affil", "note", "title_affiliation_metadata", True),
        ("affiliation", "note", "title_affiliation_metadata", True),
        ("institute", "note", "title_affiliation_metadata", True),
        ("address", "note", "title_address_metadata", True),
        ("email", "note", "title_contact_metadata", True),
    )
    display_order = 0
    for command, kind, level, allow_multiple in metadata_commands:
        matches = list(
            re.finditer(rf"\\{command}\*?(?![A-Za-z@])", preamble)
        )
        if len(matches) > 1 and not allow_multiple:
            raise PreparationError(f"ambiguous LaTeX {command}: found multiple commands")
        for match in matches:
            arg_start, arg_end, command_end = next_argument(text, match.end())
            parent_records.append(
                {
                    "kind": kind,
                    "level": level,
                    "command": command,
                    "start": match.start(),
                    "end": command_end,
                    "display_start": display_start + display_order,
                    "content_start": arg_start,
                    "content_end": arg_end,
                    "raw": text[arg_start:arg_end],
                }
            )
            display_order += 1
    if not any(record.get("command") == "title" for record in parent_records):
        raise PreparationError("maketitle has no static title command")

    thanks_records: list[dict[str, Any]] = []
    for parent in parent_records:
        for match in re.finditer(
            r"\\thanks\*?(?![A-Za-z@])",
            text[parent["content_start"] : parent["content_end"]],
        ):
            absolute_start = parent["content_start"] + match.start()
            arg_start, arg_end, command_end = next_argument(
                text, parent["content_start"] + match.end()
            )
            thanks_records.append(
                {
                    "kind": "footnote",
                    "command": "thanks",
                    "start": absolute_start,
                    "end": command_end,
                    "display_start": parent["display_start"],
                    "content_start": arg_start,
                    "content_end": arg_end,
                    "raw": text[arg_start:arg_end],
                    "footnote_reference_id": stable_id(
                        "fnref", absolute_start, sha256_text(text[arg_start:arg_end])
                    ),
                }
            )
    return parent_records, thanks_records


def decorated_record_raw(record: dict[str, Any]) -> str:
    """Insert equal-length private markers for footnotes nested in a record."""

    replacements = record.get("_footnote_replacements", [])
    if not replacements:
        return str(record["raw"])
    characters = list(str(record["raw"]))
    content_start = int(record["content_start"])
    for replacement in replacements:
        local_start = int(replacement["start"]) - content_start
        local_end = int(replacement["end"]) - content_start
        if local_start < 0 or local_end > len(characters) or local_start >= local_end:
            raise PreparationError("invalid nested footnote span")
        characters[local_start] = str(replacement["placeholder"])
        for index in range(local_start + 1, local_end):
            if characters[index] not in "\r\n":
                characters[index] = " "
    return "".join(characters)


def replace_balanced_commands(text: str, names: set[str], replacement: str) -> str:
    pattern = re.compile(r"\\([A-Za-z@]+)\*?")
    output: list[str] = []
    position = 0
    for match in pattern.finditer(text):
        if match.group(1).lower() not in names or match.start() < position:
            continue
        try:
            arg_start, arg_end, command_end = next_argument(text, match.end())
        except PreparationError:
            continue
        output.append(text[position : match.start()])
        output.append(replacement)
        position = command_end
    output.append(text[position:])
    return "".join(output)


def replace_anchor_commands(text: str, names: set[str], marker: str) -> str:
    """Replace citation/reference commands while retaining exact audit anchors."""

    pattern = re.compile(r"\\([A-Za-z@]+)\*?")
    output: list[str] = []
    position = 0
    for match in pattern.finditer(text):
        if match.group(1).lower() not in names or match.start() < position:
            continue
        try:
            optionals, arg_start, arg_end, command_end = command_argument_details(
                text, match.end()
            )
        except PreparationError:
            continue
        anchor = re.sub(r"\s+", " ", text[arg_start:arg_end]).strip()
        if not anchor:
            raise PreparationError(
                f"empty {marker.lower()} anchor at offset {match.start()}"
            )
        optional_text = " | ".join(
            value for value in (re.sub(r"\s+", " ", item).strip() for item in optionals)
            if value
        )
        token = f" [{marker}:{anchor}"
        if optional_text:
            token += f"; options:{optional_text}"
        token += "] "
        output.append(text[position : match.start()])
        output.append(token)
        position = command_end
    output.append(text[position:])
    return "".join(output)


def replace_multi_argument_commands(text: str) -> str:
    """Keep only reader-visible arguments for common multi-argument commands."""

    specifications: dict[str, tuple[int, int, str]] = {
        "href": (2, 1, "link"),
        "url": (1, 0, "url"),
        "textcolor": (2, 1, "visible"),
        "colorbox": (2, 1, "visible"),
        "fcolorbox": (3, 2, "visible"),
        "multicolumn": (3, 2, "visible"),
        "multirow": (3, 2, "visible"),
        "resizebox": (3, 2, "visible"),
        "scalebox": (2, 1, "visible"),
        "rotatebox": (2, 1, "visible"),
        "raisebox": (2, 1, "visible"),
    }
    pattern = re.compile(r"\\([A-Za-z@]+)\*?(?![A-Za-z@])")
    output: list[str] = []
    position = 0
    for match in pattern.finditer(text):
        name = match.group(1).lower()
        if name not in specifications or match.start() < position:
            continue
        count, visible_index, mode = specifications[name]
        cursor = match.end()
        arguments: list[str] = []
        command_end = cursor
        try:
            for _ in range(count):
                arg_start, arg_end, command_end = next_argument(text, cursor)
                arguments.append(text[arg_start:arg_end])
                cursor = command_end
        except PreparationError:
            continue
        visible = arguments[visible_index]
        if mode == "link":
            replacement = f" [LINK:{visible}|{arguments[0]}] "
        elif mode == "url":
            replacement = f" [LINK:{visible}|{visible}] "
        else:
            replacement = f" {visible} "
        output.append(text[position : match.start()])
        output.append(replacement)
        position = command_end
    output.append(text[position:])
    return "".join(output)


TABULAR_BEGIN_RE = re.compile(
    r"\\begin\s*\{(tabular\*?|tabularx|longtable)\}", re.IGNORECASE
)


def replace_tabular_environments(text: str) -> str:
    """Preserve common TeX table row/cell structure without keeping column specs."""

    output: list[str] = []
    position = 0
    while True:
        match = TABULAR_BEGIN_RE.search(text, position)
        if match is None:
            output.append(text[position:])
            break
        name = match.group(1)
        cursor = match.end()
        argument_count = 2 if name.lower() in {"tabular*", "tabularx"} else 1
        try:
            for _ in range(argument_count):
                _, _, cursor = next_argument(text, cursor)
        except PreparationError as exc:
            raise PreparationError(
                f"malformed {name} column specification"
            ) from exc
        end_match = re.search(
            rf"\\end\s*\{{{re.escape(name)}\}}", text[cursor:], re.IGNORECASE
        )
        if end_match is None:
            raise PreparationError(f"unclosed {name} environment")
        content_end = cursor + end_match.start()
        environment_end = cursor + end_match.end()
        content = text[cursor:content_end]
        if TABULAR_BEGIN_RE.search(content):
            raise PreparationError("nested tabular environments are unsupported")
        rows = re.split(
            r"(?<!\\)\\\\(?!\\)(?:\s*\[[^\]]*\])?", content
        )
        structured_rows: list[str] = []
        for row in rows:
            row = re.sub(
                r"\\(?:toprule|midrule|bottomrule|hline|addlinespace)"
                r"(?![A-Za-z@])(?:\s*\[[^\]]*\])?",
                " ",
                row,
            )
            row = re.sub(
                r"\\cmidrule(?![A-Za-z@])(?:\s*\([^)]*\))?\s*\{[^{}]*\}",
                " ",
                row,
            )
            cells = [cell.strip() for cell in re.split(r"(?<!\\)&", row)]
            if not any(cells):
                continue
            structured_rows.append(" [CELL] ".join(cells))
        replacement = (
            " [TABLE] " + " [ROW] ".join(structured_rows) + " [/TABLE] "
            if structured_rows
            else " "
        )
        output.append(text[position : match.start()])
        output.append(replacement)
        position = environment_end
    return "".join(output)


SAFE_TEX_COMMANDS = {
    "addlinespace", "and", "begin", "bfseries", "bottomrule", "centering", "clearpage",
    "cmidrule", "color", "emph", "end", "enspace", "footnotesize", "hfill", "hline",
    "href", "hspace", "huge", "Huge", "item", "large", "Large", "LARGE",
    "itshape", "leavevmode", "linebreak", "makecell", "maketitle", "mbox", "midrule",
    "multirow", "multicolumn", "newline", "newpage", "noindent", "normalsize",
    "operatorname", "pagebreak", "par", "path", "phantom", "protect", "qquad", "raisebox",
    "quad", "raggedleft", "raggedright", "resizebox", "rotatebox", "rule",
    "rmfamily", "scalebox", "scriptsize", "setlength", "sffamily", "shortstack", "small", "textbf",
    "textcolor", "textit", "textmd", "textnormal", "textrm", "textsf", "textsl",
    "texttt", "textup", "tiny", "toprule", "ttfamily", "underline", "url", "vskip", "vspace",
}


TEX_FORMULA_RE = re.compile(
    r"\\begin\s*\{(?P<environment>equation|align|alignat|gather|multline|displaymath)(?:\*)?\}"
    r".*?\\end\s*\{(?P=environment)(?:\*)?\}"
    r"|(?<!\\)\$\$.*?(?<!\\)\$\$"
    r"|(?<!\\)\$(?!\$).*?(?<!\\)\$(?!\$)"
    r"|\\\[.*?\\\]"
    r"|\\\(.*?\\\)",
    re.DOTALL,
)
def normalize_formula(raw_formula: str) -> str:
    """Normalize whitespace only; preserve signs, operators, labels, and symbols."""

    return re.sub(r"\s+", " ", raw_formula).strip()


def markdown_code_ranges(text: str) -> list[tuple[int, int]]:
    """Return fenced and inline Markdown code spans so dollar signs stay literal."""

    ranges = [
        (match.start(), match.end())
        for match in re.finditer(r"```.*?```|~~~.*?~~~", text, flags=re.DOTALL)
    ]
    masked = mask_ranges(text, ranges)
    ranges.extend(
        (match.start(), match.end())
        for match in re.finditer(r"(?<!`)`[^`\r\n]*`(?!`)", masked)
    )
    return sorted(ranges)


def is_escaped(text: str, position: int) -> bool:
    backslashes = 0
    cursor = position - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def markdown_formula_spans(
    text: str, excluded: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Pair Markdown math delimiters without pairing separate currency signs."""

    def excluded_at(position: int) -> tuple[int, int] | None:
        return next(
            (
                (start, end)
                for start, end in excluded
                if start <= position < end
            ),
            None,
        )

    def next_single_dollar(position: int) -> int | None:
        cursor = position
        while cursor < len(text):
            blocked = excluded_at(cursor)
            if blocked is not None:
                cursor = blocked[1]
                continue
            if text[cursor] == "$" and not is_escaped(text, cursor):
                if text[cursor : cursor + 2] == "$$":
                    cursor += 2
                    continue
                return cursor
            cursor += 1
        return None

    spans: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(text):
        blocked = excluded_at(cursor)
        if blocked is not None:
            cursor = blocked[1]
            continue
        if text[cursor] != "$" or is_escaped(text, cursor):
            cursor += 1
            continue
        if text[cursor : cursor + 2] == "$$":
            close = cursor + 2
            while True:
                close = text.find("$$", close)
                if close < 0:
                    raise PreparationError("unclosed Markdown display formula")
                if not is_escaped(text, close) and excluded_at(close) is None:
                    break
                close += 2
            spans.append((cursor, close + 2))
            cursor = close + 2
            continue

        close = next_single_dollar(cursor + 1)
        following = text[cursor + 1 : cursor + 2]
        if close is None:
            if following and not following.isdigit() and not following.isspace():
                raise PreparationError(
                    "unclosed Markdown inline formula or ambiguous dollar delimiter"
                )
            cursor += 1
            continue
        inner = text[cursor + 1 : close]
        formula_signal = re.search(r"[\\_^{}=<>+*/-]", inner) is not None
        currency_like = re.match(r"\s*\d", inner) is not None and (
            re.search(r"[A-Za-z\u3400-\u4dbf\u4e00-\u9fff]", inner) is not None
            or re.search(r"[,;，；:]", inner) is not None
        ) and not formula_signal
        if currency_like:
            cursor += 1
            continue
        spans.append((cursor, close + 1))
        cursor = close + 1
    return spans


def replace_formula_anchors(
    text: str,
    *,
    fmt: str,
    namespace: str,
    formula_records: list[dict[str, Any]] | None = None,
    source_resolver: Callable[[int, int], list[dict[str, Any]]] | None = None,
) -> str:
    """Replace formulas with stable IDs and retain reviewer-visible formula data."""

    excluded = markdown_code_ranges(text) if fmt == "md" else []
    spans = (
        markdown_formula_spans(text, excluded)
        if fmt == "md"
        else [(match.start(), match.end()) for match in TEX_FORMULA_RE.finditer(text)]
    )

    output: list[str] = []
    position = 0
    for match_start, match_end in spans:
        raw_formula = text[match_start:match_end]
        normalized = normalize_formula(raw_formula)
        formula_id = stable_id(
            "formula",
            namespace,
            match_start,
            match_end,
            sha256_text(raw_formula),
        )
        labels = list(
            dict.fromkeys(
                re.sub(r"\s+", " ", value).strip()
                for value in re.findall(r"\\label\s*\{([^{}]+)\}", raw_formula)
                if re.sub(r"\s+", " ", value).strip()
            )
        )
        if formula_records is not None:
            record = {
                "formula_id": formula_id,
                "format": fmt,
                "raw": raw_formula,
                "normalized_math": normalized,
                "raw_sha256": sha256_text(raw_formula),
                "normalized_sha256": sha256_text(normalized),
                "declared_labels": labels,
                "start_in_container": match_start,
                "end_in_container": match_end,
                "source_spans": (
                    source_resolver(match_start, match_end)
                    if source_resolver is not None
                    else []
                ),
            }
            existing = next(
                (
                    item
                    for item in formula_records
                    if item.get("formula_id") == formula_id
                ),
                None,
            )
            if existing is not None and canonical_hash(existing) != canonical_hash(record):
                raise PreparationError(
                    f"formula ID collision with incompatible content: {formula_id}"
                )
            if existing is None:
                formula_records.append(record)
        suffix = "".join(f" [LABEL:{value}]" for value in labels)
        output.append(text[position:match_start])
        output.append(f" [FORMULA:{formula_id}]{suffix} ")
        position = match_end
    output.append(text[position:])
    return "".join(output)


def tex_to_plain(
    raw: str,
    *,
    formula_namespace: str = "standalone-tex",
    formula_records: list[dict[str, Any]] | None = None,
    formula_source_resolver: Callable[[int, int], list[dict[str, Any]]] | None = None,
) -> str:
    text = raw
    escaped_dollar_sentinel = "\uf100"
    if escaped_dollar_sentinel in text:
        raise PreparationError("manuscript collides with an internal dollar marker")
    text = text.replace(r"\$", escaped_dollar_sentinel)
    text = replace_formula_anchors(
        text,
        fmt="tex",
        namespace=formula_namespace,
        formula_records=formula_records,
        source_resolver=formula_source_resolver,
    )
    text = replace_tabular_environments(text)
    text = replace_balanced_commands(
        text,
        {"caption", "captionof", "footnote", "footnotetext", "thanks", "note", "notes", "tablenote", "figurenote"},
        " ",
    )
    text = replace_anchor_commands(
        text,
        {
            "cite", "citet", "citep", "citealp", "citealt", "citeauthor",
            "citeyear", "citeyearpar", "parencite", "textcite", "autocite",
            "footcite", "smartcite", "supercite",
        },
        "CITATION",
    )
    text = replace_anchor_commands(
        text,
        {"ref", "eqref", "autoref", "pageref", "cref", "cpageref"},
        "REF",
    )
    text = replace_anchor_commands(text, {"label"}, "LABEL")
    text = replace_multi_argument_commands(text)
    text = replace_balanced_commands(
        text,
        {
            "includegraphics", "bibliography", "bibliographystyle", "input",
            "include", "sectionmark", "color",
        },
        " ",
    )
    escapes = {
        r"\%": "%",
        r"\&": "&",
        r"\_": "_",
        r"\#": "#",
        r"\$": "$",
        r"\{": "{",
        r"\}": "}",
    }
    for old, new in escapes.items():
        text = text.replace(old, new)
    text = text.replace(escaped_dollar_sentinel, "$")
    text = text.replace(r"\LaTeX", "LaTeX").replace(r"\TeX", "TeX")
    unknown_commands = sorted(
        {
            match.group(1)
            for match in re.finditer(r"\\([A-Za-z@]+)\*?", text)
            if match.group(1) not in SAFE_TEX_COMMANDS
        }
    )
    if unknown_commands:
        raise PreparationError(
            "unsupported TeX control sequence in reader-visible text: "
            + ", ".join(f"\\{name}" for name in unknown_commands)
            + "; expand custom macros or provide a supported source"
        )
    text = re.sub(r"\\(?:begin|end)\s*\{[^{}]+\}", " ", text)
    text = re.sub(
        r"\\item(?:\s*\[([^\]]*)\])?",
        lambda match: (
            f" {match.group(1).strip()}: "
            if match.group(1) and match.group(1).strip()
            else " "
        ),
        text,
    )
    text = re.sub(r"\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])?", " ", text)
    text = text.replace("\\\\", " ").replace("~", " ").replace("&", " ")
    text = text.replace("{", "").replace("}", "")
    text = text.replace("``", "\u201c").replace("''", "\u201d")
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(
        r"([.!?\u3002\uff01\uff1f])\s*((?:\[FOOTNOTE:[^\]]+\]\s*)+)",
        lambda match: f" {match.group(2).strip()}{match.group(1)}",
        text,
    )


def markdown_to_plain(
    raw: str,
    *,
    formula_namespace: str = "standalone-md",
    formula_records: list[dict[str, Any]] | None = None,
    formula_source_resolver: Callable[[int, int], list[dict[str, Any]]] | None = None,
) -> str:
    text = raw
    protected_anchors: list[str] = []

    def protect_anchor(value: str) -> str:
        placeholder = f"\ue100{len(protected_anchors)}\ue101"
        protected_anchors.append(value)
        return placeholder

    text = replace_formula_anchors(
        text,
        fmt="md",
        namespace=formula_namespace,
        formula_records=formula_records,
        source_resolver=formula_source_resolver,
    )
    text = re.sub(
        r"\[FORMULA:[^\]]+\]",
        lambda match: protect_anchor(match.group(0)),
        text,
    )
    text = re.sub(r"`[^`]*`", " [CODE] ", text)

    def protect_pandoc_citation(match: re.Match[str]) -> str:
        keys = re.findall(
            r"(?<![A-Za-z0-9_.+-])@([A-Za-z0-9][A-Za-z0-9_.:+/#-]*)",
            match.group(1),
        )
        if not keys:
            return match.group(0)
        return protect_anchor(
            " [CITATION:" + ",".join(dict.fromkeys(keys)) + "] "
        )

    text = re.sub(r"\[([^\]\n]*@[^\]\n]+)\]", protect_pandoc_citation, text)
    text = re.sub(
        r"(?<![A-Za-z0-9_.+-])@([A-Za-z0-9][A-Za-z0-9_.:+/#-]*)",
        lambda match: protect_anchor(f" [CITATION:{match.group(1)}] "),
        text,
    )
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        lambda match: protect_anchor(f" [LINK:{match.group(1)}|{match.group(2)}] "),
        text,
    )
    text = re.sub(
        r"\[\^([^\]]+)\]",
        lambda match: protect_anchor(f" [FOOTNOTE:{match.group(1)}] "),
        text,
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"^\s{0,3}(?:[-*+] |\d+[.)] )", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_~]", "", text)
    text = text.replace(r"\$", "$")
    for index, anchor in enumerate(protected_anchors):
        text = text.replace(f"\ue100{index}\ue101", anchor)
    return re.sub(r"\s+", " ", text).strip()


def audit_anchors(text: str) -> dict[str, list[str]]:
    """Expose exact citation, reference, link, footnote, and formula anchors."""

    citation_keys: list[str] = []
    for raw in re.findall(r"\[CITATION:([^;\]]+)(?:;[^\]]*)?\]", text):
        citation_keys.extend(item.strip() for item in raw.split(",") if item.strip())
    return {
        "citation_keys": list(dict.fromkeys(citation_keys)),
        "reference_labels": list(
            dict.fromkeys(
                item.strip()
                for item in re.findall(r"\[REF:([^\]]+)\]", text)
                if item.strip()
            )
        ),
        "declared_labels": list(
            dict.fromkeys(
                item.strip()
                for item in re.findall(r"\[LABEL:([^\]]+)\]", text)
                if item.strip()
            )
        ),
        "external_links": list(
            dict.fromkeys(
                item.strip()
                for item in re.findall(r"\[LINK:[^|\]]+\|([^\]]+)\]", text)
                if item.strip()
            )
        ),
        "footnote_reference_ids": list(
            dict.fromkeys(
                item.strip()
                for item in re.findall(r"\[FOOTNOTE:([^\]]+)\]", text)
                if item.strip()
            )
        ),
        "formula_ids": list(
            dict.fromkeys(
                item.strip()
                for item in re.findall(r"\[FORMULA:([^\]]+)\]", text)
                if item.strip()
            )
        ),
    }


ABBREVIATIONS = (
    "e.g.", "i.e.", "et al.", "etc.", "cf.", "vs.", "Dr.", "Mr.", "Mrs.",
    "Ms.", "Prof.", "Fig.", "Figs.", "Eq.", "Eqs.", "No.", "Nos.", "pp.",
    "U.S.", "U.K.", "a.m.", "p.m.",
)
DOT_SENTINEL = "\ue000"
EXCLAMATION_SENTINEL = "\ue001"
QUESTION_SENTINEL = "\ue002"
CJK_PERIOD_SENTINEL = "\ue003"
CJK_EXCLAMATION_SENTINEL = "\ue004"
CJK_QUESTION_SENTINEL = "\ue005"
AUDIT_TOKEN_RE = re.compile(
    r"\[(?:CITATION|REF|LABEL|LINK|FOOTNOTE|FORMULA):[^\]]+\]"
)
AUDIT_PUNCTUATION_SENTINELS = {
    ".": DOT_SENTINEL,
    "!": EXCLAMATION_SENTINEL,
    "?": QUESTION_SENTINEL,
    "\u3002": CJK_PERIOD_SENTINEL,
    "\uff01": CJK_EXCLAMATION_SENTINEL,
    "\uff1f": CJK_QUESTION_SENTINEL,
}


def protect_sentence_periods(text: str) -> str:
    protected = AUDIT_TOKEN_RE.sub(
        lambda match: "".join(
            AUDIT_PUNCTUATION_SENTINELS.get(character, character)
            for character in match.group(0)
        ),
        text,
    )
    protected = re.sub(r"(?<=\d)\.(?=\d)", DOT_SENTINEL, protected)
    for abbreviation in ABBREVIATIONS:
        pattern = re.compile(re.escape(abbreviation), flags=re.IGNORECASE)
        protected = pattern.sub(lambda match: match.group(0).replace(".", DOT_SENTINEL), protected)
    protected = re.sub(
        r"\b(?:[A-Za-z]\.){2,}",
        lambda match: match.group(0).replace(".", DOT_SENTINEL),
        protected,
    )
    protected = re.sub(
        r"\b[A-Z]\.(?=\s+[A-Z][a-z])",
        lambda match: match.group(0).replace(".", DOT_SENTINEL),
        protected,
    )
    return protected


def split_sentences(text: str) -> list[tuple[str, int, int]]:
    if not text.strip():
        return []
    protected = protect_sentence_periods(text)
    closers = "\u201d\u2019\"')\]}\u3011\u300b"
    boundaries: list[int] = []
    index = 0
    while index < len(protected):
        character = protected[index]
        is_boundary = character in "\u3002\uff01\uff1f!?"
        if character == ".":
            cursor = index + 1
            while cursor < len(protected) and protected[cursor] in ".!?":
                cursor += 1
            while cursor < len(protected) and protected[cursor] in closers:
                cursor += 1
            is_boundary = cursor == len(protected) or protected[cursor].isspace()
        if is_boundary:
            cursor = index + 1
            while cursor < len(protected) and protected[cursor] in ".!?\u3002\uff01\uff1f":
                cursor += 1
            while cursor < len(protected) and protected[cursor] in closers:
                cursor += 1
            boundaries.append(cursor)
            index = cursor
        else:
            index += 1
    if not boundaries or boundaries[-1] < len(protected):
        boundaries.append(len(protected))
    output: list[tuple[str, int, int]] = []
    start = 0
    for end in boundaries:
        raw_piece = protected[start:end]
        left = len(raw_piece) - len(raw_piece.lstrip())
        right = len(raw_piece.rstrip())
        piece_start, piece_end = start + left, start + right
        piece = protected[piece_start:piece_end]
        for punctuation, sentinel in AUDIT_PUNCTUATION_SENTINELS.items():
            piece = piece.replace(sentinel, punctuation)
        if piece:
            output.append((piece, piece_start, piece_end))
        start = end
    return output


CAUSAL_RE = re.compile(
    r"\b(?:caus\w*|effect\w*|impact\w*|because|due to|leads? to|results? in|drives?|raises?|reduces?)\b|"
    r"(?:\u56e0\u679c|\u5bfc\u81f4|\u7531\u4e8e|\u4f7f\u5f97|\u4fc3\u8fdb|\u6291\u5236|\u5f71\u54cd|\u63d0\u9ad8|\u964d\u4f4e)",
    re.IGNORECASE,
)
MECHANISM_RE = re.compile(
    r"\b(?:mechanism|channel|mediate\w*|through which|pathway)\b|(?:\u673a\u5236|\u6e20\u9053|\u901a\u8fc7|\u8def\u5f84|\u4f5c\u7528\u673a\u7406)",
    re.IGNORECASE,
)
QUALIFIER_RE = re.compile(
    r"\b(?:may|might|could|suggest\w*|consistent with|only|at most|conditional(?:ly)?|except|unless|within|among|on average|not necessarily)\b|"
    r"(?:\u53ef\u80fd|\u6216\u8bb8|\u8868\u660e|\u4ec5|\u53ea\u6709?|\u81f3\u591a|\u6761\u4ef6|\u9664\u975e|\u5e73\u5747|\u4e0d\u4e00\u5b9a|\u4e0d\u80fd)",
    re.IGNORECASE,
)
DEFINITION_RE = re.compile(
    r"\b(?:define[sd]?|denote[sd]?|refer(?:s|red)? to|is defined as|we call|means?)\b|"
    r"(?:\u5b9a\u4e49|\u8bb0\u4e3a|\u8868\u793a|\u662f\u6307|\u79f0\u4e3a|\u542b\u4e49)",
    re.IGNORECASE,
)
NUMERIC_RE = re.compile(r"(?<!\w)(?:[-+]?\d+(?:[.,]\d+)*%?|\d{4})(?!\w)|[%\uff05$\u00a5\u5143]")


UNKNOWN_TERM_VALUES = {
    "", "unknown", "tbd", "todo", "n/a", "na", "none", "null",
    "\u672a\u77e5", "\u672a\u5b9a", "\u5f85\u5b9a", "\u5f85\u8865\u5145", "\u4e0d\u9002\u7528",
}


def usable_definition_term(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    term = re.sub(r"\s+", " ", value).strip()
    if term.casefold() in UNKNOWN_TERM_VALUES:
        return None
    return term


def contract_markers(
    author: dict[str, Any],
    qa: dict[str, Any],
    definitions: list[dict[str, Any]],
    obligations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    values: list[Any] = []
    for container in (author, qa):
        for key in (
            "high_risk_markers", "risk_markers", "contract_markers",
            "high_risk_phrases", "unit_markers",
        ):
            value = container.get(key, [])
            values.extend(value if isinstance(value, list) else [value])
    for proposition in author.get("propositions", []) if isinstance(author.get("propositions"), list) else []:
        if isinstance(proposition, dict):
            values.append(
                {
                    "text": proposition.get("must_express", ""),
                    "category": "contract_marked",
                    "intent_id": proposition.get("intent_id"),
                }
            )
    for obligation in obligations:
        if not isinstance(obligation, dict):
            continue
        marker_text = first_contract_slot(
            obligation,
            (
                "must_express",
                "required_meaning",
                "meaning",
                "proposition",
                "content",
                "text",
            ),
        )
        if isinstance(marker_text, str) and marker_text.strip():
            values.append(
                {
                    "text": marker_text,
                    "category": "contract_marked",
                    "intent_id": obligation.get("intent_id")
                    or obligation.get("obligation_id")
                    or obligation.get("id"),
                }
            )
    markers: list[dict[str, Any]] = []
    for value in values:
        if isinstance(value, str):
            markers.append({"text": value, "category": "contract_marked"})
        elif isinstance(value, dict):
            text = value.get("text") or value.get("phrase") or value.get("marker") or value.get("contains")
            pattern = value.get("regex") or value.get("pattern")
            if text or pattern:
                markers.append(
                    {
                        "text": str(text) if text else None,
                        "regex": str(pattern) if pattern else None,
                        "category": str(value.get("category") or "contract_marked"),
                        "intent_id": value.get("intent_id"),
                        "definition_id": value.get("definition_id"),
                    }
                )
    for definition in definitions:
        definition_id = definition.get("definition_id") or definition.get("term_id")
        term_values: list[Any] = []
        for key in ("canonical term", "canonical_term", "canonical", "term"):
            if key in definition:
                term_values.append(definition.get(key))
        variants = definition.get("allowed_variants", [])
        term_values.extend(variants if isinstance(variants, list) else [variants])
        seen_terms: set[str] = set()
        for value in term_values:
            term = usable_definition_term(value)
            if term is None or term.casefold() in seen_terms:
                continue
            seen_terms.add(term.casefold())
            markers.append(
                {
                    "text": term,
                    "category": "definition",
                    "definition_id": definition_id,
                    "match_mode": "registered_term",
                }
            )
    return markers


def risk_for_text(text: str, markers: list[dict[str, Any]]) -> dict[str, Any]:
    categories: list[str] = []
    matches: list[dict[str, Any]] = []
    checks = (
        ("causal", CAUSAL_RE),
        ("mechanism", MECHANISM_RE),
        ("numeric", NUMERIC_RE),
        ("qualifier", QUALIFIER_RE),
        ("definition", DEFINITION_RE),
    )
    for category, pattern in checks:
        if pattern.search(text):
            categories.append(category)
    folded = text.casefold()
    for marker in markers:
        matched = False
        if marker.get("text"):
            marker_text = str(marker["text"])
            if marker.get("match_mode") == "registered_term" and not re.search(
                r"[\u3400-\u4dbf\u4e00-\u9fff]", marker_text
            ):
                matched = re.search(
                    rf"(?<!\w){re.escape(marker_text)}(?!\w)", text, flags=re.IGNORECASE
                ) is not None
            else:
                matched = marker_text.casefold() in folded
        elif marker.get("regex"):
            try:
                matched = re.search(str(marker["regex"]), text, flags=re.IGNORECASE) is not None
            except re.error as exc:
                raise PreparationError(f"invalid contract risk regex {marker['regex']!r}: {exc}") from exc
        if matched:
            category = str(marker.get("category") or "contract_marked")
            if category not in categories:
                categories.append(category)
            matches.append({key: value for key, value in marker.items() if value is not None})
    return {
        "is_high_risk": bool(categories),
        "categories": categories,
        "matched_contract_markers": matches,
        "method": "deterministic lexical flags; not a semantic verdict",
    }


def line_number(text: str, offset: int) -> int:
    starts = [0]
    starts.extend(match.end() for match in re.finditer("\n", text))
    return bisect.bisect_right(starts, max(0, offset))


def source_spans(doc: ExpandedDocument, start: int, end: int, root: Path) -> list[dict[str, Any]]:
    points = [point for point in doc.points[max(0, start):min(len(doc.points), end)] if point]
    if not points:
        return []
    groups: list[tuple[Path, int, int]] = []
    group_path, group_start, previous = points[0].path, points[0].offset, points[0].offset
    for point in points[1:]:
        if point.path == group_path and point.offset == previous + 1:
            previous = point.offset
            continue
        groups.append((group_path, group_start, previous + 1))
        group_path, group_start, previous = point.path, point.offset, point.offset
    groups.append((group_path, group_start, previous + 1))
    result: list[dict[str, Any]] = []
    for path, span_start, span_end in groups:
        raw = doc.source_texts[path]
        result.append(
            {
                "path": str(path.relative_to(root)),
                "start_offset": span_start,
                "end_offset": span_end,
                "start_line": line_number(raw, span_start),
                "end_line": line_number(raw, max(span_start, span_end - 1)),
            }
        )
    return result


def classify_visible_block(text: str, region: str, default: str = "paragraph") -> str:
    if re.match(r"^(?:notes?|sources?)\s*[:.]|^(?:\u6ce8|\u8bf4\u660e|\u8d44\u6599\u6765\u6e90)[:\uff1a]", text, re.IGNORECASE):
        return "note"
    if re.match(r"^(?:figure|table)\s+[A-Za-z0-9IVX.-]+\s*[:.\-\u2014]|^(?:\u56fe|\u8868)\s*[A-Za-z0-9\u4e00-\u4e5d.-]+\s*[:\uff1a.\-\u2014]", text, re.IGNORECASE):
        return "caption"
    if re.match(r"^(?:footnote|\u811a\u6ce8)\s*\d*\s*[:\uff1a]", text, re.IGNORECASE):
        return "footnote"
    if region == "appendix" and default == "paragraph":
        return "appendix_prose"
    return default


def paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    position = 0
    for match in re.finditer(r"(?:\r?\n[ \t]*){2,}", text):
        if text[position:match.start()].strip():
            spans.append((position, match.start()))
        position = match.end()
    if text[position:].strip():
        spans.append((position, len(text)))
    return spans


def visible_block_spans(text: str, fmt: str) -> list[tuple[int, int]]:
    """Split paragraphs further at list items, including items without punctuation."""

    output: list[tuple[int, int]] = []
    if fmt == "tex":
        item_pattern = re.compile(r"\\item(?:\s*\[[^\]]*\])?")
    else:
        item_pattern = re.compile(r"(?m)^\s{0,3}(?:[-*+] |\d+[.)] )")
    for start, end in paragraph_spans(text):
        local = text[start:end]
        markers = list(item_pattern.finditer(local))
        if not markers:
            output.append((start, end))
            continue
        first = markers[0]
        if local[:first.start()].strip():
            output.append((start, start + first.start()))
        for index, marker in enumerate(markers):
            item_end = markers[index + 1].start() if index + 1 < len(markers) else len(local)
            output.append((start + marker.start(), start + item_end))
    return [(start, end) for start, end in output if text[start:end].strip()]


APPENDIX_HEADING_RE = re.compile(
    r"^(?:"
    r"appendix(?:es)?(?=$|[\s:\uff1aA-Z0-9IVX.\-])|"
    r"\u9644\u5f55(?=$|[\s:\uff1aA-Za-z0-9\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\uff08(])"
    r")",
    re.IGNORECASE,
)


def is_appendix_heading(title: str) -> bool:
    return APPENDIX_HEADING_RE.match(title.strip()) is not None


def extract_markdown_structures(text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[tuple[int, int]], int | None]:
    sections: list[dict[str, Any]] = []
    specials: list[dict[str, Any]] = []
    ranges: list[tuple[int, int]] = []
    appendix_start: int | None = None
    for match in re.finditer(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*$", text):
        title = markdown_to_plain(match.group(2))
        sections.append(
            {
                "kind": "section", "level": f"h{len(match.group(1))}",
                "start": match.start(), "end": match.end(),
                "content_start": match.start(2), "content_end": match.end(2), "raw": match.group(2),
            }
        )
        ranges.append((match.start(), match.end()))
        if appendix_start is None and is_appendix_heading(title):
            appendix_start = match.start()
    footnote_re = re.compile(r"(?ms)^\[\^([^\]]+)\]:[ \t]*(.+?)(?=\n(?![ \t]{2,})|\Z)")
    for match in footnote_re.finditer(text):
        specials.append(
            {
                "kind": "footnote", "start": match.start(), "end": match.end(),
                "content_start": match.start(2), "content_end": match.end(2), "raw": match.group(2),
                "footnote_reference_id": match.group(1).strip(),
            }
        )
        ranges.append((match.start(), match.end()))
    for match in re.finditer(r"!\[([^\]]+)\]\([^)]+\)", text):
        specials.append(
            {
                "kind": "caption", "start": match.start(), "end": match.end(),
                "content_start": match.start(1), "content_end": match.end(1), "raw": match.group(1),
            }
        )
        ranges.append((match.start(), match.end()))
    return sections, specials, ranges, appendix_start


def extract_txt_sections(text: str) -> tuple[list[dict[str, Any]], list[tuple[int, int]], int | None]:
    pattern = re.compile(
        r"(?m)^(?P<title>[ \t]*(?:(?:\d+(?:\.\d+)*[.)]?)[ \t]+[^\n]+|"
        r"[\u4e00-\u5341]+\u3001[ \t]*[^\n]+|\u7b2c[\u4e00-\u5341\d]+[\u7ae0\u8282][ \t]*[^\n]+|"
        r"(?:Appendix|Appendices)(?:[ \t:\uff1aA-Z0-9IVX.\-]+[^\n]*)?|"
        r"\u9644\u5f55(?:[ \t:\uff1aA-Za-z0-9\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\uff08(][^\n]*)?))[ \t]*$",
        re.IGNORECASE,
    )
    sections: list[dict[str, Any]] = []
    ranges: list[tuple[int, int]] = []
    appendix_start: int | None = None
    for match in pattern.finditer(text):
        title = match.group("title").strip()
        sections.append(
            {
                "kind": "section", "level": "text_heading", "start": match.start(),
                "end": match.end(), "content_start": match.start("title"),
                "content_end": match.end("title"), "raw": title,
            }
        )
        ranges.append((match.start(), match.end()))
        if appendix_start is None and is_appendix_heading(title):
            appendix_start = match.start()
    return sections, ranges, appendix_start


def normalized_contract_slot(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, list):
        return sorted(
            (normalized_contract_slot(item) for item in value),
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    if isinstance(value, dict):
        return {
            key: normalized_contract_slot(item)
            for key, item in sorted(value.items())
        }
    return value


def first_contract_slot(record: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for alias in aliases:
        value = record.get(alias)
        if value not in (None, "", [], {}):
            return value
    return None


def contract_records_conflict(
    left: dict[str, Any], right: dict[str, Any], collection_kind: str
) -> bool:
    """Allow metadata enrichment while rejecting authority-relevant drift."""

    if collection_kind == "obligation":
        if bool(left.get("required", True)) != bool(right.get("required", True)):
            return True
        slots = (
            ("kind", ("kind", "obligation_type", "type")),
            (
                "meaning",
                (
                    "must_express", "required_meaning", "meaning", "proposition",
                    "content", "text",
                ),
            ),
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
    slot_aliases = {alias for _, aliases in slots for alias in aliases}
    for slot_name, aliases in slots:
        left_value = first_contract_slot(left, aliases)
        right_value = first_contract_slot(right, aliases)
        if slot_name == "kind":
            aliases_map = {
                "must_express": "required",
                "required": "required",
            }
            left_value = aliases_map.get(str(left_value), left_value)
            right_value = aliases_map.get(str(right_value), right_value)
        if left_value not in (None, "", [], {}) and right_value not in (
            None,
            "",
            [],
            {},
        ):
            if canonical_hash(normalized_contract_slot(left_value)) != canonical_hash(
                normalized_contract_slot(right_value)
            ):
                return True
    ignored = {
        "obligation_id", "intent_id", "definition_id", "term_id", "id", "_id",
        *slot_aliases,
    }
    for key in (set(left) & set(right)) - ignored:
        if canonical_hash(normalized_contract_slot(left[key])) != canonical_hash(
            normalized_contract_slot(right[key])
        ):
            return True
    return False


def merge_compatible_contract_records(
    records: list[dict[str, Any]], collection_kind: str
) -> list[dict[str, Any]]:
    id_fields = (
        ("obligation_id", "intent_id", "id")
        if collection_kind == "obligation"
        else ("definition_id", "term_id", "id")
    )
    merged: list[dict[str, Any]] = []
    positions: dict[str, int] = {}
    for record in records:
        key = next(
            (
                str(record[field]).strip()
                for field in id_fields
                if record.get(field) not in (None, "")
            ),
            canonical_hash(record),
        )
        if key not in positions:
            positions[key] = len(merged)
            merged.append(dict(record))
            continue
        current = merged[positions[key]]
        if contract_records_conflict(current, record, collection_kind):
            raise PreparationError(
                f"conflicting {collection_kind} with ID {key}"
            )
        for field, value in record.items():
            if field not in current or current[field] in (None, "", [], {}):
                current[field] = value
    return merged


def extract_obligations(
    author: dict[str, Any],
    qa: dict[str, Any],
    paper_state: dict[str, Any],
    artifact_contract: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    propositions = author.get("propositions", [])
    if isinstance(propositions, list):
        for index, item in enumerate(propositions, 1):
            if isinstance(item, dict):
                record = dict(item)
                record.setdefault("obligation_id", record.get("intent_id") or f"proposition_{index}")
                record.setdefault("obligation_type", "must_express")
                record.setdefault("kind", "required")
                output.append(record)
    for key in ("must_preserve", "must_not_claim", "must_not_imply", "forbidden_terms_or_frames"):
        values = author.get(key, [])
        if values is None:
            continue
        if not isinstance(values, list):
            values = [values]
        for index, value in enumerate(values, 1):
            output.append(
                {
                    "obligation_id": stable_id("obl", key, index, canonical_hash(value)),
                    "obligation_type": key,
                    "kind": key,
                    "content": value,
                }
            )
    author_records: dict[str, dict[str, Any]] = {}
    for record in output:
        for field in ("obligation_id", "intent_id", "id"):
            value = record.get(field)
            if isinstance(value, str) and value.strip():
                author_records[value.strip()] = record
    supplements: list[Any] = []
    for container in (artifact_contract or {}, qa, paper_state):
        if isinstance(container, dict):
            value = container.get("content_obligations", [])
            supplements.extend(value if isinstance(value, list) else [value])
    for index, value in enumerate(supplements, 1):
        if not value:
            continue
        if not isinstance(value, dict):
            raise PreparationBlocked(
                "audit_incomplete",
                "supplemental_obligation_unanchored",
                "QA or paper-state obligations must be objects anchored to an author-owned intent ID",
                EXIT_AUDIT_INCOMPLETE,
            )
        record = dict(value)
        trace_id = next(
            (
                str(record[field]).strip()
                for field in ("intent_id", "obligation_id", "id")
                if isinstance(record.get(field), str)
                and str(record[field]).strip() in author_records
            ),
            None,
        )
        if trace_id is None:
            raise PreparationBlocked(
                "audit_incomplete",
                "supplemental_obligation_unanchored",
                "QA or paper-state obligations cannot create a new author intent",
                EXIT_AUDIT_INCOMPLETE,
            )
        if contract_records_conflict(author_records[trace_id], record, "obligation"):
            raise PreparationBlocked(
                "audit_incomplete",
                "obligation_authority_conflict",
                f"supplemental obligation conflicts with author-owned intent {trace_id}",
                EXIT_AUDIT_INCOMPLETE,
            )
        record.setdefault("obligation_id", record.get("intent_id"))
        record.setdefault(
            "kind", record.get("obligation_type", record.get("type", "required"))
        )
        output.append(record)
    return merge_compatible_contract_records(output, "obligation")


def extract_definitions(
    author: dict[str, Any], qa: dict[str, Any], paper_state: dict[str, Any]
) -> list[dict[str, Any]]:
    raw = author.get("definition_registry", author.get("terminology", []))
    if isinstance(raw, dict):
        result = [
            {"definition_id": stable_id("def", key), "term": key, "definition": value}
            for key, value in raw.items()
        ]
    elif isinstance(raw, list):
        result = []
        for index, value in enumerate(raw, 1):
            if isinstance(value, dict):
                record = dict(value)
                record.setdefault("definition_id", record.get("term_id") or f"definition_{index}")
            else:
                record = {"definition_id": f"definition_{index}", "term": value}
            result.append(record)
    elif raw:
        result = [{"definition_id": "definition_1", "term": raw}]
    else:
        result = []
    author_definitions = {
        str(record[field]).strip(): record
        for record in result
        for field in ("definition_id", "term_id", "id")
        if isinstance(record.get(field), str) and str(record[field]).strip()
    }
    supplements: list[Any] = []
    for container in (qa, paper_state):
        if isinstance(container, dict):
            value = container.get("definition_registry", [])
            if isinstance(value, dict):
                supplements.extend(
                    {"term": key, "definition": definition} for key, definition in value.items()
                )
            else:
                supplements.extend(value if isinstance(value, list) else [value])
    for index, value in enumerate(supplements, 1):
        if not value:
            continue
        if not isinstance(value, dict):
            raise PreparationBlocked(
                "audit_incomplete",
                "supplemental_definition_unanchored",
                "QA or paper-state definitions must be objects anchored to an author-owned definition ID",
                EXIT_AUDIT_INCOMPLETE,
            )
        record = dict(value)
        trace_id = next(
            (
                str(record[field]).strip()
                for field in ("definition_id", "term_id", "id")
                if isinstance(record.get(field), str)
                and str(record[field]).strip() in author_definitions
            ),
            None,
        )
        if trace_id is None:
            raise PreparationBlocked(
                "audit_incomplete",
                "supplemental_definition_unanchored",
                "QA or paper-state definitions cannot introduce an author-unapproved term",
                EXIT_AUDIT_INCOMPLETE,
            )
        if contract_records_conflict(
            author_definitions[trace_id], record, "definition"
        ):
            raise PreparationBlocked(
                "audit_incomplete",
                "definition_authority_conflict",
                f"supplemental definition conflicts with author-owned definition {trace_id}",
                EXIT_AUDIT_INCOMPLETE,
            )
        record.setdefault("definition_id", trace_id)
        result.append(record)
    return merge_compatible_contract_records(result, "definition")


def role_list(qa: dict[str, Any]) -> list[str]:
    value = qa.get("required_roles", list(DEFAULT_ROLES))
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise PreparationError("qa_contract.required_roles must be a non-empty list")
    roles = [str(item).strip() for item in value if str(item).strip()]
    if not roles:
        raise PreparationError("qa_contract.required_roles contains no usable role")
    roles = list(dict.fromkeys(roles))
    missing = [role for role in DEFAULT_ROLES if role not in roles]
    if missing:
        raise PreparationError(
            "qa_contract.required_roles must include all four semantic roles: "
            + ", ".join(missing)
        )
    unexpected = [role for role in roles if role not in DEFAULT_ROLES]
    if unexpected:
        raise PreparationError(
            "qa_contract.required_roles contains unsupported version 1 roles: "
            + ", ".join(unexpected)
        )
    return roles


def minimum_high_risk_review_setting(qa: dict[str, Any]) -> int:
    value = qa.get("minimum_high_risk_independent_reviews")
    if isinstance(value, bool) or not isinstance(value, int) or not 2 <= value <= 4:
        raise PreparationError(
            "qa_contract.minimum_high_risk_independent_reviews must be an integer from 2 through 4"
        )
    return value


def roles_for_risk(risk: dict[str, Any], available: list[str], qa: dict[str, Any]) -> list[str]:
    # Claim-bearing status, missing definitions, and lost qualifiers are
    # semantic judgments.  Route every admitted target to every isolated role
    # so a lexical pre-classifier cannot silently suppress specialist review.
    selected = list(available)
    categories = set(str(item) for item in risk.get("categories", []))
    category_roles = {
        "evidence_claim_strength": {"evidence", "factual", "numeric", "causal", "mechanism", "empirical", "contract_marked"},
        "definitions_reader_sufficiency": {"definition", "acronym", "first_use"},
        "economic_logic_scope_qualifiers": {"causal", "mechanism", "scope", "qualifier", "negation", "normative", "logic"},
    }
    for role, triggers in category_roles.items():
        if role in available and categories & triggers:
            selected.append(role)

    overrides = qa.get("role_overrides", {})
    override_roles: list[str] = []
    if isinstance(overrides, dict):
        for category in categories:
            value = overrides.get(category)
            if value is not None:
                override_roles.extend(value if isinstance(value, list) else [value])
    elif isinstance(overrides, list):
        for record in overrides:
            if not isinstance(record, dict):
                continue
            triggers = record.get("risk_categories", record.get("categories", []))
            triggers = [triggers] if isinstance(triggers, str) else triggers
            if set(str(item) for item in triggers) & categories:
                value = record.get("required_roles", [])
                override_roles.extend(value if isinstance(value, list) else [value])
    for role in (str(item).strip() for item in override_roles if str(item).strip()):
        if role not in available:
            raise PreparationError(f"role override refers to unavailable role: {role}")
        selected.append(role)
    selected = list(dict.fromkeys(selected))
    if len(selected) < 2:
        raise PreparationError("semantic QA requires multiple independent reviewer roles")
    return selected


def prepare_units(
    doc: ExpandedDocument,
    fmt: str,
    root: Path,
    author: dict[str, Any],
    qa: dict[str, Any],
    obligations: list[dict[str, Any]],
    definitions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    text = doc.text
    formula_records: list[dict[str, Any]] = []
    appendix_start: int | None = None
    sections: list[dict[str, Any]]
    specials: list[dict[str, Any]]
    mask: list[tuple[int, int]]

    if fmt == "tex":
        working, body_ranges = document_body_mask(text)
        if re.search(r"\\footnotemark(?![A-Za-z@])|\\footnotetext(?![A-Za-z@])", working):
            raise PreparationError(
                "detached footnotemark/footnotetext linkage is unsupported; "
                "convert it to an inline footnote or provide a supported source"
            )
        appendix_matches = list(re.finditer(r"\\appendix(?![A-Za-z@])|\\begin\s*\{appendices\}", working))
        if len(appendix_matches) > 1:
            raise PreparationError(f"ambiguous LaTeX appendix boundary: found {len(appendix_matches)} markers")
        appendix_start = appendix_matches[0].start() if appendix_matches else None
        sections, section_ranges = extract_tex_sections(working)
        specials, special_ranges = extract_tex_specials(working)
        maketitle_records, title_thanks = extract_tex_maketitle_records(text, working)
        sections.extend(
            record for record in maketitle_records if record["kind"] == "section"
        )
        specials.extend(
            record for record in maketitle_records if record["kind"] != "section"
        )
        specials.extend(title_thanks)
        appendix_ranges = [(match.start(), match.end()) for match in appendix_matches]
        mask = body_ranges + section_ranges + special_ranges + appendix_ranges
        masked = mask_ranges(working, mask)
        footnote_placeholders: dict[str, str] = {}
        masked_characters = list(masked)
        inline_footnotes = [
            record for record in specials if record.get("footnote_reference_id")
        ]
        for index, record in enumerate(inline_footnotes):
            placeholder = chr(0xF0000 + index)
            if placeholder in working:
                raise PreparationError(
                    "manuscript collides with an internal footnote marker"
                )
            footnote_placeholders[placeholder] = (
                f" [FOOTNOTE:{record['footnote_reference_id']}] "
            )
            parents = [
                parent
                for parent in [*sections, *specials]
                if parent is not record
                and int(parent["content_start"]) <= int(record["start"])
                and int(record["end"]) <= int(parent["content_end"])
            ]
            if parents:
                parent = min(
                    parents,
                    key=lambda item: int(item["content_end"])
                    - int(item["content_start"]),
                )
                if parent.get("kind") == "footnote":
                    raise PreparationError("nested footnotes are unsupported")
                parent.setdefault("_footnote_replacements", []).append(
                    {
                        "start": record["start"],
                        "end": record["end"],
                        "placeholder": placeholder,
                    }
                )
                continue
            masked_characters[record["start"]] = placeholder
        masked = "".join(masked_characters)

        def to_plain(value: str, record: dict[str, Any]) -> str:
            for placeholder, anchor in footnote_placeholders.items():
                value = value.replace(placeholder, anchor)
            content_start = int(record["content_start"])
            namespace = stable_id(
                "formula_scope",
                fmt,
                record.get("kind"),
                content_start,
                record.get("content_end"),
            )
            return tex_to_plain(
                value,
                formula_namespace=namespace,
                formula_records=formula_records,
                formula_source_resolver=lambda start, end: source_spans(
                    doc, content_start + start, content_start + end, root
                ),
            )
    elif fmt == "md":
        sections, specials, mask, appendix_start = extract_markdown_structures(text)
        masked = mask_ranges(text, mask)

        def to_plain(value: str, record: dict[str, Any]) -> str:
            content_start = int(record["content_start"])
            namespace = stable_id(
                "formula_scope",
                fmt,
                record.get("kind"),
                content_start,
                record.get("content_end"),
            )
            return markdown_to_plain(
                value,
                formula_namespace=namespace,
                formula_records=formula_records,
                formula_source_resolver=lambda start, end: source_spans(
                    doc, content_start + start, content_start + end, root
                ),
            )
    else:
        sections, section_ranges, appendix_start = extract_txt_sections(text)
        specials = []
        mask = section_ranges
        masked = mask_ranges(text, mask)

        def to_plain(value: str, record: dict[str, Any]) -> str:
            return re.sub(r"\s+", " ", value).strip()

    roles = role_list(qa)
    section_units: list[dict[str, Any]] = []
    section_occurrences: Counter[tuple[str, str, str]] = Counter()
    for record in sorted(
        sections, key=lambda item: item.get("display_start", item["start"])
    ):
        plain = to_plain(decorated_record_raw(record), record)
        if not plain:
            continue
        spans = source_spans(doc, record["content_start"], record["content_end"], root)
        path = spans[0]["path"] if spans else "unknown"
        key = (path, record["level"], plain.casefold())
        section_occurrences[key] += 1
        unit_id = stable_id("sec", *key, section_occurrences[key])
        display_start = int(record.get("display_start", record["start"]))
        region = "appendix" if appendix_start is not None and display_start >= appendix_start else "main_text"
        section_units.append(
            {
                "unit_id": unit_id, "type": "section", "kind": "section",
                "level": record["level"], "text": plain, "normalized_text": plain,
                "text_sha256": sha256_text(plain), "reader_visible": True,
                "review_target": True, "claim_bearing": None,
                "requires_intent_mapping": True, "region": region,
                "main_text": region == "main_text", "appendix": region == "appendix",
                "source_spans": spans, "expanded_start": display_start,
                "expanded_end": display_start + max(1, record["end"] - record["start"]), "section_id": unit_id,
                "section_title": plain, "paragraph_id": None, "parent_id": None,
                "intent_ids": [], "definition_ids": [],
                **audit_anchors(plain),
            }
        )

    def section_at(position: int) -> tuple[str | None, str | None]:
        candidates = [unit for unit in section_units if unit["expanded_start"] <= position]
        if not candidates:
            return None, None
        chosen = candidates[-1]
        return chosen["unit_id"], chosen["text"]

    containers: list[dict[str, Any]] = []
    raw_blocks: list[dict[str, Any]] = list(specials)
    for start, end in visible_block_spans(masked, fmt):
        raw_blocks.append({"kind": "paragraph", "start": start, "end": end, "content_start": start, "content_end": end, "raw": masked[start:end]})
    raw_blocks.sort(
        key=lambda item: (
            item.get("display_start", item["start"]),
            0 if item["kind"] != "paragraph" else 1,
        )
    )
    occurrences: Counter[tuple[str, str, str, str]] = Counter()
    for block in raw_blocks:
        plain = to_plain(decorated_record_raw(block), block)
        if not plain:
            continue
        display_start = int(block.get("display_start", block["start"]))
        region = "appendix" if appendix_start is not None and display_start >= appendix_start else "main_text"
        kind = classify_visible_block(plain, region, block["kind"])
        spans = source_spans(doc, block["content_start"], block["content_end"], root)
        path = spans[0]["path"] if spans else "unknown"
        section_id, section_title = section_at(display_start)
        key = (path, section_id or "root", kind, plain.casefold())
        occurrences[key] += 1
        prefix = {"paragraph": "par", "appendix_prose": "app", "caption": "cap", "note": "note", "footnote": "fn"}.get(kind, "unit")
        unit_id = stable_id(prefix, *key, occurrences[key])
        containers.append(
            {
                "unit_id": unit_id, "type": kind, "kind": kind, "text": plain,
                "normalized_text": plain, "text_sha256": sha256_text(plain),
                "reader_visible": True, "review_target": False, "claim_bearing": None,
                "requires_intent_mapping": False, "region": region,
                "main_text": region == "main_text", "appendix": region == "appendix",
                "source_spans": spans, "expanded_start": display_start,
                "expanded_end": display_start + max(1, block["end"] - block["start"]), "section_id": section_id,
                "section_title": section_title, "paragraph_id": unit_id,
                "parent_id": section_id, "intent_ids": [], "definition_ids": [],
                "footnote_reference_id": block.get("footnote_reference_id"),
                **audit_anchors(plain),
            }
        )

    markers = contract_markers(author, qa, definitions, obligations)
    minimum_high = minimum_high_risk_review_setting(qa)
    sentences: list[dict[str, Any]] = []
    for container in containers:
        sentence_occurrences: Counter[str] = Counter()
        for sentence, text_start, text_end in split_sentences(container["text"]):
            sentence_occurrences[sentence.casefold()] += 1
            unit_id = stable_id(
                "sent", container["unit_id"], sentence.casefold(),
                sentence_occurrences[sentence.casefold()],
            )
            anchors = audit_anchors(sentence)
            risk = risk_for_text(sentence, markers)
            if anchors["footnote_reference_ids"]:
                risk["is_high_risk"] = True
                risk["categories"] = list(
                    dict.fromkeys([*risk["categories"], "footnote_dependency"])
                )
            if anchors["formula_ids"]:
                risk["is_high_risk"] = True
                risk["categories"] = list(
                    dict.fromkeys([*risk["categories"], "formula"])
                )
            intent_ids = list(
                dict.fromkeys(
                    str(item["intent_id"])
                    for item in risk["matched_contract_markers"]
                    if item.get("intent_id") not in (None, "")
                )
            )
            definition_ids = list(
                dict.fromkeys(
                    str(item["definition_id"])
                    for item in risk["matched_contract_markers"]
                    if item.get("definition_id") not in (None, "")
                )
            )
            required_roles = roles_for_risk(risk, roles, qa)
            sentences.append(
                {
                    "unit_id": unit_id, "type": "sentence", "kind": "sentence",
                    "text": sentence, "normalized_text": sentence,
                    "text_sha256": sha256_text(sentence), "reader_visible": True,
                    "review_target": True, "claim_bearing": None,
                    "requires_intent_mapping": True, "region": container["region"],
                    "main_text": container["main_text"], "appendix": container["appendix"],
                    "source_spans": container["source_spans"],
                    "expanded_start": container["expanded_start"],
                    "expanded_end": container["expanded_end"],
                    "text_start_in_parent": text_start, "text_end_in_parent": text_end,
                    "section_id": container["section_id"],
                    "section_title": container["section_title"],
                    "paragraph_id": container["unit_id"], "parent_id": container["unit_id"],
                    "intent_ids": intent_ids, "definition_ids": definition_ids, "risk": risk,
                    "risk_flags": list(risk["categories"]),
                    "high_risk": risk["is_high_risk"],
                    "risk_level": "high" if risk["is_high_risk"] else "standard",
                    "required_roles": required_roles,
                    "min_independent_reviews": max(
                        minimum_high if risk["is_high_risk"] else 1,
                        len(required_roles),
                    ),
                    "required_review_count": len(required_roles),
                    **anchors,
                }
            )

    for section in section_units:
        risk = risk_for_text(section["text"], markers)
        added_categories: list[str] = []
        if section.get("footnote_reference_ids"):
            added_categories.append("footnote_dependency")
        if section.get("formula_ids"):
            added_categories.append("formula")
        if added_categories:
            risk["is_high_risk"] = True
            risk["categories"] = list(
                dict.fromkeys([*risk["categories"], *added_categories])
            )
        section["intent_ids"] = list(
            dict.fromkeys(
                str(item["intent_id"])
                for item in risk["matched_contract_markers"]
                if item.get("intent_id") not in (None, "")
            )
        )
        section["definition_ids"] = list(
            dict.fromkeys(
                str(item["definition_id"])
                for item in risk["matched_contract_markers"]
                if item.get("definition_id") not in (None, "")
            )
        )
        section["risk"] = risk
        section["risk_flags"] = list(risk["categories"])
        section["high_risk"] = risk["is_high_risk"]
        section["risk_level"] = "high" if risk["is_high_risk"] else "structural"
        section["required_roles"] = list(roles)
        section["min_independent_reviews"] = max(
            minimum_high if risk["is_high_risk"] else 1,
            len(roles),
        )
        section["required_review_count"] = len(roles)
    for container in containers:
        container["risk"] = {"is_high_risk": False, "categories": [], "matched_contract_markers": [], "method": "container; child sentences carry review flags"}
        container["risk_flags"] = []
        container["high_risk"] = False
        container["risk_level"] = "container"
        container["required_roles"] = []
        container["min_independent_reviews"] = 0
        container["required_review_count"] = 0

    children_by_parent: dict[str, list[dict[str, Any]]] = {}
    for sentence in sentences:
        children_by_parent.setdefault(sentence["parent_id"], []).append(sentence)

    footnote_targets = {
        str(container["footnote_reference_id"]): container
        for container in containers
        if container.get("footnote_reference_id")
    }
    for sentence in [*section_units, *sentences]:
        target_ids: list[str] = []
        for reference_id in sentence.get("footnote_reference_ids", []):
            target = footnote_targets.get(reference_id)
            if target is None:
                raise PreparationError(
                    f"footnote reference has no extracted target: {reference_id}"
                )
            target_ids.append(target["unit_id"])
            target.setdefault("referenced_by_unit_ids", []).append(
                sentence["unit_id"]
            )
        sentence["footnote_target_unit_ids"] = list(dict.fromkeys(target_ids))
        sentence["dependency_unit_ids"] = list(dict.fromkeys(target_ids))

    for container in containers:
        children = children_by_parent.get(container["unit_id"], [])
        if not children:
            raise PreparationError(f"reader-visible container has no sentence child: {container['unit_id']}")
        container["child_unit_ids"] = [child["unit_id"] for child in children]
        container["child_text_sha256"] = canonical_hash(
            [[child["unit_id"], child["text_sha256"]] for child in children]
        )
        container["sentence_coverage_status"] = "complete"
        if container.get("footnote_reference_id"):
            referenced_by = list(
                dict.fromkeys(container.get("referenced_by_unit_ids", []))
            )
            container["referenced_by_unit_ids"] = referenced_by
            container["dependency_unit_ids"] = referenced_by
            for child in children:
                child["referenced_by_unit_ids"] = referenced_by
                child["dependency_unit_ids"] = list(
                    dict.fromkeys(
                        [*child.get("dependency_unit_ids", []), *referenced_by]
                    )
                )

    units = section_units + containers + sentences
    units.sort(key=lambda item: (item["expanded_start"], {"section": 0, "paragraph": 1, "appendix_prose": 1, "caption": 1, "note": 1, "footnote": 1, "sentence": 2}.get(item["type"], 3), item.get("text_start_in_parent", 0)))
    review_units = [unit for unit in units if unit["review_target"]]
    for index, unit in enumerate(units, 1):
        unit["order"] = index
        primary = unit["source_spans"][0] if unit["source_spans"] else {}
        unit["source"] = {
            **primary,
            "expanded_start": unit["expanded_start"],
            "expanded_end": unit["expanded_end"],
            "text_start_in_parent": unit.get("text_start_in_parent"),
            "text_end_in_parent": unit.get("text_end_in_parent"),
        }
        unit["source_path"] = primary.get("path")
        unit["start_line"] = primary.get("start_line")
        unit["end_line"] = primary.get("end_line")
        unit["start_offset"] = primary.get("start_offset")
        unit["end_offset"] = primary.get("end_offset")

    parent_text = {unit["unit_id"]: unit["text"] for unit in containers}
    units_by_id = {str(unit["unit_id"]): unit for unit in units}
    for index, unit in enumerate(review_units):
        dependency_context = []
        for dependency_id in unit.get("dependency_unit_ids", []):
            dependency = units_by_id.get(str(dependency_id))
            if dependency is None:
                raise PreparationError(
                    f"review dependency has no extracted unit: {dependency_id}"
                )
            dependency_context.append(
                {
                    "unit_id": dependency["unit_id"],
                    "type": dependency["type"],
                    "text": dependency["text"],
                    "text_sha256": dependency["text_sha256"],
                    "child_unit_ids": dependency.get("child_unit_ids", []),
                    "source_spans": dependency.get("source_spans", []),
                }
            )
        unit["context"] = {
            "section_id": unit["section_id"],
            "section_title": unit["section_title"],
            "paragraph_id": unit["paragraph_id"],
            "paragraph_text": parent_text.get(unit["paragraph_id"]),
            "previous_review_unit_id": review_units[index - 1]["unit_id"] if index else None,
            "previous_review_text": review_units[index - 1]["text"] if index else None,
            "next_review_unit_id": review_units[index + 1]["unit_id"] if index + 1 < len(review_units) else None,
            "next_review_text": review_units[index + 1]["text"] if index + 1 < len(review_units) else None,
            "dependency_units": dependency_context,
        }

    appendix_info = {
        "detected": appendix_start is not None,
        "expanded_offset": appendix_start,
        "rule": "first uncommented LaTeX appendix marker or Appendix/\u9644\u5f55 heading",
    }
    return units, appendix_info, formula_records


def contract_context(
    author: dict[str, Any],
    qa: dict[str, Any],
    paper_state: dict[str, Any],
    artifact_contract: dict[str, Any] | None,
    obligations: list[dict[str, Any]],
    definitions: list[dict[str, Any]],
    baseline_ledger: list[dict[str, Any]],
    evidence_registry: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence: list[Any] = []
    source_context = author.get("source_context", {})
    if isinstance(source_context, dict):
        anchors = source_context.get("evidence_anchors", [])
        evidence.extend(anchors if isinstance(anchors, list) else [anchors])
    for proposition in author.get("propositions", []) if isinstance(author.get("propositions"), list) else []:
        if isinstance(proposition, dict):
            anchors = proposition.get("evidence_anchors", [])
            evidence.extend(anchors if isinstance(anchors, list) else [anchors])
    artifact_cards = (
        artifact_contract.get("section_cards")
        if isinstance(artifact_contract, dict)
        else None
    )
    parallel_cards = [
        value
        for value in (
            qa.get("section_cards"),
            paper_state.get("section_cards"),
            author.get("section_cards"),
        )
        if value not in (None, "", [], {})
    ]
    if isinstance(artifact_contract, dict):
        if artifact_cards in (None, "", [], {}) and parallel_cards:
            raise PreparationBlocked(
                "audit_incomplete",
                "artifact_section_cards_missing",
                "when an artifact contract applies, section_cards must live in artifact_contract rather than QA, paper_state, or author parallel fields",
                EXIT_AUDIT_INCOMPLETE,
            )
        for parallel in parallel_cards:
            if canonical_hash(parallel) != canonical_hash(artifact_cards):
                raise PreparationBlocked(
                    "audit_incomplete",
                    "artifact_section_cards_conflict",
                    "parallel section_cards differ from canonical artifact_contract.section_cards",
                    EXIT_AUDIT_INCOMPLETE,
                )
        section_cards = artifact_cards or []
    else:
        section_cards = parallel_cards[0] if parallel_cards else []
        if any(
            canonical_hash(value) != canonical_hash(section_cards)
            for value in parallel_cards[1:]
        ):
            raise PreparationBlocked(
                "audit_incomplete",
                "section_cards_conflict",
                "parallel section_cards disagree in a bounded task without an artifact contract",
                EXIT_AUDIT_INCOMPLETE,
            )
    return {
        "intent_contract_id": author.get("intent_contract_id"),
        "intent_revision_id": author.get("intent_revision_id"),
        "intent_status": author.get("intent_status"),
        "purpose": author.get("purpose"),
        "reader_takeaway": author.get("reader_takeaway"),
        "propositions": author.get("propositions", []),
        "content_obligations": obligations,
        "definition_registry": definitions,
        "baseline_to_candidate": baseline_ledger,
        "evidence_anchors": [item for item in evidence if item not in (None, "")],
        "evidence_registry": evidence_registry,
        "section_cards": section_cards,
        "author_intent_contract": author,
        "qa_contract": qa,
    }


def conservation_ledger_entries(
    qa: dict[str, Any],
    artifact_contract: dict[str, Any] | None,
    paper_state: dict[str, Any],
) -> list[dict[str, Any]]:
    """Copy supplied baseline mappings; never manufacture a mature-draft ledger."""

    raw_values: list[Any] = []
    for container in (
        qa,
        paper_state,
        artifact_contract or {},
    ):
        if not isinstance(container, dict):
            continue
        for key in ("baseline_to_candidate", "content_conservation_ledger"):
            if container.get(key) not in (None, ""):
                raw_values.append(container[key])

    def flatten(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            output: list[dict[str, Any]] = []
            for item in value:
                output.extend(flatten(item))
            return output
        if not isinstance(value, dict):
            return []
        if "baseline_to_candidate" in value:
            return flatten(value["baseline_to_candidate"])
        if "entries" in value:
            return flatten(value["entries"])
        identifier_keys = {
            "ledger_id", "mapping_id", "content_id", "baseline_id", "candidate_id",
            "source_id", "disposition", "status",
        }
        if identifier_keys & set(value):
            return [dict(value)]
        output: list[dict[str, Any]] = []
        for key, item in value.items():
            if isinstance(item, dict):
                record = dict(item)
                record.setdefault("ledger_id", str(key))
                output.append(record)
            elif isinstance(item, list):
                output.extend(flatten(item))
        return output

    records: list[dict[str, Any]] = []
    seen: dict[str, str] = {}
    for raw in raw_values:
        for record in flatten(raw):
            identifier = str(
                record.get("ledger_id")
                or record.get("mapping_id")
                or record.get("content_id")
                or stable_id("cons", canonical_hash(record))
            )
            record.setdefault("ledger_id", identifier)
            digest = canonical_hash(record)
            if identifier in seen:
                if seen[identifier] != digest:
                    raise PreparationError(
                        f"conflicting baseline-to-candidate ledger entries: {identifier}"
                    )
                continue
            seen[identifier] = digest
            records.append(record)
    return records


def apply_review_scope(
    units: list[dict[str, Any]], qa_mode: str, revision_scope: Any
) -> None:
    if qa_mode == "exhaustive":
        for unit in units:
            unit["selected_for_review"] = bool(unit.get("review_target"))
            unit["selection_reasons"] = (
                ["exhaustive"] if unit["selected_for_review"] else []
            )
        return
    assert isinstance(revision_scope, dict)
    units_by_id = {str(unit["unit_id"]): unit for unit in units}
    selected_ids: set[str] = set()
    for key in ("changed_unit_ids", "dependency_unit_ids"):
        values = revision_scope.get(key, [])
        if not isinstance(values, list):
            raise PreparationError(f"bounded_change {key} must be a list")
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise PreparationError(
                    f"bounded_change {key} must contain only nonempty unit IDs"
                )
            unit_id = value.strip()
            unit = units_by_id.get(unit_id)
            if unit is None or not unit.get("review_target"):
                raise PreparationError(
                    f"bounded_change {key} contains an unknown or non-review target: {unit_id}"
                )
            selected_ids.add(unit_id)
    ranges: list[dict[str, Any]] = []
    for key in ("changed_source_ranges", "dependency_source_ranges"):
        value = revision_scope.get(key, [])
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, list):
            raise PreparationError(f"bounded_change {key} must be a list or object")
        if any(not isinstance(item, dict) for item in value):
            raise PreparationError(f"bounded_change {key} must contain only objects")
        ranges.extend(value)

    def matches_range(unit: dict[str, Any], selector: dict[str, Any]) -> bool:
        path = selector.get("path") or selector.get("source_path")
        if not isinstance(path, str) or not path.strip():
            raise PreparationError(
                "bounded_change source ranges require an explicit nonempty path"
            )
        lower_value = selector.get("start_line")
        upper_value = selector.get("end_line", lower_value)
        if (
            isinstance(lower_value, bool)
            or isinstance(upper_value, bool)
            or not isinstance(lower_value, int)
            or not isinstance(upper_value, int)
        ):
            raise PreparationError("bounded_change source ranges require integer line numbers")
        lower = lower_value
        upper = upper_value
        if lower < 1 or upper < lower:
            raise PreparationError("bounded_change source range is invalid")
        for span in unit.get("source_spans", []):
            if str(span.get("path")) != path.strip():
                continue
            if int(span.get("start_line", 0)) <= upper and int(span.get("end_line", 0)) >= lower:
                return True
        return False

    for selector in ranges:
        if not any(
            unit.get("review_target") and matches_range(unit, selector)
            for unit in units
        ):
            path = selector.get("path") or selector.get("source_path")
            raise PreparationError(
                "bounded_change source range matches no review target: "
                f"{path}:{selector.get('start_line')}-{selector.get('end_line', selector.get('start_line'))}"
            )

    affected_intent_ids = {
        str(item).strip()
        for item in revision_scope.get("affected_intent_ids", [])
        if str(item).strip()
    }
    for unit in units:
        reasons: list[str] = []
        if bool(unit.get("review_target")):
            if unit["unit_id"] in selected_ids:
                reasons.append("explicit_unit_selector")
            if any(matches_range(unit, item) for item in ranges):
                reasons.append("explicit_source_selector")
            if affected_intent_ids & set(unit.get("intent_ids", [])):
                reasons.append("affected_intent")
        unit["selected_for_review"] = bool(reasons)
        unit["selection_reasons"] = reasons

    changed = True
    while changed:
        changed = False
        selected_targets = [
            unit
            for unit in units
            if unit.get("review_target") and unit.get("selected_for_review")
        ]
        selected_target_ids = {str(unit["unit_id"]) for unit in selected_targets}
        selected_paragraph_ids = {
            str(unit["paragraph_id"])
            for unit in selected_targets
            if unit.get("paragraph_id")
        }
        selected_definition_ids = {
            str(definition_id)
            for unit in selected_targets
            for definition_id in unit.get("definition_ids", [])
        }
        selected_intent_ids = affected_intent_ids | {
            str(intent_id)
            for unit in selected_targets
            for intent_id in unit.get("intent_ids", [])
        }
        dependency_ids = {
            str(dependency_id)
            for unit in selected_targets
            for dependency_id in unit.get("dependency_unit_ids", [])
        }
        dependency_parent_ids = {
            str(units_by_id[dependency_id].get("paragraph_id"))
            for dependency_id in dependency_ids
            if dependency_id in units_by_id
            and units_by_id[dependency_id].get("paragraph_id")
        }
        for unit in units:
            if not unit.get("review_target") or unit.get("selected_for_review"):
                continue
            reasons: list[str] = []
            if unit.get("paragraph_id") and str(unit["paragraph_id"]) in (
                selected_paragraph_ids | dependency_parent_ids
            ):
                reasons.append("paragraph_closure")
            if selected_intent_ids & set(str(item) for item in unit.get("intent_ids", [])):
                reasons.append("intent_dependency_closure")
            if selected_definition_ids & set(
                str(item) for item in unit.get("definition_ids", [])
            ):
                reasons.append("definition_dependency_closure")
            if str(unit["unit_id"]) in dependency_ids or str(
                unit.get("parent_id")
            ) in dependency_ids:
                reasons.append("forward_dependency_closure")
            if selected_target_ids & set(
                str(item) for item in unit.get("dependency_unit_ids", [])
            ):
                reasons.append("reverse_dependency_closure")
            if reasons:
                unit["selected_for_review"] = True
                unit["selection_reasons"] = list(dict.fromkeys(reasons))
                changed = True

    selected_count = sum(
        bool(unit.get("review_target") and unit.get("selected_for_review"))
        for unit in units
    )
    if selected_count == 0:
        raise PreparationError("bounded_change selectors match no review-target units")


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def positive_integer_setting(
    qa: dict[str, Any], key: str, default: int, minimum: int, maximum: int
) -> int:
    value = qa.get(key, default)
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not minimum <= value <= maximum
    ):
        raise PreparationError(
            f"qa_contract.{key} must be an integer from {minimum} through {maximum}"
        )
    return value


def selector_signature(value: Any) -> list[str]:
    values = value if isinstance(value, list) else [value]
    return sorted(canonical_hash(item) for item in values)


def require_nonempty_string(container: dict[str, Any], field: str, location: str) -> str:
    value = container.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PreparationError(f"{location}.{field} must be a nonempty string")
    return value.strip()


def require_iso8601_timestamp(container: dict[str, Any], field: str, location: str) -> str:
    value = require_nonempty_string(container, field, location)
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise PreparationError(
            f"{location}.{field} must be an ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise PreparationError(
            f"{location}.{field} must include a UTC offset or Z"
        )
    return value


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    manuscript = Path(args.manuscript).expanduser().resolve()
    root = Path(args.project_root).expanduser().resolve() if args.project_root else manuscript.parent
    root = root.resolve()
    if not root.is_dir():
        raise PreparationError(f"project root is not a directory: {root}")
    ensure_within_root(manuscript, root)
    suffix = manuscript.suffix.lower()
    if suffix not in {".tex", ".md", ".txt"}:
        raise PreparationError("manuscript must have .tex, .md, or .txt extension")
    fmt = suffix[1:]
    intent_path = Path(args.author_intent_contract).expanduser().resolve()
    qa_path = Path(args.qa_contract).expanduser().resolve()
    author, intent_sha, intent_state = load_contract(
        intent_path, "author_intent_contract"
    )
    authority_source = verify_authority_source(author, intent_path)
    qa, qa_sha, qa_state = load_contract(qa_path, "qa_contract")
    evidence_registry_source, evidence_registry = (
        load_authoritative_evidence_registry(qa, qa_path)
    )
    if not isinstance(qa.get("qa_mode"), str) or not qa["qa_mode"].strip():
        raise PreparationError("qa_contract.qa_mode must be explicitly declared")
    recorded_manuscript_path = qa.get("manuscript_path")
    if not isinstance(recorded_manuscript_path, str) or not recorded_manuscript_path.strip():
        raise PreparationBlocked(
            "audit_incomplete",
            "qa_manuscript_path_missing",
            "qa_contract.manuscript_path must identify the exact live manuscript",
            EXIT_AUDIT_INCOMPLETE,
        )
    recorded_manuscript = Path(recorded_manuscript_path).expanduser()
    if not recorded_manuscript.is_absolute():
        recorded_manuscript = qa_path.parent / recorded_manuscript
    if recorded_manuscript.resolve() != manuscript:
        raise PreparationBlocked(
            "audit_incomplete",
            "qa_manuscript_path_mismatch",
            "qa_contract.manuscript_path does not resolve to --manuscript",
            EXIT_AUDIT_INCOMPLETE,
        )
    qa_mode = qa["qa_mode"].strip().lower()
    if qa_mode not in {"exhaustive", "bounded_change"}:
        raise PreparationError("qa_contract.qa_mode must be exhaustive or bounded_change")
    classification = qa.get("task_classification")
    if not isinstance(classification, dict):
        raise PreparationError("qa_contract requires a task_classification object")
    task_stage_value = require_nonempty_string(
        classification, "task_stage", "task_classification"
    )
    classification_mode = require_nonempty_string(
        classification, "qa_mode", "task_classification"
    ).lower()
    require_nonempty_string(classification, "basis", "task_classification")
    require_nonempty_string(
        classification, "classified_by", "task_classification"
    )
    require_iso8601_timestamp(
        classification, "classified_at", "task_classification"
    )
    if classification_mode != qa_mode:
        raise PreparationError(
            "task_classification.qa_mode must match qa_contract.qa_mode"
        )
    task_stage = task_stage_value.lower()
    expected_mode = TASK_STAGE_QA_MODES.get(task_stage)
    if expected_mode is None:
        raise PreparationError(
            "task_classification.task_stage must be one of: "
            + ", ".join(sorted(TASK_STAGE_QA_MODES))
        )
    if expected_mode != qa_mode:
        raise PreparationError(
            f"task_classification.task_stage={task_stage} requires qa_mode={expected_mode}"
        )
    revision_scope = qa.get(
        "revision_scope",
        qa.get("review_scope", "full_manuscript" if qa_mode == "exhaustive" else None),
    )
    if qa_mode == "bounded_change":
        required_classification_fields = (
            "changed_artifact_or_source_ranges",
            "substantive_dependencies_checked",
            "affected_intent_ids",
        )
        missing_classification = [
            key for key in required_classification_fields if key not in classification
        ]
        if missing_classification:
            raise PreparationError(
                "bounded_change task_classification is missing: "
                + ", ".join(missing_classification)
            )
        if not str(classification.get("basis", "")).strip() or not classification.get(
            "changed_artifact_or_source_ranges"
        ):
            raise PreparationError(
                "bounded_change task_classification requires a nonempty basis and changed artifact/source ranges"
            )
        if not isinstance(revision_scope, dict):
            raise PreparationError("bounded_change requires a revision_scope object")
        if "affected_intent_ids" not in revision_scope:
            raise PreparationError(
                "bounded_change revision_scope requires explicit affected_intent_ids"
            )
        for location, affected in (
            ("task_classification", classification.get("affected_intent_ids")),
            ("revision_scope", revision_scope.get("affected_intent_ids")),
        ):
            if not isinstance(affected, list) or any(
                not isinstance(item, str) or not item.strip() for item in affected
            ):
                raise PreparationError(
                    f"bounded_change {location}.affected_intent_ids must be a nonempty list of nonempty strings"
                )
            if not affected:
                raise PreparationError(
                    f"bounded_change {location}.affected_intent_ids must not be empty"
                )
            if len(affected) != len(set(item.strip() for item in affected)):
                raise PreparationError(
                    f"bounded_change {location}.affected_intent_ids contains duplicates"
                )
        if sorted(item.strip() for item in classification["affected_intent_ids"]) != sorted(
            item.strip() for item in revision_scope["affected_intent_ids"]
        ):
            raise PreparationError(
                "bounded_change task_classification affected_intent_ids must equal revision_scope affected_intent_ids"
            )
        changed = revision_scope.get("changed_unit_ids") or revision_scope.get("changed_source_ranges")
        dependency_present = (
            "dependency_unit_ids" in revision_scope or "dependency_source_ranges" in revision_scope
        )
        if not changed or not dependency_present:
            raise PreparationError(
                "bounded_change revision_scope requires a nonempty changed set and an explicit dependency set"
            )
        changed_keys = [
            key
            for key in ("changed_unit_ids", "changed_source_ranges")
            if revision_scope.get(key)
        ]
        dependency_keys = [
            key
            for key in ("dependency_unit_ids", "dependency_source_ranges")
            if key in revision_scope
        ]
        if len(changed_keys) != 1 or len(dependency_keys) != 1:
            raise PreparationError(
                "bounded_change must use exactly one changed selector type and one dependency selector type"
            )
        revision_changed = revision_scope[changed_keys[0]]
        if selector_signature(
            classification["changed_artifact_or_source_ranges"]
        ) != selector_signature(revision_changed):
            raise PreparationError(
                "bounded_change task_classification changed set must equal revision_scope changed selectors"
            )
        revision_dependencies = revision_scope[dependency_keys[0]]
        if selector_signature(
            classification["substantive_dependencies_checked"]
        ) != selector_signature(revision_dependencies):
            raise PreparationError(
                "bounded_change task_classification dependencies must equal revision_scope dependency selectors"
            )
    artifact_path = Path(args.artifact_contract).expanduser().resolve() if args.artifact_contract else None
    artifact_contract: dict[str, Any] | None = None
    artifact_sha: str | None = None
    artifact_state: dict[str, Any] = {}
    if artifact_path is not None:
        artifact_contract, artifact_sha, artifact_state = load_contract(
            artifact_path, "artifact_contract"
        )
    if task_stage in ARTIFACT_CONTRACT_REQUIRED_STAGES and artifact_contract is None:
        raise PreparationBlocked(
            "audit_incomplete",
            "artifact_contract_missing",
            f"task_stage={task_stage} requires an artifact contract before QA packet preparation",
            EXIT_AUDIT_INCOMPLETE,
        )
    if artifact_contract is not None:
        artifact_mode = str(artifact_contract.get("task_mode", "")).strip().lower()
        if artifact_mode == "translation":
            artifact_mode = "document_translation"
        if artifact_mode not in ARTIFACT_TASK_MODES:
            raise PreparationBlocked(
                "audit_incomplete",
                "artifact_task_mode_invalid",
                "artifact_contract.task_mode is missing or unsupported",
                EXIT_AUDIT_INCOMPLETE,
            )
        raw_metric_status = artifact_contract.get("metric_status")
        metric_status = (
            str(raw_metric_status).strip().lower()
            if isinstance(raw_metric_status, str)
            else ""
        )
        if metric_status not in {"measured", "unavailable", "ambiguous"}:
            raise PreparationBlocked(
                "audit_incomplete",
                "artifact_metric_status_invalid",
                "artifact_contract.metric_status must be explicitly measured, unavailable, or ambiguous",
                EXIT_AUDIT_INCOMPLETE,
            )
        if metric_status != "measured":
            raise PreparationBlocked(
                "metric_unavailable",
                "artifact_metric_unavailable",
                f"artifact_contract.metric_status={metric_status}; resolve the measurement before QA preparation",
                EXIT_METRIC_UNAVAILABLE,
            )
        measurement_contract = artifact_contract.get("measurement_contract")
        if not isinstance(measurement_contract, dict):
            raise PreparationBlocked(
                "audit_incomplete",
                "artifact_measurement_contract_invalid",
                "artifact_contract.measurement_contract must explicitly record appendix_boundary and source_word_method",
                EXIT_AUDIT_INCOMPLETE,
            )
        source_word_method = measurement_contract.get("source_word_method")
        boundary = measurement_contract.get("appendix_boundary")
        if isinstance(boundary, dict):
            boundary = boundary.get("marker") or boundary.get("value")
        if source_word_method not in {"raw_source_words", "normalized_words"} or not (
            isinstance(boundary, str) and boundary.strip()
        ):
            raise PreparationBlocked(
                "audit_incomplete",
                "artifact_measurement_contract_invalid",
                "artifact measurement requires a nonempty appendix_boundary and source_word_method=raw_source_words or normalized_words",
                EXIT_AUDIT_INCOMPLETE,
            )
        if task_stage == "final_audit":
            raw_declared_artifact_mode = classification.get("artifact_task_mode")
            if (
                not isinstance(raw_declared_artifact_mode, str)
                or not raw_declared_artifact_mode.strip()
            ):
                raise PreparationBlocked(
                    "audit_incomplete",
                    "final_audit_artifact_mode_missing",
                    "final_audit requires task_classification.artifact_task_mode",
                    EXIT_AUDIT_INCOMPLETE,
                )
            declared_artifact_mode = raw_declared_artifact_mode.strip().lower()
            if declared_artifact_mode == "translation":
                declared_artifact_mode = "document_translation"
            if declared_artifact_mode not in ARTIFACT_TASK_MODES:
                raise PreparationBlocked(
                    "audit_incomplete",
                    "final_audit_artifact_mode_invalid",
                    "task_classification.artifact_task_mode is unsupported",
                    EXIT_AUDIT_INCOMPLETE,
                )
            expected_artifact_mode = declared_artifact_mode
        else:
            expected_artifact_mode = TASK_STAGE_ARTIFACT_MODES.get(task_stage)
        if expected_artifact_mode is not None and artifact_mode != expected_artifact_mode:
            raise PreparationBlocked(
                "audit_incomplete",
                "artifact_task_mode_mismatch",
                f"task_stage={task_stage} requires artifact_contract.task_mode={expected_artifact_mode}",
                EXIT_AUDIT_INCOMPLETE,
            )
    paper_state = merge_paper_state_contexts(
        intent_state, qa_state, artifact_state
    )
    validate_author_intent_for_preparation(
        author, paper_state, intent_path, intent_sha
    )
    contract_sha = intent_sha
    qa_bundle_sha = canonical_hash(
        {
            "author_intent_contract_sha256": intent_sha,
            "qa_contract_sha256": qa_sha,
            "artifact_contract_sha256": artifact_sha,
        }
    )
    doc = expand_tex(manuscript, root) if fmt == "tex" else single_file_document(manuscript, strip_html_comments=fmt == "md")
    obligations = extract_obligations(
        author, qa, paper_state, artifact_contract
    )
    if qa_mode == "bounded_change":
        authoritative_obligations = extract_obligations(author, {}, {})
        authoritative_intent_ids = {
            str(
                item.get("intent_id")
                or item.get("obligation_id")
                or item.get("id")
            ).strip()
            for item in authoritative_obligations
            if item.get("intent_id") or item.get("obligation_id") or item.get("id")
        }
        affected_intent_ids = {
            item.strip() for item in revision_scope["affected_intent_ids"]
        }
        unknown_affected = sorted(affected_intent_ids - authoritative_intent_ids)
        if unknown_affected:
            raise PreparationError(
                "bounded_change affected_intent_ids are not present in the frozen author-intent authority: "
                + ", ".join(unknown_affected)
            )
    definitions = extract_definitions(author, qa, paper_state)
    baseline_ledger = conservation_ledger_entries(
        qa, artifact_contract, paper_state
    )
    units, appendix_info, formula_records = prepare_units(
        doc, fmt, root, author, qa, obligations, definitions
    )
    if not any(unit["type"] == "sentence" for unit in units):
        raise PreparationError("no reader-visible sentence was detected")
    apply_review_scope(units, qa_mode, revision_scope)
    revision_target_unit_ids = (
        sorted(
            {
                str(unit["unit_id"])
                for unit in units
                if unit.get("review_target") and unit.get("selected_for_review")
            }
        )
        if qa_mode == "bounded_change"
        else []
    )

    roles = role_list(qa)
    minimum_high_risk_independent_reviews = minimum_high_risk_review_setting(qa)
    review_policy = {
        "minimum_high_risk_independent_reviews": (
            minimum_high_risk_independent_reviews
        ),
        "required_semantic_roles": roles,
    }
    role_protocols = {role: ROLE_PROTOCOLS[role] for role in roles}
    role_protocols_sha = canonical_hash(
        {
            "role_protocol_version": ROLE_PROTOCOL_VERSION,
            "role_protocols": role_protocols,
        }
    )
    manuscript_sha = sha256_text(doc.source_texts[manuscript])
    expanded_sha = sha256_text(doc.text)
    formula_registry_sha = canonical_hash(formula_records)
    source_files = [
        {"path": str(path.relative_to(root)), "sha256": digest, "bytes": len(doc.source_texts[path].encode("utf-8"))}
        for path, digest in sorted(doc.source_hashes.items(), key=lambda item: str(item[0]))
    ]
    identity = {
        "schema_version": SCHEMA_VERSION,
        "manuscript_sha256": manuscript_sha,
        "expanded_sha256": expanded_sha,
        "contract_sha256": contract_sha,
        "qa_bundle_sha256": qa_bundle_sha,
        "role_protocols_sha256": role_protocols_sha,
        "formula_registry_sha256": formula_registry_sha,
        "unit_ids_and_hashes": [[unit["unit_id"], unit["text_sha256"]] for unit in units],
    }
    manifest_id = stable_id("qamanifest", canonical_hash(identity))
    context = contract_context(
        author,
        qa,
        paper_state,
        artifact_contract,
        obligations,
        definitions,
        baseline_ledger,
        evidence_registry,
    )

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    packet_dir = output_dir / "packets"
    packet_dir.mkdir(parents=True, exist_ok=True)
    max_units_per_packet = positive_integer_setting(
        qa,
        "max_units_per_packet",
        DEFAULT_MAX_UNITS_PER_PACKET,
        1,
        MAX_UNITS_PER_PACKET,
    )
    max_packet_bytes = positive_integer_setting(
        qa,
        "max_packet_bytes",
        DEFAULT_MAX_PACKET_BYTES,
        MIN_PACKET_BYTES,
        MAX_PACKET_BYTES,
    )
    packet_records: list[dict[str, Any]] = []
    for role in roles:
        assigned = [
            unit for unit in units
            if unit["review_target"] and unit["selected_for_review"] and role in unit["required_roles"]
        ]
        if not assigned:
            continue
        batches = [
            assigned[index : index + max_units_per_packet]
            for index in range(0, len(assigned), max_units_per_packet)
        ]

        def packet_payload_for(
            batch: list[dict[str, Any]], batch_index: int, batch_count: int
        ) -> dict[str, Any]:
            packet_id = stable_id(
                "packet",
                manifest_id,
                role,
                batch_index,
                *[unit["unit_id"] for unit in batch],
            )
            role_protocol = role_protocols[role]

            def formula_ids_in_context(value: Any) -> set[str]:
                if isinstance(value, str):
                    return set(re.findall(r"\[FORMULA:([^\]]+)\]", value))
                if isinstance(value, list):
                    return set().union(
                        *(formula_ids_in_context(item) for item in value)
                    ) if value else set()
                if isinstance(value, dict):
                    return set().union(
                        *(formula_ids_in_context(item) for item in value.values())
                    ) if value else set()
                return set()

            packet_formula_ids: set[str] = set()
            for unit in batch:
                packet_formula_ids.update(str(item) for item in unit.get("formula_ids", []))
                packet_formula_ids.update(
                    formula_ids_in_context(unit.get("context", {}))
                )
            packet_formulas = [
                item
                for item in formula_records
                if str(item.get("formula_id")) in packet_formula_ids
            ]
            return {
                "schema_version": PACKET_SCHEMA_VERSION,
                "schema_id": PACKET_SCHEMA_ID,
                "packet_id": packet_id,
                "manifest_id": manifest_id,
                "manifest_sha256": None,
                "manifest_sha256_instruction": "controller must compute SHA-256 of final qa_manifest.json bytes and inject it into every reviewer result",
                "manuscript_sha256": manuscript_sha,
                "content_sha256": expanded_sha,
                "expanded_manuscript_sha256": expanded_sha,
                "contract_sha256": contract_sha,
                "qa_contract_sha256": qa_sha,
                "artifact_contract_sha256": artifact_sha,
                "evidence_registry_sha256": (
                    evidence_registry_source["sha256"]
                    if evidence_registry_source is not None
                    else None
                ),
                "qa_bundle_sha256": qa_bundle_sha,
                "author_intent_authority_source": authority_source,
                "evidence_registry_source": evidence_registry_source,
                "role": role,
                "role_protocol_version": ROLE_PROTOCOL_VERSION,
                "role_protocol_sha256": canonical_hash(role_protocol),
                "formula_registry_sha256": formula_registry_sha,
                "required_checks": role_protocol["required_criterion_ids"],
                "role_protocol": role_protocol,
                "batch_index": batch_index,
                "batch_count": batch_count,
                "independence_requirement": "review independently; do not inspect other reviewers' findings",
                "reviewer_output_rule": "return structured findings only; do not edit manuscript",
                "review_result_schema": {
                    "required_top_level_fields": [
                        "schema_version", "result_id", "manifest_id",
                        "manifest_sha256", "manuscript_sha256", "content_sha256",
                        "contract_sha256", "qa_contract_sha256",
                        "artifact_contract_sha256", "packet_id", "packet_sha256",
                        "assignment_registry_sha256", "assignment_id", "status",
                        "reviewer", "unit_reviews", "ledgers", "conflicts",
                    ],
                    "reviewer_required_fields": [
                        "reviewer_id", "role", "independence_key",
                        "native_agent_id", "task_id",
                    ],
                    "unit_review_required_fields": list(
                        REVIEW_RESULT_REQUIRED_FIELDS
                    ),
                    "coverage_requirement": (
                        "return exactly one unit_review for every assigned "
                        "unit_id x required_checks criterion_id pair; use "
                        "not_applicable with evidence instead of omission"
                    ),
                },
                "contract_context": context,
                "artifact_contract": artifact_contract,
                "formula_context": packet_formulas,
                "units": batch,
            }

        while True:
            split_batches: list[list[dict[str, Any]]] = []
            oversized = False
            batch_count = len(batches)
            for batch_index, batch in enumerate(batches, 1):
                probe = packet_payload_for(batch, batch_index, batch_count)
                probe["packet_sha256"] = canonical_hash(probe)
                byte_count = len(
                    (json.dumps(probe, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
                )
                if byte_count <= max_packet_bytes:
                    split_batches.append(batch)
                    continue
                if len(batch) == 1:
                    raise PreparationError(
                        f"single review unit exceeds qa_contract.max_packet_bytes for role {role}: "
                        f"{batch[0]['unit_id']} requires {byte_count} bytes"
                    )
                midpoint = len(batch) // 2
                split_batches.extend((batch[:midpoint], batch[midpoint:]))
                oversized = True
            batches = split_batches
            if not oversized:
                break

        batch_count = len(batches)
        for batch_index, batch in enumerate(batches, 1):
            packet_payload = packet_payload_for(batch, batch_index, batch_count)
            packet_scope_hash = canonical_hash(packet_payload)
            packet_payload["packet_sha256"] = packet_scope_hash
            filename = f"{role}-{batch_index:03d}-of-{batch_count:03d}.json"
            packet_path = packet_dir / filename
            write_json(packet_path, packet_payload)
            packet_bytes = packet_path.stat().st_size
            if packet_bytes > max_packet_bytes:
                raise PreparationError(
                    f"packet size changed after batching for role {role}: {packet_bytes} bytes"
                )
            packet_records.append(
                {
                    "packet_id": packet_payload["packet_id"],
                    "role": role,
                    "batch_index": batch_index,
                    "batch_count": batch_count,
                    "path": f"packets/{filename}",
                    "packet_sha256": packet_scope_hash,
                    "role_protocol_version": ROLE_PROTOCOL_VERSION,
                    "role_protocol_sha256": packet_payload[
                        "role_protocol_sha256"
                    ],
                    "required_checks": packet_payload["required_checks"],
                    "packet_bytes": packet_bytes,
                    "unit_ids": [unit["unit_id"] for unit in batch],
                }
            )

    manuscript_record = {
        "path": str(manuscript), "relative_path": str(manuscript.relative_to(root)),
        "sha256": manuscript_sha, "expanded_sha256": expanded_sha, "format": fmt,
        "project_root": str(root),
    }
    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "schema_id": SCHEMA_ID,
        "status": "prepared",
        "manifest_id": manifest_id,
        "manifest_sha256": None,
        "manifest_sha256_scope": "not self-embedded; compute SHA-256 of final qa_manifest.json bytes before dispatch and require it in reviewer results",
        "manuscript_id": stable_id("manuscript", manuscript_sha, expanded_sha),
        "manuscript_sha256": manuscript_sha,
        "expanded_manuscript_sha256": expanded_sha,
        "contract_sha256": contract_sha,
        "qa_bundle_sha256": qa_bundle_sha,
        "author_intent_contract_sha256": intent_sha,
        "author_intent_authority_source": authority_source,
        "qa_contract_sha256": qa_sha,
        "artifact_contract_sha256": artifact_sha,
        "evidence_registry_sha256": (
            evidence_registry_source["sha256"]
            if evidence_registry_source is not None
            else None
        ),
        "role_protocol_version": ROLE_PROTOCOL_VERSION,
        "role_protocols_sha256": role_protocols_sha,
        "role_protocols": role_protocols,
        "formula_registry_sha256": formula_registry_sha,
        "formulas": formula_records,
        "manuscript": manuscript_record,
        "source": {
            "manuscript": manuscript_record,
            "source_files": source_files,
            "author_intent_contract": {"path": str(intent_path), "sha256": intent_sha},
            "author_intent_authority_source": authority_source,
            "qa_contract": {"path": str(qa_path), "sha256": qa_sha},
            "artifact_contract": (
                {"path": str(artifact_path), "sha256": artifact_sha}
                if artifact_path is not None else None
            ),
        },
        "inputs": {
            "manuscript": manuscript_record,
            "manuscript_sha256": manuscript_sha,
            "contract": {"path": str(intent_path), "sha256": contract_sha},
            "author_intent_contract": {"path": str(intent_path), "sha256": intent_sha},
            "author_intent_authority_source": authority_source,
            "qa_contract": {"path": str(qa_path), "sha256": qa_sha},
            "artifact_contract": (
                {"path": str(artifact_path), "sha256": artifact_sha}
                if artifact_path is not None else None
            ),
            "evidence_registry": evidence_registry_source,
        },
        "source_files": source_files,
        "appendix": appendix_info,
        "content_obligations": obligations,
        "definition_registry": definitions,
        "evidence_registry": evidence_registry,
        "content_conservation_ledger": baseline_ledger,
        "units": units,
        "packets": packet_records,
        "packetization": {
            "max_units_per_packet": max_units_per_packet,
            "max_packet_bytes": max_packet_bytes,
            "packet_count": len(packet_records),
        },
        "roles": {
            role: {
                "required": any(record["role"] == role for record in packet_records),
                "packet_ids": [
                    record["packet_id"] for record in packet_records if record["role"] == role
                ],
            }
            for role in roles
        },
        "ledgers": {
            "intent_to_text": [], "text_to_intent": [], "text_to_evidence": [],
            "baseline_to_candidate": baseline_ledger,
            "definitions": [], "revision_rechecks": [],
        },
        "qa_mode": qa_mode,
        "task_classification": classification,
        "revision_scope": revision_scope,
        "revision_target_unit_ids": revision_target_unit_ids,
        "review_policy": review_policy,
        "preparer_limits": [
            "risk flags are lexical routing signals, not semantic findings",
            "sentence source ranges conservatively inherit their parent visible block; text_start_in_parent narrows the normalized span",
            "unsupported or malformed balanced LaTeX structures fail closed when encountered by a required parser",
            "Python does not call a model, grade prose, or claim intent/evidence coverage",
        ],
    }
    manifest_path = output_dir / "qa_manifest.json"
    write_json(manifest_path, manifest)
    manifest_bytes_sha = sha256_bytes(manifest_path.read_bytes())
    (output_dir / "qa_manifest.sha256").write_text(
        f"{manifest_bytes_sha}  qa_manifest.json\n", encoding="utf-8"
    )
    assignment_template_path = output_dir / "qa_assignment_registry.template.json"
    assignment_records = [
        {
            "assignment_kind": "semantic_packet",
            "target_id": record["packet_id"],
            "target_sha256": record["packet_sha256"],
            "packet_id": record["packet_id"],
            "packet_sha256": record["packet_sha256"],
            "role": record["role"],
            "assignment_id": None,
            "native_agent_id": None,
            "task_id": None,
            "assigned_at": None,
        }
        for record in packet_records
    ]
    if qa_mode == "exhaustive":
        assignment_records.append(
            {
                "assignment_kind": "main_text_sufficiency",
                "target_id": "main-text-sufficiency",
                "target_sha256": expanded_sha,
                "assignment_id": None,
                "native_agent_id": None,
                "task_id": None,
                "assigned_at": None,
            }
        )
    write_json(
        assignment_template_path,
        {
            "schema_version": SCHEMA_VERSION,
            "schema_id": "qa-assignment-registry/1.0",
            "status": "template_requires_native_assignments",
            "manifest_id": manifest_id,
            "manifest_sha256": manifest_bytes_sha,
            "assignments": assignment_records,
            "instruction": (
                "The controller must copy this template, record the actual "
                "native assignment for every semantic packet"
                + (
                    " and for the one independent main-text-sufficiency target"
                    if qa_mode == "exhaustive"
                    else ""
                )
                + " before review, set status to assigned, and give each "
                "reviewer the SHA-256 of the filled registry."
                + (
                    " The fifth reviewer must not reuse any semantic "
                    "reviewer's native_agent_id."
                    if qa_mode == "exhaustive"
                    else " Bounded-change QA does not claim whole-manuscript "
                    "main-text sufficiency."
                )
            ),
        },
    )
    return {
        "status": "prepared", "manifest": str(manifest_path),
        "manifest_id": manifest_id, "manifest_file_sha256": manifest_bytes_sha,
        "assignment_registry_template": str(assignment_template_path),
        "units": len(units),
        "review_units": sum(bool(unit["review_target"] and unit["selected_for_review"]) for unit in units),
        "packets": len(packet_records),
    }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(
        description="Prepare deterministic sentence-level QA manifest and native-agent packets."
    )
    value.add_argument("--manuscript", required=True, help="UTF-8 .tex, .md, or .txt manuscript")
    value.add_argument("--project-root", help="root that bounds manuscript and LaTeX input/include paths; defaults to manuscript directory")
    value.add_argument("--author-intent-contract", required=True, help="JSON author intent contract, direct or wrapped in author_intent_contract")
    value.add_argument("--qa-contract", required=True, help="JSON QA contract, direct or wrapped in qa_contract")
    value.add_argument("--artifact-contract", help="optional JSON artifact contract kept distinct from author intent")
    value.add_argument("--output-dir", required=True, help="directory for qa_manifest.json and packets/*.json")
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        summary = prepare(args)
    except PreparationBlocked as exc:
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA_VERSION,
                    "schema_id": SCHEMA_ID,
                    "status": exc.status,
                    "reason_code": exc.reason_code,
                    "error": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return exc.exit_code
    except PreparationError as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "schema_id": SCHEMA_ID, "status": "fail", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return EXIT_PREPARATION_ERROR
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
