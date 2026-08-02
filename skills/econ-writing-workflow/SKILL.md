---
name: econ-writing-workflow
description: Use as the main entry point for economics writing workflows in English or Chinese, including paper and research-proposal planning, scope and claim convergence, full paper drafting from research questions and result packages, major revision and final audits, abstract/introduction/results revision, Chinese top-journal adaptation, English and Chinese diction cleanup, AI/translationese removal, table and figure design, notes/captions, formatting checks, and routing to empirical workflow support when data cleaning, regressions, or variable construction are involved.
---

# Economics Writing Workflow

## Role

Use this skill as the user's main entry point for economics writing work. It does not replace the specialized skills; it routes the task to the right writing module, keeps the workflow ordered, and checks that the final output matches the user's target.

This skill is not a full empirical pipeline. For data cleaning, variable construction, regression code, estimation, diagnostics, or reproducibility tasks, pair with `empirical-econ-workflow`.

## Project-Level Skill Pinning

For multi-step economics writing, table, figure, journal-submission, or paper-formatting workflows, check whether the nearest project-level `AGENTS.md` or `CLAUDE.md` already contains an economics-writing skill routing rule.

If no such rule exists, ask the user once whether to add a persistent local rule. Do not edit `AGENTS.md` or `CLAUDE.md` without explicit user approval, and do not ask for tiny one-off requests.

Recommended rule text:

```markdown
## Economics Writing Skill Routing

For economics paper writing, journal adaptation, tables, figures, captions, notes, Word/PDF formatting, and submission checks, first route through `econ-writing-workflow`.

Use `cn-top-econ-writing` for Chinese top-journal prose and journal-specific submission style. Use `econ-table-figure-design` for tables, figures, maps, captions, notes, and export quality. Use `empirical-econ-workflow` when data cleaning, variable construction, regressions, sample audits, or estimation code are involved.

Keep the relevant skill active throughout the task unless the user explicitly opts out. Do not treat skill use as a one-time setup step: at the start of each substantive phase, and whenever the work crosses from prose into tables, figures, maps, journal formatting, data facts, or empirical code, reclassify the current subtask and load the relevant specialized skill or reference file.

During manuscript drafting or revision, separate paper-facing text from author memos and task logs before writing each paragraph, table note, figure note, appendix note, or footnote. Only reader-facing manuscript text may enter the paper. Author workflow notes, submission-positioning discussion, reasons for moving/deleting material, and author-agent internal decisions must stay in the response, task README, revision memo, or checklist.

Before drafting claim-bearing prose, determine whether the author has explicitly fixed the intended meaning for the requested scope. If not, inspect the available context, ask the smallest grouped set of material questions, restate the intended meaning for confirmation, and wait. Do not draft the affected prose or use a `TODO` to bypass unresolved author intent. A `TODO` may represent a missing factual detail only when it does not change the already confirmed meaning.

Before drafting each paper-facing paragraph, apply draft-time argument clarity: ground abstract concepts in observable/model objects, state the comparison for relative or causal claims, keep design language separate from findings, distinguish mechanisms from plain heterogeneity, position close literature by the margin advanced, and keep terminology stable.

Before drafting literature-dependent claims, check whether the project has local reference papers, literature notes, `.bib` files, or source ledgers. Ask whether the literature is sufficient and whether the user wants help finding publicly available papers. If a Chinese or paywalled source cannot be obtained locally, tell the user and continue only with unaffected content. A non-semantic citation or verification detail may remain as an author-facing `TODO`; if the missing source affects literature positioning, theory, mechanism, variable meaning, identification, contribution, policy implication, or claim strength, return `evidence_conflict` and leave the affected manuscript text unwritten. When the paper uses literature-based data, theories, variables, mechanisms, or empirical choices, read the relevant source material and align with it instead of inventing a new framing.

When writing regression results, main findings, mechanisms, heterogeneity, robustness, abstracts, introductions, or conclusions that mention coefficient size, translate estimates into economic magnitude using at least one appropriate benchmark. Prefer natural units or real policy changes when available; use means, standard deviations, or percentile spreads only when they fit the variable and identification source. Never invent descriptive statistics.

When producing tables, figures, maps, or edited images, verify the final rendered artifact itself before treating the task as complete. Check that text, legends, colorbars, inset maps, axes, notes, and substantive visual content do not overlap, obscure, or cover useful information.
```

