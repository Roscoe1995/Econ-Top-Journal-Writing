#!/usr/bin/env python3
"""Synthetic regression tests for audit_manuscript_conservation.py."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("audit_manuscript_conservation.py")
SPEC = importlib.util.spec_from_file_location("audit_manuscript_conservation", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
PREPARE_SCRIPT = Path(__file__).with_name("prepare_manuscript_qa.py")
PREPARE_SPEC = importlib.util.spec_from_file_location(
    "prepare_manuscript_qa_for_conservation_test", PREPARE_SCRIPT
)
assert PREPARE_SPEC and PREPARE_SPEC.loader
PREPARE_MODULE = importlib.util.module_from_spec(PREPARE_SPEC)
sys.modules[PREPARE_SPEC.name] = PREPARE_MODULE
PREPARE_SPEC.loader.exec_module(PREPARE_MODULE)


class ConservationAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_json(self, relative: str, payload: object) -> Path:
        return self.write(relative, json.dumps(payload, ensure_ascii=False))

    def contract(self, payload: dict) -> Path:
        payload = dict(payload)
        payload.setdefault("metric_status", "measured")
        measurement = payload.setdefault("measurement_contract", {})
        if isinstance(measurement, dict):
            measurement.setdefault("appendix_boundary", r"\appendix")
            measurement.setdefault("source_word_method", "normalized_words")
        baseline_candidates = [
            path
            for suffix in ("tex", "md", "txt")
            if (path := self.root / f"baseline.{suffix}").is_file()
        ]
        if len(baseline_candidates) == 1:
            baseline = baseline_candidates[0]
            try:
                expanded, sources, _ = MODULE.load_manuscript(
                    baseline, self.root.resolve()
                )
            except MODULE.MetricUnavailable:
                expanded, sources = None, [str(baseline.resolve())]
            baseline_artifact = {
                "path": str(baseline.resolve()),
                "sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
                "source_files": MODULE.source_file_records(sources),
                "acceptance_status": "accepted",
                "accepted_by": "Alice Example",
            }
            if expanded is not None:
                baseline_artifact["expanded_sha256"] = MODULE.sha256_text(expanded)
            payload.setdefault(
                "baseline_artifact",
                baseline_artifact,
            )
        if payload.get("task_mode") in {
            "major_revision",
            "restructure",
            "shorten",
            "local_edit",
        }:
            payload.setdefault("rewrite_mode", "patch_existing")
        candidate_candidates = [
            path
            for suffix in ("tex", "md", "txt")
            if (path := self.root / f"candidate.{suffix}").is_file()
        ]
        if len(baseline_candidates) == 1:
            baseline = baseline_candidates[0]
            try:
                baseline_text, _, baseline_format = MODULE.load_manuscript(
                    baseline, self.root.resolve()
                )
                baseline_main, _ = MODULE.split_appendix(
                    baseline_text,
                    payload["measurement_contract"]["appendix_boundary"],
                    "baseline",
                    baseline_format,
                )
                metric_name = payload["measurement_contract"][
                    "source_word_method"
                ]
                baseline_metrics = MODULE.manuscript_metrics(
                    baseline_main, baseline_format
                )
                payload.setdefault(
                    "baseline_main_source_words", baseline_metrics[metric_name]
                )
                attested_pages = payload["measurement_contract"].get(
                    "attested_main_text_pages"
                )
                if isinstance(attested_pages, dict) and isinstance(
                    attested_pages.get("baseline"), dict
                ):
                    payload.setdefault(
                        "baseline_main_pdf_pages",
                        attested_pages["baseline"].get("pages"),
                    )
                if (
                    payload.get("mature_baseline") is True
                    and "section_cards" not in payload
                    and len(candidate_candidates) == 1
                ):
                    candidate = candidate_candidates[0]
                    candidate_text, _, candidate_format = MODULE.load_manuscript(
                        candidate, self.root.resolve()
                    )
                    candidate_main, _ = MODULE.split_appendix(
                        candidate_text,
                        payload["measurement_contract"]["appendix_boundary"],
                        "candidate",
                        candidate_format,
                    )
                    baseline_sections = baseline_metrics["section_metrics"]
                    candidate_sections = MODULE.extract_sections(
                        candidate_main, candidate_format
                    )
                    unused_candidate_ids = {
                        section["id"] for section in candidate_sections
                    }
                    cards = []
                    translation_mode = str(payload.get("task_mode", "")).lower() in {
                        "translation",
                        "document_translation",
                    }
                    for index, section in enumerate(baseline_sections, 1):
                        destination = next(
                            (
                                item
                                for item in candidate_sections
                                if item["id"] in unused_candidate_ids
                                and item["normalized_title"]
                                == section["normalized_title"]
                            ),
                            None,
                        )
                        if destination is None and translation_mode:
                            destination = next(
                                (
                                    item
                                    for item in candidate_sections
                                    if item["id"] in unused_candidate_ids
                                ),
                                None,
                            )
                        if destination is not None:
                            unused_candidate_ids.remove(destination["id"])
                        upper = max(
                            float(section[metric_name]),
                            float(destination[metric_name])
                            if destination is not None
                            else 0.0,
                        ) * 10 + 100
                        card = {
                            "card_id": f"card-{index}",
                            "section_name": section["title"],
                            "baseline_section_id": section["id"],
                            "baseline_section_name": section["title"],
                            "baseline_words": section[metric_name],
                            "target_word_range": [0, upper],
                            "minimum_depth_questions": [
                                f"What must {section['title']} explain?"
                            ],
                            "must_remain_main": [
                                {
                                    "type": "section",
                                    "value": (
                                        destination["title"]
                                        if destination is not None
                                        else section["title"]
                                    ),
                                }
                            ],
                        }
                        if destination is not None:
                            card["candidate_section_id"] = destination["id"]
                            card["candidate_section_name"] = destination["title"]
                        if not translation_mode:
                            card["maximum_reduction_pct"] = 1.0
                        cards.append(card)
                    payload["section_cards"] = cards
            except MODULE.MetricUnavailable:
                pass
        if (
            len(baseline_candidates) == 1
            and len(candidate_candidates) == 1
            and payload.get("task_mode") == "restructure"
            and payload.get("mature_baseline") is True
            and payload.get("rewrite_mode") != "full_redraft"
            and isinstance(payload.get("content_conservation_ledger"), list)
        ):
            baseline = baseline_candidates[0]
            candidate = candidate_candidates[0]
            try:
                baseline_text, _, _ = MODULE.load_manuscript(
                    baseline, self.root.resolve()
                )
                candidate_text, _, _ = MODULE.load_manuscript(
                    candidate, self.root.resolve()
                )
            except MODULE.MetricUnavailable:
                baseline_text = candidate_text = None
            if baseline_text is not None and candidate_text is not None:
                baseline_expanded_sha = MODULE.sha256_text(baseline_text)
                candidate_expanded_sha = MODULE.sha256_text(candidate_text)
                same_expansion = baseline_expanded_sha == candidate_expanded_sha
                compression_pass = {
                    "status": "not_needed" if same_expansion else "completed",
                    "mode": "none" if same_expansion else "limited_compression",
                    "source_expanded_sha256": baseline_expanded_sha,
                    "candidate_expanded_sha256": candidate_expanded_sha,
                    "completed_by": "controller-test",
                    "completed_at": "2026-08-03T12:01:00+08:00",
                }
                if not same_expansion:
                    compression_pass.update(
                        {
                            "approved_scope": [
                                "bounded_post_architecture_revision"
                            ],
                            "content_conservation_ledger": payload[
                                "content_conservation_ledger"
                            ],
                        }
                    )
                payload.setdefault(
                    "two_pass_restructure",
                    {
                        "architecture_pass": {
                            "status": "completed",
                            "mode": "reorder_existing_blocks",
                            "artifact_path": str(baseline.resolve()),
                            "artifact_sha256": hashlib.sha256(
                                baseline.read_bytes()
                            ).hexdigest(),
                            "expanded_sha256": baseline_expanded_sha,
                            "completed_by": "controller-test",
                            "completed_at": "2026-08-03T12:00:00+08:00",
                            "content_conservation_ledger": self.complete_ledger(
                                baseline, baseline
                            ),
                        },
                        "compression_pass": compression_pass,
                    },
                )
        return self.write(
            "contract.json",
            json.dumps({"artifact_contract": payload}, ensure_ascii=False),
        )

    def inventories(self, manuscript: Path) -> list[dict]:
        expanded, _, fmt = MODULE.load_manuscript(manuscript, self.root.resolve())
        main, appendix = MODULE.split_appendix(
            expanded, r"\appendix", "test", fmt
        )
        return MODULE.substantive_block_inventory(
            main, "main_text", fmt
        ) + MODULE.substantive_block_inventory(
            appendix, "appendix", fmt
        ) + MODULE.substantive_object_inventory(
            main, "main_text", fmt
        ) + MODULE.substantive_object_inventory(appendix, "appendix", fmt)

    def complete_ledger(
        self,
        baseline: Path,
        candidate: Path,
        *,
        authorize_destructive: bool = True,
    ) -> list[dict]:
        baseline_inventory = self.inventories(baseline)
        candidate_inventory = self.inventories(candidate)
        candidate_text, _, _ = MODULE.load_manuscript(
            candidate, self.root.resolve()
        )
        candidate_expanded_sha256 = MODULE.sha256_text(candidate_text)
        unused = {item["block_id"] for item in candidate_inventory}
        entries: list[dict] = []
        for source in baseline_inventory:
            exact = next(
                (
                    item
                    for item in candidate_inventory
                    if item["block_id"] in unused
                    and item["region"] == source["region"]
                    and item["section_id"] == source["section_id"]
                    and item["content_sha256"] == source["content_sha256"]
                ),
                None,
            )
            same_section = next(
                (
                    item
                    for item in candidate_inventory
                    if item["block_id"] in unused
                    and item["normalized_section"] == source["normalized_section"]
                    and item["region"] == source["region"]
                    and item.get("inventory_kind") == source.get("inventory_kind")
                    and item.get("object_type") == source.get("object_type")
                ),
                None,
            )
            moved = next(
                (
                    item
                    for item in candidate_inventory
                    if item["block_id"] in unused
                    and source["region"] == "main_text"
                    and item["region"] == "appendix"
                    and item["normalized_section"] == source["normalized_section"]
                    and item.get("inventory_kind") == source.get("inventory_kind")
                    and item.get("object_type") == source.get("object_type")
                    and item["content_sha256"] == source["content_sha256"]
                ),
                None,
            )
            destination = exact or same_section or moved
            if exact is not None:
                disposition = "unchanged"
            elif same_section is not None:
                disposition = "revised"
            elif moved is not None:
                disposition = "moved_appendix"
            else:
                disposition = "deleted"
            entry = {
                "source_block_id": source["block_id"],
                "disposition": disposition,
            }
            if destination is not None:
                unused.remove(destination["block_id"])
                entry["destination"] = destination["block_id"]
            if disposition in {"revised", "reordered", "merged", "renamed"}:
                entry["authority"] = {
                    "role": "controller",
                    "by": "controller-test",
                    "at": "2026-08-03T12:00:00+08:00",
                }
            if disposition in {"revised", "merged"}:
                entry.update(
                    {
                        "source_function": "fixture substantive function",
                        "reason": "fixture bounded revision",
                        "retained_meaning_evidence": (
                            "fixture maps the source meaning to this destination"
                        ),
                        "omitted_elements": [],
                    }
                )
                source_words = float(source.get("normalized_words") or 0)
                destination_words = float(destination.get("normalized_words") or 0)
                reduction = MODULE.reduction_pct(source_words, destination_words)
                if (
                    source.get("inventory_kind") == "substantive_object"
                    or (reduction is not None and reduction > 0.50)
                ):
                    entry["main_text_sufficiency_review"] = {
                        "role": "Main-Text Sufficiency and Conservation",
                        "reviewer_id": "independent-reviewer-test",
                        "reviewed_at": "2026-08-03T12:00:00+08:00",
                        "verdict": "pass",
                        "source_block_id": source["block_id"],
                        "destination_block_id": destination["block_id"],
                        "candidate_expanded_sha256": candidate_expanded_sha256,
                    }
            if disposition in {"moved_appendix", "deleted"} and authorize_destructive:
                entry["author_approval"] = {
                    "approval_authority": "author",
                    "approved_by": "Alice Example",
                    "approved_at": "2026-08-03T12:00:00+08:00",
                    "approval_source": "author confirmation fixture",
                    "approved_scope": [f"{disposition}:{source['block_id']}"],
                }
            entries.append(entry)
        return entries

    def contract_with_ledger(
        self,
        payload: dict,
        baseline: Path,
        candidate: Path,
        *,
        authorize_destructive: bool = True,
    ) -> Path:
        enriched = dict(payload)
        enriched["content_conservation_ledger"] = self.complete_ledger(
            baseline,
            candidate,
            authorize_destructive=authorize_destructive,
        )
        return self.contract(enriched)

    def split_section_fixture(
        self,
    ) -> tuple[Path, Path, list[dict], list[dict]]:
        baseline = self.write(
            "baseline.tex",
            "\\section{Analysis}\nFirst preserved paragraph.\n\n"
            "Second preserved paragraph.\n\\appendix\n"
            "\\section{Supplement}\nAppendix detail.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Part A}\nFirst preserved paragraph.\n\n"
            "\\section{Part B}\nSecond preserved paragraph.\n\\appendix\n"
            "\\section{Supplement}\nAppendix detail.\n",
        )
        baseline_inventory = self.inventories(baseline)
        candidate_inventory = self.inventories(candidate)
        ledger: list[dict] = []
        main_pairs: list[tuple[dict, dict]] = []
        for source in baseline_inventory:
            destination = next(
                item
                for item in candidate_inventory
                if item["region"] == source["region"]
                and item["content_sha256"] == source["content_sha256"]
                and item.get("inventory_kind") == source.get("inventory_kind")
            )
            disposition = (
                "reordered" if source["region"] == "main_text" else "unchanged"
            )
            entry = {
                "source_block_id": source["block_id"],
                "destination": destination["block_id"],
                "disposition": disposition,
            }
            if disposition == "reordered":
                entry["authority"] = {
                    "role": "controller",
                    "by": "controller-test",
                    "at": "2026-08-03T12:00:00+08:00",
                }
                main_pairs.append((source, destination))
            ledger.append(entry)
        baseline_main, _ = MODULE.split_appendix(
            MODULE.load_manuscript(baseline, self.root.resolve())[0],
            r"\appendix",
            "baseline",
            "tex",
        )
        candidate_main, _ = MODULE.split_appendix(
            MODULE.load_manuscript(candidate, self.root.resolve())[0],
            r"\appendix",
            "candidate",
            "tex",
        )
        baseline_section = MODULE.extract_sections(baseline_main, "tex")[0]
        candidate_sections = {
            item["id"]: item for item in MODULE.extract_sections(candidate_main, "tex")
        }
        cards: list[dict] = []
        for index, (source, destination) in enumerate(main_pairs, 1):
            candidate_section = candidate_sections[destination["section_id"]]
            cards.append(
                {
                    "card_id": f"analysis-slice-{index}",
                    "baseline_section_id": baseline_section["id"],
                    "baseline_section_name": baseline_section["title"],
                    "candidate_section_id": candidate_section["id"],
                    "candidate_section_name": candidate_section["title"],
                    "baseline_words": source["normalized_words"],
                    "target_word_range": [0, 100],
                    "maximum_reduction_pct": 1.0,
                    "minimum_depth_questions": [
                        "What substantive explanation must this preserved block retain?"
                    ],
                    "must_remain_main": [
                        {"type": "section", "value": candidate_section["title"]}
                    ],
                    "ledger_slice": {
                        "baseline_block_ids": [source["block_id"]],
                        "destination_block_ids": [destination["block_id"]],
                    },
                }
            )
        return baseline, candidate, ledger, cards

    def new_draft_payload(
        self, section_names: list[str], **overrides: object
    ) -> dict:
        payload: dict = {
            "task_mode": "full_draft",
            "mature_baseline": False,
            "target_main_source_word_range": [1, 1000],
            "section_cards": [
                {
                    "card_id": f"section-{index}",
                    "section_name": name,
                    "target_word_range": [1, 1000],
                    "must_remain_main": [{"type": "section", "value": name}],
                    "minimum_depth_questions": [f"What must {name} explain?"],
                }
                for index, name in enumerate(section_names, 1)
            ],
            "content_obligations": [
                {"obligation_id": "O1", "content": "Preserve the frozen claim."}
            ],
        }
        payload.update(overrides)
        return payload

    def run_audit(
        self,
        baseline: Path | None,
        candidate: Path,
        contract: Path | None = None,
        *extra: str,
    ) -> tuple[subprocess.CompletedProcess[str], dict]:
        report = self.root / "report.json"
        command = [
            sys.executable,
            str(SCRIPT),
            "--candidate",
            str(candidate),
            "--project-root",
            str(self.root),
            "--report",
            str(report),
        ]
        if baseline is not None:
            command.extend(["--baseline", str(baseline)])
        if contract:
            command.extend(["--contract", str(contract)])
        command.extend(extra)
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        return completed, json.loads(report.read_text(encoding="utf-8"))

    def test_audit_arguments_record_exact_optional_cli_values(self) -> None:
        args = MODULE.parser().parse_args(
            [
                "--candidate",
                "candidate.tex",
                "--report",
                "report.json",
                "--appendix-marker",
                "APPENDIX-BOUNDARY",
                "--word-metric",
                "normalized_words",
                "--max-main-reduction",
                "0.125",
                "--min-main-source-words",
                "900",
                "--baseline-main-pdf-pages",
                "30.5",
                "--candidate-main-pdf-pages",
                "27.25",
                "--min-main-pdf-pages",
                "24",
            ]
        )
        self.assertEqual(
            MODULE.audit_argument_record(args),
            {
                "appendix_marker": "APPENDIX-BOUNDARY",
                "word_metric": "normalized_words",
                "max_main_reduction": 0.125,
                "min_main_source_words": 900,
                "baseline_main_pdf_pages": 30.5,
                "candidate_main_pdf_pages": 27.25,
                "min_main_pdf_pages": 24.0,
            },
        )

    def test_metric_status_must_be_explicitly_measured(self) -> None:
        candidate = self.write(
            "candidate.tex",
            "\\section{Results}\nA bounded result remains.\n\\appendix\nExtra.\n",
        )
        cases = {
            "missing": None,
            "unavailable": "unavailable",
            "ambiguous": "ambiguous",
            "invalid": "guessed",
        }
        for name, value in cases.items():
            with self.subTest(metric_status=name):
                payload = {
                    "artifact_contract": {
                        "task_mode": "full_draft",
                        "mature_baseline": False,
                    }
                }
                if value is not None:
                    payload["artifact_contract"]["metric_status"] = value
                contract = self.write_json(f"contract-{name}.json", payload)
                completed, report = self.run_audit(None, candidate, contract)
                self.assertEqual(completed.returncode, 3)
                self.assertEqual(report["status"], "metric_unavailable")
                self.assertIn("metric_status", report["findings"]["warnings"][0])

    def test_measurement_contract_must_freeze_boundary_and_word_method(self) -> None:
        candidate = self.write(
            "candidate.tex",
            "\\section{Results}\nA bounded result remains.\n\\appendix\nExtra.\n",
        )
        cases = {
            "missing_object": None,
            "missing_both": {},
            "missing_method": {"appendix_boundary": r"\appendix"},
            "missing_boundary": {"source_word_method": "normalized_words"},
            "invalid_method": {
                "appendix_boundary": r"\appendix",
                "source_word_method": "estimated_words",
            },
            "wrong_boundary": {
                "appendix_boundary": "APPENDIX",
                "source_word_method": "normalized_words",
            },
        }
        for name, measurement in cases.items():
            with self.subTest(measurement=name):
                artifact = {
                    "task_mode": "full_draft",
                    "mature_baseline": False,
                    "metric_status": "measured",
                }
                if measurement is not None:
                    artifact["measurement_contract"] = measurement
                contract = self.write_json(
                    f"measurement-{name}.json", {"artifact_contract": artifact}
                )
                completed, report = self.run_audit(None, candidate, contract)
                self.assertEqual(completed.returncode, 3)
                self.assertEqual(report["status"], "metric_unavailable")
                self.assertIn(
                    "measurement_contract", report["findings"]["warnings"][0]
                )

    def test_cli_word_metric_cannot_override_contract_method(self) -> None:
        candidate = self.write(
            "candidate.tex",
            "\\section{Results}\nA bounded result remains.\n\\appendix\nExtra.\n",
        )
        contract = self.contract(
            self.new_draft_payload(
                ["Results"],
                measurement_contract={"source_word_method": "raw_source_words"},
            )
        )
        completed, report = self.run_audit(
            None, candidate, contract, "--word-metric", "normalized_words"
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "--word-metric must match measurement_contract.source_word_method",
            " ".join(report["findings"]["failures"]),
        )
        self.assertEqual(report["measurement"]["word_metric_for_contract"], "raw_source_words")

    def test_cli_floor_cannot_lower_artifact_contract_floor(self) -> None:
        candidate = self.write(
            "candidate.tex",
            "\\section{Results}\nA bounded result remains.\n\\appendix\nExtra.\n",
        )
        contract = self.contract(
            self.new_draft_payload(
                ["Results"], hard_main_text_floor={"source_words": 10_000}
            )
        )
        completed, report = self.run_audit(
            None, candidate, contract, "--min-main-source-words", "0"
        )
        self.assertEqual(completed.returncode, 1)
        findings = " ".join(report["findings"]["failures"])
        self.assertIn("cannot weaken artifact_contract.hard_main_text_floor", findings)
        self.assertIn("below hard floor 10000", findings)

    def test_cli_reduction_limit_cannot_weaken_artifact_contract_limit(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Results}\n" + "Baseline evidence. " * 100
            + "\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Results}\n" + "Candidate evidence. " * 80
            + "\n\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "local_edit",
                "mature_baseline": True,
                "max_unapproved_main_reduction_pct": 0.10,
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(
            baseline, candidate, contract, "--max-main-reduction", "1.0"
        )
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "--max-main-reduction cannot weaken",
            " ".join(report["findings"]["failures"]),
        )
        self.assertEqual(
            report["metrics"]["max_unapproved_main_reduction_pct"], 0.10
        )

    def test_reorder_only_passes(self) -> None:
        baseline = self.write(
            "baseline.tex",
            r"""
