---
name: econ-writing-workflow-multiagent
description: Experimental beta entry point for large economics writing projects that need native multi-agent or staged-agent coordination, including full papers and proposals, document-level translation or compression, major revisions, mature-manuscript restructuring, exhaustive semantic QA, long context management, shared paper_state and artifact-conservation protocols, role handoffs, conflict resolution, and integration across econ-write, cn-top-econ-writing, econ-table-figure-design, and empirical-econ-workflow. Use for complex projects, not short one-off polishing.
---

# Economics Writing Workflow Multiagent

## Role

This is an experimental coordination skill for large economics writing projects. It does not replace or rewrite the stable `econ-writing-workflow`; it sits beside it as a beta workflow.

Use this skill only as the controller for multi-agent or staged-agent work. It should coordinate specialized skills, maintain a shared paper state, manage context budget, and integrate outputs. It should not duplicate the substantive rules already maintained in:

- `econ-write`
- `cn-top-econ-writing`
- `econ-table-figure-design`
- `empirical-econ-workflow`

Use native sub-agents for independent semantic acceptance review and explicit
handoff templates for every delegated task. Staged same-agent roles may support
planning or drafting, but they do not satisfy the independent-review gate. If
required native reviewers are unavailable, return `audit_incomplete`; never
simulate independent reviewers sequentially and report a pass.

## When To Use

Use this beta workflow for:

- full paper drafting from a research question, result package, tables, figures, variable notes, and design notes;
- complete research proposals, document-level translations or compressions, and their final semantic acceptance audits;
- long revision projects with many sections, tables, figures, appendix items, or referee comments;
- projects where English and Chinese writing modules both matter;
- tasks where a single-agent context is likely to lose track of contributions, variables, magnitudes, caveats, or table/figure placement;
- comparisons between the stable workflow and a multi-agent-aware workflow.

Do not use it for:

- one paragraph of polishing;
- a single abstract rewrite;
- one table note or one figure caption;
- a short, unambiguously meaning-preserving translation;
- pure data cleaning, regressions, estimation, or code execution without a writing integration task.

For small tasks, use the stable `econ-writing-workflow` or the relevant child skill directly.

## Core Rule

Before splitting work across agents or roles, create or update a shared paper state. The paper state is the single source of truth. No agent may invent or silently alter:

- research question;
- contributions;
- data, sample, period, or variable definitions;
- identification or model assumptions;
- coefficient values, magnitudes, mechanisms, robustness results, or caveats;
- literature claims or citations.

Evidence-boundary accuracy is not a license to write defensive disclaimers.
Default to calibrated verbs, the correct claim type, and only the scope
qualifiers needed for the sentence. Before admitting even the first or only
stand-alone negative caveat, state affirmatively what the result, estimate,
threshold, scenario, or model object represents and what interpretation it
supports. This is explanatory wording, not favorable spin. Retain a separate
negative sentence only when it blocks a concrete material misreading not
already excluded by that wording; bind it to the exact claim or number and use
it as a last resort. An agent may not self-authorize that last resort: unless
the exact negative proposition is already frozen in the author-intent contract,
return `needs_author` and stop the affected wording for author adjudication.
Repeat it only when the method, sample, period, geography,
extrapolation target, or evidence level changes, or when a standalone abstract,
caption, or note must remain intelligible, or a journal/referee explicitly
requires it. Do not impose a per-section count. Removing a first, unique, or
repeated no-information caveat is not loss of evidence discipline, but removing
a concrete identification assumption or changing the effective claim remains a
blocking semantic change.

Missing non-semantic information may remain as a concrete `TODO`. Missing
meaning or evidence needed to support a claim returns `clarification_required`
or `evidence_conflict` and leaves the affected prose unwritten.

Multiagent state must point to the stable workflow's one authoritative
`author_intent_contract`; it must not copy it into a parallel authority. Only a
complete `frozen-current + ready` contract authorizes claim-bearing drafting.
Explicit author confirmation of the complete teach-back normally freezes the
contract in the same event. `Partial`, `proposed`, unconfirmed, held, or
materially unresolved intent never authorizes drafting, and there is no legacy
compatibility path around this gate.

Context compression governs handoffs and duplicated input, not the reader-facing manuscript. Preserve the accepted artifact budget and substantive main-text coverage unless the user, project rules, or verified format requirements authorize a shorter output.

For an accepted mature manuscript, default to `patch_existing` or
`reorder_existing_blocks`. Do not use clean-slate section redrafting unless the
author explicitly authorizes `full_redraft` for the recorded scope. A
controller's judgment that the existing section is weak or unusable is a reason
to request that authorization, not a substitute for it.

## Routing

Load the relevant reference file before starting each phase:

- Before any multi-agent task, load `references/controller_startup_checklist.md`.
- Before drafting or semantic acceptance, load `references/exhaustive_semantic_qa_protocol.md`; also load the stable workflow's authoritative author-intent reference rather than inventing a multiagent intent schema.
- For full papers/proposals, major revisions or restructures, substantive
  literature changes, and final audits with references, load the stable
  workflow's
  `econ-writing-workflow/references/literature-grounding/02_literature_coverage_and_citation_integrity.md`.
- For shared facts and the `paper_state` schema, load `references/paper_state_protocol.md`.
- For full drafting, mature-manuscript revision, restructuring, shortening, or appendix relocation, load `references/artifact_conservation_and_depth_gates.md` before setting the paper spine or assigning roles.
- For role definitions and when to use true sub-agents versus staged roles, load `references/agent_roles.md`.
- For structured delegation and return formats, load `references/handoff_templates.md`.
- For deciding whether to split work, load `references/context_budget_rules.md`.
- For merging outputs and resolving disagreements, load `references/integration_and_conflict_resolution.md`.
- For controller-led section agents, section cards, and section-level integration, load `references/section_agent_protocol.md`.
- For controller-mediated collaboration between section agents and functional agents, load `references/cross_agent_collaboration_protocol.md`.
- For complete result-package-to-paper workflows, load `references/full_paper_multiagent_workflow.md`.

