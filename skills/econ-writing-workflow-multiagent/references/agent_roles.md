# Agent Roles

## Controller

Owns the workflow. Maintains `paper_state`, the artifact contract, conservation ledger, and cumulative dashboard; assigns roles, integrates outputs, resolves conflicts, and decides what the user sees.

The controller must not let specialized agents rewrite the paper's main claim
without author-intent change control, a corresponding `paper_state` update, and
an explicit flag. It alone may apply accepted bounded patches; semantic
reviewers never edit the manuscript.

## Input Audit Role

Checks whether the provided materials are enough for the requested output.

Focus:

- research question;
- data, sample, variables, design;
- tables and figures;
- literature materials;
- accepted baseline, project artifact constraints, and available main-text measurements;
- target language and journal;
- missing non-semantic facts and `TODO` items; semantic or evidence gaps keep a
  blocking status.

## Argument Logic Role

Checks the paper spine, contribution hierarchy, section order, repetition, emphasis, and whether results serve the main line.

Route to:

- stable workflow `econ-writing-workflow/references/argument-logic/` for general logic;
- `cn-top-econ-writing/references/argument-logic/` for Chinese top-journal logic.

## Table And Figure Role

Judges main-text versus appendix placement, table/figure function, notes, captions, visual style, palettes, and export quality.

Route to `econ-table-figure-design`.

## Literature Coverage And Citation Integrity Role

This is an independent functional audit role outside the four sentence-level
semantic roles and the fifth Main-Text Sufficiency and Conservation Role. Do
not add it to `qa-assignment-registry/1.0`, change any semantic machine ID, or
use its output to satisfy semantic unit coverage.

Pre-register each run in a separate, hash-bound
`literature-audit-assignment/1.0` record containing the native agent ID, task
ID, dispatch time, independence declaration, and exact input hashes. The role
result must bind that assignment ID and hash; absence, reuse, or mismatch is
`audit_incomplete`. The assignment also binds the current core QA-assignment
registry hash and lists as forbidden every drafting/integration
agent plus all four semantic reviewers and the fifth conservation reviewer;
the literature reviewer native-agent ID may not appear in that set.
Core reviewer IDs are canonically derived from the core assignment registry;
drafting and integration IDs must come from the current native task or handoff
record. File validation can attest that the declared records are internally
consistent, but cannot prove runtime isolation or detect an actor omitted from
all editable files. Report that assurance limit explicitly as `proven: false`.

Run it for a full paper or proposal, major revision or restructure,
substantive literature change, or final audit of a manuscript with references.
Do not trigger it for spelling, pure wording, or a bounded edit that leaves
claims and citation relationships unchanged.

Read the current manuscript, `literature-coverage-contract/1.0`,
`reference-library-manifest/1.0`, `literature-registry/1.0`, and the existing
`text_to_evidence_ledger`, plus the deterministic citation-integrity report.
In final mode, also read the build attestation and visible bibliography bound
inside that report.
Check:

- every applicable coverage cluster, including recent work and contrary or
  alternative evidence when the contract marks them applicable;
- whether focused contribution prose uses a defensible comparison set without
  treating five to ten foregrounded papers as a paper-wide reference cap;
- whether each substantive source has been inspected, admitted, and assigned
  a valid coverage or evidence role;
- whether manuscript claims are actually supported at their stated strength;
- whether manuscript citekeys, authorized `nocite` items, and the final visible
  bibliography form a current-hash closed set.

Return exactly one hash-bound `literature-coverage-audit/1.0` object with the
contract, library-manifest, registry, manuscript, ledger, deterministic-report,
and, in final mode, visible-bibliography hashes; structured
cluster/source/claim findings; and a gate status. Do not edit prose, the
registry, or the reference library, and
do not invent citations or closest-literature claims.

The controller must then run `scripts/validate_literature_audit.py` with the
explicit live QA manifest and its complete core assignment registry. The role's
self-reported `gate_status`, or a deterministic citation-integrity pass by
itself, is not an acceptance artifact.

