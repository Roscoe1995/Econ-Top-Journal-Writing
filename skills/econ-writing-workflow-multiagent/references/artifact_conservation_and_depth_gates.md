# Artifact Conservation And Depth Gates

## Contents

- Core invariants
- Authority and task classification
- Artifact contract
- Safe defaults and approval gates
- Main-text sufficiency
- Conservation ledger
- Section budgets
- Two-pass restructuring
- Deterministic audit and recovery

## Core Invariants

- `context budget != manuscript budget`: treat context, QA-packet, and handoff
  compression as coordination tools, never as permission to shorten the
  reader-facing manuscript.
- For an accepted mature manuscript, default to `patch_existing` or
  `reorder_existing_blocks`. Use `full_redraft` only when the author explicitly
  authorizes it for the recorded scope. If the controller believes the source
  is unusable, stop and request that authorization; do not self-authorize a
  clean-slate rewrite.
- Preserve substantive main-text coverage and the accepted artifact budget unless a higher-priority constraint authorizes a shorter output.
- Treat word and page counts as guardrails, not measures of writing quality. Do not pad a manuscript to satisfy a threshold.

## Authority And Task Classification

Apply artifact constraints in this order:

1. explicit user instruction;
2. the nearest project instructions;
3. verified journal or format requirements;
4. the user-accepted baseline manuscript;
5. conditional skill defaults.

Classify `task_mode` as `full_draft`, `major_revision`, `restructure`,
`shorten`, `local_edit`, or `document_translation` (`translation` is a
compatibility alias only). Treat a manuscript as mature when it has a
user-accepted multi-section draft whose content and architecture are revision
inputs rather than disposable notes. `mature_baseline` must be an explicit
boolean. If maturity is unknown, do not encode `unknown`; stop with
`metric_unavailable` and resolve it before auditing.

Map the semantic-QA `task_stage` to this artifact mode deterministically:

```text
full_draft             -> full_draft
proposal_draft         -> full_draft
document_translation   -> document_translation
document_compression   -> shorten
major_revision         -> major_revision
major_restructure      -> restructure
local_edit             -> local_edit
local_polish           -> local_edit, when conservation applies
final_audit             -> task_classification.artifact_task_mode, which must equal the artifact contract
```

Do not invent a second mode for the same run. In particular,
`proposal_draft` is a semantic-QA stage, not an artifact-contract `task_mode`.
For `final_audit`, record the underlying artifact mode in the hash-bound QA
task classification; do not let the generic final-audit label bypass the
translation, shortening, restructuring, or baseline rules of that artifact.

## Artifact Contract

Keep the authoritative contract in `paper_state` or a durable project artifact. Use this schema and omit only fields that are genuinely inapplicable:

```text
artifact_contract:
  task_mode: full_draft | major_revision | restructure | shorten | local_edit | document_translation
  rewrite_mode: patch_existing | reorder_existing_blocks | full_redraft
  mature_baseline: true | false
  source_language:  # required for document_translation
  target_language:  # required for document_translation
  target_journal_or_style:
  inherited_project_constraints:
  baseline_artifact:
    path:
    sha256:
    expanded_sha256:  # required for a multi-source TeX baseline
    source_files:  # exact path/SHA-256 manifest; required for a multi-source baseline
    acceptance_status: accepted | author_accepted | confirmed | frozen_current
    accepted_by:
  measurement_contract:
    appendix_boundary:
    source_word_method:
    cross_language_length_metric: inapplicable | target_language_budget_only  # translation only
    include_resolution_mode:
    pdf_main_page_method:
    measured_by:
    measured_at:  # ISO-8601 with timezone
    attested_main_text_pages:  # required whenever any page constraint is active
      baseline:  # required when a baseline is audited
        pages:
        pdf_path:
        pdf_sha256:
      candidate:
        pages:
        pdf_path:
        pdf_sha256:
  baseline_main_source_words:
  baseline_main_pdf_pages:
  target_main_source_word_range:
  target_language_main_source_word_range:  # canonical translation budget when one is active
  target_main_pdf_page_range:
  hard_main_text_floor:
    source_words:
    pdf_pages:
  max_unapproved_main_reduction_pct:
  must_remain_main:
  allowed_appendix_moves:
  user_approved_compression: true | false
  appendix_dependency_tolerance:
  target_basis: user | project_rule | verified_journal | accepted_baseline | default
  content_obligations:
  section_cards:
    - card_id:
      section_name:  # candidate-only full_draft; legacy unique-name selector
      baseline_section_id:  # mature draft; exact live ID preferred
      baseline_section_name:
      candidate_section_id:  # optional when the validated ledger gives one exact destination
      candidate_section_name:
      optional: false
      baseline_words:
      target_word_range:
      maximum_reduction_pct:
      minimum_depth_questions:
      must_remain_main:
      allowed_appendix_moves:
      rewrite_mode:
      ledger_slice:  # only when one baseline section is split across cards
        baseline_block_ids:
        destination_block_ids:  # optional declaration; must exactly equal validated ledger destinations
  approval_record:
    approval_authority: author | recorded_human_delegate
    approved_by:
    approved_scope:
    approved_at:  # ISO-8601 with timezone
    approval_source:  # recoverable author message or decision artifact
  metric_status: measured | unavailable | ambiguous
```

Legacy artifact records may use `frozen-ready` or `frozen_ready` as
compatibility aliases for `frozen_current`; normalize them when the contract is
next revised. These aliases describe acceptance of a manuscript baseline only.
They are not the author-intent `frozen-current + ready` gate and cannot supply
missing author confirmation or drafting authority.

`metric_status` is mandatory. Only `measured` may proceed to a conservation
decision. `unavailable`, `ambiguous`, a missing value, or an unknown value
returns `metric_unavailable`; it cannot be inferred from plausible-looking
numbers in another artifact. Every measured contract must also record a
`measurement_contract` object with an explicit `appendix_boundary` and
`source_word_method` (`raw_source_words` or `normalized_words`); the auditor
must not obtain either authority from a CLI flag or implicit default. Do not
silently change the baseline or
measurement method during a revision. Do not treat an unavailable baseline as
zero or as automatic approval.

When a baseline is present, `baseline_main_source_words` is mandatory and must
equal the auditor's live pre-appendix measurement under
`measurement_contract.source_word_method`; a copied, rounded, or stale value
fails closed. If any PDF-page target, floor, or reduction check is active,
`baseline_main_pdf_pages` is also mandatory and must equal the hash-verified
baseline entry in `attested_main_text_pages`. Never use total PDF pages as a
substitute for main-text pages before the appendix. In document translation,
keep the source-baseline measurement as provenance, but do not calculate a
cross-language reduction percentage when
`cross_language_length_metric: inapplicable`.

`full_draft` is the only artifact mode that may be candidate-only. Every other
mode—including `document_translation`/`translation` and an artifact-applicable
`local_edit`—requires a live accepted baseline, exact binding, and conservation
ledger. A bounded local task may omit the artifact contract only when artifact
conservation genuinely does not apply; once a local artifact contract is
supplied, it cannot omit its baseline.

When any PDF-page input, page target, or page floor is active, the page
attestation is mandatory. `pdf_main_page_method` must explicitly measure the
main text or pages before the appendix; `appendix_boundary` must equal the
auditor's marker. Each required attestation binds a positive page count to the
exact live PDF path and SHA-256. Never write or accept `total_pdf_pages` as a
main-text measurement.

Keep this artifact contract distinct from the stable workflow's authoritative
author-intent contract and the exhaustive semantic `qa_contract`. The former
fixes intended meaning; this contract fixes artifact length, placement, depth,
and baseline conservation; the QA contract fixes review scope, hashes, roles,
and coverage. All applicable contracts must pass. None authorizes a silent
change to another.