\section{Data}\label{sec:data}
We describe the sample, variables, period, and measurement in full.
\section{Results}\label{sec:results}
The benchmark estimate, magnitude, and interpretation answer the question.
\appendix
\section{Supplement}
Additional detail.
""",
        )
        candidate = self.write(
            "candidate.tex",
            r"""
\section{Results}\label{sec:results}
The benchmark estimate, magnitude, and interpretation answer the question.
\section{Data}\label{sec:data}
We describe the sample, variables, period, and measurement in full.
\appendix
\section{Supplement}
Additional detail.
""",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "rewrite_mode": "reorder_existing_blocks",
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(report["schema_id"], "manuscript-conservation-audit/1.0")
        self.assertEqual(report["gate_type"], "manuscript_conservation")
        self.assertEqual(
            report["audit_arguments"],
            {
                "appendix_marker": r"\appendix",
                "word_metric": None,
                "max_main_reduction": None,
                "min_main_source_words": None,
                "baseline_main_pdf_pages": None,
                "candidate_main_pdf_pages": None,
                "min_main_pdf_pages": None,
            },
        )
        self.assertEqual(
            report["conservation"]["two_pass_restructure"]["status"], "pass"
        )
        contract_payload = json.loads(contract.read_text(encoding="utf-8"))[
            "artifact_contract"
        ]
        architecture_ledger = contract_payload["two_pass_restructure"][
            "architecture_pass"
        ]["content_conservation_ledger"]
        self.assertEqual(
            report["conservation"]["two_pass_restructure"][
                "architecture_ledger_sha256"
            ],
            hashlib.sha256(
                json.dumps(
                    architecture_ledger,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        )
        self.assertEqual(
            report["inputs"]["contract_sha256"],
            hashlib.sha256(contract.read_bytes()).hexdigest(),
        )
        expected_ids = sorted(item["block_id"] for item in self.inventories(baseline))
        self.assertEqual(
            report["conservation"]["expected_baseline_block_ids"], expected_ids
        )
        self.assertEqual(
            expected_ids,
            sorted(item["block_id"] for item in self.inventories(baseline)),
        )

    def test_unapproved_appendix_migration_fails(self) -> None:
        baseline = self.write(
            "baseline.tex",
            r"""
\section{Data and Sample}\label{sec:data}
The main text defines the sample, construction, exclusions, and audit.
\section{Results}\label{sec:results}
The main estimate is economically large and precisely benchmarked.
\appendix
\section{Extra checks}
Details.
""",
        )
        candidate = self.write(
            "candidate.tex",
            r"""
\section{Results}\label{sec:results}
The main estimate is economically large and precisely benchmarked.
\appendix
\section{Data and Sample}\label{sec:data}
The appendix defines the sample, construction, exclusions, and audit.
""",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "must_remain_main": [{"type": "label", "value": "sec:data"}],
            },
            baseline,
            candidate,
            authorize_destructive=False,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(report["status"], "fail")
        findings = " ".join(report["findings"]["failures"])
        self.assertIn("appendix move", findings)
        self.assertIn("must_remain_main", findings)

    def test_authorized_proof_only_migration_passes(self) -> None:
        baseline = self.write(
            "baseline.tex",
            r"""
\section{Theory}\label{sec:theory}
Agents face a constraint, change behavior, and generate the stated proposition.
The main text explains assumptions, mechanism, interpretation, and prediction.
\section{Proofs}\label{sec:proofs}
The algebra establishes the proposition step by step.
\appendix
\section{Other material}
Details.
""",
        )
        candidate = self.write(
            "candidate.tex",
            r"""
