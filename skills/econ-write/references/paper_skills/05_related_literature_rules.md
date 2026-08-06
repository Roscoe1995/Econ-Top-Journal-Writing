---
purpose: "Provide rules for positioning related literature and clarifying contribution."
applies_to: "Related literature sections, contribution paragraphs, citation grouping, and literature positioning."
last_updated: "2026-08-03"
used_by: "paper_skills"
---

# Related Literature Rules

## Purpose

Position the paper against inspected literature without turning the section
into an annotated bibliography, an adversarial list of defects, or a small
fixed bibliography. Apply these rules with
`econ-writing-workflow/references/literature-grounding/01_literature_and_judgment_grounding.md`.
For a full paper or proposal, major revision or restructure, substantive
literature revision, configured coverage target, or final citation audit, also apply
`econ-writing-workflow/references/literature-grounding/02_literature_coverage_and_citation_integrity.md`.

## Coverage Before Prose

For paper-level work that triggers the integrity protocol, define the
applicable functions in a `literature-coverage-contract/1.0`. For a bounded
wording edit that changes neither claims nor citations, reuse the active
grounding record and do not claim a new paper-wide coverage pass:

- closest work needed for contribution positioning;
- theory and mechanism foundations;
- data, measurement, institutional, or historical sources;
- method, identification, estimator, or model precedents;
- contrary evidence and credible alternative explanations;
- recent frontier through the recorded coverage date;
- any project-specific function the author requires.

Do not substitute the number of references for functional coverage. There is
no global minimum or target count. Enforce a project-specific minimum or range
only when the contract records a recoverable author requirement, journal rule,
or reproducible sample of comparable papers.

## Focused Positioning

In the introduction's focused positioning passage, foreground roughly five to
ten of the closest and most recent papers when that creates a clear narrative.
This range concerns the papers discussed in the foreground, not the complete
reference list. Additional sources may be needed elsewhere for foundations,
measurement, methods, institutional facts, contrary evidence, or other active
coverage functions.

Organize by the paper's comparison margins, not by one paragraph per source:

1. what the closest cluster establishes;
2. which specific question, setting, mechanism, data object, model, or
   identification margin remains;
3. what this paper adds on that margin;
4. how the result changes what can be concluded.

Be generous and exact. Do not force a criticism of every prior paper, claim
that a literature is absent because the exact application is new, or use vague
formulas such as `little is known`. Name the concrete difference.

## Source And Claim Integrity

- Cite only sources that were inspected for the claim being made.
- Use the published version when it is the relevant current record; retain a
  working-paper version only for a recorded substantive reason.
- Match every citekey to the authoritative reference-library manifest and an
  `admitted` literature-registry entry.
- Link claim-bearing sentences to the existing `text_to_evidence_ledger` with
  citekeys and manuscript unit IDs when the task requires exhaustive QA.
- Distinguish a source used for background, definition, method precedent,
  direct support, contrary evidence, or contribution comparison. Admission for
  one role does not authorize a stronger role.
- Do not insert a plausible source to repair an unsupported claim. Return
  `evidence_conflict` and ask for evidence or a claim revision.

Deleting an in-text citation does not automatically delete its `.bib` entry.
First check whether the deletion leaves a claim unsupported or an applicable
coverage cluster empty. Changing the literature in a way that changes the
paper's contribution, mechanism, or claim strength requires author-intent
change control.

## Bibliography Closure

The final visible bibliography must be derived from manuscript citekeys plus
explicitly authorized `nocite` entries. Unused inventory may remain in the
source `.bib`; it is not a final-output error. A visible uncited item without a
recorded `nocite` authorization fails closure. Rebuild or reject a stale `.bbl`
rather than treating it as authority.

Before final delivery, verify duplicate citekeys, duplicate DOI values,
possible duplicate titles, missing metadata, registry state, evidence-ledger
links, coverage clusters, manuscript-to-bibliography closure, and hashes of the
manuscript and citation authorities.

## Literature Caveats

Use calibrated verbs and source roles rather than attaching a generic warning
to every cited claim. State a source-specific population, period, method, or
external-validity condition when it changes how the current paper may use the
source. Under unchanged conditions, give the boundary once at the first
necessary location and avoid defensive repetition.

## Final Check

- Does the passage make the contribution margin concrete?
- Are the foregrounded papers the closest and current enough for that margin?
- Are all other applicable functional clusters covered elsewhere?
- Does each substantive citation support the precise claim and role assigned?
- Are contrary findings represented when they materially change positioning?
- Does the final bibliography close against manuscript citekeys and authorized
  `nocite`, without treating unused `.bib` inventory as visible references?
