#!/usr/bin/env python3
"""Regression tests for the deterministic citation-integrity gate."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

import audit_citation_integrity as auditor


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def bib_entry(
    citekey: str,
    *,
    title: str | None = None,
    doi: str | None = None,
    author: str = "Author, Alice",
    year: int = 2024,
) -> dict[str, Any]:
    return {
        "citekey": citekey,
        "title": title or f"Title for {citekey}",
        "doi": doi,
        "author": author,
        "year": year,
    }


STANDARD_CLUSTER_FUNCTIONS = (
    "recent_frontier",
    "closest_contribution",
    "theory_mechanism",
    "data_measurement_institution",
    "method_identification_model",
    "contrary_evidence_alternative_explanation",
)


def complete_coverage_clusters(
    active: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    active_record = active or {
        "cluster_id": "recent_frontier",
        "function": "recent_frontier",
        "applicable": True,
        "rationale": "Current frontier is applicable to the fixture.",
        "gap_disposition": "resolved",
        "minimum_verified_sources": 1,
    }
    active_function = active_record["function"]
    records = [dict(active_record)]
    for function in STANDARD_CLUSTER_FUNCTIONS:
        if function == active_function:
            continue
        records.append(
            {
                "cluster_id": function,
                "function": function,
                "applicable": False,
                "rationale": "Not applicable to this synthetic fixture.",
                "gap_disposition": "not_applicable",
            }
        )
    return records


class CitationFixture:
    def __init__(
        self,
        root: Path,
        *,
        manuscript_text: str = r"\section{Results} Evidence \citep{Smith2024}.",
        suffix: str = ".tex",
        bib_entries: list[dict[str, Any]] | None = None,
        registry_entries: list[dict[str, Any]] | None = None,
        clusters: list[dict[str, Any]] | None = None,
        coverage_extra: dict[str, Any] | None = None,
        visible_keys: list[str] | None = None,
    ) -> None:
        self.root = root
        self.manuscript = root / f"paper{suffix}"
        self.manuscript.write_text(manuscript_text, encoding="utf-8")
        self.bib = root / "references.bib"
        self.library_manifest = root / "reference_library_manifest.json"
        self.registry = root / "literature_registry.json"
        self.coverage = root / "coverage_contract.json"
        self.qa_manifest = root / "qa_manifest.json"
        self.evidence = root / "evidence_ledger.json"
        self.visible = root / "paper.bbl"
        self.attestation = root / "build_attestation.json"
        self.report = root / "citation_report.json"
        self.bib_entries = bib_entries or [
            bib_entry("Smith2024", doi="10.1000/smith"),
            bib_entry("InventoryOnly", doi="10.1000/inventory"),
        ]
        raw_registry_entries = registry_entries or [
            {
                "citekey": "Smith2024",
                "status": "admitted",
                "coverage_roles": ["recent_frontier"],
            },
            {"citekey": "InventoryOnly", "status": "candidate"},
        ]
        self.registry_entries = [dict(entry) for entry in raw_registry_entries]
        for entry in self.registry_entries:
            if entry.get("status") == "admitted":
                entry.setdefault("inspection_evidence", "fixture-inspection-record")
        self.clusters = (
            complete_coverage_clusters() if clusters is None else clusters
        )
        self.coverage_extra = coverage_extra or {}
        self.visible_keys_override = visible_keys
        self.refresh()

    def _write_bib(self) -> None:
        rendered: list[str] = []
        for entry in self.bib_entries:
            fields = [
                f"  author = {{{entry['author']}}}",
                f"  title = {{{entry['title']}}}",
                f"  year = {{{entry['year']}}}",
            ]
            if entry.get("doi"):
                fields.append(f"  doi = {{{entry['doi']}}}")
            rendered.append(
                f"@article{{{entry['citekey']},\n" + ",\n".join(fields) + "\n}\n"
            )
        self.bib.write_text("\n".join(rendered), encoding="utf-8")

    def refresh(self) -> None:
        self._write_bib()
        library_payload = {
            "schema_version": "1.0",
            "schema_id": "reference-library-manifest/1.0",
            "library_id": "fixture-library",
            "library_revision": "1",
            "libraries": [
                {"path": self.bib.name, "sha256": auditor.sha256_file(self.bib)}
            ],
        }
        write_json(self.library_manifest, library_payload)
        library_sha = auditor.sha256_file(self.library_manifest)
        registry_payload = {
            "schema_version": "1.0",
            "schema_id": "literature-registry/1.0",
            "registry_id": "fixture-registry",
            "registry_revision": "1",
            "library_id": "fixture-library",
            "library_revision": "1",
            "reference_library_manifest_sha256": library_sha,
            "entries": self.registry_entries,
        }
        write_json(self.registry, registry_payload)
        registry_sha = auditor.sha256_file(self.registry)
        coverage_payload = {
            "schema_version": "1.0",
            "schema_id": "literature-coverage-contract/1.0",
            "contract_id": "fixture-coverage",
            "contract_revision": "1",
            "task_stage": "final_audit",
            "search_scope": {
                "databases_or_closed_corpus": ["synthetic fixture corpus"],
                "languages": ["English"],
                "coverage_end_date": "2026-08-03",
                "source_types": ["journal article"],
                "inclusion_criteria": ["fixture records"],
                "exclusion_criteria": ["non-fixture records"],
            },
            "stop_condition": "All fixture clusters inspected.",
            "unresolved_gaps": [],
            "approval_record": {
                "confirmed_by": "fixture-author",
                "confirmed_at": "2026-08-03T12:00:00+08:00",
            },
            "reference_library_manifest_sha256": library_sha,
            "literature_registry_sha256": registry_sha,
            "coverage_clusters": self.clusters,
            **self.coverage_extra,
        }
        write_json(self.coverage, coverage_payload)

        expanded, fmt, source_files = auditor.load_manuscript(
            self.manuscript, self.root
        )
        occurrences = auditor.scan_citations(expanded, fmt)
        body_keys = sorted(
            {record.key for record in occurrences if record.kind == "body"}
        )
        qa_payload = {
            "schema_version": "1.0",
            "schema_id": "qa-manifest/1.0",
            "manifest_id": "qa-fixture",
            "manuscript_sha256": auditor.sha256_file(self.manuscript),
            "expanded_manuscript_sha256": auditor.sha256_text(expanded),
            "source_files": source_files,
            "units": [
                {
                    "unit_id": "sentence-1",
                    "reader_visible": True,
                    "citation_keys": body_keys,
                }
            ],
        }
        write_json(self.qa_manifest, qa_payload)
        evidence_payload = {
            "schema_version": "1.0",
            "schema_id": "text-to-evidence-ledger/1.0",
            "ledger_id": "fixture-evidence-ledger",
            "ledger_revision": "1",
            "qa_manifest_sha256": auditor.sha256_file(self.qa_manifest),
            "manuscript_sha256": auditor.sha256_file(self.manuscript),
            "expanded_manuscript_sha256": auditor.sha256_text(expanded),
            "literature_registry_sha256": registry_sha,
            "entries": (
                [
                    {
                        "claim_id": "claim-fixture-1",
                        "unit_id": "sentence-1",
                        "claim_type": "literature_support",
                        "citekeys": body_keys,
                        "support_role": "direct_support",
                        "support_strength": "consistent_with",
                        "source_locator": "synthetic full-source inspection",
                        "status": "supported",
                    }
                ]
                if body_keys
                else []
            ),
        }
        write_json(self.evidence, evidence_payload)

        authorized = auditor.authorized_nocite_keys(
            coverage_payload,
            {entry["citekey"]: entry for entry in self.registry_entries},
        )
        nocites = {record.key for record in occurrences if record.kind == "nocite"}
        effective_nocites: set[str] = set()
        for key in nocites & authorized:
            if key == "*":
                effective_nocites.update(
                    entry["citekey"]
                    for entry in self.registry_entries
                    if entry.get("status") == "admitted"
                )
            else:
                effective_nocites.add(key)
        visible_keys = (
            self.visible_keys_override
            if self.visible_keys_override is not None
            else sorted(set(body_keys) | effective_nocites)
        )
        self.visible.write_text(
            "\n".join(f"\\bibitem{{{key}}} Entry {key}." for key in visible_keys)
            + "\n",
            encoding="utf-8",
        )
        attestation_payload = {
            "schema_version": "1.0",
            "schema_id": "bibliography-build-attestation/1.0",
            "status": "complete",
            "expanded_manuscript_sha256": auditor.sha256_text(expanded),
            "reference_library_manifest_sha256": library_sha,
            "qa_manifest_sha256": auditor.sha256_file(self.qa_manifest),
            "visible_bibliography_sha256": auditor.sha256_file(self.visible),
            "reference_library_files": [
                {"path": str(self.bib), "sha256": auditor.sha256_file(self.bib)}
            ],
            "build_timestamp": "2026-08-03T12:00:00+08:00",
            "build_tool": "fixture-bibliography-builder",
        }
        write_json(self.attestation, attestation_payload)

    def run(self, mode: str = "final", *extra: str) -> tuple[int, dict[str, Any]]:
        argv = [
            "--mode",
            mode,
            "--manuscript",
            str(self.manuscript),
            "--project-root",
            str(self.root),
            "--reference-library-manifest",
            str(self.library_manifest),
            "--literature-registry",
            str(self.registry),
            "--coverage-contract",
            str(self.coverage),
            "--text-to-evidence-ledger",
            str(self.evidence),
            "--qa-manifest",
            str(self.qa_manifest),
            "--report",
            str(self.report),
        ]
        if mode == "final":
            argv.extend(
                [
                    "--visible-bibliography",
                    str(self.visible),
                    "--bibliography-build-attestation",
                    str(self.attestation),
                ]
            )
        argv.extend(extra)
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = auditor.main(argv)
        return exit_code, json.loads(self.report.read_text(encoding="utf-8"))


class CitationIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def finding_codes(self, report: dict[str, Any]) -> set[str]:
        return {finding["code"] for finding in report["findings"]}

    def test_final_tex_passes_and_unused_library_inventory_is_allowed(self) -> None:
        fixture = CitationFixture(self.root)
        code, report = fixture.run()
        self.assertEqual((code, report["status"]), (0, "pass"))
        self.assertEqual(report["scope"], "citation_integrity_gate_only")
        self.assertFalse(report["whole_manuscript_delivery_authorized"])
        self.assertNotIn("delivery_status", report)
        self.assertIn("InventoryOnly", report["citekey_sets"]["library"])
        self.assertNotIn(
            "InventoryOnly", report["citekey_sets"]["visible_bibliography"]
        )

    def test_recursive_tex_ignores_comment_pseudocitation(self) -> None:
        chapter = self.root / "chapter.tex"
        chapter.write_text(
            "Evidence \\citep[see][p.~2]{Smith2024}. % \\cite{Ghost}\n",
            encoding="utf-8",
        )
        fixture = CitationFixture(
            self.root, manuscript_text="\\section{Results}\n\\input{chapter}\n"
        )
        code, report = fixture.run()
        self.assertEqual(code, 0)
        self.assertEqual(report["citekey_sets"]["body"], ["Smith2024"])
        self.assertEqual(len(report["manuscript"]["source_files"]), 2)

    def test_unknown_custom_cite_macro_fails_closed(self) -> None:
        fixture = CitationFixture(self.root)
        fixture.manuscript.write_text(
            r"Evidence follows \mycite{Smith2024}.", encoding="utf-8"
        )
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (3, "metric_unavailable"))
        self.assertIn("unsupported or custom citation command", report["findings"][0]["message"])

    def test_tex_verbatim_pseudocitation_is_ignored(self) -> None:
        fixture = CitationFixture(
            self.root,
            manuscript_text=(
                "\\begin{verbatim}\n\\cite{Ghost}\n\\end{verbatim}\n"
                "Inline \\verb|\\cite{AlsoGhost}|.\n"
                "Evidence \\cite{Smith2024}."
            ),
        )
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (0, "pass"))
        self.assertEqual(report["citekey_sets"]["body"], ["Smith2024"])

    def test_tex_include_cycle_is_metric_unavailable(self) -> None:
        fixture = CitationFixture(self.root)
        loop = self.root / "loop.tex"
        fixture.manuscript.write_text("\\input{loop}\n", encoding="utf-8")
        loop.write_text("\\input{paper}\n", encoding="utf-8")
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (3, "metric_unavailable"))
        self.assertIn("cyclic LaTeX include", report["findings"][0]["message"])

    def test_tex_multicite_and_authorized_nocite_close(self) -> None:
        entries = [
            bib_entry("Smith2024"),
            bib_entry("Jones2023"),
            bib_entry("AppendixSource"),
        ]
        registry = [
            {
                "citekey": "Smith2024",
                "status": "admitted",
                "coverage_roles": ["recent_frontier"],
            },
            {"citekey": "Jones2023", "status": "admitted"},
            {"citekey": "AppendixSource", "status": "admitted"},
        ]
        fixture = CitationFixture(
            self.root,
            manuscript_text=(
                r"\parencites[see]{Smith2024}[compare]{Jones2023}"
                r"\nocite{AppendixSource}"
            ),
            bib_entries=entries,
            registry_entries=registry,
            coverage_extra={"authorized_nocite_keys": ["AppendixSource"]},
        )
        code, report = fixture.run()
        self.assertEqual(code, 0)
        self.assertEqual(report["citekey_sets"]["body"], ["Jones2023", "Smith2024"])
        self.assertEqual(
            report["final_bibliography_closure"]["actual_visible_citekeys"],
            ["AppendixSource", "Jones2023", "Smith2024"],
        )

    def test_authorized_nocite_star_expands_only_admitted_registry(self) -> None:
        fixture = CitationFixture(
            self.root,
            manuscript_text=r"Evidence \cite{Smith2024}. \nocite{*}",
            registry_entries=[
                {
                    "citekey": "Smith2024",
                    "status": "admitted",
                    "coverage_roles": ["recent_frontier"],
                },
                {"citekey": "InventoryOnly", "status": "admitted"},
            ],
            coverage_extra={"authorized_nocite_keys": ["*"]},
        )
        code, report = fixture.run()
        self.assertEqual(code, 0)
        self.assertEqual(
            report["citekey_sets"]["visible_bibliography"],
            ["InventoryOnly", "Smith2024"],
        )

    def test_pandoc_markdown_ignores_code_html_and_email(self) -> None:
        entries = [bib_entry("Smith2024"), bib_entry("Jones2023")]
        registry = [
            {
                "citekey": "Smith2024",
                "status": "admitted",
                "coverage_roles": ["recent_frontier"],
            },
            {"citekey": "Jones2023", "status": "admitted"},
        ]
        markdown = """---
