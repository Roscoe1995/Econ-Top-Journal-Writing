#!/usr/bin/env python3
"""Regression tests for the deterministic reader-facing label gate."""

from __future__ import annotations

import copy
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import audit_reader_facing_labels as gate


class ReaderFacingLabelAuditTests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        (self.root / "artifacts").mkdir()
        (self.root / "manifests").mkdir()
        (self.root / "reviews").mkdir()
        (self.root / "reports").mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def signature(
        semantic_type: str = "category",
        *,
        object_id: str = "city_employment_growth",
        statistic_id: str = "comparison",
        unit_code: str = "not_applicable",
        transformation_code: str = "not_applicable",
        comparison_groups: list[str] | None = None,
        direction_code: str = "not_applicable",
        baseline_id: str = "not_applicable",
        numerator_id: str = "not_applicable",
        denominator_id: str = "not_applicable",
        interval_method_id: str = "not_applicable",
        time_basis_id: str = "not_applicable",
    ) -> dict[str, object]:
        return {
            "semantic_type": semantic_type,
            "object_id": object_id,
            "statistic_id": statistic_id,
            "unit_code": unit_code,
            "transformation_code": transformation_code,
            "comparison_groups": comparison_groups or [],
            "direction_code": direction_code,
            "baseline_id": baseline_id,
            "numerator_id": numerator_id,
            "denominator_id": denominator_id,
            "interval_method_id": interval_method_id,
            "time_basis_id": time_basis_id,
        }

    def labels(self, language: str) -> list[dict[str, object]]:
        if language == "zh-CN":
            title = "城市就业增长比较"
            difference = "高收入城市与低收入城市之差（高−低）"
            title_definition = "比较高、低收入城市的年度就业增长。"
            difference_definition = "高收入城市就业增长减去低收入城市就业增长，单位为百分点。"
        else:
            title = "City employment growth comparison"
            difference = "High-income minus low-income cities"
            title_definition = "Comparison of annual employment growth across high- and low-income cities."
            difference_definition = "Employment growth in high-income cities minus growth in low-income cities, in percentage points."
        return [
            {
                "slot_id": "title-1",
                "role": "title",
                "internal_key": "not_applicable",
                "concept_id": "table_title",
                "display_text": title,
                "meaning_status": "confirmed",
                "full_definition": title_definition,
                "semantic_signature": self.signature(
                    "artifact_title",
                    object_id="city_employment_growth",
                    statistic_id="group_comparison",
                ),
                "definition_locations": ["self", "note-1"],
                "exceptions": [],
            },
            {
                "slot_id": "row-gap",
                "role": "row",
                "internal_key": "income_city_gap",
                "concept_id": "income_city_growth_gap",
                "display_text": difference,
                "meaning_status": "confirmed",
                "full_definition": difference_definition,
                "semantic_signature": self.signature(
                    "difference",
                    object_id="city_employment_growth",
                    statistic_id="mean_difference",
                    unit_code="percentage_points",
                    comparison_groups=["high_income_city", "low_income_city"],
                    direction_code="high_minus_low",
                ),
                "definition_locations": ["note-1", "context-1"],
                "exceptions": [],
            },
        ]

    def make_manifest(
        self,
        language: str = "zh-CN",
        *,
        name: str = "primary",
        stage: str = "generated",
        labels: list[dict[str, object]] | None = None,
        artifact_family_id: str = "family-city-growth",
        operation: str = "new_artifact",
    ) -> tuple[Path, dict[str, object]]:
        artifact = self.root / "artifacts" / f"{name}.txt"
        artifact.write_text(f"rendered {name} {language}\n", encoding="utf-8")
        numeric_payload = self.root / "artifacts" / f"{name}-numeric.txt"
        numeric_payload.write_text("1|2|3\n", encoding="utf-8")
        note = (
            "注：样本为2010—2020年城市；差值按高收入组减低收入组计算，单位为百分点。"
            if language == "zh-CN"
            else "Notes: The sample covers cities from 2010 to 2020; differences are high-income minus low-income cities, in percentage points."
        )
        payload: dict[str, object] = {
            "schema_version": "1.0",
            "schema_id": "reader-facing-label-manifest/1.0",
            "manifest_id": f"manifest-{name}",
            "manifest_revision": "1",
            "artifact_family_id": artifact_family_id,
            "artifact": {
                "artifact_id": f"artifact-{name}",
                "path": str(artifact.relative_to(self.root)),
                "sha256": gate.sha256_file(artifact),
                "stage": stage,
                "language": language,
                "operation": operation,
            },
            "numeric_integrity": {
                "canonicalization_id": "test-numeric-canonicalization/1.0",
                "payload_description": "Canonical numeric cells, sample counts, and displayed uncertainty metadata for the synthetic artifact.",
                "producer_source_locator": "scripts/build_synthetic_artifact.py#numeric-payload",
                "numeric_payload_path": str(numeric_payload.relative_to(self.root)),
                "numeric_payload_sha256": gate.sha256_file(numeric_payload),
            },
            "note_status": "provided",
            "notes": [{"note_id": "note-1", "text": note}],
            "contexts": [
                {
                    "context_id": "context-1",
                    "source_locator": "manuscript.md#results",
                    "text": (
                        "正文界定了高低收入城市及差值方向。"
                        if language == "zh-CN"
                        else "The text defines the income groups and subtraction direction."
                    ),
                }
            ],
            "labels": copy.deepcopy(labels if labels is not None else self.labels(language)),
        }
        if operation == "label_only_revision":
            before_payload = self.root / "artifacts" / f"{name}-numeric-before.txt"
            after_payload = self.root / "artifacts" / f"{name}-numeric-after.txt"
            before_payload.write_text("1|2|3\n", encoding="utf-8")
            after_payload.write_text("1|2|3\n", encoding="utf-8")
            payload["numeric_integrity"] = {
                "canonicalization_id": "test-numeric-canonicalization/1.0",
                "payload_description": "Canonical numeric cells before and after a label-only revision.",
                "producer_source_locator": "scripts/build_synthetic_artifact.py#numeric-payload",
                "before_path": str(before_payload.relative_to(self.root)),
                "after_path": str(after_payload.relative_to(self.root)),
                "before_sha256": gate.sha256_file(before_payload),
                "after_sha256": gate.sha256_file(after_payload),
            }
        path = self.root / "manifests" / f"{name}.json"
        self.write_json(path, payload)
        return path, payload

    @staticmethod
    def write_json(path: Path, payload: object) -> None:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def make_review(
        self,
        manifest_path: Path,
        *,
        name: str = "primary",
        close_warnings: bool = True,
    ) -> tuple[Path, dict[str, object], gate.ManifestState, gate.GateAudit]:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        stage = manifest_payload["artifact"]["stage"]
        pre_audit = gate.GateAudit()
        state = gate.validate_manifest(
            manifest_path, self.root, stage, pre_audit, name
        )
        self.assertIsNotNone(state)
        assert state is not None
        reviewer = "isolated-reader"
        reviewed_at = "2026-08-06T12:00:00+08:00"
        label_ids = sorted(state.labels)
        definition_ids = {
            location
            for record in state.labels.values()
            for location in record.get("definition_locations", [])
            if location != "self"
        }
        full_ids = sorted(set(label_ids) | definition_ids)
        language_ids = sorted(set(state.labels) | set(state.notes))
        observed = [
            {
                "element_id": slot_id,
                "text_sha256": gate.sha256_text(
                    gate.normalize_display(str(record.get("display_text", "")))
                ),
            }
            for slot_id, record in sorted(state.labels.items())
        ]
        observed.extend(
            {
                "element_id": note_id,
                "text_sha256": gate.sha256_text(gate.normalize_display(text)),
            }
            for note_id, text in sorted(state.notes.items())
        )
        warnings = pre_audit.warnings(name)
        dispositions = (
            [
                {
                    "finding_id": finding["finding_id"],
                    "disposition": "accepted",
                    "rationale": "The isolated reviewer confirmed the current wording in context and the render remains legible.",
                    "reviewer": reviewer,
                    "reviewed_at": reviewed_at,
                }
                for finding in warnings
            ]
            if close_warnings
            else []
        )
        payload: dict[str, object] = {
            "schema_version": "1.0",
            "schema_id": "reader-facing-label-review/1.0",
            "review_id": f"review-{name}",
            "review_revision": "1",
            "reviewer": reviewer,
            "reviewed_at": reviewed_at,
            "review_mode": "native_isolated_agent",
            "manifest_sha256": gate.sha256_file(manifest_path),
            "artifact_sha256": state.artifact_sha256,
            "stage": state.stage,
            "language": state.language,
            "basic_identity": {
                "status": "pass",
                "reviewed_element_ids": label_ids,
                "summary": "Titles and labels identify the economic objects, statistics, and direction without extra context.",
            },
            "full_recoverability": {
                "status": "pass",
                "reviewed_element_ids": full_ids,
                "summary": "The note and bounded context recover the unit, groups, period, and subtraction direction.",
            },
            "language_style": {
                "status": "pass",
                "reviewed_element_ids": language_ids,
                "summary": "Labels and notes use the natural conventions of the declared language.",
            },
            "numeric_integrity": {
                "status": "pass",
                "canonicalization_id": state.payload["numeric_integrity"]["canonicalization_id"],
                "producer_source_locator": state.payload["numeric_integrity"]["producer_source_locator"],
                "summary": "The reviewer verified that the declared canonical numeric payload covers the numeric cells and result metadata in the artifact.",
                "verified_payloads": [
                    {
                        "path": str(path.relative_to(self.root)),
                        "sha256": digest,
                    }
                    for path, digest in sorted(
                        state.numeric_payload_hashes.items(), key=lambda item: str(item[0])
                    )
                ],
            },
            "render": {
                "status": "pass",
                "artifact_sha256": state.artifact_sha256,
                "inspected_path": str(state.artifact_path.relative_to(self.root)),
                "checks": {key: True for key in gate.RENDER_CHECKS},
                "observed_elements": observed,
            },
            "warning_dispositions": dispositions,
        }
        path = self.root / "reviews" / f"{name}.json"
        self.write_json(path, payload)
        return path, payload, state, pre_audit

    def run_case(
        self,
        manifest_path: Path,
        review_path: Path,
        *,
        stage: str = "generated",
        paired: tuple[Path, Path] | None = None,
        absolute: bool = False,
        output_name: str = "audit.json",
    ) -> tuple[int, dict[str, object]]:
        def arg(path: Path) -> str:
            return str(path if absolute else path.relative_to(self.root))

        argv = [
            "--project-root",
            str(self.root),
            "--manifest",
            arg(manifest_path),
            "--review",
            arg(review_path),
            "--stage",
            stage,
            "--output",
            f"reports/{output_name}",
        ]
        if paired is not None:
            argv.extend(
                [
                    "--paired-manifest",
                    arg(paired[0]),
                    "--paired-review",
                    arg(paired[1]),
                ]
            )
        return gate.run(argv)

    @staticmethod
    def codes(report: dict[str, object]) -> set[str]:
        return {item["code"] for item in report["findings"]}

    def rewrite_and_review(
        self,
        manifest_path: Path,
        payload: dict[str, object],
        *,
        name: str = "primary",
        close_warnings: bool = True,
    ) -> Path:
        self.write_json(manifest_path, payload)
        review_path, _, _, _ = self.make_review(
            manifest_path, name=name, close_warnings=close_warnings
        )
        return review_path

    def test_valid_chinese_relative_paths_and_report_scope(self) -> None:
        manifest, _ = self.make_manifest("zh-CN")
        review, _, _, _ = self.make_review(manifest)
        code, report = self.run_case(manifest, review)
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["scope"], "deterministic_reader_facing_label_gate_only")
        self.assertIs(report["whole_artifact_delivery_authorized"], False)

    def test_valid_english_and_absolute_paths(self) -> None:
        manifest, _ = self.make_manifest("en")
        review, _, _, _ = self.make_review(manifest)
        code, report = self.run_case(manifest, review, absolute=True)
        self.assertEqual((code, report["status"]), (0, "pass"), report)

    def test_valid_bilingual_pair(self) -> None:
        zh_manifest, _ = self.make_manifest("zh-CN", name="zh")
        zh_review, _, _, _ = self.make_review(zh_manifest, name="primary")
        en_manifest, _ = self.make_manifest("en", name="en")
        en_review, _, _, _ = self.make_review(en_manifest, name="paired")
        code, report = self.run_case(
            zh_manifest, zh_review, paired=(en_manifest, en_review)
        )
        self.assertEqual((code, report["status"]), (0, "pass"))
        self.assertEqual(report["summary"]["manifest_count"], 2)

    def test_stage_and_hash_bindings_fail_closed(self) -> None:
        with self.subTest("CLI stage mismatch"):
            manifest, _ = self.make_manifest("en", name="stage")
            review, _, _, _ = self.make_review(manifest, name="primary")
            code, report = self.run_case(manifest, review, stage="final")
            self.assertEqual(code, gate.EXIT_CODES["fail"])
            self.assertIn("cli_stage_mismatch", self.codes(report))
        with self.subTest("artifact hash stale"):
            manifest, _ = self.make_manifest("en", name="artifact-stale")
            review, _, state, _ = self.make_review(manifest, name="primary")
            assert state.artifact_path is not None
            state.artifact_path.write_text("changed\n", encoding="utf-8")
            code, report = self.run_case(manifest, review)
            self.assertEqual(code, gate.EXIT_CODES["fail"])
            self.assertIn("artifact_hash_stale", self.codes(report))
        with self.subTest("review manifest hash stale"):
            manifest, payload = self.make_manifest("en", name="review-stale")
            review, _, _, _ = self.make_review(manifest, name="primary")
            payload["manifest_revision"] = "2"
            self.write_json(manifest, payload)
            code, report = self.run_case(manifest, review)
            self.assertEqual(code, gate.EXIT_CODES["fail"])
            self.assertIn("review_manifest_hash_stale", self.codes(report))

    def test_duplicate_ids_and_strict_json(self) -> None:
        with self.subTest("cross-type duplicate ID"):
            manifest, payload = self.make_manifest("zh-CN", name="duplicate-id")
            payload["notes"][0]["note_id"] = "title-1"
            payload["labels"][0]["definition_locations"] = ["self", "title-1"]
            review = self.rewrite_and_review(manifest, payload)
            code, report = self.run_case(manifest, review)
            self.assertEqual(code, gate.EXIT_CODES["fail"])
            self.assertIn("element_id_cross_type_duplicate", self.codes(report))
        for raw, expected_text in (
            ('{"schema_version":"1.0","schema_version":"1.0"}', "duplicate"),
            ('{"schema_version":NaN}', "non-finite"),
        ):
            with self.subTest(strict_json=expected_text):
                manifest = self.root / "manifests" / f"strict-{expected_text}.json"
                manifest.write_text(raw, encoding="utf-8")
                review = self.root / "reviews" / "missing.json"
                code, report = self.run_case(manifest, review, output_name=f"{expected_text}.json")
                self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
                self.assertIn("invalid_json", self.codes(report))

    def test_overflow_number_lone_surrogate_and_bad_timestamp_fail_safely(self) -> None:
        with self.subTest("overflow number"):
            manifest = self.root / "manifests" / "overflow.json"
            manifest.write_text('{"schema_version":"1.0","value":1e9999}', encoding="ascii")
            review = self.root / "reviews" / "missing-overflow.json"
            code, report = self.run_case(manifest, review, output_name="overflow.json")
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertIn("invalid_json", self.codes(report))
            rendered = json.dumps(report, ensure_ascii=True, allow_nan=False)
            self.assertNotIn("Infinity", rendered)

        with self.subTest("lone surrogate"):
            manifest, payload = self.make_manifest("en", name="surrogate")
            payload["labels"][1]["display_text"] = "\ud800"
            manifest.write_text(
                json.dumps(payload, ensure_ascii=True, allow_nan=False),
                encoding="ascii",
            )
            review = self.root / "reviews" / "missing-surrogate.json"
            code, report = self.run_case(manifest, review, output_name="surrogate.json")
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            rendered = json.dumps(report, ensure_ascii=True, allow_nan=False)
            self.assertNotIn("Infinity", rendered)

        with self.subTest("timestamp"):
            manifest, _ = self.make_manifest("en", name="bad-time")
            review, payload, _, _ = self.make_review(manifest, name="primary")
            payload["reviewed_at"] = "2026-08-06 12:00:00"
            self.write_json(review, payload)
            code, report = self.run_case(manifest, review, output_name="bad-time.json")
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertIn("reviewed_at_timezone_missing", self.codes(report))

    def test_cli_and_symlink_path_escape(self) -> None:
        outside = Path(tempfile.mkdtemp()).resolve()
        try:
            outside_manifest = outside / "outside.json"
            outside_manifest.write_text("{}", encoding="utf-8")
            review = self.root / "reviews" / "missing.json"
            code, report = gate.run(
                [
                    "--project-root", str(self.root),
                    "--manifest", str(outside_manifest),
                    "--review", str(review.relative_to(self.root)),
                    "--stage", "generated",
                    "--output", "reports/path-escape.json",
                ]
            )
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertIn("cli_path_invalid", self.codes(report))

            link = self.root / "manifests" / "escape-link.json"
            link.symlink_to(outside_manifest)
            code, report = gate.run(
                [
                    "--project-root", str(self.root),
                    "--manifest", str(link.relative_to(self.root)),
                    "--review", str(review.relative_to(self.root)),
                    "--stage", "generated",
                    "--output", "reports/symlink-escape.json",
                ]
            )
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertIn("cli_path_invalid", self.codes(report))
        finally:
            outside_manifest.unlink(missing_ok=True)
            outside.rmdir()

    def test_fifo_manifest_and_review_inputs_do_not_block(self) -> None:
        with self.subTest("manifest FIFO"):
            manifest_fifo = self.root / "manifests" / "manifest.fifo"
            os.mkfifo(manifest_fifo)
            started = time.monotonic()
            code, report = gate.run(
                [
                    "--project-root", str(self.root),
                    "--manifest", str(manifest_fifo.relative_to(self.root)),
                    "--review", "reviews/unused.json",
                    "--stage", "generated",
                    "--output", "reports/manifest-fifo.json",
                ]
            )
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 1.0, "FIFO input must be rejected without blocking.")
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertIn("invalid_json", self.codes(report))

        with self.subTest("review FIFO"):
            manifest, _ = self.make_manifest("en", name="review-fifo")
            review_fifo = self.root / "reviews" / "review.fifo"
            os.mkfifo(review_fifo)
            started = time.monotonic()
            code, report = gate.run(
                [
                    "--project-root", str(self.root),
                    "--manifest", str(manifest.relative_to(self.root)),
                    "--review", str(review_fifo.relative_to(self.root)),
                    "--stage", "generated",
                    "--output", "reports/review-fifo.json",
                ]
            )
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 1.0, "FIFO input must be rejected without blocking.")
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertIn("invalid_json", self.codes(report))

    def test_missing_or_nondirectory_project_root_creates_nothing(self) -> None:
        with self.subTest("missing root"):
            missing_root = self.root / "missing-project-root"
            self.assertFalse(missing_root.exists())
            code, report = gate.run(
                [
                    "--project-root", str(missing_root),
                    "--manifest", "manifest.json",
                    "--review", "review.json",
                    "--stage", "generated",
                    "--output", "reports/audit.json",
                ]
            )
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertEqual(report["status"], "audit_incomplete")
            self.assertIn("project_root_invalid", self.codes(report))
            self.assertFalse(missing_root.exists())

        with self.subTest("root is a file"):
            file_root = self.root / "project-root-file"
            file_root.write_text("not a directory\n", encoding="utf-8")
            original = file_root.read_bytes()
            code, report = gate.run(
                [
                    "--project-root", str(file_root),
                    "--manifest", "manifest.json",
                    "--review", "review.json",
                    "--stage", "generated",
                    "--output", "reports/audit.json",
                ]
            )
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertEqual(report["status"], "audit_incomplete")
            self.assertIn("project_root_invalid", self.codes(report))
            self.assertTrue(file_root.is_file())
            self.assertEqual(file_root.read_bytes(), original)

    def test_high_confidence_internal_identifiers_are_failures(self) -> None:
        for index, token in enumerate(
            (
                "ln_y",
                "city_ai_fit",
                "c.age##i.treat",
                "L.gdp",
                "group1",
                "series2",
                "group1 estimate",
                "L2.gdp",
                "F3.x",
                "2bn.year",
                "_cons",
                "__coef",
                "o.treat",
                "1b.year",
                "bn.year",
                "cityAiFit",
                "pandas.DataFrame",
                "model.result — Estimate",
                "foo.bar",
                "café_var",
                "straßeVar",
                "caféScore",
                "éScore",
                "βScore",
                "GDPGrowth",
                "XMLParser",
                "COVIDCases",
                "PhD",
                "DiD",
            )
        ):
            with self.subTest(token=token):
                labels = self.labels("en")
                labels[1]["display_text"] = token
                labels[1]["internal_key"] = "not_applicable"
                manifest, _ = self.make_manifest("en", name=f"code-{index}", labels=labels)
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(manifest, review, output_name=f"code-{index}.json")
                self.assertEqual(code, gate.EXIT_CODES["fail"])
                self.assertIn("internal_identifier_exposed", self.codes(report))

    def test_unicode_casefold_mapping_and_exception_tokens_are_exact(self) -> None:
        self.assertEqual(
            gate.bounded_casefold_literal_spans("ǰVar — measure", "J\u030cVAR"),
            [(0, 4)],
        )
        self.assertEqual(gate.nfkc_literal_occurrences("eﬀect", "f"), [])
        self.assertEqual(gate.nfkc_literal_occurrences("ﬁrm", "f"), [])
        self.assertEqual(gate.nfkc_literal_occurrences("group ⅸ", "x"), [])
        self.assertEqual(gate.nfkc_literal_occurrences("㏓ illumination", "x"), [])
        self.assertEqual(
            gate.nfkc_literal_occurrences("ﬀ estimate", "ff"),
            [(0, 1, True)],
        )
        continuations = (
            "\u0338",
            "\u20e3",
            "\ufe0f",
            "\u203f",
            "\u00b7",
            "\u0387",
            "\u2118",
            "\u212e",
        )
        for mark in continuations:
            self.assertEqual(
                gate.bounded_literal_spans(f"OpenAI{mark} estimate", "OpenAI"),
                [],
            )
            self.assertEqual(
                gate.bounded_literal_spans(f"{mark}OpenAI estimate", "OpenAI"),
                [],
            )
            self.assertEqual(
                gate.bounded_casefold_literal_spans(
                    f"OpenAI{mark} estimate", "openai"
                ),
                [],
            )
            self.assertEqual(
                gate.bounded_nfkc_literal_spans(
                    f"OpenAI{mark} estimate", "OpenAI"
                ),
                [],
            )
        with self.assertRaises(ValueError):
            gate.bounded_nfkc_literal_spans("OpenAI \u00a8\u0316", "OpenAI")

        labels = self.labels("en")
        labels[1]["display_text"] = "OpenAI estimate"
        labels[1]["internal_key"] = "not_applicable"
        labels[1]["exceptions"] = [
            {
                "type": "proper_name",
                "token": "OpenAI",
                "reason": "OpenAI is the exact formal organization name.",
                "reader_definition": "The OpenAI organization.",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="case-sensitive-proper-name-pass", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="case-sensitive-proper-name-pass.json"
        )
        self.assertEqual((code, report["status"]), (0, "pass"), report)

        marked_token_cases = (
            (
                "OpenAI",
                "not_applicable",
                "proper_name",
                {},
            ),
            (
                "PhD",
                "not_applicable",
                "standard_abbreviation",
                {},
            ),
            (
                "city_ai_fit",
                "city_ai_fit",
                "replication_codebook",
                {
                    "source_locator": "codebook.md#marked-key",
                    "reader_label": "City AI fit",
                },
            ),
        )
        compatibility_tokens = {
            "OpenAI": "ＯｐｅｎＡＩ",
            "PhD": "ＰｈＤ",
            "city_ai_fit": "ｃｉｔｙ＿ａｉ＿ｆｉｔ",
        }
        for mark_index, mark in enumerate(continuations):
            for case_index, (
                token,
                internal_key,
                exception_type,
                extra,
            ) in enumerate(marked_token_cases):
                labels = self.labels("en")
                reader_suffix = (
                    " — City AI fit"
                    if exception_type == "replication_codebook"
                    else " estimate"
                )
                labels[1]["display_text"] = f"{token}{mark}{reader_suffix}"
                labels[1]["internal_key"] = internal_key
                labels[1]["exceptions"] = [
                    {
                        "type": exception_type,
                        "token": token,
                        "reason": "Only the unmarked exact token is registered.",
                        "reader_definition": f"Reader definition of {token}.",
                        **extra,
                    }
                ]
                manifest, _ = self.make_manifest(
                    "en",
                    name=f"marked-token-{mark_index}-{case_index}",
                    labels=labels,
                )
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(
                    manifest,
                    review,
                    output_name=f"marked-token-{mark_index}-{case_index}.json",
                )
                self.assertEqual(
                    (code, report["status"]),
                    (gate.EXIT_CODES["fail"], "fail"),
                )
                self.assertIn("typed_exception_token_absent", self.codes(report))

                labels = self.labels("en")
                exact_suffix = (
                    " — City AI fit"
                    if exception_type == "replication_codebook"
                    else " estimate"
                )
                continued_suffix = (
                    " score"
                    if exception_type != "replication_codebook"
                    else " — internal score"
                )
                labels[1]["display_text"] = (
                    f"{token}{exact_suffix} and "
                    f"{token}{mark}{continued_suffix}"
                )
                labels[1]["internal_key"] = internal_key
                labels[1]["exceptions"] = [
                    {
                        "type": exception_type,
                        "token": token,
                        "reason": "Only the bounded exact occurrence is registered.",
                        "reader_definition": f"Reader definition of {token}.",
                        **extra,
                    }
                ]
                manifest, _ = self.make_manifest(
                    "en",
                    name=f"mixed-marked-token-{mark_index}-{case_index}",
                    labels=labels,
                )
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(
                    manifest,
                    review,
                    output_name=(
                        f"mixed-marked-token-{mark_index}-{case_index}.json"
                    ),
                )
                self.assertEqual(
                    (code, report["status"]),
                    (gate.EXIT_CODES["fail"], "fail"),
                    report,
                )
                self.assertIn(
                    "typed_exception_token_boundary_collision", self.codes(report)
                )

                compatibility_token = compatibility_tokens[token]
                labels = self.labels("en")
                labels[1]["display_text"] = (
                    f"{token}{exact_suffix} and "
                    f"{compatibility_token}{mark}{continued_suffix}"
                )
                labels[1]["internal_key"] = internal_key
                labels[1]["exceptions"] = [
                    {
                        "type": exception_type,
                        "token": token,
                        "reason": "Only the visible ASCII occurrence is registered.",
                        "reader_definition": f"Reader definition of {token}.",
                        **extra,
                    }
                ]
                manifest, _ = self.make_manifest(
                    "en",
                    name=f"compat-marked-token-{mark_index}-{case_index}",
                    labels=labels,
                )
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(
                    manifest,
                    review,
                    output_name=(
                        f"compat-marked-token-{mark_index}-{case_index}.json"
                    ),
                )
                self.assertEqual(
                    (code, report["status"]),
                    (gate.EXIT_CODES["fail"], "fail"),
                    report,
                )
                self.assertIn(
                    "typed_exception_normalization_collision", self.codes(report)
                )

                labels = self.labels("en")
                labels[1]["display_text"] = (
                    f"{token}{exact_suffix} and "
                    f"{mark}{token}{mark}{continued_suffix}"
                )
                labels[1]["internal_key"] = internal_key
                labels[1]["exceptions"] = [
                    {
                        "type": exception_type,
                        "token": token,
                        "reason": "Only the bounded exact occurrence is registered.",
                        "reader_definition": f"Reader definition of {token}.",
                        **extra,
                    }
                ]
                manifest, _ = self.make_manifest(
                    "en",
                    name=f"double-marked-token-{mark_index}-{case_index}",
                    labels=labels,
                )
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(
                    manifest,
                    review,
                    output_name=(
                        f"double-marked-token-{mark_index}-{case_index}.json"
                    ),
                )
                self.assertEqual(
                    (code, report["status"]),
                    (gate.EXIT_CODES["fail"], "fail"),
                    report,
                )
                self.assertIn(
                    "typed_exception_token_boundary_collision", self.codes(report)
                )

                labels = self.labels("en")
                labels[1]["display_text"] = (
                    f"{token}{exact_suffix} and "
                    f"{mark}{compatibility_token}{mark}{continued_suffix}"
                )
                labels[1]["internal_key"] = internal_key
                labels[1]["exceptions"] = [
                    {
                        "type": exception_type,
                        "token": token,
                        "reason": "Only the visible ASCII occurrence is registered.",
                        "reader_definition": f"Reader definition of {token}.",
                        **extra,
                    }
                ]
                manifest, _ = self.make_manifest(
                    "en",
                    name=f"double-compat-marked-{mark_index}-{case_index}",
                    labels=labels,
                )
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(
                    manifest,
                    review,
                    output_name=(
                        f"double-compat-marked-{mark_index}-{case_index}.json"
                    ),
                )
                self.assertEqual(
                    (code, report["status"]),
                    (gate.EXIT_CODES["fail"], "fail"),
                    report,
                )
                self.assertIn(
                    "typed_exception_normalization_collision", self.codes(report)
                )

        for index, (token, display_text) in enumerate(
            (
                ("f", "f estimate and eﬀect size"),
                ("f", "f estimate and ﬁrm effect"),
                ("x", "x estimate and group ⅸ"),
                ("x", "x estimate and ㏓ illumination"),
                ("x", "x estimate and eｘposure index"),
                ("x", "x estimate and eˣposure index"),
                ("f", "f estimate and eｆfect size"),
            )
        ):
            labels = self.labels("en")
            labels[1]["display_text"] = display_text
            labels[1]["internal_key"] = "not_applicable"
            labels[1]["exceptions"] = [
                {
                    "type": "mathematical_symbol",
                    "token": token,
                    "reason": "The exact symbol is defined in the model.",
                    "reader_definition": f"The defined {token} parameter.",
                }
            ]
            manifest, _ = self.make_manifest(
                "en", name=f"nfkc-partial-expansion-pass-{index}", labels=labels
            )
            review, _, _, _ = self.make_review(manifest, name="primary")
            code, report = self.run_case(
                manifest,
                review,
                output_name=f"nfkc-partial-expansion-pass-{index}.json",
            )
            self.assertEqual((code, report["status"]), (0, "pass"), report)

        labels = self.labels("en")
        labels[1]["display_text"] = "x estimate and e̸xposure index"
        labels[1]["internal_key"] = "not_applicable"
        labels[1]["exceptions"] = [
            {
                "type": "mathematical_symbol",
                "token": "x",
                "reason": "The exact symbol is defined in the model.",
                "reader_definition": "The defined x parameter.",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="nonraw-short-token-continuation-pass", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest,
            review,
            output_name="nonraw-short-token-continuation-pass.json",
        )
        self.assertEqual((code, report["status"]), (0, "pass"), report)

        labels = self.labels("en")
        labels[1]["display_text"] = "var — Variance and inｖａｒiant estimate"
        labels[1]["internal_key"] = "var"
        labels[1]["exceptions"] = [
            {
                "type": "replication_codebook",
                "token": "var",
                "reason": "The exact raw key is shown in a replication appendix.",
                "reader_definition": "Variance measure.",
                "source_locator": "codebook.md#variance",
                "reader_label": "Variance",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="nfkc-ordinary-word-codebook-pass", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="nfkc-ordinary-word-codebook-pass.json"
        )
        self.assertEqual((code, report["status"]), (0, "pass"), report)

        labels = self.labels("en")
        labels[1]["display_text"] = "IV estimate and Ⅳ score"
        labels[1]["internal_key"] = "not_applicable"
        labels[1]["exceptions"] = [
            {
                "type": "standard_abbreviation",
                "token": "IV",
                "reason": "IV is the defined instrumental-variables abbreviation.",
                "reader_definition": "Instrumental variables.",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="nfkc-complete-expansion-fail", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="nfkc-complete-expansion-fail.json"
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn(
            "typed_exception_normalization_collision", self.codes(report)
        )

        overlapping_exception_cases = (
            (
                "x and x_i estimates",
                (
                    ("mathematical_symbol", "x"),
                    ("mathematical_symbol", "x_i"),
                ),
            ),
            (
                "AI estimate and OpenAI coverage",
                (
                    ("standard_abbreviation", "AI"),
                    ("proper_name", "OpenAI"),
                ),
            ),
            (
                "D estimate and PhD holders",
                (
                    ("standard_abbreviation", "D"),
                    ("standard_abbreviation", "PhD"),
                ),
            ),
        )
        for index, (display_text, typed_tokens) in enumerate(
            overlapping_exception_cases
        ):
            labels = self.labels("en")
            labels[1]["display_text"] = display_text
            labels[1]["internal_key"] = "not_applicable"
            labels[1]["exceptions"] = [
                {
                    "type": exception_type,
                    "token": token,
                    "reason": "The exact visible token has an independent definition.",
                    "reader_definition": f"Reader definition of {token}.",
                }
                for exception_type, token in typed_tokens
            ]
            manifest, _ = self.make_manifest(
                "en", name=f"overlapping-exceptions-pass-{index}", labels=labels
            )
            review, _, _, _ = self.make_review(manifest, name="primary")
            code, report = self.run_case(
                manifest,
                review,
                output_name=f"overlapping-exceptions-pass-{index}.json",
            )
            self.assertEqual((code, report["status"]), (0, "pass"), report)

        labels = self.labels("en")
        labels[1]["internal_key"] = "not_applicable"
        labels[1]["exceptions"] = [
            {
                "type": "proper_name",
                "token": "OpenAI",
                "reason": "OpenAI is the exact formal organization name.",
                "reader_definition": "The OpenAI organization.",
            }
        ]
        labels[1]["display_text"] = "OpenAI \u00a8\u0316"
        manifest, _ = self.make_manifest(
            "en", name="nfkc-mapping-unavailable", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="nfkc-mapping-unavailable.json"
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn(
            "typed_exception_normalization_mapping_unavailable", self.codes(report)
        )

        labels[1]["display_text"] = "OpenAI estimate and openAi score"
        manifest, _ = self.make_manifest(
            "en", name="case-sensitive-proper-name-fail", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="case-sensitive-proper-name-fail.json"
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn("internal_identifier_exposed", self.codes(report))

        labels[1]["display_text"] = "OpenAI and openAi"
        labels[1]["exceptions"] = [
            {
                "type": "proper_name",
                "token": "OpenAI and openAi",
                "reason": "Attempted phrase-wide exception.",
                "reader_definition": "Two differently cased visible tokens.",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="phrase-wide-proper-name-fail", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="phrase-wide-proper-name-fail.json"
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn("internal_identifier_exposed", self.codes(report))

        labels[1]["display_text"] = "OpenAI and ＯｐｅｎＡＩ"
        labels[1]["exceptions"] = [
            {
                "type": "proper_name",
                "token": "OpenAI",
                "reason": "Only the ASCII spelling is the registered name.",
                "reader_definition": "The OpenAI organization.",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="compatibility-proper-name-fail", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="compatibility-proper-name-fail.json"
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn("typed_exception_normalization_collision", self.codes(report))

        labels = self.labels("en")
        labels[1]["display_text"] = (
            "city_ai_fit — City AI fit and CITY_AI_FIT score"
        )
        labels[1]["internal_key"] = "city_ai_fit"
        labels[1]["exceptions"] = [
            {
                "type": "replication_codebook",
                "token": "city_ai_fit",
                "reason": "The exact lower-case key is shown in a codebook.",
                "reader_definition": "City AI fit measure.",
                "source_locator": "codebook.md#city-ai-fit",
                "reader_label": "City AI fit",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="case-sensitive-codebook", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="case-sensitive-codebook.json"
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn("internal_identifier_exposed", self.codes(report))

        compatibility_replication_cases = (
            ("city_ai_fit", "ｃｉｔｙ＿ａｉ＿ｆｉｔ", "City AI fit"),
            ("model.result", "ｍｏｄｅｌ．ｒｅｓｕｌｔ", "Estimate"),
            ("c.age", "ｃ．ａｇｅ", "Age"),
        )
        for index, (token, compatibility_token, reader_label) in enumerate(
            compatibility_replication_cases
        ):
            labels = self.labels("en")
            labels[1]["display_text"] = (
                f"{token} — {reader_label} and {compatibility_token} score"
            )
            labels[1]["internal_key"] = token
            labels[1]["exceptions"] = [
                {
                    "type": "replication_codebook",
                    "token": token,
                    "reason": "Only the exact ASCII key is registered.",
                    "reader_definition": f"Reader definition of {reader_label}.",
                    "source_locator": f"codebook.md#compatibility-{index}",
                    "reader_label": reader_label,
                }
            ]
            manifest, _ = self.make_manifest(
                "en", name=f"compatibility-codebook-{index}", labels=labels
            )
            review, _, _, _ = self.make_review(manifest, name="primary")
            code, report = self.run_case(
                manifest,
                review,
                output_name=f"compatibility-codebook-{index}.json",
            )
            self.assertEqual(
                (code, report["status"]),
                (gate.EXIT_CODES["fail"], "fail"),
            )
            self.assertIn(
                "typed_exception_normalization_collision", self.codes(report)
            )

        for index, suffix in enumerate(("-score", "/score")):
            labels = self.labels("en")
            labels[1]["display_text"] = (
                "city_ai_fit — City AI fit and "
                f"ｃｉｔｙ＿ａｉ＿ｆｉｔ{suffix}"
            )
            labels[1]["internal_key"] = "city_ai_fit"
            labels[1]["exceptions"] = [
                {
                    "type": "replication_codebook",
                    "token": "city_ai_fit",
                    "reason": "Only the exact ASCII key is registered.",
                    "reader_definition": "City AI fit measure.",
                    "source_locator": f"codebook.md#suffix-{index}",
                    "reader_label": "City AI fit",
                }
            ]
            manifest, _ = self.make_manifest(
                "en", name=f"compatibility-suffix-{index}", labels=labels
            )
            review, _, _, _ = self.make_review(manifest, name="primary")
            code, report = self.run_case(
                manifest,
                review,
                output_name=f"compatibility-suffix-{index}.json",
            )
            self.assertEqual(
                (code, report["status"]),
                (gate.EXIT_CODES["fail"], "fail"),
            )
            self.assertIn(
                "typed_exception_normalization_collision", self.codes(report)
            )

        delimiter_exception_cases = (
            (
                "ISCO-08",
                "ＩＳＣＯ－０８",
                "formal_classification_code",
            ),
            ("AI/ML", "ＡＩ／ＭＬ", "standard_abbreviation"),
            ("GDP-AI", "ＧＤＰ－ＡＩ", "standard_abbreviation"),
            ("GDP–AI", "ＧＤＰ–ＡＩ", "standard_abbreviation"),
        )
        for index, (token, compatibility_token, exception_type) in enumerate(
            delimiter_exception_cases
        ):
            labels = self.labels("en")
            labels[1]["display_text"] = f"{token} and {compatibility_token}"
            labels[1]["internal_key"] = "not_applicable"
            labels[1]["exceptions"] = [
                {
                    "type": exception_type,
                    "token": token,
                    "reason": "Only the exact ASCII-form token is registered.",
                    "reader_definition": f"Reader definition of {token}.",
                }
            ]
            manifest, _ = self.make_manifest(
                "en", name=f"compatibility-delimiter-{index}", labels=labels
            )
            review, _, _, _ = self.make_review(manifest, name="primary")
            code, report = self.run_case(
                manifest,
                review,
                output_name=f"compatibility-delimiter-{index}.json",
            )
            self.assertEqual(
                (code, report["status"]),
                (gate.EXIT_CODES["fail"], "fail"),
            )
            self.assertIn(
                "typed_exception_normalization_collision", self.codes(report)
            )

    def test_warning_fingerprint_must_be_current_and_closed(self) -> None:
        labels = self.labels("en")
        labels[1]["display_text"] = "AI Fit Avg"
        manifest, _ = self.make_manifest("en", name="warning", labels=labels)
        review, payload, _, pre_audit = self.make_review(
            manifest, name="primary", close_warnings=False
        )
        self.assertTrue(pre_audit.warnings("primary"))
        code, report = self.run_case(manifest, review)
        self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
        self.assertIn("warning_unresolved", self.codes(report))

        review, payload, _, _ = self.make_review(
            manifest, name="primary", close_warnings=True
        )
        code, report = self.run_case(manifest, review, output_name="warning-closed.json")
        self.assertEqual((code, report["status"]), (0, "pass"))

        payload["warning_dispositions"][0]["finding_id"] = "0" * 64
        self.write_json(review, payload)
        code, report = self.run_case(manifest, review, output_name="warning-stale.json")
        self.assertEqual(code, gate.EXIT_CODES["fail"])
        self.assertIn("warning_disposition_stale", self.codes(report))

        labels = self.labels("en")
        labels.extend(
            [
                {
                    "slot_id": "panel-employment",
                    "role": "panel",
                    "internal_key": "not_applicable",
                    "concept_id": "employment_panel",
                    "display_text": "Panel A. Employment",
                    "meaning_status": "confirmed",
                    "full_definition": "Panel A reports employment outcomes.",
                    "semantic_signature": self.signature(
                        "category", object_id="employment_panel"
                    ),
                    "definition_locations": ["note-1"],
                    "exceptions": [],
                },
                {
                    "slot_id": "mean-employment",
                    "role": "row",
                    "internal_key": "mean_employment",
                    "concept_id": "mean_employment",
                    "display_text": "Mean",
                    "meaning_status": "confirmed",
                    "full_definition": "Mean employment in the sample.",
                    "semantic_signature": self.signature(
                        "category", object_id="mean_employment"
                    ),
                    "definition_locations": ["note-1"],
                    "exceptions": [],
                },
                {
                    "slot_id": "panel-wages",
                    "role": "panel",
                    "internal_key": "not_applicable",
                    "concept_id": "wages_panel",
                    "display_text": "Panel B. Wages",
                    "meaning_status": "confirmed",
                    "full_definition": "Panel B reports wage outcomes.",
                    "semantic_signature": self.signature(
                        "category", object_id="wages_panel"
                    ),
                    "definition_locations": ["note-1"],
                    "exceptions": [],
                },
                {
                    "slot_id": "mean-wages",
                    "role": "row",
                    "internal_key": "mean_wages",
                    "concept_id": "mean_wages",
                    "display_text": "Mean",
                    "meaning_status": "confirmed",
                    "full_definition": "Mean wages in the sample.",
                    "semantic_signature": self.signature(
                        "category", object_id="mean_wages"
                    ),
                    "definition_locations": ["note-1"],
                    "exceptions": [],
                },
            ]
        )
        manifest, _ = self.make_manifest(
            "en", name="panel-scoped-repeated-label", labels=labels
        )
        review, payload, panel_state, pre_audit = self.make_review(
            manifest, name="panel-scoped", close_warnings=True
        )
        panel_packet_ids = [
            element["slot_id"] for element in panel_state.basic_packet["elements"]
        ]
        self.assertLess(
            panel_packet_ids.index("panel-employment"),
            panel_packet_ids.index("mean-employment"),
        )
        self.assertLess(
            panel_packet_ids.index("mean-employment"),
            panel_packet_ids.index("panel-wages"),
        )
        self.assertLess(
            panel_packet_ids.index("panel-wages"),
            panel_packet_ids.index("mean-wages"),
        )
        self.assertTrue(
            any(
                finding["code"] == "possible_display_label_collision"
                for finding in pre_audit.findings
            )
        )
        code, report = self.run_case(
            manifest, review, output_name="panel-scoped-repeated-label.json"
        )
        self.assertEqual((code, report["status"]), (0, "pass"), report)

        payload["basic_identity"]["status"] = "fail"
        payload["basic_identity"]["summary"] = (
            "Within one scope, the repeated label does not identify its object."
        )
        self.write_json(review, payload)
        code, report = self.run_case(
            manifest, review, output_name="same-scope-repeated-label.json"
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn("basic_identity_review_not_pass", self.codes(report))

        for index, exceptions in enumerate(
            (
                [],
                [
                    {
                        "type": "standard_abbreviation",
                        "token": "U.S.",
                        "reason": "This is the conventional geographic abbreviation.",
                        "reader_definition": "United States.",
                    }
                ],
            )
        ):
            labels = self.labels("en")
            labels[1]["display_text"] = "U.S. employment"
            labels[1]["internal_key"] = "not_applicable"
            labels[1]["exceptions"] = exceptions
            manifest, _ = self.make_manifest(
                "en", name=f"dotted-abbreviation-{index}", labels=labels
            )
            review, _, _, _ = self.make_review(manifest, name="primary")
            code, report = self.run_case(
                manifest, review, output_name=f"dotted-abbreviation-{index}.json"
            )
            self.assertEqual((code, report["status"]), (0, "pass"), report)

        for index, display_text in enumerate(
            (
                "Ph.D. holders",
                "M.Phil. graduates",
                "B.Sc. graduates",
                "M.Sc. graduates",
            )
        ):
            labels = self.labels("en")
            labels[1]["display_text"] = display_text
            labels[1]["internal_key"] = "not_applicable"
            labels[1]["exceptions"] = []
            manifest, _ = self.make_manifest(
                "en", name=f"degree-abbreviation-{index}", labels=labels
            )
            review, _, _, _ = self.make_review(manifest, name="primary")
            code, report = self.run_case(
                manifest, review, output_name=f"degree-abbreviation-{index}.json"
            )
            self.assertEqual((code, report["status"]), (0, "pass"), report)

        labels = self.labels("en")
        labels[1]["display_text"] = "Ph.D. holders"
        labels[1]["internal_key"] = "not_applicable"
        labels[1]["exceptions"] = [
            {
                "type": "standard_abbreviation",
                "token": "Ph.D.",
                "reason": "This is the conventional degree abbreviation.",
                "reader_definition": "Doctor of Philosophy degree.",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="degree-abbreviation-typed", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="degree-abbreviation-typed.json"
        )
        self.assertEqual((code, report["status"]), (0, "pass"), report)

        for index, token in enumerate(("PhD", "DiD")):
            labels = self.labels("en")
            labels[1]["display_text"] = f"{token} estimate"
            labels[1]["internal_key"] = "not_applicable"
            labels[1]["exceptions"] = [
                {
                    "type": "standard_abbreviation",
                    "token": token,
                    "reason": "This is a conventional reader-facing abbreviation.",
                    "reader_definition": f"Conventional meaning of {token}.",
                }
            ]
            manifest, _ = self.make_manifest(
                "en", name=f"mixed-case-abbreviation-{index}", labels=labels
            )
            review, _, _, _ = self.make_review(manifest, name="primary")
            code, report = self.run_case(
                manifest,
                review,
                output_name=f"mixed-case-abbreviation-{index}.json",
            )
            self.assertEqual((code, report["status"]), (0, "pass"), report)

        labels = self.labels("en")
        labels[1]["display_text"] = "cityAiFit estimate"
        labels[1]["internal_key"] = "not_applicable"
        labels[1]["exceptions"] = [
            {
                "type": "standard_abbreviation",
                "token": "cityAiFit",
                "reason": "Attempted mixed-case exception.",
                "reader_definition": "An internal score.",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="mixed-case-abbreviation-bypass", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="mixed-case-abbreviation-bypass.json"
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn("typed_exception_token_incompatible", self.codes(report))
        self.assertIn("internal_identifier_exposed", self.codes(report))

        labels = self.labels("zh-CN")
        labels[1]["display_text"] = "城市GDP"
        labels[1]["internal_key"] = "not_applicable"
        labels[1]["exceptions"] = []
        manifest, _ = self.make_manifest(
            "zh-CN", name="cjk-uppercase-not-camel", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="cjk-uppercase-not-camel.json"
        )
        self.assertEqual((code, report["status"]), (0, "pass"), report)

        unicode_replication_cases = (
            (
                "café_var",
                "cafe\u0301_var",
                "Log café measure",
                "cafe\u0301_var — Log café measure",
            ),
            (
                "straßeVar",
                "straßeVar",
                "Street measure",
                "straßeVar—Street measure",
            ),
            (
                "straßeVar",
                "straßeVar",
                "街道指标",
                "straßeVar（街道指标）",
            ),
        )
        for index, (internal_key, token, reader_label, display_text) in enumerate(
            unicode_replication_cases
        ):
            labels = self.labels("en")
            labels[1]["display_text"] = display_text
            labels[1]["internal_key"] = internal_key
            labels[1]["exceptions"] = [
                {
                    "type": "replication_codebook",
                    "token": token,
                    "reason": "Shown in a Unicode-aware replication codebook.",
                    "reader_definition": "The public measure beside the raw key.",
                    "source_locator": f"codebook.md#unicode-{index}",
                    "reader_label": reader_label,
                }
            ]
            manifest, _ = self.make_manifest(
                "en", name=f"unicode-codebook-{index}", labels=labels
            )
            review, _, _, _ = self.make_review(manifest, name="primary")
            code, report = self.run_case(
                manifest, review, output_name=f"unicode-codebook-{index}.json"
            )
            self.assertEqual((code, report["status"]), (0, "pass"), report)

        labels = self.labels("en")
        labels[1]["display_text"] = "OpenAlex coverage"
        labels[1]["internal_key"] = "not_applicable"
        labels[1]["exceptions"] = [
            {
                "type": "proper_name",
                "token": "OpenAlex",
                "reason": "OpenAlex is the formal product name.",
                "reader_definition": "The OpenAlex scholarly-data platform.",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="proper-name-without-internal-key", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="proper-name-without-internal-key.json"
        )
        self.assertEqual((code, report["status"]), (0, "pass"), report)

        labels = self.labels("en")
        labels[1]["display_text"] = "model.result — Estimate"
        labels[1]["internal_key"] = "model.result"
        labels[1]["exceptions"] = [
            {
                "type": "replication_codebook",
                "token": "model.result",
                "reason": "Shown in the replication codebook.",
                "reader_definition": "The reported model estimate.",
                "source_locator": "codebook.md#model-result",
                "reader_label": "Estimate",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="dotted-codebook", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="dotted-codebook.json"
        )
        self.assertEqual((code, report["status"]), (0, "pass"), report)

    def test_vague_labels_and_unresolved_meaning_require_clarification(self) -> None:
        for index, text in enumerate(
            ("基准值", "差异", "高组/低组", "样本组之间的变化速度不同")
        ):
            with self.subTest(text=text):
                labels = self.labels("zh-CN")
                labels[1]["display_text"] = text
                manifest, _ = self.make_manifest("zh-CN", name=f"vague-{index}", labels=labels)
                review, _, _, pre_audit = self.make_review(manifest, name="primary")
                self.assertIn(
                    "opaque_basic_identity",
                    {finding["code"] for finding in pre_audit.findings},
                )
                code, report = self.run_case(manifest, review, output_name=f"vague-{index}.json")
                self.assertEqual(
                    (code, report["status"]),
                    (gate.EXIT_CODES["clarification_required"], "clarification_required"),
                )

        labels = self.labels("en")
        labels[1]["display_text"] = "High group/low group"
        manifest, _ = self.make_manifest("en", name="vague-en-groups", labels=labels)
        review, _, _, pre_audit = self.make_review(manifest, name="primary")
        self.assertIn(
            "opaque_basic_identity",
            {finding["code"] for finding in pre_audit.findings},
        )
        code, report = self.run_case(manifest, review, output_name="vague-en-groups.json")
        self.assertEqual(
            (code, report["status"]),
            (gate.EXIT_CODES["clarification_required"], "clarification_required"),
        )

        labels = self.labels("zh-CN")
        labels[1]["meaning_status"] = "unresolved"
        labels[1]["full_definition"] = None
        manifest, _ = self.make_manifest("zh-CN", name="unresolved", labels=labels)
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(manifest, review, output_name="unresolved.json")
        self.assertEqual(code, gate.EXIT_CODES["clarification_required"])
        self.assertIn("label_meaning_unresolved", self.codes(report))

    def test_semantic_type_required_fields(self) -> None:
        cases = {
            "difference": self.signature("difference"),
            "ratio": self.signature("ratio", unit_code="percent"),
            "interaction": self.signature("interaction", comparison_groups=["treatment"]),
            "growth_rate": self.signature("growth_rate", unit_code="percent"),
            "index": self.signature("index"),
            "interval": self.signature("interval", unit_code="points"),
            "level": self.signature("level"),
            "parameter": self.signature("parameter"),
        }
        for index, (semantic_type, signature) in enumerate(cases.items()):
            with self.subTest(semantic_type=semantic_type):
                labels = self.labels("en")
                labels[1]["semantic_signature"] = signature
                manifest, _ = self.make_manifest("en", name=f"semantic-{index}", labels=labels)
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(manifest, review, output_name=f"semantic-{index}.json")
                self.assertEqual(code, gate.EXIT_CODES["fail"])
                self.assertTrue(
                    {"semantic_required_value_missing", "difference_groups_missing", "interaction_components_missing"}
                    & self.codes(report)
                )

        labels = self.labels("en")
        labels[1]["semantic_signature"]["unit_code"] = "not_applicable"
        manifest, _ = self.make_manifest(
            "en", name="difference-unit-required", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="difference-unit-required.json"
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertTrue(
            any(
                finding["code"] == "semantic_required_value_missing"
                and finding.get("field") == "unit_code"
                and finding.get("semantic_type") == "difference"
                for finding in report["findings"]
            )
        )

    def test_complete_ratio_growth_index_interval_and_transform_metadata_pass(self) -> None:
        labels = self.labels("en")
        complete_rows = [
            (
                "Assessed occupations as a share of all occupations",
                self.signature(
                    "ratio",
                    object_id="assessed_occupation_share",
                    statistic_id="share",
                    unit_code="percent",
                    numerator_id="assessed_occupations",
                    denominator_id="all_occupations",
                ),
            ),
            (
                "Annual employment growth",
                self.signature(
                    "growth_rate",
                    object_id="employment",
                    statistic_id="annual_growth",
                    unit_code="percent",
                    transformation_code="log_difference",
                    time_basis_id="year_over_year",
                ),
            ),
            (
                "Standardized task-exposure index",
                self.signature(
                    "index",
                    object_id="task_exposure",
                    statistic_id="standardized_index",
                    unit_code="standard_deviations",
                    transformation_code="z_score_within_sample",
                    direction_code="higher_means_more_exposure",
                ),
            ),
            (
                "High exposure × post-policy period",
                self.signature(
                    "interaction",
                    object_id="employment_growth",
                    statistic_id="interaction_coefficient",
                    unit_code="percentage_points",
                    comparison_groups=["high_exposure", "post_policy"],
                    direction_code="high_exposure_post_relative_to_baseline",
                    baseline_id="low_exposure_pre_policy",
                ),
            ),
            (
                "Bootstrap 95% confidence interval",
                self.signature(
                    "interval",
                    object_id="city_employment_growth",
                    statistic_id="confidence_interval_95",
                    unit_code="percentage_points",
                    interval_method_id="occupation_cluster_bootstrap_1000",
                ),
            ),
        ]
        for index, (display, signature) in enumerate(complete_rows):
            labels.append(
                {
                    "slot_id": f"complete-{index}",
                    "role": "row",
                    "internal_key": f"source_key_{index}",
                    "concept_id": f"complete_concept_{index}",
                    "display_text": display,
                    "meaning_status": "confirmed",
                    "full_definition": f"Complete reader-facing definition for {display}.",
                    "semantic_signature": signature,
                    "definition_locations": ["note-1", "context-1"],
                    "exceptions": [],
                }
            )
        manifest, _ = self.make_manifest("en", name="complete-semantics", labels=labels)
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(manifest, review)
        self.assertEqual((code, report["status"]), (0, "pass"))

    def test_valid_typed_exceptions_and_invalid_exception_records(self) -> None:
        labels = self.labels("en")
        exception_rows = [
            ("GDP growth", "GDP", "standard_abbreviation"),
            ("DID estimate", "DID", "standard_abbreviation"),
            ("R²", "R²", "standard_abbreviation"),
            ("Q1/Q4", "Q1", "standard_abbreviation"),
            ("α", "α", "mathematical_symbol"),
            ("ISCO-08 employment", "ISCO-08", "formal_classification_code"),
            ("ln_wage — Log employment", "ln_wage", "replication_codebook"),
            ("(1)", "(1)", "column_number"),
            ("World Bank WDI", "World Bank WDI", "proper_name"),
        ]
        for index, (display, token, exception_type) in enumerate(exception_rows):
            labels.append(
                {
                    "slot_id": f"exception-{index}",
                    "role": "column" if exception_type == "column_number" else "row",
                    "internal_key": "ln_wage" if exception_type == "replication_codebook" else "not_applicable",
                    "concept_id": f"exception_concept_{index}",
                    "display_text": display,
                    "meaning_status": "confirmed",
                    "full_definition": f"Reader definition for {display}.",
                    "semantic_signature": self.signature(
                        "category", object_id=f"exception_object_{index}"
                    ),
                    "definition_locations": ["note-1"],
                    "exceptions": [
                        {
                            "type": exception_type,
                            "token": token,
                            "reason": "This exact form is the reader-facing conventional form.",
                            "reader_definition": f"Definition of {display}.",
                            **(
                                {
                                    "source_locator": "codebook.md#ln-wage",
                                    "reader_label": "Log employment",
                                }
                                if exception_type == "replication_codebook"
                                else {}
                            ),
                        }
                    ],
                }
            )
        manifest, _ = self.make_manifest("en", name="exceptions-valid", labels=labels)
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(manifest, review)
        self.assertEqual((code, report["status"]), (0, "pass"))

        for index, mutation in enumerate(("unknown", "wildcard", "absent", "missing_reason")):
            with self.subTest(mutation=mutation):
                bad_labels = self.labels("en")
                record = {
                    "type": "standard_abbreviation",
                    "token": "GDP",
                    "reason": "Conventional abbreviation.",
                    "reader_definition": "Gross domestic product.",
                }
                bad_labels[1]["display_text"] = "GDP difference"
                bad_labels[1]["exceptions"] = [record]
                if mutation == "unknown":
                    record["type"] = "anything_goes"
                elif mutation == "wildcard":
                    record["token"] = "G*"
                elif mutation == "absent":
                    record["token"] = "DID"
                else:
                    del record["reason"]
                manifest, _ = self.make_manifest("en", name=f"exceptions-bad-{index}", labels=bad_labels)
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(manifest, review, output_name=f"exceptions-bad-{index}.json")
                self.assertNotEqual(code, 0)
                self.assertTrue(any(value.startswith("typed_exception") for value in self.codes(report)))

    def test_defined_subscripted_math_symbols_pass_without_whitelisting_code_names(self) -> None:
        labels = self.labels("en")
        for index, token in enumerate(("x_i", "β_i", "x₁", "y₂", "β₁")):
            labels.append(
                {
                    "slot_id": f"math-subscript-{index}",
                    "role": "row",
                    "internal_key": "not_applicable",
                    "concept_id": f"defined_math_symbol_{index}",
                    "display_text": token,
                    "meaning_status": "confirmed",
                    "full_definition": f"The defined model symbol {token}.",
                    "semantic_signature": self.signature(
                        "category", object_id=f"defined_math_symbol_{index}"
                    ),
                    "definition_locations": ["note-1", "context-1"],
                    "exceptions": [
                        {
                            "type": "mathematical_symbol",
                            "token": token,
                            "reason": "This exact subscripted symbol is defined in the model.",
                            "reader_definition": f"Definition of {token} in the model.",
                        }
                    ],
                }
            )
        manifest, _ = self.make_manifest("en", name="math-subscripts", labels=labels)
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(manifest, review)
        self.assertEqual((code, report["status"]), (0, "pass"), report)

        for index, token in enumerate(("x1", "y2")):
            with self.subTest(unregistered_ascii_symbol_like_key=token):
                ascii_labels = self.labels("en")
                ascii_labels[1]["display_text"] = token
                ascii_labels[1]["internal_key"] = "not_applicable"
                ascii_labels[1]["exceptions"] = []
                manifest, _ = self.make_manifest(
                    "en", name=f"ascii-symbol-like-key-{index}", labels=ascii_labels
                )
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(manifest, review)
                self.assertEqual(
                    (code, report["status"]),
                    (gate.EXIT_CODES["fail"], "fail"),
                    report,
                )
                self.assertIn("internal_identifier_exposed", self.codes(report))

        invalid_math_labels = self.labels("en")
        invalid_math_labels[1]["display_text"] = "x1"
        invalid_math_labels[1]["internal_key"] = "not_applicable"
        invalid_math_labels[1]["exceptions"] = [
            {
                "type": "mathematical_symbol",
                "token": "x1",
                "reason": "Incorrect attempt to classify a code key as mathematics.",
                "reader_definition": "An unregistered ASCII code key.",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="ascii-math-symbol-bypass", labels=invalid_math_labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(manifest, review)
        self.assertEqual(code, gate.EXIT_CODES["fail"])
        self.assertIn("typed_exception_token_incompatible", self.codes(report))
        self.assertIn("internal_identifier_exposed", self.codes(report))

        bad_labels = self.labels("en")
        bad_labels[1]["display_text"] = "city_ai_fit"
        bad_labels[1]["internal_key"] = "not_applicable"
        bad_labels[1]["exceptions"] = [
            {
                "type": "mathematical_symbol",
                "token": "city_ai_fit",
                "reason": "Incorrect attempt to classify a code variable as mathematics.",
                "reader_definition": "An internal code variable.",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="math-symbol-code-bypass", labels=bad_labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(manifest, review)
        self.assertEqual(code, gate.EXIT_CODES["fail"])
        self.assertIn("typed_exception_token_incompatible", self.codes(report))
        self.assertIn("internal_identifier_exposed", self.codes(report))

    def test_raw_code_cannot_use_proper_name_or_incomplete_codebook_exception(self) -> None:
        cases: list[tuple[str, dict[str, object], str, str]] = [
            (
                "proper-name",
                {
                    "type": "proper_name",
                    "token": "ln_y",
                    "reason": "Claimed as a proper name.",
                    "reader_definition": "An internal outcome variable.",
                },
                "fail",
                "internal_identifier_exposed",
            ),
            (
                "codebook-missing-fields",
                {
                    "type": "replication_codebook",
                    "token": "ln_y",
                    "reason": "Shown in a replication appendix.",
                    "reader_definition": "Natural log of the outcome.",
                },
                "audit_incomplete",
                "replication_codebook_source_missing",
            ),
            (
                "codebook-no-reader-label-in-display",
                {
                    "type": "replication_codebook",
                    "token": "ln_y",
                    "reason": "Shown in a replication appendix.",
                    "reader_definition": "Natural log of the outcome.",
                    "source_locator": "codebook.md#ln-y",
                    "reader_label": "Log outcome",
                },
                "fail",
                "replication_codebook_reader_label_not_displayed",
            ),
        ]
        for index, (name, exception, expected_status, expected_code) in enumerate(cases):
            with self.subTest(name=name):
                labels = self.labels("en")
                labels[1]["display_text"] = "ln_y"
                labels[1]["internal_key"] = "ln_y"
                labels[1]["exceptions"] = [exception]
                manifest, _ = self.make_manifest("en", name=f"exception-bypass-{index}", labels=labels)
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(manifest, review, output_name=f"exception-bypass-{index}.json")
                self.assertEqual(code, gate.EXIT_CODES[expected_status])
                self.assertIn(expected_code, self.codes(report))

        labels = self.labels("en")
        labels[1]["display_text"] = "ln_wage"
        labels[1]["internal_key"] = "ln_wage"
        labels[1]["exceptions"] = [
            {
                "type": "replication_codebook",
                "token": "ln_wage",
                "reason": "Shown in a replication appendix.",
                "reader_definition": "Natural log of wages.",
                "source_locator": "codebook.md#ln-wage",
                "reader_label": "wage",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="codebook-substring-bypass", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="codebook-substring-bypass.json"
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn("replication_codebook_reader_label_not_displayed", self.codes(report))

        mismatched_codebook_records = (
            (
                "case-mismatch",
                "ln_wage",
                "LN_WAGE — Log wages",
                "LN_WAGE",
                "Log wages",
                "replication_codebook_internal_key_mismatch",
            ),
            (
                "different-key",
                "ln_wage",
                "ln_income — Log income",
                "ln_income",
                "Log income",
                "replication_codebook_internal_key_mismatch",
            ),
            (
                "unbound-key",
                "not_applicable",
                "ln_wage — Log wages",
                "ln_wage",
                "Log wages",
                "replication_codebook_internal_key_unbound",
            ),
            (
                "whole-display-reader-label",
                "ln_wage",
                "ln_wage — Log wages",
                "ln_wage",
                "ln_wage — Log wages",
                "replication_codebook_reader_label_not_displayed",
            ),
            (
                "overlapping-reader-label",
                "ln_wage",
                "ln_wage — Log ln_wage",
                "ln_wage",
                "Log ln_wage",
                "replication_codebook_reader_label_not_displayed",
            ),
        )
        for index, (
            name,
            internal_key,
            display_text,
            token,
            reader_label,
            expected_code,
        ) in enumerate(mismatched_codebook_records):
            with self.subTest(codebook_binding=name):
                labels = self.labels("en")
                labels[1]["display_text"] = display_text
                labels[1]["internal_key"] = internal_key
                labels[1]["exceptions"] = [
                    {
                        "type": "replication_codebook",
                        "token": token,
                        "reason": "Shown in a replication appendix.",
                        "reader_definition": "The public meaning beside the raw key.",
                        "source_locator": f"codebook.md#binding-{index}",
                        "reader_label": reader_label,
                    }
                ]
                manifest, _ = self.make_manifest(
                    "en", name=f"codebook-binding-{index}", labels=labels
                )
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(
                    manifest, review, output_name=f"codebook-binding-{index}.json"
                )
                self.assertEqual(
                    (code, report["status"]),
                    (gate.EXIT_CODES["fail"], "fail"),
                )
                self.assertIn(expected_code, self.codes(report))

        for index, (display_text, token, reader_label) in enumerate(
            (
                ("x — Exposure index", "x", "Exposure index"),
                ("var — Invariant effect", "var", "Invariant effect"),
                ("ln_wage（工资对数）", "ln_wage", "工资对数"),
            )
        ):
            with self.subTest(valid_independent_reader_label=display_text):
                labels = self.labels("en")
                labels[1]["display_text"] = display_text
                labels[1]["internal_key"] = token
                labels[1]["exceptions"] = [
                    {
                        "type": "replication_codebook",
                        "token": token,
                        "reason": "Shown in a replication appendix.",
                        "reader_definition": "A public definition beside the raw code token.",
                        "source_locator": f"codebook.md#valid-{index}",
                        "reader_label": reader_label,
                    }
                ]
                manifest, _ = self.make_manifest(
                    "en", name=f"codebook-independent-{index}", labels=labels
                )
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(
                    manifest,
                    review,
                    output_name=f"codebook-independent-{index}.json",
                )
                self.assertEqual((code, report["status"]), (0, "pass"), report)

        composite_cases = (
            ("c.age##i.treat", "Age-treatment interaction"),
            ("L.gdp#i.year", "Lagged GDP-year interaction"),
        )
        for index, (token, reader_label) in enumerate(composite_cases):
            with self.subTest(replication_composite=token):
                labels = self.labels("en")
                labels[1]["display_text"] = f"{token} — {reader_label}"
                labels[1]["internal_key"] = token
                labels[1]["exceptions"] = [
                    {
                        "type": "replication_codebook",
                        "token": token,
                        "reason": "Shown in a replication appendix.",
                        "reader_definition": reader_label,
                        "source_locator": f"codebook.md#composite-{index}",
                        "reader_label": reader_label,
                    }
                ]
                manifest, _ = self.make_manifest(
                    "en", name=f"codebook-composite-pass-{index}", labels=labels
                )
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(
                    manifest,
                    review,
                    output_name=f"codebook-composite-pass-{index}.json",
                )
                self.assertEqual((code, report["status"]), (0, "pass"), report)

        phrase_wide_composite_bypasses = (
            "c.age##i.treat and city_ai_fit",
            "prefix c.age##i.treat suffix",
            "c.age##i.treat,city_ai_fit",
        )
        for index, token in enumerate(phrase_wide_composite_bypasses):
            with self.subTest(replication_phrase_wide_bypass=token):
                labels = self.labels("en")
                reader_label = "Public interaction measure"
                labels[1]["display_text"] = f"{token} — {reader_label}"
                labels[1]["internal_key"] = token
                labels[1]["exceptions"] = [
                    {
                        "type": "replication_codebook",
                        "token": token,
                        "reason": "Purports to show a replication code token.",
                        "reader_definition": reader_label,
                        "source_locator": f"codebook.md#phrase-bypass-{index}",
                        "reader_label": reader_label,
                    }
                ]
                manifest, _ = self.make_manifest(
                    "en", name=f"codebook-phrase-bypass-{index}", labels=labels
                )
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(
                    manifest,
                    review,
                    output_name=f"codebook-phrase-bypass-{index}.json",
                )
                self.assertEqual(
                    (code, report["status"]),
                    (gate.EXIT_CODES["fail"], "fail"),
                    report,
                )
                self.assertIn(
                    "replication_codebook_token_incompatible", self.codes(report)
                )
                self.assertIn("internal_identifier_exposed", self.codes(report))

        punctuated_composite_cases = (
            (
                "c.age##i.treat",
                "c.age##i.treat—Age-treatment interaction",
                "Age-treatment interaction",
            ),
            (
                "L.gdp#i.year",
                "L.gdp#i.year/Lagged GDP-year interaction",
                "Lagged GDP-year interaction",
            ),
            (
                "c.age##i.treat",
                "Interaction: c.age##i.treat.",
                "Interaction",
            ),
        )
        for index, (token, display_text, reader_label) in enumerate(
            punctuated_composite_cases
        ):
            labels = self.labels("en")
            labels[1]["display_text"] = display_text
            labels[1]["internal_key"] = token
            labels[1]["exceptions"] = [
                {
                    "type": "replication_codebook",
                    "token": token,
                    "reason": "Shown in a replication appendix.",
                    "reader_definition": reader_label,
                    "source_locator": f"codebook.md#punctuated-{index}",
                    "reader_label": reader_label,
                }
            ]
            manifest, _ = self.make_manifest(
                "en", name=f"codebook-punctuated-pass-{index}", labels=labels
            )
            review, _, _, _ = self.make_review(manifest, name="primary")
            code, report = self.run_case(
                manifest,
                review,
                output_name=f"codebook-punctuated-pass-{index}.json",
            )
            self.assertEqual((code, report["status"]), (0, "pass"), report)

        for index, leaked_suffix in enumerate(("c.age leak", "c.age̸ leak")):
            labels = self.labels("en")
            token = "c.age##i.treat"
            reader_label = "Age-treatment interaction"
            labels[1]["display_text"] = (
                f"{token} — {reader_label} and {leaked_suffix}"
            )
            labels[1]["internal_key"] = token
            labels[1]["exceptions"] = [
                {
                    "type": "replication_codebook",
                    "token": token,
                    "reason": "Shown in a replication appendix.",
                    "reader_definition": reader_label,
                    "source_locator": f"codebook.md#composite-leak-{index}",
                    "reader_label": reader_label,
                }
            ]
            manifest, _ = self.make_manifest(
                "en", name=f"codebook-composite-leak-{index}", labels=labels
            )
            review, _, _, _ = self.make_review(manifest, name="primary")
            code, report = self.run_case(
                manifest,
                review,
                output_name=f"codebook-composite-leak-{index}.json",
            )
            self.assertEqual(
                (code, report["status"]),
                (gate.EXIT_CODES["fail"], "fail"),
                report,
            )
            self.assertIn("internal_identifier_exposed", self.codes(report))
            identifier_finding = next(
                finding
                for finding in report["findings"]
                if finding["code"] == "internal_identifier_exposed"
            )
            self.assertIn("c.age", identifier_finding["tokens"])

        for index, (display_text, internal_key) in enumerate(
            (
                ("x — Exposure index", "x"),
                ("var — Invariant effect", "var"),
                ("value — Outcome value", "value"),
            )
        ):
            with self.subTest(unregistered_internal_key=display_text):
                labels = self.labels("en")
                labels[1]["display_text"] = display_text
                labels[1]["internal_key"] = internal_key
                labels[1]["exceptions"] = []
                manifest, _ = self.make_manifest(
                    "en", name=f"unregistered-internal-{index}", labels=labels
                )
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(
                    manifest,
                    review,
                    output_name=f"unregistered-internal-{index}.json",
                )
                self.assertEqual(
                    (code, report["status"]),
                    (gate.EXIT_CODES["fail"], "fail"),
                )
                self.assertIn("internal_identifier_exposed", self.codes(report))

        labels = self.labels("en")
        labels[1]["display_text"] = "x — Exposure index"
        labels[1]["internal_key"] = "x"
        labels[1]["exceptions"] = [
            {
                "type": "mathematical_symbol",
                "token": "x",
                "reason": "The model defines x as the exposure index.",
                "reader_definition": "Exposure index used in the model.",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="defined-math-internal", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="defined-math-internal.json"
        )
        self.assertEqual((code, report["status"]), (0, "pass"), report)

        natural_internal_keys = (
            ("employment", "Employment growth in cities"),
            ("city", "City employment growth"),
            ("growth", "Annual employment growth"),
            ("income", "High-income minus low-income cities"),
        )
        for index, (internal_key, display_text) in enumerate(natural_internal_keys):
            with self.subTest(natural_internal_key=internal_key):
                labels = self.labels("en")
                labels[1]["display_text"] = display_text
                labels[1]["internal_key"] = internal_key
                labels[1]["exceptions"] = []
                manifest, _ = self.make_manifest(
                    "en", name=f"natural-internal-{index}", labels=labels
                )
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(
                    manifest,
                    review,
                    output_name=f"natural-internal-{index}.json",
                )
                self.assertEqual((code, report["status"]), (0, "pass"), report)

        for index, (internal_key, display_text, token) in enumerate(
            (
                ("gdp", "GDP growth", "GDP"),
                ("q1", "Q1 employment", "Q1"),
            )
        ):
            with self.subTest(case_variant_standard_token=token):
                labels = self.labels("en")
                labels[1]["display_text"] = display_text
                labels[1]["internal_key"] = internal_key
                labels[1]["exceptions"] = [
                    {
                        "type": "standard_abbreviation",
                        "token": token,
                        "reason": "This is the conventional reader-facing abbreviation.",
                        "reader_definition": f"Reader definition of {token}.",
                    }
                ]
                manifest, _ = self.make_manifest(
                    "en", name=f"standard-case-{index}", labels=labels
                )
                review, _, _, _ = self.make_review(manifest, name="primary")
                code, report = self.run_case(
                    manifest, review, output_name=f"standard-case-{index}.json"
                )
                self.assertEqual((code, report["status"]), (0, "pass"), report)

        labels = self.labels("en")
        labels[1]["display_text"] = "treatPost — Treatment after policy adoption"
        labels[1]["internal_key"] = "treatPost"
        labels[1]["exceptions"] = []
        manifest, _ = self.make_manifest(
            "en", name="camel-internal-unregistered", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="camel-internal-unregistered.json"
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn("internal_identifier_exposed", self.codes(report))

        labels = self.labels("en")
        labels[1]["display_text"] = "OpenAlex coverage"
        labels[1]["internal_key"] = "OpenAlex"
        labels[1]["exceptions"] = [
            {
                "type": "proper_name",
                "token": "OpenAlex",
                "reason": "OpenAlex is the formal product name.",
                "reader_definition": "The OpenAlex scholarly-data platform.",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="proper-name-internal", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="proper-name-internal.json"
        )
        self.assertEqual((code, report["status"]), (0, "pass"), report)

        labels = self.labels("en")
        labels[1]["display_text"] = "city_ai_fit — City AI fit"
        labels[1]["internal_key"] = "city_ai_fit"
        labels[1]["exceptions"] = [
            {
                "type": "proper_name",
                "token": "city_ai_fit",
                "reason": "Incorrectly claimed as a product name.",
                "reader_definition": "An internal constructed variable.",
            }
        ]
        manifest, _ = self.make_manifest(
            "en", name="proper-name-code-bypass", labels=labels
        )
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(
            manifest, review, output_name="proper-name-code-bypass.json"
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn("internal_identifier_exposed", self.codes(report))

    def test_note_language_and_bounded_journal_exception(self) -> None:
        for language, bad_prefix, expected_code in (
            ("zh-CN", "Notes: English template.", "chinese_note_prefix_invalid"),
            ("en", "注：中文模板。", "english_note_prefix_invalid"),
        ):
            with self.subTest(language=language):
                manifest, payload = self.make_manifest(language, name=f"note-{language}")
                payload["notes"][0]["text"] = bad_prefix
                review = self.rewrite_and_review(manifest, payload)
                code, report = self.run_case(manifest, review, output_name=f"note-{language}.json")
                self.assertEqual(code, gate.EXIT_CODES["fail"])
                self.assertIn(expected_code, self.codes(report))

                payload["notes"][0]["style_exception"] = {
                    "type": "journal_style",
                    "reason": "The target journal requires this exact note heading.",
                    "source_locator": "journal-guide.pdf#notes",
                }
                review = self.rewrite_and_review(manifest, payload)
                code, report = self.run_case(manifest, review, output_name=f"note-exception-{language}.json")
                self.assertEqual((code, report["status"]), (0, "pass"))

    def test_render_coverage_text_and_checks_fail_closed(self) -> None:
        mutations = ("coverage", "text", "check")
        for index, mutation in enumerate(mutations):
            with self.subTest(mutation=mutation):
                manifest, _ = self.make_manifest("en", name=f"render-{index}")
                review, payload, _, _ = self.make_review(manifest, name="primary")
                if mutation == "coverage":
                    payload["render"]["observed_elements"].pop()
                    expected = "render_element_coverage_incomplete"
                    expected_exit = gate.EXIT_CODES["audit_incomplete"]
                elif mutation == "text":
                    payload["render"]["observed_elements"][0]["text_sha256"] = "0" * 64
                    expected = "render_visible_text_mismatch"
                    expected_exit = gate.EXIT_CODES["fail"]
                else:
                    payload["render"]["checks"]["no_truncation"] = False
                    expected = "render_check_failed"
                    expected_exit = gate.EXIT_CODES["fail"]
                self.write_json(review, payload)
                code, report = self.run_case(manifest, review, output_name=f"render-{mutation}.json")
                self.assertEqual(code, expected_exit)
                self.assertIn(expected, self.codes(report))

    def test_full_recoverability_covers_referenced_notes_and_contexts(self) -> None:
        manifest, _ = self.make_manifest("en", name="full-coverage")
        review, payload, _, _ = self.make_review(manifest, name="primary")
        payload["full_recoverability"]["reviewed_element_ids"].remove("context-1")
        self.write_json(review, payload)
        code, report = self.run_case(manifest, review)
        self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
        self.assertIn(
            "full_recoverability_review_coverage_incomplete", self.codes(report)
        )

    def test_hard_failure_dominates_simultaneous_incomplete_finding(self) -> None:
        manifest, _ = self.make_manifest("en", name="status-priority")
        review, payload, _, _ = self.make_review(manifest, name="primary")
        payload["full_recoverability"]["reviewed_element_ids"].remove("context-1")
        payload["render"]["checks"]["no_overlap"] = False
        self.write_json(review, payload)
        code, report = self.run_case(manifest, review)
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn("render_check_failed", self.codes(report))
        self.assertIn(
            "full_recoverability_review_coverage_incomplete", self.codes(report)
        )

    def test_numeric_hash_conservation(self) -> None:
        manifest, payload = self.make_manifest(
            "en", name="numeric", operation="label_only_revision"
        )
        after_path = self.root / payload["numeric_integrity"]["after_path"]
        after_path.write_text("changed numeric payload\n", encoding="utf-8")
        payload["numeric_integrity"]["after_sha256"] = gate.sha256_file(after_path)
        review = self.rewrite_and_review(manifest, payload)
        code, report = self.run_case(manifest, review)
        self.assertEqual(code, gate.EXIT_CODES["fail"])
        self.assertIn("numeric_content_changed", self.codes(report))

    def test_label_only_distinct_paths_cannot_be_the_same_hard_link(self) -> None:
        manifest, payload = self.make_manifest(
            "en", name="numeric-hard-link", operation="label_only_revision"
        )
        before_path = self.root / payload["numeric_integrity"]["before_path"]
        after_path = self.root / payload["numeric_integrity"]["after_path"]
        after_path.unlink()
        os.link(before_path, after_path)
        self.assertNotEqual(before_path, after_path)
        self.assertEqual(before_path.stat().st_ino, after_path.stat().st_ino)
        review, _, _, _ = self.make_review(manifest, name="primary")
        code, report = self.run_case(manifest, review)
        self.assertEqual(code, gate.EXIT_CODES["fail"])
        same_file_codes = {
            finding_code
            for finding_code in self.codes(report)
            if finding_code.startswith("numeric_revision_")
            and ("same" in finding_code or "identical" in finding_code)
        }
        self.assertTrue(same_file_codes, report)

    def test_new_artifact_numeric_payload_tampering_fails(self) -> None:
        manifest, payload = self.make_manifest("en", name="numeric-tamper")
        review, _, _, _ = self.make_review(manifest, name="primary")
        numeric_path = self.root / payload["numeric_integrity"]["numeric_payload_path"]
        numeric_path.write_text("tampered after manifest creation\n", encoding="utf-8")
        code, report = self.run_case(manifest, review)
        self.assertEqual(code, gate.EXIT_CODES["fail"])
        self.assertTrue(
            {"numeric_payload_hash_stale", "numeric_payload_hash_mismatch"}
            & self.codes(report)
        )

    def test_artifact_change_after_initial_review_is_rechecked_before_report(self) -> None:
        manifest, _ = self.make_manifest("en", name="freshness-race")
        review, _, state, _ = self.make_review(manifest, name="primary")
        assert state.artifact_path is not None
        original_validate_review = gate.validate_review

        def mutate_after_review(*args: object, **kwargs: object) -> None:
            original_validate_review(*args, **kwargs)
            state_argument = args[2]
            assert isinstance(state_argument, gate.ManifestState)
            assert state_argument.artifact_path is not None
            state_argument.artifact_path.write_text(
                "changed after initial review validation\n", encoding="utf-8"
            )

        with mock.patch.object(gate, "validate_review", side_effect=mutate_after_review):
            code, report = self.run_case(manifest, review)
        self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
        self.assertIn("input_changed_during_audit", self.codes(report))

    def test_output_collision_and_existing_non_report_are_not_overwritten(self) -> None:
        manifest, manifest_payload = self.make_manifest("en", name="output")
        review, _, _, _ = self.make_review(manifest, name="primary")
        original_manifest = manifest.read_bytes()
        code, report = gate.run(
            [
                "--project-root", str(self.root),
                "--manifest", str(manifest.relative_to(self.root)),
                "--review", str(review.relative_to(self.root)),
                "--stage", "generated",
                "--output", str(manifest.relative_to(self.root)),
            ]
        )
        self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
        self.assertIn("output_path_collision", self.codes(report))
        self.assertEqual(manifest.read_bytes(), original_manifest)

        numeric_payload = self.root / manifest_payload["numeric_integrity"]["numeric_payload_path"]
        original_numeric = numeric_payload.read_bytes()
        code, report = gate.run(
            [
                "--project-root", str(self.root),
                "--manifest", str(manifest.relative_to(self.root)),
                "--review", str(review.relative_to(self.root)),
                "--stage", "generated",
                "--output", str(numeric_payload.relative_to(self.root)),
            ]
        )
        self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
        self.assertIn("output_path_collision", self.codes(report))
        self.assertEqual(numeric_payload.read_bytes(), original_numeric)

        existing = self.root / "reports" / "do-not-overwrite.txt"
        existing.write_text("not an audit report\n", encoding="utf-8")
        original_existing = existing.read_bytes()
        code, report = gate.run(
            [
                "--project-root", str(self.root),
                "--manifest", str(manifest.relative_to(self.root)),
                "--review", str(review.relative_to(self.root)),
                "--stage", "generated",
                "--output", str(existing.relative_to(self.root)),
            ]
        )
        self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
        self.assertIn("output_existing_non_report", self.codes(report))
        self.assertEqual(existing.read_bytes(), original_existing)

        failing_labels = self.labels("en")
        failing_labels[1]["display_text"] = "city_ai_fit"
        failing_labels[1]["internal_key"] = "city_ai_fit"
        failing_manifest, _ = self.make_manifest(
            "en", name="output-priority", labels=failing_labels
        )
        failing_review, _, _, _ = self.make_review(
            failing_manifest, name="output-priority"
        )
        original_failing_manifest = failing_manifest.read_bytes()
        code, report = gate.run(
            [
                "--project-root", str(self.root),
                "--manifest", str(failing_manifest.relative_to(self.root)),
                "--review", str(failing_review.relative_to(self.root)),
                "--stage", "generated",
                "--output", str(failing_manifest.relative_to(self.root)),
            ]
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn("internal_identifier_exposed", self.codes(report))
        self.assertIn("output_path_collision", self.codes(report))
        self.assertEqual(failing_manifest.read_bytes(), original_failing_manifest)

        failing_existing = self.root / "reports" / "failing-do-not-overwrite.txt"
        failing_existing.write_text("not an audit report\n", encoding="utf-8")
        original_failing_existing = failing_existing.read_bytes()
        code, report = gate.run(
            [
                "--project-root", str(self.root),
                "--manifest", str(failing_manifest.relative_to(self.root)),
                "--review", str(failing_review.relative_to(self.root)),
                "--stage", "generated",
                "--output", str(failing_existing.relative_to(self.root)),
            ]
        )
        self.assertEqual((code, report["status"]), (gate.EXIT_CODES["fail"], "fail"))
        self.assertIn("internal_identifier_exposed", self.codes(report))
        self.assertIn("output_existing_non_report", self.codes(report))
        self.assertEqual(failing_existing.read_bytes(), original_failing_existing)

    def test_missing_declared_numeric_payload_remains_output_protected(self) -> None:
        manifest, payload = self.make_manifest("en", name="missing-numeric-output")
        review, _, _, _ = self.make_review(manifest, name="primary")
        numeric_payload = self.root / payload["numeric_integrity"]["numeric_payload_path"]
        numeric_payload.unlink()
        self.assertFalse(numeric_payload.exists())
        code, report = gate.run(
            [
                "--project-root", str(self.root),
                "--manifest", str(manifest.relative_to(self.root)),
                "--review", str(review.relative_to(self.root)),
                "--stage", "generated",
                "--output", str(numeric_payload.relative_to(self.root)),
            ]
        )
        self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
        self.assertIn("numeric_payload_missing", self.codes(report))
        self.assertIn("output_path_collision", self.codes(report))
        self.assertFalse(
            numeric_payload.exists(),
            "The audit report must not create a path declared as a numeric input.",
        )

    @staticmethod
    def make_symlink_loop(path: Path) -> None:
        path.symlink_to(path.name)

    def test_symlink_loops_fail_structurally_without_traceback(self) -> None:
        review_placeholder = self.root / "reviews" / "unused.json"

        with self.subTest("project-root"):
            root_loop = self.root / "loop-root"
            self.make_symlink_loop(root_loop)
            code, report = gate.run(
                [
                    "--project-root", str(root_loop),
                    "--manifest", "manifest.json",
                    "--review", "review.json",
                    "--stage", "generated",
                    "--output", "audit.json",
                ]
            )
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertTrue(
                {
                    "project_root_unresolvable",
                    "project_root_invalid",
                    "cli_path_invalid",
                }
                & self.codes(report)
            )

        with self.subTest("manifest"):
            manifest_loop = self.root / "manifests" / "manifest-loop.json"
            self.make_symlink_loop(manifest_loop)
            code, report = gate.run(
                [
                    "--project-root", str(self.root),
                    "--manifest", str(manifest_loop.relative_to(self.root)),
                    "--review", str(review_placeholder.relative_to(self.root)),
                    "--stage", "generated",
                    "--output", "reports/manifest-loop.json",
                ]
            )
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertIn("cli_path_invalid", self.codes(report))

        with self.subTest("review"):
            manifest, _ = self.make_manifest("en", name="review-loop")
            review_loop = self.root / "reviews" / "review-loop.json"
            self.make_symlink_loop(review_loop)
            code, report = gate.run(
                [
                    "--project-root", str(self.root),
                    "--manifest", str(manifest.relative_to(self.root)),
                    "--review", str(review_loop.relative_to(self.root)),
                    "--stage", "generated",
                    "--output", "reports/review-loop.json",
                ]
            )
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertIn("cli_path_invalid", self.codes(report))

        with self.subTest("artifact"):
            manifest, manifest_payload = self.make_manifest("en", name="artifact-loop")
            review, review_payload, _, _ = self.make_review(manifest, name="primary")
            artifact_loop = self.root / "artifacts" / "artifact-loop-target.txt"
            self.make_symlink_loop(artifact_loop)
            manifest_payload["artifact"]["path"] = str(artifact_loop.relative_to(self.root))
            manifest_payload["artifact"]["sha256"] = "0" * 64
            self.write_json(manifest, manifest_payload)
            review_payload["manifest_sha256"] = gate.sha256_file(manifest)
            review_payload["artifact_sha256"] = ""
            review_payload["render"]["artifact_sha256"] = ""
            self.write_json(review, review_payload)
            code, report = self.run_case(
                manifest, review, output_name="artifact-loop.json"
            )
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertIn("artifact_path_invalid", self.codes(report))

        with self.subTest("numeric"):
            manifest, manifest_payload = self.make_manifest("en", name="numeric-loop")
            review, review_payload, _, _ = self.make_review(manifest, name="primary")
            numeric_loop = self.root / "artifacts" / "numeric-loop-target.txt"
            self.make_symlink_loop(numeric_loop)
            manifest_payload["numeric_integrity"]["numeric_payload_path"] = str(
                numeric_loop.relative_to(self.root)
            )
            manifest_payload["numeric_integrity"]["numeric_payload_sha256"] = "0" * 64
            self.write_json(manifest, manifest_payload)
            review_payload["manifest_sha256"] = gate.sha256_file(manifest)
            self.write_json(review, review_payload)
            code, report = self.run_case(
                manifest, review, output_name="numeric-loop.json"
            )
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertIn("numeric_payload_path_invalid", self.codes(report))

        with self.subTest("output"):
            manifest, _ = self.make_manifest("en", name="output-loop")
            review, _, _, _ = self.make_review(manifest, name="primary")
            output_loop = self.root / "reports" / "output-loop.json"
            self.make_symlink_loop(output_loop)
            code, report = gate.run(
                [
                    "--project-root", str(self.root),
                    "--manifest", str(manifest.relative_to(self.root)),
                    "--review", str(review.relative_to(self.root)),
                    "--stage", "generated",
                    "--output", str(output_loop.relative_to(self.root)),
                ]
            )
            self.assertEqual(code, gate.EXIT_CODES["audit_incomplete"])
            self.assertIn("cli_path_invalid", self.codes(report))

    def test_paired_unit_and_direction_mismatch(self) -> None:
        for index, field in enumerate(("unit_code", "direction_code")):
            with self.subTest(field=field):
                zh_manifest, _ = self.make_manifest("zh-CN", name=f"pair-zh-{index}")
                zh_review, _, _, _ = self.make_review(zh_manifest, name="primary")
                en_manifest, en_payload = self.make_manifest("en", name=f"pair-en-{index}")
                en_payload["labels"][1]["semantic_signature"][field] = f"mismatched_{field}"
                en_review = self.rewrite_and_review(en_manifest, en_payload, name="paired")
                code, report = self.run_case(
                    zh_manifest,
                    zh_review,
                    paired=(en_manifest, en_review),
                    output_name=f"pair-{field}.json",
                )
                self.assertEqual(code, gate.EXIT_CODES["fail"])
                self.assertIn("paired_semantic_signature_mismatch", self.codes(report))


if __name__ == "__main__":
    unittest.main(verbosity=2)
