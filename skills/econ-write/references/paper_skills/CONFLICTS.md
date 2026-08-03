---
purpose: "Record contradictions found across paper_skills rules without silently resolving them."
applies_to: "All paper_skills rule integration and revision passes."
last_updated: "2026-08-03"
used_by: "paper_skills"
---

# Conflicts

## Audit Date

2026-08-03

## Scope

The prior audit covered all Markdown files under `paper_skills/`. This update
rechecked and minimally aligned the core `SKILL.md`,
`04_introduction_rules.md`, `05_related_literature_rules.md`, and
`11_revision_linter.md` for the current author-intent, caveat-placement, and
literature-coverage rules.

## Confirmed Conflicts

No confirmed substantive contradiction remains in the rechecked files.
`03_abstract_rules.md` and `04_introduction_rules.md` now route materially
ambiguous protected content through the author-intent gate, and
`11_revision_linter.md` now distinguishes caveat meaning from repeated
disclaimer sentences. The core empirical checks and `review-checklist.md` ask
only for substantively applicable threats and literature functions rather than
ritual caveats or a small paper-wide reference ceiling.

The new related-literature rules likewise introduce no conflict. They
distinguish foregrounding from coverage: roughly 5-10 close and recent papers
may anchor a focused positioning passage, but this is not a cap on the complete
reference set. They also distinguish preserving a caveat's semantic boundary
from repeating identical defensive sentences.

## Potential Conflict Areas To Recheck After Content Is Added

- `03_abstract_rules.md` vs. `04_introduction_rules.md`: currently aligned on contribution preservation; recheck when more section-specific content is added.
- `04_introduction_rules.md` vs. `05_related_literature_rules.md`: placement is currently consistent for a standard original paper; recheck survey papers and journal-specific exceptions when those modules are filled.
- `07_empirical_section_rules.md` vs. `08_tables_figures_rules.md`: ensure table admission, coefficient reporting, sample notes, and interpretation rules agree.
- `07_empirical_section_rules.md` vs. `09_robustness_appendix_rules.md`: ensure robustness checks are not both required in main text and relegated to appendix under incompatible criteria.
- `10_latex_word_format_rules.md` vs. `08_tables_figures_rules.md`: ensure table/figure formatting conventions agree.
- `11_revision_linter.md` vs. all rule files: ensure the linter checks the same rule set rather than introducing stricter or conflicting requirements.
- `13_journal_specific/jde.md` and `13_journal_specific/research_policy.md` vs. general rules: ensure journal-specific exceptions are explicit and do not silently override general workflow rules.

## Structural Findings That Are Not Conflicts

- `05_related_literature_rules.md` now has substantive coverage, positioning, source-integrity, bibliography-closure, and caveat-discipline rules.
- `11_revision_linter.md` now explicitly checks semantic-boundary preservation and defensive repetition. It still needs extension for the new related-literature checks and other modules as they are filled.
- No duplicated substantive guidance was found. The previous repeated placeholder sentence has been replaced with file-specific pending-content notes.
- The active abstract and introduction templates are paper-type branches rather than boilerplate paragraphs. Recheck formulaic-prose risk as more rule bodies are filled.