After adding the rule, include a clear marker heading so future agents can detect it and avoid asking again.

## Paper Plan And Artifact Lifecycle

For multi-step paper work or a major paper section, first locate the project's
single authoritative current-plan store and current-plan document. If none
exists, ask the author whether to establish it before substantive production.
Do not create parallel current-plan files.

Read the authoritative current plan before each substantive phase. Keep only
the latest accepted objective and claim sequence, admitted evidence and paper
role, main-text or appendix placement, reader-facing terminology, unresolved
decisions, current non-goals, and authorization boundaries. When the author
approves, rejects, narrows, or replaces a plan, update the current plan in
place during the same task. Keep historical process in task logs, manifests,
or audit packages rather than competing current-plan documents.

Develop exploratory and candidate tables, figures, maps, measures,
specifications, model outputs, and other research objects outside the
centralized current-artifact store. Track two dimensions separately:

- `artifact_state`: `exploratory`, `candidate`, `author-confirmed`,
  `frozen-current`, `rejected`, or `superseded`;
- `manuscript_state`: `not-integrated` or `manuscript-integrated`.

Never infer a later state or approval from an earlier one. An object may remain
`frozen-current` while also being `manuscript-integrated`; a revision that
replaces it may become `superseded` while an older manuscript still cites that
revision.

Before moving to a new substantive phase, update the authoritative current
plan and check whether an `author-confirmed` object still lacks an explicit
freeze decision. If so, ask whether to freeze it as the sole current revision.
Do not repeatedly ask after the project record contains the decision, and do
not freeze a merely plausible, validated, or polished candidate.

For every freeze, replacement, rejection, or manuscript integration, load and
follow `references/artifact-lifecycle/01_artifact_state_and_freeze_protocol.md`.
That protocol requires a machine-readable registry, a complete freeze
manifest, SHA-256 coverage for code, inputs, outputs, and validation records,
and a verified immutable audit bundle before any current revision is replaced.
Do not report a freeze complete while a required manifest, checksum, approval,
or recovery artifact is missing.

Keep the centralized current-artifact store current-state only. Build and
validate replacement candidates outside it. Before updating stable current
paths, preserve and verify the old frozen revision in the superseded audit
store; then switch the replacement into the stable paths and update the
registry. Do not accumulate competing current names such as `v2`, `final2`,
`new`, or `latest`, and do not treat current-state cleanup as permission to
delete audit history or original inputs.

Treat substantive approval, freeze approval, replacement approval, and
manuscript-integration approval as separate decisions. Freezing never
authorizes Word/LaTeX edits, caption or note changes, figure redesign,
manuscript insertion, or submission export. Before integration, verify the
proposed object and placement against the authoritative current plan and the
current-artifact registry, obtain separate manuscript authorization, and
record the exact manuscript version and location.

This research-object lifecycle registry is distinct from the multiagent
manuscript `artifact_contract`, which protects accepted manuscript content,
length, and main-text sufficiency. When both apply, maintain both records; do
not use either as a substitute for the other. Follow stricter project-level
repository, terminology-firewall, manuscript-conservation, or authorization
rules first.

## Author Intent And Semantic Fidelity

Before new claim-bearing prose, substantive rewriting, translation that may
change meaning, or section restructuring, load and follow
`references/author-intent/01_author_intent_contract_and_semantic_fidelity.md`.
Do this even for a local passage; a local scope exception from paper-wide
convergence does not authorize the agent to infer the author's meaning.

Inspect the manuscript, current plan, evidence, and prior author decisions
before asking. If an existing frozen author-intent contract covers the exact
scope, reuse it without repeated confirmation. If the author has already stated
one uniquely determined meaning and requested writing from it, record that
instruction as the frozen-current contract. Otherwise, ask the smallest grouped
set of questions that would change the text and teach back the proposed meaning.
The author's explicit confirmation normally freezes that meaning for the stated
drafting scope in the same act; do not ask for a redundant second approval. Keep
it unfrozen only when the author explicitly reserves approval, a material
question remains unresolved, or an evidence conflict blocks the intended claim.

