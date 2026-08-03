#!/usr/bin/env python3
"""Synthetic regression tests for prepare_manuscript_qa.py."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("prepare_manuscript_qa.py")
SPEC = importlib.util.spec_from_file_location("prepare_manuscript_qa", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PrepareManuscriptQATests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.intent = self.write_json(
            "intent.json",
            {
                "author_intent_contract": {
                    "schema_version": "1.0",
                    "intent_contract_id": "intent-test",
                    "intent_revision_id": "r1",
                    "intent_status": "frozen-current",
                    "gate_status": "ready",
                    "unresolved_material_questions": [],
                    "approval_record": {
                        "confirmed_by": "author-test",
                        "confirmed_at": "2026-08-03T00:00:00Z",
                        "confirmed_scope": "complete_author_intent_contract",
                        "confirmation_source": "author-message-test",
                        "freeze_authorized_by": "author-test",
                        "freeze_authorized_at": "2026-08-03T00:00:00Z",
                    },
                    "reader_takeaway": "The paper reports a bounded result.",
                    "propositions": [
                        {
                            "intent_id": "I1",
                            "must_express": "bounded result",
                            "claim_type": "associational",
                            "evidence_anchors": ["table:main"],
                        }
                    ],
                    "must_not_claim": ["causality without design"],
                    "definition_registry": [
                        {
                            "definition_id": "D1",
                            "term": "Exposure",
                            "definition": "The observed treatment measure.",
                        },
                        {
                            "definition_id": "D2",
                            "term": "Sample",
                            "definition": "The admitted observations.",
                        },
                    ],
                    "extra_future_field": {"kept": True},
                }
            },
        )
        self.qa = self.write_json(
            "qa.json",
            {
                "qa_contract": {
                    "schema_version": "1.0",
                    "review_scope": "full_manuscript",
                    "qa_mode": "exhaustive",
                    "task_classification": {
                        "task_stage": "full_draft",
                        "qa_mode": "exhaustive",
                        "basis": "The complete manuscript requires semantic acceptance.",
                        "classified_by": "controller-test",
                        "classified_at": "2026-08-03T00:00:00Z",
                    },
                    "minimum_high_risk_independent_reviews": 2,
                    "high_risk_markers": [
                        {"text": "author marker", "category": "contract_marked", "intent_id": "I1"}
                    ],
                    "content_obligations": [
                        {
                            "obligation_id": "Q1",
                            "intent_id": "I1",
                            "obligation_type": "must_express",
                            "content": "bounded result",
                        }
                    ],
                    "definition_registry": [
                        {"definition_id": "D2", "term": "Sample", "definition": "The admitted observations."},
                    ],
                    "unknown_extension": [1, 2, 3],
                }
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, relative: str, content: str) -> Path:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_json(self, relative: str, payload: object) -> Path:
        return self.write(relative, json.dumps(payload, ensure_ascii=False))

    def run_prepare(
        self,
        manuscript: Path,
        output_name: str = "out",
        *extra: str,
    ) -> tuple[subprocess.CompletedProcess[str], dict | None, Path]:
        output = self.root / output_name
        extra_args = list(extra)
        omit_artifact = "--test-omit-artifact-contract" in extra_args
        omit_manuscript_path = "--test-omit-manuscript-path" in extra_args
        preserve_manuscript_path = "--test-preserve-manuscript-path" in extra_args
        omit_high_risk_minimum = (
            "--test-omit-high-risk-minimum" in extra_args
        )
        extra_args = [
            value
            for value in extra_args
            if value
            not in {
                "--test-omit-artifact-contract",
                "--test-omit-manuscript-path",
                "--test-preserve-manuscript-path",
                "--test-omit-high-risk-minimum",
            }
        ]
        qa_payload = json.loads(self.qa.read_text(encoding="utf-8"))
        qa_contract = qa_payload.get("qa_contract")
        if not isinstance(qa_contract, dict):
            paper_state = qa_payload.get("paper_state")
            qa_contract = (
                paper_state.get("qa_contract")
                if isinstance(paper_state, dict)
                else None
            )
        if isinstance(qa_contract, dict):
            if omit_high_risk_minimum:
                qa_contract.pop(
                    "minimum_high_risk_independent_reviews", None
                )
            else:
                qa_contract.setdefault(
                    "minimum_high_risk_independent_reviews", 2
                )
            if omit_manuscript_path:
                qa_contract.pop("manuscript_path", None)
            elif not preserve_manuscript_path:
                qa_contract["manuscript_path"] = str(manuscript.resolve())
            self.qa.write_text(
                json.dumps(qa_payload, ensure_ascii=False), encoding="utf-8"
            )
        if not omit_artifact and "--artifact-contract" not in extra_args:
            qa_payload = json.loads(self.qa.read_text(encoding="utf-8"))
            qa_contract = qa_payload.get("qa_contract")
            if not isinstance(qa_contract, dict):
                paper_state = qa_payload.get("paper_state")
                qa_contract = (
                    paper_state.get("qa_contract")
                    if isinstance(paper_state, dict)
                    else None
                )
            classification = (
                qa_contract.get("task_classification")
                if isinstance(qa_contract, dict)
                else None
            )
            stage = (
                str(classification.get("task_stage", "")).strip().lower()
                if isinstance(classification, dict)
                else ""
            )
            if stage in MODULE.ARTIFACT_CONTRACT_REQUIRED_STAGES:
                artifact_mode = (
                    classification.get("artifact_task_mode")
                    if stage == "final_audit" and isinstance(classification, dict)
                    else MODULE.TASK_STAGE_ARTIFACT_MODES.get(stage)
                )
                if not isinstance(artifact_mode, str) or not artifact_mode.strip():
                    artifact_mode = "full_draft"
                    if isinstance(classification, dict):
                        classification["artifact_task_mode"] = artifact_mode
                        self.qa.write_text(
                            json.dumps(qa_payload, ensure_ascii=False), encoding="utf-8"
                        )
                artifact = self.write_json(
                    "_auto-artifact-contract.json",
                    {
                        "artifact_contract": {
                            "schema_version": "1.0",
                            "task_mode": artifact_mode,
                            "mature_baseline": artifact_mode != "full_draft",
                            "metric_status": "measured",
                            "measurement_contract": {
                                "appendix_boundary": r"\appendix",
                                "source_word_method": "normalized_words",
                            },
                        }
                    },
                )
                extra_args.extend(("--artifact-contract", str(artifact)))
        command = [
            sys.executable,
            str(SCRIPT),
            "--manuscript",
            str(manuscript),
            "--project-root",
            str(self.root),
            "--author-intent-contract",
            str(self.intent),
            "--qa-contract",
            str(self.qa),
            "--output-dir",
            str(output),
            *extra_args,
        ]
        completed = subprocess.run(command, text=True, capture_output=True, check=False)
        manifest_path = output / "qa_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
        return completed, manifest, output

    def assert_prepared(self, completed: subprocess.CompletedProcess[str], manifest: dict | None) -> dict:
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertIsInstance(manifest, dict)
        assert manifest is not None
        self.assertEqual(manifest["status"], "prepared")
        return manifest

    def test_tex_nested_include_and_visible_unit_coverage(self) -> None:
        self.write(
            "parts/results.tex",
            r"""
\section{Results}
The estimate is 3.14 percent, e.g. in the preferred sample. 中文结果显著。第二句保持限定。
\begin{table}
Cell A & Cell B \\
\caption{Main estimate is 2 percent.}
\begin{tablenotes}\item Notes: Standard errors are clustered.\end{tablenotes}
\end{table}
A sentence has a footnote.\footnote{Footnote evidence remains visible.}
""",
        )
        manuscript = self.write(
            "paper.tex",
            r"""
\documentclass{article}
\begin{document}
% \input{missing} and \appendix are comments
\input{parts/results}
\appendix
\section{Supplement}
Appendix prose remains auditable.
\end{document}
""",
        )
        completed, manifest, output = self.run_prepare(manuscript)
        manifest = self.assert_prepared(completed, manifest)
        types = {unit["type"] for unit in manifest["units"]}
        self.assertTrue(
            {"section", "paragraph", "sentence", "caption", "note", "footnote", "appendix_prose"}.issubset(types),
            types,
        )
        self.assertEqual(len(manifest["source_files"]), 2)
        self.assertTrue(any(unit["appendix"] and unit["type"] == "sentence" for unit in manifest["units"]))
        joined = " ".join(unit["text"] for unit in manifest["units"] if unit["type"] == "sentence")
        self.assertNotIn("missing", joined)
        self.assertIn("Cell A", joined)
        self.assertTrue((output / "qa_manifest.sha256").is_file())
        packet_roles = {packet["role"] for packet in manifest["packets"]}
        self.assertIn("author_intent_coverage", packet_roles)
        self.assertIn("evidence_claim_strength", packet_roles)
        assignment_template = json.loads(
            (output / "qa_assignment_registry.template.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            assignment_template["schema_id"], "qa-assignment-registry/1.0"
        )
        semantic_assignments = [
            item
            for item in assignment_template["assignments"]
            if item["assignment_kind"] == "semantic_packet"
        ]
        self.assertEqual(
            {item["packet_id"] for item in semantic_assignments},
            {item["packet_id"] for item in manifest["packets"]},
        )
        self.assertTrue(
            all(
                item["native_agent_id"] is None
                for item in assignment_template["assignments"]
            )
        )
        fifth = [
            item
            for item in assignment_template["assignments"]
            if item["assignment_kind"] == "main_text_sufficiency"
        ]
        self.assertEqual(len(fifth), 1)
        self.assertEqual(fifth[0]["target_id"], "main-text-sufficiency")
        self.assertEqual(
            fifth[0]["target_sha256"], manifest["expanded_manuscript_sha256"]
        )
        self.assertTrue(
            all(
                item["target_id"] == item["packet_id"]
                and item["target_sha256"] == item["packet_sha256"]
                for item in semantic_assignments
            )
        )

    def test_crlf_root_and_include_use_raw_file_hashes(self) -> None:
        child = self.root / "parts" / "crlf-child.tex"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.write_bytes(b"Child result remains visible. % hidden\r\n")
        manuscript = self.root / "crlf-root.tex"
        manuscript.write_bytes(b"\\input{parts/crlf-child}\r\nRoot result remains visible.\r\n")
        completed, manifest, _ = self.run_prepare(manuscript, "out_crlf")
        manifest = self.assert_prepared(completed, manifest)
        records = {record["path"]: record for record in manifest["source_files"]}
        self.assertEqual(
            records["crlf-root.tex"]["sha256"],
            hashlib.sha256(manuscript.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            records["parts/crlf-child.tex"]["sha256"],
            hashlib.sha256(child.read_bytes()).hexdigest(),
        )
        self.assertEqual(records["crlf-root.tex"]["bytes"], len(manuscript.read_bytes()))
        self.assertEqual(records["parts/crlf-child.tex"]["bytes"], len(child.read_bytes()))

    def test_tex_bare_include_is_expanded_and_unsupported_include_fails_closed(self) -> None:
        self.write("parts/bare.tex", "Bare include content remains visible.\n")
        manuscript = self.write("bare.tex", "\\input parts/bare\n")
        completed, manifest, _ = self.run_prepare(manuscript, "out_bare")
        manifest = self.assert_prepared(completed, manifest)
        self.assertEqual(
            {record["path"] for record in manifest["source_files"]},
            {"bare.tex", "parts/bare.tex"},
        )
        joined = " ".join(unit["text"] for unit in manifest["units"])
        self.assertIn("Bare include content remains visible.", joined)
        self.assertNotIn("parts/bare", joined)

        unsupported = self.write("unsupported.tex", "\\subfile{parts/bare}\n")
        failed, failed_manifest, _ = self.run_prepare(
            unsupported, "out_unsupported"
        )
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("unsupported LaTeX include command", failed.stderr)

        dynamic = self.write("dynamic.tex", "\\input\\jobname\n")
        failed, failed_manifest, _ = self.run_prepare(dynamic, "out_dynamic")
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("unsupported dynamic or malformed include target", failed.stderr)

    def test_tex_citation_and_reference_anchors_remain_exact(self) -> None:
        manuscript = self.write(
            "anchors.tex",
            r"Evidence follows \citep[see][p. 3]{smith2020,jones2021} and Eq. \eqref{eq:main}.",
        )
        completed, manifest, output = self.run_prepare(manuscript, "out_anchors")
        manifest = self.assert_prepared(completed, manifest)
        sentence = next(unit for unit in manifest["units"] if unit["type"] == "sentence")
        self.assertIn("[CITATION:smith2020,jones2021; options:see | p. 3]", sentence["text"])
        self.assertIn("[REF:eq:main]", sentence["text"])
        self.assertEqual(sentence["citation_keys"], ["smith2020", "jones2021"])
        self.assertEqual(sentence["reference_labels"], ["eq:main"])
        packet = next(
            json.loads((output / record["path"]).read_text(encoding="utf-8"))
            for record in manifest["packets"]
            if sentence["unit_id"] in record["unit_ids"]
        )
        packet_unit = next(item for item in packet["units"] if item["unit_id"] == sentence["unit_id"])
        self.assertEqual(packet_unit["citation_keys"], ["smith2020", "jones2021"])
        self.assertEqual(packet_unit["reference_labels"], ["eq:main"])

    def test_tex_footnote_dependencies_and_declared_labels_are_preserved(self) -> None:
        manuscript = self.write(
            "footnote-links.tex",
            r"""