\section{Theory}\label{sec:theory}
Agents face a constraint, change behavior, and generate the stated proposition.
The main text explains assumptions, mechanism, interpretation, and prediction.
The formal proof appears in the appendix while its economic content remains here.
\appendix
\section{Proofs}\label{sec:proofs}
The algebra establishes the proposition step by step.
""",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "allowed_appendix_moves": ["Proofs"],
                "must_remain_main": ["sec:theory"],
            },
            baseline,
            candidate,
        )
        wrapped = json.loads(contract.read_text(encoding="utf-8"))
        proof_card = next(
            card
            for card in wrapped["artifact_contract"]["section_cards"]
            if card["baseline_section_name"] == "Proofs"
        )
        proof_card["must_remain_main"] = [
            {"type": "label", "value": "sec:theory"}
        ]
        self.write_json("contract.json", wrapped)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["status"], "pass")

    def test_authorized_short_form_ignores_default_fifteen_percent_gate(self) -> None:
        long_text = " ".join(["baseline discussion"] * 120)
        short_text = " ".join(["concise evidence"] * 25)
        baseline = self.write(
            "baseline.tex",
            f"\\section{{Analysis}}\n{long_text}\n\\appendix\n\\section{{Notes}}\nExtra.",
        )
        candidate = self.write(
            "candidate.tex",
            f"\\section{{Analysis}}\n{short_text}\n\\appendix\n\\section{{Notes}}\nExtra.",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "shorten",
                "mature_baseline": True,
                "target_main_source_word_range": [20, 80],
                "max_unapproved_main_reduction_pct": 0.15,
                "user_approved_compression": True,
                "target_basis": "user",
                "approval_record": {
                    "approval_authority": "author",
                    "approved_by": "Alice Example",
                    "approved_at": "2026-08-03T12:00:00+08:00",
                    "approval_source": "author confirmation fixture",
                    "approved_scope": ["compression"],
                },
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["status"], "pass")
        self.assertGreater(report["metrics"]["cumulative_reduction_pct"], 0.15)

    def test_unapproved_reduction_returns_approval_required(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Analysis}\n" + "evidence mechanism " * 100 + "\n\\appendix\nExtra.",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Analysis}\n" + "evidence mechanism " * 60 + "\n\\appendix\nExtra.",
        )
        contract = self.contract_with_ledger(
            {"task_mode": "major_revision", "mature_baseline": True},
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["status"], "approval_required")

    def test_full_redraft_requires_recoverable_author_approval(self) -> None:
        source = "\\section{Analysis}\nComplete evidence and interpretation.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        contract = self.contract_with_ledger(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "rewrite_mode": "full_redraft",
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["status"], "approval_required")
        self.assertIn("full_redraft", report["findings"]["approval_triggers"][0])

    def test_full_redraft_with_scoped_author_approval_passes(self) -> None:
        source = "\\section{Analysis}\nComplete evidence and interpretation.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        contract = self.contract_with_ledger(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "rewrite_mode": "full_redraft",
                "approval_record": {
                    "approval_authority": "author",
                    "approved_by": "Alice Example",
                    "approved_at": "2026-08-03T12:00:00+08:00",
                    "approval_source": "author confirmation fixture",
                    "approved_scope": ["full_redraft"],
                },
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["status"], "pass")

    def test_shorten_mode_without_target_or_approval_fails(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Analysis}\n" + "full evidence " * 40 + "\n\\appendix\nExtra.",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Analysis}\n" + "full evidence " * 20 + "\n\\appendix\nExtra.",
        )
        contract = self.contract_with_ledger(
            {"task_mode": "shorten", "mature_baseline": True},
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(report["status"], "fail")
        self.assertIn("requires a recorded target", report["findings"]["failures"][0])

    def test_missing_appendix_marker_is_metric_unavailable(self) -> None:
        baseline = self.write("baseline.tex", r"\section{Analysis} Complete text.")
        candidate = self.write("candidate.tex", r"\section{Analysis} Complete text.")
        contract = self.contract({"task_mode": "major_revision", "mature_baseline": True})
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(report["status"], "metric_unavailable")
        self.assertEqual(report["schema_id"], "manuscript-conservation-audit/1.0")
        self.assertEqual(report["gate_type"], "manuscript_conservation")
        self.assertEqual(report["audit_arguments"]["appendix_marker"], r"\appendix")
        self.assertIsNone(report["audit_arguments"]["word_metric"])
        self.assertEqual(
            report["inputs"]["baseline_sha256"],
            hashlib.sha256(baseline.read_bytes()).hexdigest(),
        )
        self.assertIn("measurement", report)
        self.assertIn("metrics", report)
        self.assertIn("conservation", report)
        self.assertEqual(
            report["conservation"]["two_pass_restructure"],
            {"required": False, "status": "not_applicable"},
        )
        self.assertIn("found 0", report["findings"]["warnings"][0])
        self.assertEqual(
            report["inputs"]["contract_sha256"],
            hashlib.sha256(contract.read_bytes()).hexdigest(),
        )

    def test_multiple_appendix_markers_are_metric_unavailable(self) -> None:
        baseline = self.write(
            "baseline.tex", r"\section{Analysis} Text.\appendix One.\appendix Two."
        )
        candidate = self.write(
            "candidate.tex", r"\section{Analysis} Text.\appendix One."
        )
        contract = self.contract(
            {"task_mode": "major_revision", "mature_baseline": True}
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(report["status"], "metric_unavailable")
        self.assertIn("found 2", report["findings"]["warnings"][0])

    def test_nested_inputs_and_commented_marker_pass(self) -> None:
        self.write(
            "parts/body.tex",
            r"""
\section{Data}\label{sec:data}
Sample and measurement details remain in the main text.
\input{nested/results}
""",
        )
        self.write(
            "parts/nested/results.tex",
            r"""
\section{Results}\label{sec:results}
Magnitude, benchmark, and interpretation remain in the main text.
""",
        )
        root_text = r"""
% \appendix is a comment and must not set the boundary
\input{parts/body}
\appendix
\section{Supplement}
Additional details.
"""
        baseline = self.write("baseline.tex", root_text)
        candidate = self.write("candidate.tex", root_text)
        contract = self.contract_with_ledger(
            {"task_mode": "restructure", "mature_baseline": True},
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(len(report["inputs"]["baseline_sources"]), 3)

    def test_bare_input_is_expanded_and_counted(self) -> None:
        self.write(
            "parts/body.tex",
            "\\section{Data}\\label{sec:data}\nBare include content remains visible.\n",
        )
        source = "\\input parts/body\n\\appendix\n\\section{Supplement}\nDetails.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        contract = self.contract_with_ledger(
            {"task_mode": "restructure", "mature_baseline": True},
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["status"], "pass")
        self.assertIn(str((self.root / "parts/body.tex").resolve()), report["inputs"]["baseline_sources"])
        self.assertEqual(report["metrics"]["baseline_main"]["structure"]["sections"], 1)

    def test_unsupported_include_command_fails_closed(self) -> None:
        self.write("parts/body.tex", "\\section{Data}\nContent.\n")
        source = "\\subfile{parts/body}\n\\appendix\nSupplement.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        contract = self.contract({"task_mode": "restructure", "mature_baseline": True})
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(report["status"], "metric_unavailable")
        self.assertIn("unsupported LaTeX include command", report["findings"]["warnings"][0])

    def test_candidate_only_budget_and_main_text_contract_passes(self) -> None:
        candidate = self.write(
            "candidate.tex",
            r"""
\section{Design}\label{sec:design}
The draft defines the sample and empirical comparison for the reader.
\appendix
\section{Supplement}
Additional details.
""",
        )
        contract = self.contract(
            self.new_draft_payload(
                ["Design"],
                target_main_source_word_range=[8, 40],
                hard_main_text_floor={"source_words": 8},
                must_remain_main=[{"type": "label", "value": "sec:design"}],
            )
        )
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["status"], "pass")
        self.assertIsNone(report["inputs"]["baseline"])
        self.assertIsNone(report["metrics"]["word_reduction_pct"])
        self.assertIsNone(report["metrics"]["page_reduction_pct"])
        self.assertIsNone(report["metrics"]["cumulative_reduction_pct"])
        self.assertFalse(report["measurement"]["baseline_comparison_applicable"])
        self.assertEqual(report["conservation"]["expected_baseline_block_ids"], [])
        self.assertEqual(
            report["conservation"]["candidate_only_full_draft_contract"]["status"],
            "pass",
        )
        self.assertEqual(
            report["conservation"]["two_pass_restructure"],
            {"required": False, "status": "not_applicable"},
        )

    def test_non_two_pass_major_revision_reports_not_applicable(self) -> None:
        source = (
            "\\section{Results}\\label{sec:results}\n"
            "The estimate, comparison, and interpretation remain fully reported.\n"
            "\\appendix\n\\section{Supplement}\nAdditional detail.\n"
        )
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        contract = self.contract_with_ledger(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "rewrite_mode": "patch_existing",
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["status"], "pass")
        self.assertEqual(
            report["conservation"]["two_pass_restructure"],
            {"required": False, "status": "not_applicable"},
        )

    def test_candidate_only_budget_or_must_remain_failure_is_not_a_reduction(self) -> None:
        candidate = self.write(
            "candidate.tex",
            r"\section{Results} Too short.\appendix Supplement.",
        )
        contract = self.contract(
            {
                "task_mode": "full_draft",
                "mature_baseline": False,
                "target_main_source_word_range": [20, 30],
                "hard_main_text_floor": {"source_words": 15},
                "must_remain_main": ["sec:data"],
            }
        )
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(report["status"], "fail")
        self.assertIsNone(report["metrics"]["cumulative_reduction_pct"])
        findings = " ".join(report["findings"]["failures"])
        self.assertIn("outside target range", findings)
        self.assertIn("must_remain_main", findings)

    def test_candidate_only_full_draft_missing_frozen_budget_and_depth_fails(self) -> None:
        candidate = self.write(
            "candidate.tex", "\\section{Draft} Text.\\appendix Extra."
        )
        contract = self.contract(
            {"task_mode": "full_draft", "mature_baseline": False}
        )
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        findings = " ".join(report["findings"]["failures"])
        self.assertIn("requires a source-word target range", findings)
        self.assertIn("requires nonempty section_cards", findings)
        self.assertIn("requires nonempty content_obligations", findings)

    def test_mature_section_cards_require_depth_and_main_text_obligations(self) -> None:
        source = (
            "\\section{Results}\\label{sec:results}\n"
            "The estimate, comparison, and interpretation remain fully reported.\n"
            "\\appendix\n\\section{Supplement}\nAdditional detail.\n"
        )
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        base_contract = self.contract_with_ledger(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "rewrite_mode": "patch_existing",
            },
            baseline,
            candidate,
        )
        original = json.loads(base_contract.read_text(encoding="utf-8"))

        for missing_field, expected in (
            ("minimum_depth_questions", "requires nonempty minimum_depth_questions"),
            ("must_remain_main", "requires nonempty must_remain_main"),
        ):
            payload = json.loads(json.dumps(original))
            payload["artifact_contract"]["section_cards"][0].pop(
                missing_field, None
            )
            contract = self.write_json(f"contract-missing-{missing_field}.json", payload)
            completed, report = self.run_audit(baseline, candidate, contract)
            self.assertEqual(completed.returncode, 1)
            self.assertIn(expected, " ".join(report["findings"]["failures"]))

    def test_candidate_only_section_card_budget_is_enforced(self) -> None:
        candidate = self.write(
            "candidate.tex", "\\section{Draft} Short text.\\appendix Extra."
        )
        payload = self.new_draft_payload(["Draft"])
        payload["section_cards"][0]["target_word_range"] = [100, 120]
        contract = self.contract(payload)
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "outside section-card target range",
            " ".join(report["findings"]["failures"]),
        )

    def test_missing_planned_section_fails_unless_card_is_explicitly_optional(self) -> None:
        candidate = self.write(
            "candidate.tex", "\\section{Draft} Complete text.\\appendix Extra."
        )
        payload = self.new_draft_payload(["Draft", "Mechanism"])
        contract = self.contract(payload)
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "required section card is missing from candidate main text: mechanism",
            report["findings"]["failures"],
        )

        payload["section_cards"][1]["optional"] = True
        contract = self.contract(payload)
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_translation_skips_cross_language_reduction_but_preserves_structure(self) -> None:
        baseline = self.write(
            "baseline.tex",
            r"""
\section{Data}\label{sec:data}
The source explains the sample construction, measurement, exclusions, and period in deliberately extended prose.
\section{Results}\label{sec:results}
The source reports the estimate, direction, magnitude, benchmark, and interpretation in deliberately extended prose.
\appendix
\section{Supplement}
Source detail.
""",
        )
        candidate = self.write(
            "candidate.tex",
            r"""
\section{数据}\label{sec:data}
正文说明样本、测量、排除规则与时期。
\section{结果}\label{sec:results}
正文报告估计方向、量级、基准与解释。
\appendix
\section{Supplement}
Source detail.
""",
        )
        baseline_inventory = self.inventories(baseline)
        candidate_inventory = self.inventories(candidate)
        ledger = []
        for source, destination in zip(baseline_inventory, candidate_inventory):
            disposition = (
                "unchanged"
                if source["block_id"] == destination["block_id"]
                else "revised"
            )
            entry = {
                "source_block_id": source["block_id"],
                "destination": destination["block_id"],
                "disposition": disposition,
            }
            if disposition == "revised":
                entry["authority"] = {
                    "role": "controller",
                    "by": "controller-test",
                    "at": "2026-08-03T12:00:00+08:00",
                }
                entry.update(
                    {
                        "source_function": "translated substantive block",
                        "reason": "document-level translation",
                        "retained_meaning_evidence": "source and target blocks are paired for semantic review",
                        "omitted_elements": [],
                    }
                )
            ledger.append(entry)
        contract = self.contract(
            {
                "task_mode": "document_translation",
                "mature_baseline": True,
                "source_language": "English",
                "target_language": "Chinese",
                "target_language_main_source_word_range": [9999, 10000],
                "measurement_contract": {
                    "cross_language_length_metric": "inapplicable"
                },
                "content_conservation_ledger": ledger,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["status"], "pass")
        self.assertIsNone(report["metrics"]["word_reduction_pct"])
        self.assertIsNone(report["metrics"]["cumulative_reduction_pct"])
        self.assertIsNone(report["metrics"]["max_unapproved_main_reduction_pct"])

    def test_translation_inapplicable_does_not_require_section_target_range(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Analysis}\nThe source explains the result and qualifier.\n"
            "\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Analysis}\n译文说明结果与限定条件。\n\\appendix\nExtra.\n",
        )
        baseline_main, _ = MODULE.split_appendix(
            MODULE.load_manuscript(baseline, self.root.resolve())[0],
            r"\appendix",
            "baseline",
            "tex",
        )
        candidate_main, _ = MODULE.split_appendix(
            MODULE.load_manuscript(candidate, self.root.resolve())[0],
            r"\appendix",
            "candidate",
            "tex",
        )
        baseline_section = MODULE.extract_sections(baseline_main, "tex")[0]
        candidate_section = MODULE.extract_sections(candidate_main, "tex")[0]
        contract = self.contract(
            {
                "task_mode": "document_translation",
                "mature_baseline": True,
                "source_language": "English",
                "target_language": "Chinese",
                "target_language_main_source_word_range": [9999, 10000],
                "measurement_contract": {
                    "cross_language_length_metric": "inapplicable"
                },
                "content_conservation_ledger": self.complete_ledger(
                    baseline, candidate
                ),
                "section_cards": [
                    {
                        "card_id": "analysis-translation",
                        "baseline_section_id": baseline_section["id"],
                        "baseline_section_name": baseline_section["title"],
                        "candidate_section_id": candidate_section["id"],
                        "candidate_section_name": candidate_section["title"],
                        "baseline_words": baseline_section["normalized_words"],
                        "target_word_range": [9999, 10000],
                        "maximum_reduction_pct": 0.0,
                        "minimum_depth_questions": [
                            "Does the translation retain the result and qualifier?"
                        ],
                        "must_remain_main": [
                            {"type": "section", "value": candidate_section["title"]}
                        ],
                    }
                ],
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        budget = report["conservation"]["mature_section_budget"]
        self.assertFalse(budget["target_ranges_enforced"])
        self.assertIsNone(budget["checks"][0]["target_word_range"])
        self.assertFalse(
            report["measurement"]["target_main_source_word_range_enforced"]
        )

    def test_translation_target_language_budget_only_requires_section_target_range(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Analysis}\nThe source explains the result and qualifier.\n"
            "\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Analysis}\n译文说明结果与限定条件。\n\\appendix\nExtra.\n",
        )
        baseline_main, _ = MODULE.split_appendix(
            MODULE.load_manuscript(baseline, self.root.resolve())[0],
            r"\appendix",
            "baseline",
            "tex",
        )
        candidate_main, _ = MODULE.split_appendix(
            MODULE.load_manuscript(candidate, self.root.resolve())[0],
            r"\appendix",
            "candidate",
            "tex",
        )
        baseline_section = MODULE.extract_sections(baseline_main, "tex")[0]
        candidate_section = MODULE.extract_sections(candidate_main, "tex")[0]
        payload = {
            "task_mode": "document_translation",
            "mature_baseline": True,
            "source_language": "English",
            "target_language": "Chinese",
            "target_language_main_source_word_range": [1, 100],
            "measurement_contract": {
                "cross_language_length_metric": "target_language_budget_only"
            },
            "content_conservation_ledger": self.complete_ledger(
                baseline, candidate
            ),
            "section_cards": [
                {
                    "card_id": "analysis-translation",
                    "baseline_section_id": baseline_section["id"],
                    "baseline_section_name": baseline_section["title"],
                    "candidate_section_id": candidate_section["id"],
                    "candidate_section_name": candidate_section["title"],
                    "baseline_words": baseline_section["normalized_words"],
                    "minimum_depth_questions": [
                        "Does the target-language section retain the full explanation?"
                    ],
                    "must_remain_main": [
                        {"type": "section", "value": candidate_section["title"]}
                    ],
                }
            ],
        }
        contract = self.contract(payload)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "requires a valid target_word_range",
            " ".join(report["findings"]["failures"]),
        )

        payload["section_cards"][0]["target_word_range"] = [1, 100]
        contract = self.contract(payload)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(
            report["conservation"]["mature_section_budget"][
                "target_ranges_enforced"
            ]
        )

    def test_translation_section_loss_still_fails(self) -> None:
        baseline = self.write(
            "baseline.tex",
            r"""
