# Exhaustive Semantic QA Protocol

## Contents

- Purpose and authority
- QA scope and supported inputs
- Required state and four-way ledgers
- Deterministic preparation
- Independent semantic roles
- Main-text sufficiency and conservation result
- Findings and gate decisions
- Repair and re-review
- End-to-end order

## Purpose And Authority

Use this protocol to prove review coverage and semantic fidelity for a complete
paper or proposal, a document-level translation or compression, or a major
manuscript revision. It combines deterministic
manifest generation and validation with native independent subagent judgment.
Neither part can substitute for the other.

The stable workflow's authoritative author-intent contract remains the sole
authority over what the author wants to express. Load and follow
`econ-writing-workflow/references/author-intent/01_author_intent_contract_and_semantic_fidelity.md`.
Do not create a second intent contract inside the multiagent project. Store an
exact path or artifact ID, revision ID, status, and hash in `paper_state`.

Only `frozen-current + ready` author intent authorizes claim-bearing drafting.
The author's explicit confirmation of a complete teach-back normally records
confirmation and freeze authorization in the same event. There is no drafting
compatibility exception for `proposed`, `partial`, unconfirmed, or materially
unresolved intent. An explicit hold, a nonempty material-question list, or an
evidence conflict keeps the contract unready.

An initial author instruction can establish `frozen-current + ready` without a
redundant question when it states one uniquely determined meaning, fixes the
material boundaries, and requests writing from that meaning. If more than one
material interpretation remains, teach it back and obtain confirmation first.

This single confirmation/freeze event applies only to author intent. It does
not merge the separate substantive confirmation, artifact freeze, replacement,
manuscript-integration, or submission approvals for research objects.

The stable author-intent authority may be Markdown (`.md`/`.markdown`), YAML
(`.yaml`/`.yml`), or plain text (`.txt`/`.text`). Because the version 1
deterministic QA tools consume JSON, represent one of those non-JSON authorities
with a derived JSON QA view. The `authority_source.format` value must be one of
`md`, `markdown`, `yaml`, `yml`, `txt`, or `text` and must match the path suffix;
do not infer or accept `unknown`, TeX, or an open-ended format:

```text
author_intent_contract:
  artifact_role: qa_view
  authority_source:
    path:
    sha256:
    format:
  adapter_confirmation:
    status: confirmed
    confirmed_by:  # author or recorded human delegate
    confirmed_at:  # ISO-8601 with timezone
    confirmed_scope: complete_author_intent_projection
    confirmation_source:  # recoverable author message or decision record
    authority_source_sha256:
    intent_revision_id:
    qa_view_projection_sha256:
  # the same confirmed intent IDs, meanings, prohibitions, and approval record
```

The JSON view is an adapter, not a second authority. It must point to and hash
the sole authoritative source, preserve its frozen revision and approval
record, and carry a recoverable author confirmation that the complete projection
is faithful. Compute `qa_view_projection_sha256` over the author-intent object
with `adapter_confirmation` omitted, avoiding a self-referential hash. Use
UTF-8 JSON with keys sorted, `ensure_ascii=false`, and compact separators
(`,` and `:`), matching the preparer's `canonical_hash` function. Preparation
recomputes the source and projection hashes. The Author-Intent reviewer must also
compare the source and projection and return `authority_projection_verified:
pass` bound to the current hashes; deterministic hash checks alone do not prove
semantic equivalence. A missing, stale, self-referential, unconfirmed, or
conflicting source returns `audit_incomplete`/`metric_unavailable`. When the
authoritative contract is already JSON, use it directly and omit the adapter
fields.

The author controls intended meaning; inspected evidence controls the maximum
supportable claim. If they conflict, return `evidence_conflict` instead of
silently changing either side.

## QA Scope And Supported Inputs

Set `qa_mode` before preparation:

- `exhaustive`: required for a complete paper, complete proposal,
  document-level translation or compression, major revision,
  or final acceptance of any of those artifacts;
- `bounded_change`: allowed only for a local polish whose substantive scope is
  already governed by frozen intent. Include every changed sentence, its full
  paragraph, necessary adjacent context, definitions it uses or changes, and
  corresponding abstract, introduction, conclusion, caption, note, or appendix
  statements that depend on it.

Escalate `bounded_change` to `exhaustive` when the change affects the paper
spine, claim type or strength, mechanism, definition, evidence boundary, scope,
or material placement.

`qa_mode` is mandatory and has no implicit default. Use this closed
`task_stage -> qa_mode` mapping:

- `full_draft`, `proposal_draft`, `document_translation`,
  `document_compression`, `major_revision`, `major_restructure`, and
  `final_audit` -> `exhaustive`;
- `local_edit` and `local_polish` -> `bounded_change`.

An unknown stage or a stage/mode mismatch fails preparation. Do not invent a
stage merely to obtain the cheaper mode.