\section{Results}
The estimate identifies a causal effect only under the stated assumption.\footnote{The exclusion restriction remains a maintained assumption.}
The estimating equation follows.
\begin{equation}\label{eq:main}
y_i = \beta x_i.
\end{equation}
Equation \eqref{eq:main} reports the estimand.
""",
        )
        completed, manifest, output = self.run_prepare(
            manuscript, "out_footnote_links"
        )
        manifest = self.assert_prepared(completed, manifest)
        body_sentence = next(
            unit
            for unit in manifest["units"]
            if unit["type"] == "sentence" and "causal effect" in unit["text"]
        )
        footnote = next(
            unit for unit in manifest["units"] if unit["type"] == "footnote"
        )
        footnote_sentence = next(
            unit
            for unit in manifest["units"]
            if unit["type"] == "sentence"
            and unit["parent_id"] == footnote["unit_id"]
        )
        self.assertEqual(len(body_sentence["footnote_reference_ids"]), 1)
        self.assertEqual(
            body_sentence["footnote_target_unit_ids"], [footnote["unit_id"]]
        )
        self.assertIn(footnote["unit_id"], body_sentence["dependency_unit_ids"])
        self.assertIn(body_sentence["unit_id"], footnote["referenced_by_unit_ids"])
        self.assertIn(
            body_sentence["unit_id"], footnote_sentence["dependency_unit_ids"]
        )
        self.assertIn("footnote_dependency", body_sentence["risk_flags"])
        self.assertTrue(body_sentence["high_risk"])

        declared = {
            label
            for unit in manifest["units"]
            for label in unit.get("declared_labels", [])
        }
        referenced = {
            label
            for unit in manifest["units"]
            for label in unit.get("reference_labels", [])
        }
        self.assertIn("eq:main", declared)
        self.assertIn("eq:main", referenced)

        packet_units = []
        for record in manifest["packets"]:
            packet = json.loads(
                (output / record["path"]).read_text(encoding="utf-8")
            )
            packet_units.extend(packet["units"])
        packet_body = next(
            unit
            for unit in packet_units
            if unit["unit_id"] == body_sentence["unit_id"]
        )
        self.assertEqual(
            packet_body["footnote_target_unit_ids"], [footnote["unit_id"]]
        )

    def test_tex_command_prefixes_do_not_misparse_and_detached_footnotes_fail_closed(self) -> None:
        section_mark = self.write(
            "section-mark.tex",
            r"\section{Results}\sectionmark{Short Results}Visible result.",
        )
        completed, manifest, _ = self.run_prepare(section_mark, "out_section_mark")
        manifest = self.assert_prepared(completed, manifest)
        self.assertEqual(
            [unit["text"] for unit in manifest["units"] if unit["type"] == "section"],
            ["Results"],
        )

        detached = self.write(
            "detached-footnote.tex",
            r"A qualified claim\footnotemark.\footnotetext{The qualification.}",
        )
        failed, failed_manifest, _ = self.run_prepare(
            detached, "out_detached_footnote"
        )
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("detached footnotemark/footnotetext linkage", failed.stderr)

    def test_nested_heading_caption_and_maketitle_footnotes_keep_exact_parents(self) -> None:
        manuscript = self.write(
            "nested-footnotes.tex",
            r"""
\documentclass{article}
\title{A Causal Title\thanks{The title claim is only associational.}}
\subtitle{A bounded subtitle claim}
\author{Alice\thanks{Funding support is acknowledged.}}
\affil{Department of Economics}
\date{August 2026}
\begin{document}
\maketitle
\section{Results\footnote{The section covers the admitted sample only.}}
Nearby ordinary prose must not acquire either qualifier.
\begin{figure}
\caption{The trend establishes causality.\footnote{Only under the maintained design assumption.}}
\end{figure}
\end{document}
""",
        )
        completed, manifest, _ = self.run_prepare(
            manuscript, "out_nested_footnotes"
        )
        manifest = self.assert_prepared(completed, manifest)
        title = next(
            unit
            for unit in manifest["units"]
            if unit["type"] == "section" and unit.get("level") == "title"
        )
        results_heading = next(
            unit
            for unit in manifest["units"]
            if unit["type"] == "section" and unit.get("level") == "section"
        )
        subtitle = next(
            unit
            for unit in manifest["units"]
            if unit["type"] == "section" and unit.get("level") == "subtitle"
        )
        affiliation = next(
            unit
            for unit in manifest["units"]
            if unit["type"] == "note" and "Department of Economics" in unit["text"]
        )
        caption_sentence = next(
            unit
            for unit in manifest["units"]
            if unit["type"] == "sentence" and "trend establishes" in unit["text"]
        )
        ordinary = next(
            unit
            for unit in manifest["units"]
            if unit["type"] == "sentence" and "Nearby ordinary" in unit["text"]
        )
        self.assertEqual(len(title["footnote_target_unit_ids"]), 1)
        self.assertEqual(len(results_heading["footnote_target_unit_ids"]), 1)
        self.assertEqual(len(caption_sentence["footnote_target_unit_ids"]), 1)
        self.assertEqual(ordinary["footnote_target_unit_ids"], [])
        self.assertEqual(ordinary["footnote_reference_ids"], [])
        self.assertTrue(subtitle["requires_intent_mapping"])
        self.assertTrue(affiliation["reader_visible"])
        for parent in (title, results_heading, caption_sentence):
            target_id = parent["footnote_target_unit_ids"][0]
            target = next(
                unit for unit in manifest["units"] if unit["unit_id"] == target_id
            )
            self.assertIn(parent["unit_id"], target["referenced_by_unit_ids"])

    def test_description_item_label_is_reader_visible(self) -> None:
        manuscript = self.write(
            "description.tex",
            r"\begin{description}\item[Exclusion restriction] The instrument affects the outcome only through treatment.\end{description}",
        )
        completed, manifest, _ = self.run_prepare(manuscript, "out_description")
        manifest = self.assert_prepared(completed, manifest)
        visible = " ".join(
            unit["text"] for unit in manifest["units"] if unit["review_target"]
        )
        self.assertIn("Exclusion restriction", visible)
        self.assertIn("instrument affects the outcome", visible)

    def test_unknown_reader_visible_tex_macro_fails_closed(self) -> None:
        manuscript = self.write(
            "unknown-macro.tex",
            r"""
\newcommand{\ATE}{average treatment effect}
\begin{document}
We estimate the \ATE. Formatting such as \emph{this phrase} is supported.
\end{document}
""",
        )
        failed, failed_manifest, _ = self.run_prepare(
            manuscript, "out_unknown_macro"
        )
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("unsupported TeX control sequence", failed.stderr)
        self.assertIn("\\ATE", failed.stderr)

    def test_escaped_currency_dollars_survive_alongside_inline_math(self) -> None:
        manuscript = self.write(
            "currency.tex",
            r"Revenue is \$100 and cost is \$50, while $x_i=1$ defines exposure.",
        )
        completed, manifest, _ = self.run_prepare(manuscript, "out_currency")
        manifest = self.assert_prepared(completed, manifest)
        visible = " ".join(
            unit["text"] for unit in manifest["units"] if unit["review_target"]
        )
        self.assertIn("$100", visible)
        self.assertIn("cost is $50", visible)
        self.assertIn("[FORMULA:formula_", visible)

    def test_formula_registry_preserves_signs_labels_hashes_and_packet_context(self) -> None:
        manuscript = self.write(
            "formula-semantics.tex",
            r"""
We predict $\beta>0$, while the rejected alternative is $\beta<0$.
\begin{equation}\label{eq:direction}
\Delta y_i = -\gamma x_i.
\end{equation}
""",
        )
        completed, manifest, output = self.run_prepare(
            manuscript, "out_formula_semantics"
        )
        manifest = self.assert_prepared(completed, manifest)
        formulas = manifest["formulas"]
        self.assertEqual(len(formulas), 3)
        self.assertEqual(len({item["formula_id"] for item in formulas}), 3)
        normalized = {item["normalized_math"] for item in formulas}
        self.assertIn(r"$\beta>0$", normalized)
        self.assertIn(r"$\beta<0$", normalized)
        self.assertTrue(any("-\\gamma" in item for item in normalized))
        self.assertTrue(
            all(
                item["raw_sha256"]
                == hashlib.sha256(item["raw"].encode("utf-8")).hexdigest()
                for item in formulas
            )
        )
        equation = next(
            item for item in formulas if "eq:direction" in item["declared_labels"]
        )
        self.assertTrue(equation["source_spans"])
        self.assertEqual(
            manifest["formula_registry_sha256"], MODULE.canonical_hash(formulas)
        )
        formula_sentence = next(
            unit
            for unit in manifest["units"]
            if unit["type"] == "sentence" and len(unit["formula_ids"]) == 2
        )
        self.assertIn("formula", formula_sentence["risk_flags"])
        self.assertTrue(formula_sentence["high_risk"])
        packet = next(
            json.loads((output / record["path"]).read_text(encoding="utf-8"))
            for record in manifest["packets"]
            if formula_sentence["unit_id"] in record["unit_ids"]
        )
        self.assertTrue(
            set(formula_sentence["formula_ids"]).issubset(
                {item["formula_id"] for item in packet["formula_context"]}
            )
        )
        self.assertEqual(
            packet["formula_registry_sha256"],
            manifest["formula_registry_sha256"],
        )

    def test_markdown_code_dollars_are_not_registered_as_formulas(self) -> None:
        manuscript = self.write(
            "formula-code.md",
            "# Results\nUse `$not_math$` as code, but $\\theta>0$ is a model restriction.\n",
        )
        completed, manifest, _ = self.run_prepare(manuscript, "out_formula_code")
        manifest = self.assert_prepared(completed, manifest)
        self.assertEqual(len(manifest["formulas"]), 1)
        self.assertEqual(manifest["formulas"][0]["raw"], r"$\theta>0$")

    def test_markdown_currency_is_not_consumed_as_math(self) -> None:
        manuscript = self.write(
            "currency.md",
            """# Results
