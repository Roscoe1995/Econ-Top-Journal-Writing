# Input Checklist

Use this file when the user asks for a full paper draft from a research question, regression tables, figures, slides, notes, or a result folder.

## Minimum Inputs

Before drafting, identify whether the user has provided:

- research question;
- target language and target journal or paper style;
- outcome, treatment or main explanatory variable, and key controls;
- sample definition, geography, time window, and unit of observation;
- empirical design or theoretical model logic;
- main regression tables and figure files;
- robustness, heterogeneity, and mechanism results;
- variable definitions and data source descriptions;
- intended contribution and closest literature;
- one or more frozen-current author-intent entries, at the least granular paper, section, or passage level needed to cover the requested drafting scope, including required claims, non-claims, qualifiers, and forbidden implications;
- local literature materials: PDFs, notes, extracted text, `.bib` files, source ledgers, or reference-paper folders;
- literature-dependent objects that the paper uses or adapts: data, theory, variables, mechanisms, classifications, specifications, controls, fixed effects, heterogeneity choices, or robustness designs;
- disclosure constraints, authorship constraints, or forbidden claims.

## Input Audit

Start with a compact audit:

- **Ready**: information that is available and can be used directly.
- **Partial**: non-semantic information that can support an unaffected draft but needs author-facing `TODO` markers.
- **Missing**: information that blocks a specific section or claim.
- **Do not infer**: claims that would require new data, new regressions, undisclosed literature, or private author intent.

Private author intent cannot be downgraded from `Missing` to `Partial` merely
because the manuscript or evidence suggests a plausible interpretation. Apply
`references/author-intent/01_author_intent_contract_and_semantic_fidelity.md`,
teach the proposed meaning back to the author, and obtain confirmation before
drafting the affected prose.

If the literature materials are missing or thin, ask whether the user considers them sufficient and whether the agent should help search for publicly available papers. If important Chinese or paywalled papers cannot be inspected locally, continue only with unaffected content. A non-semantic citation or verification detail may remain as an author-facing `TODO`; if the missing source affects positioning, theory, mechanism, identification, contribution, or claim strength, return `evidence_conflict` and do not draft the affected prose.

## Draftability Levels

- **Green**: research question, design, variables, main results, basic literature position, and a frozen-current author-intent contract for the requested scope are available. Draft the paper and keep uncertainties narrow.
- **Yellow**: main results, question, and requested-scope author intent are frozen-current, but literature, mechanism, or data details are incomplete. Draft only the unaffected content and use explicit `TODO` markers for non-semantic missing facts.
- **Red**: tables or figures exist without a research question, variable meaning, or identification logic. Do not write a full paper. Produce an input request and provisional outline only.

Missing or competing author intent for a claim-bearing section is also `Red`
for that section even when tables, facts, and literature are otherwise
complete.

Green requires more than a reference list: when the paper relies on literature-based data, theories, variables, mechanisms, classifications, or empirical choices, the relevant source material must be available or summarized well enough to align terminology, construction, scope, and claim strength.

## Output Template

```text
Input audit:
- Research question: [ready/partial/missing]
- Evidence package: [ready/partial/missing]
- Identification/model logic: [ready/partial/missing]
- Data and sample: [ready/partial/missing]
- Literature/contribution: [ready/partial/missing]
- Literature grounding: [source materials sufficient? judgment alignment needed?]
- Target language/journal: [ready/partial/missing]
- Author-intent contract: [frozen-current/missing]
- Author-intent gate: [ready/clarification_required/evidence_conflict]

Draftability: [green/yellow/red]
Blocked sections: [section names or none]
Required TODO markers: [specific missing items]
```