Record the classification rather than relying on a label alone:

```text
  task_classification:
    task_stage:
    qa_mode:
    artifact_task_mode:  # required for final_audit; must match artifact_contract.task_mode
    basis:
    changed_artifact_or_source_ranges:
    substantive_dependencies_checked:
    affected_intent_ids:  # nonempty authoritative list in bounded_change
    classified_by:
    classified_at:
```

Every mode requires a nonempty `task_stage`, matching `qa_mode`, basis,
classifier, and timestamp. A `bounded_change` label without a nonempty basis,
changed set, and explicit dependency set is not evidence of a local edit and
must not reduce coverage.
For `bounded_change`, the same nonempty `affected_intent_ids` list must appear
in `revision_scope`, and every ID must exist in the frozen authoritative
author-intent contract. The final validator requires an intent-to-text location
and re-review result for every affected ID; lexical marker matching is not a
substitute for the frozen mapping.
substitute for this explicit declaration.
Preparation expands the explicit changed/dependency selectors to a
deterministic closure: all review targets in the changed paragraph, all
lexically linked occurrences of affected intent IDs and definitions, and both
sides of footnote or other declared unit dependencies. An empty controller
dependency selector cannot suppress dependencies that the manifest can prove.
Pure non-reader-visible layout operations that change no manuscript unit remain
outside this semantic packet pipeline. Once a reader-visible sentence or
heading is admitted to `bounded_change`, at least one frozen intent ID is
required; do not use an empty list as a mechanical-edit bypass.

In `exhaustive` mode, capture every reader-visible textual object:

- main-text and appendix prose;
- headings and list items that carry substantive meaning;
- footnotes and endnotes;
- table and figure captions and notes;
- reader-visible text around equations, propositions, and proofs;
- any other textual object that a reader can use to interpret a claim.

Give sections, paragraphs, captions, notes, footnotes, and appendix prose stable
container IDs. Split their prose into sentence review targets, and treat
substantive headings as review targets. A container need not receive a duplicate
semantic verdict when every part of its visible text is represented by child
targets, but the deterministic validator must prove that mapping is nonempty and
lossless. Equations and inline formulas receive stable `formula_id` anchors.
The manifest retains their exact raw source, whitespace-normalized math,
SHA-256 values, declared labels, and source spans; packets containing an anchor
also contain its formula context. This is necessary to distinguish, for
example, positive from negative predictions. Propositions, labels, citations,
and table or figure references remain exact anchors even when they are not
standalone prose sentences. Comments, hidden task notes, and author memos are
not reader-visible objects and must not be treated as reviewed manuscript text.

Version 1 accepts `.tex`, `.md`, and `.txt`. TeX preparation may resolve only
bounded local `\input` and `\include` dependencies under the declared project
root. It must reject cycles, missing files, path escapes, and ambiguous include
graphs rather than silently omit text. Detached `\footnotemark`/
`\footnotetext` pairs are not linked in version 1 and therefore fail closed;
convert them to inline `\footnote` commands or provide another supported source.
A static `\title` or `\subtitle` invoked by `\maketitle` is a review target;
static author/date/affiliation/institute/address/email metadata and nested
`\thanks` notes are retained as visible metadata/footnote units. Unsupported
custom title metadata must fail closed or be explicitly recorded as an export
limitation rather than silently omitted. Reader-visible unknown control
sequences fail closed rather than losing
custom-macro meaning; expand such macros or export a supported source first.
Common `tabular`, `tabular*`, `tabularx`, and `longtable` bodies retain explicit
`[TABLE]`, `[ROW]`, and `[CELL]` boundaries and drop non-visible column-format
arguments. Description-list labels, escaped currency dollars, declared labels,
links, and visible arguments of common multi-argument formatting commands must
remain in review packets. Markdown dollar spans that are lexically
currency-like remain exact prose rather than being guessed to be formulas;
authors should escape ambiguous currency dollars when necessary.
A `.docx` manuscript must first be
exported to `.txt`, `.md`, or `.tex`; record the exported source and its hash.
Do not claim that Word-only structures were audited unless the exported source
preserves them.

## Required State And Four-Way Ledgers

Before preparation, `paper_state` must point to these current records:

```text
author_intent_contract:
  authoritative_path_or_artifact_id:
  intent_contract_id:
  intent_revision_id:
  intent_status: frozen-current
  gate_status: ready
  sha256:
content_obligations:
  obligation_id:
  intent_id:
  required_meaning:
  required_location_or_scope:
  must_remain_main:
  prohibited_claim_or_implication:
  evidence_anchors:
definition_registry:
  definition_id:
  canonical_term:
  allowed_variants:
  canonical_definition:
  first_use_requires_definition:
  author_allowed_presupposition:
  intended_first_location:
qa_contract:
  schema_version:
  qa_mode: exhaustive | bounded_change
  task_classification:
    task_stage:  # closed enum above
    qa_mode:
    artifact_task_mode:  # required for final_audit
    basis:
    changed_artifact_or_source_ranges:
    substantive_dependencies_checked:
    affected_intent_ids:
    classified_by:
    classified_at:
  revision_scope:
    affected_intent_ids:
  manuscript_path:
  required_roles:  # include all four semantic role IDs below
  minimum_high_risk_independent_reviews: 2  # v1 canonical integer, 2 through 4
  max_units_per_packet:
  max_packet_bytes:
  unit_scope:
  accepted_export_limitations:
  evidence_registry_source:
    path:
    sha256:
qa_hashes:  # preparer output; write back only after canonical packet preparation
  manuscript_sha256:
  author_intent_contract_sha256:
  qa_contract_sha256:
  artifact_contract_sha256:
  qa_bundle_sha256:
```

Before preparation, authority comes from the live manuscript path and the
author-intent, QA, evidence-registry, paper-state, and artifact-contract
sources—not from a controller-supplied `qa_hashes` block. After the preparer
has reread those live bytes, it writes the canonical hashes and manifest ID
back to `paper_state`. Treat any pre-existing values as prior-run output that
must be replaced and independently revalidated; never require a self-referential
future manifest hash as an input to packet preparation.

Keep the hashes distinct. `qa_bundle_sha256` may bind the set of contract
hashes, but it never replaces or aliases an individual contract hash.
When `paper_state.author_intent_contract` is a pointer to a separate authority,
its ID, revision, status, gate, SHA-256, and resolved path or stable contract ID
must match the live author-intent input exactly. A combined legacy paper-state
file may instead contain the exact full contract object; a partial projection
or stale pointer is not accepted.

Author-owned propositions, prohibitions, and definitions establish the ID
universe. QA-contract or paper-state records may enrich an existing obligation
or definition only when they cite its author-owned ID and preserve the same
meaning. They may not create a new intent, term meaning, mechanism, qualifier,
or claim. The preparer rejects an unanchored or conflicting supplement before
packet creation, and the validator independently repeats that authority check.

When claims require evidence beyond anchors already frozen inside the author
contract, `evidence_registry_source` must point to current live bytes with this
minimum schema:

```text
schema_version: "1.0"
schema_id: evidence-registry/1.0
status: frozen-current | accepted
approval_record:
  confirmed_by:
  confirmed_at:  # ISO-8601 with UTC offset or Z
  confirmation_source:
evidence:
  - evidence_id:  # source_id/anchor_id/id accepted as aliases
    source:       # or path
    source_sha256:  # sha256 accepted as an alias
```

The preparer verifies the live file and projects its one binding only to
`manifest.inputs.evidence_registry`; it must not create a competing
`manifest.source` alias. Review packets receive only records from this verified
registry plus author-owned anchors. The validator reloads the live bytes and
rejects a missing, stale, malformed, unapproved, duplicate, or manifest-invented
evidence ID. The manifest projection must equal the live records exactly, and
each packet's evidence binding and contract-context records must be an exact
authorized projection; retaining a valid ID while changing its source, path,
hash, or description is stale context, not a pass. A hash proves byte identity, not that evidence substantively
supports a claim; the Evidence and Claim Strength reviewer still decides that.

Maintain four recoverable ledgers. Do not reduce them to an untraceable prose
summary:

1. `intent -> text`: every required intent and content obligation maps to one
   or more unit IDs, or to a blocking finding if absent;
2. `text -> intent`: every manuscript claim maps to an authorized intent ID;
3. `text -> evidence`: every factual, numerical, causal, theoretical,
   mechanism, or normative claim maps to inspected evidence and its permitted
   strength;
4. `baseline -> candidate`: every substantive baseline block maps to its
   preserved, revised, reordered, merged, authorized appendix, or authorized
   deletion destination.

The fourth ledger is mandatory when a baseline exists and must reuse the
artifact-conservation ledger rather than create a parallel copy. The first
three remain mandatory even for a new manuscript with no baseline.

## Deterministic Preparation

Use the standard-library-only `scripts/prepare_manuscript_qa.py` to create a
versioned manifest and review packets. Python performs extraction, stable
identification, hashing, dependency
tracking, packet construction, and schema checks. It does not call a model,
judge semantic truth, or declare that a sentence is substantively acceptable.
Version 1 adds no model-provider SDK, API key, or direct per-call billing path;
native subagents are orchestrated by the active Codex environment.

Each manifest must record at least:

```text
schema_version:
manifest_id:
qa_mode:
task_classification:
revision_scope:
revision_target_unit_ids:  # sorted live review targets after bounded dependency closure; [] in exhaustive mode
review_policy:
  minimum_high_risk_independent_reviews:
  required_semantic_roles:
manuscript:
  path:
  project_root:
source_files:
manuscript_sha256:
expanded_manuscript_sha256:
author_intent_contract_sha256:
contract_sha256:  # compatibility alias for author_intent_contract_sha256
qa_contract_sha256:
artifact_contract_sha256:
evidence_registry_sha256:
qa_bundle_sha256:
role_protocol_version:
role_protocols_sha256:
role_protocols:
formula_registry_sha256:
formulas:
  - formula_id:
    raw:
    normalized_math:
    raw_sha256:
    normalized_sha256:
    declared_labels:
    source_spans:
inputs:
  evidence_registry:
    path:
    sha256:
    schema_id: evidence-registry/1.0
    status: frozen-current | accepted
evidence_registry:
  - evidence_id:
    source:
    source_sha256:
units:
  - unit_id:
    type: section | paragraph | appendix_prose | caption | note | footnote | sentence
    text:
    text_sha256:
    reader_visible:
    review_target:
    selected_for_review:
    parent_id:
    child_unit_ids:
    child_text_sha256:
    sentence_coverage_status:
    source_spans:
    text_start_in_parent:
    text_end_in_parent:
    citation_keys:
    reference_labels:
    declared_labels:
    external_links:
    footnote_reference_ids:
    footnote_target_unit_ids:
    formula_ids:
    dependency_unit_ids:
    section_id:
    paragraph_id:
    region: main_text | appendix
    context:
      paragraph_text:
      previous_review_unit_id:
      previous_review_text:
      next_review_unit_id:
      next_review_text:
    risk:
    required_roles:
    min_independent_reviews:
packets:
packetization:
  max_units_per_packet:
  max_packet_bytes:
  packet_count:
content_obligations:
definition_registry:
```

Because a file cannot contain its own byte hash without recursion, write the
final `qa_manifest.json` SHA-256 to a sidecar and require that exact value as
`manifest_sha256` in every reviewer result.

IDs must be deterministic for the same source bytes and extraction contract.
A changed source creates a new manuscript or manifest SHA-256 and invalidates
old results.
Each packet repeats the entry-manuscript hash, expanded-content hash, individual
contract hashes, authority-source record when applicable, and its own packet
hash so a reviewer can populate every required freshness field without relying
on memory. When an artifact contract applies, the packet also contains the
exact live inner `artifact_contract` object, not only its hash. The validator
requires canonical body equality with the live contract; a matching hash field
does not authorize a substituted or partial packet body.
In `exhaustive` mode, select every sentence/heading review target. In
`bounded_change` mode, require a nonempty changed selector and an explicit
dependency selector in `revision_scope`; select matching review targets and
then add the paragraph, affected-intent, definition, and bidirectional declared
dependency closure, while retaining useful adjacent context in their packets. A
preparer must freeze the resulting complete selected-target set as sorted,
unique `revision_target_unit_ids`; the validator independently reconstructs it
from the live source and requires a current revision-recheck record for every
ID. Source-range selectors never exempt a changed sentence merely because the
contract did not already know its unit ID. In exhaustive mode this bounded-only
field is the explicit empty list.

A bounded selector that matches nothing is `metric_unavailable`, not an empty
pass. Validate every selector independently: each unit ID must resolve to a
review target, and each source range must declare a known path plus integer
lines and match at least one review target. One valid selector cannot hide a
stale ID, typo, missing path, or unmatched range elsewhere in the recorded
scope.
Packets must include enough local context to interpret the unit: at minimum the
full paragraph, useful adjacent text, frozen intent slice, content obligations,
definition entries, evidence anchors, and section card. Do not send an isolated
sentence whose meaning depends on omitted context.
The validator reconstructs the canonical `contract_context` from the current
author-intent, QA, artifact, evidence, and paper-state authorities and requires
each packet to match it exactly. A packet cannot retain true top-level hashes
while substituting different proposition text, qualifiers, definitions,
obligations, evidence details, section cards, or baseline ledger entries.
Preserve a stable anchor for every inline TeX or Markdown footnote reference,
link the parent sentence to the extracted footnote target, and link the footnote
back to the sentence it qualifies. Put the current text and hash of declared
dependency units in the packet context, and include both sides in dependency-aware
re-review. Preserve declared LaTeX labels separately from reference labels so a
reviewer can distinguish an object's identity from a citation to that object.

Split long role assignments deterministically into multiple packets. Version 1
defaults to at most 25 review targets and 240,000 UTF-8 JSON bytes per packet;
the QA contract may set `max_units_per_packet` from 1 through 25 and
`max_packet_bytes` from 10,000 through 240,000. A single target that cannot fit
is `metric_unavailable`, never silently truncated. Keep `packet_id`, role,
batch index/count, exact unit IDs, byte size, and packet hash in the manifest.
The validator must accept multiple packets for one role, require a current
result for every packet, and reject cross-packet unit substitution.