Revenue is $100 and cost is $50, while $1+\\beta$ is a true formula.
Revenue was $100, while profit was $x_i$.
Price is $5 and elasticity is $\\beta<0$.
收入为$100，系数为$\\theta>0$。
""",
        )
        completed, manifest, _ = self.run_prepare(manuscript, "out_md_currency")
        manifest = self.assert_prepared(completed, manifest)
        visible = " ".join(
            unit["text"] for unit in manifest["units"] if unit["review_target"]
        )
        self.assertIn("Revenue is $100 and cost is $50", visible)
        self.assertIn("Revenue was $100", visible)
        self.assertIn("Price is $5", visible)
        self.assertIn("收入为$100", visible)
        self.assertEqual(
            {item["raw"] for item in manifest["formulas"]},
            {r"$1+\beta$", r"$x_i$", r"$\beta<0$", r"$\theta>0$"},
        )
        registry_ids = {item["formula_id"] for item in manifest["formulas"]}
        unit_formula_ids = {
            formula_id
            for unit in manifest["units"]
            for formula_id in unit.get("formula_ids", [])
        }
        self.assertEqual(unit_formula_ids, registry_ids)

        currency_only = self.write(
            "currency-only.md", "# Costs\nThe fee is $100 and the subsidy is $50.\n"
        )
        completed, currency_manifest, _ = self.run_prepare(
            currency_only, "out_currency_only"
        )
        currency_manifest = self.assert_prepared(completed, currency_manifest)
        self.assertEqual(currency_manifest["formulas"], [])

        unclosed = self.write(
            "unclosed-formula.md", "# Results\nThe restriction is $\\beta>0.\n"
        )
        failed, failed_manifest, _ = self.run_prepare(
            unclosed, "out_unclosed_formula"
        )
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("unclosed Markdown inline formula", failed.stderr)

    def test_tex_table_rows_cells_links_and_visible_multiargument_text_are_preserved(self) -> None:
        manuscript = self.write(
            "structured-tex.tex",
            r"""
