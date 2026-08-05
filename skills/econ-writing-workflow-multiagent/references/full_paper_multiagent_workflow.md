# Full Paper Multiagent Workflow

## Contents

- Purpose
- Author-intent gate
- Baseline artifact and input audit
- State, evidence, literature coverage, architecture, and drafting
- Exhaustive semantic QA and bounded repair
- Diction, conservation, and final consistency
- Final deliverable

## Purpose

Use this workflow when the user asks for a complete paper or proposal, a major
rewrite from a research question and result package, or document-level
translation or compression. Use the same acceptance phase for
a major revision even when drafting is organized as patches rather than section
agents.

This workflow supports author-responsible drafting only. It must not be used for
paid paper-writing services, undisclosed ghostwriting, fabricated research, or
automatic submission.

## Workflow

### Step 0. Author Intent: Confirm And Freeze Before Drafting

Load the stable workflow's
`econ-writing-workflow/references/author-intent/01_author_intent_contract_and_semantic_fidelity.md`.
Locate its one authoritative current contract; do not create a parallel
multiagent version.

- inspect the manuscript, current plan, evidence, definitions, and prior author
  decisions before asking questions;
- if meaning is not unique, ask the smallest grouped set of material questions
  and teach the complete requested scope back to the author;
- treat explicit confirmation of a complete teach-back as confirmation and
  freeze authorization in the same event unless the author explicitly holds
  writing, material questions remain, or an evidence conflict exists;
- proceed only when the exact drafting scope is `frozen-current + ready`.

Do not draft claim-bearing prose from `partial`, `proposed`, unconfirmed, held,
materially unresolved, or evidence-conflicted intent. There is no compatibility
exception. Use `clarification_required` or `evidence_conflict` and stop the
affected scope.

### Step 1. Baseline Artifact Audit And Contract

For a mature revision, restructuring, shortening, or appendix relocation, load
`artifact_conservation_and_depth_gates.md` before assigning roles.

- identify the user-accepted baseline by path and hash;
- classify `task_mode` and `rewrite_mode`;
- measure the main text with a fixed appendix boundary and measurement method;
- record target ranges, hard floors, cumulative reduction permission,
  `must_remain_main`, and allowed appendix moves;
- assign stable source-block IDs and initialize the conservation ledger.

Stop if required metrics are unavailable or the proposed scope implies material
shortening without a target or approval. `context budget != manuscript budget`.
Keep the 15 percent mature-draft threshold as a conditional approval trigger,
not a target or quality measure. An explicitly authorized 15-page target may
pass its own contract; never impose a universal 30-page floor.

For a new draft with no accepted baseline, freeze the paper-wide and section
target ranges, content obligations, and minimum explanation-depth questions
before drafting. Do not invent a baseline or apply the mature-draft reduction
percentage; judge the new draft against its explicit contract instead.

### Step 2. Input Audit

Use the input audit role to determine draftability:

- enough to draft;
- enough for an author-facing structural outline but not reader-facing outline
  prose or manuscript drafting;
- enough to revise selected sections only;
- insufficient without user clarification.

Record only non-semantic missing facts as `TODO`. A missing item that changes
meaning or the evidence ceiling returns `clarification_required` or
`evidence_conflict` and leaves the affected prose unwritten.

These draftability labels are controller-facing. If Step 0 has not reached
`frozen-current + ready`, even an "outline" is limited to an author-facing
structure for clarification; do not produce paper-facing outline prose or
begin any manuscript section.

### Step 3. Paper State, Obligations, Definitions, And QA Contract

Create or update `paper_state` before any section drafting. Point to the
authoritative author-intent revision and hash. Build:

- content obligations linked to intent IDs;
- a definition registry with first-use requirements and any author-authorized
  presupposed knowledge;
- an optional frozen caveat-placement policy plus a `pending_candidate`
  paper-state pointer; create the derived registry only after candidate unit
  IDs exist, then record first satisfaction and the exact repetition triggers;
- a frozen/accepted `evidence-registry/1.0` with a live path and SHA-256 when
  evidence is not already anchored inside the author contract;