The preparation report must distinguish extraction failure, unsupported input,
and unavailable metrics. It must not represent omitted or unparsed material as
an empty but successfully reviewed unit set. Every reader-visible container
must have child review targets whose normalized text covers the visible content;
every review target must receive an audit record.

```bash
python scripts/prepare_manuscript_qa.py \
  --manuscript candidate.tex \
  --project-root /path/to/project \
  --author-intent-contract author_intent_contract.json \
  --qa-contract qa_contract.json \
  --artifact-contract artifact_contract.json \
  --output-dir qa_prepared
```

The artifact contract is mandatory for `full_draft`, `proposal_draft`,
`document_translation`, `document_compression`, `major_revision`,
`major_restructure`, and `final_audit`; preparation fails before packet creation
when it is missing or its `task_mode` does not match the deterministic mapping
in `artifact_conservation_and_depth_gates.md`. `final_audit` additionally binds
`task_classification.artifact_task_mode`. Omit `--artifact-contract` only for a
`local_edit` or `local_polish` whose bounded scope genuinely does not invoke
artifact conservation. Preparation returns exit code `0` on success. Invalid
input, extraction, contract, or pipeline invariants return `2 fail` unless a
more specific typed state applies. A required artifact measurement recorded as
unavailable returns `3 metric_unavailable`; a missing or stale recoverable
authority record returns `4 audit_incomplete`; non-frozen/non-ready intent or
an explicit author hold returns `5 clarification_required`; and a recorded
unresolved evidence conflict returns `6 evidence_conflict`. Read the structured
stderr JSON rather than inferring status from console wording.

Make role and risk assignment conservative. Keyword or structural rules may
pre-assign specialist roles and high-risk status, but the absence of a keyword
does not prove that a unit is non-claim or low risk. Any semantic reviewer may
flag a missed claim, applicable role, or high-risk feature. The controller must
update the manifest and collect the newly required independent reviews before
validation can pass; it may not dismiss the escalation because the preparer did
not detect it.

## Independent Semantic Roles

Use four isolated native-subagent roles:

Use stable machine IDs in manifests and results:

```text
author_intent_coverage
evidence_claim_strength
definitions_reader_sufficiency
economic_logic_scope_qualifiers
```

### Author-Intent And Coverage

Review every sentence and substantive-heading target and both directions of the
intent mapping. Confirm deterministic coverage of reader-visible containers.
Find missing obligations, unauthorized additions, altered emphasis, forbidden
implications, wrong placement, and incompatible cross-section formulations.

### Evidence And Claim Strength

Review every claim-bearing target that depends on facts, citations, numbers,
estimates, causal interpretation, theory, mechanism evidence, or normative
support. Check the evidence anchor and maximum warranted claim strength.

### Definitions And Reader Sufficiency

Review terms, symbols, variables, actors, samples, comparisons, acronyms, and
model objects for prior definition, adequacy, stable use, clear reference, and
reader comprehension. Deterministic order checks can show that a registered
definition occurs before use; this role decides whether the definition is
actually sufficient.

### Economic Logic, Scope And Qualifiers

Review the chain from actor and constraint to behavior and outcome, the stated
comparison, logical direction, scope, timing, population, geography,
uncertainty, caveats, and the distinction between association, causality,
heterogeneity, and mechanism evidence.

Use role-protocol version `1.0` and these exact criterion IDs:

- `author_intent_coverage`: `intent_coverage`, `unauthorized_claim`,
  `prohibited_implication`, `qualifier_fidelity`;
- `evidence_claim_strength`: `evidence_support`, `claim_strength`,
  `causal_language`, `numeric_fidelity`;
- `definitions_reader_sufficiency`: `definition_before_use`,
  `definition_sufficiency`, `term_consistency`, `referent_clarity`;
- `economic_logic_scope_qualifiers`: `economic_logic`,
  `mechanism_authorization`, `scope_conditions`, `comparison_direction`,
  `qualifier_preservation`.

The Author-Intent and Coverage role covers all sentence/heading targets. Because
claim-bearing status, missing definitions, and lost qualifiers are themselves
semantic judgments, version 1 conservatively sends every admitted target to all
four roles; a specialist may return `not_applicable` with evidence when its
criterion truly does not apply. This stronger routing prevents a lexical
pre-classifier from suppressing the specialist who could discover a missed
claim. A unit is high risk when it contains or controls a causal claim,
mechanism claim, number or magnitude, definition or first use, scope or
qualification, negation, contribution boundary, or normative implication. The
general high-risk rule remains a lower bound of two independent reviews;
version 1's four-role routing exceeds it. No reviewer may see another
reviewer's first-pass verdict or the controller's proposed repair.

