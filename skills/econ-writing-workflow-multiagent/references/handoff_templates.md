# Handoff Templates

## Contents

- Delegation and return
- Drafting and table/figure handoffs
- Section-functional collaboration
- Semantic QA review and bounded repair
- Conservation audit
- Conflict handoff

## Delegation Template

Use this when assigning work to a sub-agent or staged role.

```text
Role:
Task:
Inputs to read:
Paper_state fields to respect:
Author-intent revision and hash:
Content obligations and definition entries:
Artifact contract and ledger slice:
Allowed changes:
Forbidden changes:
Questions to answer:
Expected output format:
Maximum scope:
```

## Return Template

Every role should return structured output, not a loose essay.

```text
Role:
Inputs read:
Claims used:
Findings:
Recommended changes:
Must preserve:
Words before/after:
Blocks revised, reordered, merged, moved, or omitted:
Conservation-ledger updates:
Main-text self-containment check:
Approval needed:
Conflicts with paper_state:
Missing information:  # non-semantic TODO facts only
Blocking statuses:
Output for next role:
```

## Drafting Handoff

Use this before drafting a section.

```text
Section:
Target language:
Reader-facing purpose:
Paper_state facts to use:
Tables/figures to cite:
Claims to preserve:
Caveats to preserve:
Rewrite mode:
Baseline and target length:
Must remain in main text:
Permitted appendix moves:
Cumulative main-text reduction before this task:
Ledger slice:
Do not mention:
Non-semantic TODO items to leave author-visible:
Intent IDs and content obligations:
Definition dependencies:
```

## Table/Figure Handoff

Use this for result packages.

```text
Table/Figure item:
Proposed function:
Main text or appendix:
Evidence for main claim:
Needed note/caption elements:
Risks or ambiguity:
Follow-up needed:
```

## Section-To-Functional Handoff

Use this when a section agent needs a functional agent review.

```text
Requesting section:
Section claim:
Functional role needed:
Question:
Evidence or text to review:
Decision needed:
Current section card fields:
```

## Functional-To-Section Return

Use this when a functional agent returns a bounded decision.

```text
Functional role:
Inputs read:
Answer:
Recommended section card update:
Recommended paper_state update:
Risks:
Needs user confirmation:
```

## Conservation Audit Handoff

Use this for the final Main-Text Sufficiency and Conservation Role after
post-diction semantic re-review. For an interim pre-diction conservation run,
record the deterministic status and recovery decision but do not mistake it for
the final whole-manuscript sufficiency pass. Use only for `exhaustive` QA; a
bounded change cannot claim whole-manuscript sufficiency.

```text
Accepted baseline:
Candidate manuscript:
Artifact contract:
Manifest ID and SHA-256:
Candidate and expanded-content SHA-256:
Author-intent and QA-contract SHA-256:
Filled assignment-registry SHA-256 and fifth-role assignment ID:
Reviewer native-agent and task IDs:
Conservation-report SHA-256:
Measurement contract:
Cumulative dashboard:
Conservation ledger:
Deterministic report:
Questions for semantic sufficiency review:
```

Require the exact `main-text-sufficiency-audit/1.0` result defined in
`exhaustive_semantic_qa_protocol.md`, including all hash and assignment
bindings, the fixed eight-check checklist, and typed findings. Its human-facing
summary is:

```text
Deterministic status:
Missing main-text functions:
Unjustified appendix dependencies:
Unmapped source blocks:
Sections below budget:
Cumulative reduction:
Recovery required:
Approval required:
Gate decision: pass | approval_required | fail | metric_unavailable
```

A pass has all eight checks true and no findings. A non-pass retains every
typed blocker and has at least one false check; its overall status follows the
fail-closed priority rather than discarding simultaneous findings.

## Semantic QA Review Handoff

Use only packets produced from the current deterministic manifest. First-pass
reviewers must not receive another reviewer's verdict or the controller's
preferred repair.

```text
Reviewer role:
Reviewer ID and independence key:
Assignment registry path and SHA-256:
Assignment ID, native agent ID, and task ID:
Manifest path, ID, and SHA-256:
Manuscript SHA-256:
Expanded content SHA-256:
Author-intent contract path, revision, and hash:
QA-contract path and SHA-256:
Artifact-contract path and SHA-256:
QA-bundle SHA-256:
Unit IDs and exact source spans:
Full paragraph and necessary adjacent context:
Frozen intent and content-obligation slice:
Definition-registry slice:
Evidence anchors:
Section-card fields:
Criteria to review:
Forbidden action: do not edit manuscript or state
Required finding schema:
```

Require one result object, with a unit-review record for every assigned unit and
applicable criterion:

```text
schema_version:
result_id:
manifest_id:
manifest_sha256:
manuscript_sha256:
content_sha256:
contract_sha256:
qa_contract_sha256:
artifact_contract_sha256:  # when applicable
packet_id:
packet_sha256:
assignment_registry_sha256:
assignment_id:
revision_id:  # required after a patch
status: complete
reviewer:
  reviewer_id:
  role:
  independence_key:
  native_agent_id:
  task_id:
unit_reviews:
  - unit_id:
    criterion_id:
    verdict: pass | fail | uncertain | not_applicable | evidence_conflict
    source_span:
    evidence:
    reason:
    severity: critical | major | minor | none
    confidence: 0.0 .. 1.0
    requires_author_action:
    dependency_unit_ids:
    risk_or_role_escalation:
ledgers:
  intent_to_text:
  text_to_intent:
  text_to_evidence:
  baseline_to_candidate:
  definitions:
  revision_rechecks:
conflicts:
```

## Bounded Repair And Re-Review Handoff

The controller, not a reviewer, applies an accepted patch. Send the new-hash
change set to an independent reviewer.

```text
Finding IDs addressed:
Authority for repair:
Frozen meaning that must remain unchanged:
Old and new manuscript hashes:
Changed unit IDs and paragraphs:
Definition, evidence, and qualifier dependencies:
Affected abstract/introduction/conclusion/caption/note/appendix units:
Maximum patch scope:
Forbidden semantic changes:
Required roles for re-review:
```

Return:

```text
New findings:
Prior findings closed against current hash:
Dependencies covered:
Uncertain or conflicting judgments:
Author decision needed:
Gate recommendation: pass | clarification_required | evidence_conflict | approval_required | fail | metric_unavailable | audit_incomplete
```

## Conflict Handoff

Use this when roles disagree. Reviewer output only opens a conflict; it cannot
close it. Dispatch an independent resolver whose native agent/task identity is
not used by any reviewer, and return this typed artifact for
`--conflict-resolution`:

```text
schema_version: "1.0"
schema_id: qa-conflict-resolution/1.0
status: resolved
resolution_id:
conflict_id:
conflict_sha256:  # canonical SHA-256 of the exact originating conflict object
manifest_id:
manifest_sha256:
resolved_by:
resolved_at:  # ISO-8601 with timezone
resolver_native_agent_id:
resolver_task_id:
resolution_authority: author | author_intent | definition | evidence | deterministic_gate
authority_artifact:
  path:
  sha256:
  revision_id:  # required for author/author_intent/definition authority
resolution:
```

The authority artifact must be live and must be the exact author-intent
contract, evidence registry, or upstream gate supplied to the validator. If no
such authority resolves the disagreement, leave it open and return the
applicable blocking state. Recompute the conflict hash after any change; an old
resolution cannot be reused for a rewritten conflict. Do not use majority vote.