- a QA contract with manuscript and contract hashes, mode, scope, required
  roles, and high-risk double-review requirement;
- four ledgers: `intent -> text`, `text -> intent`, `text -> evidence`, and,
  when a baseline exists, `baseline -> candidate`.

Reuse the artifact conservation ledger for the fourth direction. Do not proceed
to drafting when paper facts needed to realize frozen intent are missing.
Declare `qa_mode` explicitly. Map `full_draft`, `proposal_draft`,
`document_translation`, `document_compression`, `major_revision`,
`major_restructure`, and `final_audit` to `exhaustive`; reserve
`bounded_change` for `local_edit` and `local_polish`. A bounded scope also
records identical nonempty `affected_intent_ids` lists in its classification
and revision scope.

When the literature trigger applies, also point to the live
`literature-coverage-contract/1.0`, `reference-library-manifest/1.0`, and
`literature-registry/1.0` objects and record their hashes. Keep bibliographic
  metadata, admission decisions, claim/unit evidence links, and the final visible
  bibliography as four distinct layers. Before drafting, initialize the existing
  text-to-evidence ledger authority as `pending_candidate`; do not invent unit
  IDs. After a provisional QA manifest produces reader-visible unit IDs, add its
  current citekey/unit mappings and hash the completed ledger before citation
  audit. Do not create a second claim-source authority.

### Step 3A. Literature Coverage Contract And Authority Audit

Load the stable workflow's
`econ-writing-workflow/references/literature-grounding/02_literature_coverage_and_citation_integrity.md`
for a full paper/proposal, major revision/restructure, substantive literature
change, or final audit with references. Record search scope, languages,
coverage date, inclusion criteria, applicable functional clusters, gaps, and a
substantive stop condition. A project-specific minimum or target range is valid
only with a recoverable author requirement, journal rule, or reproducible
comparable-paper sample; there is no skill-wide reference-count floor.

A focused contribution passage may foreground roughly five to ten close and
recent papers, but that presentation choice is not a cap on the paper's full
reference set. Missing recent, theory/mechanism, data/measurement/institution,
method/identification/model, or contrary/alternative clusters cannot be offset
by adding more papers to a different cluster.

### Step 4. Table/Figure Plan

Route to `econ-table-figure-design` and decide:

- main-text and appendix tables;
- main-text and appendix figures;
- notes and captions;
- whether an item is confusing, redundant, unsupported, or necessary for a
  content obligation.

Later section agents may request bounded review through
`cross_agent_collaboration_protocol.md`. Any core appendix move remains subject
to the artifact contract and conservation ledger.

### Step 5. Argument Spine

Use the argument logic role to produce a one-sentence paper spine, contribution
hierarchy, section order, mechanism position, robustness/heterogeneity role,
and map of repeated or misplaced material. Every spine element must be
authorized by frozen intent and linked to content obligations.

### Step 6. Patch, Reorder, Or Section Drafting

Load `section_agent_protocol.md` and create a section map and controller-approved
section cards before section work.

Draft new papers in this order:

1. results and table/figure narration;
2. empirical design or model;
3. mechanism, heterogeneity, and robustness;
4. literature positioning;
5. introduction;
6. abstract;
7. conclusion.

Route English prose to `econ-write` and Chinese prose to
`cn-top-econ-writing`. When a section finds a missing empirical, literature,
logic, table/figure, or definition decision, stop that scope and use the
controller-mediated collaboration protocol.

Across sections, preserve evidence strength primarily through calibrated verbs,
claim type, and necessary scope qualifiers. Concentrate a material caveat at
the first place where it changes interpretation. Do not append the same
non-causal, non-extrapolation, or no-long-run disclaimer after every table or
figure; repeat only when the method, sample, period, geography, extrapolation
target, or evidence level changes, standalone readability requires it, or a
journal/referee explicitly asks. There is no per-section quota.