Treat the author as the authority over what the paper is intended to say and
the inspected evidence as the authority over what the paper can support.
Return `clarification_required` when intended meaning remains ambiguous or
internally inconsistent. Return `evidence_conflict` when the intended claim
exceeds the evidence. In either state, do not write around the problem, insert
the disputed claim with a `TODO`, or silently substitute the agent's preferred
interpretation.

Once the contract is frozen, preserve every `must_express`, `must_not_claim`,
`must_not_imply`, required qualifier, evidence boundary, and terminology rule.
The agent may improve syntax, order, transitions, and concision only within the
recorded `allowed_discretion`. Put alternative interpretations or stronger
frames in an author-facing memo and obtain approval before they enter the
manuscript. If intent changes, supersede only the affected contract entry and
recheck its downstream prose; never allow silent semantic drift.

After drafting, run the semantic-fidelity audit from the reference. Do not
deliver or integrate text that omits a required proposition, adds an
unapproved claim, strengthens association into causality, upgrades
heterogeneity into mechanism evidence, broadens scope, drops a qualifier, or
reintroduces a forbidden implication.

Pure spelling, punctuation, citation-format, layout, or grammar-only edits do
not require the full intent-elicitation protocol when the author explicitly
requires meaning preservation or the requested operation has one unambiguously
mechanical, meaning-preserving correction. Use the source wording and the
narrow requested operation as the baseline. Verify the correction itself,
including subject-verb agreement, pronoun antecedent and number, tense,
negation, modifier attachment, and punctuation or citation consistency. Stop
and ask only if the edit exposes a material ambiguity or requires choosing
among substantively different meanings.

## First Decision

Before writing or editing, classify the task stage as `exploration`, `proposal`, `full drafting`, `major revision`, `local polish`, or `final audit`. Do not load paper-wide convergence or final-audit checks for a bounded local edit unless a substantive contradiction blocks the requested change.

Task-stage classification never overrides the author-intent gate. A local
substantive rewrite still requires confirmed meaning; only an explicitly or
unambiguously meaning-preserving mechanical edit receives the narrow exception
above.

Then classify the request:

1. **English paper prose**: abstract, introduction, literature review, model/theory prose, empirical/results prose, conclusion, referee response, or English revision.
2. **English diction cleanup**: remove AI-like prose, translationese, vague contribution language, weak verbs, or template signposting.
3. **Argument logic and draft-time clarity**: full-paper logic, argument spine, paragraph-level clarity, concept grounding, comparison clarity, design/results separation, mechanism-versus-heterogeneity, contribution positioning, repeated material, misplaced sections, emphasis, ordering, or whether tables and figures serve the main line.
4. **Regression results and economic magnitude**: main regression interpretation, coefficient size, economic magnitude, marginal effects, interaction net effects, or result prose that needs means, standard deviations, percentiles, policy benchmarks, or log-to-percent conversions.
5. **Literature and judgment grounding**: local reference papers, literature search/download decisions, source ledgers, citation grounding, theory/mechanism/variable alignment, contribution boundaries, or literature-based judgment calibration.
6. **Full-paper drafting from a result package**: draft a complete paper from a research question, regression tables, figures, result folders, slides, variable notes, or design notes.
7. **Chinese top-journal writing**: Chinese paper structure, Chinese abstract, introduction, contribution framing, journal fit, submission style, or top-journal revision.
8. **Chinese diction cleanup**: remove AI 腔, 翻译腔, 作者备忘腔, unnatural collocations, or stiff Chinese academic prose.
9. **Journal submission style**: target-journal formatting, submission requirements, anonymous PDF checks, accepted-version Word formatting, title hierarchy, references, JEL codes, appendices, or journal-specific body/appendix placement.
10. **Tables and figures**: table/figure admission, main-text versus appendix placement, three-line tables, regression/robustness/heterogeneity/mechanism tables, notes, captions, palettes, fonts, or export quality.
11. **Empirical workflow**: data cleaning, variable construction, sample construction, regression code, estimation, diagnostics, or reproducibility.
12. **Research convergence and proposal feasibility**: scope freezing, one-sentence research question, contribution hierarchy, current non-goals, model or identification closure, theory-to-measure mapping, proposal execution plans, cross-section consistency, or stopping a mature revision cycle.

