# Section Drafting Order

Use this file to choose the drafting order for a full economics paper draft.

## Default Order

Draft in this order:

1. input audit and missing information list;
2. literature and evidence grounding;
3. author-intent confirmation, which normally freezes the confirmed meaning for the requested drafting scope in the same act;
4. table and figure admission;
5. argument spine and section outline within the frozen intent;
6. data, sample, and empirical strategy or model setup;
7. results narrative;
8. mechanism, heterogeneity, and robustness narrative;
9. introduction;
10. literature and contribution;
11. abstract;
12. conclusion;
13. semantic-fidelity, diction, logic, and formatting linter pass.

Do not start with the abstract unless the evidence package and argument spine are already stable.

## Section Roles

- **Abstract**: question, design, core finding, contribution, and one concrete implication.
- **Introduction**: motivate the question, explain the empirical or theoretical leverage, preview results, and state contribution.
- **Literature**: position the paper by contribution margin, not by a list of papers.
- **Theory or mechanism**: explain why the hypothesized relationship should exist and what evidence would support it.
- **Data**: define variables, sample, and measurement choices needed to interpret the estimates.
- **Empirical strategy**: state the comparison, identifying assumption, threats, and diagnostics.
- **Results**: interpret coefficients or facts in economic terms, not as a table inventory.
- **Robustness**: defend the central claim against plausible alternative explanations.
- **Conclusion**: return to the question, state what is learned, and mark boundaries.

## Language Branch

- For English drafts, route prose sections through `econ-write`, then apply `econ-write/references/english-diction/` when revising language.
- For Chinese drafts, route prose sections through `cn-top-econ-writing`, then apply `cn-top-econ-writing/references/chinese-diction/` when revising language.
- For all table, figure, note, and caption decisions, route through `econ-table-figure-design`.

## Drafting Discipline

- Apply `references/author-intent/01_author_intent_contract_and_semantic_fidelity.md` before the first claim-bearing section and after any approved intent change.
- Write paper-facing prose only. Keep workflow explanations in notes or task logs.
- Do not describe why the author changed a specification unless the reader needs it to evaluate the claim.
- Put unresolved non-semantic facts in author-facing `TODO` form instead of hiding them in vague prose. If an unresolved item would change intended meaning, return `clarification_required` and do not draft the affected text.