Write boundaries affirmatively first: explain what the estimate, threshold,
scenario, or comparison measures, what it means, and the conditions under
which that interpretation holds. This is explanatory precision, not optimistic
spin. A first or unique standalone negative caveat is not automatically
admissible. Before retaining one, bind it to the exact preceding claim or
quantity, identify a concrete material misreading that calibrated wording does
not already prevent, check whether it introduces a new object only to deny it,
and test whether the same boundary can be integrated into the affirmative
interpretation. Keep a separate negative sentence only as the last necessary
option. If that exact negative proposition is not already frozen by the author,
do not insert or retain it on reviewer judgment alone; return `needs_author`
for the affected unit.

For a mature `major_revision` or `restructure`, use two separate passes:

1. **Architecture pass:** default to `patch_existing` or
   `reorder_existing_blocks`; retain the complete accepted material and edit
   only transitions, duplicated signposting, and coherence around moved blocks.
2. **Compression pass:** begin only after the reordered manuscript and ledger
   are complete and measured. Remove genuine duplication only within recorded
   approval and section budgets.

Never combine clean-slate rewriting, block movement, appendix relocation, and
diction compression in one pass. Update the conservation ledger and cumulative
dashboard after every return.

### Step 7. Interim Artifact Conservation

Run `scripts/audit_manuscript_conservation.py` after architecture integration
and after any compression pass. Restore missing or under-floor material, obtain
scoped approval for `approval_required`, and repair unavailable measurements.
This interim deterministic pass protects the manuscript before semantic review;
it does not replace sentence-level QA or the final post-diction audit.

### Step 8. Deterministic QA Preparation

Load `exhaustive_semantic_qa_protocol.md`. Use
`scripts/prepare_manuscript_qa.py` to generate a current-hash manifest and
contextual packets that capture every reader-visible body, appendix, footnote,
caption, and note object. Every sentence/heading review target must be covered;
paragraph and special-text containers must map completely to their child
targets. Keep exact formula source and signs in a hash-bound formula registry,
refer to formulas by stable IDs in prose units, and include the matching formula
context in reviewer packets. Keep labels, citations, and references as exact
anchors. Treat substantive headings as intent-mapped units, not decorative
containers.

When a caveat-placement policy is active, use a deterministic two-pass
preparation sequence: generate a provisional manifest to obtain candidate unit
IDs; materialize or rebind the derived caveat registry to those IDs and the
candidate hash; then regenerate the final manifest and packets against that
current registry. A pending or stale registry cannot be smuggled into final
packets.

Version 1 accepts `.tex`, `.md`, and `.txt`. Export `.docx` first and record the
export limitation and hash. Python performs deterministic extraction,
identification, hashing, packet construction, and validation only; it does not
call models or make semantic judgments.

When the literature trigger applies, also run
`scripts/audit_citation_integrity.py` in draft mode against the manuscript,
coverage contract, library manifest, literature registry, and text-to-evidence
ledger. Deterministic citation audit checks sets, metadata, hashes, and closure;
it does not decide whether a source is important or semantically supports a
claim.

### Step 9. Independent Semantic Review, Conflict Resolution, And Repair

Dispatch the packets to four isolated native-subagent roles:

- Author-Intent and Coverage;
- Evidence and Claim Strength;
- Definitions and Reader Sufficiency;
- Economic Logic, Scope and Qualifiers.

The Economic Logic, Scope and Qualifiers reviewer checks both missing genuine
boundaries and defensive caveats that add no explanatory information, including
the first or only such sentence. For every standalone negative-caveat
candidate, the reviewer must record the bounded claim or quantity, the concrete
material misreading, whether affirmative calibrated wording already covers it,
whether the sentence introduces a new object only in negation, an affirmative
explanation, and whether a separate negative sentence remains necessary. A
calibrated verb or affirmative explanation may preserve a boundary without a
standalone disclaimer; deleting no-information caveat wording is not a failure
when the governing meaning remains intact. Do not add a fifth sentence-level
caveat reviewer or change the criterion IDs.