\begin{tabular}{lcc}
\toprule
Outcome & Effect & SE \\
Employment & \multicolumn{2}{c}{10 percent and 2 percent} \\
\bottomrule
\end{tabular}
Replication files are at \href{https://example.com/data}{replication data}.
The \textcolor{red}{causal claim} remains qualified.
""",
        )
        completed, manifest, _ = self.run_prepare(manuscript, "out_structured_tex")
        manifest = self.assert_prepared(completed, manifest)
        visible = " ".join(
            unit["text"] for unit in manifest["units"] if unit["review_target"]
        )
        self.assertIn("[TABLE]", visible)
        self.assertIn("[ROW]", visible)
        self.assertIn("[CELL]", visible)
        self.assertIn("Outcome", visible)
        self.assertIn("Effect", visible)
        self.assertIn("Employment", visible)
        self.assertIn("10 percent and 2 percent", visible)
        self.assertNotIn("lccOutcome", visible)
        self.assertNotIn("2c10", visible)
        self.assertIn("causal claim", visible)
        self.assertNotIn("redcausal", visible)
        linked = next(
            unit
            for unit in manifest["units"]
            if "[LINK:replication data|https://example.com/data]" in unit["text"]
        )
        self.assertEqual(linked["external_links"], ["https://example.com/data"])

    def test_markdown_comments_caption_footnote_note_and_appendix(self) -> None:
        manuscript = self.write(
            "paper.md",
            """# Introduction
Visible sentence. <!-- Hidden causal claim causes everything. --> Another sentence.

![Figure 1: Trend estimate.](trend.png)

Notes: Values are normalized.

Text with [source](https://example.org/a_b?q=x~y) and a footnote.[^note_a]

- First obligation without punctuation
- Second obligation without punctuation

[^note_a]: Footnote definition is visible.

# Appendix A
附录句子应当被审计。
""",
        )
        completed, manifest, _ = self.run_prepare(manuscript)
        manifest = self.assert_prepared(completed, manifest)
        types = {unit["type"] for unit in manifest["units"]}
        self.assertTrue({"caption", "note", "footnote", "appendix_prose"}.issubset(types), types)
        all_text = " ".join(unit["text"] for unit in manifest["units"])
        self.assertNotIn("Hidden causal", all_text)
        sentence_texts = [unit["text"] for unit in manifest["units"] if unit["type"] == "sentence"]
        self.assertIn("First obligation without punctuation", sentence_texts)
        self.assertIn("Second obligation without punctuation", sentence_texts)
        self.assertTrue(manifest["appendix"]["detected"])
        linked = next(unit for unit in manifest["units"] if "[LINK:source|" in unit["text"])
        self.assertEqual(linked["external_links"], ["https://example.org/a_b?q=x~y"])
        self.assertEqual(linked["footnote_reference_ids"], ["note_a"])

    def test_chinese_appendix_heading_without_space_is_detected(self) -> None:
        markdown = self.write("appendix-a.md", "# 正文\n正文句子。\n# 附录A\n附录句子。\n")
        completed, manifest, _ = self.run_prepare(markdown, "out_appendix_md")
        manifest = self.assert_prepared(completed, manifest)
        self.assertTrue(manifest["appendix"]["detected"])
        self.assertTrue(
            any(unit["appendix"] and unit["text"] == "附录句子。" for unit in manifest["units"])
        )

        plain = self.write("appendix-a.txt", "1. Main\nMain sentence.\n\n附录A\n附录句子。\n")
        completed, manifest, _ = self.run_prepare(plain, "out_appendix_txt")
        manifest = self.assert_prepared(completed, manifest)
        self.assertTrue(manifest["appendix"]["detected"])
        self.assertTrue(
            any(unit["appendix"] and unit["text"] == "附录句子。" for unit in manifest["units"])
        )

    def test_plain_text_sections_and_chinese_sentence_splitting(self) -> None:
        manuscript = self.write(
            "paper.txt",
            """1. Introduction
The estimate is stable. It remains bounded.

一、结果
第一句说明结果。第二句提出限定！第三句提出问题？

附录
附录内容完整。
""",
        )
        completed, manifest, _ = self.run_prepare(manuscript)
        manifest = self.assert_prepared(completed, manifest)
        sentences = [unit["text"] for unit in manifest["units"] if unit["type"] == "sentence"]
        self.assertIn("第一句说明结果。", sentences)
        self.assertIn("第二句提出限定！", sentences)
        self.assertIn("第三句提出问题？", sentences)
        self.assertTrue(any(unit["appendix"] for unit in manifest["units"]))

    def test_sentence_split_protects_abbreviations_decimals_and_formula_placeholders(self) -> None:
        sentences = MODULE.split_sentences(
            "The U.S. estimate is 3.14, e.g. in 2020. The next result uses [FORMULA]. 中文一句。中文二句！"
        )
        values = [item[0] for item in sentences]
        self.assertEqual(len(values), 4, values)
        self.assertIn("3.14", values[0])
        self.assertIn("e.g.", values[0])
        self.assertEqual(values[-2:], ["中文一句。", "中文二句！"])

    def test_high_risk_flags_and_double_review_requirement(self) -> None:
        manuscript = self.write(
            "risk.txt",
            """1. Results
Exposure enters the specification. An unknown object remains. It causes a 12 percent increase through a mechanism, although it may be bounded. The author marker appears.
""",
        )
        completed, manifest, _ = self.run_prepare(manuscript)
        manifest = self.assert_prepared(completed, manifest)
        sentences = [unit for unit in manifest["units"] if unit["type"] == "sentence"]
        categories = {category for unit in sentences for category in unit["risk_flags"]}
        self.assertTrue({"definition", "causal", "mechanism", "numeric", "qualifier", "contract_marked"}.issubset(categories), categories)
        self.assertTrue(all(unit["min_independent_reviews"] >= 2 for unit in sentences if unit["high_risk"]))
        self.assertTrue(
            all(set(unit["required_roles"]) == set(MODULE.DEFAULT_ROLES) for unit in sentences)
        )
        definition_sentence = next(unit for unit in sentences if "definition" in unit["risk_flags"])
        causal_sentence = next(unit for unit in sentences if "causal" in unit["risk_flags"])
        marker_sentence = next(unit for unit in sentences if "contract_marked" in unit["risk_flags"])
        exposure_sentence = next(unit for unit in sentences if unit["text"].startswith("Exposure"))
        unknown_sentence = next(unit for unit in sentences if unit["text"].startswith("An unknown"))
        exposure_definition = next(
            item for item in manifest["definition_registry"] if item.get("term") == "Exposure"
        )
        self.assertIn("definitions_reader_sufficiency", definition_sentence["required_roles"])
        self.assertIn(exposure_definition["definition_id"], exposure_sentence["definition_ids"])
        self.assertIn("definition", exposure_sentence["risk_flags"])
        self.assertIn("definitions_reader_sufficiency", exposure_sentence["required_roles"])
        self.assertNotIn("D-empty", unknown_sentence["definition_ids"])
        self.assertNotIn("D-unknown", unknown_sentence["definition_ids"])
        self.assertNotIn("definition", unknown_sentence["risk_flags"])
        self.assertIn("evidence_claim_strength", causal_sentence["required_roles"])
        self.assertIn("economic_logic_scope_qualifiers", causal_sentence["required_roles"])
        self.assertGreaterEqual(len(marker_sentence["required_roles"]), 2)
        self.assertIn("I1", marker_sentence["intent_ids"])

    def test_substantive_heading_requires_intent_and_definition_review(self) -> None:
        manuscript = self.write(
            "heading.md", "# Exposure causes higher wages\nA bounded result follows.\n"
        )
        completed, manifest, _ = self.run_prepare(manuscript, "out_heading")
        manifest = self.assert_prepared(completed, manifest)
        heading = next(unit for unit in manifest["units"] if unit["type"] == "section")
        self.assertTrue(heading["requires_intent_mapping"])
        self.assertIn("causal", heading["risk_flags"])
        self.assertIn("definition", heading["risk_flags"])
        exposure_definition = next(
            item
            for item in manifest["definition_registry"]
            if item.get("term") == "Exposure"
        )
        self.assertIn(exposure_definition["definition_id"], heading["definition_ids"])
        self.assertEqual(set(heading["required_roles"]), set(MODULE.DEFAULT_ROLES))

    def test_all_four_semantic_roles_are_mandatory(self) -> None:
        manuscript = self.write("roles.md", "# Results\nA reader-visible sentence.\n")
        self.qa.write_text(
            json.dumps(
                {
                    "qa_contract": {
                        "schema_version": "1.0",
                        "qa_mode": "exhaustive",
                        "task_classification": {
                            "task_stage": "full_draft",
                            "qa_mode": "exhaustive",
                            "basis": "The complete manuscript requires semantic acceptance.",
                            "classified_by": "controller-test",
                            "classified_at": "2026-08-03T00:00:00Z",
                        },
                        "required_roles": ["author_intent_coverage"],
                    }
                }
            ),
            encoding="utf-8",
        )
        completed, manifest, _ = self.run_prepare(manuscript, "out_missing_roles")
        self.assertEqual(completed.returncode, 2)
        self.assertIsNone(manifest)
        self.assertIn("all four semantic roles", completed.stderr)

    def test_long_review_scope_is_split_into_bounded_packets_per_role(self) -> None:
        manuscript = self.write(
            "batched.md",
            "# Results\nOne sentence. Two sentence. Three sentence. Four sentence. Five sentence.\n",
        )
        qa_payload = json.loads(self.qa.read_text(encoding="utf-8"))
        qa_payload["qa_contract"]["max_units_per_packet"] = 2
        qa_payload["qa_contract"]["max_packet_bytes"] = 240_000
        self.qa.write_text(json.dumps(qa_payload), encoding="utf-8")
        completed, manifest, output = self.run_prepare(manuscript, "out_batched")
        manifest = self.assert_prepared(completed, manifest)
        targets = {
            unit["unit_id"]
            for unit in manifest["units"]
            if unit["review_target"] and unit["selected_for_review"]
        }
        self.assertEqual(manifest["packetization"]["max_units_per_packet"], 2)
        self.assertEqual(len(manifest["packets"]), len(MODULE.DEFAULT_ROLES) * 3)
        for role in MODULE.DEFAULT_ROLES:
            records = [record for record in manifest["packets"] if record["role"] == role]
            self.assertEqual([record["batch_index"] for record in records], [1, 2, 3])
            self.assertTrue(all(record["batch_count"] == 3 for record in records))
            self.assertTrue(all(len(record["unit_ids"]) <= 2 for record in records))
            flattened = [unit_id for record in records for unit_id in record["unit_ids"]]
            self.assertEqual(set(flattened), targets)
            self.assertEqual(len(flattened), len(set(flattened)))
            for record in records:
                self.assertLessEqual(record["packet_bytes"], 240_000)
                packet_path = output / record["path"]
                self.assertTrue(packet_path.is_file())
                packet = json.loads(packet_path.read_text(encoding="utf-8"))
                self.assertEqual(
                    packet["role_protocol_version"], MODULE.ROLE_PROTOCOL_VERSION
                )
                self.assertEqual(
                    packet["required_checks"],
                    MODULE.ROLE_PROTOCOLS[role]["required_criterion_ids"],
                )
                self.assertEqual(
                    packet["role_protocol_sha256"],
                    MODULE.canonical_hash(MODULE.ROLE_PROTOCOLS[role]),
                )
                self.assertIn(
                    "unit_id x required_checks",
                    packet["review_result_schema"]["coverage_requirement"],
                )

    def test_max_units_per_packet_setting_has_closed_1_to_25_range(self) -> None:
        self.assertEqual(
            MODULE.positive_integer_setting(
                {"max_units_per_packet": 1},
                "max_units_per_packet",
                MODULE.DEFAULT_MAX_UNITS_PER_PACKET,
                1,
                MODULE.MAX_UNITS_PER_PACKET,
            ),
            1,
        )
        self.assertEqual(
            MODULE.positive_integer_setting(
                {"max_units_per_packet": 25},
                "max_units_per_packet",
                MODULE.DEFAULT_MAX_UNITS_PER_PACKET,
                1,
                MODULE.MAX_UNITS_PER_PACKET,
            ),
            25,
        )
        manuscript = self.write("packet-unit-limit.md", "# Results\nOne sentence.\n")
        base = json.loads(self.qa.read_text(encoding="utf-8"))
        for value in (0, 26):
            with self.subTest(value=value):
                payload = json.loads(json.dumps(base))
                payload["qa_contract"]["max_units_per_packet"] = value
                self.qa.write_text(json.dumps(payload), encoding="utf-8")
                completed, manifest, _ = self.run_prepare(
                    manuscript, f"out_packet_unit_limit_{value}"
                )
                self.assertEqual(completed.returncode, 2)
                self.assertIsNone(manifest)
                stderr = json.loads(completed.stderr)
                self.assertEqual(stderr["status"], "fail")
                self.assertIn("integer from 1 through 25", stderr["error"])

    def test_max_packet_bytes_setting_has_closed_10000_to_240000_range(self) -> None:
        self.assertEqual(
            MODULE.positive_integer_setting(
                {"max_packet_bytes": 10_000},
                "max_packet_bytes",
                MODULE.DEFAULT_MAX_PACKET_BYTES,
                MODULE.MIN_PACKET_BYTES,
                MODULE.MAX_PACKET_BYTES,
            ),
            10_000,
        )
        self.assertEqual(
            MODULE.positive_integer_setting(
                {"max_packet_bytes": 240_000},
                "max_packet_bytes",
                MODULE.DEFAULT_MAX_PACKET_BYTES,
                MODULE.MIN_PACKET_BYTES,
                MODULE.MAX_PACKET_BYTES,
            ),
            240_000,
        )
        manuscript = self.write("packet-byte-limit.md", "# Results\nOne sentence.\n")
        base = json.loads(self.qa.read_text(encoding="utf-8"))
        for value in (9_999, 240_001):
            with self.subTest(value=value):
                payload = json.loads(json.dumps(base))
                payload["qa_contract"]["max_packet_bytes"] = value
                self.qa.write_text(json.dumps(payload), encoding="utf-8")
                completed, manifest, _ = self.run_prepare(
                    manuscript, f"out_packet_byte_limit_{value}"
                )
                self.assertEqual(completed.returncode, 2)
                self.assertIsNone(manifest)
                stderr = json.loads(completed.stderr)
                self.assertEqual(stderr["status"], "fail")
                self.assertIn("integer from 10000 through 240000", stderr["error"])

    def test_review_policy_is_canonical_and_bound_to_unit_requirements(self) -> None:
        manuscript = self.write(
            "review-policy.md",
            "# Results\nThe author marker identifies a bounded result. A plain sentence follows.\n",
        )
        payload = json.loads(self.qa.read_text(encoding="utf-8"))
        payload["qa_contract"]["minimum_high_risk_independent_reviews"] = 3
        self.qa.write_text(json.dumps(payload), encoding="utf-8")
        completed, manifest, _ = self.run_prepare(manuscript, "out_review_policy")
        manifest = self.assert_prepared(completed, manifest)
        policy = manifest["review_policy"]
        self.assertEqual(
            policy,
            {
                "minimum_high_risk_independent_reviews": 3,
                "required_semantic_roles": list(MODULE.DEFAULT_ROLES),
            },
        )
        high_risk_units = [
            unit
            for unit in manifest["units"]
            if unit["review_target"] and unit["high_risk"]
        ]
        self.assertTrue(high_risk_units)
        for unit in high_risk_units:
            self.assertIsInstance(unit["min_independent_reviews"], int)
            self.assertGreaterEqual(
                unit["min_independent_reviews"],
                policy["minimum_high_risk_independent_reviews"],
            )
            self.assertEqual(
                unit["required_roles"], policy["required_semantic_roles"]
            )

    def test_minimum_high_risk_review_setting_rejects_noncanonical_values(self) -> None:
        manuscript = self.write(
            "review-policy-invalid.md", "# Results\nOne sentence.\n"
        )
        base = json.loads(self.qa.read_text(encoding="utf-8"))
        for index, value in enumerate((1, 5, True, 2.5, "2"), 1):
            with self.subTest(value=value):
                payload = json.loads(json.dumps(base))
                payload["qa_contract"][
                    "minimum_high_risk_independent_reviews"
                ] = value
                self.qa.write_text(json.dumps(payload), encoding="utf-8")
                completed, manifest, _ = self.run_prepare(
                    manuscript, f"out_review_policy_invalid_{index}"
                )
                self.assertEqual(completed.returncode, 2)
                self.assertIsNone(manifest)
                stderr = json.loads(completed.stderr)
                self.assertEqual(stderr["status"], "fail")
                self.assertIn("integer from 2 through 4", stderr["error"])

        missing, missing_manifest, _ = self.run_prepare(
            manuscript,
            "out_review_policy_missing",
            "--test-omit-high-risk-minimum",
        )
        self.assertEqual(missing.returncode, 2)
        self.assertIsNone(missing_manifest)
        missing_stderr = json.loads(missing.stderr)
        self.assertEqual(missing_stderr["status"], "fail")
        self.assertIn("integer from 2 through 4", missing_stderr["error"])

    def test_manifest_and_unit_ids_are_stable(self) -> None:
        manuscript = self.write("stable.md", "# Results\nA stable result appears. Another sentence follows.\n")
        first_completed, first, first_out = self.run_prepare(manuscript, "out1")
        second_completed, second, second_out = self.run_prepare(manuscript, "out2")
        first = self.assert_prepared(first_completed, first)
        second = self.assert_prepared(second_completed, second)
        self.assertEqual(first["revision_target_unit_ids"], [])
        self.assertEqual(second["revision_target_unit_ids"], [])
        self.assertEqual(first["manifest_id"], second["manifest_id"])
        self.assertEqual(
            [(unit["unit_id"], unit["text_sha256"]) for unit in first["units"]],
            [(unit["unit_id"], unit["text_sha256"]) for unit in second["units"]],
        )
        self.assertEqual(
            hashlib.sha256((first_out / "qa_manifest.json").read_bytes()).hexdigest(),
            hashlib.sha256((second_out / "qa_manifest.json").read_bytes()).hexdigest(),
        )
        self.assertEqual(first["ledgers"]["baseline_to_candidate"], [])
        self.qa.write_text(
            json.dumps(
                {
                    "qa_contract": {
                        "qa_mode": "bounded_change",
                        "task_classification": {
                            "task_stage": "local_polish",
                            "qa_mode": "bounded_change",
                            "basis": "One sentence receives a local wording patch.",
                            "changed_artifact_or_source_ranges": [
                                {"path": "stable.md", "start_line": 2, "end_line": 2}
                            ],
                            "substantive_dependencies_checked": [],
                            "affected_intent_ids": ["I1"],
                            "classified_by": "controller-test",
                            "classified_at": "2026-08-03T00:00:00Z",
                        },
                        "revision_scope": {
                            "changed_source_ranges": [
                                {"path": "stable.md", "start_line": 2, "end_line": 2}
                            ],
                            "dependency_unit_ids": [],
                            "affected_intent_ids": ["I1"],
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        bounded_completed, bounded, _ = self.run_prepare(manuscript, "out_bounded")
        bounded = self.assert_prepared(bounded_completed, bounded)
        self.assertEqual(bounded["qa_mode"], "bounded_change")
        self.assertTrue(any(unit["selected_for_review"] for unit in bounded["units"]))
        self.assertFalse(
            next(unit for unit in bounded["units"] if unit["type"] == "section")["selected_for_review"]
        )
        self.assertEqual(
            bounded["revision_target_unit_ids"],
            sorted(
                {
                    unit["unit_id"]
                    for unit in bounded["units"]
                    if unit["review_target"] and unit["selected_for_review"]
                }
            ),
        )

    def test_bounded_change_requires_recorded_task_classification(self) -> None:
        manuscript = self.write("bounded.md", "# Results\nA local sentence changes.\n")
        self.qa.write_text(
            json.dumps(
                {
                    "qa_contract": {
                        "qa_mode": "bounded_change",
                        "revision_scope": {
                            "changed_source_ranges": [
                                {"path": "bounded.md", "start_line": 2, "end_line": 2}
                            ],
                            "dependency_unit_ids": [],
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        completed, manifest, _ = self.run_prepare(manuscript, "out_bounded_unclassified")
        self.assertEqual(completed.returncode, 2)
        self.assertIsNone(manifest)
        self.assertIn("task_classification", completed.stderr)

        self.qa.write_text(
            json.dumps(
                {
                    "qa_contract": {
                        "qa_mode": "bounded_change",
                        "task_classification": {
                            "task_stage": "local_edit",
                            "qa_mode": "bounded_change",
                            "basis": "A local edit was requested.",
                            "changed_artifact_or_source_ranges": [
                                {"path": "bounded.md", "start_line": 1, "end_line": 1}
                            ],
                            "substantive_dependencies_checked": [],
                            "affected_intent_ids": ["I1"],
                            "classified_by": "controller-test",
                            "classified_at": "2026-08-03T00:00:00Z",
                        },
                        "revision_scope": {
                            "changed_source_ranges": [
                                {"path": "bounded.md", "start_line": 2, "end_line": 2}
                            ],
                            "dependency_unit_ids": [],
                            "affected_intent_ids": ["I1"],
                        },
                    }
                }
            ),
            encoding="utf-8",
        )
        mismatch, mismatch_manifest, _ = self.run_prepare(
            manuscript, "out_bounded_mismatch"
        )
        self.assertEqual(mismatch.returncode, 2)
        self.assertIsNone(mismatch_manifest)
        self.assertIn("must equal revision_scope", mismatch.stderr)

    def test_exhaustive_mode_also_requires_recorded_task_classification(self) -> None:
        manuscript = self.write(
            "unclassified-exhaustive.md", "# Results\nA full-draft sentence.\n"
        )
        self.qa.write_text(
            json.dumps({"qa_contract": {"qa_mode": "exhaustive"}}),
            encoding="utf-8",
        )
        completed, manifest, _ = self.run_prepare(
            manuscript, "out_unclassified_exhaustive"
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIsNone(manifest)
        self.assertIn("task_classification", completed.stderr)

    def test_qa_mode_and_task_stage_mapping_are_explicit_and_closed(self) -> None:
        manuscript = self.write(
            "classification.md", "# Results\nA full-draft sentence.\n"
        )
        base = json.loads(self.qa.read_text(encoding="utf-8"))

        missing_mode = json.loads(json.dumps(base))
        missing_mode["qa_contract"].pop("qa_mode")
        old_qa = self.qa
        self.qa = self.write_json("qa-missing-mode.json", missing_mode)
        try:
            completed, manifest, _ = self.run_prepare(
                manuscript, "out_missing_mode"
            )
        finally:
            self.qa = old_qa
        self.assertEqual(completed.returncode, 2)
        self.assertIsNone(manifest)
        self.assertIn("explicitly declared", completed.stderr)

        invalid_stage = json.loads(json.dumps(base))
        invalid_stage["qa_contract"]["task_classification"]["task_stage"] = "banana"
        self.qa = self.write_json("qa-invalid-stage.json", invalid_stage)
        try:
            completed, manifest, _ = self.run_prepare(
                manuscript, "out_invalid_stage"
            )
        finally:
            self.qa = old_qa
        self.assertEqual(completed.returncode, 2)
        self.assertIsNone(manifest)
        self.assertIn("task_stage must be one of", completed.stderr)

        mismatched_stage = json.loads(json.dumps(base))
        mismatched_stage["qa_contract"]["task_classification"]["task_stage"] = (
            "local_edit"
        )
        self.qa = self.write_json("qa-mismatched-stage.json", mismatched_stage)
        try:
            completed, manifest, _ = self.run_prepare(
                manuscript, "out_mismatched_stage"
            )
        finally:
            self.qa = old_qa
        self.assertEqual(completed.returncode, 2)
        self.assertIsNone(manifest)
        self.assertIn("requires qa_mode=bounded_change", completed.stderr)

        malformed_metadata = json.loads(json.dumps(base))
        malformed_metadata["qa_contract"]["task_classification"]["basis"] = {
            "not": "a string"
        }
        self.qa = self.write_json(
            "qa-malformed-classification.json", malformed_metadata
        )
        try:
            completed, manifest, _ = self.run_prepare(
                manuscript, "out_malformed_classification"
            )
        finally:
            self.qa = old_qa
        self.assertEqual(completed.returncode, 2)
        self.assertIsNone(manifest)
        self.assertIn("basis must be a nonempty string", completed.stderr)

        naive_timestamp = json.loads(json.dumps(base))
        naive_timestamp["qa_contract"]["task_classification"][
            "classified_at"
        ] = "2026-08-03"
        self.qa = self.write_json("qa-naive-timestamp.json", naive_timestamp)
        try:
            completed, manifest, _ = self.run_prepare(
                manuscript, "out_naive_timestamp"
            )
        finally:
            self.qa = old_qa
        self.assertEqual(completed.returncode, 2)
        self.assertIsNone(manifest)
        self.assertIn("UTC offset or Z", completed.stderr)

        for stage in sorted(
            value
            for value, mode in MODULE.TASK_STAGE_QA_MODES.items()
            if mode == "exhaustive"
        ):
            with self.subTest(stage=stage):
                valid = json.loads(json.dumps(base))
                valid["qa_contract"]["task_classification"]["task_stage"] = stage
                self.qa = self.write_json(f"qa-stage-{stage}.json", valid)
                try:
                    completed, manifest, _ = self.run_prepare(
                        manuscript, f"out_stage_{stage}"
                    )
                finally:
                    self.qa = old_qa
                self.assert_prepared(completed, manifest)

        full_draft_artifact = self.write_json(
            "artifact-final-audit.json",
            {
                "artifact_contract": {
                    "task_mode": "full_draft",
                    "mature_baseline": False,
                    "metric_status": "measured",
                    "measurement_contract": {
                        "appendix_boundary": r"\appendix",
                        "source_word_method": "normalized_words",
                    },
                }
            },
        )
        final_missing_mode = json.loads(json.dumps(base))
        final_missing_mode["qa_contract"]["task_classification"][
            "task_stage"
        ] = "final_audit"
        self.qa = self.write_json("qa-final-missing-artifact-mode.json", final_missing_mode)
        try:
            blocked, blocked_manifest, _ = self.run_prepare(
                manuscript,
                "out_final_missing_artifact_mode",
                "--artifact-contract",
                str(full_draft_artifact),
            )
        finally:
            self.qa = old_qa
        self.assertEqual(blocked.returncode, 4)
        self.assertIsNone(blocked_manifest)
        self.assertEqual(
            json.loads(blocked.stderr)["reason_code"],
            "final_audit_artifact_mode_missing",
        )

        final_mismatch = json.loads(json.dumps(final_missing_mode))
        final_mismatch["qa_contract"]["task_classification"][
            "artifact_task_mode"
        ] = "major_revision"
        self.qa = self.write_json("qa-final-artifact-mode-mismatch.json", final_mismatch)
        try:
            blocked, blocked_manifest, _ = self.run_prepare(
                manuscript,
                "out_final_artifact_mode_mismatch",
                "--artifact-contract",
                str(full_draft_artifact),
            )
        finally:
            self.qa = old_qa
        self.assertEqual(blocked.returncode, 4)
        self.assertIsNone(blocked_manifest)
        self.assertEqual(
            json.loads(blocked.stderr)["reason_code"],
            "artifact_task_mode_mismatch",
        )

        translation_qa = json.loads(json.dumps(base))
        translation_qa["qa_contract"]["task_classification"][
            "task_stage"
        ] = "document_translation"
        translation_artifact = self.write_json(
            "artifact-translation-alias.json",
            {
                "artifact_contract": {
                    "task_mode": "translation",
                    "mature_baseline": True,
                    "metric_status": "measured",
                    "measurement_contract": {
                        "appendix_boundary": r"\appendix",
                        "source_word_method": "normalized_words",
                    },
                }
            },
        )
        self.qa = self.write_json("qa-translation-alias.json", translation_qa)
        try:
            completed, manifest, _ = self.run_prepare(
                manuscript,
                "out_translation_alias",
                "--artifact-contract",
                str(translation_artifact),
            )
        finally:
            self.qa = old_qa
        self.assert_prepared(completed, manifest)

    def test_bounded_change_affected_intents_are_explicit_and_authoritative(self) -> None:
        manuscript = self.write(
            "bounded-intent.md", "# Results\nThe author marker appears.\n"
        )
        payload = {
            "qa_contract": {
                "qa_mode": "bounded_change",
                "task_classification": {
                    "task_stage": "local_edit",
                    "qa_mode": "bounded_change",
                    "basis": "A claim-bearing sentence changed.",
                    "changed_artifact_or_source_ranges": [
                        {"path": "bounded-intent.md", "start_line": 2, "end_line": 2}
                    ],
                    "substantive_dependencies_checked": [],
                    "affected_intent_ids": ["I1"],
                    "classified_by": "controller-test",
                    "classified_at": "2026-08-03T00:00:00Z",
                },
                "revision_scope": {
                    "changed_source_ranges": [
                        {"path": "bounded-intent.md", "start_line": 2, "end_line": 2}
                    ],
                    "dependency_unit_ids": [],
                    "affected_intent_ids": ["I1"],
                },
            }
        }
        old_qa = self.qa
        self.qa = self.write_json("qa-bounded-intent.json", payload)
        try:
            completed, manifest, output = self.run_prepare(
                manuscript, "out_bounded_intent"
            )
        finally:
            self.qa = old_qa
        manifest = self.assert_prepared(completed, manifest)
        target = next(
            unit
            for unit in manifest["units"]
            if unit["type"] == "sentence"
            and unit["selected_for_review"]
            and "author marker" in unit["text"]
        )
        self.assertTrue(target["selected_for_review"])
        self.assertEqual(manifest["revision_scope"]["affected_intent_ids"], ["I1"])
        assignment_template = json.loads(
            (output / "qa_assignment_registry.template.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(
            any(
                record.get("assignment_kind") == "main_text_sufficiency"
                for record in assignment_template["assignments"]
            )
        )

        empty = json.loads(json.dumps(payload))
        empty["qa_contract"]["task_classification"]["affected_intent_ids"] = []
        empty["qa_contract"]["revision_scope"]["affected_intent_ids"] = []
        self.qa = self.write_json("qa-bounded-empty-intents.json", empty)
        try:
            failed, failed_manifest, _ = self.run_prepare(
                manuscript, "out_bounded_empty_intents"
            )
        finally:
            self.qa = old_qa
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("must not be empty", failed.stderr)

        payload["qa_contract"]["task_classification"]["affected_intent_ids"] = [
            "invented-intent"
        ]
        payload["qa_contract"]["revision_scope"]["affected_intent_ids"] = [
            "invented-intent"
        ]
        self.qa = self.write_json("qa-bounded-invented-intent.json", payload)
        try:
            failed, failed_manifest, _ = self.run_prepare(
                manuscript, "out_bounded_invented_intent"
            )
        finally:
            self.qa = old_qa
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("not present in the frozen author-intent authority", failed.stderr)

    def test_bounded_change_closes_paragraph_intent_definition_and_footnote_dependencies(self) -> None:
        manuscript = self.write(
            "bounded-closure.md",
            """# Introduction
The bounded result uses Exposure.[^scope] A neighboring qualifier remains.

# Conclusion
The bounded result is restated for readers.

[^scope]: Exposure covers the admitted sample only.
""",
        )
        payload = {
            "qa_contract": {
                "qa_mode": "bounded_change",
                "task_classification": {
                    "task_stage": "local_edit",
                    "qa_mode": "bounded_change",
                    "basis": "The introduction claim was edited.",
                    "changed_artifact_or_source_ranges": [
                        {"path": "bounded-closure.md", "start_line": 2, "end_line": 2}
                    ],
                    "substantive_dependencies_checked": [],
                    "affected_intent_ids": ["I1"],
                    "classified_by": "controller-test",
                    "classified_at": "2026-08-03T00:00:00Z",
                },
                "revision_scope": {
                    "changed_source_ranges": [
                        {"path": "bounded-closure.md", "start_line": 2, "end_line": 2}
                    ],
                    "dependency_unit_ids": [],
                    "affected_intent_ids": ["I1"],
                },
            }
        }
        old_qa = self.qa
        self.qa = self.write_json("qa-bounded-closure.json", payload)
        try:
            completed, manifest, _ = self.run_prepare(
                manuscript, "out_bounded_closure"
            )
        finally:
            self.qa = old_qa
        manifest = self.assert_prepared(completed, manifest)
        selected_sentences = [
            unit
            for unit in manifest["units"]
            if unit["type"] == "sentence" and unit["selected_for_review"]
        ]
        selected_text = " ".join(unit["text"] for unit in selected_sentences)
        self.assertIn("neighboring qualifier", selected_text)
        self.assertIn("restated for readers", selected_text)
        self.assertIn("admitted sample only", selected_text)
        conclusion = next(
            unit for unit in selected_sentences if "restated for readers" in unit["text"]
        )
        self.assertTrue(
            {"affected_intent", "intent_dependency_closure"}
            & set(conclusion["selection_reasons"])
        )
        footnote = next(
            unit for unit in selected_sentences if "admitted sample only" in unit["text"]
        )
        self.assertTrue(
            {"forward_dependency_closure", "definition_dependency_closure"}
            & set(footnote["selection_reasons"])
        )
        expected_revision_targets = sorted(
            {
                unit["unit_id"]
                for unit in manifest["units"]
                if unit["review_target"] and unit["selected_for_review"]
            }
        )
        self.assertEqual(
            manifest["revision_target_unit_ids"], expected_revision_targets
        )
        self.assertEqual(
            len(manifest["revision_target_unit_ids"]),
            len(set(manifest["revision_target_unit_ids"])),
        )

        stale_dependency = json.loads(json.dumps(payload))
        stale_dependency["qa_contract"]["task_classification"][
            "substantive_dependencies_checked"
        ] = ["stale-or-typo"]
        stale_dependency["qa_contract"]["revision_scope"][
            "dependency_unit_ids"
        ] = ["stale-or-typo"]
        self.qa = self.write_json(
            "qa-bounded-stale-dependency.json", stale_dependency
        )
        try:
            failed, failed_manifest, _ = self.run_prepare(
                manuscript, "out_bounded_stale_dependency"
            )
        finally:
            self.qa = old_qa
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("unknown or non-review target", failed.stderr)

        mixed_ranges = json.loads(json.dumps(payload))
        invalid_range = {
            "path": "missing.md",
            "start_line": 1,
            "end_line": 1,
        }
        mixed_ranges["qa_contract"]["task_classification"][
            "changed_artifact_or_source_ranges"
        ].append(invalid_range)
        mixed_ranges["qa_contract"]["revision_scope"][
            "changed_source_ranges"
        ].append(invalid_range)
        self.qa = self.write_json("qa-bounded-mixed-ranges.json", mixed_ranges)
        try:
            failed, failed_manifest, _ = self.run_prepare(
                manuscript, "out_bounded_mixed_ranges"
            )
        finally:
            self.qa = old_qa
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("matches no review target", failed.stderr)

        boolean_line = json.loads(json.dumps(payload))
        boolean_line["qa_contract"]["task_classification"][
            "changed_artifact_or_source_ranges"
        ][0]["start_line"] = True
        boolean_line["qa_contract"]["revision_scope"]["changed_source_ranges"][
            0
        ]["start_line"] = True
        self.qa = self.write_json("qa-bounded-boolean-line.json", boolean_line)
        try:
            failed, failed_manifest, _ = self.run_prepare(
                manuscript, "out_bounded_boolean_line"
            )
        finally:
            self.qa = old_qa
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("integer line numbers", failed.stderr)

    def test_hash_contract_and_artifact_contract_interfaces(self) -> None:
        manuscript = self.write("hashes.md", "# Results\nA result appears.\n")
        artifact = self.write_json(
            "artifact.json",
            {
                "artifact_contract": {
                    "task_mode": "full_draft",
                    "mature_baseline": False,
                    "metric_status": "measured",
                    "measurement_contract": {
                        "appendix_boundary": r"\appendix",
                        "source_word_method": "normalized_words",
                    },
                    "extra": True,
                    "section_cards": [
                        {
                            "section_id": "S-results",
                            "section_name": "Results",
                            "target_word_range": [1, 100],
                            "must_remain_main": [
                                {"type": "section", "value": "Results"}
                            ],
                            "minimum_depth_questions": [
                                "Does the section explain the bounded result?"
                            ],
                        }
                    ],
                    "content_obligations": [
                        {
                            "obligation_id": "I1",
                            "intent_id": "I1",
                            "content": "bounded result",
                        }
                    ],
                    "content_conservation_ledger": [
                        {
                            "ledger_id": "L1",
                            "baseline_id": "baseline-section",
                            "candidate_id": "candidate-section",
                            "disposition": "retained",
                        }
                    ],
                }
            },
        )
        completed, manifest, output = self.run_prepare(
            manuscript, "out_hash", "--artifact-contract", str(artifact)
        )
        manifest = self.assert_prepared(completed, manifest)
        file_hash = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(manifest["manuscript_sha256"], file_hash(manuscript))
        self.assertEqual(manifest["contract_sha256"], file_hash(self.intent))
        self.assertEqual(manifest["qa_contract_sha256"], file_hash(self.qa))
        self.assertEqual(manifest["inputs"]["artifact_contract"]["sha256"], file_hash(artifact))
        self.assertIn("Q1", {item["obligation_id"] for item in manifest["content_obligations"]})
        self.assertIn("D2", {item["definition_id"] for item in manifest["definition_registry"]})
        negative = next(
            item for item in manifest["content_obligations"]
            if item.get("kind") == "must_not_claim"
        )
        self.assertEqual(negative["content"], "causality without design")
        self.assertEqual(
            manifest["ledgers"]["baseline_to_candidate"],
            [
                {
                    "ledger_id": "L1",
                    "baseline_id": "baseline-section",
                    "candidate_id": "candidate-section",
                    "disposition": "retained",
                }
            ],
        )
        sentence = next(unit for unit in manifest["units"] if unit["type"] == "sentence")
        self.assertEqual(sentence["text_sha256"], hashlib.sha256(sentence["text"].encode("utf-8")).hexdigest())
        packet = json.loads((output / manifest["packets"][0]["path"]).read_text(encoding="utf-8"))
        self.assertEqual(packet["contract_sha256"], file_hash(self.intent))
        self.assertEqual(packet["qa_contract_sha256"], file_hash(self.qa))
        self.assertEqual(packet["artifact_contract_sha256"], file_hash(artifact))
        self.assertEqual(
            packet["contract_context"]["section_cards"],
            json.loads(artifact.read_text(encoding="utf-8"))["artifact_contract"][
                "section_cards"
            ],
        )
        self.assertEqual(packet["content_sha256"], manifest["expanded_manuscript_sha256"])
        self.assertEqual(
            packet["expanded_manuscript_sha256"], manifest["expanded_manuscript_sha256"]
        )
        self.assertIsNone(packet["manifest_sha256"])
        no_ledger_artifact = self.write_json(
            "artifact-no-ledger.json",
            {
                "artifact_contract": {
                    "task_mode": "full_draft",
                    "mature_baseline": False,
                    "metric_status": "measured",
                    "measurement_contract": {
                        "appendix_boundary": r"\appendix",
                        "source_word_method": "normalized_words",
                    },
                }
            },
        )
        missing_completed, missing_manifest, _ = self.run_prepare(
            manuscript,
            "out_hash_no_ledger",
            "--artifact-contract",
            str(no_ledger_artifact),
        )
        missing_manifest = self.assert_prepared(missing_completed, missing_manifest)
        self.assertEqual(missing_manifest["ledgers"]["baseline_to_candidate"], [])

        no_contract, no_contract_manifest, _ = self.run_prepare(
            manuscript,
            "out_hash_missing_artifact",
            "--test-omit-artifact-contract",
        )
        self.assertEqual(no_contract.returncode, 4)
        self.assertIsNone(no_contract_manifest)
        self.assertEqual(
            json.loads(no_contract.stderr)["reason_code"],
            "artifact_contract_missing",
        )

        mismatched_artifact = self.write_json(
            "artifact-mismatched-mode.json",
            {
                "artifact_contract": {
                    "task_mode": "major_revision",
                    "mature_baseline": True,
                    "metric_status": "measured",
                    "measurement_contract": {
                        "appendix_boundary": r"\appendix",
                        "source_word_method": "normalized_words",
                    },
                }
            },
        )
        mismatch, mismatch_manifest, _ = self.run_prepare(
            manuscript,
            "out_hash_mismatched_artifact",
            "--artifact-contract",
            str(mismatched_artifact),
        )
        self.assertEqual(mismatch.returncode, 4)
        self.assertIsNone(mismatch_manifest)
        self.assertEqual(
            json.loads(mismatch.stderr)["reason_code"],
            "artifact_task_mode_mismatch",
        )

        conflicting_qa_payload = json.loads(self.qa.read_text(encoding="utf-8"))
        conflicting_qa_payload["qa_contract"]["section_cards"] = [
            {"section_id": "S-other", "section_name": "Other"}
        ]
        old_qa = self.qa
        self.qa = self.write_json("qa-conflicting-section-cards.json", conflicting_qa_payload)
        try:
            conflict, conflict_manifest, _ = self.run_prepare(
                manuscript,
                "out_conflicting_section_cards",
                "--artifact-contract",
                str(artifact),
            )
        finally:
            self.qa = old_qa
        self.assertEqual(conflict.returncode, 4)
        self.assertIsNone(conflict_manifest)
        self.assertEqual(
            json.loads(conflict.stderr)["reason_code"],
            "artifact_section_cards_conflict",
        )

        for name, metric_status, expected_code, expected_reason in (
            ("missing", None, 4, "artifact_metric_status_invalid"),
            ("unavailable", "unavailable", 3, "artifact_metric_unavailable"),
            ("ambiguous", "ambiguous", 3, "artifact_metric_unavailable"),
            ("invalid", "guessed", 4, "artifact_metric_status_invalid"),
            (
                "measured_without_contract",
                "measured",
                4,
                "artifact_measurement_contract_invalid",
            ),
        ):
            with self.subTest(metric_status=name):
                artifact_payload = {
                    "artifact_contract": {
                        "task_mode": "full_draft",
                        "mature_baseline": False,
                    }
                }
                if metric_status is not None:
                    artifact_payload["artifact_contract"][
                        "metric_status"
                    ] = metric_status
                status_artifact = self.write_json(
                    f"artifact-metric-{name}.json", artifact_payload
                )
                blocked, blocked_manifest, _ = self.run_prepare(
                    manuscript,
                    f"out_artifact_metric_{name}",
                    "--artifact-contract",
                    str(status_artifact),
                )
                self.assertEqual(blocked.returncode, expected_code)
                self.assertIsNone(blocked_manifest)
                stderr = json.loads(blocked.stderr)
                self.assertEqual(stderr["reason_code"], expected_reason)
                if expected_code == 3:
                    self.assertEqual(stderr["status"], "metric_unavailable")

    def test_qa_contract_manuscript_path_must_bind_live_manuscript(self) -> None:
        manuscript = self.write(
            "path-bound.md", "# Results\nA bounded result appears.\n"
        )
        missing, missing_manifest, _ = self.run_prepare(
            manuscript,
            "out_missing_qa_manuscript_path",
            "--test-omit-manuscript-path",
        )
        self.assertEqual(missing.returncode, 4)
        self.assertIsNone(missing_manifest)
        self.assertEqual(
            json.loads(missing.stderr)["reason_code"],
            "qa_manuscript_path_missing",
        )

        payload = json.loads(self.qa.read_text(encoding="utf-8"))
        payload["qa_contract"]["manuscript_path"] = str(
            (self.root / "another-manuscript.md").resolve()
        )
        old_qa = self.qa
        self.qa = self.write_json("qa-wrong-manuscript.json", payload)
        try:
            mismatched, mismatched_manifest, _ = self.run_prepare(
                manuscript,
                "out_wrong_qa_manuscript_path",
                "--test-preserve-manuscript-path",
            )
        finally:
            self.qa = old_qa
        self.assertEqual(mismatched.returncode, 4)
        self.assertIsNone(mismatched_manifest)
        self.assertEqual(
            json.loads(mismatched.stderr)["reason_code"],
            "qa_manuscript_path_mismatch",
        )

    def test_hash_bound_evidence_registry_is_verified_and_projected_once(self) -> None:
        manuscript = self.write(
            "evidence-manuscript.md", "# Results\nA bounded result appears.\n"
        )
        source = self.write("evidence/table-main.txt", "estimate=0.12\n")
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        registry_payload = {
            "schema_version": "1.0",
            "schema_id": "evidence-registry/1.0",
            "status": "frozen-current",
            "approval_record": {
                "confirmed_by": "author-test",
                "confirmed_at": "2026-08-03T12:00:00+08:00",
                "confirmation_source": "author-message-test",
            },
            "evidence": [
                {
                    "evidence_id": "E-main",
                    "source": "evidence/table-main.txt",
                    "source_sha256": source_hash,
                }
            ],
        }
        registry = self.write_json("evidence-registry.json", registry_payload)
        registry_hash = hashlib.sha256(registry.read_bytes()).hexdigest()
        qa_payload = json.loads(self.qa.read_text(encoding="utf-8"))
        qa_payload["qa_contract"]["evidence_registry_source"] = {
            "path": "evidence-registry.json",
            "sha256": registry_hash,
        }
        old_qa = self.qa
        self.qa = self.write_json("qa-with-evidence-registry.json", qa_payload)
        try:
            completed, manifest, output = self.run_prepare(
                manuscript, "out_evidence_registry"
            )
            manifest = self.assert_prepared(completed, manifest)
            binding = manifest["inputs"]["evidence_registry"]
            self.assertEqual(binding["path"], str(registry.resolve()))
            self.assertEqual(binding["sha256"], registry_hash)
            self.assertNotIn("evidence_registry", manifest["source"])
            self.assertEqual(
                [item["evidence_id"] for item in manifest["evidence_registry"]],
                ["E-main"],
            )
            packet = json.loads(
                (output / manifest["packets"][0]["path"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(packet["evidence_registry_source"], binding)
            self.assertEqual(
                packet["contract_context"]["evidence_registry"],
                manifest["evidence_registry"],
            )

            registry.write_text(
                json.dumps({**registry_payload, "status": "accepted"}),
                encoding="utf-8",
            )
            failed, failed_manifest, _ = self.run_prepare(
                manuscript, "out_stale_evidence_registry"
            )
        finally:
            self.qa = old_qa
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("changed after the QA contract was frozen", failed.stderr)

    def test_paper_state_wrappers_are_supported_and_conflicts_fail_closed(self) -> None:
        manuscript = self.write("paper-state.md", "# Results\nA bounded result appears.\n")
        combined = self.write_json(
            "paper-state.json",
            {
                "paper_state": {
                    "author_intent_contract": {
                        "schema_version": "1.0",
                        "intent_contract_id": "intent-state",
                        "intent_revision_id": "r1",
                        "intent_status": "frozen-current",
                        "gate_status": "ready",
                        "unresolved_material_questions": [],
                        "approval_record": {
                            "confirmed_by": "author-test",
                            "confirmed_at": "2026-08-03T00:00:00Z",
                            "confirmed_scope": "complete_author_intent_contract",
                            "confirmation_source": "author-message-test",
                            "freeze_authorized_by": "author-test",
                            "freeze_authorized_at": "2026-08-03T00:00:00Z",
                        },
                        "propositions": [
                            {"intent_id": "I-state", "must_express": "bounded result"},
                            {
                                "intent_id": "Q-state",
                                "must_express": "state-level obligation",
                            },
                        ],
                        "definition_registry": [
                            {
                                "definition_id": "D-state",
                                "term": "State term",
                                "definition": "A paper-state definition.",
                            }
                        ],
                    },
                    "qa_contract": {
                        "schema_version": "1.0",
                        "qa_mode": "exhaustive",
                        "task_classification": {
                            "task_stage": "full_draft",
                            "qa_mode": "exhaustive",
                            "basis": "The complete manuscript requires semantic acceptance.",
                            "classified_by": "controller-test",
                            "classified_at": "2026-08-03T00:00:00Z",
                        },
                        "required_roles": list(MODULE.DEFAULT_ROLES),
                    },
                    "artifact_contract": {
                        "schema_version": "1.0",
                        "task_mode": "full_draft",
                        "mature_baseline": False,
                        "metric_status": "measured",
                        "measurement_contract": {
                            "appendix_boundary": r"\appendix",
                            "source_word_method": "normalized_words",
                        },
                    },
                    "content_obligations": [
                        {
                            "obligation_id": "Q-state",
                            "obligation_type": "must_express",
                            "content": "state-level obligation",
                        }
                    ],
                    "definition_registry": [
                        {
                            "definition_id": "D-state",
                            "term": "State term",
                            "definition": "A paper-state definition.",
                        }
                    ],
                    "content_conservation_ledger": [
                        {
                            "ledger_id": "L-state",
                            "source_block_id": "baseline-state",
                            "destination": "sent-state",
                            "disposition": "retained",
                        }
                    ],
                }
            },
        )
        old_intent, old_qa = self.intent, self.qa
        self.intent = self.qa = combined
        try:
            completed, manifest, _ = self.run_prepare(
                manuscript,
                "out_paper_state",
                "--artifact-contract",
                str(combined),
            )
        finally:
            self.intent, self.qa = old_intent, old_qa
        manifest = self.assert_prepared(completed, manifest)
        combined_hash = hashlib.sha256(combined.read_bytes()).hexdigest()
        self.assertEqual(manifest["author_intent_contract_sha256"], combined_hash)
        self.assertEqual(manifest["qa_contract_sha256"], combined_hash)
        self.assertEqual(manifest["artifact_contract_sha256"], combined_hash)
        self.assertIn(
            "I-state", {item.get("intent_id") for item in manifest["content_obligations"]}
        )
        self.assertIn(
            "Q-state", {item.get("obligation_id") for item in manifest["content_obligations"]}
        )
        self.assertIn(
            "D-state", {item.get("definition_id") for item in manifest["definition_registry"]}
        )
        self.assertEqual(
            [item["ledger_id"] for item in manifest["ledgers"]["baseline_to_candidate"]],
            ["L-state"],
        )

        conflicting = self.write_json(
            "conflicting-state.json",
            {
                "author_intent_contract": {"intent_contract_id": "top"},
                "paper_state": {
                    "author_intent_contract": {"intent_contract_id": "nested"}
                },
            },
        )
        self.intent = conflicting
        try:
            failed, failed_manifest, _ = self.run_prepare(
                manuscript, "out_conflicting_state"
            )
        finally:
            self.intent = old_intent
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("conflicting top-level and paper_state", failed.stderr)

    def test_paper_state_author_intent_pointer_must_bind_live_authority(self) -> None:
        manuscript = self.write(
            "pointer.md", "# Results\nA bounded result appears.\n"
        )
        qa_payload = json.loads(self.qa.read_text(encoding="utf-8"))
        author_payload = json.loads(self.intent.read_text(encoding="utf-8"))[
            "author_intent_contract"
        ]
        intent_sha = hashlib.sha256(self.intent.read_bytes()).hexdigest()
        pointer = {
            "authoritative_path_or_artifact_id": str(self.intent.resolve()),
            "intent_contract_id": author_payload["intent_contract_id"],
            "intent_revision_id": author_payload["intent_revision_id"],
            "intent_status": author_payload["intent_status"],
            "gate_status": author_payload["gate_status"],
            "sha256": intent_sha,
        }
        qa_payload["paper_state"] = {"author_intent_contract": pointer}
        valid_qa = self.write_json("qa-pointer-valid.json", qa_payload)
        old_qa = self.qa
        self.qa = valid_qa
        try:
            completed, manifest, _ = self.run_prepare(
                manuscript, "out_pointer_valid"
            )
        finally:
            self.qa = old_qa
        self.assert_prepared(completed, manifest)

        attacks = {
            "revision": ("intent_revision_id", "stale-r0"),
            "hash": ("sha256", "0" * 64),
            "path": (
                "authoritative_path_or_artifact_id",
                str((self.root / "other-intent.json").resolve()),
            ),
        }
        for name, (field, value) in attacks.items():
            with self.subTest(name=name):
                attacked = json.loads(json.dumps(qa_payload))
                attacked["paper_state"]["author_intent_contract"][field] = value
                attacked_qa = self.write_json(f"qa-pointer-{name}.json", attacked)
                self.qa = attacked_qa
                try:
                    failed, failed_manifest, _ = self.run_prepare(
                        manuscript, f"out_pointer_{name}"
                    )
                finally:
                    self.qa = old_qa
                self.assertEqual(failed.returncode, 4)
                self.assertIsNone(failed_manifest)
                self.assertIn("author_intent_pointer_mismatch", failed.stderr)

    def test_same_id_contract_enrichment_merges_but_semantic_reversal_fails(self) -> None:
        manuscript = self.write("enrichment.md", "# Results\nA bounded result appears.\n")
        payload = json.loads(self.intent.read_text(encoding="utf-8"))
        author = payload["author_intent_contract"]
        author["definition_registry"] = [
            {
                "definition_id": "D1",
                "canonical_term": "Exposure",
                "canonical_definition": "The observed treatment measure.",
            },
            {
                "definition_id": "D2",
                "term": "Sample",
                "definition": "The admitted observations.",
            },
        ]
        payload["paper_state"] = {
            "content_obligations": [
                {
                    "obligation_id": "I1",
                    "intent_id": "I1",
                    "required_meaning": "bounded result",
                    "must_remain_main": True,
                }
            ],
            "definition_registry": [
                {
                    "definition_id": "D1",
                    "term": "Exposure",
                    "definition": "The observed treatment measure.",
                    "intended_first_location": "Results",
                }
            ],
        }
        old_intent = self.intent
        self.intent = self.write_json("intent-compatible-enrichment.json", payload)
        try:
            completed, manifest, _ = self.run_prepare(
                manuscript, "out_compatible_enrichment"
            )
        finally:
            self.intent = old_intent
        manifest = self.assert_prepared(completed, manifest)
        obligation = next(
            item
            for item in manifest["content_obligations"]
            if item.get("obligation_id") == "I1"
        )
        definition = next(
            item
            for item in manifest["definition_registry"]
            if item.get("definition_id") == "D1"
        )
        self.assertTrue(obligation["must_remain_main"])
        self.assertEqual(definition["intended_first_location"], "Results")

        payload["paper_state"]["content_obligations"][0]["required_meaning"] = (
            "the opposite unbounded result"
        )
        old_intent = self.intent
        self.intent = self.write_json("intent-conflicting-enrichment.json", payload)
        try:
            failed, failed_manifest, _ = self.run_prepare(
                manuscript, "out_conflicting_enrichment"
            )
        finally:
            self.intent = old_intent
        self.assertEqual(failed.returncode, 4)
        self.assertIsNone(failed_manifest)
        self.assertEqual(
            json.loads(failed.stderr)["reason_code"],
            "obligation_authority_conflict",
        )

        for name, state, reason_code in (
            (
                "unanchored-obligation",
                {
                    "content_obligations": [
                        {
                            "obligation_id": "AI-added",
                            "content": "an author-unapproved claim",
                        }
                    ]
                },
                "supplemental_obligation_unanchored",
            ),
            (
                "unanchored-definition",
                {
                    "definition_registry": [
                        {
                            "definition_id": "AI-definition",
                            "term": "Invented term",
                            "definition": "An author-unapproved meaning.",
                        }
                    ]
                },
                "supplemental_definition_unanchored",
            ),
        ):
            with self.subTest(name=name):
                unanchored = json.loads(old_intent.read_text(encoding="utf-8"))
                unanchored["paper_state"] = state
                self.intent = self.write_json(f"intent-{name}.json", unanchored)
                try:
                    blocked, blocked_manifest, _ = self.run_prepare(
                        manuscript, f"out_{name}"
                    )
                finally:
                    self.intent = old_intent
                self.assertEqual(blocked.returncode, 4)
                self.assertIsNone(blocked_manifest)
                self.assertEqual(
                    json.loads(blocked.stderr)["reason_code"], reason_code
                )

    def test_packet_preparation_requires_frozen_ready_recoverable_author_intent(self) -> None:
        manuscript = self.write("intent-gate.md", "# Results\nA bounded result appears.\n")
        original = json.loads(self.intent.read_text(encoding="utf-8"))
        cases = []

        proposed = json.loads(json.dumps(original))
        proposed["author_intent_contract"]["intent_status"] = "proposed"
        cases.append(("proposed", proposed, 5, "intent_not_frozen"))

        missing_approval = json.loads(json.dumps(original))
        missing_approval["author_intent_contract"].pop("approval_record")
        cases.append(
            ("missing-approval", missing_approval, 4, "approval_record_missing")
        )

        evidence_conflict = json.loads(json.dumps(original))
        evidence_conflict["author_intent_contract"]["gate_status"] = (
            "evidence_conflict"
        )
        cases.append(
            ("evidence-conflict", evidence_conflict, 6, "contract_evidence_conflict")
        )

        explicit_hold = json.loads(json.dumps(original))
        explicit_hold["author_intent_contract"]["approval_record"][
            "explicit_hold_reason"
        ] = "The author asked writing to remain paused."
        cases.append(("explicit-hold", explicit_hold, 5, "explicit_author_hold"))

        partial_scope = json.loads(json.dumps(original))
        partial_scope["author_intent_contract"]["approval_record"][
            "confirmed_scope"
        ] = "one paragraph only"
        cases.append(
            ("partial-scope", partial_scope, 4, "approval_scope_incomplete")
        )

        naive_time = json.loads(json.dumps(original))
        naive_time["author_intent_contract"]["approval_record"][
            "confirmed_at"
        ] = "2026-08-03 00:00:00"
        naive_time["author_intent_contract"]["approval_record"][
            "freeze_authorized_at"
        ] = "2026-08-03 00:00:00"
        cases.append(("naive-time", naive_time, 4, "approval_record_invalid"))

        mismatched_event = json.loads(json.dumps(original))
        mismatched_event["author_intent_contract"]["approval_record"][
            "freeze_authorized_at"
        ] = "2026-08-03T00:01:00Z"
        cases.append(
            (
                "mismatched-freeze-event",
                mismatched_event,
                4,
                "approval_freeze_event_mismatch",
            )
        )

        old_intent = self.intent
        try:
            for name, payload, expected_code, reason_code in cases:
                with self.subTest(name=name):
                    self.intent = self.write_json(f"intent-{name}.json", payload)
                    completed, manifest, _ = self.run_prepare(
                        manuscript, f"out_intent_{name}"
                    )
                    self.assertEqual(completed.returncode, expected_code)
                    self.assertIsNone(manifest)
                    error = json.loads(completed.stderr)
                    self.assertEqual(error["reason_code"], reason_code)
        finally:
            self.intent = old_intent

    def test_non_json_authority_uses_a_hash_bound_json_qa_view(self) -> None:
        manuscript = self.write("adapter.md", "# Results\nA bounded result appears.\n")
        authority = self.write(
            "author-intent.md",
            "# Frozen author intent\n\nThe paper must report a bounded result.\n",
        )
        payload = json.loads(self.intent.read_text(encoding="utf-8"))
        payload["author_intent_contract"]["artifact_role"] = "qa_view"
        payload["author_intent_contract"]["authority_source"] = {
            "path": "author-intent.md",
            "sha256": hashlib.sha256(authority.read_bytes()).hexdigest(),
            "format": "markdown",
        }
        projection_hash = MODULE.canonical_hash(payload["author_intent_contract"])
        payload["author_intent_contract"]["adapter_confirmation"] = {
            "status": "confirmed",
            "confirmed_by": "author-test",
            "confirmed_at": "2026-08-03T12:00:00+08:00",
            "confirmed_scope": "complete_author_intent_projection",
            "confirmation_source": "author-message-test",
            "authority_source_sha256": hashlib.sha256(authority.read_bytes()).hexdigest(),
            "intent_revision_id": "r1",
            "qa_view_projection_sha256": projection_hash,
        }
        self.intent = self.write_json("intent-adapter.json", payload)
        completed, manifest, _ = self.run_prepare(manuscript, "out_adapter")
        manifest = self.assert_prepared(completed, manifest)
        authority_record = manifest["author_intent_authority_source"]
        self.assertEqual(authority_record["path"], str(authority.resolve()))
        self.assertEqual(authority_record["format"], "markdown")
        packet = json.loads(
            (self.root / "out_adapter" / manifest["packets"][0]["path"]).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(packet["author_intent_authority_source"], authority_record)

        missing_confirmation = json.loads(self.intent.read_text(encoding="utf-8"))
        missing_confirmation["author_intent_contract"].pop("adapter_confirmation")
        old_intent = self.intent
        self.intent = self.write_json("intent-adapter-unconfirmed.json", missing_confirmation)
        try:
            failed, failed_manifest, _ = self.run_prepare(
                manuscript, "out_unconfirmed_adapter"
            )
        finally:
            self.intent = old_intent
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("explicit adapter_confirmation", failed.stderr)

        invalid_confirmation_time = json.loads(
            self.intent.read_text(encoding="utf-8")
        )
        invalid_confirmation_time["author_intent_contract"]["adapter_confirmation"][
            "confirmed_at"
        ] = "2026-08-03 12:00:00"
        old_intent = self.intent
        self.intent = self.write_json(
            "intent-adapter-invalid-time.json", invalid_confirmation_time
        )
        try:
            failed, failed_manifest, _ = self.run_prepare(
                manuscript, "out_invalid_adapter_time"
            )
        finally:
            self.intent = old_intent
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("must include a UTC offset or Z", failed.stderr)

        stale_projection = json.loads(self.intent.read_text(encoding="utf-8"))
        stale_projection["author_intent_contract"]["reader_takeaway"] = (
            "A silently changed projection."
        )
        old_intent = self.intent
        self.intent = self.write_json("intent-adapter-stale-view.json", stale_projection)
        try:
            failed, failed_manifest, _ = self.run_prepare(
                manuscript, "out_stale_projection"
            )
        finally:
            self.intent = old_intent
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("qa_view_projection_sha256", failed.stderr)

        authority.write_text("Changed authority.\n", encoding="utf-8")
        failed, failed_manifest, _ = self.run_prepare(manuscript, "out_stale_adapter")
        self.assertEqual(failed.returncode, 2)
        self.assertIsNone(failed_manifest)
        self.assertIn("authoritative intent source changed", failed.stderr)

    def test_authority_adapter_format_is_closed_and_suffix_bound(self) -> None:
        manuscript = self.write("adapter-format.md", "# Results\nA bounded result appears.\n")

        def adapter_payload(authority: Path, source_format: str) -> dict:
            payload = json.loads(self.intent.read_text(encoding="utf-8"))
            source_hash = hashlib.sha256(authority.read_bytes()).hexdigest()
            payload["author_intent_contract"]["artifact_role"] = "qa_view"
            payload["author_intent_contract"]["authority_source"] = {
                "path": authority.name,
                "sha256": source_hash,
                "format": source_format,
            }
            projection_hash = MODULE.canonical_hash(payload["author_intent_contract"])
            payload["author_intent_contract"]["adapter_confirmation"] = {
                "status": "confirmed",
                "confirmed_by": "author-test",
                "confirmed_at": "2026-08-03T12:00:00+08:00",
                "confirmed_scope": "complete_author_intent_projection",
                "confirmation_source": "author-message-test",
                "authority_source_sha256": source_hash,
                "intent_revision_id": "r1",
                "qa_view_projection_sha256": projection_hash,
            }
            return payload

        authority_txt = self.write("author-intent.txt", "Frozen author intent.\n")
        original_intent = self.intent
        self.intent = self.write_json(
            "intent-adapter-txt.json", adapter_payload(authority_txt, "txt")
        )
        try:
            completed, manifest, _ = self.run_prepare(manuscript, "out_adapter_txt")
            manifest = self.assert_prepared(completed, manifest)
            self.assertEqual(manifest["author_intent_authority_source"]["format"], "txt")
        finally:
            self.intent = original_intent

        cases = (
            ("unknown", authority_txt, "docx", "must be one of"),
            ("suffix-mismatch", authority_txt, "yaml", "does not match"),
        )
        for name, authority, source_format, expected in cases:
            with self.subTest(name=name):
                self.intent = self.write_json(
                    f"intent-adapter-{name}.json",
                    adapter_payload(authority, source_format),
                )
                try:
                    failed, failed_manifest, _ = self.run_prepare(
                        manuscript, f"out_adapter_{name}"
                    )
                finally:
                    self.intent = original_intent
                self.assertEqual(failed.returncode, 2)
                self.assertIsNone(failed_manifest)
                self.assertIn(expected, failed.stderr)

    def test_include_escape_fails_closed(self) -> None:
        outside = Path(self.temp.name).parent / "outside-qa-test.tex"
        outside.write_text("Outside sentence.", encoding="utf-8")
        try:
            manuscript = self.write("escape.tex", "\\input{../outside-qa-test}\n")
            completed, manifest, _ = self.run_prepare(manuscript)
            self.assertEqual(completed.returncode, 2)
            self.assertIsNone(manifest)
            self.assertIn("escapes project root", completed.stderr)
        finally:
            outside.unlink(missing_ok=True)

    def test_missing_include_fails_closed(self) -> None:
        manuscript = self.write("missing.tex", "\\input{does-not-exist}\n")
        completed, manifest, _ = self.run_prepare(manuscript)
        self.assertEqual(completed.returncode, 2)
        self.assertIsNone(manifest)
        self.assertIn("included file not found", completed.stderr)

    def test_include_cycle_fails_closed(self) -> None:
        manuscript = self.write("cycle.tex", "\\input{part}\n")
        self.write("part.tex", "\\input{cycle}\n")
        completed, manifest, _ = self.run_prepare(manuscript)
        self.assertEqual(completed.returncode, 2)
        self.assertIsNone(manifest)
        self.assertIn("cyclic LaTeX include", completed.stderr)

    def test_duplicate_appendix_marker_fails_closed(self) -> None:
        manuscript = self.write(
            "duplicate.tex",
            "\\section{Main}\nVisible sentence.\\appendix First.\\appendix Second.",
        )
        completed, manifest, _ = self.run_prepare(manuscript)
        self.assertEqual(completed.returncode, 2)
        self.assertIsNone(manifest)
        self.assertIn("ambiguous LaTeX appendix boundary", completed.stderr)

    def test_malformed_required_balanced_argument_fails_closed(self) -> None:
        manuscript = self.write("malformed.tex", "\\section{Unclosed\nVisible sentence.")
        completed, manifest, _ = self.run_prepare(manuscript)
        self.assertEqual(completed.returncode, 2)
        self.assertIsNone(manifest)
        self.assertIn("unclosed balanced", completed.stderr)


if __name__ == "__main__":
    unittest.main()
