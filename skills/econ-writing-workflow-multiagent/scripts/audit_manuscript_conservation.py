#!/usr/bin/env python3
"""Audit a manuscript's budget and, when supplied, baseline conservation.

This standard-library-only guardrail measures deterministic changes. It does
not decide whether prose is substantively sufficient; pair it with the
Main-Text Sufficiency and Conservation Role.

Supported manuscript sources are UTF-8 ``.tex``, ``.md``, and ``.txt``. TeX
may recursively expand static ``input``/``include`` commands inside the
declared project root; Markdown and text are deliberately single-file inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "1.0"
SCHEMA_ID = "manuscript-conservation-audit/1.0"
GATE_TYPE = "manuscript_conservation"
EXIT_CODES = {
    "pass": 0,
    "fail": 1,
    "approval_required": 2,
    "metric_unavailable": 3,
}
SUPPORTED_FORMATS = {"tex", "md", "txt"}
VALID_TASK_MODES = {
    "full_draft",
    "major_revision",
    "restructure",
    "shorten",
    "local_edit",
    "translation",
    "document_translation",
}
BASELINE_REQUIRED_TASK_MODES = VALID_TASK_MODES - {"full_draft"}
VALID_REWRITE_MODES = {
    "patch_existing",
    "reorder_existing_blocks",
    "full_redraft",
}
REWRITE_MODE_AUTHORITY_RANK = {
    "patch_existing": 0,
    "reorder_existing_blocks": 1,
    "full_redraft": 2,
}
REWRITE_MODE_REQUIRED_TASK_MODES = {
    "major_revision",
    "restructure",
    "shorten",
    "local_edit",
}
VALID_TARGET_BASES = {
    "user",
    "project_rule",
    "verified_journal",
    "accepted_baseline",
    "default",
}


class MetricUnavailable(RuntimeError):
    """Raised when a deterministic manuscript metric cannot be reproduced."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_file_records(paths: list[str]) -> list[dict[str, str]]:
    """Return a stable, deduplicated manifest for every expanded source."""

    unique = sorted({str(Path(item).resolve()) for item in paths})
    return [
        {"path": item, "sha256": sha256_file(Path(item))}
        for item in unique
    ]


def strip_latex_comments(text: str) -> str:
    """Blank unescaped comments while preserving bytes offsets and newlines.

    This is intentionally identical to the QA preparer's canonical TeX
    expansion rule so both gates bind the same expanded-manuscript SHA-256.
    """

    cleaned: list[str] = []
    for line in text.splitlines(keepends=True):
        cut = len(line)
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
        fragment = line[:cut] + "".join(
            "\n" if character == "\n" else " " for character in line[cut:]
        )
        cleaned.append(fragment)
    return "".join(cleaned)


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
        raise MetricUnavailable(f"missing include target in {current}")
    if text[cursor] == "{":
        depth = 1
        start = cursor + 1
        cursor += 1
        while cursor < len(text) and depth:
            if text[cursor] == "{" and (cursor == 0 or text[cursor - 1] != "\\"):
                depth += 1
            elif text[cursor] == "}" and (cursor == 0 or text[cursor - 1] != "\\"):
                depth -= 1
                if depth == 0:
                    return text[start:cursor], cursor + 1
            cursor += 1
        raise MetricUnavailable(f"unbalanced include target in {current}")
    match = SAFE_BARE_INCLUDE_RE.match(text, cursor)
    if match is None:
        raise MetricUnavailable(
            f"unsupported dynamic or malformed include target in {current} at offset {cursor}"
        )
    return match.group(0), match.end()