For deterministic audits, express `must_remain_main` entries as a section
title, a label, or `{type: section | label | obligation | intent, value: ...}`.
Express `allowed_appendix_moves` as approved section titles or labels. Keep
`approval_record.approved_scope` narrow, using entries such as `compression`,
`move_appendix:<title-or-label>`, `delete:<title>`, or `full_redraft`; do not use
`all` unless the user explicitly authorizes that entire scope. A bare
`user_approved_compression: true` is not authority by itself: it must be backed
by the complete approval record above.

Bind `baseline_artifact.path` to the exact audited root source and its raw
SHA-256. When the baseline expands more than one TeX source, also bind the
expanded-content SHA-256 and the complete live `source_files` path/hash
manifest. `version_or_hash` and `hash` remain input aliases for old records,
but new contracts should write `sha256`. Mutating an included baseline file
must therefore invalidate the contract even when the root file is unchanged.

## Safe Defaults And Approval Gates

For a mature baseline with `task_mode` equal to `major_revision` or `restructure`, and no explicit shorter target:

- default to `rewrite_mode: patch_existing`;
- allow `reorder_existing_blocks` during an architecture pass;
- set `max_unapproved_main_reduction_pct` to `0.15`;
- require approval before `full_redraft`;
- require approval before deleting a substantive section or moving central data construction, sample audit, identification/model environment, main results, or core robustness discussion to the appendix.

Treat the 15 percent value as an approval trigger for cumulative net main-text reduction, not a universal target or quality rule. Apply section-deletion and core-object gates even when the total reduction remains below 15 percent.

For a new draft without a baseline, freeze a paper-wide target range, section
target ranges, content obligations, and minimum explanation-depth questions
before drafting. Do not treat zero as the baseline or transfer the mature-draft
15 percent rule to a new artifact.

For document-level translation, map every substantive source block and intent
to the translated candidate, but do not compare raw source-language and
target-language word counts as if they were one length metric. Use an explicit
target-language range or mark that cross-language metric inapplicable while
retaining block, obligation, definition, and semantic-conservation gates.

When the user requests a short paper, note, letter, or verified capped format, record the shorter target and approval scope in the contract. Let that explicit contract override the conditional 15 percent default. Never impose a universal 30-page floor; inherit a page floor only from the user, project, or verified format requirement.

An explicitly authorized 15-page paper may therefore pass. It still must meet
its frozen content obligations, definition and reader-sufficiency requirements,
and target-specific artifact contract; short authorization does not waive
semantic QA.

## Main-Text Sufficiency

Require the main text to let a reader answer, without reconstructing the paper from the appendix:

1. What are the research question and contribution?
2. What data, sample, or model environment is used?
3. How is the central object measured or defined?
4. What comparison, accounting map, identification, or mechanism produces the result?
5. What are the main magnitude and benchmark?
6. What are the central threats, robustness results, and sample limitations?
7. Which claims are descriptive, causal, calibrated, conditional, or scenarios?

Allow proofs, supplementary derivations, secondary definitions, extended robustness, and validation detail in the appendix when the main text retains the assumptions, mechanism, proposition interpretation, evidence function, and limitations needed for those answers.

## Conservation Ledger

Maintain the complete ledger outside agent prompts. Give each role only the slice it needs.

```text
source_block_id:
source_function:
disposition: unchanged | revised | reordered | merged | moved_appendix | deleted
destination:
main_text_replacement_or_summary:
reason:
approval_required:
approval_status:
```

Assign stable block IDs before restructuring. Map every old substantive block to a disposition. Do not accept “still exists in the appendix” unless the ledger identifies what explanation remains in the main text. Require controller approval for merges or renames that prevent deterministic title matching.

This ledger is the `baseline -> candidate` direction of the four-way QA ledger.
Keep it linked to, but distinct from, `intent -> text`, `text -> intent`, and
`text -> evidence`. A block's continued existence does not prove that its
meaning, evidence strength, or definition survived; semantic reviewers check
those directions separately.

## Section Budgets

Use `artifact_contract.section_cards` as the canonical field; do not maintain a
parallel `section_budgets` object. Add these fields to every mature-draft
section card:

Do not maintain a second `qa_contract.section_cards`, top-level
`paper_state.section_cards`, or author-contract section-card body once an
artifact contract applies. A legacy parallel projection is acceptable only
when it is canonically identical to `artifact_contract.section_cards`; a
missing canonical body alongside a parallel projection, or any disagreement,
blocks packet preparation.

```text
card_id:
baseline_section_id:
baseline_section_name:
candidate_section_id:
candidate_section_name:
baseline_words:
target_word_range:
maximum_reduction_pct:
minimum_depth_questions:
must_remain_main:
allowed_appendix_moves:
rewrite_mode:
ledger_slice:
  baseline_block_ids:
  destination_block_ids:
```

Use `card_id` as the card identity. `section_id` is accepted only as a legacy
alias for that card ID and, when both appear, must equal `card_id`; it is never
a baseline or candidate manuscript selector. For a mature draft, select the
live sections with `baseline_section_id` and, when recorded,
`candidate_section_id`. A unique exact name may be used as a fallback, but a
duplicate title requires the exact live ID. Any explicit candidate selector
must equal the candidate section reached by the validated conservation ledger;
a same-name stub cannot satisfy the card.

Normally use one whole-section card per baseline section. If a baseline
section is split across cards, every card must carry a closed `ledger_slice`
of live baseline prose-block IDs. The slices must be nonoverlapping and jointly
cover every live prose block in that baseline section; do not mix sliced and
whole-section cards. When `destination_block_ids` is present it must exactly
equal the validated ledger destinations. Candidate destinations must be
measurable and uniquely attributable; a destination block shared by multiple
cards, or a split/merge that cannot be charged without double counting, fails
closed. Equations, propositions, tables, and figures remain covered by the
full conservation ledger and semantic QA, but are not valid prose-word slice
IDs.

Bind `baseline_words` to the live contract word metric. In same-language work,
require and enforce both `target_word_range` and
`maximum_reduction_pct`. For translation with
`cross_language_length_metric: inapplicable`, retain the source measurement
and ledger binding but do not enforce a cross-language section target or
reduction percentage. With `target_language_budget_only`, enforce the
candidate target-language range but still do not compute source-to-target
reduction.

Every mature card must also carry nonempty `minimum_depth_questions` and
`must_remain_main`; the fifth role reviews the questions and the deterministic
gate verifies that each referenced section, label, intent, or obligation exists
in the candidate/main contract registry. Card-level
`allowed_appendix_moves` and `rewrite_mode` are optional narrow overrides. If
omitted, they inherit the artifact-wide fields; if supplied, they may only
narrow that authority and never authorize a move, deletion, or redraft that the
top-level contract and ledger do not permit.

The deterministic gate applies the effective card authority to the validated
ledger rather than merely reporting it. A `moved_appendix` disposition must be
allowed by that card's effective section-title or label set and must still have
the separate action-specific author approval required by the ledger. Under
`patch_existing`, the relative order of baseline-main blocks that remain mapped
to candidate main text must be conserved; new unmapped insertions do not count
as reordering. Only `reorder_existing_blocks` or an approved `full_redraft`
permits those mapped blocks to change relative order.

Use ranges and substantive questions rather than mechanical quotas. Return
large deviations to the controller before integration. Do not assume another
section preserves an omitted object without a verified destination in the
section map and ledger.

For a candidate-only `full_draft`—including a semantic `proposal_draft` mapped
to artifact mode `full_draft`—the deterministic gate additionally requires a
nonempty `content_obligations` registry and one section card for every
reader-visible main-text section. Each non-optional card must name the section,
provide a valid nonnegative `target_word_range`, at least one
`minimum_depth_questions` item, and a nonempty `must_remain_main` reference to a
section, label, intent, or obligation. It also requires either a manuscript-wide
source-word target range or a verified main-text page target. These checks prove
contract completeness and reference existence; the independent sufficiency
role still decides whether the resulting explanation is adequate.

## Two-Pass Restructuring

