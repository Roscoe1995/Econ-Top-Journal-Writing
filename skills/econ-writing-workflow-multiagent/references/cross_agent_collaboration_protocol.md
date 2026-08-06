# Cross-Agent Collaboration Protocol

## Contents

- Purpose and core rule
- Collaboration types
- Requests, returns, and controller updates
- Trigger and forbidden patterns
- Integration check

## Purpose

Use this protocol when section agents and functional agents need to work together. Collaboration must be controller-mediated: agents should not freely rewrite each other's decisions or create parallel paper states.

The goal is two-way coordination:

```text
section need -> controller -> functional review -> controller updates section card -> section revision
```

## Core Rule

The controller is the hub. Section agents may request functional review; functional agents may flag section problems; only the controller updates `paper_state`, table/figure placement, or section cards.

## Collaboration Types

### Table/Figure Collaboration

Use when a section depends on tables, figures, notes, captions, palettes, or main-text versus appendix placement.

Flow:

1. Section agent states the section's evidence need.
2. Controller sends a bounded request to the table/figure agent.
3. Table/figure agent returns placement, reading focus, note/caption requirements, and risks.
4. If the proposal moves a core object to the appendix, the agent states what remains in the main text and the cumulative artifact-budget effect; the controller runs the approval gate.
5. Controller updates the section card and conservation ledger.
6. Section agent drafts or revises using the updated card.

### Argument-Logic Collaboration

Use when a section may drift from the paper spine, repeat another section, delete a contribution, or overemphasize a secondary point.

Flow:

1. Section agent flags a logic uncertainty.
2. Controller asks the argument-logic agent to evaluate the section's function and order.
3. Argument-logic agent returns spine fit, missing link, redundancy, and must-preserve claims.
4. Controller updates the section card or paper spine.
5. Section agent revises within the new boundary.

### Literature Collaboration

Use when a section needs contribution positioning, closest-literature grouping, claim strength, or citation grounding.

Flow:

1. Section agent states the literature claim it wants to make.
2. Controller asks the literature positioning agent to check support and margin.
3. Literature agent returns the allowed claim, unsupported claim, source gap,
   blocking evidence status, and only non-semantic citation-metadata TODOs.
4. Controller updates the section card.
5. Section agent writes only the supported literature positioning.

### Diction Collaboration

Use only after section logic is stable and the substantive semantic QA gate has
passed for the integrated candidate.

Flow:

1. Section agent returns a structurally acceptable draft.
2. Controller sends the draft to the diction/linter role.
3. Diction role cleans prose but must preserve claims, caveats, variables, magnitudes, and table/figure references.
4. Controller regenerates the affected QA units and routes the changed and
   dependent set to independent semantic re-review.
5. Only a current-hash validated pass establishes that polish did not narrow or
   inflate the section claim.

### Empirical Collaboration

Use when writing depends on variable construction, sample changes, regression estimates, or reproducibility.

Flow:

1. Section agent identifies a missing empirical fact or ambiguity.
2. Controller routes the empirical task to `empirical-econ-workflow`.
3. Empirical output updates `paper_state` only after the controller verifies what was actually produced.
4. Section agent revises using the verified fact.

### Exhaustive Semantic QA Collaboration

Use after integration for complete papers/proposals, document-level
translations or compressions, and major revisions. Use a
bounded changed-unit set for local polish.

Flow:

1. Controller runs deterministic preparation and fixes the manifest and
   contract hashes.
2. Controller sends contextual packets to isolated Author-Intent and Coverage,
   Evidence and Claim Strength, Definitions and Reader Sufficiency, and
   Economic Logic, Scope and Qualifiers reviewers.
3. Reviewers return structured findings only and do not edit text or state.
4. Controller validates coverage and resolves conflicts by authority rather
   than majority vote.
5. Controller applies the smallest authorized patch and sends changed and
   dependent units to independent re-review.
6. Missing reviewers, `uncertain`, stale or invalid results, uncovered targets
   or containers,
   and unresolved disagreements return `audit_incomplete` or the more specific
   blocking status; they never pass by default.

## Section-To-Functional Request

```text
requesting_section:
section_claim:
functional_role_needed:
question_for_functional_agent:
current_section_card_fields:
evidence_or_text_to_review:
decision_needed:
deadline_or_scope:
```

## Functional Return

```text
functional_role:
inputs_read:
answer:
recommended_update_to_section_card:
recommended_update_to_paper_state:
proposed_ledger_update:
main_text_explanation_retained:
cumulative_artifact_budget_effect:
risks:
needs_user_confirmation:
```

## Controller Update

```text
controller_decision:
paper_state_update:
section_card_update:
instructions_to_section_agent:
instructions_to_functional_agent:
unresolved_todos:  # non-semantic facts only
blocking_statuses:
```

## When To Trigger Cross-Agent Review

Trigger functional review when:

- a section needs a table or figure not yet admitted to main text;
- a section cannot decide whether a result belongs in main text or appendix;
- a functional agent proposes moving central data construction, sample audit, identification/model environment, main results, or core robustness discussion to the appendix;
- any proposed relocation would cross a section or cumulative artifact-budget trigger;
- a section wants to make a literature claim not grounded in inspected sources;
- a section's contribution framing conflicts with the paper spine;
- a diction pass may remove a mechanism, magnitude, caveat, or secondary contribution;
- empirical details are missing or inconsistent.
- an integrated manuscript is ready for mandatory exhaustive semantic QA, or a
  bounded polish changed a sentence, paragraph, definition, evidence link, or
  cross-section dependency.

Do not trigger ordinary drafting-time functional review for every sentence.
The separate exhaustive semantic acceptance phase still assigns every
reader-visible object a manifest ID, proves that every container is covered by
sentence children, and gives every sentence/heading review target the required
record, specialist roles, and contract-declared independent-review coverage.

## Forbidden Patterns

- A section agent directly changes table/figure placement without controller approval.
- A functional or section agent executes an unapproved core appendix move or treats appendix existence as sufficient main-text coverage.
- A table/figure agent rewrites prose beyond its evidence and presentation scope.
- A literature agent invents citations to support a section.
- A diction agent removes caveats or magnitudes for smoothness.
- Two agents maintain separate versions of the paper state.
- A semantic reviewer edits the manuscript, sees another first-pass verdict, or
  approves its own repair.
- The controller substitutes sequential same-agent roles for required native
  independent reviewers or resolves disagreement by majority vote.

## Integration Check

After a cross-agent loop, the controller must confirm:

- the updated section card reflects the functional decision;
- the section agent used the updated card;
- any changed claim remains consistent with `paper_state`;
- any appendix move has an authorized ledger entry, a sufficient main-text replacement, and an updated cumulative budget;
- any unresolved semantic, evidence, definition, or scope issue retains its
  blocking status; only a missing non-semantic fact appears as a concrete
  `TODO`;
- the current manifest and finding hashes match the candidate and all required
  changed/dependency re-reviews are complete;
- the final user-facing output does not expose unnecessary internal agent chatter.
