#!/usr/bin/env python3
"""Deterministically audit citation, bibliography, and literature-state closure.

This gate is deliberately independent from the four semantic-review roles and
their assignment registry.  It proves only machine-checkable properties:
manuscript citation extraction, library/registry/ledger consistency, coverage
counts, bibliography closure, and hash freshness.  It never decides whether a
source is important or whether it substantively supports a claim; those remain
tasks for the Literature Coverage and Citation Integrity Role.

The implementation uses only the Python standard library.  Supported
manuscripts are bounded recursive TeX, Pandoc Markdown, and structured plain
text.  Final mode additionally requires a visible bibliography and a fresh,
hash-bound bibliography build attestation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

try:
    import prepare_manuscript_qa as qa_preparer
except ImportError:  # pragma: no cover - converted to metric_unavailable below
    qa_preparer = None


SCHEMA_VERSION = "1.0"
SCHEMA_ID = "citation-integrity-audit/1.0"
GATE_TYPE = "citation_integrity"
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
SUPPORTED_MANUSCRIPT_SUFFIXES = {".tex": "tex", ".md": "md", ".markdown": "md", ".txt": "txt", ".text": "txt"}
ADMITTED_STATUSES = {"admitted"}
KNOWN_REGISTRY_STATUSES = {
    "candidate",
    "inspected",
    "admitted",
    "rejected",
    "superseded",
}
PASS_LEDGER_STATUSES = {
    "pass",
    "supported",
    "verified",
    "admitted",
    "complete",
    "current",
    "covered",
}
EVIDENCE_CONFLICT_STATUSES = {
    "evidence_conflict",
    "unsupported",
    "contradicted",
    "insufficient_evidence",
}
KNOWN_LEDGER_STATUSES = PASS_LEDGER_STATUSES | EVIDENCE_CONFLICT_STATUSES | {
    "fail",
    "uncertain",
    "approval_required",
    "not_applicable",
    "non_claim",
}
SOURCE_COUNT_PROVENANCE = {
    "author_requirement",
    "journal_rule",
    "comparable_paper_sample",
}
STANDARD_COVERAGE_FUNCTIONS = {
    "closest_contribution",
    "theory_mechanism",
    "data_measurement_institution",
    "method_identification_model",
    "contrary_evidence_alternative_explanation",
    "recent_frontier",
}
COVERAGE_FUNCTIONS = STANDARD_COVERAGE_FUNCTIONS | {"project_specific"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CITEKEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:+/#-]*$")
TEX_SINGLE_CITE_COMMANDS = {
    "cite",
    "citealp",
    "citealt",
    "citeauthor",
    "citep",
    "citepalias",
    "citet",
    "citetalias",
    "citeyear",
    "citeyearpar",
    "parencite",
    "textcite",
    "autocite",
    "footcite",
    "smartcite",
    "supercite",
}
TEX_MULTI_CITE_COMMANDS = {
    "cites",
    "parencites",
    "textcites",
    "autocites",
    "footcites",
    "smartcites",
    "supercites",
}
TEX_NONCITATION_CITE_COMMANDS = {
    "citestyle",
    "setcitestyle",
    "citereset",
    "defcitealias",
}


class MetricUnavailable(RuntimeError):
    """The requested citation universe cannot be parsed deterministically."""


@dataclass(frozen=True)
class CitationOccurrence:
    key: str
    kind: str
    offset: int


@dataclass(frozen=True)
class BibEntry:
    citekey: str
    entry_type: str
    fields: dict[str, str]
    source_path: str


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

    def sorted_findings(self) -> list[dict[str, Any]]:
        return sorted(
            self.findings,
            key=lambda item: (
                STATUS_PRIORITY.index(item["status"])
                if item["status"] in STATUS_PRIORITY
                else len(STATUS_PRIORITY),
                str(item.get("code", "")),
                json.dumps(item, ensure_ascii=False, sort_keys=True),
            ),
        )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_hash(value: Any) -> str:
    return sha256_bytes(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )


def normalized_sha(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    candidate = value.strip().lower()
    return candidate if SHA256_RE.fullmatch(candidate) else ""


def ensure_within_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise MetricUnavailable(f"path escapes project root: {path}") from exc


def read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise MetricUnavailable(f"file not found: {path}") from exc
    except UnicodeDecodeError as exc:
        raise MetricUnavailable(f"file is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise MetricUnavailable(f"cannot read {path}: {exc}") from exc


def load_json_object(
    path: Path, audit: GateAudit, label: str
) -> dict[str, Any] | None:
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
    audit: GateAudit,
    label: str,
) -> bool:
    if payload is None:
        return False
    valid = True
    schema_id = payload.get("schema_id")
    version = payload.get("schema_version")
    if schema_id != expected:
        audit.add(
            "audit_incomplete",
            "schema_id_invalid",
            f"{label} must use schema_id={expected}.",
            actual_schema_id=payload.get("schema_id"),
        )
        valid = False
    if version != SCHEMA_VERSION:
        audit.add(
            "audit_incomplete",
            "schema_version_invalid",
            f"{label} must use schema_version={SCHEMA_VERSION}.",
            actual_schema_version=payload.get("schema_version"),
        )
        valid = False
    return valid


def require_nonempty_field(
    payload: dict[str, Any] | None,
    field_name: str,
    audit: GateAudit,
    label: str,
) -> str:
    value = payload.get(field_name) if payload is not None else None
    if not isinstance(value, str) or not value.strip():
        audit.add(
            "audit_incomplete",
            "authority_identity_missing",
            f"{label} requires nonempty {field_name}.",
            field=field_name,
        )
        return ""
    return value.strip()


def validate_authority_metadata(
    library_manifest: dict[str, Any] | None,
    registry: dict[str, Any] | None,
    coverage: dict[str, Any] | None,
    audit: GateAudit,
) -> None:
    """Validate the minimum identities and frozen-contract approval chain."""

    library_id = require_nonempty_field(
        library_manifest, "library_id", audit, "Reference-library manifest"
    )
    library_revision = require_nonempty_field(
        library_manifest, "library_revision", audit, "Reference-library manifest"
    )
    require_nonempty_field(registry, "registry_id", audit, "Literature registry")
    require_nonempty_field(
        registry, "registry_revision", audit, "Literature registry"
    )
    registry_library_id = require_nonempty_field(
        registry, "library_id", audit, "Literature registry"
    )
    registry_library_revision = require_nonempty_field(
        registry, "library_revision", audit, "Literature registry"
    )
    if library_id and registry_library_id and library_id != registry_library_id:
        audit.add(
            "audit_incomplete",
            "registry_library_id_mismatch",
            "Literature registry library_id does not match the authoritative manifest.",
            manifest_library_id=library_id,
            registry_library_id=registry_library_id,
        )
    if (
        library_revision
        and registry_library_revision
        and library_revision != registry_library_revision
    ):
        audit.add(
            "audit_incomplete",
            "registry_library_revision_mismatch",
            "Literature registry library_revision does not match the authoritative manifest.",
            manifest_library_revision=library_revision,
            registry_library_revision=registry_library_revision,
        )

    require_nonempty_field(
        coverage, "contract_id", audit, "Literature coverage contract"
    )
    require_nonempty_field(
        coverage, "contract_revision", audit, "Literature coverage contract"
    )
    require_nonempty_field(
        coverage, "task_stage", audit, "Literature coverage contract"
    )
    require_nonempty_field(
        coverage, "stop_condition", audit, "Literature coverage contract"
    )
    search_scope = coverage.get("search_scope") if coverage is not None else None
    if not isinstance(search_scope, dict) or not search_scope:
        audit.add(
            "audit_incomplete",
            "coverage_search_scope_missing",
            "Literature coverage contract requires a nonempty search_scope object.",
        )
    else:
        required_scope_fields = (
            "databases_or_closed_corpus",
            "languages",
            "coverage_end_date",
            "source_types",
            "inclusion_criteria",
            "exclusion_criteria",
        )
        missing_scope_fields = []
        for field_name in required_scope_fields:
            value = search_scope.get(field_name)
            if isinstance(value, str):
                present = bool(value.strip())
            elif isinstance(value, (list, dict)):
                present = bool(value)
            else:
                present = False
            if not present:
                missing_scope_fields.append(field_name)
        if missing_scope_fields:
            audit.add(
                "audit_incomplete",
                "coverage_search_scope_fields_missing",
                "Coverage search_scope must record corpus, languages, date, source types, and inclusion/exclusion criteria.",
                missing_fields=missing_scope_fields,
            )
        raw_end_date = search_scope.get("coverage_end_date")
        try:
            parsed_end_date = datetime.strptime(raw_end_date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            parsed_end_date = None
        if parsed_end_date is None or parsed_end_date > datetime.now().date():
            audit.add(
                "audit_incomplete",
                "coverage_end_date_invalid",
                "coverage_end_date must be a non-future ISO-8601 date.",
                coverage_end_date=raw_end_date,
            )
    unresolved_gaps = coverage.get("unresolved_gaps") if coverage is not None else None
    if not isinstance(unresolved_gaps, list):
        audit.add(
            "audit_incomplete",
            "coverage_unresolved_gaps_registry_missing",
            "Literature coverage contract requires an explicit unresolved_gaps array, which may be empty.",
        )
    approval = coverage.get("approval_record") if coverage is not None else None
    if not isinstance(approval, dict):
        audit.add(
            "audit_incomplete",
            "coverage_approval_missing",
            "Literature coverage contract requires a recoverable approval_record.",
        )
    else:
        if not isinstance(approval.get("confirmed_by"), str) or not approval[
            "confirmed_by"
        ].strip():
            audit.add(
                "audit_incomplete",
                "coverage_approval_actor_missing",
                "Coverage approval_record requires confirmed_by.",
            )
        if not valid_iso8601_timestamp(approval.get("confirmed_at")):
            audit.add(
                "audit_incomplete",
                "coverage_approval_time_invalid",
                "Coverage approval_record requires a timezone-aware confirmed_at timestamp.",
            )


def list_value(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_key_list(value: Any) -> list[str]:
    values: list[str] = []
    for item in list_value(value):
        if isinstance(item, str):
            values.extend(
                part.strip() for part in item.split(",") if part.strip()
            )
    return values


def resolve_declared_path(raw: Any, anchor: Path, root: Path) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = anchor / path
    path = path.resolve()
    ensure_within_root(path, root)
    return path


def blank_preserve_newlines(value: str) -> str:
    return "".join(character if character in "\r\n" else " " for character in value)


def load_manuscript(
    path: Path, project_root: Path
) -> tuple[str, str, list[dict[str, str]]]:
    path = path.resolve()
    project_root = project_root.resolve()
    ensure_within_root(path, project_root)
    fmt = SUPPORTED_MANUSCRIPT_SUFFIXES.get(path.suffix.lower())
    if fmt is None:
        raise MetricUnavailable(
            f"manuscript must be TeX, Pandoc Markdown, or structured text: {path}"
        )
    if qa_preparer is None:
        raise MetricUnavailable("prepare_manuscript_qa.py could not be imported")
    try:
        if fmt == "tex":
            document = qa_preparer.expand_tex(path, project_root)
        else:
            document = qa_preparer.single_file_document(
                path, strip_html_comments=(fmt == "md")
            )
    except (
        qa_preparer.PreparationError,
        OSError,
        UnicodeDecodeError,
        RecursionError,
    ) as exc:
        raise MetricUnavailable(str(exc)) from exc
    records = [
        {"path": str(source), "sha256": document.source_hashes[source]}
        for source in sorted(document.source_hashes, key=lambda item: str(item))
    ]
    return document.text, fmt, records


def parse_balanced(
    text: str, position: int, opening: str, closing: str
) -> tuple[str, int]:
    if position >= len(text) or text[position] != opening:
        raise MetricUnavailable(
            f"expected {opening!r} at citation offset {position}"
        )
    depth = 1
    cursor = position + 1
    start = cursor
    while cursor < len(text):
        character = text[cursor]
        escaped = cursor > 0 and text[cursor - 1] == "\\"
        if not escaped and character == opening:
            depth += 1
        elif not escaped and character == closing:
            depth -= 1
            if depth == 0:
                return text[start:cursor], cursor + 1
        cursor += 1
    raise MetricUnavailable(f"unbalanced {opening}{closing} citation argument")


def skip_space(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def skip_optional_arguments(text: str, position: int) -> int:
    cursor = skip_space(text, position)
    while cursor < len(text) and text[cursor] == "[":
        _, cursor = parse_balanced(text, cursor, "[", "]")
        cursor = skip_space(text, cursor)
    return cursor


def validated_citekeys(raw: str, command: str) -> list[str]:
    keys = [item.strip() for item in raw.split(",") if item.strip()]
    if not keys:
        raise MetricUnavailable(f"empty citekey list in \\{command}")
    for key in keys:
        if key == "*" and command == "nocite":
            continue
        if not CITEKEY_RE.fullmatch(key):
            raise MetricUnavailable(
                f"dynamic or malformed citekey {key!r} in \\{command}"
            )
    return keys


def blank_tex_verbatim(text: str) -> str:
    """Blank common verbatim/code regions and inline ``\\verb`` commands."""

    characters = list(text)
    begin_pattern = re.compile(
        r"(?<!\\)\\begin\s*\{(verbatim\*?|Verbatim|lstlisting|minted)\}"
    )
    position = 0
    while True:
        match = begin_pattern.search(text, position)
        if match is None:
            break
        environment = match.group(1)
        end_pattern = re.compile(
            rf"(?<!\\)\\end\s*\{{{re.escape(environment)}\}}"
        )
        end = end_pattern.search(text, match.end())
        if end is None:
            raise MetricUnavailable(f"unclosed TeX {environment} environment")
        for index in range(match.start(), end.end()):
            if characters[index] not in "\r\n":
                characters[index] = " "
        position = end.end()

    verb_pattern = re.compile(r"(?<!\\)\\(?:verb|lstinline)\*?")
    position = 0
    while True:
        match = verb_pattern.search(text, position)
        if match is None:
            break
        delimiter_position = match.end()
        if delimiter_position >= len(text):
            raise MetricUnavailable("malformed TeX inline-verbatim command")
        delimiter = text[delimiter_position]
        if delimiter.isspace() or delimiter.isalnum():
            raise MetricUnavailable("invalid TeX inline-verbatim delimiter")
        end = text.find(delimiter, delimiter_position + 1)
        if end < 0:
            raise MetricUnavailable("unclosed TeX inline-verbatim command")
        for index in range(match.start(), end + 1):
            if characters[index] not in "\r\n":
                characters[index] = " "
        position = end + 1
    return "".join(characters)


def scan_tex_citations(text: str) -> list[CitationOccurrence]:
    text = blank_tex_verbatim(text)
    occurrences: list[CitationOccurrence] = []
    pattern = re.compile(r"(?<!\\)\\([A-Za-z@]+)\*?")
    supported = TEX_SINGLE_CITE_COMMANDS | TEX_MULTI_CITE_COMMANDS | {"nocite"}
    for match in pattern.finditer(text):
        name = match.group(1).lower()
        if (
            "cite" in name
            and name not in supported
            and name not in TEX_NONCITATION_CITE_COMMANDS
        ):
            raise MetricUnavailable(
                f"unsupported or custom citation command \\{match.group(1)}; "
                "expand it to a supported natbib/biblatex command before auditing"
            )
        if name not in supported:
            continue
        cursor = skip_optional_arguments(text, match.end())
        if cursor >= len(text) or text[cursor] != "{":
            raise MetricUnavailable(f"missing citekey argument in \\{name}")
        groups: list[tuple[str, int]] = []
        raw, cursor = parse_balanced(text, cursor, "{", "}")
        groups.append((raw, match.start()))
        if name in TEX_MULTI_CITE_COMMANDS:
            while True:
                candidate = skip_optional_arguments(text, cursor)
                if candidate >= len(text) or text[candidate] != "{":
                    break
                raw, cursor = parse_balanced(text, candidate, "{", "}")
                groups.append((raw, candidate))
        kind = "nocite" if name == "nocite" else "body"
        for raw_group, offset in groups:
            for key in validated_citekeys(raw_group, name):
                occurrences.append(CitationOccurrence(key, kind, offset))
    return occurrences


def blank_markdown_code(text: str) -> str:
    """Blank fenced and inline code while preserving offsets."""

    characters = list(text)
    in_fence = False
    fence_character = ""
    fence_length = 0
    offset = 0
    for line in text.splitlines(keepends=True):
        match = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if not in_fence and match:
            in_fence = True
            fence_character = match.group(1)[0]
            fence_length = len(match.group(1))
            closing_line = False
        elif in_fence:
            closing_line = bool(
                re.match(
                    rf"^ {{0,3}}{re.escape(fence_character)}{{{fence_length},}}\s*$",
                    line.rstrip("\r\n"),
                )
            )
        else:
            closing_line = False
        if in_fence:
            for index in range(offset, offset + len(line)):
                if characters[index] not in "\r\n":
                    characters[index] = " "
            if closing_line:
                in_fence = False
        offset += len(line)
    cleaned = "".join(characters)
    return re.sub(
        r"(`+)(?!`)(.*?)(?<!`)\1(?!`)",
        lambda match: blank_preserve_newlines(match.group(0)),
        cleaned,
        flags=re.DOTALL,
    )


def markdown_front_matter(text: str) -> tuple[str, list[str]]:
    if not re.match(r"^---\s*(?:\r?\n)", text):
        return text, []
    closing = re.search(r"(?m)^---\s*$", text[text.find("\n") + 1 :])
    if closing is None:
        return text, []
    first_line_end = text.find("\n") + 1
    end = first_line_end + closing.end()
    block = text[:end]
    nocite_keys: list[str] = []
    lines = block.splitlines()
    collecting = False
    for line in lines[1:]:
        field = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$", line)
        if field:
            collecting = field.group(1).lower() == "nocite"
            value = field.group(2)
        elif collecting and (line.startswith(" ") or line.startswith("\t")):
            value = line
        else:
            collecting = False
            continue
        if collecting:
            for match in re.finditer(
                r"(?<![A-Za-z0-9_.+\-])@([A-Za-z0-9][A-Za-z0-9_.:+/#-]*|\*)",
                value,
            ):
                nocite_keys.append(match.group(1).rstrip(".,;:!?"))
    return blank_preserve_newlines(block) + text[end:], nocite_keys


STRUCTURED_MARKER_RE = re.compile(
    r"\[(CITATION|NOCITE|BIBITEM):([^\]]+)\]", re.IGNORECASE
)


def structured_marker_occurrences(text: str) -> list[CitationOccurrence]:
    occurrences: list[CitationOccurrence] = []
    for match in STRUCTURED_MARKER_RE.finditer(text):
        marker = match.group(1).lower()
        if marker == "bibitem":
            continue
        for key in validated_citekeys(
            match.group(2), "nocite" if marker == "nocite" else "cite"
        ):
            occurrences.append(
                CitationOccurrence(
                    key,
                    "nocite" if marker == "nocite" else "body",
                    match.start(),
                )
            )
    return occurrences


def scan_markdown_citations(text: str) -> list[CitationOccurrence]:
    prepared, yaml_nocites = markdown_front_matter(text)
    prepared = blank_markdown_code(prepared)
    occurrences = structured_marker_occurrences(prepared)
    prepared = STRUCTURED_MARKER_RE.sub(
        lambda match: blank_preserve_newlines(match.group(0)), prepared
    )
    for key in yaml_nocites:
        occurrences.append(CitationOccurrence(key, "nocite", 0))
    pattern = re.compile(
        r"(?<![A-Za-z0-9_.+\-])-?@([A-Za-z0-9][A-Za-z0-9_.:+/#-]*)"
    )
    for match in pattern.finditer(prepared):
        key = match.group(1).rstrip(".,;:!?")
        if not key:
            raise MetricUnavailable("malformed Pandoc citekey")
        occurrences.append(CitationOccurrence(key, "body", match.start()))
    return occurrences


def scan_txt_citations(text: str) -> list[CitationOccurrence]:
    markers = list(STRUCTURED_MARKER_RE.finditer(text))
    if not markers:
        raise MetricUnavailable(
            "plain text requires structured [CITATION:key], [NOCITE:key], or [BIBITEM:key] markers"
        )
    return structured_marker_occurrences(text)


def scan_citations(text: str, fmt: str) -> list[CitationOccurrence]:
    if fmt == "tex":
        return scan_tex_citations(text) + structured_marker_occurrences(text)
    if fmt == "md":
        return scan_markdown_citations(text)
    return scan_txt_citations(text)


def top_level_split(text: str, delimiter: str) -> list[str]:
    output: list[str] = []
    start = 0
    braces = 0
    parentheses = 0
    in_quote = False
    escaped = False
    for index, character in enumerate(text):
        if escaped:
            escaped = False
            continue
        if character == "\\":
            escaped = True
            continue
        if character == '"':
            in_quote = not in_quote
            continue
        if in_quote:
            continue
        if character == "{":
            braces += 1
        elif character == "}":
            braces -= 1
        elif character == "(":
            parentheses += 1
        elif character == ")":
            parentheses -= 1
        elif character == delimiter and braces == 0 and parentheses == 0:
            output.append(text[start:index])
            start = index + 1
        if braces < 0 or parentheses < 0:
            raise MetricUnavailable("malformed BibTeX nesting")
    if in_quote or braces or parentheses:
        raise MetricUnavailable("unbalanced BibTeX field")
    output.append(text[start:])
    return output


def split_assignment(text: str) -> tuple[str, str]:
    pieces = top_level_split(text, "=")
    if len(pieces) != 2:
        raise MetricUnavailable(f"malformed BibTeX assignment: {text[:80]!r}")
    return pieces[0].strip(), pieces[1].strip()


def unwrap_bib_value(value: str, strings: dict[str, str]) -> str:
    pieces = top_level_split(value, "#")
    rendered: list[str] = []
    for piece in pieces:
        token = piece.strip()
        if len(token) >= 2 and token[0] == "{" and token[-1] == "}":
            rendered.append(token[1:-1])
        elif len(token) >= 2 and token[0] == '"' and token[-1] == '"':
            rendered.append(token[1:-1])
        else:
            rendered.append(strings.get(token.casefold(), token))
    return "".join(rendered).strip()


def scan_bib_blocks(text: str) -> list[tuple[str, str]]:
    blocks: list[tuple[str, str]] = []
    cursor = 0
    header = re.compile(r"@([A-Za-z]+)\s*([({])")
    while True:
        match = header.search(text, cursor)
        if match is None:
            break
        opening = match.group(2)
        closing = "}" if opening == "{" else ")"
        stack = [closing]
        in_quote = False
        escaped = False
        index = match.end()
        body_start = index
        while index < len(text) and stack:
            character = text[index]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_quote = not in_quote
            elif not in_quote:
                if character == "{":
                    stack.append("}")
                elif character == "(":
                    stack.append(")")
                elif character in "})":
                    if not stack or character != stack[-1]:
                        raise MetricUnavailable("malformed BibTeX entry nesting")
                    stack.pop()
                    if not stack:
                        blocks.append(
                            (match.group(1).casefold(), text[body_start:index])
                        )
                        cursor = index + 1
                        break
            index += 1
        if stack:
            raise MetricUnavailable("unclosed BibTeX entry")
    return blocks


def strip_bibtex_percent_comments(text: str) -> str:
    """Blank percent comments without erasing percent-encoded field values."""

    characters = list(text)
    braces = 0
    parentheses = 0
    in_quote = False
    escaped = False
    index = 0
    while index < len(text):
        character = text[index]
        if character in "\r\n":
            escaped = False
            index += 1
            continue
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\":
            escaped = True
            index += 1
            continue
        if character == '"':
            in_quote = not in_quote
            index += 1
            continue
        if not in_quote:
            if character == "{":
                braces += 1
            elif character == "}":
                braces = max(0, braces - 1)
            elif character == "(":
                parentheses += 1
            elif character == ")":
                parentheses = max(0, parentheses - 1)
            elif character == "%" and braces <= 1 and parentheses <= 1:
                while index < len(text) and text[index] not in "\r\n":
                    characters[index] = " "
                    index += 1
                continue
        index += 1
    return "".join(characters)


def parse_bibtex(path: Path) -> list[BibEntry]:
    text = strip_bibtex_percent_comments(read_utf8(path))
    blocks = scan_bib_blocks(text)
    strings: dict[str, str] = {}
    pending: list[tuple[str, str]] = []
    for entry_type, body in blocks:
        if entry_type == "string":
            name, value = split_assignment(body.strip().rstrip(","))
            strings[name.casefold()] = unwrap_bib_value(value, strings)
        elif entry_type not in {"comment", "preamble"}:
            pending.append((entry_type, body))
    entries: list[BibEntry] = []
    for entry_type, body in pending:
        pieces = top_level_split(body, ",")
        citekey = pieces[0].strip()
        if not CITEKEY_RE.fullmatch(citekey):
            raise MetricUnavailable(
                f"malformed BibTeX citekey {citekey!r} in {path}"
            )
        fields: dict[str, str] = {}
        for piece in pieces[1:]:
            if not piece.strip():
                continue
            name, value = split_assignment(piece)
            normalized_name = name.casefold()
            if normalized_name in fields:
                raise MetricUnavailable(
                    f"duplicate BibTeX field {name!r} in {citekey}"
                )
            fields[normalized_name] = unwrap_bib_value(value, strings)
        entries.append(BibEntry(citekey, entry_type, fields, str(path)))
    return entries


def normalize_doi(value: str) -> str:
    normalized = value.strip().casefold()
    normalized = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", normalized)
    return normalized.strip(" \t\r\n{}.,;")


def normalize_title(value: str) -> str:
    text = re.sub(r"\\[A-Za-z@]+\*?", "", value)
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"[^\w]+", "", text.casefold(), flags=re.UNICODE)


def manifest_library_records(
    payload: dict[str, Any], manifest_path: Path, project_root: Path, audit: GateAudit
) -> list[dict[str, Any]]:
    raw_records = payload.get("libraries")
    if raw_records is None:
        raw_records = payload.get(
            "sources", payload.get("bib_files", payload.get("files"))
        )
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in list_value(raw_records):
        record = {"path": raw} if isinstance(raw, str) else raw
        if not isinstance(record, dict):
            audit.add(
                "audit_incomplete",
                "library_record_invalid",
                "Reference-library records must be paths or objects.",
            )
            continue
        try:
            path = resolve_declared_path(
                record.get("path"), manifest_path.parent, project_root
            )
        except MetricUnavailable as exc:
            audit.add("audit_incomplete", "library_path_invalid", str(exc))
            continue
        if path is None or path.suffix.lower() != ".bib":
            audit.add(
                "audit_incomplete",
                "library_path_invalid",
                "Each reference-library file must be a declared .bib path.",
                path=str(path) if path else None,
            )
            continue
        if str(path) in seen:
            audit.add(
                "fail",
                "library_file_duplicate",
                "The same .bib file is declared more than once.",
                path=str(path),
            )
            continue
        seen.add(str(path))
        expected = normalized_sha(record.get("sha256"))
        if not expected:
            audit.add(
                "audit_incomplete",
                "library_hash_missing",
                "Each .bib file requires a SHA-256 in the library manifest.",
                path=str(path),
            )
        if not path.is_file():
            audit.add(
                "audit_incomplete",
                "library_file_missing",
                "Declared .bib file is missing.",
                path=str(path),
            )
            continue
        actual = sha256_file(path)
        if expected and actual != expected:
            audit.add(
                "audit_incomplete",
                "library_hash_stale",
                "A .bib file changed after the library manifest was frozen.",
                path=str(path),
                expected_sha256=expected,
                actual_sha256=actual,
            )
        records.append({"path": str(path), "sha256": actual})
    if not records:
        audit.add(
            "metric_unavailable",
            "reference_library_empty",
            "No readable .bib file is declared by the reference-library manifest.",
        )
    return sorted(records, key=lambda item: item["path"])


def validate_bibliographic_duplicates(
    entries: list[BibEntry], audit: GateAudit
) -> dict[str, BibEntry]:
    by_key: dict[str, list[BibEntry]] = defaultdict(list)
    by_doi: dict[str, list[str]] = defaultdict(list)
    by_title: dict[str, list[str]] = defaultdict(list)
    for entry in entries:
        by_key[entry.citekey].append(entry)
        doi = normalize_doi(entry.fields.get("doi", ""))
        if doi:
            by_doi[doi].append(entry.citekey)
        title = normalize_title(entry.fields.get("title", ""))
        if title:
            by_title[title].append(entry.citekey)
    for key, records in sorted(by_key.items()):
        if len(records) > 1:
            audit.add(
                "fail",
                "duplicate_citekey",
                "A citekey occurs more than once across the authoritative libraries.",
                citekey=key,
                source_paths=sorted(record.source_path for record in records),
            )
    for doi, keys in sorted(by_doi.items()):
        unique = sorted(set(keys))
        if len(unique) > 1:
            audit.add(
                "fail",
                "duplicate_doi",
                "Different citekeys share the same normalized DOI.",
                doi=doi,
                citekeys=unique,
            )
    for title, keys in sorted(by_title.items()):
        unique = sorted(set(keys))
        if len(unique) > 1:
            audit.add(
                "approval_required",
                "suspected_duplicate_title",
                "Different citekeys share the same deterministically normalized title; human resolution is required.",
                normalized_title=title,
                citekeys=unique,
            )
    return {key: records[0] for key, records in sorted(by_key.items())}


def registry_entries(
    payload: dict[str, Any], audit: GateAudit
) -> dict[str, dict[str, Any]]:
    raw_entries = payload.get("entries", payload.get("sources"))
    output: dict[str, dict[str, Any]] = {}
    for raw in list_value(raw_entries):
        if not isinstance(raw, dict):
            audit.add(
                "audit_incomplete",
                "registry_entry_invalid",
                "Literature-registry entries must be objects.",
            )
            continue
        key = raw.get("citekey", raw.get("key"))
        if not isinstance(key, str) or not CITEKEY_RE.fullmatch(key.strip()):
            audit.add(
                "audit_incomplete",
                "registry_citekey_invalid",
                "Each registry entry requires a valid citekey.",
                citekey=key,
            )
            continue
        key = key.strip()
        if key in output:
            audit.add(
                "fail",
                "registry_citekey_duplicate",
                "A citekey occurs more than once in the literature registry.",
                citekey=key,
            )
            continue
        status = str(raw.get("status", "")).strip().casefold()
        if status not in KNOWN_REGISTRY_STATUSES:
            audit.add(
                "fail",
                "registry_status_invalid",
                "Registry status must be candidate, inspected, admitted, rejected, or superseded.",
                citekey=key,
                actual_status=status,
            )
        output[key] = raw
    return dict(sorted(output.items()))


def verify_hash_binding(
    payload: dict[str, Any] | None,
    field_names: Iterable[str],
    expected: str,
    audit: GateAudit,
    code_prefix: str,
    label: str,
    required: bool = True,
) -> None:
    if payload is None:
        return
    present: list[tuple[str, str]] = []
    invalid_fields: list[str] = []
    for name in field_names:
        if payload.get(name) is None:
            continue
        digest = normalized_sha(payload.get(name))
        if digest:
            present.append((name, digest))
        else:
            invalid_fields.append(name)
    if invalid_fields:
        audit.add(
            "audit_incomplete",
            f"{code_prefix}_hash_invalid",
            f"{label} contains an invalid SHA-256 alias.",
            fields=sorted(invalid_fields),
        )
    if len({digest for _, digest in present}) > 1:
        audit.add(
            "audit_incomplete",
            f"{code_prefix}_hash_alias_conflict",
            f"{label} contains conflicting SHA-256 aliases.",
            bindings={name: digest for name, digest in sorted(present)},
        )
        return
    if not present:
        if required:
            audit.add(
                "audit_incomplete",
                f"{code_prefix}_hash_missing",
                f"{label} lacks a valid required SHA-256 binding.",
            )
        return
    actual = present[0][1]
    if actual != expected:
        audit.add(
            "audit_incomplete",
            f"{code_prefix}_hash_stale",
            f"{label} is stale for its bound input.",
            expected_sha256=expected,
            actual_sha256=actual,
        )


def validate_registry_library_closure(
    library: dict[str, BibEntry], registry: dict[str, dict[str, Any]], audit: GateAudit
) -> None:
    missing_registry = sorted(set(library) - set(registry))
    missing_library = sorted(set(registry) - set(library))
    if missing_registry:
        audit.add(
            "audit_incomplete",
            "library_entries_unregistered",
            "Every authoritative .bib entry must have a literature-registry state.",
            citekeys=missing_registry,
        )
    if missing_library:
        audit.add(
            "fail",
            "registry_entries_missing_from_library",
            "Registry citekeys must resolve in the authoritative reference library.",
            citekeys=missing_library,
        )


def coverage_roles(record: dict[str, Any]) -> set[str]:
    raw = record.get(
        "coverage_cluster_ids",
        record.get(
            "coverage_roles", record.get("coverage_clusters", record.get("roles"))
        ),
    )
    return {
        str(item).strip()
        for item in list_value(raw)
        if isinstance(item, str) and item.strip()
    }


def has_inspection_evidence(record: dict[str, Any]) -> bool:
    value = record.get("inspection_evidence")
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return False


def validate_coverage(
    contract: dict[str, Any], registry: dict[str, dict[str, Any]], audit: GateAudit
) -> dict[str, Any]:
    raw_clusters = contract.get(
        "coverage_clusters",
        contract.get("functional_clusters", contract.get("clusters")),
    )
    if not isinstance(raw_clusters, list) or not raw_clusters:
        audit.add(
            "audit_incomplete",
            "coverage_cluster_universe_missing",
            "Coverage contract must explicitly declare every standard functional cluster, marking inapplicable clusters with a rationale.",
        )
        raw_clusters = []
    cluster_counts: dict[str, int] = Counter()
    admitted_keys: set[str] = set()
    verified_keys: set[str] = set()
    for key, record in registry.items():
        registry_status = str(record.get("status", "")).strip().casefold()
        if registry_status not in ADMITTED_STATUSES:
            continue
        admitted_keys.add(key)
        if not has_inspection_evidence(record):
            continue
        verified_keys.add(key)
        for role in coverage_roles(record):
            cluster_counts[role] += 1

    requirements: list[dict[str, Any]] = []
    seen_cluster_ids: set[str] = set()
    declared_functions: set[str] = set()
    for raw in list_value(raw_clusters):
        if not isinstance(raw, dict):
            audit.add(
                "audit_incomplete",
                "coverage_cluster_invalid",
                "Coverage-cluster records must be objects.",
            )
            continue
        cluster_id = raw.get("cluster_id", raw.get("id", raw.get("name")))
        if not isinstance(cluster_id, str) or not cluster_id.strip():
            audit.add(
                "audit_incomplete",
                "coverage_cluster_id_missing",
                "Each coverage cluster requires a stable ID.",
            )
            continue
        cluster_id = cluster_id.strip()
        if cluster_id in seen_cluster_ids:
            audit.add(
                "fail",
                "coverage_cluster_duplicate",
                "A coverage cluster ID occurs more than once in the contract.",
                cluster_id=cluster_id,
            )
            continue
        seen_cluster_ids.add(cluster_id)
        function = raw.get("function")
        if not isinstance(function, str) or function.strip() not in COVERAGE_FUNCTIONS:
            audit.add(
                "audit_incomplete",
                "coverage_cluster_function_invalid",
                "Each coverage cluster requires a closed functional role.",
                cluster_id=cluster_id,
                function=function,
                allowed_functions=sorted(COVERAGE_FUNCTIONS),
            )
            function = ""
        else:
            function = function.strip()
            declared_functions.add(function)
        applicability = raw.get("applicability", raw.get("status", "required"))
        applicable = raw.get("applicable")
        if isinstance(applicable, bool):
            is_required = applicable
        else:
            is_required = str(applicability).strip().casefold() not in {
                "not_applicable",
                "inactive",
                "optional",
                "false",
                "0",
            }
        if not is_required and (
            not isinstance(raw.get("rationale"), str)
            or not raw["rationale"].strip()
        ):
            audit.add(
                "audit_incomplete",
                "coverage_inapplicable_rationale_missing",
                "An inapplicable functional cluster requires a nonempty rationale.",
                cluster_id=cluster_id,
                function=function or None,
            )
        raw_minimum = raw.get("minimum_verified_sources", raw.get("minimum_sources"))
        if raw_minimum is None:
            minimum = 1 if is_required else 0
        elif isinstance(raw_minimum, int) and not isinstance(raw_minimum, bool) and raw_minimum >= 0:
            minimum = raw_minimum
        else:
            audit.add(
                "audit_incomplete",
                "coverage_minimum_invalid",
                "Cluster minimum_verified_sources must be a nonnegative integer.",
                cluster_id=cluster_id,
            )
            minimum = 0
        count = int(cluster_counts.get(cluster_id, 0))
        declared_keys = set(parse_key_list(raw.get("admitted_citekeys")))
        if declared_keys:
            unknown_declared = sorted(declared_keys - set(registry))
            nonadmitted_declared = sorted(
                key
                for key in declared_keys
                if key in registry
                and str(registry[key].get("status", "")).strip().casefold()
                not in ADMITTED_STATUSES
            )
            role_mismatch = sorted(
                key
                for key in declared_keys
                if key in registry and cluster_id not in coverage_roles(registry[key])
            )
            if unknown_declared or nonadmitted_declared or role_mismatch:
                audit.add(
                    "fail",
                    "coverage_cluster_registry_mismatch",
                    "Contract cluster citekeys must resolve to admitted registry entries carrying the same cluster role.",
                    cluster_id=cluster_id,
                    unknown_citekeys=unknown_declared,
                    nonadmitted_citekeys=nonadmitted_declared,
                    role_mismatch_citekeys=role_mismatch,
                )
        known_gap = raw.get("known_gap")
        gap_disposition = str(raw.get("gap_disposition", "")).strip().casefold()
        if known_gap and gap_disposition not in {"resolved", "not_applicable"}:
            audit.add(
                "fail",
                "coverage_known_gap_unresolved",
                "A recorded applicable coverage gap lacks a resolved disposition.",
                cluster_id=cluster_id,
            )
        requirements.append(
            {
                "cluster_id": cluster_id,
                "function": function or None,
                "required": is_required,
                "minimum_verified_sources": minimum,
                "verified_sources": count,
                "status": "pass" if not is_required or count >= minimum else "fail",
            }
        )
        if is_required and count < minimum:
            audit.add(
                "fail",
                "coverage_cluster_gap",
                "An applicable literature coverage cluster is below its frozen minimum.",
                cluster_id=cluster_id,
                minimum_verified_sources=minimum,
                verified_sources=count,
            )

    missing_functions = sorted(STANDARD_COVERAGE_FUNCTIONS - declared_functions)
    if missing_functions:
        audit.add(
            "audit_incomplete",
            "coverage_cluster_function_declarations_missing",
            "Every standard literature function must be declared as applicable or inapplicable.",
            missing_functions=missing_functions,
        )

    source_count_policy = (
        contract.get("source_count_policy")
        if isinstance(contract.get("source_count_policy"), dict)
        else {}
    )
    top_minimum = contract.get("minimum_verified_sources")
    policy_minimum = source_count_policy.get("minimum_verified_sources")
    if top_minimum is not None and policy_minimum is not None and top_minimum != policy_minimum:
        audit.add(
            "audit_incomplete",
            "coverage_total_minimum_alias_conflict",
            "Top-level and source_count_policy minimum_verified_sources aliases conflict.",
        )
    raw_total_minimum = top_minimum if top_minimum is not None else policy_minimum
    basis_aliases = [
        value
        for value in (
            contract.get("minimum_verified_sources_basis"),
            contract.get("source_count_basis"),
            source_count_policy.get("provenance"),
        )
        if value is not None
    ]
    if len({str(value).strip().casefold() for value in basis_aliases}) > 1:
        audit.add(
            "audit_incomplete",
            "coverage_source_count_provenance_alias_conflict",
            "Source-count provenance aliases conflict.",
        )
    basis = basis_aliases[0] if basis_aliases else None
    normalized_basis = str(basis).strip().casefold() if isinstance(basis, str) else ""
    if raw_total_minimum is not None:
        if not isinstance(raw_total_minimum, int) or isinstance(raw_total_minimum, bool) or raw_total_minimum < 0:
            audit.add(
                "audit_incomplete",
                "coverage_total_minimum_invalid",
                "minimum_verified_sources must be a nonnegative integer.",
            )
        elif normalized_basis not in SOURCE_COUNT_PROVENANCE:
            audit.add(
                "audit_incomplete",
                "coverage_total_minimum_basis_invalid",
                "A project source minimum requires provenance=author_requirement, journal_rule, or comparable_paper_sample.",
                provenance=basis,
            )
        elif len(verified_keys) < raw_total_minimum:
            audit.add(
                "fail",
                "coverage_total_below_minimum",
                "The admitted verified source count is below the frozen project minimum.",
                minimum_verified_sources=raw_total_minimum,
                verified_sources=len(verified_keys),
            )

    top_target = contract.get("target_range")
    policy_target = source_count_policy.get("target_range")
    if top_target is not None and policy_target is not None and canonical_hash(top_target) != canonical_hash(policy_target):
        audit.add(
            "audit_incomplete",
            "coverage_target_range_alias_conflict",
            "Top-level and source_count_policy target_range aliases conflict.",
        )
    raw_target = top_target if top_target is not None else policy_target
    provenance_record = source_count_policy.get(
        "provenance_record", contract.get("source_count_provenance_record")
    )
    if isinstance(provenance_record, str):
        provenance_record_present = bool(provenance_record.strip())
    elif isinstance(provenance_record, (list, dict)):
        provenance_record_present = bool(provenance_record)
    else:
        provenance_record_present = False
    if (
        raw_total_minimum is not None or raw_target is not None
    ) and not provenance_record_present:
        audit.add(
            "audit_incomplete",
            "coverage_source_count_provenance_record_missing",
            "A configured source minimum or target range requires a recoverable provenance_record.",
        )
    parsed_target: tuple[int, int] | None = None
    if raw_target is not None:
        if isinstance(raw_target, list) and len(raw_target) == 2:
            lower, upper = raw_target
        elif isinstance(raw_target, dict):
            lower = raw_target.get("minimum", raw_target.get("min"))
            upper = raw_target.get("maximum", raw_target.get("max"))
        else:
            lower = upper = None
        valid_endpoint = lambda value: isinstance(value, int) and not isinstance(value, bool) and value >= 0
        if not valid_endpoint(lower) or not valid_endpoint(upper) or lower > upper:
            audit.add(
                "audit_incomplete",
                "coverage_target_range_invalid",
                "target_range must be [minimum, maximum] or an object with nonnegative integer minimum/maximum and minimum <= maximum.",
            )
        else:
            parsed_target = (lower, upper)
            if normalized_basis not in SOURCE_COUNT_PROVENANCE:
                audit.add(
                    "audit_incomplete",
                    "coverage_target_range_basis_invalid",
                    "A project target range requires provenance=author_requirement, journal_rule, or comparable_paper_sample.",
                    provenance=basis,
                )
            enforcement = str(
                contract.get(
                    "target_range_enforcement",
                    source_count_policy.get("enforcement", "advisory"),
                )
            ).strip().casefold()
            if enforcement not in {
                "advisory",
                "hard",
                "required",
                "approval_required",
            }:
                audit.add(
                    "audit_incomplete",
                    "coverage_target_range_enforcement_invalid",
                    "target_range enforcement must be advisory, hard, required, or approval_required.",
                    enforcement=enforcement,
                )
            verified_count = len(verified_keys)
            if verified_count < lower:
                audit.add(
                    "fail",
                    "coverage_target_below_minimum",
                    "The verified admitted source count is below the frozen target range.",
                    minimum=lower,
                    verified_sources=verified_count,
                )
            elif verified_count > upper:
                if enforcement in {"hard", "required", "approval_required"}:
                    audit.add(
                        "approval_required",
                        "coverage_target_above_hard_maximum",
                        "The verified admitted source count exceeds a hard author-configured maximum.",
                        maximum=upper,
                        verified_sources=verified_count,
                    )
                else:
                    audit.add(
                        "warning",
                        "coverage_target_above_advisory_maximum",
                        "The verified admitted source count exceeds an advisory target maximum; this does not fail coverage.",
                        maximum=upper,
                        verified_sources=verified_count,
                    )
    unresolved = []
    for raw in list_value(contract.get("unresolved_gaps")):
        if isinstance(raw, dict):
            disposition = str(raw.get("status", raw.get("disposition", ""))).strip().casefold()
            if disposition in {"resolved", "closed", "not_applicable"}:
                continue
        if raw:
            unresolved.append(raw)
    if unresolved:
        audit.add(
            "fail",
            "coverage_contract_unresolved_gaps",
            "The literature coverage contract still records unresolved applicable gaps.",
            gap_count=len(unresolved),
        )
    return {
        "admitted_sources": len(admitted_keys),
        "admitted_verified_sources": len(verified_keys),
        "verified_admitted_sources": len(verified_keys),
        "verified_sources": len(verified_keys),
        "cluster_counts": dict(sorted(cluster_counts.items())),
        "requirements": sorted(requirements, key=lambda item: item["cluster_id"]),
        "global_minimum_applied": raw_total_minimum is not None,
        "target_range": list(parsed_target) if parsed_target is not None else None,
    }


def authorized_nocite_keys(
    coverage: dict[str, Any], registry: dict[str, dict[str, Any]]
) -> set[str]:
    keys = set(parse_key_list(coverage.get("authorized_nocite_keys")))
    for raw in list_value(coverage.get("nocite_authorizations")):
        if not isinstance(raw, dict):
            continue
        status = str(raw.get("status", "")).strip().casefold()
        if status in {"approved", "authorized", "confirmed", "current"}:
            keys.update(parse_key_list(raw.get("citekeys", raw.get("citekey"))))
    return keys


def validate_nocite_authorizations(
    keys: set[str],
    library: dict[str, BibEntry],
    registry: dict[str, dict[str, Any]],
    audit: GateAudit,
) -> None:
    explicit = keys - {"*"}
    missing_library = sorted(explicit - set(library))
    missing_registry = sorted(explicit - set(registry))
    nonadmitted = sorted(
        key
        for key in explicit
        if key in registry
        and str(registry[key].get("status", "")).strip().casefold()
        != "admitted"
    )
    uninspected = sorted(
        key
        for key in explicit
        if key in registry
        and str(registry[key].get("status", "")).strip().casefold() == "admitted"
        and not has_inspection_evidence(registry[key])
    )
    if "*" in keys:
        uninspected = sorted(
            set(uninspected)
            | {
                key
                for key, record in registry.items()
                if str(record.get("status", "")).strip().casefold()
                == "admitted"
                and not has_inspection_evidence(record)
            }
        )
    if missing_library or missing_registry or nonadmitted or uninspected:
        audit.add(
            "fail",
            "nocite_authorization_invalid",
            "Each explicit nocite authorization must resolve to an inspected, admitted source in the authoritative library and registry.",
            missing_library_citekeys=missing_library,
            missing_registry_citekeys=missing_registry,
            nonadmitted_citekeys=nonadmitted,
            uninspected_citekeys=uninspected,
        )


def validate_qa_manifest(
    payload: dict[str, Any],
    path: Path,
    manuscript_path: Path,
    manuscript_text: str,
    source_files: list[dict[str, str]],
    body_keys: set[str],
    project_root: Path,
    audit: GateAudit,
) -> tuple[dict[str, set[str]], str]:
    require_schema(payload, "qa-manifest/1.0", audit, "QA manifest")
    qa_hash = sha256_file(path)
    expected_main = normalized_sha(payload.get("manuscript_sha256"))
    actual_main = sha256_file(manuscript_path)
    if not expected_main or expected_main != actual_main:
        audit.add(
            "audit_incomplete",
            "qa_manifest_manuscript_stale",
            "QA manifest does not bind the current manuscript bytes.",
            expected_sha256=expected_main or None,
            actual_sha256=actual_main,
        )
    expected_expanded = normalized_sha(
        payload.get("expanded_manuscript_sha256", payload.get("content_sha256"))
    )
    actual_expanded = sha256_text(manuscript_text)
    if not expected_expanded or expected_expanded != actual_expanded:
        audit.add(
            "audit_incomplete",
            "qa_manifest_content_stale",
            "QA manifest does not bind the current expanded manuscript.",
            expected_sha256=expected_expanded or None,
            actual_sha256=actual_expanded,
        )
    expected_sources: dict[str, str] = {}
    for raw in list_value(payload.get("source_files")):
        if not isinstance(raw, dict):
            continue
        try:
            source = resolve_declared_path(raw.get("path"), project_root, project_root)
        except MetricUnavailable:
            source = None
        digest = normalized_sha(raw.get("sha256"))
        if source is not None and digest:
            expected_sources[str(source)] = digest
    actual_sources = {record["path"]: record["sha256"] for record in source_files}
    if expected_sources != actual_sources:
        audit.add(
            "audit_incomplete",
            "qa_manifest_sources_stale",
            "QA manifest source-file hashes do not match the recursively expanded manuscript.",
            expected_source_files=[
                {"path": key, "sha256": value}
                for key, value in sorted(expected_sources.items())
            ],
            actual_source_files=source_files,
        )
    all_unit_citations: dict[str, set[str]] = {}
    unit_citations: dict[str, set[str]] = {}
    for raw in list_value(payload.get("units")):
        if not isinstance(raw, dict):
            continue
        unit_id = raw.get("unit_id")
        if not isinstance(unit_id, str) or not unit_id:
            continue
        citations = set(parse_key_list(raw.get("citation_keys")))
        all_unit_citations[unit_id] = citations
        unit_type = str(raw.get("type", raw.get("kind", ""))).strip().casefold()
        if not unit_type or unit_type in {"sentence", "section", "heading"}:
            unit_citations[unit_id] = citations
    manifest_keys = (
        set().union(*all_unit_citations.values()) if all_unit_citations else set()
    )
    if manifest_keys != body_keys:
        audit.add(
            "audit_incomplete",
            "qa_manifest_citation_projection_stale",
            "QA unit citation keys do not equal the current manuscript citation set.",
            manifest_citekeys=sorted(manifest_keys),
            manuscript_citekeys=sorted(body_keys),
        )
    return unit_citations, qa_hash


def evidence_entries(payload: dict[str, Any]) -> list[Any]:
    if isinstance(payload.get("entries"), list):
        return payload["entries"]
    if isinstance(payload.get("text_to_evidence"), list):
        return payload["text_to_evidence"]
    if isinstance(payload.get("text_to_evidence_ledger"), list):
        return payload["text_to_evidence_ledger"]
    ledgers = payload.get("ledgers")
    if isinstance(ledgers, dict) and isinstance(ledgers.get("text_to_evidence"), list):
        return ledgers["text_to_evidence"]
    return []


def validate_evidence_ledger(
    payload: dict[str, Any],
    unit_citations: dict[str, set[str]],
    body_keys: set[str],
    library: dict[str, BibEntry],
    registry: dict[str, dict[str, Any]],
    audit: GateAudit,
) -> dict[str, Any]:
    for field_name in ("ledger_id", "ledger_revision"):
        if not isinstance(payload.get(field_name), str) or not payload[
            field_name
        ].strip():
            audit.add(
                "audit_incomplete",
                "evidence_ledger_identity_missing",
                "text-to-evidence ledger requires stable ledger_id and ledger_revision fields.",
                field=field_name,
            )
    covered_keys: set[str] = set()
    mapped_keys: set[str] = set()
    mapped_pairs: set[tuple[str, str]] = set()
    passing_pairs: set[tuple[str, str]] = set()
    expected_pairs = {
        (unit_id, citekey)
        for unit_id, citekeys in unit_citations.items()
        for citekey in citekeys
    }
    valid_records = 0
    for raw in evidence_entries(payload):
        if not isinstance(raw, dict):
            audit.add(
                "audit_incomplete",
                "evidence_ledger_entry_invalid",
                "text_to_evidence entries must be objects.",
            )
            continue
        missing_fields: list[str] = []
        for field_name in (
            "claim_id",
            "claim_type",
            "support_role",
            "support_strength",
        ):
            value = raw.get(field_name)
            if not isinstance(value, str) or not value.strip():
                missing_fields.append(field_name)
        source_locator = raw.get("source_locator")
        if isinstance(source_locator, str):
            source_locator_present = bool(source_locator.strip())
        elif isinstance(source_locator, (list, dict)):
            source_locator_present = bool(source_locator)
        else:
            source_locator_present = False
        if not source_locator_present:
            missing_fields.append("source_locator")
        if missing_fields:
            audit.add(
                "audit_incomplete",
                "evidence_ledger_entry_fields_missing",
                "Each text-to-evidence entry requires claim identity, type, support role/strength, and a recoverable source locator.",
                missing_fields=missing_fields,
            )
            continue
        unit_id = raw.get("unit_id")
        if not isinstance(unit_id, str) or unit_id not in unit_citations:
            audit.add(
                "audit_incomplete",
                "evidence_ledger_unit_invalid",
                "Each citation-bearing ledger entry requires a current QA unit_id.",
                unit_id=unit_id,
            )
            continue
        status = str(raw.get("status", "")).strip().casefold()
        if status not in KNOWN_LEDGER_STATUSES:
            audit.add(
                "audit_incomplete",
                "evidence_ledger_status_invalid",
                "text_to_evidence status is outside the closed status enum.",
                unit_id=unit_id,
                actual_status=status,
            )
        if status in EVIDENCE_CONFLICT_STATUSES:
            audit.add(
                "evidence_conflict",
                "claim_source_evidence_conflict",
                "The text-to-evidence ledger records an unresolved source conflict.",
                unit_id=unit_id,
            )
        elif status == "fail":
            audit.add(
                "fail",
                "claim_source_ledger_failed",
                "The text-to-evidence ledger records a failed claim-source mapping.",
                unit_id=unit_id,
            )
        elif status == "uncertain":
            audit.add(
                "clarification_required",
                "claim_source_ledger_uncertain",
                "The text-to-evidence ledger records unresolved uncertainty.",
                unit_id=unit_id,
            )
        elif status == "approval_required":
            audit.add(
                "approval_required",
                "claim_source_ledger_approval_required",
                "The text-to-evidence ledger records an unresolved author approval.",
                unit_id=unit_id,
            )
        elif status in {"not_applicable", "non_claim"} and unit_citations[unit_id]:
            audit.add(
                "audit_incomplete",
                "citation_ledger_status_inapplicable",
                "A citation-bearing unit cannot close citation integrity as non_claim or not_applicable.",
                unit_id=unit_id,
                actual_status=status,
            )
        keys = set(
            parse_key_list(
                raw.get("citekeys", raw.get("citation_keys", raw.get("citekey")))
            )
        )
        if not keys and unit_citations[unit_id]:
            audit.add(
                "audit_incomplete",
                "evidence_ledger_citekey_missing",
                "A citation-bearing unit ledger entry must record its citekey(s).",
                unit_id=unit_id,
            )
            continue
        outside_unit = sorted(keys - unit_citations[unit_id])
        if outside_unit:
            audit.add(
                "fail",
                "evidence_ledger_unit_citation_mismatch",
                "Ledger citekeys are absent from the cited QA unit.",
                unit_id=unit_id,
                citekeys=outside_unit,
            )
        outside_body = sorted(keys - body_keys)
        if outside_body:
            audit.add(
                "fail",
                "evidence_ledger_manuscript_mismatch",
                "Ledger citekeys are absent from the manuscript body.",
                unit_id=unit_id,
                citekeys=outside_body,
            )
        missing_library = sorted(keys - set(library))
        if missing_library:
            audit.add(
                "fail",
                "evidence_ledger_citekey_missing_from_library",
                "Ledger citekeys do not resolve in the authoritative library.",
                unit_id=unit_id,
                citekeys=missing_library,
            )
        nonadmitted = sorted(
            key
            for key in keys
            if key in registry
            and str(registry[key].get("status", "")).strip().casefold()
            not in ADMITTED_STATUSES
        )
        if nonadmitted:
            audit.add(
                "fail",
                "evidence_ledger_source_not_admitted",
                "Ledger citekeys must have admitted registry status.",
                unit_id=unit_id,
                citekeys=nonadmitted,
            )
        uninspected = sorted(
            key
            for key in keys
            if key in registry
            and str(registry[key].get("status", "")).strip().casefold()
            == "admitted"
            and not has_inspection_evidence(registry[key])
        )
        if uninspected:
            audit.add(
                "fail",
                "evidence_ledger_source_uninspected",
                "Admitted ledger sources require nonempty inspection_evidence.",
                unit_id=unit_id,
                citekeys=uninspected,
            )
        if status in PASS_LEDGER_STATUSES and not outside_unit and not outside_body:
            covered_keys.update(keys)
            passing_pairs.update((unit_id, key) for key in keys)
            valid_records += 1
        if not outside_unit and not outside_body:
            mapped_keys.update(keys)
            mapped_pairs.update((unit_id, key) for key in keys)
    missing_pairs = sorted(expected_pairs - mapped_pairs)
    if missing_pairs:
        audit.add(
            "audit_incomplete",
            "unit_citekey_evidence_mapping_missing",
            "Every citation-bearing QA unit requires a ledger mapping for each citekey in that unit.",
            unit_citekey_pairs=[
                {"unit_id": unit_id, "citekey": citekey}
                for unit_id, citekey in missing_pairs
            ],
        )
    uncovered = sorted(body_keys - mapped_keys)
    if uncovered:
        audit.add(
            "audit_incomplete",
            "body_citations_missing_evidence_mapping",
            "Each body citekey requires at least one current passing text-to-evidence mapping.",
            citekeys=uncovered,
        )
    return {
        "valid_records": valid_records,
        "mapped_body_citekeys": sorted(mapped_keys),
        "covered_body_citekeys": sorted(covered_keys),
        "uncovered_body_citekeys": uncovered,
        "expected_unit_citekey_pairs": [
            {"unit_id": unit_id, "citekey": citekey}
            for unit_id, citekey in sorted(expected_pairs)
        ],
        "mapped_unit_citekey_pairs": [
            {"unit_id": unit_id, "citekey": citekey}
            for unit_id, citekey in sorted(mapped_pairs)
        ],
        "passing_unit_citekey_pairs": [
            {"unit_id": unit_id, "citekey": citekey}
            for unit_id, citekey in sorted(passing_pairs)
        ],
    }


def parse_visible_bibliography(path: Path) -> tuple[set[str], list[str]]:
    raw_keys: list[str] = []
    if path.suffix.lower() == ".json":
        payload = json.loads(read_utf8(path))
        if isinstance(payload, list):
            raw_entries = payload
        elif isinstance(payload, dict):
            raw_entries = payload.get("citekeys", payload.get("entries", []))
        else:
            raise MetricUnavailable("visible bibliography JSON must be an object or list")
        for raw in list_value(raw_entries):
            key = raw if isinstance(raw, str) else raw.get("citekey", raw.get("key")) if isinstance(raw, dict) else None
            if not isinstance(key, str) or not CITEKEY_RE.fullmatch(key.strip()):
                raise MetricUnavailable("visible bibliography JSON contains an invalid citekey")
            raw_keys.append(key.strip())
        duplicates = sorted(
            key for key, count in Counter(raw_keys).items() if count > 1
        )
        return set(raw_keys), duplicates
    text = read_utf8(path)
    if qa_preparer is not None and path.suffix.lower() in {".tex", ".bbl"}:
        text = qa_preparer.strip_tex_comments_preserve_offsets(text)
    raw_keys.extend(
        match.group(1).strip()
        for match in re.finditer(r"\\bibitem(?:\s*\[[^\]]*\])?\s*\{([^{}]+)\}", text)
    )
    raw_keys.extend(
        match.group(1).strip()
        for match in re.finditer(r"\\entry\s*\{([^{}]+)\}\s*\{", text)
    )
    for match in re.finditer(r"\[BIBITEM:([^\]]+)\]", text, re.IGNORECASE):
        raw_keys.extend(validated_citekeys(match.group(1), "bibitem"))
    keys = set(raw_keys)
    invalid = sorted(key for key in keys if not CITEKEY_RE.fullmatch(key))
    if invalid:
        raise MetricUnavailable(f"visible bibliography contains invalid citekeys: {invalid}")
    if not keys:
        raise MetricUnavailable(
            "visible bibliography requires \\bibitem, biblatex \\entry, structured [BIBITEM:key], or citekey JSON"
        )
    duplicates = sorted(key for key, count in Counter(raw_keys).items() if count > 1)
    return keys, duplicates


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


def validate_build_attestation(
    payload: dict[str, Any],
    manuscript_expanded_sha: str,
    library_manifest_sha: str,
    library_files: list[dict[str, str]],
    visible_bibliography_sha: str,
    qa_manifest_sha: str,
    audit: GateAudit,
) -> None:
    require_schema(
        payload,
        "bibliography-build-attestation/1.0",
        audit,
        "bibliography build attestation",
    )
    if str(payload.get("status", "")).strip().casefold() not in {
        "complete",
        "completed",
        "current",
    }:
        audit.add(
            "audit_incomplete",
            "build_attestation_status_invalid",
            "Bibliography build attestation must be complete/current.",
        )
    bindings = (
        ("expanded_manuscript_sha256", manuscript_expanded_sha),
        ("reference_library_manifest_sha256", library_manifest_sha),
        ("visible_bibliography_sha256", visible_bibliography_sha),
        ("qa_manifest_sha256", qa_manifest_sha),
    )
    for field_name, expected in bindings:
        actual = normalized_sha(payload.get(field_name))
        if not actual or actual != expected:
            audit.add(
                "audit_incomplete",
                "build_attestation_stale",
                "Bibliography build attestation does not bind the current build inputs.",
                field=field_name,
                expected_sha256=expected,
                actual_sha256=actual or None,
            )
    raw_files = payload.get("reference_library_files", payload.get("bib_files"))
    attested: list[dict[str, str]] = []
    for raw in list_value(raw_files):
        if not isinstance(raw, dict):
            continue
        path = raw.get("path")
        digest = normalized_sha(raw.get("sha256"))
        if isinstance(path, str) and digest:
            attested.append({"path": str(Path(path).expanduser().resolve()), "sha256": digest})
    if sorted(attested, key=lambda item: item["path"]) != library_files:
        audit.add(
            "audit_incomplete",
            "build_attestation_library_files_stale",
            "Bibliography build attestation does not bind every current .bib file.",
            expected_reference_library_files=library_files,
            actual_reference_library_files=sorted(attested, key=lambda item: item["path"]),
        )
    if not valid_iso8601_timestamp(payload.get("build_timestamp")):
        audit.add(
            "audit_incomplete",
            "build_timestamp_invalid",
            "Build attestation requires a timezone-aware ISO-8601 timestamp.",
        )
    if not isinstance(payload.get("build_tool"), str) or not payload["build_tool"].strip():
        audit.add(
            "audit_incomplete",
            "build_tool_missing",
            "Build attestation requires the generating tool or manual-build identity.",
        )


def validate_final_closure(
    visible: set[str],
    body: set[str],
    nocite: set[str],
    authorized_nocite: set[str],
    registry: dict[str, dict[str, Any]],
    library: dict[str, BibEntry],
    audit: GateAudit,
) -> dict[str, Any]:
    unauthorized = sorted(key for key in nocite if key not in authorized_nocite)
    if unauthorized:
        audit.add(
            "approval_required",
            "nocite_unauthorized",
            "Every nocite item, including '*', requires explicit frozen authorization.",
            citekeys=unauthorized,
        )
    # Authorization is a separate approval gate.  Include every actual nocite
    # in the closure expectation so an unauthorized-but-otherwise-valid item
    # remains approval_required rather than being spuriously upgraded to a
    # derived "unreferenced bibliography" failure.
    effective_nocite: set[str] = set()
    for key in nocite:
        if key == "*":
            effective_nocite.update(
                registry_key
                for registry_key, record in registry.items()
                if str(record.get("status", "")).strip().casefold()
                in ADMITTED_STATUSES
            )
            if key not in authorized_nocite:
                effective_nocite.update(visible)
        else:
            effective_nocite.add(key)
    expected = body | effective_nocite
    missing = sorted(expected - visible)
    extra = sorted(visible - expected)
    if missing:
        audit.add(
            "fail",
            "final_bibliography_missing_entries",
            "Body citations and authorized nocite entries must appear in the final bibliography.",
            citekeys=missing,
        )
    if extra:
        audit.add(
            "fail",
            "final_bibliography_unreferenced_entries",
            "Final visible bibliography contains uncited and unauthorized entries.",
            citekeys=extra,
        )
    unknown = sorted(visible - set(library))
    if unknown:
        audit.add(
            "fail",
            "final_bibliography_missing_from_library",
            "Final bibliography entries must resolve in the authoritative library.",
            citekeys=unknown,
        )
    nonadmitted = sorted(
        key
        for key in visible
        if key in registry
        and str(registry[key].get("status", "")).strip().casefold()
        not in ADMITTED_STATUSES
    )
    if nonadmitted:
        audit.add(
            "fail",
            "final_bibliography_source_not_admitted",
            "Final bibliography may contain only admitted sources.",
            citekeys=nonadmitted,
        )
    uninspected = sorted(
        key
        for key in visible
        if key in registry
        and str(registry[key].get("status", "")).strip().casefold()
        == "admitted"
        and not has_inspection_evidence(registry[key])
    )
    if uninspected:
        audit.add(
            "fail",
            "final_bibliography_source_uninspected",
            "Final bibliography admitted sources require nonempty inspection_evidence.",
            citekeys=uninspected,
        )
    return {
        "expected_visible_citekeys": sorted(expected),
        "actual_visible_citekeys": sorted(visible),
        "missing_citekeys": missing,
        "extra_citekeys": extra,
    }


def input_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path) if path.is_file() else None,
    }


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("--mode", choices=("draft", "final"), required=True)
    cli.add_argument("--manuscript", required=True)
    cli.add_argument("--project-root")
    cli.add_argument("--reference-library-manifest", required=True)
    cli.add_argument("--literature-registry", required=True)
    cli.add_argument("--coverage-contract", required=True)
    cli.add_argument("--text-to-evidence-ledger", required=True)
    cli.add_argument("--qa-manifest", required=True)
    cli.add_argument("--visible-bibliography")
    cli.add_argument("--bibliography-build-attestation")
    cli.add_argument("--report", required=True)
    return cli


def run(args: argparse.Namespace) -> dict[str, Any]:
    audit = GateAudit()
    manuscript_path = Path(args.manuscript).expanduser().resolve()
    project_root = (
        Path(args.project_root).expanduser().resolve()
        if args.project_root
        else manuscript_path.parent.resolve()
    )
    paths = {
        "reference_library_manifest": Path(args.reference_library_manifest).expanduser().resolve(),
        "literature_registry": Path(args.literature_registry).expanduser().resolve(),
        "coverage_contract": Path(args.coverage_contract).expanduser().resolve(),
        "text_to_evidence_ledger": Path(args.text_to_evidence_ledger).expanduser().resolve(),
        "qa_manifest": Path(args.qa_manifest).expanduser().resolve(),
    }
    visible_path = Path(args.visible_bibliography).expanduser().resolve() if args.visible_bibliography else None
    attestation_path = Path(args.bibliography_build_attestation).expanduser().resolve() if args.bibliography_build_attestation else None

    manuscript_text, fmt, source_files = load_manuscript(manuscript_path, project_root)
    occurrences = scan_citations(manuscript_text, fmt)
    body_keys = {item.key for item in occurrences if item.kind == "body"}
    nocite_keys = {item.key for item in occurrences if item.kind == "nocite"}
    expanded_sha = sha256_text(manuscript_text)

    library_manifest = load_json_object(paths["reference_library_manifest"], audit, "reference-library manifest")
    registry_payload = load_json_object(paths["literature_registry"], audit, "literature registry")
    coverage_payload = load_json_object(paths["coverage_contract"], audit, "literature coverage contract")
    evidence_payload = load_json_object(paths["text_to_evidence_ledger"], audit, "text-to-evidence ledger")
    qa_payload = load_json_object(paths["qa_manifest"], audit, "QA manifest")
    require_schema(library_manifest, "reference-library-manifest/1.0", audit, "reference-library manifest")
    require_schema(registry_payload, "literature-registry/1.0", audit, "literature registry")
    require_schema(coverage_payload, "literature-coverage-contract/1.0", audit, "literature coverage contract")
    require_schema(evidence_payload, "text-to-evidence-ledger/1.0", audit, "text-to-evidence ledger")
    validate_authority_metadata(
        library_manifest, registry_payload, coverage_payload, audit
    )

    library_manifest_sha = sha256_file(paths["reference_library_manifest"]) if paths["reference_library_manifest"].is_file() else ""
    registry_sha = sha256_file(paths["literature_registry"]) if paths["literature_registry"].is_file() else ""
    coverage_sha = sha256_file(paths["coverage_contract"]) if paths["coverage_contract"].is_file() else ""
    evidence_sha = sha256_file(paths["text_to_evidence_ledger"]) if paths["text_to_evidence_ledger"].is_file() else ""
    qa_sha = sha256_file(paths["qa_manifest"]) if paths["qa_manifest"].is_file() else ""
    library_files: list[dict[str, str]] = []
    all_bib_entries: list[BibEntry] = []
    if library_manifest is not None:
        library_files = manifest_library_records(
            library_manifest, paths["reference_library_manifest"], project_root, audit
        )
        for record in library_files:
            try:
                all_bib_entries.extend(parse_bibtex(Path(record["path"])))
            except MetricUnavailable as exc:
                audit.add(
                    "metric_unavailable",
                    "bibtex_parse_unavailable",
                    str(exc),
                    path=record["path"],
                )
    library = validate_bibliographic_duplicates(all_bib_entries, audit)
    registry = registry_entries(registry_payload or {}, audit)
    validate_registry_library_closure(library, registry, audit)

    verify_hash_binding(
        registry_payload,
        ("reference_library_manifest_sha256", "library_manifest_sha256"),
        library_manifest_sha,
        audit,
        "registry_library_manifest",
        "Literature registry",
    )
    verify_hash_binding(
        coverage_payload,
        ("reference_library_manifest_sha256", "library_manifest_sha256"),
        library_manifest_sha,
        audit,
        "coverage_library_manifest",
        "Literature coverage contract",
    )
    verify_hash_binding(
        coverage_payload,
        ("literature_registry_sha256", "registry_sha256"),
        registry_sha,
        audit,
        "coverage_registry",
        "Literature coverage contract",
    )

    coverage_metrics = validate_coverage(coverage_payload or {}, registry, audit)
    unit_citations: dict[str, set[str]] = {}
    if qa_payload is not None:
        unit_citations, qa_sha = validate_qa_manifest(
            qa_payload,
            paths["qa_manifest"],
            manuscript_path,
            manuscript_text,
            source_files,
            body_keys,
            project_root,
            audit,
        )

    if evidence_payload is not None:
        verify_hash_binding(
            evidence_payload,
            ("qa_manifest_sha256", "manifest_sha256"),
            qa_sha,
            audit,
            "evidence_qa_manifest",
            "Text-to-evidence ledger",
        )
        verify_hash_binding(
            evidence_payload,
            ("manuscript_sha256", "candidate_sha256"),
            sha256_file(manuscript_path),
            audit,
            "evidence_manuscript",
            "Text-to-evidence ledger",
        )
        verify_hash_binding(
            evidence_payload,
            ("expanded_manuscript_sha256", "content_sha256"),
            expanded_sha,
            audit,
            "evidence_content",
            "Text-to-evidence ledger",
        )
        verify_hash_binding(
            evidence_payload,
            ("literature_registry_sha256",),
            registry_sha,
            audit,
            "evidence_registry",
            "Text-to-evidence ledger",
        )
        evidence_metrics = validate_evidence_ledger(
            evidence_payload, unit_citations, body_keys, library, registry, audit
        )
    else:
        evidence_metrics = {
            "valid_records": 0,
            "covered_body_citekeys": [],
            "uncovered_body_citekeys": sorted(body_keys),
        }

    missing_body = sorted(body_keys - set(library))
    if missing_body:
        audit.add(
            "fail",
            "body_citekeys_missing_from_library",
            "Every manuscript citekey must resolve in the authoritative library.",
            citekeys=missing_body,
        )
    missing_registry = sorted(body_keys - set(registry))
    if missing_registry:
        audit.add(
            "audit_incomplete",
            "body_citekeys_missing_from_registry",
            "Every manuscript citekey must have a current literature-registry state.",
            citekeys=missing_registry,
        )
    body_not_admitted = sorted(
        key
        for key in body_keys
        if key in registry
        and str(registry[key].get("status", "")).strip().casefold()
        not in ADMITTED_STATUSES
    )
    if body_not_admitted:
        audit.add(
            "fail",
            "body_source_not_admitted",
            "Candidate, inspected-only, rejected, or superseded sources cannot appear in manuscript citations.",
            citekeys=body_not_admitted,
        )
    body_uninspected = sorted(
        key
        for key in body_keys
        if key in registry
        and str(registry[key].get("status", "")).strip().casefold()
        == "admitted"
        and not has_inspection_evidence(registry[key])
    )
    if body_uninspected:
        audit.add(
            "fail",
            "body_source_inspection_missing",
            "Every cited admitted source requires nonempty inspection_evidence.",
            citekeys=body_uninspected,
        )

    authorization = authorized_nocite_keys(coverage_payload or {}, registry)
    validate_nocite_authorizations(authorization, library, registry, audit)
    closure_metrics: dict[str, Any] = {
        "expected_visible_citekeys": [],
        "actual_visible_citekeys": [],
        "missing_citekeys": [],
        "extra_citekeys": [],
    }
    visible_keys: set[str] = set()
    if args.mode == "final":
        if visible_path is None:
            audit.add(
                "audit_incomplete",
                "visible_bibliography_missing",
                "Final mode requires --visible-bibliography.",
            )
        else:
            try:
                visible_keys, duplicate_visible_keys = parse_visible_bibliography(
                    visible_path
                )
                if duplicate_visible_keys:
                    audit.add(
                        "fail",
                        "final_bibliography_duplicate_entries",
                        "A citekey occurs more than once in the final visible bibliography.",
                        citekeys=duplicate_visible_keys,
                    )
                closure_metrics = validate_final_closure(
                    visible_keys,
                    body_keys,
                    nocite_keys,
                    authorization,
                    registry,
                    library,
                    audit,
                )
            except (MetricUnavailable, json.JSONDecodeError) as exc:
                audit.add(
                    "metric_unavailable",
                    "visible_bibliography_parse_unavailable",
                    str(exc),
                    path=str(visible_path),
                )
        if attestation_path is None:
            audit.add(
                "audit_incomplete",
                "bibliography_build_attestation_missing",
                "Final mode requires a hash-bound bibliography build attestation.",
            )
        else:
            attestation = load_json_object(
                attestation_path, audit, "bibliography build attestation"
            )
            if attestation is not None and visible_path is not None and visible_path.is_file():
                validate_build_attestation(
                    attestation,
                    expanded_sha,
                    library_manifest_sha,
                    library_files,
                    sha256_file(visible_path),
                    qa_sha,
                    audit,
                )
    else:
        unauthorized = sorted(key for key in nocite_keys if key not in authorization)
        if unauthorized:
            audit.add(
                "approval_required",
                "nocite_unauthorized",
                "Every nocite item, including '*', requires explicit frozen authorization.",
                citekeys=unauthorized,
            )

    input_paths = {
        "manuscript": manuscript_path,
        **paths,
        "visible_bibliography": visible_path,
        "bibliography_build_attestation": attestation_path,
    }
    status = audit.status()
    findings = audit.sorted_findings()
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "schema_id": SCHEMA_ID,
        "gate_type": GATE_TYPE,
        "scope": "citation_integrity_gate_only",
        "status": status,
        "gate_local_status": status,
        "whole_manuscript_delivery_authorized": False,
        "exit_code": EXIT_CODES[status],
        "mode": args.mode,
        "inputs": {
            key: input_record(value) if value is not None else None
            for key, value in sorted(input_paths.items())
        },
        "project_root": str(project_root),
        "manuscript": {
            "format": fmt,
            "expanded_sha256": expanded_sha,
            "source_files": source_files,
        },
        "reference_library_files": library_files,
        "citekey_sets": {
            "body": sorted(body_keys),
            "nocite": sorted(nocite_keys),
            "authorized_nocite": sorted(authorization),
            "library": sorted(library),
            "registry": sorted(registry),
            "visible_bibliography": sorted(visible_keys),
        },
        "occurrence_counts": {
            "body": sum(1 for item in occurrences if item.kind == "body"),
            "nocite": sum(1 for item in occurrences if item.kind == "nocite"),
        },
        "coverage": coverage_metrics,
        "evidence_ledger": evidence_metrics,
        "final_bibliography_closure": closure_metrics,
        "finding_counts": dict(
            sorted(Counter(item["status"] for item in findings).items())
        ),
        "findings": findings,
    }
    report["hashes"] = {
        "audit_payload_sha256": canonical_hash(report),
        "manuscript_sha256": sha256_file(manuscript_path),
        "reference_library_manifest_sha256": library_manifest_sha or None,
        "literature_registry_sha256": registry_sha or None,
        "literature_coverage_contract_sha256": coverage_sha or None,
        "text_to_evidence_ledger_sha256": evidence_sha or None,
        "qa_manifest_sha256": qa_sha or None,
        "visible_bibliography_sha256": (
            sha256_file(visible_path)
            if visible_path is not None and visible_path.is_file()
            else None
        ),
        "bibliography_build_attestation_sha256": (
            sha256_file(attestation_path)
            if attestation_path is not None and attestation_path.is_file()
            else None
        ),
        "expanded_manuscript_sha256": expanded_sha,
    }
    return report


def unavailable_report(args: argparse.Namespace, error: Exception) -> dict[str, Any]:
    status = "metric_unavailable"
    explicit_paths = {
        "manuscript": args.manuscript,
        "reference_library_manifest": args.reference_library_manifest,
        "literature_registry": args.literature_registry,
        "coverage_contract": args.coverage_contract,
        "text_to_evidence_ledger": args.text_to_evidence_ledger,
        "qa_manifest": args.qa_manifest,
        "visible_bibliography": args.visible_bibliography,
        "bibliography_build_attestation": args.bibliography_build_attestation,
    }
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "schema_id": SCHEMA_ID,
        "gate_type": GATE_TYPE,
        "scope": "citation_integrity_gate_only",
        "status": status,
        "gate_local_status": status,
        "whole_manuscript_delivery_authorized": False,
        "exit_code": EXIT_CODES[status],
        "mode": args.mode,
        "inputs": {
            key: (
                input_record(Path(value).expanduser().resolve())
                if value is not None
                else None
            )
            for key, value in sorted(explicit_paths.items())
        },
        "project_root": str(
            Path(args.project_root).expanduser().resolve()
            if args.project_root
            else Path(args.manuscript).expanduser().resolve().parent
        ),
        "citekey_sets": {},
        "coverage": {},
        "evidence_ledger": {},
        "final_bibliography_closure": {},
        "finding_counts": {status: 1},
        "findings": [
            {
                "status": status,
                "code": "citation_metric_unavailable",
                "message": str(error),
            }
        ],
    }
    report["hashes"] = {"audit_payload_sha256": canonical_hash(report)}
    return report


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = run(args)
    except (MetricUnavailable, RecursionError) as exc:
        report = unavailable_report(args, exc)
    report_path = Path(args.report).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"citation integrity audit: {report['status']}; report={report_path}"
    )
    for finding in report.get("findings", []):
        if finding["status"] != "pass":
            print(f"{finding['status'].upper()}: {finding['code']}: {finding['message']}")
    return int(report["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