For major restructuring:

1. Run an architecture pass that reorders the complete accepted material and edits only transitions, duplicated signposting, and changes needed to make moved blocks coherent.
2. Measure and audit the complete reordered manuscript.
3. Run a separate compression pass that removes genuine duplication within the artifact contract.

Do not combine clean-slate rewriting, block relocation, table/figure migration, and diction compression in one pass.

Use `two_pass_restructure` as the one canonical machine record. Do not also
require `restructure_phase` or `major_restructure_sequence`:

```text
two_pass_restructure:
  architecture_pass:
    status: completed | pass
    mode: reorder_existing_blocks
    artifact_path:
    artifact_sha256:  # raw architecture artifact bytes
    expanded_sha256:
    completed_by:
    completed_at:  # ISO-8601 with timezone
    content_conservation_ledger:  # accepted baseline -> architecture artifact
  compression_pass:
    status: not_needed | completed | pass
    mode: none | limited_compression
    source_expanded_sha256:  # equals architecture_pass.expanded_sha256
    candidate_expanded_sha256:
    completed_by:
    completed_at:  # ISO-8601 with timezone
    approved_scope:  # required for limited_compression
    content_conservation_ledger:  # architecture artifact -> candidate; required for limited_compression
```

The architecture ledger may preserve, rename, or reorder only content that is
byte/normalized-content conserved under the deterministic auditor. The
compression ledger is a second, independent mapping. The audit report returns
their canonical JSON hashes; consumers must validate the report, not recreate a
parallel two-pass schema.

## Deterministic Audit And Recovery

Run `scripts/audit_manuscript_conservation.py` after architecture integration,
after compression integration, and again after diction and post-diction
semantic re-review before finalization. Interpret its statuses as follows:

```bash
python scripts/audit_manuscript_conservation.py \
  --baseline baseline.tex \
  --candidate candidate.tex \
  --project-root /path/to/project \
  --contract artifact_contract.json \
  --report conservation_audit.json
```

Use `--baseline-main-pdf-pages` and `--candidate-main-pdf-pages` only for page counts measured with an explicit appendix boundary. Never substitute total PDF pages. Bind `--appendix-marker`, `--word-metric`, `--max-main-reduction`, and hard-floor flags to the recorded measurement contract under the non-weakening rule below. Require exactly one uncommented appendix marker in each expanded source; otherwise treat the metric as unavailable.

CLI options cannot weaken the frozen contract. `--word-metric` must equal a
recorded `source_word_method`; a CLI source-word or PDF-page floor may only
raise the corresponding contract floor; and `--max-main-reduction` may only
lower the contract's permitted reduction. A conflicting weaker override is a
deterministic failure, even if replay would otherwise reproduce it.

Every report records those optional decisions in the canonical
`audit_arguments` object. The final QA validator must invoke the same shipped
auditor against the live baseline, candidate, project root, and artifact
contract with exactly those arguments, then compare the canonical report
projection. A self-consistent or correctly hash-bound JSON report is not proof
that the audit ran: missing or unknown replay arguments, source-derived metric
differences, or any material replay mismatch fail closed as `audit_incomplete`.

- `pass`: this conservation gate is satisfied; record it as
  `gate_local_status: pass`, not as a manuscript-wide delivery decision. Still run the independent
  Main-Text Sufficiency and Conservation Role at the final stage.
- `approval_required`: preserve or restore material, or obtain and record user approval before continuing.
- `fail`: restore missing or under-floor material before diction or finalization.
- `metric_unavailable`: repair the baseline, appendix boundary, include graph, or page measurement; do not treat the result as a pass.

Treat exit codes `0`, `1`, `2`, and `3` as `pass`, `fail`, `approval_required`, and `metric_unavailable`, respectively. Read the JSON report rather than inferring status from console wording.

Keep private manuscripts and copyrighted fixtures local. Commit only synthetic tests. If a candidate fails, restore baseline blocks or revise the contract through the authority order; never change the baseline merely to make the audit pass.
