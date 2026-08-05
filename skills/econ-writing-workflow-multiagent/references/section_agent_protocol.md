# Section Agent Protocol

## Contents

- Purpose and controller duties
- Section card and mature-draft rules
- Section agents
- Section return
- Controller integration

## Purpose

Use this protocol when a paper task is large enough that each major section needs its own focused pass. The controller remains responsible for the whole paper; section agents work only inside the section contract assigned to them.

This protocol adds section-level specialization without letting chapters drift away from the central argument.

## Controller Duties

Before assigning section agents, the controller must settle:

- `paper_state`;
- the stable workflow's one authoritative author-intent revision, with the exact
  drafting scope `frozen-current + ready`;
- content obligations and definition-registry entries for the section;
- the optional frozen caveat-placement policy slice and, for an existing
  candidate only, its current derived registry slice, distinguishing semantic
  boundary preservation from repeated disclaimer wording;
- literature coverage, library, registry, and audit pointers when the
  literature trigger applies;
- one-sentence paper spine;
- contribution hierarchy;
- table/figure placement plan;
- artifact contract, accepted baseline, and cumulative length/depth dashboard when revising a mature draft;
- stable source-block IDs and an initial conservation ledger;
- target language and journal style;
- missing non-semantic facts and `TODO` items; semantic or evidence gaps retain
  their blocking status.

Then create a section map. No section agent should draft before receiving its section card.

There is no compatibility exception that permits drafting from `partial`,
`proposed`, unconfirmed, held, materially unresolved, or evidence-conflicted
intent. If a section uncovers a material ambiguity, return it to the controller
for author clarification instead of drafting a plausible interpretation.

If a section needs table/figure, argument-logic, literature, diction, or empirical review, use `cross_agent_collaboration_protocol.md`. Section agents should request functional review through the controller rather than contacting functional agents directly.

## Section Card

```text
card_id:
section_id:  # legacy card-ID alias only; if present it must equal card_id
section_name:
baseline_section_id:  # mature draft, exact live manuscript section
baseline_section_name:
candidate_section_id:  # mature draft, must agree with validated ledger destination
candidate_section_name:
target_language:
section_purpose:
reader_question:
paper_spine_link:
author_intent_revision_id:
author_intent_hash:
intent_ids_to_realize:
content_obligations:
prohibited_claims_or_implications:
definition_registry_slice:
evidence_anchors:
caveat_placement_policy_slice:
caveat_placement_registry_slice:
literature_coverage_contract_slice:
must_preserve:
must_not_claim:
inputs_to_read:
tables_figures_to_use:
handoff_from_previous_section:
handoff_to_next_section:
child_skill_to_use:
rewrite_mode:
baseline_words:
target_word_range:
maximum_reduction_pct:
minimum_depth_questions:
must_remain_main:
allowed_appendix_moves:
ledger_slice:  # split cards only; exact live prose block IDs
  baseline_block_ids:
  destination_block_ids:
qa_dependency_unit_ids:
open_todos:  # non-semantic facts only
blocking_statuses:
```

For mature manuscripts, do not use `section_id` to identify manuscript
sections. Use the explicit baseline/candidate selectors above. If a section is
split across multiple cards, give every card a nonoverlapping `ledger_slice`
and make the slices exactly cover the baseline section's live prose blocks.
The deterministic conservation audit rejects ambiguous or double-counted
split/merge attribution before a section agent may proceed.

If cross-agent review changes evidence placement, contribution framing, claim strength, or empirical facts, the controller must update the section card before the section agent revises.

## Mature-Draft Rules

- Default each mature-draft card to `patch_existing`. Use `reorder_existing_blocks` when the architecture pass requires movement without deletion.
- Under `patch_existing`, preserve the relative order of every baseline block
  that remains mapped to main text; an unmapped insertion may be added without
  being treated as a reorder. A card-level patch restriction also applies to
  the mapped blocks in that card even when the artifact-wide mode permits
  broader reordering.
- Return patches or block moves instead of a replacement section unless the
  artifact contract contains the author's recoverable `full_redraft`
  authorization and exact scope, and the card inherits that rewrite mode.
  A card may narrow top-level authority but cannot create or widen it;
  controller preference alone cannot populate the approval record.
- Give every source block a ledger disposition. Do not let a block disappear because the agent omitted it from newly generated prose.
- Recommend an appendix move when appropriate, but execute it only when
  the card's effective `allowed_appendix_moves` authorizes the section title or
  exact source label and the ledger records recoverable, scoped user approval
  for that exact move. Neither record substitutes for the other.
- Keep a main-text replacement or summary for every appendix move that affects a central reader question.
- Do not assume another section covers an omitted object without a verified destination in the section map and conservation ledger.
- Treat length ranges and depth questions as guardrails. Do not add padding or preserve genuine repetition merely to hit a number.
- Apply “shortest complete version” only to the abstract. Do not generalize it to the manuscript or other sections.

## Section Agents

### Abstract Agent

Purpose: compress the paper spine into the shortest complete version.

Must preserve:

- research question;
- main contribution;
- main result or proposition;
- mechanism if it is part of the contribution;
- key data/design feature;
- any concrete caveat necessary for standalone interpretation; do not append a
  generic disclaimer when calibrated claim language already preserves the
  evidence boundary. State affirmatively what the result measures and means
  before considering a separate negative sentence.

Must not:

- add results not in `paper_state`;
- delete secondary contribution if the controller marks it as strategic;
- turn a mixed theory-empirical paper into a pure measurement paper.

### Introduction Agent

Purpose: make the reader understand the question, why it matters, how the paper answers it, what it finds, and what it contributes.