\section{Data}\label{sec:data}
The source defines the sample.
\section{Results}\label{sec:results}
The source reports the result.
\appendix
\section{Supplement}
Detail.
""",
        )
        candidate = self.write(
            "candidate.tex",
            r"""
\section{数据}\label{sec:data}
译文定义样本。
\appendix
\section{Supplement}
Detail.
""",
        )
        baseline_inventory = self.inventories(baseline)
        candidate_inventory = self.inventories(candidate)
        ledger = []
        for index, source in enumerate(baseline_inventory):
            destination = candidate_inventory[min(index, len(candidate_inventory) - 1)]
            disposition = "renamed" if index == 0 else "deleted"
            entry = {
                "source_block_id": source["block_id"],
                "disposition": disposition,
            }
            if disposition == "renamed":
                entry.update(
                    {
                        "destination": destination["block_id"],
                        "authority": {
                            "role": "controller",
                            "by": "controller-test",
                            "at": "2026-08-03T12:00:00+08:00",
                        },
                    }
                )
            ledger.append(entry)
        contract = self.contract(
            {
                "task_mode": "translation",
                "mature_baseline": True,
                "source_language": "English",
                "target_language": "Chinese",
                "measurement_contract": {
                    "cross_language_length_metric": "inapplicable"
                },
                "content_conservation_ledger": ledger,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        findings = " ".join(report["findings"]["failures"])
        self.assertIn("whole-section disappearance", findings)
        self.assertIn("label disappeared", findings)

    def test_translation_requires_languages_and_length_contract(self) -> None:
        source = "\\section{One}\nText.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        ledger = self.complete_ledger(baseline, candidate)
        contract = self.contract(
            {
                "task_mode": "translation",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
                "measurement_contract": {},
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        findings = " ".join(report["findings"]["failures"])
        self.assertIn("source_language and target_language", findings)
        self.assertIn("cross_language_length_metric=inapplicable", findings)

    def test_translation_rejects_unsupported_cross_language_metric(self) -> None:
        source = "\\section{One}\nText.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        contract = self.contract(
            {
                "task_mode": "document_translation",
                "mature_baseline": True,
                "source_language": "English",
                "target_language": "Chinese",
                "target_language_main_source_word_range": [1, 100],
                "measurement_contract": {
                    "cross_language_length_metric": "same_language_comparison"
                },
                "content_conservation_ledger": self.complete_ledger(
                    baseline, candidate
                ),
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "cross_language_length_metric must be inapplicable or "
            "target_language_budget_only",
            " ".join(report["findings"]["failures"]),
        )

    def test_source_child_mutation_changes_per_file_and_expanded_hashes(self) -> None:
        child = self.write(
            "parts/body.tex",
            "\\section{Data} Initial child content remains visible.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\input{parts/body}\n\\appendix\n\\section{Supplement} Detail.\n",
        )
        contract = self.contract(self.new_draft_payload(["Data"]))
        first_completed, first = self.run_audit(None, candidate, contract)
        self.assertEqual(first_completed.returncode, 0)
        child_record = next(
            item
            for item in first["inputs"]["candidate_source_files"]
            if item["path"] == str(child.resolve())
        )
        child.write_text(
            "\\section{Data} Mutated child content changes the expansion.\n",
            encoding="utf-8",
        )
        second_completed, second = self.run_audit(None, candidate, contract)
        self.assertEqual(second_completed.returncode, 0)
        changed_record = next(
            item
            for item in second["inputs"]["candidate_source_files"]
            if item["path"] == str(child.resolve())
        )
        self.assertEqual(first["inputs"]["candidate_sha256"], second["inputs"]["candidate_sha256"])
        self.assertNotEqual(child_record["sha256"], changed_record["sha256"])
        self.assertNotEqual(
            first["inputs"]["candidate_expanded_sha256"],
            second["inputs"]["candidate_expanded_sha256"],
        )

    def test_expanded_hash_matches_qa_preparer_with_comments_and_nested_include(self) -> None:
        self.write(
            "parts/nested.tex",
            "\\section{Results} Result text. % nested comment\n",
        )
        self.write(
            "parts/body.tex",
            "\\section{Data} Data text. % body comment\n\\input{nested}\n",
        )
        candidate = self.write(
            "candidate.tex",
            "% root comment with \\appendix\n\\input{parts/body}\n\\appendix\nSupplement.\n",
        )
        conservation_text, _ = MODULE.expand_tex(candidate, self.root.resolve())
        prepared = PREPARE_MODULE.expand_tex(candidate, self.root.resolve())
        self.assertEqual(conservation_text, prepared.text)
        contract = self.contract(
            self.new_draft_payload(["Data", "Results"])
        )
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(
            report["inputs"]["candidate_expanded_sha256"],
            PREPARE_MODULE.sha256_text(prepared.text),
        )

    def test_live_hash_bound_main_text_page_attestation_passes(self) -> None:
        source = "\\section{Analysis}\nComplete text.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        baseline_pdf = self.write("baseline.pdf", "baseline pdf bytes")
        candidate_pdf = self.write("candidate.pdf", "candidate pdf bytes")
        measurement = {
            "appendix_boundary": r"\appendix",
            "pdf_main_page_method": "compiled main-text-only pages before appendix",
            "measured_by": "controller-test",
            "measured_at": "2026-08-03T12:00:00+08:00",
            "attested_main_text_pages": {
                "baseline": {
                    "pages": 20,
                    "pdf_path": baseline_pdf.name,
                    "pdf_sha256": hashlib.sha256(baseline_pdf.read_bytes()).hexdigest(),
                },
                "candidate": {
                    "pages": 18,
                    "pdf_path": candidate_pdf.name,
                    "pdf_sha256": hashlib.sha256(candidate_pdf.read_bytes()).hexdigest(),
                },
            },
        }
        contract = self.contract_with_ledger(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "measurement_contract": measurement,
                "hard_main_text_floor": {"pdf_pages": 15},
                "target_main_pdf_page_range": [15, 25],
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(
            baseline,
            candidate,
            contract,
            "--baseline-main-pdf-pages",
            "20",
            "--candidate-main-pdf-pages",
            "18",
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        verified = report["measurement"]["verified_page_attestation"]
        self.assertEqual(verified["candidate"]["pdf_sha256"], measurement["attested_main_text_pages"]["candidate"]["pdf_sha256"])

    def test_candidate_only_page_budget_needs_only_candidate_attestation(self) -> None:
        candidate = self.write(
            "candidate.tex", "\\section{Draft} Text.\\appendix Extra."
        )
        candidate_pdf = self.write("candidate.pdf", "candidate-only pdf")
        contract = self.contract(
            self.new_draft_payload(
                ["Draft"],
                target_main_source_word_range=None,
                hard_main_text_floor={"pdf_pages": 5},
                target_main_pdf_page_range=[5, 8],
                measurement_contract={
                    "appendix_boundary": r"\appendix",
                    "pdf_main_page_method": "main-text-only pages before appendix",
                    "measured_by": "controller-test",
                    "measured_at": "2026-08-03T12:00:00+08:00",
                    "attested_main_text_pages": {
                        "candidate": {
                            "pages": 6,
                            "pdf_path": candidate_pdf.name,
                            "pdf_sha256": hashlib.sha256(candidate_pdf.read_bytes()).hexdigest(),
                        }
                    },
                },
            )
        )
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["measurement"]["candidate_main_pdf_pages"], 6)
        self.assertIsNone(report["measurement"]["baseline_main_pdf_pages"])

    def test_total_pdf_pages_attestation_is_rejected(self) -> None:
        source = "\\section{Analysis} Text.\\appendix Extra."
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        baseline_pdf = self.write("baseline.pdf", "baseline pdf")
        candidate_pdf = self.write("candidate.pdf", "candidate pdf")
        contract = self.contract_with_ledger(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "hard_main_text_floor": {"pdf_pages": 1},
                "measurement_contract": {
                    "appendix_boundary": r"\appendix",
                    "pdf_main_page_method": "total_pdf_pages",
                    "measured_by": "controller-test",
                    "measured_at": "2026-08-03T12:00:00+08:00",
                    "total_pdf_pages": 9,
                    "attested_main_text_pages": {
                        "baseline": {"pages": 2, "pdf_path": baseline_pdf.name, "pdf_sha256": hashlib.sha256(baseline_pdf.read_bytes()).hexdigest()},
                        "candidate": {"pages": 2, "pdf_path": candidate_pdf.name, "pdf_sha256": hashlib.sha256(candidate_pdf.read_bytes()).hexdigest()},
                    },
                },
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 3)
        self.assertIn("total_pdf_pages", report["findings"]["warnings"][0])

    def test_stale_attested_pdf_hash_is_rejected(self) -> None:
        source = "\\section{Analysis} Text.\\appendix Extra."
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        baseline_pdf = self.write("baseline.pdf", "baseline pdf")
        candidate_pdf = self.write("candidate.pdf", "candidate pdf before")
        measurement = {
            "appendix_boundary": r"\appendix",
            "pdf_main_page_method": "main-text-only pages before appendix",
            "measured_by": "controller-test",
            "measured_at": "2026-08-03T12:00:00+08:00",
            "attested_main_text_pages": {
                "baseline": {"pages": 2, "pdf_path": baseline_pdf.name, "pdf_sha256": hashlib.sha256(baseline_pdf.read_bytes()).hexdigest()},
                "candidate": {"pages": 2, "pdf_path": candidate_pdf.name, "pdf_sha256": hashlib.sha256(candidate_pdf.read_bytes()).hexdigest()},
            },
        }
        contract = self.contract_with_ledger(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "hard_main_text_floor": {"pdf_pages": 1},
                "measurement_contract": measurement,
            },
            baseline,
            candidate,
        )
        candidate_pdf.write_text("candidate pdf after", encoding="utf-8")
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 3)
        self.assertIn("attested PDF hash is stale", report["findings"]["warnings"][0])

    def test_forged_baseline_main_source_words_fails_live_binding(self) -> None:
        source = "\\section{Analysis}\nBound source text.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        contract = self.contract_with_ledger(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "baseline_main_source_words": 9999,
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "baseline_main_source_words 9999 does not equal live",
            " ".join(report["findings"]["failures"]),
        )

    def test_forged_baseline_main_pdf_pages_fails_attested_binding(self) -> None:
        source = "\\section{Analysis}\nBound source text.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        baseline_pdf = self.write("baseline.pdf", "baseline PDF fixture")
        candidate_pdf = self.write("candidate.pdf", "candidate PDF fixture")
        measurement = {
            "appendix_boundary": r"\appendix",
            "pdf_main_page_method": "compiled main-text-only pages before appendix",
            "measured_by": "controller-test",
            "measured_at": "2026-08-03T12:00:00+08:00",
            "attested_main_text_pages": {
                "baseline": {
                    "pages": 20,
                    "pdf_path": baseline_pdf.name,
                    "pdf_sha256": hashlib.sha256(
                        baseline_pdf.read_bytes()
                    ).hexdigest(),
                },
                "candidate": {
                    "pages": 20,
                    "pdf_path": candidate_pdf.name,
                    "pdf_sha256": hashlib.sha256(
                        candidate_pdf.read_bytes()
                    ).hexdigest(),
                },
            },
        }
        contract = self.contract_with_ledger(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "measurement_contract": measurement,
                "baseline_main_pdf_pages": 21,
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "baseline_main_pdf_pages does not equal the live attested baseline pages",
            " ".join(report["findings"]["failures"]),
        )

    def test_forged_section_card_baseline_words_fails_live_binding(self) -> None:
        source = "\\section{Analysis}\nBound source text.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        contract = self.contract_with_ledger(
            {"task_mode": "major_revision", "mature_baseline": True},
            baseline,
            candidate,
        )
        payload = json.loads(contract.read_text(encoding="utf-8"))
        card = payload["artifact_contract"]["section_cards"][0]
        card["baseline_words"] = float(card["baseline_words"]) + 1
        contract.write_text(json.dumps(payload), encoding="utf-8")
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "baseline_words must equal live",
            " ".join(report["findings"]["failures"]),
        )

    def test_single_section_overcompression_fails_when_global_reduction_is_below_fifteen_percent(self) -> None:
        stable_text = "stable evidence " * 300
        baseline = self.write(
            "baseline.tex",
            "\\section{Core}\n"
            + stable_text
            + "\n\\section{Mechanism}\n"
            + ("mechanism detail " * 20)
            + "\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Core}\n"
            + stable_text
            + "\n\\section{Mechanism}\nMechanism.\n\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {"task_mode": "major_revision", "mature_baseline": True},
            baseline,
            candidate,
        )
        payload = json.loads(contract.read_text(encoding="utf-8"))
        mechanism_card = next(
            card
            for card in payload["artifact_contract"]["section_cards"]
            if card["baseline_section_name"] == "Mechanism"
        )
        mechanism_card["maximum_reduction_pct"] = 0.20
        contract.write_text(json.dumps(payload), encoding="utf-8")
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertLess(report["metrics"]["word_reduction_pct"], 0.15)
        self.assertIn(
            "exceeds maximum 20.0%",
            " ".join(report["findings"]["failures"]),
        )

    def test_same_name_stub_cannot_override_validated_ledger_destination(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Data}\nOriginal data content remains.\n"
            "\\appendix\n\\section{Supplement}\nDetail.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Data}\nA same-name stub.\n"
            "\\section{Results}\nOriginal data content remains.\n"
            "\\appendix\n\\section{Supplement}\nDetail.\n",
        )
        baseline_inventory = self.inventories(baseline)
        candidate_inventory = self.inventories(candidate)
        ledger: list[dict] = []
        for source in baseline_inventory:
            destination = next(
                item
                for item in candidate_inventory
                if item["region"] == source["region"]
                and item["content_sha256"] == source["content_sha256"]
                and item.get("inventory_kind") == source.get("inventory_kind")
            )
            disposition = (
                "reordered" if source["region"] == "main_text" else "unchanged"
            )
            entry = {
                "source_block_id": source["block_id"],
                "destination": destination["block_id"],
                "disposition": disposition,
            }
            if disposition == "reordered":
                entry["authority"] = {
                    "role": "controller",
                    "by": "controller-test",
                    "at": "2026-08-03T12:00:00+08:00",
                }
            ledger.append(entry)
        baseline_main, _ = MODULE.split_appendix(
            MODULE.load_manuscript(baseline, self.root.resolve())[0],
            r"\appendix",
            "baseline",
            "tex",
        )
        candidate_main, _ = MODULE.split_appendix(
            MODULE.load_manuscript(candidate, self.root.resolve())[0],
            r"\appendix",
            "candidate",
            "tex",
        )
        baseline_section = MODULE.extract_sections(baseline_main, "tex")[0]
        stub_section = MODULE.extract_sections(candidate_main, "tex")[0]
        contract = self.contract(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
                "section_cards": [
                    {
                        "card_id": "data-card",
                        "baseline_section_id": baseline_section["id"],
                        "baseline_section_name": "Data",
                        "candidate_section_id": stub_section["id"],
                        "candidate_section_name": "Data",
                        "baseline_words": baseline_section["normalized_words"],
                        "target_word_range": [0, 100],
                        "maximum_reduction_pct": 1.0,
                    }
                ],
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "disagrees with validated ledger destination section results#1",
            " ".join(report["findings"]["failures"]),
        )

    def test_authorized_section_rename_with_verified_destination_passes(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Old Name}\nSame substantive paragraph.\n\\appendix\n\\section{Supplement}\nDetail.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{New Name}\nSame substantive paragraph.\n\\appendix\n\\section{Supplement}\nDetail.\n",
        )
        baseline_inventory = self.inventories(baseline)
        candidate_inventory = self.inventories(candidate)
        ledger = []
        for source, destination in zip(baseline_inventory, candidate_inventory):
            disposition = "renamed" if source["region"] == "main_text" else "unchanged"
            entry = {"source_block_id": source["block_id"], "destination": destination["block_id"], "disposition": disposition}
            if disposition == "renamed":
                entry["authority"] = {"role": "controller", "by": "controller-test", "at": "2026-08-03T12:00:00+08:00"}
            ledger.append(entry)
        contract = self.contract(
            {"task_mode": "restructure", "mature_baseline": True, "content_conservation_ledger": ledger}
        )
        wrapped = json.loads(contract.read_text(encoding="utf-8"))
        wrapped["artifact_contract"]["section_cards"][0]["must_remain_main"] = [
            {"type": "section", "value": "New Name"}
        ]
        self.write_json("contract.json", wrapped)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(report["conservation"]["whole_sections_missing_or_moved"][0]["ledger_exempted"])

    def test_rename_without_authority_cannot_exempt_disappeared_section(self) -> None:
        baseline = self.write("baseline.tex", "\\section{Old}\nText.\n\\appendix\nExtra.\n")
        candidate = self.write("candidate.tex", "\\section{New}\nText.\n\\appendix\nExtra.\n")
        baseline_inventory = self.inventories(baseline)
        candidate_inventory = self.inventories(candidate)
        ledger = [
            {"source_block_id": source["block_id"], "destination": destination["block_id"], "disposition": "renamed" if source["region"] == "main_text" else "unchanged"}
            for source, destination in zip(baseline_inventory, candidate_inventory)
        ]
        contract = self.contract(
            {"task_mode": "restructure", "mature_baseline": True, "baseline_to_candidate": ledger}
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("requires dated controller or author authority", " ".join(report["findings"]["failures"]))

    def test_authorized_many_to_one_merge_passes(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Analysis}\nFirst substantive block.\n\nSecond substantive block.\n\\appendix\n\\section{Supplement}\nDetail.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Analysis}\nFirst substantive block. Second substantive block.\n\\appendix\n\\section{Supplement}\nDetail.\n",
        )
        baseline_inventory = self.inventories(baseline)
        candidate_inventory = self.inventories(candidate)
        main_destination = next(item for item in candidate_inventory if item["region"] == "main_text")
        appendix_destination = next(item for item in candidate_inventory if item["region"] == "appendix")
        ledger = []
        for source in baseline_inventory:
            if source["region"] == "main_text":
                ledger.append(
                    {
                        "source_block_id": source["block_id"],
                        "destination": main_destination["block_id"],
                        "disposition": "merged",
                        "authority": {"role": "controller", "by": "controller-test", "at": "2026-08-03T12:00:00+08:00"},
                        "source_function": "preserve the section's substantive claim",
                        "reason": "combine two short sections without deleting either claim",
                        "retained_meaning_evidence": "both source sentences appear in the combined destination",
                        "omitted_elements": [],
                    }
                )
            else:
                ledger.append({"source_block_id": source["block_id"], "destination": appendix_destination["block_id"], "disposition": "unchanged"})
        contract = self.contract(
            {"task_mode": "restructure", "mature_baseline": True, "content_conservation_ledger": ledger}
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_cross_section_merge_with_shared_destination_fails_closed(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Data}\nFirst substantive block.\n\n"
            "\\section{Results}\nSecond substantive block.\n"
            "\\appendix\n\\section{Supplement}\nDetail.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Combined}\nFirst substantive block. Second substantive block.\n"
            "\\appendix\n\\section{Supplement}\nDetail.\n",
        )
        baseline_inventory = self.inventories(baseline)
        candidate_inventory = self.inventories(candidate)
        main_destination = next(
            item for item in candidate_inventory if item["region"] == "main_text"
        )
        appendix_destination = next(
            item for item in candidate_inventory if item["region"] == "appendix"
        )
        ledger = []
        for source in baseline_inventory:
            if source["region"] == "main_text":
                ledger.append(
                    {
                        "source_block_id": source["block_id"],
                        "destination": main_destination["block_id"],
                        "disposition": "merged",
                        "authority": {
                            "role": "controller",
                            "by": "controller-test",
                            "at": "2026-08-03T12:00:00+08:00",
                        },
                        "source_function": "preserve each source section claim",
                        "reason": "combine two sections",
                        "retained_meaning_evidence": "both source sentences remain",
                        "omitted_elements": [],
                    }
                )
            else:
                ledger.append(
                    {
                        "source_block_id": source["block_id"],
                        "destination": appendix_destination["block_id"],
                        "disposition": "unchanged",
                    }
                )
        contract = self.contract(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        findings = " ".join(report["findings"]["failures"])
        self.assertIn("receives ledger destinations from multiple baseline sections", findings)
        self.assertIn("measured by multiple cards without nonoverlapping ledger_slice", findings)

    def test_complete_nonoverlapping_ledger_slices_allow_unambiguous_split(self) -> None:
        baseline, candidate, ledger, cards = self.split_section_fixture()
        contract = self.contract(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
                "section_cards": cards,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        checks = report["conservation"]["mature_section_budget"]["checks"]
        self.assertEqual(
            {check["measurement_scope"] for check in checks}, {"ledger_slice"}
        )

    def test_ledger_slices_honor_raw_source_word_metric(self) -> None:
        baseline, candidate, ledger, cards = self.split_section_fixture()
        baseline_inventory = {
            item["block_id"]: item for item in self.inventories(baseline)
        }
        for card in cards:
            source_id = card["ledger_slice"]["baseline_block_ids"][0]
            card["baseline_words"] = baseline_inventory[source_id][
                "raw_source_words"
            ]
        contract = self.contract(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "measurement_contract": {
                    "source_word_method": "raw_source_words"
                },
                "content_conservation_ledger": ledger,
                "section_cards": cards,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        budget = report["conservation"]["mature_section_budget"]
        self.assertEqual(budget["word_metric"], "raw_source_words")
        self.assertTrue(
            all(
                check["baseline_observed"] == check["baseline_declared"]
                for check in budget["checks"]
            )
        )

    def test_unsliced_section_split_fails_closed(self) -> None:
        baseline, candidate, ledger, _ = self.split_section_fixture()
        contract = self.contract(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "maps to multiple candidate sections",
            " ".join(report["findings"]["failures"]),
        )

    def test_ledger_slice_destination_declaration_must_match_validated_ledger(self) -> None:
        baseline, candidate, ledger, cards = self.split_section_fixture()
        cards[0]["ledger_slice"]["destination_block_ids"] = list(
            cards[1]["ledger_slice"]["destination_block_ids"]
        )
        contract = self.contract(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
                "section_cards": cards,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "destination block IDs do not exactly match the validated ledger",
            " ".join(report["findings"]["failures"]),
        )

    def test_ledger_slices_must_not_overlap_and_must_cover_live_prose(self) -> None:
        baseline, candidate, ledger, cards = self.split_section_fixture()
        cards[1]["ledger_slice"]["baseline_block_ids"] = list(
            cards[0]["ledger_slice"]["baseline_block_ids"]
        )
        cards[1]["baseline_words"] = cards[0]["baseline_words"]
        contract = self.contract(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
                "section_cards": cards,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        findings = " ".join(report["findings"]["failures"])
        self.assertIn("overlaps cards", findings)
        self.assertIn("must exactly cover live prose blocks", findings)

    def test_authorized_reordered_dispositions_pass(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Analysis}\nFirst block.\n\nSecond block.\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Analysis}\nSecond block.\n\nFirst block.\n\\appendix\nExtra.\n",
        )
        ledger = self.complete_ledger(baseline, candidate)
        for entry in ledger:
            source = next(
                item
                for item in self.inventories(baseline)
                if item["block_id"] == entry["source_block_id"]
            )
            if source["region"] == "main_text":
                entry["disposition"] = "reordered"
                entry["authority"] = {
                    "role": "controller",
                    "by": "controller-test",
                    "at": "2026-08-03T12:00:00+08:00",
                }
        contract = self.contract(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "rewrite_mode": "reorder_existing_blocks",
                "content_conservation_ledger": ledger,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_authorized_whole_section_delete_with_label_passes(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Keep} Kept block.\n\\section{Delete Me}\\label{sec:delete} Deleted block.\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Keep} Kept block.\n\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "user_approved_compression": True,
                "approval_record": {
                    "approval_authority": "author",
                    "approved_by": "Alice Example",
                    "approved_at": "2026-08-03T12:00:00+08:00",
                    "approval_source": "author confirmation fixture",
                    "approved_scope": ["compression", "delete:sec:delete"],
                },
            },
            baseline,
            candidate,
        )
        wrapped = json.loads(contract.read_text(encoding="utf-8"))
        deleted_card = next(
            card
            for card in wrapped["artifact_contract"]["section_cards"]
            if card["baseline_section_name"] == "Delete Me"
        )
        deleted_card["must_remain_main"] = [
            {"type": "section", "value": "Keep"}
        ]
        self.write_json("contract.json", wrapped)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["conservation"]["labels_missing_entirely"], ["sec:delete"])

    def test_authorized_whole_section_move_to_appendix_passes(self) -> None:
        extracted = MODULE.extract_sections(
            "\\section{Methods}\\label{sec:methods}\n"
            "Body object. \\label{fig:not-a-heading-label}\n",
            "tex",
        )[0]
        self.assertEqual(extracted["heading_labels"], ["sec:methods"])
        self.assertEqual(
            extracted["labels"], ["fig:not-a-heading-label", "sec:methods"]
        )
        baseline = self.write(
            "baseline.tex",
            "\\section{Keep}\nKept main-text block.\n"
            "\\section{Methods}\\label{sec:methods}\nMovable methods block.\n"
            "\\appendix\n\\section{Supplement}\nDetail.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Keep}\nKept main-text block.\n\\appendix\n"
            "\\section{Methods}\\label{sec:methods}\nMovable methods block.\n"
            "\\section{Supplement}\nDetail.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "allowed_appendix_moves": ["sec:methods"],
                "user_approved_compression": True,
                "approval_record": {
                    "approval_authority": "author",
                    "approved_by": "Alice Example",
                    "approved_at": "2026-08-03T12:00:00+08:00",
                    "approval_source": "author confirmation fixture",
                    "approved_scope": ["compression"],
                },
            },
            baseline,
            candidate,
        )
        wrapped = json.loads(contract.read_text(encoding="utf-8"))
        methods_card = next(
            card
            for card in wrapped["artifact_contract"]["section_cards"]
            if card["baseline_section_name"] == "Methods"
        )
        methods_card["must_remain_main"] = [
            {"type": "section", "value": "Keep"}
        ]
        self.write_json("contract.json", wrapped)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        moved_check = next(
            check
            for check in report["conservation"]["mature_section_budget"]["checks"]
            if check["baseline_selector"] == "methods#1"
        )
        self.assertTrue(moved_check["authorized_absence"])

    def test_duplicate_section_names_require_explicit_live_ids(self) -> None:
        source = (
            "\\section{Data}\nFirst data block.\n"
            "\\section{Data}\nSecond data block.\n"
            "\\appendix\nExtra.\n"
        )
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        baseline_main, _ = MODULE.split_appendix(
            MODULE.load_manuscript(baseline, self.root.resolve())[0],
            r"\appendix",
            "baseline",
            "tex",
        )
        sections = MODULE.extract_sections(baseline_main, "tex")
        common = {
            "target_word_range": [0, 100],
            "maximum_reduction_pct": 1.0,
        }
        payload = {
            "task_mode": "major_revision",
            "mature_baseline": True,
            "content_conservation_ledger": self.complete_ledger(
                baseline, candidate
            ),
            "section_cards": [
                {
                    **common,
                    "card_id": "data-one",
                    "baseline_section_name": "Data",
                    "candidate_section_id": sections[0]["id"],
                    "baseline_words": sections[0]["normalized_words"],
                },
                {
                    **common,
                    "card_id": "data-two",
                    "baseline_section_id": sections[1]["id"],
                    "candidate_section_id": sections[1]["id"],
                    "baseline_words": sections[1]["normalized_words"],
                },
            ],
        }
        contract = self.contract(payload)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "baseline_section_name matches multiple live sections; explicit baseline_section_id is required",
            " ".join(report["findings"]["failures"]),
        )

        payload["section_cards"][0]["baseline_section_id"] = sections[0]["id"]
        payload["section_cards"][0].pop("baseline_section_name")
        payload["section_cards"][0].pop("candidate_section_id")
        payload["section_cards"][0]["candidate_section_name"] = "Data"
        contract = self.contract(payload)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "candidate_section_name matches multiple live sections; explicit candidate_section_id is required",
            " ".join(report["findings"]["failures"]),
        )

    def test_legacy_section_id_is_only_an_equal_card_id_alias(self) -> None:
        source = "\\section{Analysis}\nBound text.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        contract = self.contract_with_ledger(
            {"task_mode": "major_revision", "mature_baseline": True},
            baseline,
            candidate,
        )
        payload = json.loads(contract.read_text(encoding="utf-8"))
        card = payload["artifact_contract"]["section_cards"][0]
        legacy_id = card.pop("card_id")
        card["section_id"] = legacy_id
        contract.write_text(json.dumps(payload), encoding="utf-8")
        completed, _ = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

        card["card_id"] = "conflicting-card-id"
        contract.write_text(json.dumps(payload), encoding="utf-8")
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "conflicting card_id and legacy section_id",
            " ".join(report["findings"]["failures"]),
        )

    def test_partial_ledger_fails_exact_coverage(self) -> None:
        source = "\\section{One}\nParagraph one.\n\nParagraph two.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        ledger = self.complete_ledger(baseline, candidate)
        omitted = ledger.pop(0)["source_block_id"]
        contract = self.contract(
            {"task_mode": "restructure", "mature_baseline": True, "content_conservation_ledger": ledger}
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(f"{omitted}; found 0", " ".join(report["findings"]["failures"]))

    def test_duplicate_ledger_source_fails_exact_coverage(self) -> None:
        source = "\\section{One}\nParagraph.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        ledger = self.complete_ledger(baseline, candidate)
        duplicate = dict(ledger[0])
        ledger.append(duplicate)
        contract = self.contract(
            {"task_mode": "restructure", "mature_baseline": True, "content_conservation_ledger": ledger}
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("found 2", " ".join(report["findings"]["failures"]))

    def test_unknown_baseline_block_in_ledger_fails(self) -> None:
        source = "\\section{One}\nParagraph.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        ledger = self.complete_ledger(baseline, candidate)
        ledger.append({"source_block_id": "block-unknown-1", "destination": ledger[0]["destination"], "disposition": "unchanged"})
        contract = self.contract(
            {"task_mode": "restructure", "mature_baseline": True, "content_conservation_ledger": ledger}
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("unknown baseline block", " ".join(report["findings"]["failures"]))

    def test_unverifiable_candidate_destination_fails(self) -> None:
        source = "\\section{One}\nParagraph.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        ledger = self.complete_ledger(baseline, candidate)
        ledger[0]["destination"] = "block-does-not-exist"
        contract = self.contract(
            {"task_mode": "restructure", "mature_baseline": True, "content_conservation_ledger": ledger}
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("destination is not verifiable", " ".join(report["findings"]["failures"]))

    def test_unknown_disposition_fails(self) -> None:
        source = "\\section{One}\nParagraph.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        ledger = self.complete_ledger(baseline, candidate)
        ledger[0]["disposition"] = "teleported"
        contract = self.contract(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("invalid disposition", " ".join(report["findings"]["failures"]))

    def test_mature_full_draft_contract_is_contradictory(self) -> None:
        source = "\\section{One}\nParagraph.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        contract = self.contract_with_ledger(
            {"task_mode": "full_draft", "mature_baseline": True}, baseline, candidate
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("conflicts with task_mode full_draft", " ".join(report["findings"]["failures"]))

    def test_paper_state_artifact_contract_and_sibling_ledger_are_supported(self) -> None:
        source = "\\section{One}\nParagraph.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        ledger = self.complete_ledger(baseline, candidate)
        baseline_main, _ = MODULE.split_appendix(
            MODULE.load_manuscript(baseline, self.root.resolve())[0],
            r"\appendix",
            "baseline",
            "tex",
        )
        baseline_section = MODULE.extract_sections(baseline_main, "tex")[0]
        candidate_expanded_sha = MODULE.sha256_text(
            MODULE.load_manuscript(candidate, self.root.resolve())[0]
        )
        contract = self.write(
            "contract.json",
            json.dumps(
                {
                    "paper_state": {
                        "artifact_contract": {
                            "task_mode": "restructure",
                            "mature_baseline": True,
                            "metric_status": "measured",
                            "measurement_contract": {
                                "appendix_boundary": r"\appendix",
                                "source_word_method": "normalized_words",
                            },
                            "baseline_main_source_words": MODULE.normalized_words(
                                baseline_main, "tex"
                            ),
                            "section_cards": [
                                {
                                    "card_id": "card-results",
                                    "section_name": "One",
                                    "baseline_section_id": baseline_section["id"],
                                    "baseline_section_name": "One",
                                    "candidate_section_id": baseline_section["id"],
                                    "candidate_section_name": "One",
                                    "baseline_words": baseline_section[
                                        "normalized_words"
                                    ],
                                    "target_word_range": [0, 100],
                                    "maximum_reduction_pct": 1.0,
                                    "minimum_depth_questions": [
                                        "What must Results explain?"
                                    ],
                                    "must_remain_main": [
                                        {"type": "section", "value": "One"}
                                    ],
                                }
                            ],
                            "rewrite_mode": "patch_existing",
                            "baseline_artifact": {
                                "path": str(baseline.resolve()),
                                "sha256": hashlib.sha256(
                                    baseline.read_bytes()
                                ).hexdigest(),
                                "acceptance_status": "accepted",
                                "accepted_by": "Alice Example",
                            },
                            "two_pass_restructure": {
                                "architecture_pass": {
                                    "status": "completed",
                                    "mode": "reorder_existing_blocks",
                                    "artifact_path": str(candidate.resolve()),
                                    "artifact_sha256": hashlib.sha256(
                                        candidate.read_bytes()
                                    ).hexdigest(),
                                    "expanded_sha256": candidate_expanded_sha,
                                    "completed_by": "controller-test",
                                    "completed_at": "2026-08-03T12:00:00+08:00",
                                    "content_conservation_ledger": ledger,
                                },
                                "compression_pass": {
                                    "status": "not_needed",
                                    "mode": "none",
                                    "source_expanded_sha256": candidate_expanded_sha,
                                    "candidate_expanded_sha256": candidate_expanded_sha,
                                    "completed_by": "controller-test",
                                    "completed_at": "2026-08-03T12:01:00+08:00",
                                },
                            },
                        },
                        "content_conservation_ledger": ledger,
                    }
                }
            ),
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertTrue(report["conservation"]["ledger_required"])

    def test_local_edit_does_not_invent_fifteen_percent_gate(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{One}\n" + "Long baseline content. " * 100 + "\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{One}\n" + "Short content. " * 20 + "\n\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {"task_mode": "local_edit", "mature_baseline": True}, baseline, candidate
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertGreater(report["metrics"]["word_reduction_pct"], 0.15)
        self.assertIsNone(report["metrics"]["max_unapproved_main_reduction_pct"])

    def test_major_revision_without_mature_true_does_not_get_default_fifteen_percent(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{One}\n" + "Baseline evidence. " * 100 + "\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{One}\n" + "Candidate evidence. " * 20 + "\n\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {"task_mode": "major_revision", "mature_baseline": False},
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertGreater(report["metrics"]["word_reduction_pct"], 0.15)
        self.assertIsNone(report["metrics"]["max_unapproved_main_reduction_pct"])

    def test_boolean_only_compression_does_not_bypass_fifteen_percent_gate(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{One}\n" + "Baseline evidence. " * 100 + "\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{One}\n" + "Candidate evidence. " * 20 + "\n\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "user_approved_compression": True,
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 2)
        self.assertEqual(report["status"], "approval_required")

    def test_controller_cannot_authorize_destructive_disposition(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Data}\nSubstantive data block.\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\appendix\n\\section{Data}\nSubstantive data block.\n\nExtra.\n",
        )
        ledger = self.complete_ledger(
            baseline, candidate, authorize_destructive=False
        )
        moved = next(item for item in ledger if item["disposition"] == "moved_appendix")
        moved["author_approval"] = {
            "approval_authority": "controller",
            "approved_by": "controller-test",
            "approved_at": "2026-08-03T12:00:00+08:00",
            "approval_source": "controller decision",
            "approved_scope": [f"moved_appendix:{moved['source_block_id']}"],
        }
        contract = self.contract(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "requires action-specific dated author approval",
            " ".join(report["findings"]["failures"]),
        )

    def test_pdf_floor_requires_main_page_metric(self) -> None:
        source = r"\section{Analysis} Complete text.\appendix Extra."
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        contract = self.contract(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "hard_main_text_floor": {"pdf_pages": 15},
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(report["status"], "metric_unavailable")
        self.assertIn("pdf_main_page_method", report["findings"]["warnings"][0])

    def test_escaped_currency_is_counted_while_inline_math_is_removed(self) -> None:
        text = r"Revenue is \$100 and cost is \$50. Model: $y=x$."
        self.assertEqual(MODULE.normalized_words(text), 8)
        markdown = "Revenue is $100 and cost is $50. Model: $y=x$."
        self.assertEqual(MODULE.normalized_words(markdown, "md"), 8)
        self.assertEqual(
            len(
                MODULE.markdown_formula_spans(
                    markdown, MODULE.markdown_code_ranges(markdown)
                )
            ),
            1,
        )
        self.assertEqual(MODULE.normalize_identifier("研究设计"), "研究设计")

    def test_balanced_tex_section_title_with_nested_formatting_passes(self) -> None:
        candidate = self.write(
            "candidate.tex",
            r"""