For `recommended_disposition: keep`, the reviewer must check author authority.
Only an exact unit-to-frozen-proposition binding permits `pass` with no author
action. Otherwise it returns `needs_author` and
`requires_author_action: true`; no controller or other reviewer may outvote or
self-authorize the sentence.

After author approval, add or supersede the frozen author-intent proposition
with the exact reader-visible negative unit, update the contract revision and
hash, and reprepare all affected QA artifacts. After rejection, integrate the
boundary affirmatively or delete the sentence and re-review. Do not edit only
the old reviewer verdict.

Before dispatch, fill the preparer's `qa-assignment-registry/1.0` template with
the actual assignment ID, native agent ID, task ID, and timestamp for every
packet and the independent fifth role. Hash the completed registry and bind
every result to it. Do not count a same-agent staged role as an independent
review.

In version 1, every sentence/heading target is sent to all four roles. A role
may return `not_applicable` with evidence, but lexical preclassification cannot
prevent a specialist from discovering an unmarked claim, missing definition,
or dropped qualifier. The general rule that high-risk causal, mechanism,
numerical, definition, scope/qualifier, negation, contribution, and normative
units receive at least two independent reviews remains a lower bound.

Reviewers return structured findings only. They do not edit the manuscript or
state. Use `scripts/validate_manuscript_qa.py` to verify current hashes, schema,
unit and role coverage, definition order, intent obligations, conflict closure,
and re-review requirements.

Do not use majority vote. A critical failure, `uncertain`, absent reviewer,
stale or invalid result, uncovered target/container, or unresolved disagreement blocks
delivery. If native independent reviewers are unavailable, return
`audit_incomplete`; do not simulate a pass.

Close a disagreement only with an independent
`qa-conflict-resolution/1.0` artifact bound to a live author-intent, evidence,
definition, or deterministic-gate authority. A reviewer or controller prose
memo is not a resolution artifact.

Resolve findings through frozen intent, inspected evidence, registered
definitions, and the authority order. The controller may apply only the
smallest authorized patch. If repair changes meaning, evidence strength, a
definition's substance, or the conclusion, stop for an author decision and
intent change control. Regenerate hashes and re-review changed units, their
paragraphs, all definition/evidence/qualifier dependencies, and corresponding
abstract, introduction, conclusion, caption, note, and appendix statements.

### Step 9A. Independent Literature Coverage And Citation Integrity Audit

For every triggered task, send the current manuscript, literature authorities,
text-to-evidence ledger, and draft citation report to the independent
Literature Coverage and Citation Integrity Role. Require a hash-bound
`literature-coverage-audit/1.0` result. This role is outside the four semantic
roles and the Main-Text Sufficiency and Conservation Role and must not appear in
`qa-assignment-registry/1.0`.

Pre-register it instead in a separate
`literature-audit-assignment/1.0` record with a unique assignment ID, native
agent ID, task ID, timezone-aware dispatch time, independence declaration, and
all input hashes. Bind the explicit live QA manifest and complete core QA
assignment registry
and forbid reuse of every drafting/integration agent, four semantic reviewers,
and the fifth conservation reviewer. Bind the returned audit to the literature
assignment ID and file hash.
This preserves auditable delegation without changing the stable semantic or
conservation assignment schema.
Populate drafting/integration identities from the native task or current
handoff record. The validator can prove internal consistency of the file chain
and derive the core five reviewer identities, but editable files cannot prove
that the declared runtime actor universe is complete; its assurance therefore
remains `attested: true, proven: false` even on a structurally valid pass.

Missing or stale output is `audit_incomplete`; an unresolved applicable
coverage cluster is `fail`; a claim unsupported by inspected admitted sources
is `evidence_conflict`; unauthorized `nocite` is `approval_required`; and an
unmeasurable format is `metric_unavailable`. The role returns findings only and
does not edit manuscript prose, the registry, ledger, or library.

Run `scripts/validate_literature_audit.py` after the role returns. Supply the
live manuscript, coverage contract, reference-library manifest, literature
registry, text-to-evidence ledger, deterministic citation report, separate
literature assignment, literature audit, current core QA assignment registry
and explicit live QA manifest, plus visible bibliography in final mode. Only
the validator's current `literature-audit-validation/1.0`
`gate_local_status: pass` closes this literature step; the role's own status is
not sufficient, and the local pass does not authorize whole-manuscript
delivery.