Use these fail-closed outcomes: missing, stale, malformed, or absent required
role output is `audit_incomplete`; an unresolved applicable coverage gap is
`fail`; a manuscript claim unsupported by admitted inspected sources is
`evidence_conflict`; an unauthorized `nocite` is `approval_required`; and a
format or metric that cannot be measured reliably is `metric_unavailable`.
Only a current-hash result with no blocking finding may be `pass`.

## Exhaustive Semantic QA Roles

Use these four isolated native-subagent roles after a deterministic QA manifest
has been prepared. Follow `exhaustive_semantic_qa_protocol.md` for packets,
coverage, findings schema, and gate decisions.

### Author-Intent And Coverage

Machine ID: `author_intent_coverage`.

Review every sentence and substantive-heading review target against frozen
intent and content obligations. Confirm that each reader-visible container is
fully represented by its child review targets.
Check `intent -> text` for omissions and `text -> intent` for unauthorized
claims, including changed emphasis, forbidden implications, and inconsistent
abstract/body/conclusion/caption formulations.

### Evidence And Claim Strength

Machine ID: `evidence_claim_strength`.

Review factual, numerical, causal, theoretical, mechanism, and normative claims
against inspected evidence and its maximum warranted strength. Flag a missing
anchor, invented fact, causal upgrade, mechanism overstatement, changed sign or
magnitude, and unsupported policy implication.

### Definitions And Reader Sufficiency

Machine ID: `definitions_reader_sufficiency`.

Review terms, symbols, variables, actors, samples, comparisons, and model
objects for definition before use, definition adequacy, consistent meaning,
clear reference, and reader comprehension. Treat deterministic first-use order
as evidence, not proof that the definition is sufficient.

### Economic Logic, Scope And Qualifiers

Machine ID: `economic_logic_scope_qualifiers`.

Review actor-constraint-behavior-outcome logic, comparison, direction, timing,
population, geography, scope, negation, uncertainty, caveats, and the separation
of association, causality, heterogeneity, and mechanism evidence.

Check both failure directions: a real evidence boundary may not disappear or
be weakened, and a first, unique, or repeated no-information defensive sentence
should not be added after a table, figure, or result paragraph. Calibrated verbs
and claim type may fully preserve a boundary without a standalone disclaimer.

For every stand-alone negative caveat, identify the exact preceding claim,
number, estimate, threshold, scenario, or model object it limits; the concrete
materially stronger reading it blocks; whether calibrated wording already
blocks that reading; whether the caveat introduces a new outcome or estimand
only to deny it; and whether the needed meaning can instead be stated as an
integrated affirmative explanation of what the object is and what it shows.
`Affirmative` is explanatory, not favorable, and must not strengthen the
evidence. If no material misreading remains, flag the negative sentence for
deletion or affirmative rewrite. If a negative contrast remains necessary,
require it to bind to the exact object and treat a separate sentence as the
last resort. The reviewer may recommend that last resort but may not authorize
it. Return `pass + keep` only when the exact unit is bound to a frozen
author-intent proposition; otherwise return `needs_author` with
`requires_author_action=true` and let the author decide.

A limitation is repeated only when method, sample, period, geography,
extrapolation target, or evidence level changes; a standalone
abstract/caption/note needs it; or a journal/referee explicitly requires it. Do
not enforce a per-section count, and do not demand a long-run caveat when the
manuscript makes no long-run claim.

In version 1, all four roles review every sentence/heading target. A specialist
may return `not_applicable` with evidence, but a lexical pre-classifier cannot
exclude the very reviewer who could discover an unmarked claim, missing
definition, or lost qualifier. The general rule that causal, mechanism,
numerical, definition/first-use, scope/qualifier, negation,
contribution-boundary, and normative units require at least two independent
semantic reviews remains a lower bound. Reviewers must be isolated for
first-pass findings and must not see another reviewer's verdict or a
controller-authored repair.