If a request spans more than one category, handle them in this order:

1. empirical workflow and sample/design facts;
2. literature and judgment grounding;
3. applicable research-convergence gates;
4. table and figure design;
5. paper structure and section logic;
6. full-paper drafting plan;
7. prose and diction cleanup;
8. final formatting/export checks.

## Routing

- For new claim-bearing prose, substantive rewriting, meaning-sensitive translation, section restructuring, or uncertainty about what the author wants to say or not say, first load `references/author-intent/01_author_intent_contract_and_semantic_fidelity.md`.
- For English paper prose, use `econ-write`.
- For English diction cleanup, use `econ-write` and load `references/english-diction/` selectively.
- For full-paper logic, repeated material, emphasis, section ordering, and argument-spine audits, load `references/argument-logic/` selectively before polishing prose. Before drafting or revising abstracts, introductions, literature positioning, design, results, mechanisms, heterogeneity, contributions, or conclusions, load `references/argument-logic/06_draft_time_argument_clarity.md` so clarity is handled during generation, not only in the final audit.
- For regression results, main findings, economic magnitude, coefficient interpretation, marginal effects, interaction net effects, log-to-percent conversions, or benchmark choices using means, standard deviations, percentiles, policy changes, or natural units, load `references/regression-results/01_economic_magnitude_interpretation.md` before drafting the relevant prose.
- For literature-dependent drafting, closest-literature positioning, literature search/download decisions, source ledgers, citation grounding, theory/mechanism/variable alignment, or calibration of similar judgments from prior papers, load `references/literature-grounding/01_literature_and_judgment_grounding.md` before drafting the relevant prose.
- For manuscript-facing versus author-facing voice, internal memo leakage, or requests to remove author workflow notes from paper prose, load `references/manuscript-voice/01_no_author_memo_in_manuscript.md` before finalizing text.
- For full-paper drafting from research questions, regression tables, figures, or result folders, load `references/full-paper-drafting/` first, then route table/figure decisions to `econ-table-figure-design` and language-specific prose to `econ-write` or `cn-top-econ-writing`.
- For full-paper or proposal scoping, major restructuring, contribution drift, terminology drift, or repeated expansion beyond the current question, load `references/research-convergence/01_scope_and_claim_contract.md`.
- For theory/model closure, assumption roles, theory-to-measure mapping, identification capacity, evidence-status calibration, welfare claims, or normative policy recommendations, load only the applicable sections of `references/research-convergence/02_theory_empirical_closure_gates.md`.
- For a general research proposal, executable research plan, paper-wide ordered revision, final consistency audit, or mature-draft stopping decision, load only the applicable sections of `references/research-convergence/03_proposal_revision_stop_gates.md`.
- Do not load all research-convergence modules for local diction cleanup, a bounded paragraph rewrite, citation formatting, or a narrow table/figure note edit. Keep the requested scope unless a high-impact substantive contradiction prevents a responsible local answer.
- For Chinese top-journal writing, use `cn-top-econ-writing`.
- For target-journal submission style, anonymous manuscript checks, accepted-version formatting, references, appendices, or requests such as “按《经济学（季刊）》投稿要求调整”, use `cn-top-econ-writing` and its `references/journal-styles/` module. For 《经济学（季刊）》, load `references/journal-styles/00_journal_submission_workflow.md`, `references/journal-styles/economics_quarterly.md`, and when table/figure/appendix issues appear, `references/journal-styles/common_chinese_journal_rules.md`.
- For Chinese diction cleanup, use `cn-top-econ-writing` and load `references/chinese-diction/` selectively.
- For tables, figures, notes, captions, palettes, typography, and export checks, use `econ-table-figure-design`.
- For data cleaning, regression code, variable construction, or estimation, pair with `empirical-econ-workflow`. Do not let this writing workflow invent or run empirical results by itself.