### Step 10. Diction And Post-Diction Semantic Re-Review

Run language-specific diction only after substantive semantic findings are
closed:

- English: `econ-write/references/english-diction/`;
- Chinese: `cn-top-econ-writing/references/chinese-diction/`.

Treat diction as a new change set. Regenerate affected units and hashes and send
changed and dependent units to independent semantic re-review. Smooth prose is
not accepted if it loses a concrete qualifier, changes a definition, narrows
content, or strengthens a claim. It may consolidate a semantically redundant
disclaimer; do not mechanically restore that repetition when the frozen
boundary remains satisfied. Any manuscript byte change invalidates the prior
deterministic citation report and literature-role result because both bind the
candidate hash, even when citekeys are unchanged; regenerate them before final
acceptance.

### Step 11. Final Conservation, Main-Text Sufficiency, And Consistency

Before conservation finalization, run `scripts/audit_citation_integrity.py` in
final mode when references are present. First create a current
`bibliography-build-attestation/1.0` that binds the expanded manuscript,
reference-library manifest, every manifested `.bib` file, QA manifest, visible
bibliography, timezone-aware build time, and build tool. Pass that file through
`--bibliography-build-attestation`; final mode fails closed without it. Verify
that manuscript citekeys plus
authorized `nocite` entries exactly generate the visible bibliography. Unused
inventory in a manifested `.bib` is allowed when it is absent from the visible
bibliography. Reject missing citekeys, duplicate citekeys/DOIs, stale `.bbl` or
manual reference lists, unauthorized `nocite`, and any hash mismatch. If
the manuscript, any literature authority, ledger, citation report, or visible
bibliography changed since Step 9A, rerun the independent literature role
against the final hashes and rerun `scripts/validate_literature_audit.py`.

Run the deterministic conservation script against the final post-diction
candidate, then route the baseline, candidate, artifact contract, four-way
ledgers, and current deterministic reports to the independent Main-Text
Sufficiency and Conservation Role.

Before accepting that report, the final validator replays the shipped
conservation auditor over the live sources and contract using the report's
closed `audit_arguments` record. It rejects hand-authored metrics, stale source
universes, omitted sections, and any canonical replay mismatch.

The fifth role must use the dedicated assignment in the filled registry and
return `main-text-sufficiency-audit/1.0`, bound to the exact manifest,
candidate/expanded content, author-intent contract, QA contract, artifact
contract, assignment registry, and applicable conservation report hashes. Its
native agent/task identity may not be reused by any semantic reviewer.

- `pass`: continue to final consistency;
- `approval_required`: restore material or obtain and record scoped approval,
  then rerun;
- `fail`: restore missing or under-floor material and rerun;
- `metric_unavailable`: repair the measurement; never treat it as a pass.

A structurally valid non-pass fifth-role result retains that real status and
all of its findings. Reserve `audit_incomplete` for a missing, malformed,
stale, unassigned, or otherwise unverifiable fifth-role record.

Final consistency checks paper state versus draft, cross-section meaning,
definitions, variables, table/figure references, magnitudes, concrete
evidence-boundary semantics and non-redundant caveat placement,
contribution preservation, manuscript voice, and unresolved items. Delivery is
blocked by `clarification_required`, `evidence_conflict`, `approval_required`,
`fail`, `metric_unavailable`, or `audit_incomplete` from any applicable gate.

## Final Deliverable

Return the draft or revision with:

```text
Author-intent revision and gate:
Input audit:
Paper spine:
Table/figure placement:
Drafted or patched sections:
Preserved claims:
Semantic-QA status and reviewed manuscript hash:
Literature-coverage and citation-integrity status and hashes:
Four-way ledger status:
Artifact-contract and main-text-sufficiency status:
Remaining TODOs or blocking findings:
Risks:
Next pass:
```