\section[Results]{\textbf{Results and \emph{Discussion}}}
The estimates, magnitude, and economic interpretation remain explicit.
\appendix
Supplementary detail.
""",
        )
        contract = self.contract(
            self.new_draft_payload(["Results and Discussion"])
        )
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        section = report["metrics"]["candidate_main"]["section_metrics"][0]
        self.assertEqual(section["title"], "Results and Discussion")

    def test_malformed_nested_tex_section_title_fails_closed(self) -> None:
        candidate = self.write(
            "candidate.tex",
            r"\section{\textbf{Results} Broken title.\appendix Extra.",
        )
        contract = self.contract(self.new_draft_payload(["Results"]))
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 3)
        self.assertEqual(report["status"], "metric_unavailable")
        self.assertIn("unbalanced title argument", report["findings"]["warnings"][0])

    def test_markdown_candidate_only_passes_and_hash_matches_preparer(self) -> None:
        candidate = self.write(
            "candidate.md",
            """<!-- # Appendix is only a comment -->
# Introduction {#sec-intro}
The paper defines the question, sample, and contribution.

# Results
The main estimate, magnitude, and interpretation are reported.

# Appendix
## Additional material
Supplementary detail.
""",
        )
        contract = self.contract(
            self.new_draft_payload(["Introduction", "Results"])
        )
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        prepared = PREPARE_MODULE.single_file_document(
            candidate.resolve(), strip_html_comments=True
        )
        self.assertEqual(report["inputs"]["candidate_format"], "md")
        self.assertEqual(
            report["inputs"]["candidate_expanded_sha256"],
            PREPARE_MODULE.sha256_text(prepared.text),
        )
        self.assertEqual(
            report["inputs"]["candidate_source_files"],
            [
                {
                    "path": str(candidate.resolve()),
                    "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
                }
            ],
        )

    def test_plain_text_candidate_only_passes(self) -> None:
        candidate = self.write(
            "candidate.txt",
            """1. Introduction