## Active Routing During Work

Do not route only once at the beginning of a long task. At the start of each substantive phase, and whenever the work crosses from prose into tables, figures, maps, journal formatting, data facts, or empirical code, reclassify the current subtask and load the relevant specialized skill or reference file.

Route immediately when these boundaries appear:

- new claim-bearing prose, substantive rewriting, meaning-sensitive translation, section restructuring, or possible drift in claim meaning, strength, qualifiers, implications, or emphasis: load `references/author-intent/01_author_intent_contract_and_semantic_fidelity.md` before the language-specific writing skill;
- tables, figures, maps, image edits, captions, legends, colorbars, fonts, export quality, or main-text versus appendix placement: use `econ-table-figure-design`;
- abstracts, introductions, literature positioning, research design, results, mechanisms, heterogeneity, contributions, or conclusions where the wording depends on observable objects, comparison groups, design/results separation, mechanism evidence, contribution margins, or terminology stability: load `references/argument-logic/06_draft_time_argument_clarity.md`;
- main regression results, mechanism or heterogeneity estimates, coefficient size, economic magnitude, marginal effects, interaction net effects, log-to-percent conversions, mean/SD/percentile comparisons, or policy benchmark interpretation: load `references/regression-results/01_economic_magnitude_interpretation.md`;
- local reference papers, PDFs, `.bib` files, literature search/download, closest-literature positioning, data/theory/variable/mechanism alignment with prior papers, contribution boundaries, or claim-strength calibration: load `references/literature-grounding/01_literature_and_judgment_grounding.md`;
- full drafting, proposal development, major restructuring, scope or terminology drift, theory/model closure, theory-to-measure mapping, normative policy claims, paper-wide revision, or final-audit stopping decisions: load only the matching `references/research-convergence/` file and section;
- target-journal style, anonymous submission, title hierarchy, references, JEL codes, appendices, Word/PDF submission format, or 《经济学（季刊）》 rules: use `cn-top-econ-writing` and its `references/journal-styles/` module;
- data cleaning, variable construction, regression code, estimation, sample changes, or post-estimation sample audit: pair with `empirical-econ-workflow`;
- English prose or English diction: use `econ-write`;
- Chinese top-journal prose, Chinese diction, Chinese abstract, or Chinese contribution framing: use `cn-top-econ-writing`.

After a specialized skill settles its part, return to this workflow to integrate the decision into the paper-level order and final output check.

## Operating Rules