Native independence is an acceptance requirement. A controller may use staged
same-agent roles for drafting support, but it cannot count them as independent
semantic reviewers. If the environment cannot supply the required native
subagents, return `audit_incomplete`; do not simulate reviewers sequentially
and claim `pass`.

Each packet carries `role_protocol_version`, a protocol hash, the role's fixed
`required_checks`, criterion definitions, and its output schema. Every reviewer
must return exactly one structured record for every assigned unit and every
required criterion; use evidenced `not_applicable` rather than omitting a check.
Preparation also writes `qa_assignment_registry.template.json`. Before
dispatch, copy it to a final registry, record a unique assignment ID, native
agent ID, task ID, and assignment time for every packet, set its status to
`assigned`, hash the completed bytes, and give that hash to each reviewer.

Use this exact registry shape. Every final registry contains exactly one
`semantic_packet` assignment for every manifest packet. An `exhaustive` run
also contains exactly one fifth-role assignment; a `bounded_change` run contains
none because it cannot claim whole-manuscript sufficiency. An extra, missing,
duplicate, stale, or cross-role-reused assignment fails closed:

```text
schema_version: "1.0"
schema_id: qa-assignment-registry/1.0
status: assigned
manifest_id:
manifest_sha256:
assignments:
  - assignment_kind: semantic_packet
    target_id:  # packet_id
    target_sha256:  # packet_sha256
    packet_id:
    packet_sha256:
    role:
    assignment_id:
    native_agent_id:
    task_id:
    assigned_at:  # ISO-8601 with timezone
  - assignment_kind: main_text_sufficiency  # exhaustive only
    target_id: main-text-sufficiency
    target_sha256:  # expanded manuscript content SHA-256
    assignment_id:
    native_agent_id:
    task_id:
    assigned_at:  # ISO-8601 with timezone
```

For exhaustive QA, the fifth-role `native_agent_id` and `task_id` must be
distinct from all four semantic-role assignments. A semantic native agent may
handle multiple batches for its one role, but one native agent may not serve
different roles in the same audit. These records and reviewer declarations are
structural evidence and attestations of isolation, not mathematical proof of
independence. Bounded QA reports only bounded semantic coverage and must not
accept or advertise a whole-manuscript sufficiency result.

Pre-register the exhaustive fifth-role assignment even though execution is
downstream of the deterministic conservation gate. If a fresh, canonically
replayed conservation result is `fail`, `approval_required`, or
`metric_unavailable`, the controller may fail fast without producing a fifth-
role result; retain that authentic status, repair or authorize it, and then run
the complete downstream review. Only a missing, malformed, stale, or
unreplayable conservation artifact turns the absence into `audit_incomplete`.

Reviewers only return findings. They must not edit the manuscript, alter
`paper_state`, rewrite the author-intent contract, or approve their own repair.

## Main-Text Sufficiency And Conservation Result

For `exhaustive` QA that reaches the downstream acceptance stage, the
independently assigned fifth role returns this exact object after the final
deterministic conservation run and post-diction semantic re-review:

```text
schema_version: "1.0"
schema_id: main-text-sufficiency-audit/1.0
gate_type: main_text_sufficiency_and_conservation
result_id:
status: pass | fail | approval_required | metric_unavailable
reviewed_at:  # ISO-8601 with timezone
manifest_id:
manifest_sha256:
candidate_sha256:
content_sha256:
contract_sha256:
qa_contract_sha256:
artifact_contract_sha256:
assignment_registry_sha256:
assignment_id:
conservation_gate_sha256:  # required when the conservation report is composed
reviewer:
  reviewer_id:
  role: main_text_sufficiency_and_conservation
  independence_key:
  native_agent_id:
  task_id:
checklist:
  main_text_self_contained:
  definitions_and_assumptions_sufficient:
  data_model_sample_explained:
  economic_interpretation_present:
  required_content_in_main_text:
  appendix_moves_authorized:
  baseline_content_conserved:
  length_and_depth_contract_satisfied:
question_reviews:
  - card_id:
    question_id:  # depth-question-<first 20 hex chars of question_sha256>
    question_sha256:
    verdict: pass | fail | approval_required | metric_unavailable
    rationale:
    evidence_units:
      - unit_id:
        text_sha256:
findings:
  - status: fail | approval_required | metric_unavailable
    code:
    message:
    evidence:  # optional structured support and source locations
```

All eight checklist values are explicit booleans. Reconstruct each depth
question from the live artifact contract in card order. Its SHA-256 is the
canonical JSON hash of `card_id`, one-based `question_index`, and the exact
`question_text`; its deterministic ID uses the first 20 hex characters of that
hash. `question_reviews` must cover those identities exactly once, with no
missing, duplicate, or extra record. Each review binds the live card and
question hash, gives a typed verdict and nonempty rationale, and cites at least
one current manifest unit by both `unit_id` and exact `text_sha256`.
For a passing question, every cited unit must be current main-text material in
the candidate section bound to that card. Resolve candidate-only cards from
their unique live `section_name`; resolve mature cards from their explicit live
candidate selector or from the candidate section returned by the validator's
fresh canonical conservation replay. Never trust a fifth-role or hand-written
gate result to supply this destination. Version 1 has no hash-bound typed
cross-section evidence authority, so cross-section evidence cannot support a
passing question. A nonpassing review may cite a current appendix or other
location to prove omission or misplacement, but it still binds the live unit
and text hash.