The paper defines the question and contribution.

2. Results
The main estimate and interpretation are reported.

Appendix
Supplementary detail.
""",
        )
        contract = self.contract(
            self.new_draft_payload(["1. Introduction", "2. Results"])
        )
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["inputs"]["candidate_format"], "txt")
        self.assertEqual(report["metrics"]["candidate_main"]["structure"]["sections"], 2)

    def test_markdown_reorder_with_complete_ledger_passes(self) -> None:
        baseline = self.write(
            "baseline.md",
            """# Data
The sample and measurement remain fully defined.

# Results
The estimate and interpretation remain fully reported.

# Appendix
Supplementary detail.
""",
        )
        candidate = self.write(
            "candidate.md",
            """# Results
The estimate and interpretation remain fully reported.

# Data
The sample and measurement remain fully defined.

# Appendix
Supplementary detail.
""",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "rewrite_mode": "reorder_existing_blocks",
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(report["inputs"]["baseline_format"], "md")

    def test_major_revision_without_baseline_is_metric_unavailable(self) -> None:
        candidate = self.write(
            "candidate.tex", r"\section{Results} Text.\appendix Extra."
        )
        contract = self.contract(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "rewrite_mode": "patch_existing",
            }
        )
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 3)
        self.assertIn("requires --baseline", report["findings"]["warnings"][0])

    def test_unknown_task_mode_is_metric_unavailable(self) -> None:
        candidate = self.write(
            "candidate.tex", r"\section{Results} Text.\appendix Extra."
        )
        contract = self.contract(
            {"task_mode": "major_revison", "mature_baseline": False}
        )
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 3)
        self.assertIn("task_mode must be one of", report["findings"]["warnings"][0])

    def test_unknown_maturity_is_metric_unavailable(self) -> None:
        candidate = self.write(
            "candidate.tex", r"\section{Results} Text.\appendix Extra."
        )
        contract = self.contract(
            {"task_mode": "full_draft", "mature_baseline": "unknown"}
        )
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 3)
        self.assertIn("explicit boolean", report["findings"]["warnings"][0])

    def test_missing_baseline_artifact_binding_fails(self) -> None:
        source = "\\section{Results}\nText.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        raw_contract = {
            "artifact_contract": {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "metric_status": "measured",
                "measurement_contract": {
                    "appendix_boundary": r"\appendix",
                    "source_word_method": "normalized_words",
                },
                "rewrite_mode": "patch_existing",
                "content_conservation_ledger": self.complete_ledger(
                    baseline, candidate
                ),
            }
        }
        contract = self.write("contract.json", json.dumps(raw_contract))
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "requires artifact_contract.baseline_artifact",
            " ".join(report["findings"]["failures"]),
        )

    def test_stale_baseline_artifact_hash_fails(self) -> None:
        source = "\\section{Results}\nText.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        payload = {
            "task_mode": "major_revision",
            "mature_baseline": True,
            "metric_status": "measured",
            "measurement_contract": {
                "appendix_boundary": r"\appendix",
                "source_word_method": "normalized_words",
            },
            "rewrite_mode": "patch_existing",
            "baseline_artifact": {
                "path": str(baseline.resolve()),
                "sha256": "0" * 64,
                "acceptance_status": "accepted",
                "accepted_by": "Alice Example",
            },
            "content_conservation_ledger": self.complete_ledger(
                baseline, candidate
            ),
        }
        contract = self.write(
            "contract.json", json.dumps({"artifact_contract": payload})
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn("SHA-256 mismatch", " ".join(report["findings"]["failures"]))

    def test_missing_rewrite_mode_fails_for_mature_revision(self) -> None:
        source = "\\section{Results}\nText.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        payload = {
            "task_mode": "restructure",
            "mature_baseline": True,
            "metric_status": "measured",
            "measurement_contract": {
                "appendix_boundary": r"\appendix",
                "source_word_method": "normalized_words",
            },
            "baseline_artifact": {
                "path": str(baseline.resolve()),
                "sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
                "acceptance_status": "accepted",
                "accepted_by": "Alice Example",
            },
            "content_conservation_ledger": self.complete_ledger(
                baseline, candidate
            ),
        }
        contract = self.write(
            "contract.json", json.dumps({"artifact_contract": payload})
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "requires rewrite_mode", " ".join(report["findings"]["failures"])
        )

    def test_restructure_without_two_pass_record_fails(self) -> None:
        source = "\\section{Results}\nText.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        payload = {
            "task_mode": "restructure",
            "mature_baseline": True,
            "metric_status": "measured",
            "measurement_contract": {
                "appendix_boundary": r"\appendix",
                "source_word_method": "normalized_words",
            },
            "rewrite_mode": "patch_existing",
            "baseline_artifact": {
                "path": str(baseline.resolve()),
                "sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
                "acceptance_status": "accepted",
                "accepted_by": "Alice Example",
            },
            "content_conservation_ledger": self.complete_ledger(
                baseline, candidate
            ),
        }
        contract = self.write(
            "contract.json", json.dumps({"artifact_contract": payload})
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "requires a hash-bound two_pass_restructure record",
            " ".join(report["findings"]["failures"]),
        )

    def test_moved_appendix_destination_must_match_source_content(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Data}\nOriginal core block.\n\\appendix\n"
            "\\section{Supplement}\nExtra detail.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Results}\nReplacement main block.\n\\appendix\n"
            "\\section{Data}\nDifferent appendix block.\n\n"
            "\\section{Supplement}\nExtra detail.\n",
        )
        baseline_inventory = self.inventories(baseline)
        candidate_inventory = self.inventories(candidate)
        source = next(
            item
            for item in baseline_inventory
            if item["region"] == "main_text"
        )
        destination = next(
            item
            for item in candidate_inventory
            if item["region"] == "appendix"
            and item["normalized_section"] == "data"
        )
        ledger = self.complete_ledger(baseline, candidate)
        source_entry = next(
            item for item in ledger if item["source_block_id"] == source["block_id"]
        )
        source_entry.update(
            {
                "destination": destination["block_id"],
                "disposition": "moved_appendix",
                "author_approval": {
                    "approval_authority": "author",
                    "approved_by": "Alice Example",
                    "approved_at": "2026-08-03T12:00:00+08:00",
                    "approval_source": "author confirmation fixture",
                    "approved_scope": [f"moved_appendix:{source['block_id']}"],
                },
            }
        )
        contract = self.contract(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "moved_appendix destination content hash does not match source",
            " ".join(report["findings"]["failures"]),
        )

    def test_extreme_local_block_compression_requires_independent_review(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Core}\n"
            + "Core evidence and interpretation. " * 100
            + "\n\\section{Stable}\n"
            + "Stable material. " * 2000
            + "\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Core}\nOne sentence.\n\\section{Stable}\n"
            + "Stable material. " * 2000
            + "\n\\appendix\nExtra.\n",
        )
        ledger = self.complete_ledger(baseline, candidate)
        revised = next(
            item
            for item in ledger
            if item["disposition"] == "revised"
            and item.get("main_text_sufficiency_review")
        )
        revised.pop("main_text_sufficiency_review")
        contract = self.contract(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertLess(report["metrics"]["cumulative_reduction_pct"], 0.15)
        self.assertIn(
            "local word reduction",
            " ".join(report["findings"]["failures"]),
        )

    def test_unlabeled_figure_deletion_requires_object_disposition_approval(self) -> None:
        baseline = self.write(
            "baseline.tex",
            r"""