- Apply research-convergence rules by task stage, paper type, requested scope, and claim type. Do not turn a local prose edit into an unsolicited paper-wide audit, and do not force an exploration-stage idea into premature closure.
- Keep one central question visible while preserving legitimate secondary theory, data, measurement, structural, or policy contributions that materially change the intellectual claim. Treat fixed paragraph counts, result counts, and minimal-model advice as defaults with paper-type exceptions, not universal vetoes.
- Distinguish model results, numerical exercises, causal estimates, descriptive facts, suggestive interpretations, and planned tests. The abstract, introduction, conclusion, and policy discussion must not state a stronger or more complete result than the body supports.
- Keep scope contracts, non-goal lists, consistency matrices, revision-pass labels, and stopping decisions in author-facing logs or memos. Never insert them into manuscript prose, table notes, figure notes, appendix notes, or footnotes.
- Read available manuscript context before giving paper-level prose advice. If only an excerpt is available, state that the advice is excerpt-level.
- Before drafting each paper-facing paragraph, apply the author-intent gate and then the draft-time clarity gate. Identify the intended proposition, object, observable or model anchor, claim type, comparison, qualifiers, forbidden implications, and section function. If an unknown item would change meaning, return `clarification_required`; use a `TODO` only for a missing non-semantic fact inside an already confirmed proposition.
- Do not rewrite tables or figures as prose problems. Table selection, sample comparability, notes, and visual design are part of the research presentation.
- Do not put author workflow notes in paper-facing text, table notes, or figure notes.
- Before delivering or inserting manuscript text, classify each sentence as paper-facing text, author memo, or task log. Only paper-facing text may enter the manuscript.
- If the manuscript context is unclear on research question, variables, sample, identification, table/figure meaning, target journal, or whether the author wants to keep, delete, strengthen, weaken, or reframe a substantive claim, ask the user and stop the affected drafting scope; do not guess or use a `TODO` as semantic authorization.
- When discussing regression results in the manuscript, translate the coefficient into at least one suitable economic magnitude benchmark. Do not invent means, standard deviations, percentiles, policy changes, or marginal effects; compute them from supplied materials or ask for them. If the missing benchmark is recorded as an author-facing `TODO`, keep the unsupported magnitude out of paper-facing prose.
- Before writing literature-dependent claims, check local literature materials and ask whether they are sufficient when that is unclear. If the user wants help finding literature, only rely on papers that can be inspected or that the user supplies. If important Chinese or paywalled papers are unavailable, say so; use an author-facing `TODO` only for non-semantic citation or verification details, and return `evidence_conflict` with affected prose withheld when the missing support changes the claim.
- When the paper uses or adapts data, theory, concepts, variables, mechanisms, classifications, model objects, controls, fixed effects, heterogeneity dimensions, robustness checks, or policy interpretations from reference papers, inspect the relevant source material first and align terminology, construction, sample scope, and claim strength with those sources. Do not invent a new framing when a local reference already provides the relevant concept or boundary.
- When writing main-text pointers to appendices, tables, figures, or online appendices, keep them as pure pointers: state what to see and where to see it; only when needed, name the substantive role for the current claim, such as robustness, variable construction, sample scope, background fact, or extended result. Do not write meta-language such as `this is related to the main text` or `因此与正文有关`. Do not include layout or production language such as split columns, left/right halves, column width, page breaks, continued tables, repeated headers, or appendix-table formatting in the main text; put necessary reading guidance in the appendix text, table title, or note.
- Do not merge all specialized rules into the response. Load only the relevant child skill or reference files needed for the task.
- Preserve the user's language target: English manuscript tasks should output English unless asked otherwise; Chinese top-journal tasks should output Chinese unless asked otherwise.
- For full draft requests, never invent citations, data, variable definitions, identification claims, coefficient values, mechanisms, robustness results, or policy implications. Record only non-semantic missing facts as author-facing `TODO` items; mark a missing item `BLOCKED` and withhold the affected prose when it changes meaning or evidentiary support.
- Do not provide full manuscript drafting for paid paper-writing services, undisclosed ghostwriting, fabricated research, or academic misconduct. Offer an ethical outline, checklist, or teaching-oriented alternative instead.

## Argument-Logic References

Load only the relevant files:

- `references/argument-logic/01_argument_spine.md`: one-chain paper logic and missing-link audit.
- `references/argument-logic/02_redundancy_linter.md`: repeated, appendix, and delete/merge material.
- `references/argument-logic/03_emphasis_and_ordering.md`: what to foreground, delay, or de-emphasize.
- `references/argument-logic/04_table_figure_logic.md`: whether tables and figures serve the main line.
- `references/argument-logic/05_revision_workflow.md`: full-paper logic revision workflow.
- `references/argument-logic/06_draft_time_argument_clarity.md`: draft-time concept grounding, comparison clarity, design/results separation, mechanism-versus-heterogeneity, literature-margin positioning, and terminology stability.

## Research-Convergence References

Load only the matching module and relevant section:

- `references/research-convergence/01_scope_and_claim_contract.md`: task-stage classification, scope contract, paper-type argument spine, must-preserve/current-non-goal lists, terminology ledger, and reopening conditions.
- `references/research-convergence/02_theory_empirical_closure_gates.md`: evidence-status calibration, model closure, friction and assumption roles, economic-result qualification, concept-to-measure mapping, identification capacity, and normative policy conditions.
- `references/research-convergence/03_proposal_revision_stop_gates.md`: proposal status and executable plans, ordered major-revision passes, author-facing consistency matrix, and stop/reopen criteria.

## Author-Intent Reference

Load before claim-bearing drafting or substantive rewriting:

- `references/author-intent/01_author_intent_contract_and_semantic_fidelity.md`:
  defines the author-intent contract, teach-back confirmation, narrow mechanical
  exception, frozen-current meaning record, evidence-conflict handling, change
  control, and post-draft semantic-fidelity audit.

## Artifact-Lifecycle Reference

Load for multi-step projects that create, approve, freeze, replace, reject, or
insert tables, figures, maps, measures, specifications, model outputs, or other
research objects:

- `references/artifact-lifecycle/01_artifact_state_and_freeze_protocol.md`:
  separates artifact lifecycle from manuscript integration; defines allowed
  transitions, mandatory registry and SHA-256 fields, immutable superseded
  audit bundles, and safe current-path replacement.

## Full-Paper Drafting References

Load only the relevant files:

- `references/full-paper-drafting/01_input_checklist.md`: input audit and draftability levels.
- `references/full-paper-drafting/02_from_results_to_outline.md`: result ledger, argument spine, and table/figure placement logic.
- `references/full-paper-drafting/03_section_drafting_order.md`: section order and language-specific routing.
- `references/full-paper-drafting/04_missing_information_policy.md`: anti-fabrication rules and `TODO` format.
- `references/full-paper-drafting/05_full_draft_workflow.md`: full result-package-to-paper workflow.

## Literature-Grounding References

Load before drafting or revising literature-dependent sections or judgments:

- `references/literature-grounding/01_literature_and_judgment_grounding.md`: checks local references, asks whether literature is sufficient, builds source and judgment ledgers, aligns reused data/theory/variables/mechanisms with sources, and audits claim strength.

## Manuscript-Voice References

Load when drafting, revising, polishing, or auditing prose that will enter the manuscript:

- `references/manuscript-voice/01_no_author_memo_in_manuscript.md`: separates manuscript text from author memos and task logs; includes forbidden and context-dependent author-memo patterns.

## Regression-Results References

Load before drafting or revising main result prose, abstracts, introductions, conclusions, or referee responses that discuss coefficient size:

- `references/regression-results/01_economic_magnitude_interpretation.md`: chooses natural units, policy changes, means, standard deviations, percentile spreads, marginal effects, interaction net effects, and log-to-percent conversions for reader-facing economic magnitude.

## Output Check

Before finalizing a response, confirm that:

- the routed skill still matches the current subtask, not just the original request;
- any claim-bearing draft is covered by a frozen-current author-intent contract for the requested scope, or qualifies for the explicit meaning-preserving mechanical exception;
- the semantic-fidelity audit maps every required intent to the draft and finds no unapproved addition, claim-strength escalation, lost qualifier, forbidden implication, or evidence conflict;
- any table/figure decision has main-text versus appendix placement;
- any empirical claim is grounded in provided or inspected evidence;
- any main regression or important mechanism/robustness result has an economic magnitude benchmark, or the missing benchmark is kept out of paper-facing prose and recorded as a concrete author-facing `TODO`;
- any literature-dependent claim, theory, mechanism, variable, data source, empirical choice, contribution boundary, or policy implication is grounded in inspected local sources; unavailable non-semantic metadata is recorded as an author-facing `TODO`, while a material support gap returns `evidence_conflict` and keeps the affected prose unwritten;
- any full-draft output has an input audit, argument spine, table/figure placement plan, and unresolved `TODO` list when needed;
- any applicable convergence module was loaded selectively rather than imposed on an unrelated local edit;
- any proposal distinguishes completed, preliminary, planned, and expected results and supplies executable stages, risks, fallbacks, and deliverables when required;
- any theory-to-empirical claim has a recoverable concept-to-measure link, and any normative policy claim states the relevant social-private wedge and implementation conditions;
- any final consistency matrix, scope contract, or stop decision remains author-facing and does not leak into the manuscript;
- any prose revision removes vague, inflated, AI-like, or translation-like wording;
- any drafted or revised paragraph grounds abstract concepts, states needed comparisons, keeps design separate from findings, explains mechanism links rather than relabeling heterogeneity, and uses stable terminology;
- no paper-facing paragraph, table note, or figure note contains author-facing workflow notes, draft-management explanations, or internal discussion with the author;
- any remaining uncertainty is stated as a concrete limitation or next step.