A `pass` requires every checklist value and every depth-question verdict to be
`pass`, plus `findings: []`. A non-pass requires at least one false value and
one or more typed findings. Preserve every blocker: findings may mix `fail`,
`approval_required`, and `metric_unavailable`; the top-level status must equal
their fail-closed priority (`fail` before `approval_required` before
`metric_unavailable`). A complete, fresh non-pass remains its real status;
reserve `audit_incomplete` for a missing, malformed, stale, unassigned, or
otherwise unverifiable result. This whole-manuscript schema is forbidden in
`bounded_change`.

Interpret the booleans by applicability, not by forcing every paper into an
empirical mature-manuscript template. For candidate-only `full_draft`,
`baseline_content_conserved: true` means that no accepted baseline exists and
the candidate-only contract gate passed; it must not invent a baseline.
`appendix_moves_authorized: true` means either that no main-to-appendix move
occurred or that every such move has exact author authorization.
`data_model_sample_explained: true` means every applicable data, model, and
sample object for that paper type is explained; a pure theory paper does not
fail merely because data or sample objects are inapplicable. Review findings
must identify which applicable object is missing or insufficient.

## Findings And Gate Decisions

Each reviewer returns one machine-checkable result object tied to the current
manifest and contract. Use this version 1 structure:

```text
schema_version:
result_id:
manifest_id:
manifest_sha256:
manuscript_sha256:
content_sha256:  # expanded manuscript content, including resolved TeX inputs
contract_sha256:  # author-intent artifact bytes
qa_contract_sha256:
artifact_contract_sha256:  # required when the manifest declares one
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
    requires_author_action: true | false
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

The validator requires every unit-review field through
`requires_author_action`; dependency and risk-escalation fields are added when
applicable. Each result must cite the exact assigned `packet_id` and
`packet_sha256`, the current QA-contract hash, and the artifact-contract hash
when one exists. Record `revision_id` after any patch so the validator can prove
re-review against the current revision. Treat `reviewer.independence_key` as a
reviewer attestation, not mathematical proof. Final acceptance also requires a
hash-bound assignment registry mapping each packet to its native agent/task
identity and assignment time; a missing or mismatched registry returns
`audit_incomplete`. `manifest_sha256` binds results to the exact manifest
bytes; `manifest_id` alone is only a stable identity. Here `contract_sha256` is
the SHA-256 of the authoritative
author-intent contract artifact supplied to validation, including a permitted
paper-state wrapper when used. It is a compatibility alias for
`author_intent_contract_sha256`, not a QA-bundle or artifact-contract hash.

Use the standard-library-only `scripts/validate_manuscript_qa.py` after
collecting findings. It verifies
schema, hashes, lossless reader-visible container coverage, complete review-
target coverage, required-role completion, high-risk
double review, the three semantic ledgers, registered definition order,
conflict closure, upstream artifact-gate status, and required re-review after
patches. It does not replace semantic judgment.

```bash
python scripts/validate_manuscript_qa.py \
  --manifest qa_manifest.json \
  --contract author_intent_contract.json \
  --assignment-registry qa_assignment_registry.json \
  --main-text-sufficiency-audit main_text_sufficiency_audit.json \
  --review-result review_results/ \
  --candidate candidate.tex \
  --project-root /path/to/project \
  --upstream-gate conservation_audit.json \
  --conflict-resolution conflict_resolution.json \
  --report qa_validation.json
