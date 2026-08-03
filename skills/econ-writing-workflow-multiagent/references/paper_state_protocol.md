# Paper State Protocol

## Purpose

Use `paper_state` as the integration index and single source of truth for a
large economics writing project. Every agent or staged role must read it before
working and must report any proposed change to it. The stable workflow's
authoritative author-intent contract remains a separately governed authority;
`paper_state` points to its exact current revision and hash rather than copying
or replacing it.

## When To Create

Create or update `paper_state` when the task involves:

- a full paper draft;
- many tables or figures;
- multiple sections;
- a major revision;
- bilingual writing;
- referee comments;
- long context that may exceed what one agent can reliably track.

For small polishing tasks, do not create a full paper state unless the user asks.

## Required Fields

```text
project_title:
target_language:
target_journal_or_style:
author_intent_contract:
  authoritative_path_or_artifact_id:
  intent_contract_id:
  intent_revision_id:
  intent_status:
  gate_status:
  sha256:
content_obligations:
definition_registry:
qa_contract:
  task_classification:
research_question:
main_contribution:
secondary_contributions:
theory_or_mechanism:
data_sources:
sample_scope:
period:
unit_of_observation:
key_variables:
identification_or_model:
main_tables:
main_figures:
main_results_and_magnitudes:
mechanism_results:
heterogeneity_results:
robustness_results:
literature_positioning:
scope_conditions_and_caveats:
caveat_placement_registry:  # optional derived placement/de-duplication index; never a second intent authority
  status: not_required | pending_candidate | current | stale
  path:
  sha256:
  author_intent_revision_id:
  author_intent_sha256:
  manuscript_sha256:
literature_coverage:  # required only when the literature audit trigger applies
  trigger_status:
  coverage_contract:
    path:
    sha256:
  reference_library_manifest:
    path:
    sha256:
  literature_registry:
    path:
    sha256:
  citation_integrity_report:
    status: not_triggered | pending_candidate | current | stale | blocking_status
    path:
    sha256:
  literature_audit_assignment:
    status: not_triggered | pending_candidate | assigned | stale | blocking_status
    schema_id: literature-audit-assignment/1.0
    path:
    sha256:
    assignment_id:
    core_qa_assignment_registry_sha256:
  bibliography_build_attestation:  # required in final mode
    schema_id: bibliography-build-attestation/1.0
    status: not_triggered | pending_build | current | stale | blocking_status
    path:
    sha256:
  visible_bibliography:  # final mode
    path:
    sha256:
  literature_role_audit:
    status: not_triggered | pending_candidate | current | stale | blocking_status
    path:
    sha256:
    gate_status:
  literature_acceptance_validation:
    status: not_triggered | pending_candidate | current | stale | blocking_status
    schema_id: literature-audit-validation/1.0
    path:
    sha256:
    gate_local_status:
artifact_contract:
  section_cards:  # canonical length/depth records; do not duplicate as section_budgets
  content_obligations:
content_conservation_ledger:
intent_to_text_ledger:
text_to_intent_ledger:
text_to_evidence_ledger:
cannot_invent:
open_todos:  # non-semantic facts only
blocking_statuses:
last_updated_by:
```

## Authority Rules

- Claim-bearing drafting is forbidden unless the author-intent pointer resolves
  to the exact requested scope, its hash is current, and its state is
  `frozen-current + ready`. An explicit confirmation of a complete teach-back
  normally supplies confirmation and freeze authorization in one event. Do not
  create a `partial`, compatibility, or provisional drafting path.
- When a separate author-intent file is used, the pointer's contract ID,
  revision ID, status, gate, SHA-256, and authoritative path or stable contract
  ID must all match that live authority. A stale revision or correct-looking
  status paired with another file fails closed. A legacy combined paper-state
  file may embed the exact complete contract object instead of a separate
  pointer; it may not embed a conflicting or partial projection.
- Keep content obligations and definition entries traceable to frozen intent
  IDs. A new substantive obligation or definition meaning requires author-intent
  change control, not an unlogged paper-state edit.
- A paper-state supplement must cite an existing author-owned obligation,
  intent, or definition ID and may add only non-conflicting metadata. It cannot
  mint a new semantic ID for the QA pipeline.
- If `paper_state` conflicts with a draft paragraph, table note, or agent output, pause and flag the conflict.
- If an agent infers a fact from supplied materials, label it as `inferred` until confirmed.
- If a needed non-semantic fact is missing, write a concrete `TODO` rather than smoothing over the gap. If the gap changes intended meaning or the evidence ceiling, return `clarification_required` or `evidence_conflict` and withhold the affected prose.
- If user instructions update the paper facts, update `paper_state` before editing prose.
- Treat user, project, verified-journal, and accepted-baseline artifact constraints as paper-state authority rather than optional style preferences.
- Fix the accepted baseline path or hash and the measurement contract before recording cumulative changes. Never replace the baseline merely because a candidate fails.
- Keep the complete conservation ledger in a durable JSON or Markdown artifact. Put only the relevant ledger slice in a role handoff.
- Record `metric_status: unavailable` or `ambiguous` and pause artifact-sensitive work when required measurements cannot be reproduced.
- Do not use `paper_state` to store long source excerpts, paper PDFs, or copyrighted text.
- Keep the complete four-way ledgers durable and separately inspectable:
  `intent -> text`, `text -> intent`, `text -> evidence`, and, when a baseline
  exists, `baseline -> candidate`. Reuse `content_conservation_ledger` for the
  fourth direction; do not maintain two baseline ledgers.