title: Test
---
Evidence @Smith2024 and [see -@Jones2023].
`@CodeOnly`
<!-- @CommentOnly -->
author@example.com
```text
@FenceOnly
```
"""
        fixture = CitationFixture(
            self.root,
            manuscript_text=markdown,
            suffix=".md",
            bib_entries=entries,
            registry_entries=registry,
        )
        code, report = fixture.run()
        self.assertEqual(code, 0)
        self.assertEqual(report["citekey_sets"]["body"], ["Jones2023", "Smith2024"])

    def test_markdown_fence_closes_and_later_citation_is_visible(self) -> None:
        markdown = """```text
@Ghost
```
After the fence @Smith2024.
"""
        fixture = CitationFixture(
            self.root, manuscript_text=markdown, suffix=".md"
        )
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (0, "pass"))
        self.assertEqual(report["citekey_sets"]["body"], ["Smith2024"])

    def test_structured_txt_passes(self) -> None:
        fixture = CitationFixture(
            self.root,
            manuscript_text="Evidence [CITATION:Smith2024].\n",
            suffix=".txt",
        )
        code, report = fixture.run()
        self.assertEqual((code, report["status"]), (0, "pass"))

    def test_unstructured_txt_is_metric_unavailable(self) -> None:
        fixture = CitationFixture(self.root)
        fixture.manuscript = self.root / "plain.txt"
        fixture.manuscript.write_text("Smith (2024) reports a result.", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            code = auditor.main(
                [
                    "--mode",
                    "draft",
                    "--manuscript",
                    str(fixture.manuscript),
                    "--reference-library-manifest",
                    str(fixture.library_manifest),
                    "--literature-registry",
                    str(fixture.registry),
                    "--coverage-contract",
                    str(fixture.coverage),
                    "--text-to-evidence-ledger",
                    str(fixture.evidence),
                    "--qa-manifest",
                    str(fixture.qa_manifest),
                    "--report",
                    str(fixture.report),
                ]
            )
        report = json.loads(fixture.report.read_text(encoding="utf-8"))
        self.assertEqual((code, report["status"]), (3, "metric_unavailable"))

    def test_missing_body_citekey_fails(self) -> None:
        registry = [
            {
                "citekey": "Missing2024",
                "status": "admitted",
                "coverage_roles": ["recent_frontier"],
            }
        ]
        fixture = CitationFixture(
            self.root,
            manuscript_text=r"Evidence \cite{Missing2024}.",
            bib_entries=[bib_entry("LibraryOnly")],
            registry_entries=registry,
        )
        code, report = fixture.run("draft")
        self.assertNotEqual(code, 0)
        self.assertIn("body_citekeys_missing_from_library", self.finding_codes(report))

    def test_duplicate_citekey_fails(self) -> None:
        fixture = CitationFixture(
            self.root,
            bib_entries=[bib_entry("Smith2024"), bib_entry("Smith2024", title="Other")],
            registry_entries=[
                {
                    "citekey": "Smith2024",
                    "status": "admitted",
                    "coverage_roles": ["recent_frontier"],
                }
            ],
        )
        code, report = fixture.run("draft")
        self.assertEqual(report["status"], "fail")
        self.assertIn("duplicate_citekey", self.finding_codes(report))

    def test_multiple_bib_files_string_macro_and_unicode_pass(self) -> None:
        fixture = CitationFixture(self.root)
        second = self.root / "supplement.bib"
        second.write_text(
            '@string{jn = "\u7ecf\u6d4e\u5b66\u671f\u520a"}\n'
            '@article{Second2022, title={{\u4e2d\u6587} Nested Title}, '
            'journal=jn # " A", year={2022}}\n',
            encoding="utf-8",
        )
        manifest = json.loads(fixture.library_manifest.read_text(encoding="utf-8"))
        manifest["sources"] = manifest.pop("libraries")
        manifest["sources"].append(
            {"path": second.name, "sha256": auditor.sha256_file(second)}
        )
        write_json(fixture.library_manifest, manifest)
        library_sha = auditor.sha256_file(fixture.library_manifest)
        registry = json.loads(fixture.registry.read_text(encoding="utf-8"))
        registry.pop("reference_library_manifest_sha256")
        registry["library_manifest_sha256"] = library_sha
        registry["entries"][0]["coverage_cluster_ids"] = registry["entries"][0].pop(
            "coverage_roles"
        )
        registry["entries"].append(
            {"citekey": "Second2022", "status": "candidate"}
        )
        write_json(fixture.registry, registry)
        registry_sha = auditor.sha256_file(fixture.registry)
        coverage = json.loads(fixture.coverage.read_text(encoding="utf-8"))
        coverage.pop("reference_library_manifest_sha256")
        coverage["library_manifest_sha256"] = library_sha
        coverage["literature_registry_sha256"] = registry_sha
        write_json(fixture.coverage, coverage)
        evidence = json.loads(fixture.evidence.read_text(encoding="utf-8"))
        evidence["literature_registry_sha256"] = registry_sha
        write_json(fixture.evidence, evidence)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (0, "pass"))
        self.assertEqual(
            report["citekey_sets"]["library"],
            ["InventoryOnly", "Second2022", "Smith2024"],
        )

    def test_compact_schema_identity_is_rejected_consistently(self) -> None:
        fixture = CitationFixture(self.root)
        manifest = json.loads(fixture.library_manifest.read_text(encoding="utf-8"))
        manifest.pop("schema_id")
        manifest["schema_version"] = "reference-library-manifest/1.0"
        write_json(fixture.library_manifest, manifest)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn("schema_id_invalid", self.finding_codes(report))
        self.assertIn("schema_version_invalid", self.finding_codes(report))

    def test_bibtex_percent_comments_do_not_create_fake_entries(self) -> None:
        path = self.root / "comments.bib"
        path.write_text(
            "% @article{Ghost, title={Fake}}\n"
            "@article{Smith2024,\n"
            "  title={Real \\% Measure}, % trailing comment\n"
            "  year={2024}\n"
            "}\n",
            encoding="utf-8",
        )
        entries = auditor.parse_bibtex(path)
        self.assertEqual([entry.citekey for entry in entries], ["Smith2024"])
        self.assertIn(r"\%", entries[0].fields["title"])

    def test_duplicate_doi_fails(self) -> None:
        fixture = CitationFixture(
            self.root,
            bib_entries=[
                bib_entry("Smith2024", doi="https://doi.org/10.1/same"),
                bib_entry("Other2024", doi="DOI: 10.1/SAME"),
            ],
            registry_entries=[
                {
                    "citekey": "Smith2024",
                    "status": "admitted",
                    "coverage_roles": ["recent_frontier"],
                },
                {"citekey": "Other2024", "status": "candidate"},
            ],
        )
        code, report = fixture.run("draft")
        self.assertEqual(report["status"], "fail")
        self.assertIn("duplicate_doi", self.finding_codes(report))

    def test_suspected_duplicate_title_requires_approval(self) -> None:
        fixture = CitationFixture(
            self.root,
            bib_entries=[
                bib_entry("Smith2024", title="A Shared Title"),
                bib_entry("Other2024", title="A {Shared} Title!"),
            ],
            registry_entries=[
                {
                    "citekey": "Smith2024",
                    "status": "admitted",
                    "coverage_roles": ["recent_frontier"],
                },
                {"citekey": "Other2024", "status": "candidate"},
            ],
        )
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (2, "approval_required"))
        self.assertIn("suspected_duplicate_title", self.finding_codes(report))

    def test_nonadmitted_body_source_fails(self) -> None:
        fixture = CitationFixture(
            self.root,
            registry_entries=[
                {
                    "citekey": "Smith2024",
                    "status": "inspected",
                    "coverage_roles": ["recent_frontier"],
                },
                {"citekey": "InventoryOnly", "status": "candidate"},
            ],
        )
        code, report = fixture.run("draft")
        self.assertEqual(report["status"], "fail")
        self.assertIn("body_source_not_admitted", self.finding_codes(report))

    def test_registry_status_enum_rejects_accepted_alias(self) -> None:
        fixture = CitationFixture(self.root)
        fixture.registry_entries[0]["status"] = "accepted"
        fixture.refresh()
        code, report = fixture.run("draft")
        self.assertEqual(report["status"], "fail")
        self.assertIn("registry_status_invalid", self.finding_codes(report))

    def test_cited_admitted_source_requires_inspection_evidence(self) -> None:
        fixture = CitationFixture(self.root)
        fixture.registry_entries[0].pop("inspection_evidence")
        fixture.refresh()
        code, report = fixture.run("draft")
        self.assertEqual(report["status"], "fail")
        self.assertIn("body_source_inspection_missing", self.finding_codes(report))

    def test_coverage_cluster_gap_fails(self) -> None:
        fixture = CitationFixture(
            self.root,
            clusters=complete_coverage_clusters(
                {
                    "cluster_id": "method_identification",
                    "function": "method_identification_model",
                    "applicable": True,
                    "rationale": "Identification precedents are applicable.",
                    "gap_disposition": "fail",
                    "minimum_verified_sources": 1,
                }
            ),
        )
        code, report = fixture.run("draft")
        self.assertEqual(report["status"], "fail")
        self.assertIn("coverage_cluster_gap", self.finding_codes(report))

    def test_project_minimum_is_enforced_only_when_configured(self) -> None:
        fixture = CitationFixture(
            self.root,
            coverage_extra={
                "source_count_policy": {
                    "minimum_verified_sources": 2,
                    "provenance": "author_requirement",
                    "provenance_record": "Synthetic author requirement.",
                }
            },
        )
        code, report = fixture.run("draft")
        self.assertEqual(report["status"], "fail")
        self.assertIn("coverage_total_below_minimum", self.finding_codes(report))
        self.assertTrue(report["coverage"]["global_minimum_applied"])

    def test_configured_source_count_requires_provenance_record(self) -> None:
        fixture = CitationFixture(
            self.root,
            coverage_extra={
                "source_count_policy": {
                    "minimum_verified_sources": 1,
                    "provenance": "author_requirement",
                }
            },
        )
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn(
            "coverage_source_count_provenance_record_missing",
            self.finding_codes(report),
        )

    def test_target_range_lower_bound_is_enforced(self) -> None:
        fixture = CitationFixture(
            self.root,
            coverage_extra={
                "source_count_policy": {
                    "target_range": [2, 4],
                    "provenance": "author_requirement",
                    "provenance_record": "Synthetic author requirement.",
                }
            },
        )
        code, report = fixture.run("draft")
        self.assertEqual(report["status"], "fail")
        self.assertIn("coverage_target_below_minimum", self.finding_codes(report))

    def test_hard_target_range_upper_bound_requires_approval(self) -> None:
        fixture = CitationFixture(
            self.root,
            coverage_extra={
                "source_count_policy": {
                    "target_range": {"minimum": 0, "maximum": 0},
                    "provenance": "author_requirement",
                    "provenance_record": "Synthetic author requirement.",
                    "enforcement": "hard",
                }
            },
        )
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (2, "approval_required"))
        self.assertIn(
            "coverage_target_above_hard_maximum", self.finding_codes(report)
        )

    def test_target_range_provenance_is_closed_enum(self) -> None:
        fixture = CitationFixture(
            self.root,
            coverage_extra={
                "target_range": [1, 2],
                "minimum_verified_sources_basis": "researcher_intuition",
            },
        )
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn("coverage_target_range_basis_invalid", self.finding_codes(report))

    def test_target_range_rejects_reversed_or_noninteger_bounds(self) -> None:
        fixture = CitationFixture(
            self.root,
            coverage_extra={
                "target_range": {"minimum": 3, "maximum": 2},
                "minimum_verified_sources_basis": "journal_rule",
            },
        )
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn("coverage_target_range_invalid", self.finding_codes(report))

    def test_target_range_alias_conflict_is_incomplete(self) -> None:
        fixture = CitationFixture(
            self.root,
            coverage_extra={
                "target_range": [1, 2],
                "source_count_policy": {
                    "target_range": [2, 3],
                    "provenance": "author_requirement",
                    "provenance_record": "Synthetic author requirement.",
                },
                "minimum_verified_sources_basis": "author_requirement",
            },
        )
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn("coverage_target_range_alias_conflict", self.finding_codes(report))

    def test_target_range_enforcement_is_closed_enum(self) -> None:
        fixture = CitationFixture(
            self.root,
            coverage_extra={
                "target_range": [0, 10],
                "minimum_verified_sources_basis": "author_requirement",
                "target_range_enforcement": "hadr",
            },
        )
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn(
            "coverage_target_range_enforcement_invalid",
            self.finding_codes(report),
        )

    def test_minimum_without_authoritative_basis_is_incomplete(self) -> None:
        fixture = CitationFixture(
            self.root, coverage_extra={"minimum_verified_sources": 1}
        )
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn(
            "coverage_total_minimum_basis_invalid", self.finding_codes(report)
        )

    def test_unauthorized_nocite_requires_approval(self) -> None:
        fixture = CitationFixture(
            self.root,
            manuscript_text=r"Evidence \cite{Smith2024}. \nocite{InventoryOnly}",
        )
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (2, "approval_required"))
        self.assertIn("nocite_unauthorized", self.finding_codes(report))

    def test_registry_boolean_does_not_authorize_nocite(self) -> None:
        fixture = CitationFixture(
            self.root,
            manuscript_text=r"Evidence \cite{Smith2024}. \nocite{InventoryOnly}",
            registry_entries=[
                {
                    "citekey": "Smith2024",
                    "status": "admitted",
                    "coverage_roles": ["recent_frontier"],
                },
                {
                    "citekey": "InventoryOnly",
                    "status": "admitted",
                    "nocite_authorized": True,
                },
            ],
        )
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (2, "approval_required"))
        self.assertIn("nocite_unauthorized", self.finding_codes(report))

    def test_authorized_nocite_must_be_admitted(self) -> None:
        fixture = CitationFixture(
            self.root,
            coverage_extra={
                "authorized_nocite_keys": ["InventoryOnly", "NeverSeen"]
            },
        )
        code, report = fixture.run("draft")
        self.assertEqual(report["status"], "fail")
        self.assertIn("nocite_authorization_invalid", self.finding_codes(report))

    def test_final_unauthorized_nocite_remains_approval_required(self) -> None:
        fixture = CitationFixture(
            self.root,
            manuscript_text=r"Evidence \cite{Smith2024}. \nocite{InventoryOnly}",
            registry_entries=[
                {
                    "citekey": "Smith2024",
                    "status": "admitted",
                    "coverage_roles": ["recent_frontier"],
                },
                {"citekey": "InventoryOnly", "status": "admitted"},
            ],
            visible_keys=["Smith2024", "InventoryOnly"],
        )
        code, report = fixture.run("final")
        self.assertEqual((code, report["status"]), (2, "approval_required"))
        self.assertIn("nocite_unauthorized", self.finding_codes(report))
        self.assertNotIn(
            "final_bibliography_unreferenced_entries", self.finding_codes(report)
        )

    def test_final_bibliography_extra_entry_fails(self) -> None:
        fixture = CitationFixture(
            self.root, visible_keys=["Smith2024", "InventoryOnly"]
        )
        code, report = fixture.run()
        self.assertEqual(report["status"], "fail")
        self.assertIn(
            "final_bibliography_unreferenced_entries", self.finding_codes(report)
        )

    def test_final_duplicate_bibitem_fails(self) -> None:
        fixture = CitationFixture(
            self.root, visible_keys=["Smith2024", "Smith2024"]
        )
        code, report = fixture.run()
        self.assertEqual(report["status"], "fail")
        self.assertIn(
            "final_bibliography_duplicate_entries", self.finding_codes(report)
        )

    def test_stale_build_attestation_is_incomplete(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.attestation.read_text(encoding="utf-8"))
        payload["expanded_manuscript_sha256"] = "0" * 64
        write_json(fixture.attestation, payload)
        code, report = fixture.run()
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn("build_attestation_stale", self.finding_codes(report))

    def test_stale_qa_manifest_is_incomplete(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.qa_manifest.read_text(encoding="utf-8"))
        payload["expanded_manuscript_sha256"] = "f" * 64
        write_json(fixture.qa_manifest, payload)
        # Keep the ledger binding current so the failure is specifically the QA projection.
        evidence = json.loads(fixture.evidence.read_text(encoding="utf-8"))
        evidence["qa_manifest_sha256"] = auditor.sha256_file(fixture.qa_manifest)
        write_json(fixture.evidence, evidence)
        attestation = json.loads(fixture.attestation.read_text(encoding="utf-8"))
        attestation["qa_manifest_sha256"] = auditor.sha256_file(fixture.qa_manifest)
        write_json(fixture.attestation, attestation)
        code, report = fixture.run()
        self.assertEqual(report["status"], "audit_incomplete")
        self.assertIn("qa_manifest_content_stale", self.finding_codes(report))

    def test_qa_source_paths_are_anchored_at_project_root(self) -> None:
        fixture = CitationFixture(self.root)
        qa_directory = self.root / "qa"
        qa_directory.mkdir()
        payload = json.loads(fixture.qa_manifest.read_text(encoding="utf-8"))
        for record in payload["source_files"]:
            record["path"] = str(
                Path(record["path"]).resolve().relative_to(self.root.resolve())
            )
        fixture.qa_manifest = qa_directory / "qa_manifest.json"
        write_json(fixture.qa_manifest, payload)
        evidence = json.loads(fixture.evidence.read_text(encoding="utf-8"))
        evidence["qa_manifest_sha256"] = auditor.sha256_file(fixture.qa_manifest)
        write_json(fixture.evidence, evidence)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (0, "pass"))

    def test_recursion_error_returns_hashed_unavailable_report(self) -> None:
        fixture = CitationFixture(self.root)
        with mock.patch.object(
            auditor.qa_preparer, "expand_tex", side_effect=RecursionError("too deep")
        ):
            code, report = fixture.run("final")
        self.assertEqual((code, report["status"]), (3, "metric_unavailable"))
        for key in (
            "manuscript",
            "reference_library_manifest",
            "literature_registry",
            "coverage_contract",
            "text_to_evidence_ledger",
            "qa_manifest",
            "visible_bibliography",
            "bibliography_build_attestation",
        ):
            self.assertRegex(report["inputs"][key]["sha256"], r"^[0-9a-f]{64}$")

    def test_evidence_conflict_has_stable_status_and_exit_code(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.evidence.read_text(encoding="utf-8"))
        payload["entries"][0]["status"] = "evidence_conflict"
        write_json(fixture.evidence, payload)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (6, "evidence_conflict"))
        self.assertIn("claim_source_evidence_conflict", self.finding_codes(report))

    def test_unknown_evidence_ledger_status_is_incomplete(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.evidence.read_text(encoding="utf-8"))
        payload["entries"][0]["status"] = "looks_good"
        write_json(fixture.evidence, payload)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn("evidence_ledger_status_invalid", self.finding_codes(report))

    def test_evidence_ledger_schema_is_required(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.evidence.read_text(encoding="utf-8"))
        payload["schema_id"] = "wrong-ledger/1.0"
        write_json(fixture.evidence, payload)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn("schema_id_invalid", self.finding_codes(report))

    def test_evidence_ledger_requires_identity_and_support_fields(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.evidence.read_text(encoding="utf-8"))
        payload.pop("ledger_id")
        payload.pop("ledger_revision")
        for field_name in (
            "claim_id",
            "claim_type",
            "support_role",
            "support_strength",
            "source_locator",
        ):
            payload["entries"][0].pop(field_name)
        write_json(fixture.evidence, payload)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        codes = self.finding_codes(report)
        self.assertIn("evidence_ledger_identity_missing", codes)
        self.assertIn("evidence_ledger_entry_fields_missing", codes)

    def test_known_failing_evidence_ledger_status_blocks(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.evidence.read_text(encoding="utf-8"))
        payload["entries"][0]["status"] = "fail"
        write_json(fixture.evidence, payload)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (1, "fail"))
        self.assertIn("claim_source_ledger_failed", self.finding_codes(report))

    def test_citation_bearing_unit_cannot_be_nonclaim(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.evidence.read_text(encoding="utf-8"))
        payload["entries"][0]["status"] = "non_claim"
        write_json(fixture.evidence, payload)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn("citation_ledger_status_inapplicable", self.finding_codes(report))

    def test_every_unit_citekey_pair_requires_mapping(self) -> None:
        fixture = CitationFixture(self.root)
        qa = json.loads(fixture.qa_manifest.read_text(encoding="utf-8"))
        qa["units"].append(
            {
                "unit_id": "sentence-2",
                "type": "sentence",
                "reader_visible": True,
                "citation_keys": ["Smith2024"],
            }
        )
        write_json(fixture.qa_manifest, qa)
        evidence = json.loads(fixture.evidence.read_text(encoding="utf-8"))
        evidence["qa_manifest_sha256"] = auditor.sha256_file(fixture.qa_manifest)
        write_json(fixture.evidence, evidence)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn(
            "unit_citekey_evidence_mapping_missing", self.finding_codes(report)
        )

    def test_ledger_unit_citekey_mismatch_blocks_delivery(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.evidence.read_text(encoding="utf-8"))
        payload["entries"][0]["citekeys"] = ["InventoryOnly"]
        write_json(fixture.evidence, payload)
        code, report = fixture.run("draft")
        self.assertNotEqual(code, 0)
        self.assertIn(
            "evidence_ledger_unit_citation_mismatch", self.finding_codes(report)
        )

    def test_final_mode_requires_bibliography_and_attestation(self) -> None:
        fixture = CitationFixture(self.root)
        with contextlib.redirect_stdout(io.StringIO()):
            code = auditor.main(
                [
                    "--mode",
                    "final",
                    "--manuscript",
                    str(fixture.manuscript),
                    "--project-root",
                    str(self.root),
                    "--reference-library-manifest",
                    str(fixture.library_manifest),
                    "--literature-registry",
                    str(fixture.registry),
                    "--coverage-contract",
                    str(fixture.coverage),
                    "--text-to-evidence-ledger",
                    str(fixture.evidence),
                    "--qa-manifest",
                    str(fixture.qa_manifest),
                    "--report",
                    str(fixture.report),
                ]
            )
        report = json.loads(fixture.report.read_text(encoding="utf-8"))
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn("visible_bibliography_missing", self.finding_codes(report))
        self.assertIn(
            "bibliography_build_attestation_missing", self.finding_codes(report)
        )

    def test_coverage_hashes_are_required(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.coverage.read_text(encoding="utf-8"))
        payload.pop("reference_library_manifest_sha256")
        payload.pop("literature_registry_sha256")
        write_json(fixture.coverage, payload)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn("coverage_library_manifest_hash_missing", self.finding_codes(report))
        self.assertIn("coverage_registry_hash_missing", self.finding_codes(report))

    def test_conflicting_hash_aliases_fail_closed(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.coverage.read_text(encoding="utf-8"))
        payload["library_manifest_sha256"] = "0" * 64
        payload["registry_sha256"] = "1" * 64
        write_json(fixture.coverage, payload)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn(
            "coverage_library_manifest_hash_alias_conflict",
            self.finding_codes(report),
        )
        self.assertIn(
            "coverage_registry_hash_alias_conflict", self.finding_codes(report)
        )

    def test_duplicate_coverage_cluster_fails(self) -> None:
        duplicate = {
            "cluster_id": "recent_frontier",
            "function": "recent_frontier",
            "applicable": True,
            "rationale": "Current frontier is applicable.",
            "gap_disposition": "resolved",
            "minimum_verified_sources": 1,
        }
        fixture = CitationFixture(
            self.root,
            clusters=complete_coverage_clusters(duplicate) + [dict(duplicate)],
        )
        code, report = fixture.run("draft")
        self.assertEqual(report["status"], "fail")
        self.assertIn("coverage_cluster_duplicate", self.finding_codes(report))

    def test_empty_coverage_cluster_universe_is_incomplete(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.coverage.read_text(encoding="utf-8"))
        payload["coverage_clusters"] = []
        write_json(fixture.coverage, payload)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn(
            "coverage_cluster_universe_missing", self.finding_codes(report)
        )

    def test_omitted_standard_coverage_function_is_incomplete(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.coverage.read_text(encoding="utf-8"))
        payload["coverage_clusters"] = [
            record
            for record in payload["coverage_clusters"]
            if record["function"] != "contrary_evidence_alternative_explanation"
        ]
        write_json(fixture.coverage, payload)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn(
            "coverage_cluster_function_declarations_missing",
            self.finding_codes(report),
        )

    def test_coverage_contract_requires_identity_and_approval(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.coverage.read_text(encoding="utf-8"))
        payload.pop("contract_id")
        payload.pop("approval_record")
        write_json(fixture.coverage, payload)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        self.assertIn("authority_identity_missing", self.finding_codes(report))
        self.assertIn("coverage_approval_missing", self.finding_codes(report))

    def test_coverage_contract_requires_recoverable_search_scope(self) -> None:
        fixture = CitationFixture(self.root)
        payload = json.loads(fixture.coverage.read_text(encoding="utf-8"))
        payload["search_scope"] = {"languages": ["English"]}
        payload.pop("unresolved_gaps")
        write_json(fixture.coverage, payload)
        code, report = fixture.run("draft")
        self.assertEqual((code, report["status"]), (4, "audit_incomplete"))
        codes = self.finding_codes(report)
        self.assertIn("coverage_search_scope_fields_missing", codes)
        self.assertIn("coverage_end_date_invalid", codes)
        self.assertIn("coverage_unresolved_gaps_registry_missing", codes)

    def test_repeated_run_is_deterministic(self) -> None:
        fixture = CitationFixture(self.root)
        _, first = fixture.run()
        _, second = fixture.run()
        self.assertEqual(first, second)
        self.assertEqual(
            first["hashes"]["audit_payload_sha256"],
            second["hashes"]["audit_payload_sha256"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
