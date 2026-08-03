# Controller Startup Checklist

## Purpose

Run this checklist before any multi-agent or staged-agent economics writing task. It prevents the controller from jumping directly into drafting before author intent, shared state, section boundaries, and cross-agent rules are active.

## Startup Steps

1. Confirm this task is large enough for `econ-writing-workflow-multiagent`.
   - If it is a short polish, one abstract, one table note, or one caption, route to the stable workflow or a child skill instead.

2. Activate the controller role.
   - The controller owns `paper_state`, section cards, cross-agent requests, integration, conflict resolution, and final user-facing output.

3. Read the nearest project instructions and classify the artifact task.
   - Record `task_mode`, whether an accepted mature baseline exists, and the default `rewrite_mode`.
   - Record the classification basis, changed artifact or source ranges, and
     inspected substantive dependencies. Do not use a bare `local_edit` label
     to reduce QA coverage.
   - Do not infer permission to shorten from a request to improve structure or prose.

4. Locate the one authoritative author-intent contract governed by the stable
   workflow.
   - Load the stable author-intent reference and
     `exhaustive_semantic_qa_protocol.md`.
   - Inspect available manuscript, plan, evidence, definitions, and prior
     author decisions before asking questions.
   - If material meaning is not unique, ask a grouped clarification and teach
     the complete scope back to the author. An explicit confirmation normally
     records confirmation and freeze authorization in the same event.
   - Do not delegate claim-bearing drafting until the applicable intent
     revision is `frozen-current + ready`. `Partial`, `proposed`, unconfirmed,
     held, materially unresolved, or evidence-conflicted intent has no drafting
     compatibility exception.

5. Classify `qa_mode`.
   - Explicitly map `full_draft`, `proposal_draft`, `document_translation`,
     `document_compression`, `major_revision`, `major_restructure`, and
     `final_audit` to `exhaustive`.
   - Map only `local_edit` and `local_polish` to `bounded_change`; define changed units, their
     paragraph and adjacent context, and all affected definitions and
     cross-section dependencies.
   - Require a nonempty classification basis, changed set, and explicit
     dependency set before accepting `bounded_change`. Record the same explicit
     nonempty `affected_intent_ids` list in the task classification and revision
     scope; every ID must come from frozen author
     authority and receive a location and re-review.
   - Reject missing modes, unknown stages, and stage/mode mismatches rather
     than defaulting to a cheaper audit.

6. Create the artifact contract when the task is a full draft, mature revision, restructuring, shortening, or appendix relocation.
   - Load `artifact_conservation_and_depth_gates.md`.
   - Fix the accepted baseline path and hash, measurement method, target basis, approval triggers, and `must_remain_main` objects.
   - Measure the baseline before delegation. Record unavailable or ambiguous metrics instead of substituting zero.
   - For a candidate-only full draft or proposal, freeze nonempty content
     obligations plus one canonical `artifact_contract.section_cards` record
     per main-text section, including target range, minimum-depth questions,
     and must-remain-main references.
   - For page constraints, bind main-text-only page counts to the exact PDFs and
     hashes; never substitute total PDF pages.

7. Load or create `paper_state`.
   - Use `paper_state_protocol.md`.
   - Point to the authoritative author-intent revision and hash; do not copy it
     into a parallel contract.
   - Build content obligations, the definition registry, QA contract, and
     four-way ledgers before drafting.
   - Mark only non-semantic missing facts as concrete `TODO` items.
   - Do not invent data, citations, results, mechanisms, or sample details.

8. Decide which coordination mode is needed.
   - Functional-only: table/figure, literature, argument logic, diction, empirical review.
   - Section-agent mode: abstract, introduction, literature, theory/mechanism, empirical design, main results, mechanism, heterogeneity, robustness, conclusion.
   - Full workflow: result package to paper draft or major revision.

9. Create section cards when section agents are needed.
   - Use `section_agent_protocol.md`.
   - No section agent drafts before receiving a controller-approved section card.
   - For mature drafts, include rewrite mode, baseline/target range, `must_remain_main`, allowed appendix moves, and a ledger slice.

10. Use controller-mediated cross-agent collaboration when needed.
   - Use `cross_agent_collaboration_protocol.md`.
   - Section agents may request functional review, but only the controller updates `paper_state`, table/figure placement, or section cards.

11. Before semantic dispatch, complete the native assignment registry.
   - Fill every semantic packet and the one fifth-role assignment with unique
     assignment/task IDs, native-agent identities, and timezone-aware times;
     include the fifth assignment only for `exhaustive` QA.
   - Hash the filled registry and bind every review result to it.
   - If the required independent native agents are unavailable, record
     `audit_incomplete`; do not run a same-agent simulation and call it passed.

## Startup Output

Before delegating, produce or internally maintain:

```text
coordination_mode:
author_intent_contract_path_or_id:
author_intent_revision_id:
author_intent_hash:
author_intent_status:
author_intent_gate_status:
qa_mode:
task_stage:
task_classification_basis:
changed_artifact_or_source_ranges:
substantive_dependencies_checked:
affected_intent_ids:
qa_contract_status:
paper_state_status:
artifact_contract_status:
baseline_main_length:
target_main_length:
rewrite_mode:
compression_permission:
must_remain_main:
approval_triggers:
section_agents_needed:
functional_agents_needed:
semantic_reviewers_available:
first_handoff:
blocking_todos:  # legacy field; non-semantic TODO facts only
blocking_statuses:
```

## Stop Conditions

Pause and ask the user or return a bounded plan if:

- research question, main result, data/sample, or identification/model facts are missing for a requested full draft;
- the exact drafting scope lacks a complete `frozen-current + ready`
  author-intent contract, including when only part of the contract was
  confirmed;
- a requested claim depends on unavailable literature or uninspected sources;
- a mature-manuscript restructuring may materially shorten the main text but has no accepted baseline, target, or approval scope;
- the baseline, appendix boundary, or required page metric is unavailable or ambiguous and the proposed edit would cross an artifact gate;
- the task appears to be paid ghostwriting, fabricated research, or academic misconduct;
- the user requests empirical estimates that have not been produced;
- exhaustive QA is required but native independent semantic reviewers are
  unavailable; return `audit_incomplete` rather than simulating a pass.