- Bind every QA manifest and finding set to the manuscript, intent-contract,
  QA-contract, and applicable artifact-contract hashes. A stale hash invalidates
  the result.
- Evidence beyond anchors already frozen in the author contract must come from
  a live, hash-bound `evidence-registry/1.0` named by
  `qa_contract.evidence_registry_source`; paper state and manifests may project
  its IDs but may not invent or override that authority.
- Treat `caveat_placement_registry` as an optional presentation and
  de-duplication index derived after a candidate draft exists. Before then,
  record only `pending_candidate`; do not fabricate unit IDs. Bind a current
  registry to the live manuscript hash and authoritative author-intent
  revision/hash. Every entry uses the canonical `caveat_id`, `intent_id`,
  optional `content_obligation_ids`, `first_required_location`,
  `satisfied_by_unit_ids`, and `permitted_repeat_triggers` fields. Every listed
  obligation must trace to that intent. Rebuild it whenever manuscript unit IDs
  change. It cannot weaken or create an evidence boundary or
  mutate the frozen author contract. A calibrated verb or claim type may
  satisfy the intent without a standalone disclaimer; deleting no-information
  repeated wording does not erase the governing intent.
- When the literature trigger applies, resolve all three literature authority
  pointers to the live `literature-coverage-contract/1.0`,
  `reference-library-manifest/1.0`, and `literature-registry/1.0` objects. The
  library manifest alone owns bibliographic metadata; the registry owns
  candidate/inspected/admitted/rejected/superseded status; the existing
  `text_to_evidence_ledger` owns claim and unit links and must include citekeys
  and reader-visible unit IDs; the final visible bibliography is derived from
  manuscript citekeys plus authorized `nocite` entries.
  The coverage contract must explicitly declare each standard functional
  cluster as applicable or inapplicable and bind the current library-manifest
  and registry hashes; an empty or partial declaration is
  `audit_incomplete`. In final mode, also keep a current
  `bibliography-build-attestation/1.0` pointer before accepting the visible
  bibliography.
- Keep literature audit state outside `qa_contract.required_roles` and the
  five-role assignment registry. Pre-register a separate, hash-bound
  `literature-audit-assignment/1.0` so the native reviewer identity, task,
  independence, dispatch time, and exact inputs remain auditable without
  changing the core assignment schema. Missing or stale assignment/output is
  `audit_incomplete`; coverage gaps are `fail`; unsupported claims are
  `evidence_conflict`; unauthorized `nocite` is `approval_required`; and
  unmeasurable formats are `metric_unavailable`. Any manuscript byte change
  makes the prior deterministic report and role output stale. Do not set
  literature status to pass from controller judgment alone.

## QA State

Use the field definitions and unit requirements in
`exhaustive_semantic_qa_protocol.md`. At minimum record:

```text
qa_contract:
  schema_version:
  qa_mode: exhaustive | bounded_change
  task_classification:
    task_stage: full_draft | proposal_draft | document_translation | document_compression | major_revision | major_restructure | final_audit | local_edit | local_polish
    qa_mode:
    artifact_task_mode:  # required for final_audit and equal to artifact_contract.task_mode
    basis:
    changed_artifact_or_source_ranges:
    substantive_dependencies_checked:
    affected_intent_ids:
    classified_by:
    classified_at:
  revision_scope:
    affected_intent_ids:
  manuscript_path:
  required_roles:
  minimum_high_risk_independent_reviews: 2  # v1 canonical integer, 2 through 4
  unit_scope:
  accepted_export_limitations:
  evidence_registry_source:
    path:
    sha256:
qa_hashes:  # post-prepare write-back, never a pre-prepare authority
  manuscript_sha256:
  author_intent_contract_sha256:
  qa_contract_sha256:
  artifact_contract_sha256:
  qa_bundle_sha256:
qa_status:
  manifest_path:
  manifest_id:
  manifest_hash:
  findings_paths:
  validation_report_path:
  gate_status: pass | clarification_required | evidence_conflict | approval_required | fail | metric_unavailable | audit_incomplete
  reviewed_manuscript_sha256:
  unresolved_finding_ids:
```

Do not pre-populate `qa_hashes` as an input requirement. Before packet
preparation, retain the live source paths, stable IDs, revisions, statuses, and
approval records needed to resolve each authority. The preparer computes this
block only after rereading the live bytes and generating the canonical
manifest; the validator then recomputes the same projections. Existing hashes
belong to an earlier run until that replay proves otherwise and must not be
used to bless changed manuscript or contract bytes.

Do not set `gate_status: pass` from controller judgment alone. It requires a
valid deterministic report plus all mandatory native independent semantic
reviews and any patch or post-diction re-review.
The first seven task stages require `exhaustive`; only `local_edit` and
`local_polish` permit `bounded_change`. `qa_mode` may not be omitted or
defaulted. For bounded work, record the same nonempty `affected_intent_ids`
list in the classification and revision scope and re-audit every listed frozen
intent.

## Minimal Paper State

If inputs are sparse, use this reduced form:

```text
research_question:
main_contribution:
author_intent_contract_pointer:
author_intent_gate_status:
data_or_model:
main_results:
mechanism:
tables_figures_available:
missing_information:
do_not_invent:
```