\section{Results}
The main estimate is reported.

\begin{figure}
\caption{Main identifying variation}
\end{figure}
\appendix
Extra.
""",
        )
        candidate = self.write(
            "candidate.tex",
            r"""
\section{Results}
The main estimate is reported.
\appendix
Extra.
""",
        )
        contract = self.contract_with_ledger(
            {"task_mode": "major_revision", "mature_baseline": True},
            baseline,
            candidate,
            authorize_destructive=False,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        objects = report["conservation"]["baseline_object_inventory"]
        self.assertEqual([item["object_type"] for item in objects], ["figure"])
        object_id = objects[0]["block_id"]
        self.assertIn(
            f"ledger {object_id}: deleted requires action-specific dated author approval",
            report["findings"]["failures"],
        )

    def test_unlabeled_double_dollar_equation_deletion_is_detected(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Model}\nModel prose remains.\n\n$$\\beta>0$$\n"
            "\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Model}\nModel prose remains.\n\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {"task_mode": "major_revision", "mature_baseline": True},
            baseline,
            candidate,
            authorize_destructive=False,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        baseline_metrics = report["metrics"]["baseline_main"]["structure"]
        self.assertEqual(baseline_metrics["formulas"], 1)
        self.assertEqual(baseline_metrics["equations"], 1)
        objects = report["conservation"]["baseline_object_inventory"]
        equation = next(item for item in objects if item["object_type"] == "equation")
        self.assertIn(
            f"ledger {equation['block_id']}: deleted requires action-specific dated author approval",
            report["findings"]["failures"],
        )

    def test_accepted_multifile_baseline_detects_child_mutation(self) -> None:
        child = self.write(
            "parts/body.tex",
            "\\section{Results}\nAccepted child content.\n",
        )
        baseline = self.write(
            "baseline.tex", "\\input{parts/body}\n\\appendix\nExtra.\n"
        )
        candidate = self.write(
            "candidate.tex", "\\input{parts/body}\n\\appendix\nExtra.\n"
        )
        contract = self.contract_with_ledger(
            {"task_mode": "major_revision", "mature_baseline": True},
            baseline,
            candidate,
        )
        child.write_text(
            "\\section{Results}\nMutated child content.\n", encoding="utf-8"
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        findings = " ".join(report["findings"]["failures"])
        self.assertIn("expanded_sha256 does not match", findings)
        self.assertIn("source_files does not match", findings)

    def test_destructive_approval_requires_iso_timestamp_with_timezone(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Data}\nDelete this block.\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex", "\\section{Data}\n\\appendix\nExtra.\n"
        )
        ledger = self.complete_ledger(baseline, candidate)
        deleted = next(item for item in ledger if item["disposition"] == "deleted")
        deleted["author_approval"]["approved_at"] = "not-a-timestamp"
        contract = self.contract(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "requires action-specific dated author approval",
            " ".join(report["findings"]["failures"]),
        )

    def test_renamed_cannot_hide_content_replacement(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Old Name}\n" + "Substantive source meaning. " * 50
            + "\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{New Name}\nA different sentence.\n\\appendix\nExtra.\n",
        )
        ledger = self.complete_ledger(baseline, candidate)
        main_entry = next(
            item
            for item in ledger
            if item["source_block_id"]
            == next(
                source["block_id"]
                for source in self.inventories(baseline)
                if source["region"] == "main_text"
            )
        )
        main_entry["disposition"] = "renamed"
        main_entry["destination"] = next(
            item["block_id"]
            for item in self.inventories(candidate)
            if item["region"] == "main_text"
        )
        main_entry["authority"] = {
            "role": "controller",
            "by": "controller-test",
            "at": "2026-08-03T12:00:00+08:00",
        }
        contract = self.contract(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "renamed destination content hash does not match source",
            " ".join(report["findings"]["failures"]),
        )

    def test_inline_formula_change_requires_current_hash_independent_review(self) -> None:
        baseline = self.write(
            "baseline.tex",
            r"\section{Model} The model implies $\beta>0$.\appendix Extra.",
        )
        candidate = self.write(
            "candidate.tex",
            r"\section{Model} The model implies $\beta<0$.\appendix Extra.",
        )
        baseline_object = next(
            item
            for item in self.inventories(baseline)
            if item.get("object_type") == "inline_formula"
        )
        ledger = self.complete_ledger(baseline, candidate)
        object_entry = next(
            item
            for item in ledger
            if item["source_block_id"] == baseline_object["block_id"]
        )
        self.assertEqual(object_entry["disposition"], "revised")
        object_entry.pop("main_text_sufficiency_review")
        contract = self.contract(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "content_conservation_ledger": ledger,
            }
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "substantive object content changed",
            " ".join(report["findings"]["failures"]),
        )

    def test_authorized_single_labeled_figure_move_does_not_require_whole_section_move(self) -> None:
        long_prose = "Main result interpretation remains. " * 100
        figure = (
            "\\begin{figure}\n\\caption{Identifying variation}"
            "\\label{fig:variation}\n\\end{figure}\n"
        )
        baseline = self.write(
            "baseline.tex",
            "\\section{Results}\n"
            + long_prose
            + "\n\n"
            + figure
            + "\\appendix\n\\section{Extra}\nDetail.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Results}\n"
            + long_prose
            + "\n\\appendix\n\\section{Results}\n"
            + figure
            + "\\section{Extra}\nDetail.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "restructure",
                "mature_baseline": True,
                "allowed_appendix_moves": ["fig:variation"],
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(
            report["conservation"]["labels_moved_to_appendix"],
            ["fig:variation"],
        )

    def test_controller_cannot_raise_default_reduction_limit_without_authority(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Results}\n" + "Baseline evidence. " * 100
            + "\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Results}\n" + "Candidate evidence. " * 20
            + "\n\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "max_unapproved_main_reduction_pct": 0.90,
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(
            report["metrics"]["max_unapproved_main_reduction_pct"], 0.15
        )
        self.assertIn(
            "raising max_unapproved_main_reduction_pct",
            " ".join(report["findings"]["failures"]),
        )

    def test_authoritative_user_shorter_target_overrides_default_reduction_gate(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Results}\n" + "Baseline evidence. " * 100
            + "\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Results}\n" + "Candidate evidence. " * 20
            + "\n\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "major_revision",
                "mature_baseline": True,
                "target_basis": "user",
                "target_main_source_word_range": [20, 100],
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIsNone(report["metrics"]["max_unapproved_main_reduction_pct"])

    def test_candidate_only_section_authority_inherits_or_narrows(self) -> None:
        candidate = self.write(
            "candidate.tex",
            "\\section{Results}\nA bounded result remains.\n\\appendix\nExtra.\n",
        )
        cases = {
            "inherit": {},
            "same": {
                "allowed_appendix_moves": ["PROOFS", "sec detail"],
                "rewrite_mode": "full_redraft",
            },
            "narrow": {
                "allowed_appendix_moves": [" PROOFS "],
                "rewrite_mode": "reorder_existing_blocks",
            },
        }
        for name, override in cases.items():
            with self.subTest(case=name):
                payload = self.new_draft_payload(
                    ["Results"],
                    allowed_appendix_moves=["Proofs", "sec:Detail"],
                    rewrite_mode="full_redraft",
                )
                payload["section_cards"][0].update(override)
                contract = self.contract(payload)
                completed, report = self.run_audit(None, candidate, contract)
                self.assertEqual(
                    completed.returncode, 0, completed.stdout + completed.stderr
                )
                check = report["conservation"][
                    "candidate_only_full_draft_contract"
                ]["section_authority_checks"][0]
                self.assertEqual(check["status"], "pass")
                self.assertFalse(check["author_approval_inferred"])
                if name == "inherit":
                    self.assertEqual(
                        check["effective_allowed_appendix_moves"],
                        ["proofs", "sec detail"],
                    )
                    self.assertEqual(check["effective_rewrite_mode"], "full_redraft")
                    self.assertEqual(
                        check["allowed_appendix_moves_source"], "inherited"
                    )
                    self.assertEqual(check["rewrite_mode_source"], "inherited")
                elif name == "same":
                    self.assertEqual(
                        check["effective_allowed_appendix_moves"],
                        ["proofs", "sec detail"],
                    )
                    self.assertEqual(check["effective_rewrite_mode"], "full_redraft")
                    self.assertTrue(
                        check["allowed_appendix_moves_override_accepted"]
                    )
                    self.assertTrue(check["rewrite_mode_override_accepted"])
                else:
                    self.assertEqual(
                        check["effective_allowed_appendix_moves"], ["proofs"]
                    )
                    self.assertEqual(
                        check["effective_rewrite_mode"],
                        "reorder_existing_blocks",
                    )

    def test_candidate_only_section_authority_rejects_invalid_or_broader_overrides(self) -> None:
        candidate = self.write(
            "candidate.tex",
            "\\section{Results}\nA bounded result remains.\n\\appendix\nExtra.\n",
        )
        cases = {
            "invalid_format": (
                ["Proofs"],
                "full_redraft",
                {"allowed_appendix_moves": "Proofs"},
                "must be a list",
            ),
            "normalized_duplicate": (
                ["Proofs"],
                "full_redraft",
                {"allowed_appendix_moves": ["Proofs", " proofs "]},
                "duplicate normalized entry",
            ),
            "extra_move": (
                ["Proofs"],
                "full_redraft",
                {"allowed_appendix_moves": ["Data"]},
                "exceeds artifact-wide authority",
            ),
            "move_without_parent": (
                None,
                "full_redraft",
                {"allowed_appendix_moves": ["Proofs"]},
                "exceeds artifact-wide authority",
            ),
            "broader_rewrite": (
                ["Proofs"],
                "patch_existing",
                {"rewrite_mode": "reorder_existing_blocks"},
                "exceeds artifact-wide rewrite_mode",
            ),
            "invalid_rewrite": (
                ["Proofs"],
                "full_redraft",
                {"rewrite_mode": "clean_slate"},
                "rewrite_mode must be patch_existing",
            ),
            "rewrite_without_parent": (
                ["Proofs"],
                None,
                {"rewrite_mode": "patch_existing"},
                "cannot be supplied without a valid artifact_contract.rewrite_mode",
            ),
        }
        for name, (top_moves, top_rewrite, card_override, expected) in cases.items():
            with self.subTest(case=name):
                payload = self.new_draft_payload(["Results"])
                if top_moves is not None:
                    payload["allowed_appendix_moves"] = top_moves
                if top_rewrite is not None:
                    payload["rewrite_mode"] = top_rewrite
                payload["section_cards"][0].update(card_override)
                contract = self.contract(payload)
                completed, report = self.run_audit(None, candidate, contract)
                self.assertEqual(completed.returncode, 1)
                self.assertIn(expected, " ".join(report["findings"]["failures"]))

    def test_top_level_and_card_appendix_moves_reject_normalized_duplicates(self) -> None:
        candidate = self.write(
            "candidate.tex",
            "\\section{Results}\nA bounded result remains.\n\\appendix\nExtra.\n",
        )
        payload = self.new_draft_payload(
            ["Results"],
            allowed_appendix_moves=["sec:Proofs", " sec-proofs "],
        )
        contract = self.contract(payload)
        completed, report = self.run_audit(None, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "artifact_contract.allowed_appendix_moves contains duplicate normalized entry",
            " ".join(report["findings"]["failures"]),
        )

    def test_mature_section_authority_can_only_narrow_top_level_bounds(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Analysis}\nThe full interpretation remains.\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Analysis}\nThe full interpretation remains.\n\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "local_edit",
                "mature_baseline": True,
                "rewrite_mode": "reorder_existing_blocks",
                "allowed_appendix_moves": ["Proofs", "sec:Detail"],
            },
            baseline,
            candidate,
        )
        wrapped = json.loads(contract.read_text(encoding="utf-8"))
        card = wrapped["artifact_contract"]["section_cards"][0]
        card["allowed_appendix_moves"] = [" proofs "]
        card["rewrite_mode"] = "patch_existing"
        self.write_json("contract.json", wrapped)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        check = report["conservation"]["mature_section_budget"][
            "section_authority_checks"
        ][0]
        self.assertEqual(check["status"], "pass")
        self.assertEqual(check["effective_allowed_appendix_moves"], ["proofs"])
        self.assertEqual(check["effective_rewrite_mode"], "patch_existing")
        self.assertFalse(check["author_approval_inferred"])

        wrapped["artifact_contract"]["rewrite_mode"] = "patch_existing"
        card["rewrite_mode"] = "full_redraft"
        self.write_json("contract.json", wrapped)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "exceeds artifact-wide rewrite_mode patch_existing",
            " ".join(report["findings"]["failures"]),
        )

    def test_card_appendix_move_declaration_never_replaces_author_approval(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Theory}\nThe economic mechanism remains in the main text.\n"
            "\\section{Proofs}\nThe formal proof is recorded here.\n"
            "\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Theory}\nThe economic mechanism remains in the main text.\n"
            "\\appendix\n\\section{Proofs}\nThe formal proof is recorded here.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "local_edit",
                "mature_baseline": True,
                "allowed_appendix_moves": ["Proofs"],
            },
            baseline,
            candidate,
            authorize_destructive=False,
        )
        wrapped = json.loads(contract.read_text(encoding="utf-8"))
        proof_card = next(
            card
            for card in wrapped["artifact_contract"]["section_cards"]
            if card["baseline_section_name"] == "Proofs"
        )
        proof_card["allowed_appendix_moves"] = [" proofs "]
        self.write_json("contract.json", wrapped)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        findings = " ".join(report["findings"]["failures"])
        self.assertIn(
            "moved_appendix requires action-specific dated author approval",
            findings,
        )
        checks = report["conservation"]["mature_section_budget"][
            "section_authority_checks"
        ]
        self.assertFalse(any(check["author_approval_inferred"] for check in checks))

    def test_card_empty_allowed_moves_blocks_authorized_appendix_move(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Keep}\nCore interpretation remains.\n"
            "\\section{Methods}\\label{sec:methods}\nMethod details.\n"
            "\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Keep}\nCore interpretation remains.\n"
            "\\appendix\n\\section{Methods}\\label{sec:methods}\nMethod details.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "local_edit",
                "mature_baseline": True,
                "allowed_appendix_moves": ["sec:methods"],
            },
            baseline,
            candidate,
        )
        wrapped = json.loads(contract.read_text(encoding="utf-8"))
        methods_card = next(
            card
            for card in wrapped["artifact_contract"]["section_cards"]
            if card["baseline_section_name"] == "Methods"
        )
        methods_card["allowed_appendix_moves"] = []
        methods_card["must_remain_main"] = [
            {"type": "section", "value": "Keep"}
        ]
        self.write_json("contract.json", wrapped)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "outside effective allowed_appendix_moves",
            " ".join(report["findings"]["failures"]),
        )
        moved_records = [
            item
            for item in report["conservation"]["ledger_validation"]
            if item["disposition"] == "moved_appendix"
        ]
        self.assertTrue(moved_records)
        self.assertTrue(all(item["status"] == "pass" for item in moved_records))
        methods_check = next(
            item
            for item in report["conservation"]["mature_section_budget"][
                "section_authority_checks"
            ]
            if item["card_id"] == methods_card["card_id"]
        )
        self.assertEqual(methods_check["effective_allowed_appendix_moves"], [])
        self.assertFalse(methods_check["author_approval_inferred"])

    def test_mature_card_missing_main_text_label_fails(self) -> None:
        source = "\\section{Results}\nThe result remains.\n\\appendix\nExtra.\n"
        baseline = self.write("baseline.tex", source)
        candidate = self.write("candidate.tex", source)
        contract = self.contract_with_ledger(
            {"task_mode": "local_edit", "mature_baseline": True},
            baseline,
            candidate,
        )
        wrapped = json.loads(contract.read_text(encoding="utf-8"))
        wrapped["artifact_contract"]["section_cards"][0][
            "must_remain_main"
        ] = [{"type": "label", "value": "sec:missing"}]
        self.write_json("contract.json", wrapped)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertIn(
            "unverifiable must_remain_main reference: sec:missing",
            " ".join(report["findings"]["failures"]),
        )

    def test_patch_existing_rejects_whole_section_order_inversion(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Data}\nSample construction.\n"
            "\\section{Results}\nMain estimate.\n\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Results}\nMain estimate.\n"
            "\\section{Data}\nSample construction.\n\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "local_edit",
                "mature_baseline": True,
                "rewrite_mode": "patch_existing",
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        order_check = report["conservation"]["patch_order_conservation"]
        self.assertEqual(order_check["status"], "fail")
        self.assertTrue(order_check["inversions"])
        self.assertIn(
            "artifact-wide patch_existing relative-order inversion",
            " ".join(report["findings"]["failures"]),
        )

    def test_patch_existing_rejects_same_section_paragraph_inversion(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Analysis}\nFirst explanation.\n\nSecond explanation.\n"
            "\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Analysis}\nSecond explanation.\n\nFirst explanation.\n"
            "\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "local_edit",
                "mature_baseline": True,
                "rewrite_mode": "patch_existing",
            },
            baseline,
            candidate,
        )
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(
            report["conservation"]["patch_order_conservation"]["status"],
            "fail",
        )

    def test_card_level_patch_rejects_internal_inversion_under_top_reorder(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Analysis}\nFirst explanation.\n\nSecond explanation.\n"
            "\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Analysis}\nSecond explanation.\n\nFirst explanation.\n"
            "\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "local_edit",
                "mature_baseline": True,
                "rewrite_mode": "reorder_existing_blocks",
            },
            baseline,
            candidate,
        )
        wrapped = json.loads(contract.read_text(encoding="utf-8"))
        wrapped["artifact_contract"]["section_cards"][0][
            "rewrite_mode"
        ] = "patch_existing"
        self.write_json("contract.json", wrapped)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 1)
        self.assertEqual(
            report["conservation"]["patch_order_conservation"]["status"],
            "not_applicable",
        )
        card_check = report["conservation"]["mature_section_budget"]["checks"][0]
        self.assertEqual(card_check["patch_order_conservation"]["status"], "fail")
        self.assertIn(
            "section card card-1 patch_existing relative-order inversion",
            " ".join(report["findings"]["failures"]),
        )

    def test_patch_existing_allows_text_patch_and_ignores_new_unmapped_block(self) -> None:
        baseline = self.write(
            "baseline.tex",
            "\\section{Analysis}\nOriginal explanation.\n\nSecond preserved point.\n"
            "\\appendix\nExtra.\n",
        )
        candidate = self.write(
            "candidate.tex",
            "\\section{Analysis}\nRevised explanation.\n\n"
            "Newly inserted bridge.\n\nSecond preserved point.\n"
            "\\appendix\nExtra.\n",
        )
        contract = self.contract_with_ledger(
            {
                "task_mode": "local_edit",
                "mature_baseline": True,
                "rewrite_mode": "patch_existing",
                "content_obligations": [
                    {"intent_id": "I-keep", "content": "Keep the interpretation."}
                ],
            },
            baseline,
            candidate,
        )
        wrapped = json.loads(contract.read_text(encoding="utf-8"))
        wrapped["artifact_contract"]["section_cards"][0][
            "must_remain_main"
        ] = [{"type": "intent", "value": "I-keep"}]
        self.write_json("contract.json", wrapped)
        completed, report = self.run_audit(baseline, candidate, contract)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        order_check = report["conservation"]["patch_order_conservation"]
        self.assertEqual(order_check["status"], "pass")
        self.assertTrue(order_check["new_unmapped_blocks_ignored"])
        reference_check = report["conservation"]["mature_section_budget"][
            "checks"
        ][0]["must_remain_reference_checks"][0]
        self.assertEqual(reference_check["matched_kind"], "obligation_or_intent")


if __name__ == "__main__":
    unittest.main()