Must preserve:

- problem tension;
- design or argument path;
- main result and magnitude when available;
- mechanism;
- contribution relative to literature;
- boundary conditions that materially change interpretation; consolidate a
  boundary already stated under unchanged scope instead of repeating it.

Must not:

- bury the main result;
- turn literature review into a citation list;
- let background crowd out the research question.

### Literature Coverage And Positioning Agent

Purpose: organize close literature by contribution margin while realizing the
applicable clusters in the literature-coverage contract.

Must preserve:

- closest literatures;
- what each literature explains;
- what margin this paper adds;
- limits of claim strength when sources are missing.
- recent, theory/mechanism, data/measurement/institution,
  method/identification/model, and contrary/alternative clusters marked
  applicable by the contract.

Must not invent citations, treat five to ten foregrounded papers as the full
reference ceiling, or claim "first" unless verified. This drafting agent does
not replace the independent Literature Coverage and Citation Integrity Role.

### Theory And Mechanism Agent

Purpose: connect economic actors, constraints, behavior, and testable implications.

Must preserve:

- actor;
- constraint or incentive;
- behavior change;
- observable implication;
- link to later main result, mechanism, or heterogeneity evidence.

Must not write abstract concepts without empirical or model anchors.

### Empirical Design Agent

Purpose: explain sample, variables, identification, model, and comparison.

Must preserve:

- data source and period;
- unit of observation;
- treatment or key variable;
- comparison group or model object;
- fixed effects, controls, clustering, and sample restrictions when known;
- a concrete identification assumption or limitation when omission would
  change the effective claim; do not repeat a generic non-causal disclaimer
  after every result under the same design.

Must not invent estimation details or overstate causality.

### Main Results Agent

Purpose: explain the main table or figure as the answer to the research question.

Must preserve:

- core coefficient, sign, magnitude, or proposition;
- an affirmative explanation of what the coefficient, threshold, scenario, or
  proposition measures and means;
- sample comparability;
- design credibility;
- link to mechanism or next section.

Must not do column-by-column narration unless needed for identification, or
append a first or unique negative caveat merely because it is technically true.
Retain a standalone negative sentence only when it prevents a concrete material
misreading not already blocked by calibrated wording and cannot be integrated
into the affirmative interpretation. A section agent still may not add or
retain that sentence unless its exact proposition is frozen by the author; it
must otherwise return the proposed contrast for author adjudication rather
than place it in manuscript prose.

### Mechanism Agent

Purpose: explain why the main result arises.

Must preserve:

- mechanism promised by the theory or introduction;
- evidence type and strength;
- link between mechanism measure and economic behavior.

Must not claim proof when evidence is only suggestive.

### Heterogeneity Agent

Purpose: show where, for whom, or under what conditions the effect differs.

Must preserve:

- reason for each split;
- link to mechanism, policy target, or scope condition;
- whether the result belongs in main text or appendix.

Must not report every possible split.

### Robustness Agent

Purpose: answer threats to interpretation.

Must preserve:

- the threat each check addresses;
- what changes and what remains stable;
- main text versus appendix placement.

Must not write all checks as "results remain significant".

### Conclusion Agent

Purpose: return to the research question, contribution, scope, and implication.

Must preserve:

- central finding;
- mechanism or theoretical takeaway;
- boundary conditions only when they materially affect the conclusion and have
  not already been adequately concentrated elsewhere;
- policy or research implication supported by the paper.

Must not introduce new evidence, new literature, or unsupported policy claims.

## Section Return Format

```text
section_id:
section_agent:
inputs_read:
section_claim:
draft_or_revision:
intent_ids_realized:
content_obligations_realized:
definitions_introduced_or_used:
evidence_anchors_used:
must_preserve_check:
words_before:
words_after:
blocks_revised_reordered_merged_moved_or_omitted:
conservation_ledger_updates:
main_text_self_containment_check:
approval_needed:
conflicts_with_paper_state:
handoff_to_next_section:
remaining_todos:  # non-semantic facts only
blocking_statuses:
```

## Controller Integration Pass

After section agents return, the controller must check:

- all section claims point to the same paper spine;
- key terms, variables, and mechanisms are stable;
- main contribution and secondary contribution are preserved;
- no section repeats another section's job;
- tables and figures are cited only where they serve the argument;
- concrete evidence boundaries remain semantically preserved, while
  no-information defensive disclaimers, including a first or unique standalone
  sentence, are either replaced by an affirmative explanation or removed under
  the frozen caveat-placement policy and, once candidate unit IDs exist, the
  derived registry rather than restored mechanically;
- when literature audit is triggered, the coverage contract, library,
  registry, ledger, manuscript citekeys, and audit hashes are current and the
  independent literature role has no blocking status;
- the integrated draft is ready for deterministic manifest generation and
  independent semantic review; section-agent self-checks are not acceptance QA;
- every mature-draft source block has a ledger disposition and every executed appendix move was authorized;
- section and cumulative word/page changes remain within the artifact contract;
- the main text remains self-contained for the section's reader question.

Update the cumulative length/depth dashboard after every section return. If a section or the integrated manuscript crosses an approval trigger, stop further compression and send the candidate to the Main-Text Sufficiency and Conservation Role before continuing.

If a section fails this check, return it to the relevant section agent with a narrowed revision card.

After section integration, follow `exhaustive_semantic_qa_protocol.md`. Do not
send a complete paper/proposal, document-level translation/compression, or major
revision to diction until the substantive semantic gate passes. After diction,
re-review changed and dependent units before the final conservation and
main-text-sufficiency gate.
