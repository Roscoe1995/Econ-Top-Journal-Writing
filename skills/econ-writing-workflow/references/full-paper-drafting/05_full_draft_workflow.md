# Full Draft Workflow

Use this file when the user asks for a complete paper draft from a result package.

## Workflow

1. **Ethical check**: confirm the request is for the user's own legitimate research, teaching, revision, or noncommercial academic support.
2. **Input audit**: apply `01_input_checklist.md` and assign green, yellow, or red draftability.
3. **Literature grounding**: apply `references/literature-grounding/01_literature_and_judgment_grounding.md` when local reference papers, literature positioning, theory, mechanisms, variables, data sources, or contribution boundaries affect the draft. Ask whether the literature is sufficient; if sources are missing, mark only non-semantic missing details with concrete TODOs.
4. **Evidence ledger**: apply `02_from_results_to_outline.md` to summarize tables and figures without overstating them.
5. **Author-intent gate**: after inspecting the relevant evidence and sources, apply `references/author-intent/01_author_intent_contract_and_semantic_fidelity.md`. Ask all material meaning questions together, teach the proposed contract back to the author, and freeze it before drafting claim-bearing prose. If the gate returns `clarification_required` or `evidence_conflict`, stop the affected sections.
6. **Table and figure design**: use `econ-table-figure-design` for main-text placement, appendix placement, notes, captions, and visual consistency.
7. **Argument spine**: use `references/argument-logic/` to remove repeated material and order the paper around the central chain.
8. **Section drafting**: apply `03_section_drafting_order.md` and route prose through the relevant English or Chinese writing skill.
9. **Missing information pass**: apply `04_missing_information_policy.md` and replace unsupported non-semantic details with concrete `TODO` markers.
10. **Semantic-fidelity pass**: map the draft to the frozen author-intent entries and resolve omissions, unapproved additions, claim-strength changes, lost qualifiers, and forbidden implications.
11. **Diction and final package**: run the relevant language linter, then return the draft, table/figure placement plan, semantic-fidelity status, and `TODO` list.

## One-Sentence Prompt Handling

If the user gives a short request such as "use these tables and my research
question to write the paper," do not stop at a generic question. First inspect
available files or pasted material and produce an input audit. Reconstruct a
compact proposed author-intent contract from that evidence, but do not treat a
plausible reconstruction as the author's choice. Ask for confirmation before
drafting. Unless the author explicitly reserves the decision, leaves a material
question unresolved, or faces an evidence conflict, that confirmation freezes
the meaning for the stated drafting scope in the same act. If the user already
supplied one uniquely determined meaning and requested writing from it, record
it as frozen-current without asking a redundant second question.

## Final Output Structure

For full draft tasks, return:

```text
1. Input audit
2. Literature/source grounding note
3. Author-intent contract and gate status
4. Argument spine
5. Table and figure placement plan
6. Full draft or section draft
7. Semantic-fidelity audit
8. TODO list
9. Verification notes
```

The draft may be incomplete, but it must be honest: no fabricated data, citations, estimates, or mechanisms.

## Quality Bar

A successful full draft:

- reads as a paper, not as a work log;
- expresses only the author's frozen intended meaning for the requested scope and passes the semantic-fidelity audit;
- keeps the central question visible throughout;
- aligns literature-based data, theory, variables, mechanisms, specifications, and claim strength with inspected sources;
- discusses only results supported by the provided tables, figures, or notes;
- records missing non-semantic facts as precise author-facing `TODO` items and keeps substantively blocked prose unwritten;
- separates main findings from robustness, heterogeneity, and mechanism evidence;
- uses language appropriate to the target language and journal style;
- leaves the author responsible for verification, citations, disclosure, and final submission choices.
