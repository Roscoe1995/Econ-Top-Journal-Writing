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

## Literature Positioning Role

Checks literature grouping, contribution margins, citation grounding, and whether claims are supported by supplied or inspected sources.

Do not invent citations or closest-literature claims.

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

In version 1, all four roles review every sentence/heading target. A specialist
may return `not_applicable` with evidence, but a lexical pre-classifier cannot
exclude the very reviewer who could discover an unmarked claim, missing
definition, or lost qualifier. The general rule that causal, mechanism,
numerical, definition/first-use, scope/qualifier, negation,
contribution-boundary, and normative units require at least two independent
semantic reviews remains a lower bound. Reviewers must be isolated for
first-pass findings and must not see another reviewer's verdict or a
controller-authored repair.

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

Run this role only after substantive semantic findings are closed. Treat its
edits as a new change set and send changed and dependent units through
independent semantic re-review before acceptance.

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

Checks terminology, variables, table and figure numbers, magnitudes, caveats,
contribution preservation, manuscript voice, unresolved non-semantic `TODO`
items, and any blocking status after the sufficiency and conservation gate
passes.

This role should be skeptical and should not rewrite the paper unless the controller asks for a final integrated pass.
