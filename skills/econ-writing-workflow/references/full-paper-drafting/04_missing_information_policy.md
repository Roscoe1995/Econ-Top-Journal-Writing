# Missing Information Policy

Use this file whenever a full draft request lacks information needed for credible academic prose.

## Never Invent

Do not invent:

- citations, author names, journal names, or literature claims;
- literature-based data, theory, variable, mechanism, classification, specification, or policy judgments that have not been inspected in the relevant source or confirmed by the user;
- data sources, sample windows, sample restrictions, or observation counts;
- variable definitions, transformations, or units;
- identifying assumptions, instruments, discontinuities, shocks, or treatment timing;
- coefficient signs, magnitudes, standard errors, significance, or robustness results;
- mechanism evidence, heterogeneity patterns, or placebo outcomes;
- policy implications that do not follow from the evidence;
- journal-specific requirements not provided or inspected.

## TODO Format

A `TODO` is an author-facing record of a missing fact, source, value, or
verification; it is not author authorization and must not appear as a settled
manuscript claim. Do not use one to bypass uncertainty about what the author
wants to claim, not claim, imply, qualify, emphasize, retain, or omit. If the
missing item would change meaning or the maximum claim supported by evidence,
return `clarification_required` or `evidence_conflict` and do not draft the
affected text. Apply the author-intent protocol first.

Use concrete markers:

```text
TODO[citation]: Verify the page number for the already-supported definition in Source X.
TODO[metadata]: Complete the issue number and DOI for Source Y.
TODO[result]: Insert the verified coefficient, standard error, and economic magnitude from Table X; keep the affected sentence unwritten until then.
BLOCKED[data]: Confirm the sample window and unit of observation before drafting the affected design text.
BLOCKED[mechanism]: Provide inspected mechanism evidence or revise the intended claim; return evidence_conflict meanwhile.
BLOCKED[identification]: Confirm the identifying assumption and main threat before drafting the affected identification claim.
```

Each `TODO` or `BLOCKED` item must name the missing object and where it affects
the draft. Use `BLOCKED`, not `TODO`, whenever the missing item changes meaning
or the maximum claim supported by evidence.

## Allowed Provisional Language

Use provisional wording only in an author memo, never as a substitute for the
affected manuscript text:

- "The draft can state this claim after the author verifies ..."
- "This paragraph assumes the table shows ..."
- "If the identifying variation is ..., the empirical strategy section should ..."

Do not convert provisional notes into paper-facing claims.

## Ethical Boundary

If the request appears to be paid ghostwriting, undisclosed authorship, fabricated evidence, or evasion of journal or university rules, do not provide a full manuscript. Offer an ethical alternative such as an outline, revision checklist, or teaching-oriented explanation.

## Insufficient Inputs

When key inputs are missing, produce:

1. what can be drafted now;
2. what may remain as a non-semantic `TODO` and what is substantively `BLOCKED`;
3. what cannot be drafted responsibly;
4. the smallest set of additional files or facts needed to proceed.