If this role discovers a standalone negative caveat that lacks the
`negative_caveat_candidate` flag, it must not return an ordinary pass. Return
`risk_or_role_escalation` with that exact category and source span. The
controller then records the exact phrase or unit as a QA-contract risk marker,
regenerates the manifest and packets, and obtains the structured admission
evidence. This semantic escalation closes residual lexical misses without
letting Python decide whether the caveat is justified.

The structured rationale is review evidence, not authority. Long or polished
free text cannot convert an unapproved `keep` into a pass. Python checks the
schema, standard sentinel values, hashes, and exact frozen-author binding; the
isolated reviewer judges meaning, and the author adjudicates any exceptional
keep that was not already frozen.

Each role returns structured findings only, including unit and criterion IDs,
exact source anchor, verdict, evidence, reason, severity, confidence, and
whether author action is required. Do not use majority vote. A critical
failure, `uncertain`, missing reviewer, invalid or stale result, unresolved
disagreement, or unreviewed dependency blocks delivery. If native independent
subagents are unavailable, return `audit_incomplete`; staged same-agent review
cannot satisfy this gate.

## Section Drafting Role

Drafts sections only after the controller has settled the paper state, table/figure plan, and argument spine.

For large paper tasks, do not treat this as one generic writer. Use `section_agent_protocol.md` to create section cards for abstract, introduction, literature, theory/mechanism, empirical design, main results, mechanism, heterogeneity, robustness, and conclusion agents.

Route to:

- `econ-write` for English;
- `cn-top-econ-writing` for Chinese.

## Diction And Linter Role

Polishes language after structure is stable.

Run this role only after substantive semantic findings and every triggered
literature gate are current and `pass`. Treat its edits as a new change set and
send changed and dependent units through independent semantic re-review; when
the paper-level literature trigger is active, also regenerate the citation
report, assignment, and literature audit against the changed candidate before
acceptance.

Route to:

- `econ-write/references/english-diction/` for English;
- `cn-top-econ-writing/references/chinese-diction/` for Chinese.

## Main-Text Sufficiency And Conservation Role

Audit the integrated candidate against the accepted baseline, artifact contract, cumulative dashboard, and conservation ledger. Keep this role independent from drafting and diction.

Report:

- missing main-text functions and unjustified appendix dependencies;
- cumulative main-text word and page changes;
- source blocks without a ledger disposition;
- whole sections or core labels that disappeared or crossed the appendix boundary;
- sections below their approved budget or minimum-depth questions;
- deterministic audit status and unresolved approval triggers.

Do not polish prose, silently restore text, or change the artifact contract. Block diction and finalization when status is `fail`, `metric_unavailable`, or unapproved `approval_required`; return the recovery or approval decision to the controller and user.

This role is a whole-manuscript and main-text sufficiency gate, not a substitute
for sentence-level semantic roles. Run it after the final post-diction semantic
re-review and deterministic conservation audit. Also block on
`audit_incomplete`, `clarification_required`, or `evidence_conflict` from the
semantic QA pipeline.

For `exhaustive` QA, dispatch it as the fifth native assignment in
`qa-assignment-registry/1.0`. Its native agent and task identities must not be
reused by any of the four semantic roles. Return the exact
`main-text-sufficiency-audit/1.0` object defined in
`exhaustive_semantic_qa_protocol.md`; a prose memo cannot satisfy the gate.
Do not run or accept this whole-manuscript role for `bounded_change`; that mode
reports only the reviewed change/dependency closure.

## Final Consistency Role

Checks terminology, variables, table and figure numbers, magnitudes, concrete
evidence-boundary semantics and their non-redundant placement, contribution
preservation, manuscript voice, unresolved non-semantic `TODO` items, and any
blocking status after the sufficiency and conservation gate passes.

This role should be skeptical and should not rewrite the paper unless the controller asks for a final integrated pass.