Then route substantive work to child skills:

- English writing and revision: `econ-write`.
- English diction cleanup: `econ-write` with `econ-write/references/english-diction/`.
- Chinese top-journal writing: `cn-top-econ-writing`.
- Chinese diction cleanup: `cn-top-econ-writing` with `cn-top-econ-writing/references/chinese-diction/`.
- Chinese argument logic: `cn-top-econ-writing` with `cn-top-econ-writing/references/argument-logic/`.
- Tables, figures, notes, captions, palettes, and main-text versus appendix placement: `econ-table-figure-design`.
- Data cleaning, variable construction, regression estimation, and reproducibility: `empirical-econ-workflow`.

## Default Workflow

For complex paper tasks, proceed in this order:

1. Run the controller startup checklist.
2. Classify the request and decide whether multi-agent coordination is justified.
3. Locate the stable workflow's authoritative author-intent contract. Clarify,
   teach back, and obtain confirmation when needed; proceed only when its exact
   scope is `frozen-current + ready`.
4. Build or update `paper_state`, content obligations, definition registry,
   optional frozen caveat-placement policy and `pending_candidate` registry
   pointer, four-way ledgers, literature authority pointers and status when
   triggered, and, when applicable, the artifact contract and baseline
   measurements. Materialize the derived caveat registry only after candidate
   unit IDs exist.
5. Audit inputs and keep non-semantic missing facts as `TODO`; stop semantic or
   evidence gaps with `clarification_required` or `evidence_conflict`.
6. Settle the paper spine and create section cards with intent IDs, rewrite
   modes, and artifact budgets when section-level work is needed.
7. Assign narrow drafting or functional roles using the handoff template, then
   integrate outputs against the frozen state and ledgers rather than memory.
8. For every complete paper/proposal, document-level translation/compression,
   or major revision, generate the deterministic QA manifest and run the four
   isolated semantic-review roles from the exhaustive-QA protocol.
9. When literature audit is triggered, run deterministic citation integrity
   and the independent Literature Coverage and Citation Integrity Role outside
   the core four-role plus conservation-role assignment schema, using its
   separate hash-bound `literature-audit-assignment/1.0` record. Accept neither
   artifact by inspection alone: run `scripts/validate_literature_audit.py`
   over the live authorities, deterministic report, assignment, role result,
   and applicable core assignment registry.
10. Resolve conflicts by authority rather than majority vote; apply only bounded
   minimum patches, then re-review changed and dependent units.
11. Run diction only after semantic acceptance, then run post-diction semantic
    re-review.
12. Run final deterministic citation closure when references are present,
    revalidate the final-hash literature assignment/result, then run
    conservation and independent main-text sufficiency checks, followed by
    final consistency.
13. Deliver only when every applicable gate is `pass`; otherwise return the
    exact blocking status, unresolved items, and required user decision.

## Output Check

Before finalizing, confirm:

- the stable workflow's author-intent authority was reused rather than copied
  into a competing multiagent contract;
- claim-bearing drafting began only after the exact requested scope was
  `frozen-current + ready`;
- the controller startup checklist was run before delegation;
- every delegated or staged pass used `paper_state` as the authority;
- every section agent worked from a controller-approved section card when section-level drafting was used;
- every section-functional collaboration went through the controller and updated the section card when needed;
- disagreements were resolved explicitly by authority; unresolved semantic,
  evidence, definition, or scope conflicts retain a blocking status, while only
  missing non-semantic facts may remain as user-facing `TODO`;
- table/figure decisions were integrated into the argument spine;
- every triggered literature role has a current
  gate-local `literature-audit-validation/1.0` pass from
  `scripts/validate_literature_audit.py`; a plausible role memo or a
  deterministic citation pass alone was not treated as acceptance, and this
  local pass was not presented as whole-manuscript delivery authorization;
- prose edits did not delete central contributions, mechanisms, magnitudes,
  concrete necessary evidence boundaries, or design features; a first, unique,
  or repeated no-information defensive sentence was rewritten as affirmative
  interpretation or removed without being treated as a semantic loss, while
  every retained negative sentence remained bound to a concrete claim and
  material misreading and had exact frozen author-intent authority; an
  otherwise recommended `keep` ended in `needs_author`, not an agent-generated
  pass;
- any mature-draft revision followed its recorded rewrite mode and mapped every substantive source block to a conservation-ledger disposition;
- context or handoff limits were not used as manuscript-length instructions;
- the QA manifest captures every reader-visible body, appendix, footnote,
  caption, and note object; every sentence/heading review target is covered in
  exhaustive mode, or the declared changed and dependency set is covered in
  bounded-change mode;
- every required native semantic role returned a valid current-hash result,
  every high-risk unit met the contract's explicit independent-review minimum,
  and no `uncertain`,
  missing, stale, invalid, or unresolved finding was treated as a voteable pass;
- reviewers returned structured findings without editing the manuscript, and
  controller patches plus diction changes received the required semantic
  re-review;
- every triggered literature audit has a current separate assignment and is
  current-hash bound; applicable coverage clusters, admitted citekeys, the
  text-to-evidence ledger, and the final visible bibliography close under the
  literature contract;
- the integrated manuscript satisfies the artifact contract, cumulative compression permission, and main-text self-containment gate;
- deterministic audit status is `pass`; if it first returned `approval_required`, any scoped approval was recorded and the audit was rerun to `pass`;
- no fabricated data, citations, results, or policy implications entered the output.