```

Repeat `--review-result`, `--upstream-gate`, and `--conflict-resolution` as
needed; omit `--conflict-resolution` only when no reviewer reported a conflict.
A filled assignment registry is required in both QA modes. The
`--main-text-sufficiency-audit` input is required for `exhaustive` and must be
omitted for `bounded_change`.
A trusted candidate
digest may be supplied with `--candidate-sha256` or
`--candidate-sha256-file` when exact candidate bytes are not passed.
When the manifest declares an artifact-contract SHA-256, at least one upstream
gate must declare the matching contract path and hash. Validation recomputes
the contract bytes and returns `audit_incomplete` if the path, hash, or match is
missing; an upstream `pass` alone does not prove which contract was applied.

A reviewer cannot close its own conflict. Every reported conflict that is not
still blocking requires one separate, independent artifact with this exact
identity and live authority binding:

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

The resolver's native agent/task identity must not match any reviewer involved
in the run. `authority_artifact` must still exist and match the governing
author-intent contract, evidence registry, or supplied upstream gate as
applicable. The validator recomputes `conflict_sha256`, so a resolution cannot
be replayed after the same conflict ID's content changes. Majority vote, vote
counts, and unsupported controller preference are never resolution authority.
Compute that hash over the exact conflict object using UTF-8 JSON with sorted
keys, `ensure_ascii=false`, and compact separators, matching `canonical_hash`.

Never use majority vote. Resolve disagreement by the frozen intent, inspected
evidence, definition registry, and explicit authority order. Any critical
failure, unresolved disagreement, `uncertain` verdict, missing required
reviewer, invalid result, stale hash, uncovered target/container, or unreviewed dependency
blocks delivery.

Use these combined gate outcomes:

- `pass`: deterministic coverage is complete; every required semantic review
  and re-review passes; no unresolved finding or authority conflict remains;
- `clarification_required`: intended meaning is missing, ambiguous, or
  materially inconsistent;
- `evidence_conflict`: intended wording exceeds or contradicts inspected
  evidence;
- `approval_required`: a conservation, deletion, compression, or placement
  decision needs scoped author approval;
- `fail`: the current candidate violates a valid contract or has a repairable
  substantive QA failure;
- `metric_unavailable`: a required deterministic artifact measurement cannot
  be reproduced;
- `audit_incomplete`: independent review, valid packets/results, complete
  coverage, or mandatory re-review is unavailable.

A fresh, structurally valid, canonically replayed upstream conservation result
retains its real `fail`, `approval_required`, or `metric_unavailable` status.
Do not relabel it `audit_incomplete` merely because downstream semantic or
fifth-role work correctly did not begin. Missing, malformed, stale, or
unreplayable gate evidence is `audit_incomplete`; an authentic non-pass gate is
the higher-level stopping result and must be repaired or authorized before
downstream acceptance work resumes.

An explicit author hold keeps `intent_status: proposed` and drafting disabled.
For the combined validator interface, serialize its blocking outcome as
`clarification_required` with `reason_code: explicit_author_hold`; this status
means renewed author action is required, not that the already stated meaning is
necessarily unclear.

Distinguish `gate_local_status` from `delivery_status`. A conservation, role,
or sentence-level gate may locally pass while another applicable gate remains
open. Only `delivery_status: pass` after every applicable gate passes permits
final delivery. A report must retain every blocker in `findings` even when it
also exposes one deterministic primary status; do not let a primary status,
majority vote, or approval item erase a simultaneous failure.

Validator exit codes are `0` pass, `1` fail, `2` approval required, `3` metric
unavailable, `4` audit incomplete, `5` clarification required, and `6` evidence
conflict. Read the JSON report rather than inferring the result from console
wording.

## Repair And Re-Review

The controller converts accepted findings into a bounded patch plan. Apply the
smallest patch that restores the frozen meaning and evidence boundary. Do not
perform a clean-slate rewrite, add a new mechanism, weaken an author-required
meaning, or change a conclusion merely because a reviewer suggests it.

If a repair changes intended meaning, evidence strength, a definition's
substance, or the research conclusion, stop for an author decision and, when
approved, supersede the affected intent revision before editing.

After every patch:

1. regenerate or update the deterministic manifest and hashes;
2. re-review each changed unit and its full paragraph;
3. re-review units that depend on the changed definition, claim, evidence,
   table or figure interpretation, or qualifier;
4. re-review corresponding abstract, introduction, conclusion, caption, note,
   and appendix statements;
5. validate that prior findings were closed against the new manuscript hash.

Run diction only after the substantive semantic gate passes. Treat diction as
a new change set: regenerate affected units and run semantic re-review so that
smoother prose cannot remove a caveat, alter a definition, or strengthen a
claim. A reviewer or controller cannot approve the exact repair it authored
without an independent re-review.

## End-To-End Order

```text
author intent clarified, taught back, confirmed, and frozen-current + ready
-> content obligations, definition registry, and artifact/length contract
-> patch/reorder or section drafting
-> deterministic QA manifest and contextual packets
-> isolated native-subagent semantic reviews
-> authority-based conflict resolution
-> bounded minimum patches
-> changed-unit and dependency re-review
-> language-specific diction
-> post-diction semantic re-review
-> final deterministic conservation and main-text sufficiency audit
-> delivery only when every applicable gate is pass
```

Context budget is not manuscript budget. Review-packet size, role isolation,
or token limits never authorize omitted manuscript content. Keep the mature
manuscript's `patch_existing` or `reorder_existing_blocks` default, cumulative
15 percent approval trigger, section-depth requirements, and conservation
ledger. An explicitly authorized 15-page target may pass when its own artifact
contract and semantic obligations pass; never impose a universal 30-page floor.
