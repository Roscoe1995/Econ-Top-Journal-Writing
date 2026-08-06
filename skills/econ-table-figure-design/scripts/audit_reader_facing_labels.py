#!/usr/bin/env python3
"""Deterministically audit reader-facing table and figure labels.

The gate validates declared label coverage, hash freshness, language mode,
typed code-identifier exceptions, semantic metadata, bilingual pairing,
warning closure, numeric-content conservation, and hash-bound semantic/render
review records. It never edits an artifact and never judges whether wording is
economically true or stylistically natural. Those judgments remain with the
Table/Figure Role and the cold-reader passes described by the skill.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence


SCHEMA_VERSION = "1.0"
MANIFEST_SCHEMA_ID = "reader-facing-label-manifest/1.0"
REVIEW_SCHEMA_ID = "reader-facing-label-review/1.0"
REPORT_SCHEMA_ID = "reader-facing-label-audit/1.0"
GATE_TYPE = "reader_facing_labels"
EXIT_CODES = {
    "pass": 0,
    "fail": 1,
    "audit_incomplete": 4,
    "clarification_required": 5,
}
STATUS_PRIORITY = ("fail", "audit_incomplete", "clarification_required")
FINDING_PRIORITY = {
    "fail": 0,
    "audit_incomplete": 1,
    "clarification_required": 2,
    "warning": 3,
}

ALLOWED_LANGUAGES = {"zh-CN", "en"}
ALLOWED_STAGES = {"generated", "final"}
ALLOWED_OPERATIONS = {"new_artifact", "label_only_revision"}
ALLOWED_ROLES = {
    "title",
    "caption",
    "panel",
    "row",
    "column",
    "axis_x",
    "axis_y",
    "tick",
    "legend",
    "colorbar",
    "annotation",
}
ALLOWED_SEMANTIC_TYPES = {
    "artifact_title",
    "level",
    "difference",
    "ratio",
    "interaction",
    "growth_rate",
    "index",
    "interval",
    "parameter",
    "category",
    "other",
}
SIGNATURE_FIELDS = {
    "semantic_type",
    "object_id",
    "statistic_id",
    "unit_code",
    "transformation_code",
    "comparison_groups",
    "direction_code",
    "baseline_id",
    "numerator_id",
    "denominator_id",
    "interval_method_id",
    "time_basis_id",
}
ALLOWED_EXCEPTION_TYPES = {
    "standard_abbreviation",
    "mathematical_symbol",
    "formal_classification_code",
    "replication_codebook",
    "column_number",
    "proper_name",
}
ALLOWED_REVIEW_MODES = {"native_isolated_agent", "bounded_same_agent"}
RENDER_CHECKS = {
    "visible_text_matches_manifest",
    "no_truncation",
    "no_overlap",
    "legible_without_excessive_font_reduction",
    "notes_readable",
    "labels_fit",
}
STANDARD_TOKENS = {
    "GDP",
    "DID",
    "RDD",
    "IV",
    "PPML",
    "OLS",
    "R²",
    "R2",
    "Q1",
    "Q2",
    "Q3",
    "Q4",
    "CI",
    "SE",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
STATA_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:c|i|o|b|bn|l[0-9]*|f[0-9]*|d[0-9]*|"
    r"ib[0-9]+|ibn|[0-9]+(?:b|bn|o))\.[A-Za-z_][A-Za-z0-9_.]*",
    re.IGNORECASE,
)
GENERIC_CODE_RE = re.compile(
    r"^(?:group|series|var|value|ctrls?|depvar|indepvar|x|y)[0-9]*$",
    re.IGNORECASE,
)
GENERIC_CODE_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:group|series|var|value|ctrls?|depvar|indepvar|x|y)"
    r"[0-9]+(?![A-Za-z0-9])",
    re.IGNORECASE,
)
UNDERSCORE_IDENTIFIER_TOKEN_RE = re.compile(
    r"(?<!\w)(?:_+\w+|[^\W\d_]\w*_\w+)(?!\w)"
)
WORD_TOKEN_RE = re.compile(
    r"(?<!\w)[^\W\d_]\w*(?!\w)"
)
DOTTED_IDENTIFIER_RE = re.compile(
    r"^[^\W\d_]\w*(?:\.[^\W\d_]\w*)+$"
)
DOTTED_IDENTIFIER_TOKEN_RE = re.compile(
    r"(?<!\w)[^\W\d_]\w*(?:\.[^\W\d_]\w*)+\.?(?!\w)"
)
HASH_COMPOSITE_TOKEN_RE = re.compile(
    r"(?<!\w)\w+(?:\.\w+)*(?:#{1,2}\w+(?:\.\w+)*)+(?!\w)"
)
DOTTED_ABBREVIATION_RE = re.compile(
    r"^(?:(?:[A-Z]\.)+[A-Z]|e\.g|i\.e|Ph\.D|Ed\.D|D\.Phil|"
    r"M\.Phil|B\.Sc|M\.Sc|D\.Sc|LL\.B|LL\.M)$"
)
INTERNAL_ABBREVIATION_RE = re.compile(
    r"\b(?:avg|ctrls?|std|var|depvar|indepvar|fe)\b", re.IGNORECASE
)
STANDARD_ABBREVIATION_TOKEN_RE = re.compile(r"^(?=.*[A-Z])[A-Z0-9²/&.\-–—]+$")
MIXED_CASE_STANDARD_ABBREVIATIONS = {"PhD", "DiD"}
MATHEMATICAL_SYMBOL_TOKEN_RE = re.compile(
    r"^(?:[A-Za-z]|[\u0370-\u03ff\u1f00-\u1fff∑∏√∞±≤≥≠≈])"
    r"(?:_(?:[A-Za-z0-9]+|\{[A-Za-z0-9]+\})|[₀-₉]+|"
    r"\^(?:[A-Za-z0-9]+|\{[A-Za-z0-9]+\}))?$"
)
FORMAL_CODE_TOKEN_RE = re.compile(r"^(?=.*[A-Za-z])(?=.*[0-9])[A-Za-z0-9.\-–—]+$")
COLUMN_NUMBER_TOKEN_RE = re.compile(r"^\([0-9]+\)(?:[\-–—]\([0-9]+\))?$")
CJK_RE = re.compile(r"[\u3400-\u9fff]")
LATIN_RE = re.compile(r"[A-Za-z]")
HARD_OPAQUE_ZH_RE = re.compile(
    r"^(?:基准值|差异|差值|不同|高组|低组|高低组|高组[/／、]低组|高、低组|"
    r"变化|增量|占比)$|不同$"
)
HARD_OPAQUE_EN_RE = re.compile(
    r"^(?:baseline(?: value)?|difference|different|high group|low group|"
    r"high[/–—-]low group|high group[/–—-]low group|high and low groups?|"
    r"change|value)$|"
    r"(?:is|are|was|were|looks?)\s+different$",
    re.IGNORECASE,
)
POSSIBLE_OPAQUE_ZH_RE = re.compile(r"(?:差异|差值|之差)$")
POSSIBLE_OPAQUE_EN_RE = re.compile(r"(?:difference|differs)$", re.IGNORECASE)
NOT_APPLICABLE = "not_applicable"
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_JSON_DEPTH = 128


class DuplicateKeyError(ValueError):
    """A JSON object contains a duplicate key."""


class UnsafeOutputError(ValueError):
    """The requested output would overwrite a non-report object."""


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
        present = {item["status"] for item in self.findings}
        for status in STATUS_PRIORITY:
            if status in present:
                return status
        return "pass"

    def warnings(self, manifest_label: str) -> list[dict[str, Any]]:
        return [
            item
            for item in self.findings
            if item["status"] == "warning"
            and item.get("manifest_label") == manifest_label
        ]

    def sorted_findings(self) -> list[dict[str, Any]]:
        return sorted(
            self.findings,
            key=lambda item: (
                FINDING_PRIORITY.get(item["status"], 99),
                str(item.get("manifest_label", "")),
                str(item.get("code", "")),
                str(item.get("element_id", "")),
                json.dumps(item, ensure_ascii=False, sort_keys=True),
            ),
        )


@dataclass
class ManifestState:
    label: str
    path: Path
    payload: dict[str, Any]
    manifest_sha256: str
    artifact_path: Path | None
    artifact_sha256: str
    artifact_id: str
    artifact_family_id: str
    language: str
    stage: str
    declared_numeric_payload_paths: tuple[Path, ...]
    numeric_payload_hashes: dict[Path, str]
    labels: dict[str, dict[str, Any]]
    notes: dict[str, str]
    contexts: dict[str, dict[str, str]]
    concept_signatures: dict[str, dict[str, Any]]
    semantic_contract_sha256: str
    basic_packet: dict[str, Any]
    full_packet: dict[str, Any]
    review_path: Path | None = None
    review_sha256: str = ""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError(f"not a regular file: {path}")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_hash(value: Any) -> str:
    return sha256_bytes(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )


def normalize_display(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def code_scan_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    without_format = "".join(
        character
        for character in normalized
        if unicodedata.category(character) not in {"Cf", "Cc"}
    )
    return " ".join(without_format.split())


def is_token_continuation(character: str) -> bool:
    """Treat Unicode identifier continuations and marks as token continuations."""

    category = unicodedata.category(character)
    return (
        bool(re.match(r"\w", character))
        or category.startswith("M")
        or category == "Pc"
        or ("a" + character).isidentifier()
    )


def exact_spans_with_token_boundaries(
    text: str, literal: str
) -> list[tuple[int, int]]:
    """Return exact spans whose neighbors do not continue the visible token."""

    if not literal:
        return []
    spans: list[tuple[int, int]] = []
    for match in re.finditer(re.escape(literal), text):
        start, end = match.span()
        if start > 0 and is_token_continuation(text[start - 1]):
            continue
        if end < len(text) and is_token_continuation(text[end]):
            continue
        spans.append((start, end))
    return spans


def bounded_literal_spans(text: str, literal: str) -> list[tuple[int, int]]:
    """Return boundary-complete, case-sensitive spans for one visible literal."""

    normalized_text = unicodedata.normalize("NFC", text)
    normalized_literal = unicodedata.normalize("NFC", literal)
    return exact_spans_with_token_boundaries(normalized_text, normalized_literal)


def bounded_casefold_literal_spans(
    text: str, literal: str
) -> list[tuple[int, int]]:
    """Return case-insensitive spans mapped safely to the original NFC text."""

    normalized_text = unicodedata.normalize("NFC", text)
    normalized_literal = unicodedata.normalize("NFC", literal).casefold()
    if not normalized_literal:
        return []
    folded_parts: list[str] = []
    folded_starts: list[int] = []
    folded_ends: list[int] = []
    for index, character in enumerate(normalized_text):
        folded_character = character.casefold()
        folded_parts.append(folded_character)
        folded_starts.extend([index] * len(folded_character))
        folded_ends.extend([index + 1] * len(folded_character))
    folded_text = "".join(folded_parts)
    mapped: list[tuple[int, int]] = []
    for folded_start, folded_end in exact_spans_with_token_boundaries(
        folded_text, normalized_literal
    ):
        if folded_start == folded_end:
            continue
        span = (folded_starts[folded_start], folded_ends[folded_end - 1])
        if span not in mapped:
            mapped.append(span)
    return mapped


def nfkc_literal_occurrences(
    text: str, literal: str
) -> list[tuple[int, int, bool]]:
    """Map every NFKC-equivalent occurrence to the NFC original and its boundary state."""

    normalized_text = unicodedata.normalize("NFC", text)
    normalized_literal = unicodedata.normalize(
        "NFKC", unicodedata.normalize("NFC", literal)
    )
    if not normalized_literal:
        return []
    mapped_parts: list[str] = []
    mapped_starts: list[int] = []
    mapped_ends: list[int] = []
    for index, character in enumerate(normalized_text):
        mapped_character = unicodedata.normalize("NFKC", character)
        mapped_parts.append(mapped_character)
        mapped_starts.extend([index] * len(mapped_character))
        mapped_ends.extend([index + 1] * len(mapped_character))
    mapped_text = "".join(mapped_parts)
    if mapped_text != unicodedata.normalize("NFKC", normalized_text):
        raise ValueError(
            "NFKC mapping cannot be aligned unambiguously to the original text"
        )
    original_occurrences: list[tuple[int, int, bool]] = []
    search_start = 0
    while True:
        mapped_start = mapped_text.find(normalized_literal, search_start)
        if mapped_start < 0:
            break
        mapped_end = mapped_start + len(normalized_literal)
        has_boundaries = not (
            mapped_start > 0
            and is_token_continuation(mapped_text[mapped_start - 1])
        ) and not (
            mapped_end < len(mapped_text)
            and is_token_continuation(mapped_text[mapped_end])
        )
        occurrence = (
            mapped_starts[mapped_start],
            mapped_ends[mapped_end - 1],
            has_boundaries,
        )
        original_start, original_end, _ = occurrence
        original_equivalent = unicodedata.normalize(
            "NFKC", normalized_text[original_start:original_end]
        )
        if (
            original_equivalent == normalized_literal
            and occurrence not in original_occurrences
        ):
            original_occurrences.append(occurrence)
        search_start = mapped_start + 1
    return original_occurrences


def bounded_nfkc_literal_spans(
    text: str, literal: str
) -> list[tuple[int, int]]:
    """Map boundary-complete NFKC-equivalent literal spans to the NFC original."""

    return [
        (start, end)
        for start, end, has_boundaries in nfkc_literal_occurrences(text, literal)
        if has_boundaries
    ]


def has_camel_case_transition(text: str) -> bool:
    """Detect Unicode camel/Pascal boundaries without treating CJK Lo as case."""

    categories = [unicodedata.category(character) for character in text]
    if any(
        left in {"Ll", "Lt"} and right == "Lu"
        for left, right in zip(categories, categories[1:])
    ):
        return True
    return any(
        categories[index - 1] == "Lu"
        and categories[index] == "Lu"
        and categories[index + 1] == "Ll"
        for index in range(1, len(categories) - 1)
    )


def is_traditional_dotted_abbreviation(text: str) -> bool:
    """Recognize a closed natural abbreviation only in terminal-dot form."""

    normalized = unicodedata.normalize("NFC", text)
    return normalized.endswith(".") and bool(
        DOTTED_ABBREVIATION_RE.fullmatch(normalized[:-1])
    )


def is_standard_abbreviation_token(text: str) -> bool:
    """Recognize only closed conventional forms eligible for a typed exception."""

    normalized = unicodedata.normalize("NFC", text)
    return bool(
        STANDARD_ABBREVIATION_TOKEN_RE.fullmatch(normalized)
        or is_traditional_dotted_abbreviation(normalized)
        or normalized in MIXED_CASE_STANDARD_ABBREVIATIONS
    )


def independent_reader_label_is_visible(
    display_text: str, token: str, reader_label: str
) -> bool:
    """Require a boundary-complete reader label outside every raw-token span."""

    token_spans = bounded_literal_spans(display_text, token)
    reader_spans = bounded_literal_spans(display_text, reader_label)
    return bool(token_spans) and any(
        all(
            reader_end <= token_start or reader_start >= token_end
            for token_start, token_end in token_spans
        )
        for reader_start, reader_end in reader_spans
    )


def high_confidence_internal_key(text: str) -> bool:
    """Identify internal keys whose visible reuse is deterministically code-like."""

    scanned = code_scan_text(text)
    return bool(
        UNDERSCORE_IDENTIFIER_TOKEN_RE.fullmatch(scanned)
        or STATA_TOKEN_RE.fullmatch(scanned)
        or GENERIC_CODE_RE.fullmatch(scanned)
        or has_camel_case_transition(scanned)
        or (
            DOTTED_IDENTIFIER_RE.fullmatch(scanned)
            and not is_traditional_dotted_abbreviation(scanned)
        )
        or "#" in scanned
    )


def replication_codebook_token_is_structurally_eligible(text: str) -> bool:
    """Require one closed raw-name/code expression, never reader prose."""

    scanned = code_scan_text(text)
    return bool(
        UNDERSCORE_IDENTIFIER_TOKEN_RE.fullmatch(scanned)
        or STATA_TOKEN_RE.fullmatch(scanned)
        or GENERIC_CODE_RE.fullmatch(scanned)
        or has_camel_case_transition(scanned)
        or (
            DOTTED_IDENTIFIER_RE.fullmatch(scanned)
            and not is_traditional_dotted_abbreviation(scanned)
        )
        or HASH_COMPOSITE_TOKEN_RE.fullmatch(scanned)
    )


def embedded_exception_occurrence_is_identifier_risk(
    text: str, start: int, end: int
) -> bool:
    """Detect where the raw scanner can truncate a high-confidence visible token."""

    scanned_literal = code_scan_text(text[start:end])
    raw_scanner_can_emit_literal = bool(
        UNDERSCORE_IDENTIFIER_TOKEN_RE.fullmatch(scanned_literal)
        or STATA_TOKEN_RE.fullmatch(scanned_literal)
        or has_camel_case_transition(scanned_literal)
        or (
            DOTTED_IDENTIFIER_RE.fullmatch(scanned_literal)
            and not is_traditional_dotted_abbreviation(scanned_literal)
        )
        or GENERIC_CODE_TOKEN_RE.fullmatch(scanned_literal)
        or HASH_COMPOSITE_TOKEN_RE.fullmatch(scanned_literal)
    )
    if not raw_scanner_can_emit_literal:
        return False

    left_continuation = start > 0 and is_token_continuation(text[start - 1])
    right_continuation = end < len(text) and is_token_continuation(text[end])
    left_nonword_identifier = left_continuation and not bool(
        re.match(r"\w", text[start - 1])
    )
    right_nonword_identifier = right_continuation and not bool(
        re.match(r"\w", text[end])
    )
    return left_nonword_identifier or right_nonword_identifier


def proper_name_exception_is_structurally_eligible(text: str) -> bool:
    """Allow a typed proper-name claim only for otherwise plain camel-case names."""

    scanned = code_scan_text(text)
    return has_camel_case_transition(scanned) and not bool(
        UNDERSCORE_IDENTIFIER_TOKEN_RE.fullmatch(scanned)
        or STATA_TOKEN_RE.fullmatch(scanned)
        or GENERIC_CODE_RE.fullmatch(scanned)
        or (
            DOTTED_IDENTIFIER_RE.fullmatch(scanned)
            and not is_traditional_dotted_abbreviation(scanned)
        )
        or "#" in scanned
    )


def normalized_sha(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip().lower()
    return candidate if SHA256_RE.fullmatch(candidate) else ""


def validate_json_value(value: Any, location: str = "$") -> None:
    pending: list[tuple[Any, str, int]] = [(value, location, 0)]
    while pending:
        current, current_location, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise ValueError(
                f"JSON nesting exceeds {MAX_JSON_DEPTH} levels at {current_location}"
            )
        if isinstance(current, float) and not math.isfinite(current):
            raise ValueError(f"non-finite JSON number at {current_location}")
        if isinstance(current, str):
            for character in current:
                category = unicodedata.category(character)
                if category == "Cs" or (
                    category in {"Cc", "Cf"}
                    and character not in {"\n", "\r", "\t"}
                ):
                    raise ValueError(
                        "forbidden Unicode control, format, or surrogate "
                        f"character at {current_location}"
                    )
        elif isinstance(current, list):
            pending.extend(
                (item, f"{current_location}[{index}]", depth + 1)
                for index, item in enumerate(current)
            )
        elif isinstance(current, dict):
            for key, item in current.items():
                pending.append((key, f"{current_location}.<key>", depth + 1))
                pending.append((item, f"{current_location}.{key}", depth + 1))


def strict_json_load_with_hash(path: Path) -> tuple[dict[str, Any], str]:
    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for key, value in pairs:
            if key in output:
                raise DuplicateKeyError(f"duplicate JSON key: {key}")
            output[key] = value
        return output

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("JSON input must be a regular file")
        if metadata.st_size > MAX_JSON_BYTES:
            raise ValueError(
                f"JSON input exceeds the {MAX_JSON_BYTES}-byte safety limit"
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, MAX_JSON_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_JSON_BYTES:
                raise ValueError(
                    f"JSON input exceeds the {MAX_JSON_BYTES}-byte safety limit"
                )
        raw_bytes = b"".join(chunks)
    finally:
        os.close(descriptor)
    raw = raw_bytes.decode("utf-8", errors="strict")
    try:
        value = json.loads(
            raw,
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except RecursionError as exc:
        raise ValueError("JSON nesting is too deep to parse safely") from exc
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    validate_json_value(value)
    return value, sha256_bytes(raw_bytes)


def strict_json_load(path: Path) -> dict[str, Any]:
    value, _ = strict_json_load_with_hash(path)
    return value


def ensure_within_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes project root: {path}") from exc


def resolve_input_path(raw: Any, root: Path, base: Path | None = None) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("path must be a non-empty string")
    candidate = Path(raw.strip())
    if not candidate.is_absolute():
        candidate = (base or root) / candidate
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"cannot resolve path safely: {candidate}: {exc}") from exc
    ensure_within_root(resolved, root)
    return resolved


def load_json(
    path: Path, root: Path, audit: GateAudit, label: str
) -> tuple[dict[str, Any], str] | None:
    try:
        resolved = path.resolve()
        ensure_within_root(resolved, root)
        return strict_json_load_with_hash(resolved)
    except (
        OSError,
        RuntimeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
    ) as exc:
        audit.add(
            "audit_incomplete",
            "invalid_json",
            f"Cannot read {label} as strict UTF-8 JSON: {exc}",
            manifest_label=label,
            path=str(path),
        )
        return None


def required_string(
    value: Any,
    audit: GateAudit,
    code: str,
    message: str,
    *,
    manifest_label: str,
    element_id: str | None = None,
) -> str:
    if not isinstance(value, str) or not value.strip():
        audit.add(
            "audit_incomplete",
            code,
            message,
            manifest_label=manifest_label,
            element_id=element_id,
        )
        return ""
    return value.strip()


def string_list(
    value: Any,
    audit: GateAudit,
    code: str,
    message: str,
    *,
    manifest_label: str,
    element_id: str | None = None,
    allow_empty: bool = False,
) -> list[str]:
    if not isinstance(value, list) or (not value and not allow_empty):
        audit.add(
            "audit_incomplete",
            code,
            message,
            manifest_label=manifest_label,
            element_id=element_id,
        )
        return []
    output: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            audit.add(
                "audit_incomplete",
                code,
                message,
                manifest_label=manifest_label,
                element_id=element_id,
            )
            continue
        output.append(item.strip())
    return output


def has_invisible_control(text: str) -> bool:
    return any(
        unicodedata.category(character) in {"Cf", "Cc"}
        and character not in {"\n", "\r", "\t"}
        for character in text
    )


def warning_fingerprint(
    code: str,
    element_id: str,
    visible_text: str,
    review_context_sha256: str,
) -> str:
    return canonical_hash(
        {
            "code": code,
            "element_id": element_id,
            "visible_text_sha256": sha256_text(normalize_display(visible_text)),
            "review_context_sha256": review_context_sha256,
        }
    )


def add_warning(
    audit: GateAudit,
    *,
    manifest_label: str,
    code: str,
    message: str,
    element_id: str,
    visible_text: str,
    review_context_sha256: str,
) -> None:
    audit.add(
        "warning",
        code,
        message,
        manifest_label=manifest_label,
        element_id=element_id,
        visible_text=visible_text,
        finding_id=warning_fingerprint(
            code, element_id, visible_text, review_context_sha256
        ),
    )


def validate_exceptions(
    raw: Any,
    display_text: str,
    internal_key: str,
    audit: GateAudit,
    *,
    manifest_label: str,
    element_id: str,
) -> dict[str, set[str]]:
    if raw is None:
        return {}
    if not isinstance(raw, list):
        audit.add(
            "audit_incomplete",
            "typed_exceptions_invalid",
            "exceptions must be a list of exact typed exception records.",
            manifest_label=manifest_label,
            element_id=element_id,
        )
        return {}
    covered: dict[str, set[str]] = {}
    for record in raw:
        if not isinstance(record, dict):
            audit.add(
                "audit_incomplete",
                "typed_exception_invalid",
                "Each exception must be an object.",
                manifest_label=manifest_label,
                element_id=element_id,
            )
            continue
        exception_type = required_string(
            record.get("type"),
            audit,
            "typed_exception_type_missing",
            "Each exception requires a closed type.",
            manifest_label=manifest_label,
            element_id=element_id,
        )
        token = required_string(
            record.get("token"),
            audit,
            "typed_exception_token_missing",
            "Each exception requires one exact visible token.",
            manifest_label=manifest_label,
            element_id=element_id,
        )
        required_string(
            record.get("reason"),
            audit,
            "typed_exception_reason_missing",
            "Each exception requires a reason.",
            manifest_label=manifest_label,
            element_id=element_id,
        )
        required_string(
            record.get("reader_definition"),
            audit,
            "typed_exception_definition_missing",
            "Each exception requires a reader-facing definition.",
            manifest_label=manifest_label,
            element_id=element_id,
        )
        token_type_compatible = bool(
            exception_type in ALLOWED_EXCEPTION_TYPES and token
        )
        if exception_type and exception_type not in ALLOWED_EXCEPTION_TYPES:
            audit.add(
                "fail",
                "typed_exception_type_unknown",
                "Exception type is not in the closed allowlist.",
                manifest_label=manifest_label,
                element_id=element_id,
                exception_type=exception_type,
            )
        if exception_type == "standard_abbreviation" and token:
            if not is_standard_abbreviation_token(token):
                token_type_compatible = False
                audit.add(
                    "fail",
                    "typed_exception_token_incompatible",
                    "standard_abbreviation requires a closed conventional abbreviation token.",
                    manifest_label=manifest_label,
                    element_id=element_id,
                    token=token,
                    exception_type=exception_type,
                )
        elif exception_type == "mathematical_symbol" and token:
            if not MATHEMATICAL_SYMBOL_TOKEN_RE.fullmatch(token):
                token_type_compatible = False
                audit.add(
                    "fail",
                    "typed_exception_token_incompatible",
                    "mathematical_symbol requires a mathematical or Greek symbol token.",
                    manifest_label=manifest_label,
                    element_id=element_id,
                    token=token,
                    exception_type=exception_type,
                )
        elif exception_type == "formal_classification_code" and token:
            if not FORMAL_CODE_TOKEN_RE.fullmatch(token):
                token_type_compatible = False
                audit.add(
                    "fail",
                    "typed_exception_token_incompatible",
                    "formal_classification_code requires an official alphanumeric code form.",
                    manifest_label=manifest_label,
                    element_id=element_id,
                    token=token,
                    exception_type=exception_type,
                )
        elif exception_type == "column_number" and token:
            if not COLUMN_NUMBER_TOKEN_RE.fullmatch(token):
                token_type_compatible = False
                audit.add(
                    "fail",
                    "typed_exception_token_incompatible",
                    "column_number requires a parenthesized column number or range.",
                    manifest_label=manifest_label,
                    element_id=element_id,
                    token=token,
                    exception_type=exception_type,
                )
        elif exception_type == "replication_codebook":
            if token and not replication_codebook_token_is_structurally_eligible(
                token
            ):
                token_type_compatible = False
                audit.add(
                    "fail",
                    "replication_codebook_token_incompatible",
                    "replication_codebook requires one closed raw-name or code expression, not reader prose or a phrase-wide token.",
                    manifest_label=manifest_label,
                    element_id=element_id,
                    token=token,
                )
            required_string(
                record.get("source_locator"),
                audit,
                "replication_codebook_source_missing",
                "replication_codebook exceptions require a bounded codebook or replication source locator.",
                manifest_label=manifest_label,
                element_id=element_id,
            )
            reader_label = required_string(
                record.get("reader_label"),
                audit,
                "replication_codebook_reader_label_missing",
                "replication_codebook exceptions require an independent public reader_label displayed beside the raw token.",
                manifest_label=manifest_label,
                element_id=element_id,
            )
            if not internal_key:
                audit.add(
                    "audit_incomplete",
                    "replication_codebook_internal_key_missing",
                    "replication_codebook requires this label's internal_key for exact raw-name binding.",
                    manifest_label=manifest_label,
                    element_id=element_id,
                    token=token,
                )
            elif internal_key == NOT_APPLICABLE:
                audit.add(
                    "fail",
                    "replication_codebook_internal_key_unbound",
                    "replication_codebook cannot be used when internal_key is not_applicable.",
                    manifest_label=manifest_label,
                    element_id=element_id,
                    token=token,
                )
            elif token and unicodedata.normalize(
                "NFC", token
            ) != unicodedata.normalize("NFC", internal_key):
                audit.add(
                    "fail",
                    "replication_codebook_internal_key_mismatch",
                    "The raw code token must NFC-exactly match this label's internal_key.",
                    manifest_label=manifest_label,
                    element_id=element_id,
                    token=token,
                    internal_key=internal_key,
                )
            if reader_label and token and not independent_reader_label_is_visible(
                display_text, token, reader_label
            ):
                audit.add(
                    "fail",
                    "replication_codebook_reader_label_not_displayed",
                    "The independent reader_label must appear beside, and differ from, the raw code token.",
                    manifest_label=manifest_label,
                    element_id=element_id,
                    token=token,
                    reader_label=reader_label,
                )
        if token:
            if any(character in token for character in "*?[]"):
                audit.add(
                    "fail",
                    "typed_exception_wildcard_forbidden",
                    "Exception tokens must be exact and cannot contain wildcards.",
                    manifest_label=manifest_label,
                    element_id=element_id,
                    token=token,
                )
            elif not bounded_literal_spans(display_text, token):
                audit.add(
                    "fail",
                    "typed_exception_token_absent",
                    "The exact exception token is not present in display text.",
                    manifest_label=manifest_label,
                    element_id=element_id,
                    token=token,
                )
            else:
                normalized_display = unicodedata.normalize("NFC", display_text)
                normalized_token_nfc = unicodedata.normalize("NFC", token)
                normalized_token = code_scan_text(token)
                try:
                    normalized_occurrences = nfkc_literal_occurrences(
                        display_text, token
                    )
                except ValueError as exc:
                    audit.add(
                        "fail",
                        "typed_exception_normalization_mapping_unavailable",
                        str(exc),
                        manifest_label=manifest_label,
                        element_id=element_id,
                        token=token,
                    )
                    normalized_occurrences = []
                boundary_collisions = sorted(
                    (start, end)
                    for start, end, has_boundaries in normalized_occurrences
                    if normalized_display[start:end] == normalized_token_nfc
                    and not has_boundaries
                    and embedded_exception_occurrence_is_identifier_risk(
                        normalized_display, start, end
                    )
                )
                if boundary_collisions:
                    audit.add(
                        "fail",
                        "typed_exception_token_boundary_collision",
                        "An exact exception token cannot cover another occurrence embedded in a longer visible token.",
                        manifest_label=manifest_label,
                        element_id=element_id,
                        token=token,
                        conflicting_spans=[
                            {"start": start, "end": end}
                            for start, end in boundary_collisions
                        ],
                    )
                compatibility_variants = sorted(
                    {
                        normalized_display[start:end]
                        for start, end, has_boundaries in normalized_occurrences
                        if normalized_display[start:end] != normalized_token_nfc
                        and (
                            has_boundaries
                            or embedded_exception_occurrence_is_identifier_risk(
                                normalized_display, start, end
                            )
                        )
                    }
                )
                if compatibility_variants:
                    audit.add(
                        "fail",
                        "typed_exception_normalization_collision",
                        "An exact exception token cannot cover a compatibility-distinct visible token.",
                        manifest_label=manifest_label,
                        element_id=element_id,
                        token=token,
                        conflicting_tokens=compatibility_variants,
                    )
                if token_type_compatible:
                    covered.setdefault(normalized_token, set()).add(exception_type)
    return covered


def validate_signature(
    raw: Any,
    audit: GateAudit,
    *,
    manifest_label: str,
    element_id: str,
    meaning_status: str,
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        audit.add(
            "audit_incomplete",
            "semantic_signature_invalid",
            "Each label requires a language-neutral semantic_signature object.",
            manifest_label=manifest_label,
            element_id=element_id,
        )
        return {}
    missing = sorted(SIGNATURE_FIELDS - set(raw))
    extra = sorted(set(raw) - SIGNATURE_FIELDS)
    if missing:
        audit.add(
            "audit_incomplete",
            "semantic_signature_fields_missing",
            "Semantic signature lacks required fields.",
            manifest_label=manifest_label,
            element_id=element_id,
            fields=missing,
        )
    if extra:
        audit.add(
            "audit_incomplete",
            "semantic_signature_fields_unknown",
            "Semantic signature contains unknown fields.",
            manifest_label=manifest_label,
            element_id=element_id,
            fields=extra,
        )

    normalized: dict[str, Any] = {}
    for field_name in sorted(SIGNATURE_FIELDS - {"comparison_groups"}):
        value = raw.get(field_name)
        if not isinstance(value, str) or not value.strip():
            audit.add(
                "audit_incomplete",
                "semantic_signature_value_invalid",
                "Semantic signature scalar fields must be non-empty strings.",
                manifest_label=manifest_label,
                element_id=element_id,
                field=field_name,
            )
            normalized[field_name] = ""
        else:
            normalized[field_name] = value.strip()
    normalized["comparison_groups"] = string_list(
        raw.get("comparison_groups"),
        audit,
        "semantic_comparison_groups_invalid",
        "comparison_groups must be a list of stable IDs; use an empty list only when not applicable.",
        manifest_label=manifest_label,
        element_id=element_id,
        allow_empty=True,
    )

    semantic_type = normalized.get("semantic_type", "")
    if semantic_type and semantic_type not in ALLOWED_SEMANTIC_TYPES:
        audit.add(
            "fail",
            "semantic_type_unknown",
            "semantic_type is not in the closed set.",
            manifest_label=manifest_label,
            element_id=element_id,
            semantic_type=semantic_type,
        )

    comparison_groups = normalized["comparison_groups"]
    if len(comparison_groups) != len(set(comparison_groups)):
        audit.add(
            "fail",
            "semantic_comparison_groups_duplicate",
            "comparison_groups must contain distinct stable group IDs.",
            manifest_label=manifest_label,
            element_id=element_id,
        )

    if meaning_status != "confirmed":
        return normalized

    def require_not_na(field_name: str, message: str) -> None:
        if normalized.get(field_name) in {"", NOT_APPLICABLE}:
            audit.add(
                "fail",
                "semantic_required_value_missing",
                message,
                manifest_label=manifest_label,
                element_id=element_id,
                field=field_name,
                semantic_type=semantic_type,
            )

    if semantic_type == "difference":
        if len(comparison_groups) < 2:
            audit.add(
                "fail",
                "difference_groups_missing",
                "A difference requires at least two comparison-group IDs.",
                manifest_label=manifest_label,
                element_id=element_id,
            )
        require_not_na(
            "direction_code", "A difference requires a subtraction direction."
        )
        require_not_na("unit_code", "A difference requires a unit or scale code.")
    elif semantic_type == "ratio":
        require_not_na("numerator_id", "A ratio requires a numerator.")
        require_not_na("denominator_id", "A ratio requires a denominator.")
        require_not_na("unit_code", "A ratio requires a unit or scale code.")
    elif semantic_type == "interaction":
        if len(comparison_groups) < 2:
            audit.add(
                "fail",
                "interaction_components_missing",
                "An interaction requires at least two component IDs.",
                manifest_label=manifest_label,
                element_id=element_id,
            )
        require_not_na("baseline_id", "An interaction requires a reference case.")
        require_not_na(
            "direction_code", "An interaction requires an interpretation direction."
        )
        require_not_na(
            "unit_code", "An interaction requires an outcome unit or coefficient scale."
        )
    elif semantic_type == "growth_rate":
        require_not_na("time_basis_id", "A growth rate requires a time basis.")
        require_not_na("unit_code", "A growth rate requires a unit or scale code.")
    elif semantic_type == "index":
        require_not_na(
            "transformation_code", "An index requires a construction or transformation."
        )
        require_not_na(
            "direction_code", "An index requires a direction-of-scale definition."
        )
        require_not_na("unit_code", "An index requires a unit or scale code.")
    elif semantic_type == "interval":
        require_not_na(
            "interval_method_id", "An interval requires a construction method."
        )
        require_not_na("unit_code", "An interval requires a unit or scale code.")
    elif semantic_type in {"level", "parameter"}:
        require_not_na(
            "unit_code", "A level or parameter requires a unit, including dimensionless."
        )
    return normalized


def validate_hashed_payload_file(
    record: dict[str, Any],
    *,
    path_field: str,
    hash_field: str,
    root: Path,
    audit: GateAudit,
    manifest_label: str,
) -> tuple[Path | None, str]:
    try:
        payload_path = resolve_input_path(record.get(path_field), root)
    except ValueError as exc:
        audit.add(
            "audit_incomplete",
            "numeric_payload_path_invalid",
            str(exc),
            manifest_label=manifest_label,
            field=path_field,
        )
        return None, ""
    expected = normalized_sha(record.get(hash_field))
    if not expected:
        audit.add(
            "audit_incomplete",
            "numeric_payload_hash_missing",
            "Numeric payload files require a valid declared SHA-256.",
            manifest_label=manifest_label,
            field=hash_field,
        )
    if not payload_path.is_file():
        audit.add(
            "audit_incomplete",
            "numeric_payload_missing",
            "Declared numeric payload file is missing.",
            manifest_label=manifest_label,
            field=path_field,
            path=str(payload_path),
        )
        return payload_path, ""
    try:
        actual = sha256_file(payload_path)
    except OSError as exc:
        audit.add(
            "audit_incomplete",
            "numeric_payload_unreadable",
            f"Cannot read declared numeric payload file: {exc}",
            manifest_label=manifest_label,
            field=path_field,
            path=str(payload_path),
        )
        return payload_path, ""
    if expected and actual != expected:
        audit.add(
            "fail",
            "numeric_payload_hash_stale",
            "Numeric payload bytes do not match the declared SHA-256.",
            manifest_label=manifest_label,
            field=hash_field,
            path=str(payload_path),
            expected_sha256=expected,
            actual_sha256=actual,
        )
    return payload_path, actual


def validate_numeric_integrity(
    payload: dict[str, Any],
    root: Path,
    audit: GateAudit,
    manifest_label: str,
) -> tuple[dict[Path, str], tuple[Path, ...]]:
    artifact = payload.get("artifact")
    operation = artifact.get("operation") if isinstance(artifact, dict) else None
    record = payload.get("numeric_integrity")
    if not isinstance(record, dict):
        audit.add(
            "audit_incomplete",
            "numeric_integrity_missing",
            "Manifest requires numeric_integrity metadata.",
            manifest_label=manifest_label,
        )
        return {}, ()
    required_string(
        record.get("canonicalization_id"),
        audit,
        "numeric_canonicalization_id_missing",
        "numeric_integrity requires the stable canonicalization procedure ID used to create its payload files.",
        manifest_label=manifest_label,
    )
    required_string(
        record.get("payload_description"),
        audit,
        "numeric_payload_description_missing",
        "numeric_integrity requires a description of the numeric cells, sample, and result metadata represented by the payload.",
        manifest_label=manifest_label,
    )
    required_string(
        record.get("producer_source_locator"),
        audit,
        "numeric_producer_source_missing",
        "numeric_integrity requires a source locator for the code or deterministic procedure that generated the payload.",
        manifest_label=manifest_label,
    )
    payload_hashes: dict[Path, str] = {}
    declared_paths: list[Path] = []
    if operation == "new_artifact":
        payload_path, actual = validate_hashed_payload_file(
            record,
            path_field="numeric_payload_path",
            hash_field="numeric_payload_sha256",
            root=root,
            audit=audit,
            manifest_label=manifest_label,
        )
        if payload_path is not None:
            declared_paths.append(payload_path)
            if actual:
                payload_hashes[payload_path] = actual
    elif operation == "label_only_revision":
        before_path, before = validate_hashed_payload_file(
            record,
            path_field="before_path",
            hash_field="before_sha256",
            root=root,
            audit=audit,
            manifest_label=manifest_label,
        )
        after_path, after = validate_hashed_payload_file(
            record,
            path_field="after_path",
            hash_field="after_sha256",
            root=root,
            audit=audit,
            manifest_label=manifest_label,
        )
        if before_path is not None:
            declared_paths.append(before_path)
            if before:
                payload_hashes[before_path] = before
        if after_path is not None:
            declared_paths.append(after_path)
            if after:
                payload_hashes[after_path] = after
        if before_path is not None and after_path is not None and before_path == after_path:
            audit.add(
                "fail",
                "numeric_revision_paths_identical",
                "A label-only revision requires distinct before and after numeric payload files.",
                manifest_label=manifest_label,
            )
        elif (
            before_path is not None
            and after_path is not None
            and before_path.is_file()
            and after_path.is_file()
        ):
            try:
                same_file = os.path.samefile(before_path, after_path)
            except OSError as exc:
                audit.add(
                    "audit_incomplete",
                    "numeric_revision_file_identity_unavailable",
                    f"Cannot verify that before and after payloads are independent files: {exc}",
                    manifest_label=manifest_label,
                )
            else:
                if same_file:
                    audit.add(
                        "fail",
                        "numeric_revision_files_same_identity",
                        "Before and after numeric payload paths resolve to the same file identity or hard link.",
                        manifest_label=manifest_label,
                    )
        if before and after and before != after:
            audit.add(
                "fail",
                "numeric_content_changed",
                "A label-only revision changed the verified canonical numeric payload bytes.",
                manifest_label=manifest_label,
                before_sha256=before,
                after_sha256=after,
            )
    return payload_hashes, tuple(dict.fromkeys(declared_paths))


def validate_manifest(
    path: Path,
    root: Path,
    cli_stage: str,
    audit: GateAudit,
    manifest_label: str,
) -> ManifestState | None:
    loaded = load_json(path, root, audit, manifest_label)
    if loaded is None:
        return None
    payload, manifest_sha256 = loaded
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get(
        "schema_id"
    ) != MANIFEST_SCHEMA_ID:
        audit.add(
            "audit_incomplete",
            "manifest_schema_invalid",
            "Label manifest must use reader-facing-label-manifest/1.0.",
            manifest_label=manifest_label,
        )
    required_string(
        payload.get("manifest_id"),
        audit,
        "manifest_id_missing",
        "Manifest requires manifest_id.",
        manifest_label=manifest_label,
    )
    required_string(
        payload.get("manifest_revision"),
        audit,
        "manifest_revision_missing",
        "Manifest requires manifest_revision.",
        manifest_label=manifest_label,
    )
    artifact_family_id = required_string(
        payload.get("artifact_family_id"),
        audit,
        "artifact_family_id_missing",
        "Manifest requires artifact_family_id for optional bilingual pairing.",
        manifest_label=manifest_label,
    )

    artifact = payload.get("artifact")
    if not isinstance(artifact, dict):
        audit.add(
            "audit_incomplete",
            "artifact_record_missing",
            "Manifest requires an artifact object.",
            manifest_label=manifest_label,
        )
        artifact = {}
    artifact_id = required_string(
        artifact.get("artifact_id"),
        audit,
        "artifact_id_missing",
        "Artifact requires artifact_id.",
        manifest_label=manifest_label,
    )
    stage = required_string(
        artifact.get("stage"),
        audit,
        "artifact_stage_missing",
        "Artifact requires stage.",
        manifest_label=manifest_label,
    )
    if stage and stage not in ALLOWED_STAGES:
        audit.add(
            "fail",
            "artifact_stage_unknown",
            "Artifact stage must be generated or final.",
            manifest_label=manifest_label,
            stage=stage,
        )
    if stage and stage != cli_stage:
        audit.add(
            "fail",
            "cli_stage_mismatch",
            "CLI stage is authoritative and does not match manifest stage.",
            manifest_label=manifest_label,
            cli_stage=cli_stage,
            manifest_stage=stage,
        )
    language = required_string(
        artifact.get("language"),
        audit,
        "artifact_language_missing",
        "Artifact requires language.",
        manifest_label=manifest_label,
    )
    if language and language not in ALLOWED_LANGUAGES:
        audit.add(
            "fail",
            "artifact_language_unknown",
            "Artifact language must be zh-CN or en.",
            manifest_label=manifest_label,
            language=language,
        )
    operation = required_string(
        artifact.get("operation"),
        audit,
        "artifact_operation_missing",
        "Artifact requires operation.",
        manifest_label=manifest_label,
    )
    if operation and operation not in ALLOWED_OPERATIONS:
        audit.add(
            "fail",
            "artifact_operation_unknown",
            "Artifact operation must be new_artifact or label_only_revision.",
            manifest_label=manifest_label,
            operation=operation,
        )

    artifact_path: Path | None = None
    artifact_sha256 = ""
    try:
        artifact_path = resolve_input_path(artifact.get("path"), root)
    except ValueError as exc:
        audit.add(
            "audit_incomplete",
            "artifact_path_invalid",
            str(exc),
            manifest_label=manifest_label,
        )
    expected_artifact_sha = normalized_sha(artifact.get("sha256"))
    if not expected_artifact_sha:
        audit.add(
            "audit_incomplete",
            "artifact_hash_missing",
            "Artifact requires a valid SHA-256.",
            manifest_label=manifest_label,
        )
    if artifact_path is not None:
        if not artifact_path.is_file():
            audit.add(
                "audit_incomplete",
                "artifact_missing",
                "Declared artifact file is missing.",
                manifest_label=manifest_label,
                path=str(artifact_path),
            )
        else:
            try:
                artifact_sha256 = sha256_file(artifact_path)
            except OSError as exc:
                audit.add(
                    "audit_incomplete",
                    "artifact_unreadable",
                    f"Cannot read declared artifact: {exc}",
                    manifest_label=manifest_label,
                    path=str(artifact_path),
                )
            else:
                if expected_artifact_sha and artifact_sha256 != expected_artifact_sha:
                    audit.add(
                        "fail",
                        "artifact_hash_stale",
                        "Artifact changed after the label manifest was created.",
                        manifest_label=manifest_label,
                        expected_sha256=expected_artifact_sha,
                        actual_sha256=artifact_sha256,
                    )

    numeric_payload_hashes, declared_numeric_payload_paths = validate_numeric_integrity(
        payload, root, audit, manifest_label
    )

    note_status = payload.get("note_status")
    if note_status not in {"provided", "not_applicable"}:
        audit.add(
            "audit_incomplete",
            "note_status_invalid",
            "note_status must be provided or not_applicable.",
            manifest_label=manifest_label,
        )
    notes: dict[str, str] = {}
    raw_notes = payload.get("notes")
    if not isinstance(raw_notes, list):
        audit.add(
            "audit_incomplete",
            "notes_invalid",
            "notes must be a list.",
            manifest_label=manifest_label,
        )
        raw_notes = []
    for record in raw_notes:
        if not isinstance(record, dict):
            audit.add(
                "audit_incomplete",
                "note_record_invalid",
                "Each note must be an object.",
                manifest_label=manifest_label,
            )
            continue
        note_id = required_string(
            record.get("note_id"),
            audit,
            "note_id_missing",
            "Each note requires note_id.",
            manifest_label=manifest_label,
        )
        text = required_string(
            record.get("text"),
            audit,
            "note_text_missing",
            "Each note requires text.",
            manifest_label=manifest_label,
            element_id=note_id or None,
        )
        if note_id in notes:
            audit.add(
                "fail",
                "note_id_duplicate",
                "note_id must be unique.",
                manifest_label=manifest_label,
                element_id=note_id,
            )
        elif note_id:
            notes[note_id] = text
        style_exception = record.get("style_exception")
        has_journal_exception = False
        if style_exception is not None:
            if not isinstance(style_exception, dict):
                audit.add(
                    "audit_incomplete",
                    "note_style_exception_invalid",
                    "Note style_exception must be an object.",
                    manifest_label=manifest_label,
                    element_id=note_id or None,
                )
            else:
                has_journal_exception = (
                    style_exception.get("type") == "journal_style"
                    and isinstance(style_exception.get("reason"), str)
                    and bool(style_exception["reason"].strip())
                    and isinstance(style_exception.get("source_locator"), str)
                    and bool(style_exception["source_locator"].strip())
                )
                if not has_journal_exception:
                    audit.add(
                        "fail",
                        "note_style_exception_incomplete",
                        "A journal note-style exception requires type, reason, and source_locator.",
                        manifest_label=manifest_label,
                        element_id=note_id or None,
                    )
        if text and language == "zh-CN" and not text.startswith("注："):
            if not has_journal_exception:
                audit.add(
                    "fail",
                    "chinese_note_prefix_invalid",
                    "Chinese notes must start with 注： unless a journal rule is recorded.",
                    manifest_label=manifest_label,
                    element_id=note_id or None,
                )
        if text and language == "en" and not text.startswith("Notes:"):
            if not has_journal_exception:
                audit.add(
                    "fail",
                    "english_note_prefix_invalid",
                    "English notes must start with Notes: unless a journal rule is recorded.",
                    manifest_label=manifest_label,
                    element_id=note_id or None,
                )
    if note_status == "provided" and not notes:
        audit.add(
            "audit_incomplete",
            "notes_required",
            "note_status=provided requires at least one note.",
            manifest_label=manifest_label,
        )
    if note_status == "not_applicable":
        required_string(
            payload.get("note_not_applicable_reason"),
            audit,
            "note_not_applicable_reason_missing",
            "A note-free artifact requires a substantive reason.",
            manifest_label=manifest_label,
        )
        if notes:
            audit.add(
                "fail",
                "note_status_conflict",
                "note_status=not_applicable conflicts with declared notes.",
                manifest_label=manifest_label,
            )

    contexts: dict[str, dict[str, str]] = {}
    raw_contexts = payload.get("contexts")
    if not isinstance(raw_contexts, list):
        audit.add(
            "audit_incomplete",
            "contexts_invalid",
            "contexts must be a list.",
            manifest_label=manifest_label,
        )
        raw_contexts = []
    for record in raw_contexts:
        if not isinstance(record, dict):
            audit.add(
                "audit_incomplete",
                "context_record_invalid",
                "Each context record must be an object.",
                manifest_label=manifest_label,
            )
            continue
        context_id = required_string(
            record.get("context_id"),
            audit,
            "context_id_missing",
            "Each context requires context_id.",
            manifest_label=manifest_label,
        )
        source_locator = required_string(
            record.get("source_locator"),
            audit,
            "context_locator_missing",
            "Each context requires a bounded source_locator.",
            manifest_label=manifest_label,
            element_id=context_id or None,
        )
        text = required_string(
            record.get("text"),
            audit,
            "context_text_missing",
            "Each context requires text.",
            manifest_label=manifest_label,
            element_id=context_id or None,
        )
        if context_id in contexts:
            audit.add(
                "fail",
                "context_id_duplicate",
                "context_id must be unique.",
                manifest_label=manifest_label,
                element_id=context_id,
            )
        elif context_id:
            contexts[context_id] = {
                "source_locator": source_locator,
                "text": text,
            }

    raw_labels = payload.get("labels")
    if not isinstance(raw_labels, list) or not raw_labels:
        audit.add(
            "audit_incomplete",
            "labels_missing",
            "Manifest requires a non-empty labels list.",
            manifest_label=manifest_label,
        )
        raw_labels = []

    labels: dict[str, dict[str, Any]] = {}
    preliminary_signatures: dict[str, dict[str, Any]] = {}
    preliminary_rows: list[tuple[dict[str, Any], str, str, str, dict[str, Any]]] = []
    for record in raw_labels:
        if not isinstance(record, dict):
            audit.add(
                "audit_incomplete",
                "label_record_invalid",
                "Each label must be an object.",
                manifest_label=manifest_label,
            )
            continue
        slot_id = required_string(
            record.get("slot_id"),
            audit,
            "slot_id_missing",
            "Each label requires slot_id.",
            manifest_label=manifest_label,
        )
        role = required_string(
            record.get("role"),
            audit,
            "label_role_missing",
            "Each label requires role.",
            manifest_label=manifest_label,
            element_id=slot_id or None,
        )
        if role and role not in ALLOWED_ROLES:
            audit.add(
                "fail",
                "label_role_unknown",
                "Label role is not in the closed set.",
                manifest_label=manifest_label,
                element_id=slot_id or None,
                role=role,
            )
        internal_key = required_string(
            record.get("internal_key"),
            audit,
            "internal_key_missing",
            "Each label requires internal_key or the literal not_applicable.",
            manifest_label=manifest_label,
            element_id=slot_id or None,
        )
        concept_id = required_string(
            record.get("concept_id"),
            audit,
            "concept_id_missing",
            "Each label requires concept_id.",
            manifest_label=manifest_label,
            element_id=slot_id or None,
        )
        display_text = required_string(
            record.get("display_text"),
            audit,
            "display_text_missing",
            "Each label requires public display_text.",
            manifest_label=manifest_label,
            element_id=slot_id or None,
        )
        meaning_status = required_string(
            record.get("meaning_status"),
            audit,
            "meaning_status_missing",
            "Each label requires meaning_status.",
            manifest_label=manifest_label,
            element_id=slot_id or None,
        )
        if meaning_status not in {"confirmed", "unresolved"}:
            audit.add(
                "fail",
                "meaning_status_unknown",
                "meaning_status must be confirmed or unresolved.",
                manifest_label=manifest_label,
                element_id=slot_id or None,
                meaning_status=meaning_status,
            )
        if meaning_status == "unresolved":
            audit.add(
                "clarification_required",
                "label_meaning_unresolved",
                "Public label meaning is unresolved; obtain author clarification.",
                manifest_label=manifest_label,
                element_id=slot_id or None,
            )
        full_definition = record.get("full_definition")
        if meaning_status == "confirmed":
            required_string(
                full_definition,
                audit,
                "full_definition_missing",
                "A confirmed label requires a full public definition.",
                manifest_label=manifest_label,
                element_id=slot_id or None,
            )
        elif full_definition is not None and not isinstance(full_definition, str):
            audit.add(
                "audit_incomplete",
                "full_definition_invalid",
                "full_definition must be text when present.",
                manifest_label=manifest_label,
                element_id=slot_id or None,
            )
        signature = validate_signature(
            record.get("semantic_signature"),
            audit,
            manifest_label=manifest_label,
            element_id=slot_id or "",
            meaning_status=meaning_status,
        )
        if slot_id in labels:
            audit.add(
                "fail",
                "slot_id_duplicate",
                "slot_id must be unique.",
                manifest_label=manifest_label,
                element_id=slot_id,
            )
        elif slot_id:
            labels[slot_id] = record
        if concept_id and signature:
            previous = preliminary_signatures.get(concept_id)
            if previous is not None and canonical_hash(previous) != canonical_hash(
                signature
            ):
                audit.add(
                    "fail",
                    "concept_signature_conflict",
                    "The same concept_id has conflicting semantic signatures.",
                    manifest_label=manifest_label,
                    element_id=slot_id or None,
                    concept_id=concept_id,
                )
            preliminary_signatures.setdefault(concept_id, signature)
        preliminary_rows.append(
            (record, slot_id, role, display_text, signature)
        )

    id_sets = {
        "label": set(labels),
        "note": set(notes),
        "context": set(contexts),
    }
    for left, right in (("label", "note"), ("label", "context"), ("note", "context")):
        for duplicate_id in sorted(id_sets[left] & id_sets[right]):
            audit.add(
                "fail",
                "element_id_cross_type_duplicate",
                "Label, note, and context IDs must be globally unique within a manifest.",
                manifest_label=manifest_label,
                element_id=duplicate_id,
                element_types=[left, right],
            )

    semantic_contract_sha256 = canonical_hash(
        {key: preliminary_signatures[key] for key in sorted(preliminary_signatures)}
    )
    warning_context_sha256 = canonical_hash(
        {
            "language": language,
            "semantic_contract_sha256": semantic_contract_sha256,
            "labels": [
                {
                    "slot_id": slot_id,
                    "role": role,
                    "display_text": display_text,
                    "concept_id": record.get("concept_id"),
                    "full_definition": record.get("full_definition"),
                    "definition_locations": record.get("definition_locations"),
                    "exceptions": record.get("exceptions", []),
                }
                for record, slot_id, role, display_text, _ in preliminary_rows
            ],
            "notes": notes,
            "contexts": contexts,
        }
    )
    valid_location_ids = {"self", *notes.keys(), *contexts.keys()}
    internal_mappings: dict[str, tuple[str, str]] = {}
    display_concepts: dict[str, set[str]] = {}
    display_slots: dict[str, list[tuple[str, str]]] = {}
    for record, slot_id, role, display_text, signature in preliminary_rows:
        if not slot_id:
            continue
        internal_key = str(record.get("internal_key", "")).strip()
        concept_id = str(record.get("concept_id", "")).strip()
        meaning_status = str(record.get("meaning_status", "")).strip()
        locations = string_list(
            record.get("definition_locations"),
            audit,
            "definition_locations_invalid",
            "Each label requires one or more definition-location IDs.",
            manifest_label=manifest_label,
            element_id=slot_id,
        )
        for location in locations:
            if location not in valid_location_ids:
                audit.add(
                    "fail",
                    "definition_location_dangling",
                    "definition_locations contains an unknown note or context ID.",
                    manifest_label=manifest_label,
                    element_id=slot_id,
                    location=location,
                )
        if meaning_status == "confirmed" and not locations:
            audit.add(
                "fail",
                "definition_location_missing",
                "A confirmed label requires a recoverable definition location.",
                manifest_label=manifest_label,
                element_id=slot_id,
            )
        exceptions = validate_exceptions(
            record.get("exceptions"),
            display_text,
            internal_key,
            audit,
            manifest_label=manifest_label,
            element_id=slot_id,
        )
        if has_invisible_control(display_text):
            audit.add(
                "fail",
                "display_control_character",
                "Display text contains invisible control or format characters.",
                manifest_label=manifest_label,
                element_id=slot_id,
            )
        scanned = code_scan_text(display_text)
        raw_code_hits: set[str] = set()
        camel_code_hits: set[str] = set()
        dotted_code_hits: set[str] = set()
        internal_key_hits: set[str] = set()
        proper_name_eligible_internal_hits: set[str] = set()
        raw_hit_spans: dict[str, set[tuple[int, int]]] = {}

        def record_raw_hit(hit: str, start: int, end: int) -> None:
            raw_code_hits.add(hit)
            raw_hit_spans.setdefault(hit, set()).add((start, end))

        for match in UNDERSCORE_IDENTIFIER_TOKEN_RE.finditer(scanned):
            record_raw_hit(match.group(0), *match.span())
        for match in HASH_COMPOSITE_TOKEN_RE.finditer(scanned):
            record_raw_hit(match.group(0), *match.span())
        for match in STATA_TOKEN_RE.finditer(scanned):
            token = match.group(0)
            start, end = match.span()
            if is_traditional_dotted_abbreviation(token):
                continue
            while token.endswith("."):
                token = token[:-1]
                end -= 1
            if token:
                record_raw_hit(token, start, end)
        for match in WORD_TOKEN_RE.finditer(scanned):
            token = match.group(0)
            if has_camel_case_transition(token):
                camel_code_hits.add(token)
                record_raw_hit(token, *match.span())
        for match in DOTTED_IDENTIFIER_TOKEN_RE.finditer(scanned):
            token = match.group(0)
            start, end = match.span()
            if is_traditional_dotted_abbreviation(token):
                continue
            if token.endswith("."):
                token = token[:-1]
                end -= 1
            dotted_code_hits.add(token)
            record_raw_hit(token, start, end)
        for hit in tuple(raw_code_hits):
            if is_traditional_dotted_abbreviation(hit):
                raw_code_hits.discard(hit)
                raw_hit_spans.pop(hit, None)
        if GENERIC_CODE_RE.fullmatch(scanned):
            record_raw_hit(scanned, 0, len(scanned))
        for match in GENERIC_CODE_TOKEN_RE.finditer(scanned):
            record_raw_hit(match.group(0), *match.span())
        high_hit_occurrences: set[tuple[str, int, int]] = {
            (hit, start, end)
            for hit, spans in raw_hit_spans.items()
            for start, end in spans
        }
        scanned_internal_key = code_scan_text(internal_key)
        visible_internal_spans = bounded_literal_spans(
            scanned, scanned_internal_key
        ) or bounded_casefold_literal_spans(scanned, scanned_internal_key)
        if (
            scanned_internal_key
            and scanned_internal_key != NOT_APPLICABLE
            and visible_internal_spans
            and high_confidence_internal_key(scanned_internal_key)
        ):
            for start, end in visible_internal_spans:
                visible_internal_key = scanned[start:end]
                internal_key_hits.add(visible_internal_key)
                high_hit_occurrences.add(
                    (visible_internal_key, start, end)
                )
                if proper_name_exception_is_structurally_eligible(
                    scanned_internal_key
                ):
                    proper_name_eligible_internal_hits.add(visible_internal_key)

        scanned_exception_types = exceptions.get(scanned, set())
        exception_spans = {
            token: set(bounded_literal_spans(scanned, token))
            for token in exceptions
        }
        replication_composite_spans = [
            (start, end)
            for token, exception_types in exceptions.items()
            if "replication_codebook" in exception_types
            and HASH_COMPOSITE_TOKEN_RE.fullmatch(token)
            for start, end in exception_spans.get(token, set())
        ]

        def exception_covers(hit: str, start: int, end: int) -> bool:
            normalized_hit = code_scan_text(hit)
            exception_types = exceptions.get(normalized_hit, set())
            if (start, end) not in exception_spans.get(normalized_hit, set()):
                exception_types = set()
            direct_coverage = False
            if hit in raw_code_hits:
                direct_coverage = "replication_codebook" in exception_types or (
                    "mathematical_symbol" in exception_types
                ) or (
                    hit in camel_code_hits
                    and hit not in dotted_code_hits
                    and "proper_name" in exception_types
                ) or (
                    "standard_abbreviation" in exception_types
                    and is_standard_abbreviation_token(hit)
                )
            elif hit in internal_key_hits:
                direct_coverage = (
                    "replication_codebook" in exception_types
                    or (
                        "mathematical_symbol" in exception_types
                    )
                    or (
                        "standard_abbreviation" in exception_types
                        and is_standard_abbreviation_token(hit)
                    )
                    or (
                        "formal_classification_code" in exception_types
                        and FORMAL_CODE_TOKEN_RE.fullmatch(hit) is not None
                    )
                    or (
                        "proper_name" in exception_types
                        and hit in proper_name_eligible_internal_hits
                    )
                )
            else:
                direct_coverage = bool(exception_types)
            if direct_coverage:
                return True
            return any(
                composite_start <= start and end <= composite_end
                for composite_start, composite_end in replication_composite_spans
            )

        uncovered = sorted(
            {
                hit
                for hit, start, end in high_hit_occurrences
                if not exception_covers(hit, start, end)
            }
        )
        if uncovered:
            audit.add(
                "fail",
                "internal_identifier_exposed",
                "Display text exposes a high-confidence internal code identifier without an exact typed exception.",
                manifest_label=manifest_label,
                element_id=slot_id,
                tokens=uncovered,
            )

        warning_codes: list[tuple[str, str]] = []
        if has_camel_case_transition(scanned) and not scanned_exception_types:
            warning_codes.append(
                (
                    "possible_camel_case_identifier",
                    "Display text may contain a camelCase internal identifier.",
                )
            )
        if INTERNAL_ABBREVIATION_RE.search(scanned):
            warning_codes.append(
                (
                    "possible_internal_abbreviation",
                    "Display text may be a cosmetic rewrite of internal shorthand.",
                )
            )
        normalized_display = normalize_display(display_text)
        if language == "zh-CN" and HARD_OPAQUE_ZH_RE.search(normalized_display):
            audit.add(
                "clarification_required",
                "opaque_basic_identity",
                "Chinese display text is a forbidden opaque label; replace it only after confirming the intended object or comparison.",
                manifest_label=manifest_label,
                element_id=slot_id,
                visible_text=display_text,
            )
        elif language == "zh-CN" and POSSIBLE_OPAQUE_ZH_RE.search(
            normalized_display
        ):
            warning_codes.append(
                (
                    "possible_opaque_identity",
                    "Chinese display text may not identify the statistic or comparison without internal knowledge.",
                )
            )
        if language == "en" and HARD_OPAQUE_EN_RE.search(normalized_display):
            audit.add(
                "clarification_required",
                "opaque_basic_identity",
                "English display text is a forbidden opaque label; replace it only after confirming the intended object or comparison.",
                manifest_label=manifest_label,
                element_id=slot_id,
                visible_text=display_text,
            )
        elif language == "en" and POSSIBLE_OPAQUE_EN_RE.search(
            normalized_display
        ):
            warning_codes.append(
                (
                    "possible_opaque_identity",
                    "English display text may not identify the statistic or comparison.",
                )
            )
        if role not in {"title", "caption"} and (
            len(display_text) > 80 or len(CJK_RE.findall(display_text)) > 40
        ):
            warning_codes.append(
                (
                    "possible_label_overflow",
                    "Label length may cause wrapping, truncation, or excessive font reduction; inspect the rendering.",
                )
            )
        if language == "zh-CN" and not CJK_RE.search(display_text):
            visible_tokens = {
                token.upper() for token in re.findall(r"[A-Za-z0-9²]+", display_text)
            }
            if visible_tokens and not visible_tokens <= STANDARD_TOKENS:
                warning_codes.append(
                    (
                        "possible_chinese_language_mismatch",
                        "Chinese artifact contains a label with no Chinese text and no fully standard token set.",
                    )
                )
        if language == "en" and CJK_RE.search(display_text):
            warning_codes.append(
                (
                    "possible_english_language_mismatch",
                    "English artifact contains Chinese display text.",
                )
            )
        for code, message in warning_codes:
            add_warning(
                audit,
                manifest_label=manifest_label,
                code=code,
                message=message,
                element_id=slot_id,
                visible_text=display_text,
                review_context_sha256=warning_context_sha256,
            )

        if internal_key and internal_key != NOT_APPLICABLE:
            mapping = (concept_id, canonical_hash(signature))
            previous = internal_mappings.get(internal_key)
            if previous is not None and previous != mapping:
                audit.add(
                    "fail",
                    "internal_key_mapping_conflict",
                    "The same internal key maps to conflicting concepts or semantics.",
                    manifest_label=manifest_label,
                    element_id=slot_id,
                    internal_key=internal_key,
                )
            internal_mappings.setdefault(internal_key, mapping)
        normalized_display_key = normalize_display(display_text)
        display_concepts.setdefault(normalized_display_key, set()).add(concept_id)
        display_slots.setdefault(normalized_display_key, []).append(
            (slot_id, display_text)
        )
    for display_text, concept_ids in sorted(display_concepts.items()):
        if display_text and len(concept_ids) > 1:
            for slot_id, original_display_text in display_slots[display_text]:
                add_warning(
                    audit,
                    manifest_label=manifest_label,
                    code="possible_display_label_collision",
                    message=(
                        "The same short display label maps to multiple concepts; "
                        "the basic-identity reviewer must verify that titles, panels, "
                        "or spanning headers disambiguate every occurrence."
                    ),
                    element_id=slot_id,
                    visible_text=original_display_text,
                    review_context_sha256=warning_context_sha256,
                )
    if not any(
        str(record.get("role", "")) in {"title", "caption"}
        for record in labels.values()
    ):
        audit.add(
            "fail",
            "title_or_caption_missing",
            "Artifact requires at least one reader-facing title or caption.",
            manifest_label=manifest_label,
        )

    basic_elements = [
        {
            "slot_id": slot_id,
            "role": record.get("role"),
            "display_text": record.get("display_text"),
        }
        for slot_id, record in labels.items()
    ]
    full_packet = {
        "artifact_id": artifact_id,
        "language": language,
        "labels": [
            {
                "slot_id": slot_id,
                "role": record.get("role"),
                "display_text": record.get("display_text"),
                "concept_id": record.get("concept_id"),
                "full_definition": record.get("full_definition"),
                "definition_locations": record.get("definition_locations"),
                "semantic_signature": record.get("semantic_signature"),
                "exceptions": record.get("exceptions", []),
            }
            for slot_id, record in labels.items()
        ],
        "notes": [
            {"note_id": note_id, "text": text}
            for note_id, text in sorted(notes.items())
        ],
        "contexts": [
            {"context_id": context_id, **record}
            for context_id, record in sorted(contexts.items())
        ],
    }
    return ManifestState(
        label=manifest_label,
        path=path.resolve(),
        payload=payload,
        manifest_sha256=manifest_sha256,
        artifact_path=artifact_path,
        artifact_sha256=artifact_sha256,
        artifact_id=artifact_id,
        artifact_family_id=artifact_family_id,
        language=language,
        stage=stage,
        declared_numeric_payload_paths=declared_numeric_payload_paths,
        numeric_payload_hashes=numeric_payload_hashes,
        labels=labels,
        notes=notes,
        contexts=contexts,
        concept_signatures=preliminary_signatures,
        semantic_contract_sha256=semantic_contract_sha256,
        basic_packet={
            "artifact_id": artifact_id,
            "language": language,
            "elements": basic_elements,
        },
        full_packet=full_packet,
    )


def review_verdict(
    record: Any,
    key: str,
    required_ids: set[str],
    audit: GateAudit,
    manifest_label: str,
) -> None:
    if not isinstance(record, dict):
        audit.add(
            "audit_incomplete",
            f"{key}_review_missing",
            f"Review requires a {key} object.",
            manifest_label=manifest_label,
        )
        return
    status = record.get("status")
    if status != "pass":
        blocking = "clarification_required" if status == "clarification_required" else "fail"
        audit.add(
            blocking,
            f"{key}_review_not_pass",
            f"{key} review did not pass.",
            manifest_label=manifest_label,
            review_status=status,
        )
    reviewed = set(
        string_list(
            record.get("reviewed_element_ids"),
            audit,
            f"{key}_review_coverage_invalid",
            f"{key} review requires reviewed_element_ids.",
            manifest_label=manifest_label,
            allow_empty=not required_ids,
        )
    )
    if reviewed != required_ids:
        audit.add(
            "audit_incomplete",
            f"{key}_review_coverage_incomplete",
            f"{key} review must cover the exact current element set.",
            manifest_label=manifest_label,
            missing=sorted(required_ids - reviewed),
            unexpected=sorted(reviewed - required_ids),
        )
    required_string(
        record.get("summary"),
        audit,
        f"{key}_review_summary_missing",
        f"{key} review requires a substantive summary.",
        manifest_label=manifest_label,
    )


def valid_timezone_timestamp(value: str) -> bool:
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def validate_review(
    path: Path,
    root: Path,
    state: ManifestState,
    audit: GateAudit,
) -> None:
    label = state.label
    loaded = load_json(path, root, audit, f"{label}_review")
    if loaded is None:
        return
    payload, review_sha256 = loaded
    state.review_path = path.resolve()
    state.review_sha256 = review_sha256
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get(
        "schema_id"
    ) != REVIEW_SCHEMA_ID:
        audit.add(
            "audit_incomplete",
            "review_schema_invalid",
            "Review must use reader-facing-label-review/1.0.",
            manifest_label=label,
        )
    required_string(
        payload.get("review_id"),
        audit,
        "review_id_missing",
        "Review requires review_id.",
        manifest_label=label,
    )
    required_string(
        payload.get("review_revision"),
        audit,
        "review_revision_missing",
        "Review requires review_revision.",
        manifest_label=label,
    )
    reviewer = required_string(
        payload.get("reviewer"),
        audit,
        "reviewer_missing",
        "Review requires reviewer.",
        manifest_label=label,
    )
    reviewed_at = required_string(
        payload.get("reviewed_at"),
        audit,
        "reviewed_at_missing",
        "Review requires a timezone-qualified reviewed_at timestamp.",
        manifest_label=label,
    )
    if reviewed_at and not valid_timezone_timestamp(reviewed_at):
        audit.add(
            "audit_incomplete",
            "reviewed_at_timezone_missing",
            "reviewed_at must include Z or an explicit UTC offset.",
            manifest_label=label,
        )
    review_mode = required_string(
        payload.get("review_mode"),
        audit,
        "review_mode_missing",
        "Review requires review_mode.",
        manifest_label=label,
    )
    if review_mode and review_mode not in ALLOWED_REVIEW_MODES:
        audit.add(
            "fail",
            "review_mode_unknown",
            "review_mode must be native_isolated_agent or bounded_same_agent.",
            manifest_label=label,
            review_mode=review_mode,
        )
    if normalized_sha(payload.get("manifest_sha256")) != state.manifest_sha256:
        audit.add(
            "fail",
            "review_manifest_hash_stale",
            "Review is not bound to the current manifest bytes.",
            manifest_label=label,
        )
    if normalized_sha(payload.get("artifact_sha256")) != state.artifact_sha256:
        audit.add(
            "fail",
            "review_artifact_hash_stale",
            "Review is not bound to the current artifact bytes.",
            manifest_label=label,
        )
    if payload.get("stage") != state.stage:
        audit.add(
            "fail",
            "review_stage_mismatch",
            "Review stage does not match the current manifest and CLI stage.",
            manifest_label=label,
        )
    if payload.get("language") != state.language:
        audit.add(
            "fail",
            "review_language_mismatch",
            "Review language does not match the artifact language.",
            manifest_label=label,
        )

    label_ids = set(state.labels)
    full_recovery_ids = label_ids | set(state.notes) | set(state.contexts)
    all_visible_ids = label_ids | set(state.notes)
    review_verdict(
        payload.get("basic_identity"),
        "basic_identity",
        label_ids,
        audit,
        label,
    )
    review_verdict(
        payload.get("full_recoverability"),
        "full_recoverability",
        full_recovery_ids,
        audit,
        label,
    )
    review_verdict(
        payload.get("language_style"),
        "language_style",
        all_visible_ids,
        audit,
        label,
    )

    numeric_review = payload.get("numeric_integrity")
    manifest_numeric = state.payload.get("numeric_integrity")
    if not isinstance(numeric_review, dict):
        audit.add(
            "audit_incomplete",
            "numeric_integrity_review_missing",
            "Review requires a numeric_integrity attestation tied to the verified payload files.",
            manifest_label=label,
        )
    else:
        if numeric_review.get("status") != "pass":
            audit.add(
                "fail",
                "numeric_integrity_review_not_pass",
                "Numeric-integrity review did not pass.",
                manifest_label=label,
                review_status=numeric_review.get("status"),
            )
        expected_canonicalization = (
            manifest_numeric.get("canonicalization_id")
            if isinstance(manifest_numeric, dict)
            else None
        )
        if numeric_review.get("canonicalization_id") != expected_canonicalization:
            audit.add(
                "fail",
                "numeric_integrity_review_canonicalization_mismatch",
                "Numeric-integrity review cites a different canonicalization procedure.",
                manifest_label=label,
            )
        expected_source = (
            manifest_numeric.get("producer_source_locator")
            if isinstance(manifest_numeric, dict)
            else None
        )
        if numeric_review.get("producer_source_locator") != expected_source:
            audit.add(
                "fail",
                "numeric_integrity_review_source_mismatch",
                "Numeric-integrity review cites a different producer source locator.",
                manifest_label=label,
            )
        required_string(
            numeric_review.get("summary"),
            audit,
            "numeric_integrity_review_summary_missing",
            "Numeric-integrity review requires a substantive summary of how the payload corresponds to the artifact.",
            manifest_label=label,
        )
        raw_verified = numeric_review.get("verified_payloads")
        verified: dict[Path, str] = {}
        if not isinstance(raw_verified, list):
            audit.add(
                "audit_incomplete",
                "numeric_integrity_review_payloads_invalid",
                "numeric_integrity review requires verified_payloads.",
                manifest_label=label,
            )
            raw_verified = []
        for record in raw_verified:
            if not isinstance(record, dict):
                audit.add(
                    "audit_incomplete",
                    "numeric_integrity_review_payload_invalid",
                    "Each verified numeric payload must be an object.",
                    manifest_label=label,
                )
                continue
            try:
                verified_path = resolve_input_path(record.get("path"), root)
            except ValueError as exc:
                audit.add(
                    "audit_incomplete",
                    "numeric_integrity_review_payload_path_invalid",
                    str(exc),
                    manifest_label=label,
                )
                continue
            verified_hash = normalized_sha(record.get("sha256"))
            if not verified_hash:
                audit.add(
                    "audit_incomplete",
                    "numeric_integrity_review_payload_hash_invalid",
                    "Each verified numeric payload requires a valid SHA-256.",
                    manifest_label=label,
                    path=str(verified_path),
                )
                continue
            if verified_path in verified:
                audit.add(
                    "fail",
                    "numeric_integrity_review_payload_duplicate",
                    "Verified numeric payload paths must be unique.",
                    manifest_label=label,
                    path=str(verified_path),
                )
            verified[verified_path] = verified_hash
        if verified != state.numeric_payload_hashes:
            audit.add(
                "audit_incomplete",
                "numeric_integrity_review_payload_coverage_incomplete",
                "Numeric-integrity review must cover the exact verified payload path and hash mapping.",
                manifest_label=label,
                missing=sorted(
                    str(path)
                    for path in set(state.numeric_payload_hashes) - set(verified)
                ),
                unexpected=sorted(
                    str(path)
                    for path in set(verified) - set(state.numeric_payload_hashes)
                ),
            )

    render = payload.get("render")
    if not isinstance(render, dict):
        audit.add(
            "audit_incomplete",
            "render_review_missing",
            "Review requires a hash-bound render object.",
            manifest_label=label,
        )
    else:
        if render.get("status") != "pass":
            audit.add(
                "fail",
                "render_review_not_pass",
                "Final rendering review did not pass.",
                manifest_label=label,
                render_status=render.get("status"),
            )
        if normalized_sha(render.get("artifact_sha256")) != state.artifact_sha256:
            audit.add(
                "fail",
                "render_artifact_hash_stale",
                "Render review is not bound to the current artifact bytes.",
                manifest_label=label,
            )
        try:
            inspected_path = resolve_input_path(render.get("inspected_path"), root)
        except ValueError as exc:
            audit.add(
                "audit_incomplete",
                "render_path_invalid",
                str(exc),
                manifest_label=label,
            )
            inspected_path = None
        if (
            inspected_path is not None
            and state.artifact_path is not None
            and inspected_path != state.artifact_path
        ):
            audit.add(
                "fail",
                "render_path_mismatch",
                "Render review inspected a different artifact path.",
                manifest_label=label,
                inspected_path=str(inspected_path),
                artifact_path=str(state.artifact_path),
            )
        checks = render.get("checks")
        if not isinstance(checks, dict):
            audit.add(
                "audit_incomplete",
                "render_checks_missing",
                "Render review requires closed visual checks.",
                manifest_label=label,
            )
        else:
            for check in sorted(RENDER_CHECKS):
                if checks.get(check) is not True:
                    audit.add(
                        "fail",
                        "render_check_failed",
                        "A required rendered-artifact check is missing or false.",
                        manifest_label=label,
                        check=check,
                        actual=checks.get(check),
                    )
        observed = render.get("observed_elements")
        observed_map: dict[str, str] = {}
        if not isinstance(observed, list):
            audit.add(
                "audit_incomplete",
                "render_observed_elements_missing",
                "Render review requires observed_elements.",
                manifest_label=label,
            )
            observed = []
        for record in observed:
            if not isinstance(record, dict):
                audit.add(
                    "audit_incomplete",
                    "render_observed_element_invalid",
                    "Each observed element must be an object.",
                    manifest_label=label,
                )
                continue
            element_id = record.get("element_id")
            digest = normalized_sha(record.get("text_sha256"))
            if not isinstance(element_id, str) or not element_id.strip() or not digest:
                audit.add(
                    "audit_incomplete",
                    "render_observed_element_invalid",
                    "Observed elements require element_id and text_sha256.",
                    manifest_label=label,
                )
                continue
            element_id = element_id.strip()
            if element_id in observed_map:
                audit.add(
                    "fail",
                    "render_observed_element_duplicate",
                    "Rendered element IDs must be unique.",
                    manifest_label=label,
                    element_id=element_id,
                )
            observed_map[element_id] = digest
        expected_text = {
            slot_id: sha256_text(
                normalize_display(str(record.get("display_text", "")))
            )
            for slot_id, record in state.labels.items()
        }
        expected_text.update(
            {
                note_id: sha256_text(normalize_display(text))
                for note_id, text in state.notes.items()
            }
        )
        if set(observed_map) != set(expected_text):
            audit.add(
                "audit_incomplete",
                "render_element_coverage_incomplete",
                "Render attestation must cover the exact label and note element set.",
                manifest_label=label,
                missing=sorted(set(expected_text) - set(observed_map)),
                unexpected=sorted(set(observed_map) - set(expected_text)),
            )
        for element_id in sorted(set(observed_map) & set(expected_text)):
            if observed_map[element_id] != expected_text[element_id]:
                audit.add(
                    "fail",
                    "render_visible_text_mismatch",
                    "Rendered visible-text hash differs from the current manifest.",
                    manifest_label=label,
                    element_id=element_id,
                )

    warnings = audit.warnings(label)
    required_warning_ids = {item["finding_id"] for item in warnings}
    raw_dispositions = payload.get("warning_dispositions")
    if not isinstance(raw_dispositions, list):
        audit.add(
            "audit_incomplete",
            "warning_dispositions_invalid",
            "warning_dispositions must be a list.",
            manifest_label=label,
        )
        raw_dispositions = []
    disposition_ids: set[str] = set()
    for record in raw_dispositions:
        if not isinstance(record, dict):
            audit.add(
                "audit_incomplete",
                "warning_disposition_invalid",
                "Each warning disposition must be an object.",
                manifest_label=label,
            )
            continue
        finding_id = record.get("finding_id")
        if not isinstance(finding_id, str) or not SHA256_RE.fullmatch(finding_id):
            audit.add(
                "audit_incomplete",
                "warning_disposition_id_invalid",
                "Warning disposition requires the exact 64-character finding_id.",
                manifest_label=label,
            )
            continue
        if finding_id in disposition_ids:
            audit.add(
                "fail",
                "warning_disposition_duplicate",
                "A warning finding has more than one disposition.",
                manifest_label=label,
                finding_id=finding_id,
            )
        disposition_ids.add(finding_id)
        if record.get("disposition") not in {"accepted", "false_positive"}:
            audit.add(
                "fail",
                "warning_disposition_unknown",
                "Warning disposition must be accepted or false_positive; revise and rerun instead of marking fixed.",
                manifest_label=label,
                finding_id=finding_id,
            )
        required_string(
            record.get("rationale"),
            audit,
            "warning_disposition_rationale_missing",
            "Warning disposition requires a substantive rationale.",
            manifest_label=label,
        )
        if record.get("reviewer") != reviewer:
            audit.add(
                "fail",
                "warning_disposition_reviewer_mismatch",
                "Warning disposition reviewer must match the current review.",
                manifest_label=label,
                finding_id=finding_id,
            )
        if record.get("reviewed_at") != reviewed_at:
            audit.add(
                "fail",
                "warning_disposition_time_mismatch",
                "Warning disposition timestamp must match the current review.",
                manifest_label=label,
                finding_id=finding_id,
            )
    missing = sorted(required_warning_ids - disposition_ids)
    unexpected = sorted(disposition_ids - required_warning_ids)
    if missing:
        audit.add(
            "fail" if unexpected else "audit_incomplete",
            "warning_unresolved",
            "Every deterministic warning requires a current-fingerprint disposition; stale substitutions fail rather than closing the warning.",
            manifest_label=label,
            finding_ids=missing,
        )
    if unexpected:
        audit.add(
            "fail",
            "warning_disposition_stale",
            "Warning dispositions refer to stale or nonexistent findings.",
            manifest_label=label,
            finding_ids=unexpected,
        )


def validate_pair(
    primary: ManifestState,
    paired: ManifestState,
    audit: GateAudit,
) -> None:
    if primary.artifact_family_id != paired.artifact_family_id:
        audit.add(
            "fail",
            "paired_artifact_family_mismatch",
            "Paired manifests must share artifact_family_id.",
        )
    if primary.language == paired.language:
        audit.add(
            "fail",
            "paired_language_mismatch",
            "Paired manifests must be separate Chinese and English versions.",
            languages=[primary.language, paired.language],
        )
    if {primary.language, paired.language} != ALLOWED_LANGUAGES:
        audit.add(
            "fail",
            "paired_language_set_invalid",
            "Paired audit requires one zh-CN and one en manifest.",
            languages=sorted({primary.language, paired.language}),
        )
    if primary.stage != paired.stage:
        audit.add(
            "fail",
            "paired_stage_mismatch",
            "Paired manifests must be audited at the same stage.",
            stages=[primary.stage, paired.stage],
        )
    primary_ids = set(primary.concept_signatures)
    paired_ids = set(paired.concept_signatures)
    if primary_ids != paired_ids:
        audit.add(
            "fail",
            "paired_concept_set_mismatch",
            "Paired manifests must cover the same concept IDs.",
            missing_in_paired=sorted(primary_ids - paired_ids),
            extra_in_paired=sorted(paired_ids - primary_ids),
        )
    for concept_id in sorted(primary_ids & paired_ids):
        if canonical_hash(primary.concept_signatures[concept_id]) != canonical_hash(
            paired.concept_signatures[concept_id]
        ):
            audit.add(
                "fail",
                "paired_semantic_signature_mismatch",
                "Paired language versions disagree on a language-neutral semantic signature.",
                concept_id=concept_id,
            )


def report_payload(
    audit: GateAudit,
    states: Sequence[ManifestState],
    cli_stage: str,
) -> dict[str, Any]:
    status = audit.status()
    return {
        "schema_version": SCHEMA_VERSION,
        "schema_id": REPORT_SCHEMA_ID,
        "gate_type": GATE_TYPE,
        "stage": cli_stage,
        "status": status,
        "scope": "deterministic_reader_facing_label_gate_only",
        "whole_artifact_delivery_authorized": False,
        "summary": {
            "manifest_count": len(states),
            "finding_count": len(audit.findings),
            "blocking_finding_count": sum(
                item["status"] in STATUS_PRIORITY for item in audit.findings
            ),
            "warning_count": sum(
                item["status"] == "warning" for item in audit.findings
            ),
        },
        "inputs": [
            {
                "manifest_label": state.label,
                "manifest_path": str(state.path),
                "manifest_sha256": state.manifest_sha256,
                "review_path": (
                    str(state.review_path) if state.review_path is not None else None
                ),
                "review_sha256": state.review_sha256 or None,
                "artifact_id": state.artifact_id,
                "artifact_path": (
                    str(state.artifact_path) if state.artifact_path else None
                ),
                "artifact_sha256": state.artifact_sha256,
                "artifact_family_id": state.artifact_family_id,
                "language": state.language,
                "semantic_contract_sha256": state.semantic_contract_sha256,
                "numeric_payloads": [
                    {"path": str(path), "sha256": digest}
                    for path, digest in sorted(
                        state.numeric_payload_hashes.items(), key=lambda item: str(item[0])
                    )
                ],
            }
            for state in states
        ],
        "review_packets": [
            {
                "manifest_label": state.label,
                "basic_identity": state.basic_packet,
                "full_recoverability": state.full_packet,
            }
            for state in states
        ],
        "findings": audit.sorted_findings(),
    }


def expected_input_hashes(
    states: Sequence[ManifestState], audit: GateAudit
) -> dict[Path, str]:
    expected: dict[Path, str] = {}

    def add(path: Path | None, digest: str, role: str) -> None:
        if path is None or not digest:
            return
        previous = expected.get(path)
        if previous is not None and previous != digest:
            audit.add(
                "fail",
                "input_path_hash_conflict",
                "One input path is assigned conflicting validated hashes.",
                path=str(path),
                input_role=role,
            )
        expected[path] = digest

    for state in states:
        add(state.path, state.manifest_sha256, f"{state.label}_manifest")
        add(state.review_path, state.review_sha256, f"{state.label}_review")
        add(state.artifact_path, state.artifact_sha256, f"{state.label}_artifact")
        for path, digest in state.numeric_payload_hashes.items():
            add(path, digest, f"{state.label}_numeric_payload")
    return expected


def recheck_input_hashes(
    expected: dict[Path, str], audit: GateAudit
) -> None:
    for path, validated_hash in sorted(expected.items(), key=lambda item: str(item[0])):
        try:
            current_hash = sha256_file(path)
        except OSError as exc:
            audit.add(
                "audit_incomplete",
                "input_unreadable_during_freshness_check",
                f"A validated input became unreadable before report creation: {exc}",
                path=str(path),
            )
            continue
        if current_hash != validated_hash:
            audit.add(
                "audit_incomplete",
                "input_changed_during_audit",
                "A validated input changed before the audit report was created.",
                path=str(path),
                validated_sha256=validated_hash,
                current_sha256=current_hash,
            )


def atomic_write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file():
            raise UnsafeOutputError("output path exists and is not a regular file")
        try:
            previous = strict_json_load(path)
        except (
            OSError,
            RuntimeError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ) as exc:
            raise UnsafeOutputError(
                "refusing to overwrite an existing file that is not a valid prior label-audit report"
            ) from exc
        if previous.get("schema_id") != REPORT_SCHEMA_ID:
            raise UnsafeOutputError(
                "refusing to overwrite an existing file that is not a prior label-audit report"
            )

    temporary_path: Path | None = None
    try:
        descriptor, raw_temporary_path = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        temporary_path = Path(raw_temporary_path)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(
                report,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit reader-facing economics table and figure labels."
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--stage", required=True, choices=sorted(ALLOWED_STAGES))
    parser.add_argument("--paired-manifest", type=Path)
    parser.add_argument("--paired-review", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def run(argv: Sequence[str] | None = None) -> tuple[int, dict[str, Any]]:
    args = build_parser().parse_args(argv)
    audit = GateAudit()
    try:
        root = args.project_root.resolve()
    except (OSError, RuntimeError) as exc:
        audit.add(
            "audit_incomplete",
            "project_root_unresolvable",
            f"Cannot resolve project-root safely: {exc}",
            path=str(args.project_root),
        )
        report = report_payload(audit, [], args.stage)
        return EXIT_CODES["audit_incomplete"], report
    if not root.is_dir():
        audit.add(
            "audit_incomplete",
            "project_root_invalid",
            "project-root must be an existing directory.",
            path=str(root),
        )
        report = report_payload(audit, [], args.stage)
        return EXIT_CODES["audit_incomplete"], report
    if bool(args.paired_manifest) != bool(args.paired_review):
        audit.add(
            "audit_incomplete",
            "paired_inputs_incomplete",
            "paired-manifest and paired-review must be supplied together.",
        )

    def cli_path(raw: Path | None, label: str) -> Path | None:
        if raw is None:
            return None
        try:
            return resolve_input_path(str(raw), root)
        except ValueError as exc:
            audit.add(
                "audit_incomplete",
                "cli_path_invalid",
                str(exc),
                input_name=label,
            )
            return None

    manifest_path = cli_path(args.manifest, "manifest")
    review_path = cli_path(args.review, "review")
    paired_manifest_path = cli_path(args.paired_manifest, "paired_manifest")
    paired_review_path = cli_path(args.paired_review, "paired_review")
    output_path = cli_path(args.output, "output")

    states: list[ManifestState] = []
    primary = (
        validate_manifest(manifest_path, root, args.stage, audit, "primary")
        if manifest_path is not None
        else None
    )
    if primary is not None:
        states.append(primary)
        if review_path is not None:
            validate_review(review_path, root, primary, audit)
    paired: ManifestState | None = None
    if paired_manifest_path is not None:
        paired = validate_manifest(
            paired_manifest_path, root, args.stage, audit, "paired"
        )
        if paired is not None:
            states.append(paired)
            if paired_review_path is not None:
                validate_review(paired_review_path, root, paired, audit)
    if primary is not None and paired is not None:
        validate_pair(primary, paired, audit)

    protected_paths = {
        path
        for path in (
            manifest_path,
            review_path,
            paired_manifest_path,
            paired_review_path,
        )
        if path is not None
    }
    for state in states:
        if state.artifact_path is not None:
            protected_paths.add(state.artifact_path)
        protected_paths.update(state.declared_numeric_payload_paths)
    if output_path is not None and output_path in protected_paths:
        audit.add(
            "audit_incomplete",
            "output_path_collision",
            "Refusing to write the audit report over an input, artifact, or numeric payload file.",
            path=str(output_path),
        )

    recheck_input_hashes(expected_input_hashes(states, audit), audit)
    report = report_payload(audit, states, args.stage)
    if output_path is None or output_path in protected_paths:
        return EXIT_CODES[report["status"]], report
    try:
        atomic_write_report(output_path, report)
    except (OSError, ValueError) as exc:
        audit.add(
            "audit_incomplete",
            "output_existing_non_report"
            if isinstance(exc, UnsafeOutputError)
            else "output_write_failed",
            f"Cannot safely write audit report: {exc}",
            path=str(output_path),
        )
        report = report_payload(audit, states, args.stage)
        print(f"cannot write audit report: {exc}", file=sys.stderr)
        return EXIT_CODES[report["status"]], report
    return EXIT_CODES[report["status"]], report


def main(argv: Sequence[str] | None = None) -> int:
    exit_code, report = run(argv)
    print(
        json.dumps(
            {
                "schema_version": report.get("schema_version"),
                "schema_id": report.get("schema_id"),
                "status": report.get("status"),
                "stage": report.get("stage"),
                "summary": report.get("summary"),
                "whole_artifact_delivery_authorized": False,
            },
            ensure_ascii=False,
            sort_keys=True,
            allow_nan=False,
        )
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