def ensure_within_root(path: Path, root: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise MetricUnavailable(f"include escapes project root: {path}") from exc


def resolve_input(raw: str, current_file: Path, project_root: Path) -> Path:
    child = Path(raw.strip())
    if not child.suffix:
        child = child.with_suffix(".tex")
    if not child.is_absolute():
        child = current_file.parent / child
    child = child.resolve()
    ensure_within_root(child, project_root)
    if not child.is_file():
        raise MetricUnavailable(f"included file not found: {child}")
    return child


def expand_tex(
    path: Path,
    project_root: Path,
    stack: tuple[Path, ...] = (),
) -> tuple[str, list[str]]:
    path = path.resolve()
    ensure_within_root(path, project_root)
    if path in stack:
        cycle = " -> ".join(str(item) for item in (*stack, path))
        raise MetricUnavailable(f"cyclic LaTeX include: {cycle}")
    if not path.is_file():
        raise MetricUnavailable(f"manuscript file not found: {path}")
    try:
        text = strip_latex_comments(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise MetricUnavailable(f"file is not valid UTF-8: {path}") from exc

    unsupported = UNSUPPORTED_INCLUDE_COMMAND_RE.search(text)
    if unsupported is not None:
        raise MetricUnavailable(
            f"unsupported LaTeX include command {unsupported.group(0)} in {path}; "
            "expand it before conservation auditing"
        )

    output: list[str] = []
    sources = [str(path)]
    position = 0
    for match in INPUT_COMMAND_RE.finditer(text):
        output.append(text[position : match.start()])
        raw_target, command_end = include_argument(text, match.end(), path)
        child = resolve_input(raw_target, path, project_root)
        child_text, child_sources = expand_tex(child, project_root, (*stack, path))
        output.append(child_text)
        sources.extend(child_sources)
        position = command_end
    output.append(text[position:])
    return "".join(output), sources


def blank_html_comments(text: str) -> str:
    """Blank Markdown HTML comments while preserving offsets and newlines.

    This intentionally mirrors ``prepare_manuscript_qa.py`` so a Markdown
    manuscript has the same expanded SHA-256 at both deterministic gates.
    """

    def blank(match: re.Match[str]) -> str:
        return "".join(
            character if character in "\r\n" else " "
            for character in match.group(0)
        )

    return re.sub(r"<!--.*?-->", blank, text, flags=re.DOTALL)


def manuscript_format(path: Path) -> str:
    fmt = path.suffix.lower().lstrip(".")
    if fmt not in SUPPORTED_FORMATS:
        raise MetricUnavailable(
            f"manuscript must have .tex, .md, or .txt extension: {path}"
        )
    return fmt


def read_utf8(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise MetricUnavailable(f"file is not valid UTF-8: {path}") from exc
    except OSError as exc:
        raise MetricUnavailable(f"cannot read manuscript file {path}: {exc}") from exc


def load_manuscript(
    path: Path, project_root: Path
) -> tuple[str, list[str], str]:
    """Load one supported manuscript using the QA preparer's hash semantics."""

    path = path.resolve()
    ensure_within_root(path, project_root)
    if not path.is_file():
        raise MetricUnavailable(f"manuscript file not found: {path}")
    fmt = manuscript_format(path)
    if fmt == "tex":
        text, sources = expand_tex(path, project_root)
    else:
        raw = read_utf8(path)
        text = blank_html_comments(raw) if fmt == "md" else raw
        sources = [str(path)]
    return text, sources, fmt


def marker_pattern(marker: str) -> re.Pattern[str]:
    suffix = r"(?![A-Za-z@])" if marker and marker[-1].isalpha() else ""
    return re.compile(re.escape(marker) + suffix)


APPENDIX_HEADING_RE = re.compile(
    r"^(?:"
    r"appendix(?:es)?(?=$|[\s:\uff1aA-Z0-9IVX.\-])|"
    r"\u9644\u5f55(?=$|[\s:\uff1aA-Za-z0-9\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\uff08(])"
    r")",
    re.IGNORECASE,
)


def markdown_heading_title(raw: str) -> str:
    title = re.sub(r"\s+\{#[A-Za-z0-9_.:-]+\}\s*$", "", raw)
    title = re.sub(r"[*_~`]", "", title)
    title = re.sub(r"<[^>]+>", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def markdown_code_ranges(text: str) -> list[tuple[int, int]]:
    ranges = [
        (match.start(), match.end())
        for match in re.finditer(r"```.*?```|~~~.*?~~~", text, flags=re.DOTALL)
    ]
    for match in re.finditer(r"(?<!`)`[^`\r\n]*`(?!`)", text):
        if not any(start <= match.start() < end for start, end in ranges):
            ranges.append((match.start(), match.end()))
    return sorted(ranges)


def span_overlaps(
    start: int, end: int, ranges: list[tuple[int, int]]
) -> bool:
    return any(start < range_end and end > range_start for range_start, range_end in ranges)


def blank_ranges(text: str, ranges: list[tuple[int, int]]) -> str:
    characters = list(text)
    for start, end in ranges:
        for index in range(start, min(end, len(characters))):
            if characters[index] not in "\r\n":
                characters[index] = " "
    return "".join(characters)


def markdown_formula_spans(
    text: str, excluded: list[tuple[int, int]] | None = None
) -> list[tuple[int, int]]:
    """Match the QA preparer's dollar/currency disambiguation rules."""

    blocked_ranges = excluded or []

    def blocked_at(position: int) -> tuple[int, int] | None:
        return next(
            (
                (start, end)
                for start, end in blocked_ranges
                if start <= position < end
            ),
            None,
        )

    def next_single_dollar(position: int) -> int | None:
        cursor = position
        while cursor < len(text):
            blocked = blocked_at(cursor)
            if blocked is not None:
                cursor = blocked[1]
                continue
            if text[cursor] == "$" and not escaped_at(text, cursor):
                if text[cursor : cursor + 2] == "$$":
                    cursor += 2
                    continue
                return cursor
            cursor += 1
        return None

    spans: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(text):
        blocked = blocked_at(cursor)
        if blocked is not None:
            cursor = blocked[1]
            continue
        if text[cursor] != "$" or escaped_at(text, cursor):
            cursor += 1
            continue
        if text[cursor : cursor + 2] == "$$":
            close = cursor + 2
            while True:
                close = text.find("$$", close)
                if close < 0:
                    raise MetricUnavailable("unclosed Markdown display formula")
                if not escaped_at(text, close) and blocked_at(close) is None:
                    break
                close += 2
            spans.append((cursor, close + 2))
            cursor = close + 2
            continue
        close = next_single_dollar(cursor + 1)
        following = text[cursor + 1 : cursor + 2]
        if close is None:
            if following and not following.isdigit() and not following.isspace():
                raise MetricUnavailable(
                    "unclosed Markdown inline formula or ambiguous dollar delimiter"
                )
            cursor += 1
            continue
        inner = text[cursor + 1 : close]
        formula_signal = re.search(r"[\\_^{}=<>+*/-]", inner) is not None
        currency_like = re.match(r"\s*\d", inner) is not None and (
            re.search(r"[A-Za-z\u3400-\u4dbf\u4e00-\u9fff]", inner) is not None
            or re.search(r"[,;\uff0c\uff1b:]", inner) is not None
        ) and not formula_signal
        if currency_like:
            cursor += 1
            continue
        spans.append((cursor, close + 1))
        cursor = close + 1
    return spans


def txt_heading_matches(text: str) -> list[re.Match[str]]:
    pattern = re.compile(
        r"(?m)^(?P<title>[ \t]*(?:(?:\d+(?:\.\d+)*[.)]?)[ \t]+[^\n]+|"
        r"[\u4e00-\u5341]+\u3001[ \t]*[^\n]+|\u7b2c[\u4e00-\u5341\d]+[\u7ae0\u8282][ \t]*[^\n]+|"
        r"(?:Appendix|Appendices)(?:[ \t:\uff1aA-Z0-9IVX.\-]+[^\n]*)?|"
        r"\u9644\u5f55(?:[ \t:\uff1aA-Za-z0-9\u4e00\u4e8c\u4e09\u56db\u4e94\u516d\u4e03\u516b\u4e5d\u5341\uff08(][^\n]*)?))[ \t]*$",
        re.IGNORECASE,
    )
    return list(pattern.finditer(text))


def native_appendix_matches(text: str, fmt: str) -> list[re.Match[str]]:
    if fmt == "md":
        headings = list(re.finditer(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*$", text))
        return [
            match
            for match in headings
            if APPENDIX_HEADING_RE.match(markdown_heading_title(match.group(2)))
        ]
    return [
        match
        for match in txt_heading_matches(text)
        if APPENDIX_HEADING_RE.match(match.group("title").strip())
    ]


def split_appendix(
    text: str, marker: str, label: str, fmt: str = "tex"
) -> tuple[str, str]:
    if fmt not in SUPPORTED_FORMATS:
        raise MetricUnavailable(f"unsupported manuscript format: {fmt}")
    if fmt == "tex" or marker != r"\appendix":
        matches = list(marker_pattern(marker).finditer(text))
        marker_description = marker
    else:
        matches = native_appendix_matches(text, fmt)
        marker_description = f"{fmt} Appendix/\u9644\u5f55 heading"
    if len(matches) != 1:
        raise MetricUnavailable(
            f"{label} requires exactly one appendix marker {marker_description!r}; "
            f"found {len(matches)}"
        )
    match = matches[0]
    return text[: match.start()], text[match.end() :]


def raw_source_words(text: str) -> int:
    return len(re.findall(r"\S+", text))


DROP_ARGUMENT_COMMANDS = re.compile(
    r"\\(?:label|ref|eqref|autoref|pageref|cite\w*|url|href)\*?"
    r"(?:\s*\[[^\]]*\])*\s*\{[^{}]*\}"
)


def normalized_words(text: str, fmt: str = "tex") -> int:
    if fmt == "txt":
        return len(
            re.findall(
                r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*|[\u3400-\u4dbf\u4e00-\u9fff]",
                text,
            )
        )
    if fmt == "md":
        code_ranges = markdown_code_ranges(text)
        formula_ranges = markdown_formula_spans(text, code_ranges)
        cleaned = blank_ranges(text, [*code_ranges, *formula_ranges])
        cleaned = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", cleaned)
        cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
        cleaned = re.sub(r"\[\^[^\]]+\]", " ", cleaned)
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        cleaned = re.sub(r"(?m)^\s{0,3}#{1,6}[ \t]+", " ", cleaned)
        cleaned = re.sub(r"(?m)^\s{0,3}(?:[-*+] |\d+[.)] )", " ", cleaned)
        cleaned = re.sub(r"[*_~]", "", cleaned)
        return len(
            re.findall(
                r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*|[\u3400-\u4dbf\u4e00-\u9fff]",
                cleaned,
            )
        )
    escaped_dollar = "\ue000"
    text = text.replace(r"\$", escaped_dollar)
    cleaned = DROP_ARGUMENT_COMMANDS.sub(" ", text)
    cleaned = re.sub(r"\$\$.*?\$\$|\$.*?\$", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"\\\[.*?\\\]|\\\(.*?\\\)", " ", cleaned, flags=re.DOTALL)
    cleaned = re.sub(r"\\begin\s*\{[^{}]*\}|\\end\s*\{[^{}]*\}", " ", cleaned)
    cleaned = re.sub(r"\\[A-Za-z@]+\*?(?:\s*\[[^\]]*\])*", " ", cleaned)
    cleaned = cleaned.translate(str.maketrans({"{": " ", "}": " ", "~": " ", "&": " "}))
    cleaned = cleaned.replace(escaped_dollar, " ")
    tokens = re.findall(
        r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*|[\u3400-\u4dbf\u4e00-\u9fff]",
        cleaned,
    )
    return len(tokens)


def clean_title(title: str) -> str:
    title = re.sub(r"\\[A-Za-z@]+\*?", " ", title)
    title = re.sub(r"[{}~]", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def normalize_identifier(value: str) -> str:
    return re.sub(
        r"[^a-z0-9\u3400-\u4dbf\u4e00-\u9fff]+",
        " ",
        clean_title(value).lower(),
    ).strip()


LABEL_RE = re.compile(r"\\label\s*\{([^{}]+)\}")
CITE_RE = re.compile(r"\\cite\w*\*?(?:\s*\[[^\]]*\])*\s*\{([^{}]+)\}")


def escaped_at(text: str, position: int) -> bool:
    backslashes = 0
    cursor = position - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def balanced_argument(
    text: str, position: int, opening: str, closing: str, label: str
) -> tuple[str, int]:
    if position >= len(text) or text[position] != opening:
        raise MetricUnavailable(f"missing {label} at offset {position}")
    depth = 1
    cursor = position + 1
    while cursor < len(text):
        character = text[cursor]
        if character == opening and not escaped_at(text, cursor):
            depth += 1
        elif character == closing and not escaped_at(text, cursor):
            depth -= 1
            if depth == 0:
                return text[position + 1 : cursor], cursor + 1
        cursor += 1
    raise MetricUnavailable(f"unbalanced {label} at offset {position}")


TEX_SECTION_COMMAND_RE = re.compile(
    r"\\(subsection|section)\*?(?![A-Za-z@])"
)


def scan_tex_headings(text: str) -> list[dict[str, Any]]:
    """Parse section headings with balanced optional and required arguments."""

    records: list[dict[str, Any]] = []
    for match in TEX_SECTION_COMMAND_RE.finditer(text):
        cursor = match.end()
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
        while cursor < len(text) and text[cursor] == "[":
            _, cursor = balanced_argument(
                text, cursor, "[", "]", f"optional argument for {match.group(1)}"
            )
            while cursor < len(text) and text[cursor].isspace():
                cursor += 1
        raw_title, end = balanced_argument(
            text, cursor, "{", "}", f"title argument for {match.group(1)}"
        )
        records.append(
            {
                "start": match.start(),
                "end": end,
                "command": match.group(1),
                "level": 1 if match.group(1) == "section" else 2,
                "title": clean_title(raw_title),
                "raw_title": raw_title,
            }
        )
    return records


def native_headings(text: str, fmt: str) -> list[dict[str, Any]]:
    if fmt == "tex":
        return scan_tex_headings(text)
    if fmt == "md":
        return [
            {
                "start": match.start(),
                "end": match.end(),
                "command": f"h{len(match.group(1))}",
                "level": len(match.group(1)),
                "title": markdown_heading_title(match.group(2)),
                "raw_title": match.group(2),
            }
            for match in re.finditer(r"(?m)^(#{1,6})[ \t]+(.+?)[ \t]*$", text)
        ]
    if fmt == "txt":
        return [
            {
                "start": match.start(),
                "end": match.end(),
                "command": "text_heading",
                "level": 1,
                "title": match.group("title").strip(),
                "raw_title": match.group("title"),
            }
            for match in txt_heading_matches(text)
        ]
    raise MetricUnavailable(f"unsupported manuscript format: {fmt}")


def primary_section_headings(text: str, fmt: str) -> list[dict[str, Any]]:
    headings = native_headings(text, fmt)
    if fmt == "tex":
        return [item for item in headings if item["command"] == "section"]
    return headings


def native_labels(text: str, fmt: str) -> list[str]:
    if fmt == "tex":
        return sorted(set(LABEL_RE.findall(text)))
    if fmt == "md":
        anchors = set(re.findall(r"\{#([A-Za-z0-9_.:-]+)\}", text))
        anchors.update(
            re.findall(r"\bid\s*=\s*[\"']([^\"']+)[\"']", text, re.IGNORECASE)
        )
        return sorted(anchors)
    return []


def section_heading_labels(
    text: str, heading: dict[str, Any], section_end: int, fmt: str
) -> list[str]:
    """Return labels bound to the heading, not arbitrary labels in its body."""

    if fmt == "md":
        return native_labels(text[heading["start"] : heading["end"]], fmt)
    if fmt != "tex":
        return []

    labels = set(native_labels(text[heading["start"] : heading["end"]], fmt))
    cursor = heading["end"]
    while cursor < section_end:
        whitespace = re.match(r"\s*", text[cursor:section_end])
        if whitespace is not None:
            cursor += whitespace.end()
        label = LABEL_RE.match(text, cursor, section_end)
        if label is None:
            break
        labels.add(label.group(1))
        cursor = label.end()
    return sorted(labels)


def extract_sections(text: str, fmt: str = "tex") -> list[dict[str, Any]]:
    matches = primary_section_headings(text, fmt)
    occurrences: Counter[str] = Counter()
    sections: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        title = match["title"]
        normalized = normalize_identifier(title)
        occurrences[normalized] += 1
        end = matches[index + 1]["start"] if index + 1 < len(matches) else len(text)
        body = text[match["start"] : end]
        sections.append(
            {
                "id": f"{normalized}#{occurrences[normalized]}",
                "title": title,
                "normalized_title": normalized,
                "raw_source_words": raw_source_words(body),
                "normalized_words": normalized_words(body, fmt),
                "labels": native_labels(body, fmt),
                "heading_labels": section_heading_labels(text, match, end, fmt),
            }
        )
    return sections


def extract_citations(text: str, fmt: str = "tex") -> list[str]:
    citations: set[str] = set()
    if fmt == "tex":
        for group in CITE_RE.findall(text):
            citations.update(item.strip() for item in group.split(",") if item.strip())
    elif fmt == "md":
        for group in re.findall(r"\[([^\]]*@[A-Za-z0-9_.:-]+[^\]]*)\]", text):
            citations.update(re.findall(r"@([A-Za-z0-9_.:-]+)", group))
    return sorted(citations)


def count_environments(text: str, names: tuple[str, ...]) -> int:
    choices = "|".join(re.escape(name) for name in names)
    return len(re.findall(rf"\\begin\s*\{{(?:{choices})\*?\}}", text))


def structure_metrics(text: str, fmt: str = "tex") -> dict[str, Any]:
    headings = native_headings(text, fmt)
    if fmt == "tex":
        section_count = sum(item["command"] == "section" for item in headings)
        subsection_count = sum(item["command"] == "subsection" for item in headings)
        object_spans = tex_object_spans(text)
        equation_count = sum(
            object_type == "equation" for _, _, object_type in object_spans
        )
        formula_count = equation_count + sum(
            object_type == "inline_formula"
            for _, _, object_type in object_spans
        )
        proposition_count = count_environments(
            text, ("proposition", "theorem", "lemma", "corollary")
        )
        table_count = count_environments(text, ("table", "longtable"))
        figure_count = count_environments(text, ("figure",))
    elif fmt == "md":
        section_count = len(headings)
        subsection_count = sum(item["level"] > 1 for item in headings)
        object_spans = markdown_object_spans(text)
        equation_count = sum(
            object_type == "equation" for _, _, object_type in object_spans
        )
        formula_count = equation_count + sum(
            object_type == "inline_formula"
            for _, _, object_type in object_spans
        )
        proposition_count = len(
            re.findall(
                r"(?im)^(?:#{1,6}[ \t]+|\*\*)?(?:proposition|theorem|lemma|corollary)\b",
                text,
            )
        )
        table_count = len(
            re.findall(
                r"(?m)^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*$",
                text,
            )
        )
        figure_count = len(re.findall(r"!\[[^\]]*\]\([^)]+\)", text))
    else:
        section_count = len(headings)
        subsection_count = 0
        equation_count = len(re.findall(r"(?im)^\s*equation\s+[A-Za-z0-9IVX.:-]+", text))
        formula_count = equation_count
        proposition_count = len(
            re.findall(r"(?im)^\s*(?:proposition|theorem|lemma|corollary)\b", text)
        )
        table_count = len(re.findall(r"(?im)^\s*table\s+[A-Za-z0-9IVX.:-]+", text))
        figure_count = len(re.findall(r"(?im)^\s*figure\s+[A-Za-z0-9IVX.:-]+", text))
    return {
        "sections": section_count,
        "subsections": subsection_count,
        "formulas": formula_count,
        "equations": equation_count,
        "propositions_theorems": proposition_count,
        "tables": table_count,
        "figures": figure_count,
        "labels": native_labels(text, fmt),
        "citations": extract_citations(text, fmt),
    }


def manuscript_metrics(text: str, fmt: str = "tex") -> dict[str, Any]:
    metric_text = document_body(text, fmt)
    metrics = {
        "raw_source_words": raw_source_words(metric_text),
        "normalized_words": normalized_words(metric_text, fmt),
        "structure": structure_metrics(metric_text, fmt),
        "section_metrics": extract_sections(metric_text, fmt),
    }
    return metrics


def load_contract(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MetricUnavailable(f"cannot read artifact contract: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise MetricUnavailable("artifact contract must be a JSON object")
    direct = payload.get("artifact_contract")
    paper_state = payload.get("paper_state")
    if "artifact_contract" in payload and not isinstance(direct, dict):
        raise MetricUnavailable("artifact_contract must be a JSON object")
    if "paper_state" in payload and not isinstance(paper_state, dict):
        raise MetricUnavailable("paper_state must be a JSON object")
    state_contract = (
        paper_state.get("artifact_contract")
        if isinstance(paper_state, dict)
        else None
    )
    if (
        isinstance(paper_state, dict)
        and "artifact_contract" in paper_state
        and not isinstance(state_contract, dict)
    ):
        raise MetricUnavailable("paper_state.artifact_contract must be a JSON object")
    candidates = [item for item in (direct, state_contract) if isinstance(item, dict)]
    canonical = {
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for item in candidates
    }
    if len(canonical) > 1:
        raise MetricUnavailable(
            "conflicting top-level and paper_state artifact_contract objects"
        )
    nested = candidates[0] if candidates else payload
    if not isinstance(nested, dict):
        raise MetricUnavailable("artifact_contract must be a JSON object")
    contract = dict(nested)
    contexts = (payload, paper_state if isinstance(paper_state, dict) else {})
    for key in (
        "content_conservation_ledger",
        "baseline_to_candidate",
        "section_cards",
        "content_obligations",
    ):
        values = []
        if contract.get(key) not in (None, ""):
            values.append(contract[key])
        values.extend(
            context[key]
            for context in contexts
            if context.get(key) not in (None, "")
        )
        fingerprints = {
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for value in values
        }
        if len(fingerprints) > 1:
            raise MetricUnavailable(f"conflicting artifact context field: {key}")
        if key not in contract and values:
            contract[key] = values[0]
    return contract


def normalized_sha256(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw.startswith("sha256:"):
        raw = raw.split(":", 1)[1].strip()
    return raw


def nonempty_identity(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(
            str(value.get(key) or "").strip()
            for key in ("name", "id", "author", "user", "by")
        )
    return False


def resolve_contract_path(
    raw: str, contract_path: Path | None, project_root: Path
) -> Path:
    value = Path(raw).expanduser()
    if value.is_absolute():
        resolved = value.resolve()
    else:
        bases = [contract_path.parent] if contract_path is not None else []
        if project_root not in bases:
            bases.append(project_root)
        candidates = [(base / value).resolve() for base in bases]
        existing = [item for item in candidates if item.is_file()]
        if len({str(item) for item in existing}) > 1:
            raise MetricUnavailable(f"ambiguous baseline_artifact.path: {raw}")
        resolved = existing[0] if existing else candidates[0]
    ensure_within_root(resolved, project_root)
    return resolved


def validate_baseline_binding(
    contract: dict[str, Any],
    baseline_path: Path | None,
    baseline_expanded_sha256: str | None,
    baseline_source_files: list[dict[str, str]],
    contract_path: Path | None,
    project_root: Path,
) -> list[str]:
    """Bind the audited baseline to an accepted, live-hash contract record."""

    failures: list[str] = []
    record = contract.get("baseline_artifact")
    if baseline_path is None:
        if record not in (None, {}, ""):
            failures.append(
                "baseline_artifact is present but the audit has no --baseline"
            )
        return failures
    if not isinstance(record, dict):
        return [
            "--baseline requires artifact_contract.baseline_artifact with path, SHA-256, accepted status, and accepted_by"
        ]

    raw_path = str(record.get("path") or "").strip()
    if not raw_path:
        failures.append("baseline_artifact.path is required")
    else:
        recorded_path = resolve_contract_path(raw_path, contract_path, project_root)
        if recorded_path != baseline_path:
            failures.append(
                f"--baseline does not match baseline_artifact.path: {recorded_path}"
            )

    expected_hash = normalized_sha256(
        record.get("sha256")
        or record.get("version_or_hash")
        or record.get("hash")
    )
    if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        failures.append("baseline_artifact requires a valid SHA-256")
    else:
        live_hash = sha256_file(baseline_path)
        if expected_hash != live_hash:
            failures.append(
                f"baseline_artifact SHA-256 mismatch: expected {expected_hash}, got {live_hash}"
            )

    expected_expanded_hash = normalized_sha256(record.get("expanded_sha256"))
    if len(baseline_source_files) > 1 and record.get("expanded_sha256") is None:
        failures.append(
            "multi-source baseline_artifact requires expanded_sha256"
        )
    if record.get("expanded_sha256") is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_expanded_hash):
            failures.append("baseline_artifact.expanded_sha256 is invalid")
        elif expected_expanded_hash != baseline_expanded_sha256:
            failures.append(
                "baseline_artifact.expanded_sha256 does not match the audited expansion"
            )

    recorded_sources = record.get("source_files")
    if len(baseline_source_files) > 1 and not isinstance(recorded_sources, list):
        failures.append(
            "multi-source baseline_artifact requires a source_files hash manifest"
        )
    if recorded_sources is not None:
        if not isinstance(recorded_sources, list):
            failures.append("baseline_artifact.source_files must be a list")
        else:
            normalized_records: list[dict[str, str]] = []
            for index, item in enumerate(recorded_sources, 1):
                if not isinstance(item, dict):
                    failures.append(
                        f"baseline_artifact.source_files[{index}] must be an object"
                    )
                    continue
                raw_source_path = str(item.get("path") or "").strip()
                source_hash = normalized_sha256(item.get("sha256"))
                if not raw_source_path or not re.fullmatch(r"[0-9a-f]{64}", source_hash):
                    failures.append(
                        f"baseline_artifact.source_files[{index}] requires path and SHA-256"
                    )
                    continue
                source_path = resolve_contract_path(
                    raw_source_path, contract_path, project_root
                )
                normalized_records.append(
                    {"path": str(source_path), "sha256": source_hash}
                )
            if sorted(
                normalized_records, key=lambda item: item["path"]
            ) != sorted(baseline_source_files, key=lambda item: item["path"]):
                failures.append(
                    "baseline_artifact.source_files does not match the audited source graph"
                )

    status = str(
        record.get("acceptance_status")
        or record.get("status")
        or record.get("artifact_status")
        or ""
    ).strip().lower()
    if status not in {
        "accepted",
        "author_accepted",
        "confirmed",
        "frozen_current",
        "frozen-ready",
        "frozen_ready",
    }:
        failures.append("baseline_artifact must record an accepted status")
    if not nonempty_identity(record.get("accepted_by")):
        failures.append("baseline_artifact.accepted_by is required")
    return failures


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def range_pair(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    lower, upper = number(value[0]), number(value[1])
    if lower is None or upper is None or lower < 0 or upper < 0 or lower > upper:
        return None
    return lower, upper


def nonempty_approval_source(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(str(item).strip() for item in value.values() if item is not None)
    return False


def valid_iso_timestamp(value: Any) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def audit_argument_record(args: argparse.Namespace) -> dict[str, Any]:
    """Serialize every optional CLI decision needed for deterministic replay."""

    return {
        "appendix_marker": args.appendix_marker,
        "word_metric": args.word_metric,
        "max_main_reduction": args.max_main_reduction,
        "min_main_source_words": args.min_main_source_words,
        "baseline_main_pdf_pages": args.baseline_main_pdf_pages,
        "candidate_main_pdf_pages": args.candidate_main_pdf_pages,
        "min_main_pdf_pages": args.min_main_pdf_pages,
    }


def valid_author_approval_record(record: Any) -> bool:
    if not isinstance(record, dict):
        return False
    authority = str(
        record.get("approval_authority")
        or record.get("authority_role")
        or record.get("role")
        or ""
    ).strip().lower()
    return bool(
        authority in {"author", "recorded_human_delegate"}
        and str(record.get("approved_by") or record.get("by") or "").strip()
        and valid_iso_timestamp(record.get("approved_at") or record.get("at"))
        and nonempty_approval_source(record.get("approval_source"))
    )


def approval_scopes(contract: dict[str, Any]) -> set[str]:
    record = contract.get("approval_record", {})
    return scope_values(record) if valid_author_approval_record(record) else set()


def compression_approved(contract: dict[str, Any], scopes: set[str]) -> bool:
    value = contract.get("user_approved_compression", False)
    records: list[dict[str, Any]] = []
    if isinstance(value, dict) and value.get("approved"):
        records.append(value)
    record = contract.get("approval_record")
    if value is True and isinstance(record, dict):
        records.append(record)
    if isinstance(record, dict):
        records.append(record)
    return any(
        valid_author_approval_record(item)
        and bool(
            {"all", "compression", "main_text_reduction"} & scope_values(item)
        )
        for item in records
    )


def full_redraft_approved(contract: dict[str, Any], scopes: set[str]) -> bool:
    record = contract.get("approval_record")
    return bool(
        valid_author_approval_record(record)
        and {"all", "full_redraft"} & scopes
    )


def selected_word_metric(contract: dict[str, Any], cli_value: str | None) -> str:
    measurement = contract.get("measurement_contract", {})
    if isinstance(measurement, dict):
        method = measurement.get("source_word_method")
        if method in {"raw_source_words", "normalized_words"}:
            return str(method)
    if cli_value:
        return cli_value
    return "normalized_words"


def reduction_pct(baseline: float, candidate: float) -> float | None:
    if baseline <= 0:
        return None
    return (baseline - candidate) / baseline


def structural_delta(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    for key in (
        "sections",
        "subsections",
        "formulas",
        "equations",
        "propositions_theorems",
        "tables",
        "figures",
    ):
        delta[key] = candidate[key] - baseline[key]
    baseline_labels, candidate_labels = set(baseline["labels"]), set(candidate["labels"])
    baseline_cites, candidate_cites = set(baseline["citations"]), set(candidate["citations"])
    delta["labels_removed"] = sorted(baseline_labels - candidate_labels)
    delta["labels_added"] = sorted(candidate_labels - baseline_labels)
    delta["citations_removed"] = sorted(baseline_cites - candidate_cites)
    delta["citations_added"] = sorted(candidate_cites - baseline_cites)
    return delta


def main_label_to_section(sections: list[dict[str, Any]]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for section in sections:
        for label in section["labels"]:
            mapping[label] = section["normalized_title"]
    return mapping


def check_must_remain(
    contract: dict[str, Any], candidate_sections: list[dict[str, Any]], candidate_labels: set[str]
) -> list[str]:
    requirements = contract.get("must_remain_main", [])
    if isinstance(requirements, (str, dict)):
        requirements = [requirements]
    if not isinstance(requirements, list):
        return ["must_remain_main has an invalid type"]
    section_names = {section["normalized_title"] for section in candidate_sections}
    missing: list[str] = []
    for requirement in requirements:
        if isinstance(requirement, dict):
            kind = str(requirement.get("type", "")).lower()
            value = str(requirement.get("value") or requirement.get("id") or "").strip()
        else:
            kind, value = "either", str(requirement).strip()
        if not value:
            continue
        present = False
        if kind in {"label", "either"} and value in candidate_labels:
            present = True
        if kind in {"section", "title", "either"} and normalize_identifier(value) in section_names:
            present = True
        if not present:
            missing.append(value)
    return missing


def registered_obligation_ids(contract: dict[str, Any]) -> set[str]:
    """Return the closed obligation/intent ID registry visible to this gate."""

    obligations = contract.get("content_obligations")
    identifiers: set[str] = set()
    if isinstance(obligations, list):
        items = obligations
    elif isinstance(obligations, dict):
        identifiers.update(
            str(key).strip() for key in obligations if str(key).strip()
        )
        items = list(obligations.values())
    else:
        items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        identifier = (
            item.get("obligation_id")
            or item.get("intent_id")
            or item.get("id")
        )
        if isinstance(identifier, str) and identifier.strip():
            identifiers.add(identifier.strip())
    return identifiers


def validate_card_must_remain_references(
    card: dict[str, Any],
    card_id: str,
    candidate_sections: list[dict[str, Any]],
    obligation_ids: set[str],
    failures: list[str],
) -> list[dict[str, Any]]:
    """Bind every mature-card main-text requirement to a live object or ID."""

    raw = card.get("must_remain_main")
    requirements = raw if isinstance(raw, list) else [raw]
    section_names = {
        section["normalized_title"] for section in candidate_sections
    }
    candidate_labels = {
        label for section in candidate_sections for label in section.get("labels", [])
    }
    valid_kinds = {
        "section",
        "title",
        "label",
        "obligation",
        "obligation_id",
        "intent",
        "intent_id",
        "either",
    }
    checks: list[dict[str, Any]] = []
    for index, requirement in enumerate(requirements, 1):
        if isinstance(requirement, dict):
            kind = str(requirement.get("type") or "either").strip().lower()
            value = str(
                requirement.get("value")
                or requirement.get("obligation_id")
                or requirement.get("intent_id")
                or requirement.get("id")
                or requirement.get("label")
                or requirement.get("section")
                or ""
            ).strip()
        elif isinstance(requirement, str):
            kind = "either"
            value = requirement.strip()
        else:
            kind = "invalid"
            value = ""

        matched_kind: str | None = None
        if kind not in valid_kinds:
            failures.append(
                f"section card {card_id} must_remain_main entry {index} has "
                f"unsupported type: {kind}"
            )
        elif not value:
            failures.append(
                f"section card {card_id} must_remain_main entry {index} "
                "requires a nonempty value"
            )
        else:
            if kind in {"section", "title", "either"} and (
                normalize_identifier(value) in section_names
            ):
                matched_kind = "section"
            if matched_kind is None and kind in {"label", "either"} and (
                value in candidate_labels
            ):
                matched_kind = "label"
            if matched_kind is None and kind in {
                "obligation",
                "obligation_id",
                "intent",
                "intent_id",
                "either",
            } and value in obligation_ids:
                matched_kind = "obligation_or_intent"
            if matched_kind is None:
                failures.append(
                    f"section card {card_id} has unverifiable must_remain_main "
                    f"reference: {value}"
                )
        checks.append(
            {
                "kind": kind,
                "value": value,
                "matched_kind": matched_kind,
                "status": "verified_reference" if matched_kind else "unverifiable",
            }
        )
    return checks


def canonical_block_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def paragraph_spans(text: str) -> list[tuple[int, int, str]]:
    """Return the same blocks as the canonical split while retaining offsets."""

    spans: list[tuple[int, int, str]] = []
    cursor = 0
    for separator in re.finditer(r"(?:\r?\n\s*){2,}", text):
        spans.append((cursor, separator.start(), text[cursor : separator.start()]))
        cursor = separator.end()
    spans.append((cursor, len(text), text[cursor:]))
    return spans


def document_body(text: str, fmt: str = "tex") -> str:
    if fmt == "tex":
        begin = re.search(r"\\begin\s*\{document\}", text)
        if begin is not None:
            text = text[begin.end() :]
        end = re.search(r"\\end\s*\{document\}", text)
        if end is not None:
            text = text[: end.start()]
    return text


def substantive_block_inventory(
    text: str, region: str, fmt: str = "tex"
) -> list[dict[str, Any]]:
    """Create stable paragraph/block IDs for deterministic ledger coverage.

    IDs bind the region, section identity, and canonical block content. They are
    stable across runs and section reordering, while a move, rename, or revision
    deliberately creates a new candidate destination ID that the ledger must name.
    """

    body = document_body(text, fmt)
    section_matches = primary_section_headings(body, fmt)
    segments: list[tuple[str, str, str, int]] = []
    if section_matches:
        prefix = body[: section_matches[0]["start"]]
        if canonical_block_text(prefix):
            segments.append(("front-matter#1", "Front matter", prefix, 0))
        occurrences: Counter[str] = Counter()
        for index, match in enumerate(section_matches):
            title = match["title"]
            normalized = normalize_identifier(title) or "untitled"
            occurrences[normalized] += 1
            section_id = f"{normalized}#{occurrences[normalized]}"
            end = (
                section_matches[index + 1]["start"]
                if index + 1 < len(section_matches)
                else len(body)
            )
            segments.append(
                (section_id, title, body[match["end"] : end], match["end"])
            )
    else:
        segments.append(("unsectioned#1", "Unsectioned", body, 0))

    inventory: list[dict[str, Any]] = []
    occurrences_by_fingerprint: Counter[str] = Counter()
    for section_id, section_title, section_body, section_start in segments:
        for block_start, block_end, raw_block in paragraph_spans(section_body):
            canonical = canonical_block_text(raw_block)
            if not canonical or normalized_words(canonical, fmt) == 0:
                continue
            content_hash = sha256_text(canonical)
            material = f"{region}\0{section_id}\0{content_hash}"
            fingerprint = sha256_text(material)[:20]
            occurrences_by_fingerprint[fingerprint] += 1
            block_id = (
                f"block-{fingerprint}-{occurrences_by_fingerprint[fingerprint]}"
            )
            inventory.append(
                {
                    "block_id": block_id,
                    "inventory_kind": "prose_block",
                    "content_sha256": content_hash,
                    "section_id": section_id,
                    "section": section_title,
                    "normalized_section": section_id.rsplit("#", 1)[0],
                    "region": region,
                    "source_start": section_start + block_start,
                    "source_end": section_start + block_end,
                    "raw_source_words": raw_source_words(canonical),
                    "normalized_words": normalized_words(canonical, fmt),
                    "labels": native_labels(canonical, fmt),
                }
            )
    return inventory


TEX_OBJECT_ENVIRONMENTS = {
    "equation": "equation",
    "align": "equation",
    "alignat": "equation",
    "gather": "equation",
    "multline": "equation",
    "displaymath": "equation",
    "proposition": "proposition",
    "theorem": "proposition",
    "lemma": "proposition",
    "corollary": "proposition",
    "table": "table",
    "longtable": "table",
    "figure": "figure",
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


def section_contexts(text: str, fmt: str) -> list[dict[str, Any]]:
    occurrences: Counter[str] = Counter()
    contexts: list[dict[str, Any]] = []
    for heading in primary_section_headings(text, fmt):
        normalized = normalize_identifier(heading["title"]) or "untitled"
        occurrences[normalized] += 1
        contexts.append(
            {
                "start": heading["start"],
                "section": heading["title"],
                "normalized_section": normalized,
                "section_id": f"{normalized}#{occurrences[normalized]}",
            }
        )
    return contexts


def context_at(position: int, contexts: list[dict[str, Any]]) -> dict[str, str]:
    current = {
        "section": "Front matter",
        "normalized_section": "front matter",
        "section_id": "front-matter#1",
    }
    for context in contexts:
        if context["start"] > position:
            break
        current = {
            "section": context["section"],
            "normalized_section": context["normalized_section"],
            "section_id": context["section_id"],
        }
    return current


def tex_object_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    choices = "|".join(
        sorted((re.escape(item) for item in TEX_OBJECT_ENVIRONMENTS), key=len, reverse=True)
    )
    begin_re = re.compile(rf"\\begin\s*\{{(?P<name>{choices})(?:\*)?\}}")
    for match in begin_re.finditer(text):
        name = match.group("name")
        close = re.search(
            rf"\\end\s*\{{{re.escape(name)}(?:\*)?\}}", text[match.end() :]
        )
        if close is None:
            raise MetricUnavailable(
                f"unclosed {name} environment at offset {match.start()}"
            )
        end = match.end() + close.end()
        spans.append((match.start(), end, TEX_OBJECT_ENVIRONMENTS[name]))
    occupied = [(start, end) for start, end, _ in spans]
    for match in TEX_FORMULA_RE.finditer(text):
        if any(start <= match.start() and match.end() <= end for start, end in occupied):
            continue
        raw = match.group(0)
        object_type = (
            "inline_formula"
            if (raw.startswith("$") and not raw.startswith("$$"))
            or raw.startswith(r"\(")
            else "equation"
        )
        spans.append((match.start(), match.end(), object_type))
        occupied.append((match.start(), match.end()))
    return sorted(spans)


def markdown_object_spans(text: str) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    code_ranges = markdown_code_ranges(text)
    for start, end in markdown_formula_spans(text, code_ranges):
        spans.append(
            (
                start,
                end,
                "equation" if text[start:end].startswith("$$") else "inline_formula",
            )
        )
    spans.extend(
        (match.start(), match.end(), "equation")
        for match in re.finditer(r"\\\[.*?\\\]", text, re.DOTALL)
        if not span_overlaps(match.start(), match.end(), code_ranges)
    )
    spans.extend(
        (match.start(), match.end(), "figure")
        for match in re.finditer(r"!\[[^\]]*\]\([^)]+\)(?:\s*\{#[^}]+\})?", text)
        if not span_overlaps(match.start(), match.end(), code_ranges)
    )
    lines = list(re.finditer(r"(?m)^.*(?:\n|$)", text))
    for index, line in enumerate(lines):
        if not re.fullmatch(
            r"\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*:?-{3,}:?\s*\|?\s*(?:\n|$)",
            line.group(0),
        ):
            continue
        if span_overlaps(line.start(), line.end(), code_ranges):
            continue
        start_index = max(0, index - 1)
        end_index = index + 1
        while end_index < len(lines) and "|" in lines[end_index].group(0):
            end_index += 1
        spans.append(
            (
                lines[start_index].start(),
                lines[end_index - 1].end(),
                "table",
            )
        )
    for match in re.finditer(
        r"(?im)^(?:#{1,6}[ \t]+|\*\*)?(?:proposition|theorem|lemma|corollary)\b[^\n]*",
        text,
    ):
        if span_overlaps(match.start(), match.end(), code_ranges):
            continue
        spans.append((match.start(), match.end(), "proposition"))
    return sorted(set(spans))


def txt_object_spans(text: str) -> list[tuple[int, int, str]]:
    kind_by_name = {
        "equation": "equation",
        "proposition": "proposition",
        "theorem": "proposition",
        "lemma": "proposition",
        "corollary": "proposition",
        "table": "table",
        "figure": "figure",
    }
    spans: list[tuple[int, int, str]] = []
    for match in re.finditer(
        r"(?im)^\s*(equation|proposition|theorem|lemma|corollary|table|figure)\b[^\n]*",
        text,
    ):
        spans.append((match.start(), match.end(), kind_by_name[match.group(1).lower()]))
    return spans


def substantive_object_inventory(
    text: str, region: str, fmt: str = "tex"
) -> list[dict[str, Any]]:
    body = document_body(text, fmt)
    contexts = section_contexts(body, fmt)
    if fmt == "tex":
        spans = tex_object_spans(body)
    elif fmt == "md":
        spans = markdown_object_spans(body)
    elif fmt == "txt":
        spans = txt_object_spans(body)
    else:
        raise MetricUnavailable(f"unsupported manuscript format: {fmt}")

    inventory: list[dict[str, Any]] = []
    occurrences: Counter[str] = Counter()
    for start, end, object_type in spans:
        canonical = canonical_block_text(body[start:end])
        if not canonical:
            continue
        content_hash = sha256_text(canonical)
        context = context_at(start, contexts)
        fingerprint = sha256_text(
            f"{region}\0{context['section_id']}\0{object_type}\0{content_hash}"
        )[:20]
        occurrences[fingerprint] += 1
        inventory.append(
            {
                "block_id": f"object-{fingerprint}-{occurrences[fingerprint]}",
                "inventory_kind": "substantive_object",
                "object_type": object_type,
                "content_sha256": content_hash,
                "section_id": context["section_id"],
                "section": context["section"],
                "normalized_section": context["normalized_section"],
                "region": region,
                "source_start": start,
                "source_end": end,
                "raw_source_words": raw_source_words(canonical),
                "normalized_words": normalized_words(canonical, fmt),
                "labels": native_labels(canonical, fmt),
            }
        )
    return inventory


def ledger_values(contract: dict[str, Any]) -> list[dict[str, Any]]:
    raw_values: list[Any] = []
    for key in ("content_conservation_ledger", "baseline_to_candidate"):
        if contract.get(key) not in (None, ""):
            raw_values.append(contract[key])
    ledgers = contract.get("ledgers")
    if isinstance(ledgers, dict):
        for key in ("content_conservation_ledger", "baseline_to_candidate"):
            if ledgers.get(key) not in (None, ""):
                raw_values.append(ledgers[key])
    deduplicated: list[Any] = []
    seen_raw: set[str] = set()
    for raw in raw_values:
        fingerprint = json.dumps(
            raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        if fingerprint not in seen_raw:
            seen_raw.add(fingerprint)
            deduplicated.append(raw)
    raw_values = deduplicated

    def flatten(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, list):
            output: list[dict[str, Any]] = []
            for item in value:
                output.extend(flatten(item))
            return output
        if not isinstance(value, dict):
            return []
        for wrapper in ("entries", "baseline_to_candidate", "content_conservation_ledger"):
            if wrapper in value:
                return flatten(value[wrapper])
        identifiers = {
            "source_block_id", "baseline_id", "source_id", "block_id", "disposition"
        }
        if identifiers & set(value):
            return [dict(value)]
        output = []
        for key, item in value.items():
            if isinstance(item, dict):
                record = dict(item)
                record.setdefault("source_block_id", str(key))
                output.append(record)
            elif isinstance(item, list):
                output.extend(flatten(item))
        return output

    records: list[dict[str, Any]] = []
    for raw in raw_values:
        records.extend(flatten(raw))
    return records


def record_source_id(entry: dict[str, Any]) -> str:
    value = (
        entry.get("source_block_id")
        or entry.get("baseline_id")
        or entry.get("source_id")
        or entry.get("block_id")
    )
    return str(value or "").strip()


def record_destination_id(entry: dict[str, Any]) -> str:
    value: Any = (
        entry.get("destination")
        or entry.get("candidate_block_id")
        or entry.get("candidate_id")
        or entry.get("destination_block_id")
    )
    if isinstance(value, dict):
        value = (
            value.get("block_id")
            or value.get("candidate_block_id")
            or value.get("candidate_id")
            or value.get("id")
        )
    return str(value or "").strip()


def scope_values(record: dict[str, Any]) -> set[str]:
    raw = record.get("approved_scope", record.get("scope", []))
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return set()
    return {str(item).strip().lower() for item in raw if str(item).strip()}


def authority_record(entry: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("authority", "authorization", "approval_record"):
        value = entry.get(key)
        if isinstance(value, dict):
            return value
    if (
        entry.get("authorized_by")
        or entry.get("authority_role")
        or entry.get("approval_authority")
    ):
        return {
            "role": (
                entry.get("approval_authority")
                or entry.get("authority_role")
                or entry.get("authorized_by")
            ),
            "by": entry.get("authorized_by") or entry.get("approved_by"),
            "at": entry.get("authorized_at") or entry.get("approved_at"),
            "approval_source": entry.get("approval_source"),
        }
    return None


def valid_controller_or_author_authority(entry: dict[str, Any]) -> bool:
    record = authority_record(entry)
    if not isinstance(record, dict):
        return False
    role = str(
        record.get("role")
        or record.get("approval_authority")
        or record.get("authority_role")
        or record.get("approved_by")
        or ""
    ).strip().lower()
    actor = str(
        record.get("by")
        or record.get("authorized_by")
        or record.get("approved_by")
        or ""
    ).strip()
    at = record.get("at") or record.get("authorized_at") or record.get("approved_at")
    if role not in {"author", "controller", "recorded_human_delegate"} or not (
        actor and valid_iso_timestamp(at)
    ):
        return False
    if role in {"author", "recorded_human_delegate"}:
        return nonempty_approval_source(record.get("approval_source"))
    return True


def author_action_approved(
    entry: dict[str, Any],
    contract: dict[str, Any],
    action: str,
    source: dict[str, Any],
) -> bool:
    records: list[dict[str, Any]] = []
    for value in (
        entry.get("author_approval"),
        entry.get("approval_record"),
        contract.get("approval_record"),
    ):
        if isinstance(value, dict):
            records.append(value)
    action_aliases = {action}
    if action == "deleted":
        action_aliases.add("delete")
    if action == "moved_appendix":
        action_aliases.update({"move_appendix", "moved_to_appendix"})
    required_scopes = {
        f"{scope_action}:{value}".lower()
        for scope_action in action_aliases
        for value in (
            source["block_id"],
            source["section"],
            source["normalized_section"],
        )
    }
    for record in records:
        if not valid_author_approval_record(record):
            continue
        scopes = scope_values(record)
        if scopes & required_scopes:
            return True
    return False


def valid_block_sufficiency_review(
    entry: dict[str, Any],
    source_id: str,
    destination_id: str,
    candidate_expanded_sha256: str,
) -> bool:
    review = entry.get("main_text_sufficiency_review")
    if not isinstance(review, dict):
        return False
    role = normalize_identifier(str(review.get("role") or ""))
    verdict = str(review.get("verdict") or review.get("status") or "").strip().lower()
    return bool(
        role == "main text sufficiency and conservation"
        and verdict == "pass"
        and str(review.get("reviewer_id") or "").strip()
        and valid_iso_timestamp(review.get("reviewed_at"))
        and str(review.get("source_block_id") or "").strip() == source_id
        and str(review.get("destination_block_id") or "").strip()
        == destination_id
        and normalized_sha256(review.get("candidate_expanded_sha256"))
        == candidate_expanded_sha256
    )


VALID_DISPOSITIONS = {
    "unchanged",
    "retained",
    "revised",
    "reordered",
    "merged",
    "renamed",
    "moved_appendix",
    "deleted",
}
AUTHORITY_DISPOSITIONS = {"revised", "reordered", "merged", "renamed"}
DISPOSITION_ALIASES = {
    "delete": "deleted",
    "move_appendix": "moved_appendix",
    "moved_to_appendix": "moved_appendix",
    "preserved": "unchanged",
}


def validate_conservation_ledger(
    contract: dict[str, Any],
    baseline_inventory: list[dict[str, Any]],
    candidate_inventory: list[dict[str, Any]],
    required: bool,
    candidate_expanded_sha256: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    entries = ledger_values(contract)
    failures: list[str] = []
    raw_ledger_values: list[Any] = [
        contract.get(key)
        for key in ("content_conservation_ledger", "baseline_to_candidate")
        if contract.get(key) not in (None, "")
    ]
    nested_ledgers = contract.get("ledgers")
    if isinstance(nested_ledgers, dict):
        raw_ledger_values.extend(
            nested_ledgers.get(key)
            for key in ("content_conservation_ledger", "baseline_to_candidate")
            if nested_ledgers.get(key) not in (None, "")
        )
    if any(not isinstance(value, (list, dict)) for value in raw_ledger_values):
        failures.append("conservation ledger must be a list or object")
    ledger_fingerprints = {
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        for value in raw_ledger_values
        if isinstance(value, (list, dict))
    }
    if len(ledger_fingerprints) > 1:
        failures.append("conflicting conservation ledger aliases")
    if required and not baseline_inventory:
        failures.append("required baseline substantive block inventory is empty")
    baseline_by_id = {item["block_id"]: item for item in baseline_inventory}
    candidate_by_id = {item["block_id"]: item for item in candidate_inventory}
    entries_by_source: dict[str, list[dict[str, Any]]] = {}
    validations: list[dict[str, Any]] = []

    for entry in entries:
        source_id = record_source_id(entry)
        if not source_id:
            failures.append("conservation ledger entry lacks source_block_id")
            continue
        entries_by_source.setdefault(source_id, []).append(entry)

    for source_id, matches in entries_by_source.items():
        if source_id not in baseline_by_id:
            failures.append(f"conservation ledger references unknown baseline block: {source_id}")
        if len(matches) != 1:
            failures.append(
                f"baseline block must have exactly one ledger disposition: {source_id}; found {len(matches)}"
            )

    if required:
        for source_id in baseline_by_id:
            count = len(entries_by_source.get(source_id, []))
            if count != 1:
                failures.append(
                    f"baseline block must have exactly one ledger disposition: {source_id}; found {count}"
                )

    normalized_by_source: dict[str, dict[str, Any]] = {}
    destination_uses: dict[str, list[tuple[str, str]]] = {}
    for source_id, matches in entries_by_source.items():
        if len(matches) != 1 or source_id not in baseline_by_id:
            continue
        entry = matches[0]
        source = baseline_by_id[source_id]
        raw_disposition = str(entry.get("disposition", "")).strip().lower()
        disposition = DISPOSITION_ALIASES.get(raw_disposition, raw_disposition)
        destination_id = record_destination_id(entry)
        status = "pass"
        reasons: list[str] = []
        if disposition not in VALID_DISPOSITIONS:
            reasons.append(f"invalid disposition {disposition!r}")
        destination = candidate_by_id.get(destination_id) if destination_id else None
        local_word_reduction: float | None = None
        if disposition not in {"deleted"}:
            if not destination_id:
                reasons.append("nonempty candidate destination is required")
            elif destination is None:
                reasons.append(f"candidate destination is not verifiable: {destination_id}")
        elif destination_id:
            reasons.append("deleted disposition must not name a candidate destination")

        if destination is not None:
            destination_uses.setdefault(destination_id, []).append((source_id, disposition))
            source_kind = source.get("inventory_kind", "prose_block")
            destination_kind = destination.get("inventory_kind", "prose_block")
            if source_kind != destination_kind:
                reasons.append(
                    "candidate destination must have the same inventory kind as the source"
                )
            if (
                source_kind == "substantive_object"
                and source.get("object_type") != destination.get("object_type")
            ):
                reasons.append(
                    "candidate destination must have the same substantive object type"
                )
            if disposition == "moved_appendix":
                if source["region"] != "main_text" or destination["region"] != "appendix":
                    reasons.append("moved_appendix must map main_text to appendix")
            elif destination["region"] != source["region"]:
                reasons.append(
                    "only moved_appendix may change a block's main-text/appendix region"
                )
            if disposition in {
                "unchanged",
                "retained",
                "reordered",
                "renamed",
                "moved_appendix",
            } and (
                source["content_sha256"] != destination["content_sha256"]
            ):
                reasons.append(f"{disposition} destination content hash does not match source")
            if disposition in {"unchanged", "retained"} and (
                source["section_id"] != destination["section_id"]
            ):
                reasons.append(
                    f"{disposition} cannot move content to a different section; use reordered or renamed with authority"
                )
            local_word_reduction = reduction_pct(
                float(source.get("normalized_words") or 0),
                float(destination.get("normalized_words") or 0),
            )

        if disposition in {"revised", "merged"}:
            source_function = str(entry.get("source_function") or "").strip()
            reason = str(entry.get("reason") or "").strip()
            retained_evidence = str(
                entry.get("retained_meaning_evidence")
                or entry.get("meaning_conservation_evidence")
                or entry.get("retained_meaning")
                or ""
            ).strip()
            if not source_function:
                reasons.append(f"{disposition} requires source_function")
            if not reason:
                reasons.append(f"{disposition} requires reason")
            if not retained_evidence:
                reasons.append(
                    f"{disposition} requires retained_meaning_evidence"
                )
            if "omitted_elements" not in entry:
                reasons.append(f"{disposition} requires omitted_elements evidence")
            independent_review_required = bool(
                source.get("inventory_kind") == "substantive_object"
                or (
                    local_word_reduction is not None
                    and local_word_reduction > 0.50
                )
            )
            if independent_review_required and not valid_block_sufficiency_review(
                    entry,
                    source_id,
                    destination_id,
                    candidate_expanded_sha256,
                ):
                review_reason = (
                    f"local word reduction {local_word_reduction:.1%} exceeds 50%"
                    if local_word_reduction is not None
                    and local_word_reduction > 0.50
                    else "substantive object content changed"
                )
                reasons.append(
                    f"{disposition} {review_reason}; "
                    "a current-hash Main-Text Sufficiency and Conservation review is required"
                )

        if disposition in AUTHORITY_DISPOSITIONS and not valid_controller_or_author_authority(entry):
            reasons.append(
                f"{disposition} requires dated controller or author authority"
            )
        if disposition in {"deleted", "moved_appendix"} and not author_action_approved(
            entry, contract, disposition, source
        ):
            reasons.append(
                f"{disposition} requires action-specific dated author approval"
            )
        recorded_status = str(entry.get("status", "")).strip().lower()
        if recorded_status in {"fail", "failed", "pending", "uncertain", "rejected"}:
            reasons.append(f"ledger status is not accepted: {recorded_status}")
        if reasons:
            status = "fail"
            for reason in reasons:
                failures.append(f"ledger {source_id}: {reason}")
        normalized = {
            "source_block_id": source_id,
            "destination_block_id": destination_id or None,
            "disposition": disposition or None,
            "status": status,
            "reasons": reasons,
            "local_word_reduction_pct": local_word_reduction,
        }
        validations.append(normalized)
        normalized_by_source[source_id] = normalized

    for destination_id, uses in destination_uses.items():
        if len(uses) <= 1:
            continue
        dispositions = {disposition for _, disposition in uses}
        if dispositions not in ({"merged"}, {"moved_appendix"}):
            sources = ", ".join(source_id for source_id, _ in uses)
            failures.append(
                f"candidate destination {destination_id} is reused by non-merged mappings: {sources}"
            )

    return validations, normalized_by_source, failures


def ordered_main_inventory(
    inventory: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return a deterministic live-source order for main-text inventory items."""

    kind_rank = {"prose_block": 0, "substantive_object": 1}
    return sorted(
        (item for item in inventory if item.get("region") == "main_text"),
        key=lambda item: (
            int(item.get("source_start") or 0),
            int(item.get("source_end") or 0),
            kind_rank.get(str(item.get("inventory_kind")), 9),
            str(item.get("block_id") or ""),
        ),
    )


def patch_order_conservation_check(
    baseline_inventory: list[dict[str, Any]],
    candidate_inventory: list[dict[str, Any]],
    ledger_by_source: dict[str, dict[str, Any]],
    rewrite_mode: str | None,
    scope: str,
    source_filter: set[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Reject relative-order inversions among validated main-to-main mappings."""

    if rewrite_mode != "patch_existing":
        return (
            {
                "required": False,
                "status": "not_applicable",
                "scope": scope,
                "rewrite_mode": rewrite_mode,
                "new_unmapped_blocks_ignored": True,
            },
            [],
        )

    baseline_order = ordered_main_inventory(baseline_inventory)
    candidate_order = ordered_main_inventory(candidate_inventory)
    baseline_rank = {
        item["block_id"]: index for index, item in enumerate(baseline_order)
    }
    candidate_rank = {
        item["block_id"]: index for index, item in enumerate(candidate_order)
    }
    baseline_by_id = {item["block_id"]: item for item in baseline_order}
    candidate_by_id = {item["block_id"]: item for item in candidate_order}

    mappings: list[dict[str, Any]] = []
    for source_id, source_position in baseline_rank.items():
        if source_filter is not None and source_id not in source_filter:
            continue
        record = ledger_by_source.get(source_id)
        if not isinstance(record, dict) or record.get("status") != "pass":
            continue
        destination_id = str(record.get("destination_block_id") or "").strip()
        if destination_id not in candidate_rank:
            continue
        source = baseline_by_id[source_id]
        destination = candidate_by_id[destination_id]
        mappings.append(
            {
                "source_block_id": source_id,
                "source_rank": source_position,
                "source_section": source.get("section"),
                "destination_block_id": destination_id,
                "destination_rank": candidate_rank[destination_id],
                "destination_section": destination.get("section"),
                "disposition": record.get("disposition"),
            }
        )
    mappings.sort(key=lambda item: (item["source_rank"], item["source_block_id"]))

    inversions: list[dict[str, Any]] = []
    maximum_destination_rank = -1
    maximum_mapping: dict[str, Any] | None = None
    for mapping in mappings:
        destination_position = int(mapping["destination_rank"])
        if (
            maximum_mapping is not None
            and destination_position < maximum_destination_rank
        ):
            inversion = {
                "earlier_source_block_id": maximum_mapping["source_block_id"],
                "earlier_source_section": maximum_mapping["source_section"],
                "earlier_destination_block_id": maximum_mapping[
                    "destination_block_id"
                ],
                "earlier_destination_section": maximum_mapping[
                    "destination_section"
                ],
                "later_source_block_id": mapping["source_block_id"],
                "later_source_section": mapping["source_section"],
                "later_destination_block_id": mapping["destination_block_id"],
                "later_destination_section": mapping["destination_section"],
            }
            inversions.append(inversion)
        if destination_position > maximum_destination_rank:
            maximum_destination_rank = destination_position
            maximum_mapping = mapping

    failures = [
        f"{scope} patch_existing relative-order inversion: "
        f"{item['earlier_source_block_id']} before {item['later_source_block_id']} "
        "in the baseline, but their validated main-text destinations are reversed"
        for item in inversions
    ]
    return (
        {
            "required": True,
            "status": "fail" if inversions else "pass",
            "scope": scope,
            "rewrite_mode": rewrite_mode,
            "mapped_main_text_block_count": len(mappings),
            "new_unmapped_blocks_ignored": True,
            "inversions": inversions,
        },
        failures,
    )


def validate_two_pass_restructure(
    contract: dict[str, Any],
    contract_path: Path | None,
    project_root: Path,
    appendix_marker: str,
    baseline_inventory: list[dict[str, Any]],
    candidate_inventory: list[dict[str, Any]],
    candidate_text: str,
    candidate_format: str,
) -> tuple[dict[str, Any], list[str]]:
    """Verify a hash-bound architecture pass before any compression pass."""

    raw = contract.get("two_pass_restructure")
    if not isinstance(raw, dict):
        return {"required": True, "status": "fail"}, [
            "restructure requires a hash-bound two_pass_restructure record"
        ]
    failures: list[str] = []
    architecture = raw.get("architecture_pass")
    compression = raw.get("compression_pass")
    if not isinstance(architecture, dict):
        return {"required": True, "status": "fail"}, [
            "two_pass_restructure.architecture_pass must be an object"
        ]
    if not isinstance(compression, dict):
        return {"required": True, "status": "fail"}, [
            "two_pass_restructure.compression_pass must be an object"
        ]

    architecture_mode = str(architecture.get("mode") or "").strip().lower()
    architecture_status = str(architecture.get("status") or "").strip().lower()
    if architecture_mode != "reorder_existing_blocks":
        failures.append(
            "two-pass architecture_pass.mode must be reorder_existing_blocks"
        )
    if architecture_status not in {"completed", "pass"}:
        failures.append("two-pass architecture_pass.status must be completed")
    if not str(architecture.get("completed_by") or "").strip() or not valid_iso_timestamp(
        architecture.get("completed_at")
    ):
        failures.append(
            "two-pass architecture_pass requires completed_by and ISO-8601 completed_at with timezone"
        )

    raw_path = str(architecture.get("artifact_path") or "").strip()
    expected_file_hash = normalized_sha256(architecture.get("artifact_sha256"))
    expected_expanded_hash = normalized_sha256(
        architecture.get("expanded_sha256")
    )
    architecture_path: Path | None = None
    architecture_text: str | None = None
    architecture_format: str | None = None
    architecture_inventory: list[dict[str, Any]] = []
    architecture_ledger_hash: str | None = None
    architecture_ledger_status: str | None = None
    compression_ledger_hash: str | None = None
    compression_ledger_status: str | None = None
    if not raw_path:
        failures.append("two-pass architecture_pass.artifact_path is required")
    else:
        architecture_path = resolve_contract_path(
            raw_path, contract_path, project_root
        )
        if not architecture_path.is_file():
            failures.append(
                f"two-pass architecture artifact is missing: {architecture_path}"
            )
        else:
            if not re.fullmatch(r"[0-9a-f]{64}", expected_file_hash):
                failures.append(
                    "two-pass architecture_pass.artifact_sha256 is invalid"
                )
            elif sha256_file(architecture_path) != expected_file_hash:
                failures.append("two-pass architecture artifact SHA-256 is stale")
            architecture_text, _, architecture_format = load_manuscript(
                architecture_path, project_root
            )
            live_expanded_hash = sha256_text(architecture_text)
            if not re.fullmatch(r"[0-9a-f]{64}", expected_expanded_hash):
                failures.append(
                    "two-pass architecture_pass.expanded_sha256 is invalid"
                )
            elif live_expanded_hash != expected_expanded_hash:
                failures.append(
                    "two-pass architecture artifact expanded SHA-256 is stale"
                )
            if architecture_format != candidate_format:
                failures.append(
                    "two-pass architecture artifact format must match candidate format"
                )
            architecture_main, architecture_appendix = split_appendix(
                architecture_text,
                appendix_marker,
                "two-pass architecture artifact",
                architecture_format,
            )
            architecture_inventory = substantive_block_inventory(
                architecture_main, "main_text", architecture_format
            ) + substantive_block_inventory(
                architecture_appendix, "appendix", architecture_format
            ) + substantive_object_inventory(
                architecture_main, "main_text", architecture_format
            ) + substantive_object_inventory(
                architecture_appendix, "appendix", architecture_format
            )
            architecture_ledger = architecture.get(
                "content_conservation_ledger"
            )
            architecture_ledger_hash = sha256_text(
                json.dumps(
                    architecture_ledger,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            architecture_contract = {
                "content_conservation_ledger": architecture_ledger
            }
            (
                architecture_ledger_validation,
                _,
                architecture_ledger_failures,
            ) = validate_conservation_ledger(
                architecture_contract,
                baseline_inventory,
                architecture_inventory,
                True,
                live_expanded_hash,
            )
            failures.extend(
                f"two-pass architecture ledger: {item}"
                for item in architecture_ledger_failures
            )
            architecture_ledger_status = (
                "fail" if architecture_ledger_failures else "pass"
            )
            safe_architecture_dispositions = {
                "unchanged",
                "retained",
                "reordered",
                "renamed",
            }
            for item in architecture_ledger_validation:
                if item.get("disposition") not in safe_architecture_dispositions:
                    architecture_ledger_status = "fail"
                    failures.append(
                        "two-pass architecture ledger may only preserve or reorder exact "
                        f"content; {item.get('source_block_id')} uses "
                        f"{item.get('disposition')}"
                    )

    compression_mode = str(compression.get("mode") or "").strip().lower()
    compression_status = str(compression.get("status") or "").strip().lower()
    if compression_mode not in {"none", "limited_compression"}:
        failures.append(
            "two-pass compression_pass.mode must be none or limited_compression"
        )
    accepted_statuses = (
        {"not_needed", "completed", "pass"}
        if compression_mode == "none"
        else {"completed", "pass"}
    )
    if compression_status not in accepted_statuses:
        failures.append("two-pass compression_pass.status is invalid")
    if not str(compression.get("completed_by") or "").strip() or not valid_iso_timestamp(
        compression.get("completed_at")
    ):
        failures.append(
            "two-pass compression_pass requires completed_by and ISO-8601 completed_at with timezone"
        )
    recorded_source_hash = normalized_sha256(
        compression.get("source_expanded_sha256")
    )
    recorded_candidate_hash = normalized_sha256(
        compression.get("candidate_expanded_sha256")
    )
    current_candidate_hash = sha256_text(candidate_text)
    if recorded_source_hash != expected_expanded_hash:
        failures.append(
            "two-pass compression source hash must equal the architecture expanded hash"
        )
    if recorded_candidate_hash != current_candidate_hash:
        failures.append(
            "two-pass compression candidate hash must equal the audited candidate expansion"
        )
    if compression_mode == "none":
        if expected_expanded_hash != current_candidate_hash:
            failures.append(
                "two-pass compression mode none requires architecture and candidate hashes to match"
            )
    elif architecture_inventory:
        if not nonempty_requirement(
            compression.get("approved_scope") or compression.get("scope")
        ):
            failures.append(
                "limited_compression requires a nonempty approved_scope"
            )
        compression_ledger = compression.get("content_conservation_ledger")
        compression_ledger_hash = sha256_text(
            json.dumps(
                compression_ledger,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        compression_contract = {
            "content_conservation_ledger": compression_ledger
        }
        _, _, compression_ledger_failures = validate_conservation_ledger(
            compression_contract,
            architecture_inventory,
            candidate_inventory,
            True,
            current_candidate_hash,
        )
        failures.extend(
            f"two-pass compression ledger: {item}"
            for item in compression_ledger_failures
        )
        compression_ledger_status = (
            "fail" if compression_ledger_failures else "pass"
        )
    elif compression_mode == "none":
        compression_ledger_status = "not_applicable"

    return (
        {
            "required": True,
            "status": "fail" if failures else "pass",
            "architecture_mode": architecture_mode or None,
            "architecture_artifact": (
                str(architecture_path) if architecture_path is not None else None
            ),
            "architecture_expanded_sha256": expected_expanded_hash or None,
            "architecture_inventory_count": len(architecture_inventory),
            "architecture_ledger_sha256": architecture_ledger_hash,
            "architecture_ledger_status": architecture_ledger_status,
            "compression_mode": compression_mode or None,
            "compression_approved_scope": (
                compression.get("approved_scope") or compression.get("scope")
            ),
            "compression_ledger_sha256": compression_ledger_hash,
            "compression_ledger_status": compression_ledger_status,
            "candidate_expanded_sha256": sha256_text(candidate_text),
        },
        failures,
    )


def contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return key in value or any(contains_key(item, key) for item in value.values())
    if isinstance(value, list):
        return any(contains_key(item, key) for item in value)
    return False


def resolve_attested_file(raw: str, contract_path: Path | None, project_root: Path) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        resolved = path.resolve()
    else:
        bases = [contract_path.parent] if contract_path is not None else []
        if project_root not in bases:
            bases.append(project_root)
        candidates = [(base / path).resolve() for base in bases]
        existing = [item for item in candidates if item.is_file()]
        if len({str(item) for item in existing}) > 1:
            raise MetricUnavailable(f"ambiguous attested PDF path: {raw}")
        resolved = existing[0] if existing else candidates[0]
    ensure_within_root(resolved, project_root)
    if not resolved.is_file():
        raise MetricUnavailable(f"attested PDF not found: {resolved}")
    return resolved


def validate_page_attestation(
    args: argparse.Namespace,
    contract: dict[str, Any],
    contract_path: Path | None,
    project_root: Path,
    baseline_present: bool,
    page_constraints_active: bool,
) -> tuple[float | None, float | None, dict[str, Any] | None]:
    if not page_constraints_active:
        return None, None, None
    measurement = contract.get("measurement_contract")
    if not isinstance(measurement, dict):
        raise MetricUnavailable(
            "page metrics require artifact_contract.measurement_contract"
        )
    if contains_key(measurement, "total_pdf_pages"):
        raise MetricUnavailable("total_pdf_pages is not a valid main-text page metric")
    method = str(measurement.get("pdf_main_page_method", "")).strip()
    method_key = normalize_identifier(method)
    if not method or "total" in method_key or not (
        "main text" in method_key or "before appendix" in method_key
    ):
        raise MetricUnavailable(
            "pdf_main_page_method must attest a main-text-only or pages-before-appendix method"
        )
    boundary = measurement.get("appendix_boundary")
    if isinstance(boundary, dict):
        boundary = boundary.get("marker") or boundary.get("value")
    if str(boundary or "").strip() != args.appendix_marker:
        raise MetricUnavailable(
            "measurement_contract appendix_boundary must match --appendix-marker"
        )
    attestations = measurement.get("attested_main_text_pages")
    if not isinstance(attestations, dict):
        raise MetricUnavailable(
            "page metrics require measurement_contract.attested_main_text_pages"
        )
    measured_by = str(
        measurement.get("measured_by") or attestations.get("measured_by") or ""
    ).strip()
    measured_at = str(
        measurement.get("measured_at") or attestations.get("measured_at") or ""
    ).strip()
    if not measured_by or not valid_iso_timestamp(measured_at):
        raise MetricUnavailable(
            "page attestation requires measured_by and ISO-8601 measured_at with timezone"
        )

    required_names = ["candidate"]
    if baseline_present:
        required_names.insert(0, "baseline")
    verified: dict[str, Any] = {
        "measured_by": measured_by,
        "measured_at": measured_at,
        "pdf_main_page_method": method,
        "appendix_boundary": str(boundary),
    }
    page_values: dict[str, float] = {}
    cli_values = {
        "baseline": number(args.baseline_main_pdf_pages),
        "candidate": number(args.candidate_main_pdf_pages),
    }
    for name in required_names:
        record = attestations.get(name)
        if not isinstance(record, dict):
            raise MetricUnavailable(f"missing {name} main-text page attestation")
        pages = number(record.get("pages"))
        raw_path = str(record.get("pdf_path", "")).strip()
        expected_hash = str(record.get("pdf_sha256", "")).strip().lower()
        if pages is None or pages <= 0 or not raw_path or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise MetricUnavailable(
                f"{name} page attestation requires positive pages, pdf_path, and SHA-256"
            )
        pdf_path = resolve_attested_file(raw_path, contract_path, project_root)
        actual_hash = sha256_file(pdf_path)
        if actual_hash != expected_hash:
            raise MetricUnavailable(
                f"{name} attested PDF hash is stale: expected {expected_hash}, got {actual_hash}"
            )
        if cli_values[name] is not None and cli_values[name] != pages:
            raise MetricUnavailable(
                f"--{name}-main-pdf-pages does not match attested_main_text_pages"
            )
        page_values[name] = pages
        verified[name] = {
            "pages": pages,
            "pdf_path": str(pdf_path),
            "pdf_sha256": actual_hash,
        }
    if not baseline_present and cli_values["baseline"] is not None:
        raise MetricUnavailable("--baseline-main-pdf-pages requires --baseline")
    return page_values.get("baseline"), page_values.get("candidate"), verified


def nonempty_requirement(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(
            str(value.get(key) or "").strip()
            for key in ("value", "id", "content", "label", "section")
        )
    if isinstance(value, (list, tuple, set)):
        return any(nonempty_requirement(item) for item in value)
    return False


def nonempty_questions(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set)):
        return any(isinstance(item, str) and item.strip() for item in value)
    return False


def nonempty_obligations(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return any(nonempty_obligations(item) for item in value)
    if isinstance(value, dict):
        if any(
            str(value.get(key) or "").strip()
            for key in ("content", "must_express", "text", "description")
        ):
            return True
        return any(nonempty_obligations(item) for item in value.values())
    return False


def candidate_only_full_draft_contract_check(
    contract: dict[str, Any],
    candidate_sections: list[dict[str, Any]],
    target_words: tuple[float, float] | None,
    target_pages: tuple[float, float] | None,
    verified_page_attestation: dict[str, Any] | None,
    metric_name: str,
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    page_target_verified = bool(
        target_pages is not None
        and isinstance(verified_page_attestation, dict)
        and isinstance(verified_page_attestation.get("candidate"), dict)
    )
    if target_words is None and not page_target_verified:
        failures.append(
            "candidate-only full_draft requires a source-word target range or verified main-text page target range"
        )

    raw_cards = contract.get("section_cards")
    cards: list[dict[str, Any]] = []
    if isinstance(raw_cards, list):
        cards = [dict(item) for item in raw_cards if isinstance(item, dict)]
        if len(cards) != len(raw_cards):
            failures.append("section_cards entries must be objects")
    elif isinstance(raw_cards, dict):
        for key, value in raw_cards.items():
            if not isinstance(value, dict):
                failures.append("section_cards entries must be objects")
                continue
            card = dict(value)
            card.setdefault("card_id", str(key))
            cards.append(card)
    else:
        failures.append("candidate-only full_draft requires nonempty section_cards")
    if not cards and isinstance(raw_cards, (list, dict)):
        failures.append("candidate-only full_draft requires nonempty section_cards")

    card_names: set[str] = set()
    card_ids: set[str] = set()
    card_labels: list[str] = []
    required_card_names: set[str] = set()
    card_ranges: dict[str, tuple[float, float]] = {}
    authority = section_card_authority_context(contract, failures)
    authority_checks: list[dict[str, Any]] = []
    for index, card in enumerate(cards, 1):
        label = section_card_identity(
            card, index, failures, "candidate-only section"
        )
        card_labels.append(label)
        if label in card_ids:
            failures.append(f"duplicate candidate-only section card_id: {label}")
        card_ids.add(label)
        authority_checks.append(
            section_card_authority_override_check(
                card, label, authority, failures
            )
        )
        section_name = str(
            card.get("section_name")
            or card.get("section_title")
            or card.get("title")
            or ""
        ).strip()
        if not section_name:
            failures.append(f"section card {label} requires section_name")
        else:
            normalized_name = normalize_identifier(section_name)
            if normalized_name in card_names:
                failures.append(f"duplicate section card name: {section_name}")
            card_names.add(normalized_name)
            if card.get("optional") is not True:
                required_card_names.add(normalized_name)
        card_range = range_pair(
            card.get("target_word_range")
            or card.get("target_main_source_word_range")
        )
        if card_range is None:
            failures.append(
                f"section card {label} requires a valid nonnegative target_word_range"
            )
        elif section_name:
            card_ranges[normalize_identifier(section_name)] = card_range
        if not nonempty_requirement(card.get("must_remain_main")):
            failures.append(f"section card {label} requires nonempty must_remain_main")
        if not nonempty_questions(card.get("minimum_depth_questions")):
            failures.append(
                f"section card {label} requires nonempty minimum_depth_questions"
            )

    candidate_names = {
        section["normalized_title"] for section in candidate_sections
    }
    for name in sorted(candidate_names - card_names):
        failures.append(f"candidate main-text section lacks a section card: {name}")
    for name in sorted(required_card_names - candidate_names):
        failures.append(f"required section card is missing from candidate main text: {name}")
    section_budget_checks: list[dict[str, Any]] = []
    for section in candidate_sections:
        name = section["normalized_title"]
        card_range = card_ranges.get(name)
        if card_range is None:
            continue
        observed = float(section[metric_name])
        passed = card_range[0] <= observed <= card_range[1]
        section_budget_checks.append(
            {
                "section": name,
                "word_metric": metric_name,
                "observed": observed,
                "target_word_range": [card_range[0], card_range[1]],
                "status": "pass" if passed else "fail",
            }
        )
        if not passed:
            failures.append(
                f"candidate section {name} {metric_name} {observed:.0f} is outside section-card target range "
                f"[{card_range[0]:.0f}, {card_range[1]:.0f}]"
            )

    obligations = contract.get("content_obligations")
    if not nonempty_obligations(obligations):
        failures.append(
            "candidate-only full_draft requires nonempty content_obligations"
        )
    obligation_ids: set[str] = set()
    if isinstance(obligations, list):
        for item in obligations:
            if isinstance(item, dict):
                identifier = (
                    item.get("obligation_id")
                    or item.get("intent_id")
                    or item.get("id")
                )
                if identifier:
                    obligation_ids.add(str(identifier).strip())
    elif isinstance(obligations, dict):
        obligation_ids.update(str(key).strip() for key in obligations if str(key).strip())
        for item in obligations.values():
            if isinstance(item, dict):
                identifier = (
                    item.get("obligation_id")
                    or item.get("intent_id")
                    or item.get("id")
                )
                if identifier:
                    obligation_ids.add(str(identifier).strip())

    candidate_labels = {
        label for section in candidate_sections for label in section.get("labels", [])
    }
    must_remain_reference_checks: list[dict[str, Any]] = []
    for card, label in zip(cards, card_labels):
        section_name = str(
            card.get("section_name")
            or card.get("section_title")
            or card.get("title")
            or ""
        ).strip()
        normalized_name = normalize_identifier(section_name)
        if card.get("optional") is True and normalized_name not in candidate_names:
            continue
        raw_requirements = card.get("must_remain_main")
        requirements = (
            raw_requirements
            if isinstance(raw_requirements, list)
            else [raw_requirements]
        )
        for requirement in requirements:
            kind = "either"
            value = ""
            if isinstance(requirement, dict):
                kind = str(requirement.get("type") or "either").strip().lower()
                value = str(
                    requirement.get("value")
                    or requirement.get("obligation_id")
                    or requirement.get("intent_id")
                    or requirement.get("id")
                    or ""
                ).strip()
            elif isinstance(requirement, str):
                value = requirement.strip()
            verified = False
            if kind in {"section", "title", "either"} and normalize_identifier(value) in candidate_names:
                verified = True
            if kind in {"label", "either"} and value in candidate_labels:
                verified = True
            if kind in {"obligation", "obligation_id", "intent", "intent_id", "either"} and value in obligation_ids:
                verified = True
            must_remain_reference_checks.append(
                {
                    "section_card": label,
                    "kind": kind,
                    "value": value,
                    "status": "verified_reference" if verified else "unverifiable",
                }
            )
            if not verified:
                failures.append(
                    f"section card {label} has unverifiable must_remain_main reference: {value or '<empty>'}"
                )
    obligation_count = (
        len(obligations)
        if isinstance(obligations, (list, tuple, set, dict))
        else (1 if isinstance(obligations, str) and obligations.strip() else 0)
    )
    return (
        {
            "required": True,
            "status": "fail" if failures else "pass",
            "global_target_kind": (
                "source_words"
                if target_words is not None
                else ("verified_main_text_pages" if page_target_verified else None)
            ),
            "section_card_count": len(cards),
            "content_obligation_count": obligation_count,
            "candidate_section_names": sorted(candidate_names),
            "card_section_names": sorted(card_names),
            "required_card_section_names": sorted(required_card_names),
            "section_budget_checks": section_budget_checks,
            "must_remain_reference_checks": must_remain_reference_checks,
            "section_authority_checks": authority_checks,
            "contract_check_scope": "deterministic contract completeness and reference existence only",
            "minimum_depth_questions_semantically_verified": False,
            "requires_main_text_sufficiency_role": True,
        },
        failures,
    )


def section_card_identity(
    card: dict[str, Any],
    index: int,
    failures: list[str],
    context: str,
) -> str:
    """Return the canonical card ID without treating it as a manuscript ID."""

    canonical_raw = card.get("card_id")
    legacy_raw = card.get("section_id")
    canonical = canonical_raw.strip() if isinstance(canonical_raw, str) else ""
    legacy = legacy_raw.strip() if isinstance(legacy_raw, str) else ""
    if canonical_raw is not None and not canonical:
        failures.append(f"{context} card {index} has an invalid card_id")
    if legacy_raw is not None and not legacy:
        failures.append(f"{context} card {index} has an invalid legacy section_id")
    if canonical and legacy and canonical != legacy:
        failures.append(
            f"{context} card {index} has conflicting card_id and legacy section_id"
        )
    card_id = canonical or legacy
    if not card_id:
        failures.append(
            f"{context} card {index} requires card_id; section_id is only a legacy card-ID alias"
        )
        return f"invalid-card-{index}"
    return card_id


def normalized_appendix_move_set(
    value: Any,
    field: str,
    failures: list[str],
) -> set[str] | None:
    """Parse a closed appendix-move list using manuscript-ID normalization."""

    if not isinstance(value, list):
        failures.append(
            f"{field} must be a list of nonempty section titles or labels"
        )
        return None
    normalized: set[str] = set()
    valid = True
    for index, raw in enumerate(value, 1):
        if not isinstance(raw, str) or not raw.strip():
            failures.append(
                f"{field} entry {index} must be a nonempty section title or label"
            )
            valid = False
            continue
        item = normalize_identifier(raw)
        if not item:
            failures.append(
                f"{field} entry {index} has no valid normalized identifier"
            )
            valid = False
            continue
        if item in normalized:
            failures.append(
                f"{field} contains duplicate normalized entry: {item}"
            )
            valid = False
            continue
        normalized.add(item)
    return normalized if valid else None


def section_card_authority_context(
    contract: dict[str, Any],
    failures: list[str],
) -> dict[str, Any]:
    """Resolve artifact-wide bounds without turning declarations into approval."""

    moves_present = "allowed_appendix_moves" in contract
    moves = (
        normalized_appendix_move_set(
            contract.get("allowed_appendix_moves"),
            "artifact_contract.allowed_appendix_moves",
            failures,
        )
        if moves_present
        else set()
    )
    rewrite_present = "rewrite_mode" in contract
    raw_rewrite = contract.get("rewrite_mode")
    rewrite_mode = (
        raw_rewrite.strip().lower()
        if isinstance(raw_rewrite, str) and raw_rewrite.strip()
        else None
    )
    rewrite_valid = bool(
        not rewrite_present or rewrite_mode in REWRITE_MODE_AUTHORITY_RANK
    )
    return {
        "allowed_appendix_moves": moves,
        "allowed_appendix_moves_valid": moves is not None,
        "rewrite_mode": rewrite_mode,
        "rewrite_mode_present": rewrite_present,
        "rewrite_mode_valid": rewrite_valid,
    }


def section_card_authority_override_check(
    card: dict[str, Any],
    card_id: str,
    authority: dict[str, Any],
    failures: list[str],
) -> dict[str, Any]:
    """Require card authority to inherit or narrow the artifact-wide bounds."""

    failure_count_before = len(failures)
    top_moves = authority.get("allowed_appendix_moves")
    moves_override_present = "allowed_appendix_moves" in card
    moves_override_accepted = False
    if moves_override_present:
        card_moves = normalized_appendix_move_set(
            card.get("allowed_appendix_moves"),
            f"section card {card_id} allowed_appendix_moves",
            failures,
        )
        if card_moves is not None and isinstance(top_moves, set):
            extras = sorted(card_moves - top_moves)
            if extras:
                failures.append(
                    f"section card {card_id} allowed_appendix_moves exceeds "
                    "artifact-wide authority: " + ", ".join(extras)
                )
            else:
                moves_override_accepted = True
        elif card_moves is not None:
            failures.append(
                f"section card {card_id} allowed_appendix_moves cannot inherit "
                "an invalid artifact-wide authority"
            )
        effective_moves = card_moves if moves_override_accepted else None
    else:
        card_moves = None
        effective_moves = top_moves if isinstance(top_moves, set) else None

    top_rewrite = authority.get("rewrite_mode")
    rewrite_override_present = "rewrite_mode" in card
    rewrite_override_accepted = False
    if rewrite_override_present:
        raw_card_rewrite = card.get("rewrite_mode")
        card_rewrite = (
            raw_card_rewrite.strip().lower()
            if isinstance(raw_card_rewrite, str) and raw_card_rewrite.strip()
            else None
        )
        if card_rewrite not in REWRITE_MODE_AUTHORITY_RANK:
            failures.append(
                f"section card {card_id} rewrite_mode must be patch_existing, "
                "reorder_existing_blocks, or full_redraft"
            )
        elif (
            not authority.get("rewrite_mode_present")
            or not authority.get("rewrite_mode_valid")
            or top_rewrite not in REWRITE_MODE_AUTHORITY_RANK
        ):
            failures.append(
                f"section card {card_id} rewrite_mode cannot be supplied without "
                "a valid artifact_contract.rewrite_mode"
            )
        elif (
            REWRITE_MODE_AUTHORITY_RANK[card_rewrite]
            > REWRITE_MODE_AUTHORITY_RANK[top_rewrite]
        ):
            failures.append(
                f"section card {card_id} rewrite_mode {card_rewrite} exceeds "
                f"artifact-wide rewrite_mode {top_rewrite}"
            )
        else:
            rewrite_override_accepted = True
        effective_rewrite = card_rewrite if rewrite_override_accepted else None
    else:
        card_rewrite = None
        effective_rewrite = (
            top_rewrite if authority.get("rewrite_mode_valid") else None
        )

    inherited_authority_invalid = bool(
        not authority.get("allowed_appendix_moves_valid")
        or not authority.get("rewrite_mode_valid")
    )

    return {
        "card_id": card_id,
        "allowed_appendix_moves_source": (
            "card_narrow_override" if moves_override_present else "inherited"
        ),
        "declared_allowed_appendix_moves": (
            sorted(card_moves) if isinstance(card_moves, set) else None
        ),
        "allowed_appendix_moves_override_accepted": (
            moves_override_accepted if moves_override_present else None
        ),
        "effective_allowed_appendix_moves": (
            sorted(effective_moves) if isinstance(effective_moves, set) else None
        ),
        "rewrite_mode_source": (
            "card_narrow_override" if rewrite_override_present else "inherited"
        ),
        "declared_rewrite_mode": card_rewrite,
        "rewrite_mode_override_accepted": (
            rewrite_override_accepted if rewrite_override_present else None
        ),
        "effective_rewrite_mode": effective_rewrite,
        "author_approval_inferred": False,
        "status": (
            "fail"
            if inherited_authority_invalid or len(failures) > failure_count_before
            else "pass"
        ),
    }


def string_id_list(
    value: Any,
    field: str,
    card_id: str,
    failures: list[str],
) -> list[str] | None:
    if not isinstance(value, list) or not value:
        failures.append(
            f"section card {card_id} {field} must be a nonempty list of block IDs"
        )
        return None
    values: list[str] = []
    for raw in value:
        if not isinstance(raw, str) or not raw.strip():
            failures.append(
                f"section card {card_id} {field} must contain only nonempty string block IDs"
            )
            return None
        values.append(raw.strip())
    if len(values) != len(set(values)):
        failures.append(
            f"section card {card_id} {field} contains duplicate block IDs"
        )
        return None
    return values


def parse_ledger_slice(
    card: dict[str, Any],
    card_id: str,
    failures: list[str],
) -> tuple[bool, list[str], list[str] | None]:
    """Parse a closed ledger-slice schema; no supplied slice is ignored."""

    if "ledger_slice" not in card or card.get("ledger_slice") is None:
        return False, [], None
    raw = card.get("ledger_slice")
    if isinstance(raw, list):
        source_ids = string_id_list(
            raw, "ledger_slice", card_id, failures
        )
        return True, source_ids or [], None
    if not isinstance(raw, dict):
        failures.append(
            f"section card {card_id} ledger_slice must be a block-ID list or object"
        )
        return True, [], None

    source_keys = (
        "baseline_block_ids",
        "source_block_ids",
        "baseline_prose_block_ids",
    )
    destination_keys = (
        "destination_block_ids",
        "candidate_block_ids",
        "candidate_prose_block_ids",
    )
    unknown = sorted(set(raw) - set(source_keys) - set(destination_keys))
    if unknown:
        failures.append(
            f"section card {card_id} ledger_slice has unsupported fields: "
            + ", ".join(unknown)
        )

    def alias_value(keys: tuple[str, ...], label: str) -> list[str] | None:
        values: list[list[str]] = []
        for key in keys:
            if key not in raw:
                continue
            parsed = string_id_list(raw[key], f"ledger_slice.{key}", card_id, failures)
            if parsed is not None:
                values.append(parsed)
        if not values:
            return None
        fingerprints = {tuple(sorted(value)) for value in values}
        if len(fingerprints) > 1:
            failures.append(
                f"section card {card_id} has conflicting {label} ledger_slice aliases"
            )
        return values[0]

    source_ids = alias_value(source_keys, "baseline")
    destination_ids = alias_value(destination_keys, "destination")
    if source_ids is None:
        failures.append(
            f"section card {card_id} ledger_slice requires baseline_block_ids"
        )
    return True, source_ids or [], destination_ids


def resolve_mature_section(
    card: dict[str, Any],
    card_id: str,
    prefix: str,
    sections: list[dict[str, Any]],
    failures: list[str],
) -> tuple[dict[str, Any] | None, str, bool]:
    """Resolve an exact live section and reject ambiguous name selectors."""

    raw_id = card.get(f"{prefix}_section_id")
    section_id = raw_id.strip() if isinstance(raw_id, str) else ""
    if raw_id is not None and not section_id:
        failures.append(
            f"section card {card_id} has an invalid {prefix}_section_id"
        )

    specific_name_raw = card.get(f"{prefix}_section_name")
    specific_name = (
        specific_name_raw.strip() if isinstance(specific_name_raw, str) else ""
    )
    if specific_name_raw is not None and not specific_name:
        failures.append(
            f"section card {card_id} has an invalid {prefix}_section_name"
        )
    legacy_name_raw = (
        card.get("section_name")
        or card.get("section_title")
        or card.get("title")
    )
    legacy_name = str(legacy_name_raw or "").strip()
    if prefix == "baseline" and specific_name and legacy_name and (
        normalize_identifier(specific_name) != normalize_identifier(legacy_name)
    ):
        failures.append(
            f"section card {card_id} has conflicting baseline_section_name and legacy section_name"
        )
    name = specific_name or legacy_name
    name_is_legacy_candidate_hint = bool(
        prefix == "candidate" and not specific_name and legacy_name
    )

    if section_id:
        matches = [section for section in sections if section["id"] == section_id]
        if len(matches) != 1:
            failures.append(
                f"section card {card_id} {prefix}_section_id does not match an exact live main-text section: {section_id}"
            )
            return None, section_id, True
        selected = matches[0]
        name_to_validate = specific_name if prefix == "candidate" else name
        if name_to_validate and (
            selected["normalized_title"] != normalize_identifier(name_to_validate)
        ):
            failures.append(
                f"section card {card_id} {prefix}_section_id and {prefix}_section_name disagree"
            )
        return selected, section_id, True

    if not name:
        return None, "", False
    normalized_name = normalize_identifier(name)
    matches = [
        section
        for section in sections
        if section["normalized_title"] == normalized_name
    ]
    if len(matches) > 1:
        failures.append(
            f"section card {card_id} {prefix}_section_name matches multiple live sections; explicit {prefix}_section_id is required"
        )
        return None, name, True
    if len(matches) == 1:
        return matches[0], name, True
    if name_is_legacy_candidate_hint:
        # A legacy section_name names the baseline. A rename may legitimately
        # leave no same-name candidate, in which case the validated ledger is
        # the only permissible candidate selector.
        return None, name, False
    failures.append(
        f"section card {card_id} {prefix}_section_name does not match a live main-text section: {name}"
    )
    return None, name, True


def mature_section_budget_check(
    contract: dict[str, Any],
    baseline_sections: list[dict[str, Any]],
    candidate_sections: list[dict[str, Any]],
    baseline_inventory: list[dict[str, Any]],
    candidate_inventory: list[dict[str, Any]],
    ledger_by_source: dict[str, dict[str, Any]],
    metric_name: str,
    translation_mode: bool,
) -> tuple[dict[str, Any], list[str]]:
    """Bind mature section cards to live sections and validated ledger paths."""

    failures: list[str] = []
    raw_cards = contract.get("section_cards")
    cards: list[dict[str, Any]] = []
    if isinstance(raw_cards, list):
        cards = [dict(item) for item in raw_cards if isinstance(item, dict)]
        if len(cards) != len(raw_cards):
            failures.append("mature section_cards entries must be objects")
    elif isinstance(raw_cards, dict):
        for key, value in raw_cards.items():
            if not isinstance(value, dict):
                failures.append("mature section_cards entries must be objects")
                continue
            card = dict(value)
            card.setdefault("card_id", str(key))
            cards.append(card)
    else:
        failures.append(
            "mature baseline requires nonempty artifact_contract.section_cards"
        )
    if not cards and isinstance(raw_cards, (list, dict)):
        failures.append(
            "mature baseline requires nonempty artifact_contract.section_cards"
        )

    measurement = contract.get("measurement_contract")
    cross_language_metric = (
        str(measurement.get("cross_language_length_metric") or "").strip().lower()
        if isinstance(measurement, dict)
        else ""
    )
    enforce_target_range = bool(
        not translation_mode
        or cross_language_metric == "target_language_budget_only"
    )
    enforce_reduction = not translation_mode

    baseline_by_id = {item["block_id"]: item for item in baseline_inventory}
    candidate_by_id = {item["block_id"]: item for item in candidate_inventory}
    candidate_section_by_id = {item["id"]: item for item in candidate_sections}
    destination_section_sources: dict[str, set[str]] = {}
    for source_id, ledger_record in ledger_by_source.items():
        source = baseline_by_id.get(source_id)
        destination_id = str(
            ledger_record.get("destination_block_id") or ""
        ).strip()
        destination = candidate_by_id.get(destination_id)
        if (
            source is None
            or destination is None
            or ledger_record.get("status") != "pass"
            or destination.get("region") != "main_text"
        ):
            continue
        destination_section_sources.setdefault(
            str(destination.get("section_id")), set()
        ).add(str(source.get("section_id")))

    checks: list[dict[str, Any]] = []
    seen_card_ids: set[str] = set()
    baseline_card_coverage: dict[str, list[dict[str, Any]]] = {}
    source_slice_owner: dict[str, str] = {}
    candidate_usages: dict[str, list[dict[str, Any]]] = {}
    destination_slice_owner: dict[str, str] = {}
    authority = section_card_authority_context(contract, failures)
    authority_checks: list[dict[str, Any]] = []
    obligation_ids = registered_obligation_ids(contract)

    for index, card in enumerate(cards, 1):
        failure_count_before = len(failures)
        card_id = section_card_identity(card, index, failures, "mature section")
        if card_id in seen_card_ids:
            failures.append(f"duplicate mature section card_id: {card_id}")
        seen_card_ids.add(card_id)
        authority_check = section_card_authority_override_check(
            card, card_id, authority, failures
        )
        authority_checks.append(authority_check)
        if not nonempty_questions(card.get("minimum_depth_questions")):
            failures.append(
                f"section card {card_id} requires nonempty minimum_depth_questions"
            )
        if not nonempty_requirement(card.get("must_remain_main")):
            failures.append(
                f"section card {card_id} requires nonempty must_remain_main"
            )
        must_remain_reference_checks = validate_card_must_remain_references(
            card,
            card_id,
            candidate_sections,
            obligation_ids,
            failures,
        )

        baseline, baseline_selector, _ = resolve_mature_section(
            card, card_id, "baseline", baseline_sections, failures
        )
        candidate_hint, candidate_selector, candidate_selector_bound = (
            resolve_mature_section(
                card, card_id, "candidate", candidate_sections, failures
            )
        )
        slice_present, slice_source_ids, declared_destination_ids = (
            parse_ledger_slice(card, card_id, failures)
        )
        check: dict[str, Any] = {
            "section_card_id": card_id,
            "baseline_selector": baseline_selector,
            "candidate_selector": candidate_selector,
            "candidate_selector_explicit_or_resolved": candidate_selector_bound,
            "word_metric": metric_name,
            "measurement_scope": (
                "ledger_slice" if slice_present else "whole_live_section"
            ),
            "must_remain_reference_checks": must_remain_reference_checks,
            "status": "pass",
        }

        if baseline is None:
            if not baseline_selector:
                failures.append(
                    f"section card {card_id} requires baseline_section_id or baseline_section_name"
                )
            check["status"] = "fail"
            checks.append(check)
            continue

        section_sources = [
            item
            for item in baseline_inventory
            if item.get("region") == "main_text"
            and item.get("section_id") == baseline["id"]
        ]
        section_prose_sources = [
            item
            for item in section_sources
            if item.get("inventory_kind") == "prose_block"
        ]
        if not section_sources:
            failures.append(
                f"section card {card_id} baseline section {baseline['id']} has no substantive inventory for ledger binding"
            )

        selected_sources: list[dict[str, Any]]
        if slice_present:
            selected_sources = []
            for source_id in slice_source_ids:
                source = baseline_by_id.get(source_id)
                if source is None:
                    failures.append(
                        f"section card {card_id} ledger_slice references unknown live baseline block: {source_id}"
                    )
                    continue
                if source.get("inventory_kind") != "prose_block":
                    failures.append(
                        f"section card {card_id} ledger_slice may contain only baseline prose blocks: {source_id}"
                    )
                    continue
                if source.get("region") != "main_text":
                    failures.append(
                        f"section card {card_id} ledger_slice block is not in baseline main text: {source_id}"
                    )
                    continue
                if source.get("section_id") != baseline["id"]:
                    failures.append(
                        f"section card {card_id} ledger_slice block {source_id} is outside baseline section {baseline['id']}"
                    )
                    continue
                prior_owner = source_slice_owner.get(source_id)
                if prior_owner is not None and prior_owner != card_id:
                    failures.append(
                        f"baseline ledger_slice block {source_id} overlaps cards {prior_owner} and {card_id}"
                    )
                else:
                    source_slice_owner[source_id] = card_id
                selected_sources.append(source)
            if not selected_sources:
                failures.append(
                    f"section card {card_id} ledger_slice resolves no live baseline prose blocks"
                )
            consistency_sources = selected_sources
            observed_baseline = float(
                sum(float(item.get(metric_name) or 0) for item in selected_sources)
            )
        else:
            selected_sources = section_prose_sources
            consistency_sources = section_sources
            observed_baseline = float(baseline[metric_name])

        baseline_card_coverage.setdefault(baseline["id"], []).append(
            {
                "card_id": card_id,
                "slice_present": slice_present,
                "source_block_ids": {
                    item["block_id"] for item in selected_sources
                },
            }
        )
        declared_baseline = number(card.get("baseline_words"))
        check.update(
            {
                "baseline_section_id": baseline["id"],
                "baseline_observed": observed_baseline,
                "baseline_declared": declared_baseline,
                "ledger_source_block_ids": [
                    item["block_id"] for item in consistency_sources
                ],
            }
        )
        if declared_baseline is None or declared_baseline != observed_baseline:
            failures.append(
                f"section card {card_id} baseline_words must equal live {metric_name} {observed_baseline:.0f}"
            )

        section_ledger_records: list[dict[str, Any]] = []
        for source in consistency_sources:
            record = ledger_by_source.get(source["block_id"])
            if record is None:
                failures.append(
                    f"section card {card_id} lacks a validated ledger record for {source['block_id']}"
                )
                continue
            if record.get("status") != "pass":
                failures.append(
                    f"section card {card_id} ledger record is not validated pass: {source['block_id']}"
                )
                continue
            section_ledger_records.append(record)

        effective_moves = set(
            authority_check.get("effective_allowed_appendix_moves") or []
        )
        appendix_move_authority_checks: list[dict[str, Any]] = []
        for source in consistency_sources:
            record = ledger_by_source.get(source["block_id"])
            if not isinstance(record, dict) or record.get("status") != "pass":
                continue
            if record.get("disposition") != "moved_appendix":
                continue
            permitted_identifiers = {
                normalize_identifier(str(value))
                for value in (
                    baseline.get("title"),
                    *baseline.get("heading_labels", []),
                    *source.get("labels", []),
                )
                if normalize_identifier(str(value or ""))
            }
            matched = sorted(effective_moves & permitted_identifiers)
            permitted = bool(matched)
            appendix_move_authority_checks.append(
                {
                    "source_block_id": source["block_id"],
                    "source_section": source.get("section"),
                    "source_labels": source.get("labels", []),
                    "effective_allowed_appendix_moves": sorted(effective_moves),
                    "matched_identifiers": matched,
                    "status": "pass" if permitted else "fail",
                    "author_approval_still_required": True,
                }
            )
            if not permitted:
                failures.append(
                    f"section card {card_id} moved_appendix source "
                    f"{source['block_id']} is outside effective "
                    "allowed_appendix_moves"
                )
        check["appendix_move_authority_checks"] = appendix_move_authority_checks

        card_order_check, card_order_failures = patch_order_conservation_check(
            baseline_inventory,
            candidate_inventory,
            ledger_by_source,
            str(authority_check.get("effective_rewrite_mode") or "") or None,
            f"section card {card_id}",
            {source["block_id"] for source in consistency_sources},
        )
        check["patch_order_conservation"] = card_order_check
        failures.extend(card_order_failures)

        ledger_destination_ids = [
            str(record.get("destination_block_id"))
            for record in section_ledger_records
            if record.get("destination_block_id")
        ]
        if declared_destination_ids is not None and (
            set(declared_destination_ids) != set(ledger_destination_ids)
        ):
            failures.append(
                f"section card {card_id} ledger_slice destination block IDs do not exactly match the validated ledger"
            )

        destination_items = [
            candidate_by_id[destination_id]
            for destination_id in ledger_destination_ids
            if destination_id in candidate_by_id
        ]
        main_destination_items = [
            item for item in destination_items if item.get("region") == "main_text"
        ]
        main_destination_section_ids = {
            str(item.get("section_id")) for item in main_destination_items
        }
        dispositions = {
            str(record.get("disposition") or "")
            for record in section_ledger_records
        }
        authorized_absence = bool(
            section_ledger_records
            and not main_destination_items
            and dispositions <= {"deleted", "moved_appendix"}
        )

        candidate: dict[str, Any] | None = None
        if len(main_destination_section_ids) == 1:
            destination_section_id = next(iter(main_destination_section_ids))
            candidate = candidate_section_by_id.get(destination_section_id)
            if candidate is None:
                failures.append(
                    f"section card {card_id} validated ledger destination is not a live candidate main-text section: {destination_section_id}"
                )
            if candidate_hint is not None and candidate_hint["id"] != destination_section_id:
                failures.append(
                    f"section card {card_id} candidate selector {candidate_hint['id']} disagrees with validated ledger destination section {destination_section_id}"
                )
        elif len(main_destination_section_ids) > 1:
            failures.append(
                f"section card {card_id} maps to multiple candidate sections; use nonoverlapping ledger_slice cards or fail closed"
            )
        elif authorized_absence:
            if candidate_hint is not None:
                failures.append(
                    f"section card {card_id} candidate selector {candidate_hint['id']} disagrees with validated deleted/moved_appendix ledger disposition"
                )
        else:
            failures.append(
                f"section card {card_id} has no unambiguous validated main-text ledger destination"
            )

        check.update(
            {
                "ledger_destination_block_ids": sorted(
                    set(ledger_destination_ids)
                ),
                "ledger_dispositions": sorted(dispositions),
                "authorized_absence": authorized_absence,
            }
        )

        observed_candidate: float | None = None
        measured_main_destination_ids: set[str] = set()
        if candidate is not None:
            if slice_present:
                main_prose_destinations = [
                    item
                    for item in main_destination_items
                    if item.get("inventory_kind") == "prose_block"
                ]
                nonprose_destinations = [
                    item
                    for item in main_destination_items
                    if item.get("inventory_kind") != "prose_block"
                ]
                if nonprose_destinations:
                    failures.append(
                        f"section card {card_id} prose ledger_slice resolves non-prose candidate destinations"
                    )
                measured_main_destination_ids = {
                    item["block_id"] for item in main_prose_destinations
                }
                observed_candidate = float(
                    sum(
                        float(candidate_by_id[item_id].get(metric_name) or 0)
                        for item_id in measured_main_destination_ids
                    )
                )
                if not measured_main_destination_ids and not authorized_absence:
                    failures.append(
                        f"section card {card_id} ledger_slice has no measurable candidate main-text prose destination"
                    )
                for destination_id in measured_main_destination_ids:
                    prior_owner = destination_slice_owner.get(destination_id)
                    if prior_owner is not None and prior_owner != card_id:
                        failures.append(
                            f"candidate ledger destination {destination_id} is shared by sliced cards {prior_owner} and {card_id}; merge attribution is ambiguous"
                        )
                    else:
                        destination_slice_owner[destination_id] = card_id
            else:
                contributing_sections = destination_section_sources.get(
                    candidate["id"], set()
                )
                if contributing_sections - {baseline["id"]}:
                    failures.append(
                        f"section card {card_id} candidate section {candidate['id']} receives ledger destinations from multiple baseline sections; ledger_slice attribution is required"
                    )
                observed_candidate = float(candidate[metric_name])

            candidate_usages.setdefault(candidate["id"], []).append(
                {
                    "card_id": card_id,
                    "slice_present": slice_present,
                    "destination_block_ids": measured_main_destination_ids,
                }
            )
            check.update(
                {
                    "candidate_section_id": candidate["id"],
                    "candidate_observed": observed_candidate,
                    "measured_candidate_block_ids": sorted(
                        measured_main_destination_ids
                    ),
                }
            )
        else:
            check.update(
                {
                    "candidate_section_id": None,
                    "candidate_observed": None,
                    "measured_candidate_block_ids": [],
                }
            )

        if observed_candidate is not None and enforce_target_range:
            target_range = range_pair(card.get("target_word_range"))
            check["target_word_range"] = (
                [target_range[0], target_range[1]]
                if target_range is not None
                else None
            )
            if target_range is None:
                failures.append(
                    f"section card {card_id} requires a valid target_word_range"
                )
            elif not target_range[0] <= observed_candidate <= target_range[1]:
                failures.append(
                    f"candidate section for card {card_id} {metric_name} {observed_candidate:.0f} is outside target range [{target_range[0]:.0f}, {target_range[1]:.0f}]"
                )
        else:
            check["target_word_range"] = None
            check["target_range_applicable"] = enforce_target_range

        if observed_candidate is not None and enforce_reduction:
            reduction = reduction_pct(observed_baseline, observed_candidate)
            maximum = number(card.get("maximum_reduction_pct"))
            check.update(
                {
                    "reduction_pct": reduction,
                    "maximum_reduction_pct": maximum,
                }
            )
            if reduction is None:
                failures.append(
                    f"section card {card_id} baseline section must have positive {metric_name}"
                )
            if maximum is None or not 0 <= maximum <= 1:
                failures.append(
                    f"section card {card_id} maximum_reduction_pct must be between 0 and 1"
                )
            elif reduction is not None and reduction > maximum:
                failures.append(
                    f"section card {card_id} reduction {reduction:.1%} exceeds maximum {maximum:.1%}"
                )
        elif translation_mode:
            check["reduction_pct"] = None
            check["maximum_reduction_pct"] = None
            check["cross_language_reduction_applicable"] = False

        if len(failures) > failure_count_before:
            check["status"] = "fail"
        checks.append(check)

    uncovered: list[str] = []
    for section in baseline_sections:
        section_id = section["id"]
        coverage = baseline_card_coverage.get(section_id, [])
        if not coverage:
            uncovered.append(section_id)
            continue
        sliced = [item for item in coverage if item["slice_present"]]
        if sliced and len(sliced) != len(coverage):
            failures.append(
                f"baseline section {section_id} mixes whole-section and ledger_slice cards"
            )
            continue
        if not sliced:
            if len(coverage) != 1:
                failures.append(
                    f"multiple whole-section cards map to baseline section {section_id}; ledger_slice is required"
                )
            continue
        expected = {
            item["block_id"]
            for item in baseline_inventory
            if item.get("region") == "main_text"
            and item.get("section_id") == section_id
            and item.get("inventory_kind") == "prose_block"
        }
        observed = set().union(
            *(item["source_block_ids"] for item in sliced)
        )
        if observed != expected:
            missing = sorted(expected - observed)
            extra = sorted(observed - expected)
            failures.append(
                f"baseline section {section_id} ledger_slice cards must exactly cover live prose blocks; missing={missing}, extra={extra}"
            )

    for candidate_section_id, usages in candidate_usages.items():
        if len(usages) <= 1:
            continue
        if any(not usage["slice_present"] for usage in usages):
            failures.append(
                f"candidate section {candidate_section_id} is measured by multiple cards without nonoverlapping ledger_slice attribution"
            )

    if uncovered:
        failures.append(
            "baseline main-text sections lack section cards: " + ", ".join(uncovered)
        )
    status = "fail" if failures else "pass"
    return (
        {
            "required": True,
            "status": status,
            "word_metric": metric_name,
            "translation_mode": translation_mode,
            "cross_language_length_metric": (
                cross_language_metric if translation_mode else None
            ),
            "target_ranges_enforced": enforce_target_range,
            "checks": checks,
            "section_authority_checks": authority_checks,
            "uncovered_baseline_section_ids": uncovered,
        },
        failures,
    )


def audit(args: argparse.Namespace) -> dict[str, Any]:
    baseline_path = (
        Path(args.baseline).expanduser().resolve() if args.baseline else None
    )
    candidate_path = Path(args.candidate).expanduser().resolve()
    contract_path = Path(args.contract).expanduser().resolve() if args.contract else None
    contract = load_contract(contract_path)
    task_mode = str(contract.get("task_mode", "")).strip().lower()
    if task_mode not in VALID_TASK_MODES:
        expected = ", ".join(sorted(VALID_TASK_MODES))
        raise MetricUnavailable(
            f"artifact_contract.task_mode must be one of: {expected}"
        )
    raw_metric_status = contract.get("metric_status")
    metric_status = (
        str(raw_metric_status).strip().lower()
        if isinstance(raw_metric_status, str)
        else ""
    )
    if metric_status not in {"measured", "unavailable", "ambiguous"}:
        raise MetricUnavailable(
            "artifact_contract.metric_status must be explicitly measured, unavailable, or ambiguous"
        )
    if metric_status != "measured":
        raise MetricUnavailable(
            f"artifact_contract.metric_status={metric_status}; resolve the measurement before auditing"
        )
    measurement_contract = contract.get("measurement_contract")
    if not isinstance(measurement_contract, dict):
        raise MetricUnavailable(
            "artifact_contract.measurement_contract must be an object with an explicit appendix_boundary and source_word_method"
        )
    source_word_method = measurement_contract.get("source_word_method")
    if source_word_method not in {"raw_source_words", "normalized_words"}:
        raise MetricUnavailable(
            "measurement_contract.source_word_method must be explicitly raw_source_words or normalized_words"
        )
    recorded_boundary = measurement_contract.get("appendix_boundary")
    if isinstance(recorded_boundary, dict):
        recorded_boundary = recorded_boundary.get("marker") or recorded_boundary.get("value")
    if not isinstance(recorded_boundary, str) or not recorded_boundary.strip():
        raise MetricUnavailable(
            "measurement_contract.appendix_boundary must be explicitly recorded"
        )
    if recorded_boundary.strip() != args.appendix_marker:
        raise MetricUnavailable(
            "measurement_contract.appendix_boundary does not match --appendix-marker"
        )
    mature_value = contract.get("mature_baseline")
    if not isinstance(mature_value, bool):
        raise MetricUnavailable(
            "artifact_contract.mature_baseline must be an explicit boolean; "
            "missing or unknown maturity cannot authorize a conservation audit"
        )
    mature = mature_value
    translation_mode = task_mode in {"translation", "document_translation"}

    if args.project_root:
        project_root = Path(args.project_root).expanduser().resolve()
    else:
        parents = [str(candidate_path.parent)]
        if baseline_path is not None:
            parents.append(str(baseline_path.parent))
        project_root = Path(os.path.commonpath(parents)).resolve()
    if not project_root.is_dir():
        raise MetricUnavailable(f"project root is not a directory: {project_root}")
    if baseline_path is None and task_mode in BASELINE_REQUIRED_TASK_MODES:
        raise MetricUnavailable(f"task_mode={task_mode} requires --baseline")

    candidate_text, candidate_sources, candidate_format = load_manuscript(
        candidate_path, project_root
    )
    candidate_main, candidate_appendix = split_appendix(
        candidate_text, args.appendix_marker, "candidate", candidate_format
    )
    baseline_text: str | None = None
    baseline_sources: list[str] = []
    baseline_format: str | None = None
    baseline_main: str | None = None
    baseline_appendix: str | None = None
    if baseline_path is not None:
        baseline_text, baseline_sources, baseline_format = load_manuscript(
            baseline_path, project_root
        )
        baseline_main, baseline_appendix = split_appendix(
            baseline_text, args.appendix_marker, "baseline", baseline_format
        )

    candidate_metrics = manuscript_metrics(candidate_main, candidate_format)
    candidate_appendix_metrics = manuscript_metrics(
        candidate_appendix, candidate_format
    )
    baseline_metrics = (
        manuscript_metrics(baseline_main, baseline_format)
        if baseline_main is not None and baseline_format is not None
        else None
    )
    baseline_appendix_metrics = (
        manuscript_metrics(baseline_appendix, baseline_format)
        if baseline_appendix is not None and baseline_format is not None
        else None
    )
    baseline_source_file_records = source_file_records(baseline_sources)
    candidate_source_file_records = source_file_records(candidate_sources)
    metric_name = selected_word_metric(contract, args.word_metric)
    candidate_words = float(candidate_metrics[metric_name])
    baseline_words = (
        float(baseline_metrics[metric_name]) if baseline_metrics is not None else None
    )

    preflight_failures: list[str] = validate_baseline_binding(
        contract,
        baseline_path,
        sha256_text(baseline_text) if baseline_text is not None else None,
        baseline_source_file_records,
        contract_path,
        project_root,
    )
    declared_baseline_words = number(contract.get("baseline_main_source_words"))
    if baseline_path is not None:
        if declared_baseline_words is None:
            preflight_failures.append(
                "artifact_contract.baseline_main_source_words must bind the live accepted baseline"
            )
        elif declared_baseline_words != baseline_words:
            preflight_failures.append(
                f"artifact_contract.baseline_main_source_words {declared_baseline_words:.0f} does not equal live {metric_name} {baseline_words:.0f}"
            )
    elif contract.get("baseline_main_source_words") is not None:
        preflight_failures.append(
            "baseline_main_source_words is not allowed without --baseline"
        )
    rewrite_mode = str(contract.get("rewrite_mode", "")).strip().lower()
    if rewrite_mode and rewrite_mode not in VALID_REWRITE_MODES:
        preflight_failures.append(
            "rewrite_mode must be patch_existing, reorder_existing_blocks, or full_redraft"
        )
    if task_mode in REWRITE_MODE_REQUIRED_TASK_MODES and not rewrite_mode:
        preflight_failures.append(f"task_mode={task_mode} requires rewrite_mode")
    recorded_target_basis = str(contract.get("target_basis", "")).strip().lower()
    if recorded_target_basis and recorded_target_basis not in VALID_TARGET_BASES:
        preflight_failures.append(
            "target_basis must be user, project_rule, verified_journal, accepted_baseline, or default"
        )
    if task_mode == "full_draft" and baseline_path is not None:
        preflight_failures.append("task_mode=full_draft must not supply --baseline")
    if (
        baseline_format is not None
        and baseline_format != candidate_format
        and not translation_mode
    ):
        preflight_failures.append(
            "baseline and candidate formats may differ only in translation mode"
        )
    if "measurement_contract" in contract and not isinstance(
        measurement_contract, dict
    ):
        preflight_failures.append("measurement_contract must be an object")
    if isinstance(measurement_contract, dict):
        source_word_method = measurement_contract.get("source_word_method")
        if source_word_method is not None and source_word_method not in {
            "raw_source_words",
            "normalized_words",
        }:
            preflight_failures.append(
                "measurement_contract.source_word_method is unsupported"
            )
        if (
            args.word_metric is not None
            and source_word_method in {"raw_source_words", "normalized_words"}
            and args.word_metric != source_word_method
        ):
            preflight_failures.append(
                "--word-metric must match measurement_contract.source_word_method"
            )
        recorded_boundary = measurement_contract.get("appendix_boundary")
        if isinstance(recorded_boundary, dict):
            recorded_boundary = recorded_boundary.get("marker") or recorded_boundary.get("value")
        if recorded_boundary is not None and str(recorded_boundary).strip() != args.appendix_marker:
            preflight_failures.append(
                "measurement_contract.appendix_boundary does not match --appendix-marker"
            )
    word_range_fields = [
        ("target_language_main_source_word_range", contract.get("target_language_main_source_word_range")),
        ("target_main_source_word_range", contract.get("target_main_source_word_range")),
    ]
    if isinstance(measurement_contract, dict):
        word_range_fields.extend(
            [
                ("measurement_contract.target_language_word_range", measurement_contract.get("target_language_word_range")),
                ("measurement_contract.target_language_length_range", measurement_contract.get("target_language_length_range")),
            ]
        )
    for field, raw in word_range_fields:
        if raw is not None and range_pair(raw) is None:
            preflight_failures.append(f"{field} must be a nonnegative [lower, upper] range")
    target_words = range_pair(contract.get("target_language_main_source_word_range"))
    if target_words is None:
        target_words = range_pair(contract.get("target_main_source_word_range"))
    if target_words is None and isinstance(measurement_contract, dict):
        target_words = range_pair(
            measurement_contract.get("target_language_word_range")
            or measurement_contract.get("target_language_length_range")
        )
    target_pages = range_pair(contract.get("target_main_pdf_page_range"))
    if contract.get("target_main_pdf_page_range") is not None and target_pages is None:
        preflight_failures.append(
            "target_main_pdf_page_range must be a nonnegative [lower, upper] range"
        )
    floor_value = contract.get("hard_main_text_floor", {})
    if isinstance(floor_value, (int, float)) and not isinstance(floor_value, bool):
        floor_words = float(floor_value)
        floor_pages = None
    elif isinstance(floor_value, dict):
        floor_words = number(floor_value.get("source_words"))
        floor_pages = number(floor_value.get("pdf_pages"))
        if floor_value.get("source_words") is not None and (
            floor_words is None or floor_words < 0
        ):
            preflight_failures.append(
                "hard_main_text_floor.source_words must be nonnegative"
            )
        if floor_value.get("pdf_pages") is not None and (
            floor_pages is None or floor_pages < 0
        ):
            preflight_failures.append(
                "hard_main_text_floor.pdf_pages must be nonnegative"
            )
    else:
        floor_words = floor_pages = None
        if floor_value not in (None, ""):
            preflight_failures.append(
                "hard_main_text_floor must be a number or an object"
            )
    if args.min_main_source_words is not None:
        cli_floor_words = float(args.min_main_source_words)
        if cli_floor_words < 0:
            preflight_failures.append(
                "--min-main-source-words must be nonnegative"
            )
        if floor_words is not None and cli_floor_words < floor_words:
            preflight_failures.append(
                "--min-main-source-words cannot weaken artifact_contract.hard_main_text_floor.source_words"
            )
        floor_words = max(floor_words or 0.0, cli_floor_words)
    if args.min_main_pdf_pages is not None:
        cli_floor_pages = float(args.min_main_pdf_pages)
        if cli_floor_pages < 0:
            preflight_failures.append("--min-main-pdf-pages must be nonnegative")
        if floor_pages is not None and cli_floor_pages < floor_pages:
            preflight_failures.append(
                "--min-main-pdf-pages cannot weaken artifact_contract.hard_main_text_floor.pdf_pages"
            )
        floor_pages = max(floor_pages or 0.0, cli_floor_pages)
    if floor_words is not None and floor_words < 0:
        preflight_failures.append("main-text source-word floor must be nonnegative")
    if floor_pages is not None and floor_pages < 0:
        preflight_failures.append("main-text PDF-page floor must be nonnegative")

    declared_baseline_pages = number(contract.get("baseline_main_pdf_pages"))
    if contract.get("baseline_main_pdf_pages") is not None and (
        declared_baseline_pages is None or declared_baseline_pages <= 0
    ):
        preflight_failures.append(
            "artifact_contract.baseline_main_pdf_pages must be positive"
        )
    page_constraints_active = bool(
        args.baseline_main_pdf_pages is not None
        or args.candidate_main_pdf_pages is not None
        or args.min_main_pdf_pages is not None
        or floor_pages is not None
        or target_pages is not None
        or contract.get("baseline_main_pdf_pages") is not None
    )
    baseline_pages, candidate_pages, verified_page_attestation = validate_page_attestation(
        args,
        contract,
        contract_path,
        project_root,
        baseline_path is not None,
        page_constraints_active,
    )
    if page_constraints_active and baseline_path is not None:
        if declared_baseline_pages is None:
            preflight_failures.append(
                "active PDF-page constraints require artifact_contract.baseline_main_pdf_pages"
            )
        elif baseline_pages is not None and declared_baseline_pages != baseline_pages:
            preflight_failures.append(
                "artifact_contract.baseline_main_pdf_pages does not equal the live attested baseline pages"
            )
    elif baseline_path is None and contract.get("baseline_main_pdf_pages") is not None:
        preflight_failures.append(
            "baseline_main_pdf_pages is not allowed without --baseline"
        )

    word_reduction: float | None = None
    page_reduction: float | None = None
    if baseline_words is not None and not translation_mode:
        word_reduction = reduction_pct(baseline_words, candidate_words)
        if word_reduction is None:
            raise MetricUnavailable(f"baseline {metric_name} must be greater than zero")
        if baseline_pages is not None and candidate_pages is not None:
            page_reduction = reduction_pct(baseline_pages, candidate_pages)

    candidate_sections = candidate_metrics["section_metrics"]
    candidate_appendix_sections = candidate_appendix_metrics["section_metrics"]
    candidate_only_contract_check: dict[str, Any] = {
        "required": False,
        "status": "not_applicable",
    }
    if baseline_path is None and task_mode == "full_draft":
        (
            candidate_only_contract_check,
            candidate_only_failures,
        ) = candidate_only_full_draft_contract_check(
            contract,
            candidate_sections,
            target_words,
            target_pages,
            verified_page_attestation,
            metric_name,
        )
        preflight_failures.extend(candidate_only_failures)
    baseline_sections = baseline_metrics["section_metrics"] if baseline_metrics else []
    mature_section_budget: dict[str, Any] = {
        "required": False,
        "status": "not_applicable",
    }
    baseline_counts = Counter(section["normalized_title"] for section in baseline_sections)
    candidate_counts = Counter(section["normalized_title"] for section in candidate_sections)
    appendix_counts = Counter(
        section["normalized_title"] for section in candidate_appendix_sections
    )
    baseline_titles = {
        section["normalized_title"]: section["title"] for section in baseline_sections
    }
    missing_sections: list[dict[str, Any]] = []
    for normalized, count in baseline_counts.items():
        missing_count = max(0, count - candidate_counts[normalized])
        moved_count = min(missing_count, appendix_counts[normalized])
        for index in range(missing_count):
            missing_sections.append(
                {
                    "title": baseline_titles[normalized],
                    "normalized_title": normalized,
                    "disposition": "moved_appendix" if index < moved_count else "missing",
                }
            )

    baseline_main_labels = (
        set(baseline_metrics["structure"]["labels"]) if baseline_metrics else set()
    )
    candidate_main_labels = set(candidate_metrics["structure"]["labels"])
    candidate_appendix_labels = set(candidate_appendix_metrics["structure"]["labels"])
    labels_moved_to_appendix = sorted(
        (baseline_main_labels - candidate_main_labels) & candidate_appendix_labels
    )
    labels_missing_entirely = sorted(
        baseline_main_labels - candidate_main_labels - candidate_appendix_labels
    )
    label_source_sections = main_label_to_section(baseline_sections)

    baseline_inventory = []
    if (
        baseline_main is not None
        and baseline_appendix is not None
        and baseline_format is not None
    ):
        baseline_inventory = substantive_block_inventory(
            baseline_main, "main_text", baseline_format
        ) + substantive_block_inventory(
            baseline_appendix, "appendix", baseline_format
        ) + substantive_object_inventory(
            baseline_main, "main_text", baseline_format
        ) + substantive_object_inventory(
            baseline_appendix, "appendix", baseline_format
        )
    candidate_inventory = substantive_block_inventory(
        candidate_main, "main_text", candidate_format
    ) + substantive_block_inventory(
        candidate_appendix, "appendix", candidate_format
    ) + substantive_object_inventory(
        candidate_main, "main_text", candidate_format
    ) + substantive_object_inventory(
        candidate_appendix, "appendix", candidate_format
    )
    ledger_required = baseline_path is not None
    ledger_validation, ledger_by_source, ledger_failures = validate_conservation_ledger(
        contract,
        baseline_inventory,
        candidate_inventory,
        ledger_required,
        sha256_text(candidate_text),
    )
    if baseline_path is not None:
        global_patch_order_check, global_patch_order_failures = (
            patch_order_conservation_check(
                baseline_inventory,
                candidate_inventory,
                ledger_by_source,
                rewrite_mode or None,
                "artifact-wide",
            )
        )
    else:
        global_patch_order_check, global_patch_order_failures = {
            "required": False,
            "status": "not_applicable",
            "scope": "artifact-wide",
            "rewrite_mode": rewrite_mode or None,
            "new_unmapped_blocks_ignored": True,
        }, []
    if mature and baseline_path is not None:
        mature_section_budget, mature_section_failures = mature_section_budget_check(
            contract,
            baseline_sections,
            candidate_sections,
            baseline_inventory,
            candidate_inventory,
            ledger_by_source,
            metric_name,
            translation_mode,
        )
        preflight_failures.extend(mature_section_failures)

    two_pass_required = bool(
        mature
        and rewrite_mode != "full_redraft"
        and (
            task_mode == "restructure"
            or (
                task_mode == "major_revision"
                and rewrite_mode == "reorder_existing_blocks"
            )
        )
    )
    if two_pass_required:
        two_pass_check, two_pass_failures = validate_two_pass_restructure(
            contract,
            contract_path,
            project_root,
            args.appendix_marker,
            baseline_inventory,
            candidate_inventory,
            candidate_text,
            candidate_format,
        )
    else:
        two_pass_check, two_pass_failures = {
            "required": False,
            "status": "not_applicable",
        }, []

    scopes = approval_scopes(contract)
    failures: list[str] = [
        *preflight_failures,
        *ledger_failures,
        *global_patch_order_failures,
        *two_pass_failures,
    ]
    approval_triggers: list[str] = []
    warnings: list[str] = []
    if mature and task_mode == "full_draft":
        failures.append("mature_baseline=true conflicts with task_mode full_draft")

    cross_language_metric: str | None = None
    effective_target_words = target_words
    if translation_mode:
        source_language = str(contract.get("source_language", "")).strip()
        target_language = str(contract.get("target_language", "")).strip()
        if not source_language or not target_language:
            failures.append(
                "translation requires nonempty source_language and target_language"
            )
        measurement = measurement_contract
        cross_metric = (
            str(measurement.get("cross_language_length_metric", "")).strip().lower()
            if isinstance(measurement, dict)
            else ""
        )
        if cross_metric and cross_metric not in {
            "inapplicable",
            "target_language_budget_only",
        }:
            failures.append(
                "measurement_contract.cross_language_length_metric must be "
                "inapplicable or target_language_budget_only"
            )
        cross_language_metric = (
            cross_metric
            if cross_metric
            else ("target_language_budget_only" if target_words else None)
        )
        if cross_metric != "inapplicable" and target_words is None:
            failures.append(
                "translation requires cross_language_length_metric=inapplicable or a target-language word range"
            )
        if cross_metric == "inapplicable":
            effective_target_words = None

    if (
        rewrite_mode == "full_redraft"
        and task_mode in REWRITE_MODE_REQUIRED_TASK_MODES
        and not full_redraft_approved(contract, scopes)
    ):
        approval_triggers.append(
            "rewrite_mode full_redraft requires recoverable author approval with approved_by, approved_at, and approved_scope"
        )

    baseline_main_blocks = [
        item for item in baseline_inventory if item["region"] == "main_text"
    ]

    def section_ledger_exemption(normalized: str, disposition: str) -> bool:
        blocks = [
            item
            for item in baseline_main_blocks
            if item["normalized_section"] == normalized
        ]
        if not blocks:
            return False
        records = [ledger_by_source.get(item["block_id"]) for item in blocks]
        if any(record is None or record.get("status") != "pass" for record in records):
            return False
        dispositions = {str(record.get("disposition")) for record in records if record}
        if disposition == "moved_appendix":
            return dispositions == {"moved_appendix"}
        if dispositions <= {"deleted"}:
            return True
        return bool(dispositions) and dispositions <= AUTHORITY_DISPOSITIONS

    def label_ledger_exemption(label: str, disposition: str) -> bool:
        object_sources = [
            item
            for item in baseline_main_blocks
            if item.get("inventory_kind") == "substantive_object"
            and label in item.get("labels", [])
        ]
        sources = object_sources or [
            item
            for item in baseline_main_blocks
            if label in item.get("labels", [])
        ]
        if not sources:
            return False
        records = [ledger_by_source.get(item["block_id"]) for item in sources]
        return all(
            record is not None
            and record.get("status") == "pass"
            and record.get("disposition") == disposition
            for record in records
        )

    for section in missing_sections:
        title = section["title"]
        normalized = section["normalized_title"]
        if section_ledger_exemption(normalized, section["disposition"]):
            section["ledger_exempted"] = True
            continue
        section["ledger_exempted"] = False
        if section["disposition"] == "moved_appendix":
            failures.append(f"unapproved whole-section appendix move: {title}")
        else:
            failures.append(f"unapproved whole-section disappearance: {title}")

    for label in labels_moved_to_appendix:
        source_section = label_source_sections.get(label, "")
        if not (
            label_ledger_exemption(label, "moved_appendix")
            or section_ledger_exemption(source_section, "moved_appendix")
        ):
            failures.append(f"unapproved label moved to appendix: {label}")
    for label in labels_missing_entirely:
        source_section = label_source_sections.get(label, "")
        section_blocks = [
            item
            for item in baseline_main_blocks
            if item["normalized_section"] == source_section
        ]
        deletion_records = [
            ledger_by_source.get(item["block_id"]) for item in section_blocks
        ]
        deletion_authorized = label_ledger_exemption(label, "deleted") or (
            bool(section_blocks) and all(
            record is not None
            and record.get("status") == "pass"
            and record.get("disposition") == "deleted"
            for record in deletion_records
            )
        )
        if not deletion_authorized:
            failures.append(f"baseline main-text label disappeared: {label}")

    missing_required = check_must_remain(contract, candidate_sections, candidate_main_labels)
    for item in missing_required:
        failures.append(f"must_remain_main missing: {item}")

    if floor_words is not None and candidate_words < floor_words:
        failures.append(
            f"candidate {metric_name} {candidate_words:.0f} is below hard floor {floor_words:.0f}"
        )
    if floor_pages is not None and candidate_pages is not None and candidate_pages < floor_pages:
        failures.append(
            f"candidate main PDF pages {candidate_pages:.0f} are below hard floor {floor_pages:.0f}"
        )
    if effective_target_words and not (
        effective_target_words[0] <= candidate_words <= effective_target_words[1]
    ):
        failures.append(
            f"candidate {metric_name} {candidate_words:.0f} is outside target range "
            f"[{effective_target_words[0]:.0f}, {effective_target_words[1]:.0f}]"
        )
    if target_pages and candidate_pages is not None and not (
        target_pages[0] <= candidate_pages <= target_pages[1]
    ):
        failures.append(
            f"candidate main PDF pages {candidate_pages:.0f} are outside target range "
            f"[{target_pages[0]:.0f}, {target_pages[1]:.0f}]"
        )

    shortening_requested = task_mode == "shorten"
    target_basis = str(contract.get("target_basis", "")).strip().lower()
    authoritative_short_target = bool(
        effective_target_words or target_pages
    ) and target_basis in {
        "user",
        "project_rule",
        "verified_journal",
    }
    explicit_shorter = bool(compression_approved(contract, scopes)) or (
        shortening_requested and bool(effective_target_words or target_pages)
    ) or authoritative_short_target
    if shortening_requested and not explicit_shorter:
        failures.append(
            "shorten mode requires a recorded target range or explicit compression approval"
        )

    cli_maximum = number(args.max_main_reduction)
    contract_maximum = number(contract.get("max_unapproved_main_reduction_pct"))
    for label, raw_value, parsed_value in (
        ("--max-main-reduction", args.max_main_reduction, cli_maximum),
        (
            "max_unapproved_main_reduction_pct",
            contract.get("max_unapproved_main_reduction_pct"),
            contract_maximum,
        ),
    ):
        if raw_value is not None and (
            parsed_value is None or parsed_value < 0 or parsed_value > 1
        ):
            failures.append(f"{label} must be between 0 and 1")
    valid_cli_maximum = (
        cli_maximum
        if cli_maximum is not None and 0 <= cli_maximum <= 1
        else None
    )
    valid_contract_maximum = (
        contract_maximum
        if contract_maximum is not None and 0 <= contract_maximum <= 1
        else None
    )
    if (
        valid_cli_maximum is not None
        and valid_contract_maximum is not None
        and valid_cli_maximum > valid_contract_maximum
    ):
        failures.append(
            "--max-main-reduction cannot weaken artifact_contract.max_unapproved_main_reduction_pct"
        )
    maximum_candidates = [
        value
        for value in (valid_cli_maximum, valid_contract_maximum)
        if value is not None
    ]
    maximum = min(maximum_candidates) if maximum_candidates else None
    if translation_mode:
        maximum = None
    else:
        conditional_fifteen_percent_gate = bool(
            mature
            and task_mode in {"major_revision", "restructure"}
            and not explicit_shorter
        )
        if (
            conditional_fifteen_percent_gate
            and maximum is not None
            and maximum > 0.15
        ):
            failures.append(
                "raising max_unapproved_main_reduction_pct above 0.15 requires "
                "an authoritative shorter target or human compression approval"
            )
            maximum = 0.15
        elif conditional_fifteen_percent_gate and maximum is None:
            maximum = 0.15
    reductions = [item for item in (word_reduction, page_reduction) if item is not None]
    cumulative_reduction = max(reductions) if reductions else None
    if (
        maximum is not None
        and cumulative_reduction is not None
        and cumulative_reduction > maximum
        and not explicit_shorter
        and not compression_approved(contract, scopes)
    ):
        approval_triggers.append(
            f"cumulative main-text reduction {cumulative_reduction:.1%} exceeds "
            f"unapproved limit {maximum:.1%}"
        )

    if candidate_metrics["structure"]["sections"] == 0:
        warnings.append("candidate main text contains no detected section headings")

    if failures:
        status = "fail"
    elif approval_triggers:
        status = "approval_required"
    else:
        status = "pass"

    baseline_by_id = {
        item["id"]: item for item in baseline_sections
    }
    candidate_by_id = {item["id"]: item for item in candidate_sections}
    section_changes: list[dict[str, Any]] = []
    for section_id in sorted(set(baseline_by_id) | set(candidate_by_id)):
        before = baseline_by_id.get(section_id)
        after = candidate_by_id.get(section_id)
        section_changes.append(
            {
                "section_id": section_id,
                "title": (after or before or {}).get("title"),
                "baseline_raw_source_words": before and before["raw_source_words"],
                "candidate_raw_source_words": after and after["raw_source_words"],
                "baseline_normalized_words": before and before["normalized_words"],
                "candidate_normalized_words": after and after["normalized_words"],
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "schema_id": SCHEMA_ID,
        "gate_type": GATE_TYPE,
        "status": status,
        "exit_code": EXIT_CODES[status],
        "audit_arguments": audit_argument_record(args),
        "inputs": {
            "baseline": str(baseline_path) if baseline_path else None,
            "baseline_format": baseline_format,
            "baseline_sha256": sha256_file(baseline_path) if baseline_path else None,
            "baseline_expanded_sha256": sha256_text(baseline_text) if baseline_text is not None else None,
            "candidate": str(candidate_path),
            "candidate_format": candidate_format,
            "candidate_sha256": sha256_file(candidate_path),
            "candidate_expanded_sha256": sha256_text(candidate_text),
            "expanded_sha256_scope": (
                "format-aware UTF-8 canonical source: recursive TeX expansion after "
                "comment blanking; Markdown HTML-comment blanking; plain text unchanged"
            ),
            "project_root": str(project_root),
            "contract": str(contract_path) if contract_path else None,
            "contract_sha256": (
                sha256_file(contract_path)
                if contract_path is not None and contract_path.is_file()
                else None
            ),
            "appendix_marker": args.appendix_marker,
            "baseline_sources": [item["path"] for item in baseline_source_file_records],
            "candidate_sources": [item["path"] for item in candidate_source_file_records],
            "baseline_source_files": baseline_source_file_records,
            "candidate_source_files": candidate_source_file_records,
        },
        "measurement": {
            "word_metric_for_contract": metric_name,
            "baseline_comparison_applicable": baseline_path is not None and not translation_mode,
            "cross_language_length_metric": (
                cross_language_metric
                if translation_mode
                else "same-language-comparison"
            ),
            "target_main_source_word_range_enforced": bool(
                effective_target_words is not None
            ),
            "baseline_main_pdf_pages": baseline_pages,
            "candidate_main_pdf_pages": candidate_pages,
            "verified_page_attestation": verified_page_attestation,
            "page_metric_note": "main-text page counts require live-hash-bound attestation at an explicit appendix boundary; total PDF pages are rejected",
        },
        "metrics": {
            "baseline_main": baseline_metrics,
            "candidate_main": candidate_metrics,
            "baseline_appendix": baseline_appendix_metrics,
            "candidate_appendix": candidate_appendix_metrics,
            "word_reduction_pct": word_reduction,
            "page_reduction_pct": page_reduction,
            "cumulative_reduction_pct": cumulative_reduction,
            "max_unapproved_main_reduction_pct": maximum,
            "structural_delta": (
                structural_delta(
                    baseline_metrics["structure"], candidate_metrics["structure"]
                )
                if baseline_metrics is not None
                else None
            ),
            "section_changes": section_changes,
        },
        "conservation": {
            "ledger_required": ledger_required,
            "candidate_only_full_draft_contract": candidate_only_contract_check,
            "mature_section_budget": mature_section_budget,
            "expected_baseline_block_ids": sorted(
                item["block_id"] for item in baseline_inventory
            ),
            "baseline_block_inventory": baseline_inventory,
            "candidate_block_inventory": candidate_inventory,
            "baseline_object_inventory": [
                item
                for item in baseline_inventory
                if item.get("inventory_kind") == "substantive_object"
            ],
            "candidate_object_inventory": [
                item
                for item in candidate_inventory
                if item.get("inventory_kind") == "substantive_object"
            ],
            "ledger_validation": ledger_validation,
            "patch_order_conservation": global_patch_order_check,
            "two_pass_restructure": two_pass_check,
            "whole_sections_missing_or_moved": missing_sections,
            "labels_moved_to_appendix": labels_moved_to_appendix,
            "labels_missing_entirely": labels_missing_entirely,
            "must_remain_main_missing": missing_required,
        },
        "findings": {
            "failures": sorted(set(failures)),
            "approval_triggers": sorted(set(approval_triggers)),
            "warnings": sorted(set(warnings)),
        },
    }


def unavailable_report(args: argparse.Namespace, error: Exception) -> dict[str, Any]:
    baseline_path = (
        Path(args.baseline).expanduser().resolve() if args.baseline else None
    )
    candidate_path = Path(args.candidate).expanduser().resolve()
    contract_path = Path(args.contract).expanduser().resolve() if args.contract else None
    if args.project_root:
        project_root = Path(args.project_root).expanduser().resolve()
    else:
        parents = [str(candidate_path.parent)]
        if baseline_path is not None:
            parents.append(str(baseline_path.parent))
        project_root = Path(os.path.commonpath(parents)).resolve()

    def snapshot(
        path: Path | None,
    ) -> tuple[str | None, list[dict[str, str]], str | None]:
        if path is None or not path.is_file() or not project_root.is_dir():
            return None, [], None
        try:
            expanded, sources, fmt = load_manuscript(path, project_root)
            return sha256_text(expanded), source_file_records(sources), fmt
        except MetricUnavailable:
            return None, [], None

    (
        baseline_expanded_sha,
        baseline_source_files,
        baseline_format,
    ) = snapshot(baseline_path)
    (
        candidate_expanded_sha,
        candidate_source_files,
        candidate_format,
    ) = snapshot(candidate_path)
    return {
        "schema_version": SCHEMA_VERSION,
        "schema_id": SCHEMA_ID,
        "gate_type": GATE_TYPE,
        "status": "metric_unavailable",
        "exit_code": EXIT_CODES["metric_unavailable"],
        "audit_arguments": audit_argument_record(args),
        "inputs": {
            "baseline": str(baseline_path) if baseline_path else None,
            "baseline_format": baseline_format,
            "baseline_sha256": (
                sha256_file(baseline_path)
                if baseline_path is not None and baseline_path.is_file()
                else None
            ),
            "baseline_expanded_sha256": baseline_expanded_sha,
            "candidate": str(candidate_path),
            "candidate_format": candidate_format,
            "candidate_sha256": sha256_file(candidate_path) if candidate_path.is_file() else None,
            "candidate_expanded_sha256": candidate_expanded_sha,
            "expanded_sha256_scope": (
                "format-aware UTF-8 canonical source: recursive TeX expansion after "
                "comment blanking; Markdown HTML-comment blanking; plain text unchanged"
            ),
            "project_root": str(project_root),
            "contract": str(contract_path) if contract_path else None,
            "contract_sha256": (
                sha256_file(contract_path)
                if contract_path is not None and contract_path.is_file()
                else None
            ),
            "appendix_marker": args.appendix_marker,
            "baseline_sources": [item["path"] for item in baseline_source_files],
            "candidate_sources": [item["path"] for item in candidate_source_files],
            "baseline_source_files": baseline_source_files,
            "candidate_source_files": candidate_source_files,
        },
        "measurement": {
            "status": "metric_unavailable",
            "word_metric_for_contract": args.word_metric,
            "baseline_comparison_applicable": None,
            "cross_language_length_metric": None,
            "baseline_main_pdf_pages": args.baseline_main_pdf_pages,
            "candidate_main_pdf_pages": args.candidate_main_pdf_pages,
            "verified_page_attestation": None,
            "page_metric_note": "main-text page counts require live-hash-bound attestation at an explicit appendix boundary; total PDF pages are rejected",
        },
        "metrics": {
            "baseline_main": None,
            "candidate_main": None,
            "baseline_appendix": None,
            "candidate_appendix": None,
            "word_reduction_pct": None,
            "page_reduction_pct": None,
            "cumulative_reduction_pct": None,
            "max_unapproved_main_reduction_pct": None,
            "structural_delta": None,
            "section_changes": [],
        },
        "conservation": {
            "ledger_required": None,
            "candidate_only_full_draft_contract": {
                "required": None,
                "status": "metric_unavailable",
            },
            "expected_baseline_block_ids": [],
            "baseline_block_inventory": [],
            "candidate_block_inventory": [],
            "baseline_object_inventory": [],
            "candidate_object_inventory": [],
            "ledger_validation": [],
            "two_pass_restructure": {
                "required": False,
                "status": "not_applicable",
            },
            "whole_sections_missing_or_moved": [],
            "labels_moved_to_appendix": [],
            "labels_missing_entirely": [],
            "must_remain_main_missing": [],
        },
        "findings": {
            "failures": [],
            "approval_triggers": [],
            "warnings": [str(error)],
        },
    }


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument(
        "--baseline",
        help="Accepted baseline .tex, .md, or .txt source; omit only for a candidate-only full_draft audit",
    )
    cli.add_argument(
        "--candidate", required=True, help="Candidate .tex, .md, or .txt source"
    )
    cli.add_argument("--project-root", help="Root that bounds recursive input/include resolution")
    cli.add_argument("--contract", help="JSON artifact contract or object containing artifact_contract")
    cli.add_argument("--appendix-marker", default=r"\appendix")
    cli.add_argument(
        "--word-metric", choices=("raw_source_words", "normalized_words")
    )
    cli.add_argument("--max-main-reduction", type=float)
    cli.add_argument("--min-main-source-words", type=int)
    cli.add_argument("--baseline-main-pdf-pages", type=float)
    cli.add_argument("--candidate-main-pdf-pages", type=float)
    cli.add_argument("--min-main-pdf-pages", type=float)
    cli.add_argument("--report", required=True, help="Machine-readable JSON output")
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        report = audit(args)
    except MetricUnavailable as exc:
        report = unavailable_report(args, exc)
    report_path = Path(args.report).expanduser()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    status = report["status"]
    metrics = report.get("metrics", {})
    reduction = metrics.get("cumulative_reduction_pct")
    reduction_text = f"; cumulative reduction={reduction:.1%}" if reduction is not None else ""
    print(f"conservation audit: {status}{reduction_text}; report={report_path}")
    for item in report.get("findings", {}).get("failures", []):
        print(f"FAIL: {item}")
    for item in report.get("findings", {}).get("approval_triggers", []):
        print(f"APPROVAL: {item}")
    for item in report.get("findings", {}).get("warnings", []):
        print(f"WARNING: {item}")
    return EXIT_CODES[status]


if __name__ == "__main__":
    sys.exit(main())
