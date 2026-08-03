# Integration And Conflict Resolution

## Integration Order

The controller integrates in this order:

1. user instructions;
2. the stable workflow's current frozen author-intent contract;
3. `paper_state`, including content obligations, definition registry, artifact
   contract, and recorded approvals;
4. the accepted baseline and four-way ledgers;
5. inspected tables, figures, data notes, manuscript text, and source materials;
6. specialized role findings;
7. prose preferences and style compression.

If a prose suggestion conflicts with a paper fact, the paper fact wins.

## Common Conflicts

- Contribution conflict: one role narrows or expands the claim.
- Result conflict: prose differs from table values or notes.
- Mechanism conflict: mechanism prose is not supported by theory or result evidence.
- Placement conflict: table/figure role moves an item that drafting role relies on.
- Language conflict: diction role smooths away a caveat or secondary contribution.
- Literature conflict: contribution claim is stronger than inspected literature supports.
- Caveat-discipline conflict: a concrete evidence boundary disappears, or the
  same no-information non-causal, extrapolation, or long-run disclaimer is
  repeated under unchanged conditions.
- Citation-closure conflict: coverage, library metadata, registry status,
  ledger links, manuscript citekeys, authorized `nocite`, and the visible
  bibliography do not resolve to one current-hash chain.
- Artifact-budget conflict: the integrated candidate falls below a target, hard floor, or unapproved cumulative-reduction threshold.
- Main-versus-appendix sufficiency conflict: material still exists but the main text can no longer explain a central data, model, design, result, or limitation without the appendix.
- Intent-coverage conflict: a required intent has no text location or a text
  claim has no authorizing intent ID.
- Definition conflict: a term is used before a registered definition, changes
  meaning across sections, or remains inadequate for the intended reader.
- Semantic-review conflict: isolated reviewers disagree, return `uncertain`, or
  identify incompatible evidence and intent constraints.

## Resolution Rules

- Resolve contribution conflicts by returning to `main_contribution`, `secondary_contributions`, and `scope_conditions_and_caveats`.
- Resolve result conflicts by inspecting the table, figure, variable definition, and sample note.
- Resolve mechanism conflicts by checking the mechanism chain and whether evidence is direct, indirect, or only suggestive.
- Resolve placement conflicts by asking whether the item supports the argument spine or only documents robustness.
- Resolve language conflicts by restoring the substantive claim and concrete
  evidence boundary in compressed form; do not restore redundant disclaimer
  wording merely because it appeared in an earlier draft.
- Resolve literature conflicts through the coverage contract, admitted
  inspected sources, and text-to-evidence ledger. An unsupported claim returns
  `evidence_conflict`; an unresolved applicable cluster returns `fail`. Offer a
  weaker author-facing candidate but do not silently weaken frozen intent or
  use a `TODO` when the source gap changes meaning or claim strength.
- Resolve caveat-discipline conflicts by preserving the governing semantic
  boundary at its first necessary placement and removing no-information
  repetition. Repeat only for a changed method, sample, period, geography,
  extrapolation target, or evidence level; standalone readability; or explicit
  journal/referee demand. Do not use a per-section quota.
- Resolve citation-closure conflicts with the authoritative library manifest,
  literature registry, manuscript citekeys, ledger unit links, and the
  deterministic citation report. Unauthorized `nocite` returns
  `approval_required`; missing, stale, or invalid required audit output returns
  `audit_incomplete`; unmeasurable formats return `metric_unavailable`.
- Resolve artifact-budget conflicts by restoring accepted material, narrowing the proposed compression, or obtaining a scoped user approval. Do not change the baseline to clear the gate.
- Resolve main-versus-appendix conflicts by restoring a sufficient main-text explanation or reversing the move. Appendix existence alone does not resolve the conflict.
- Resolve intent-coverage and definition conflicts through the authoritative
  contract, content obligations, definition registry, and inspected context.
  If repair changes meaning, request author change control rather than selecting
  a smoother interpretation.
- Resolve semantic-review disagreements by authority and evidence, never by
  majority vote. A critical failure, `uncertain`, absent reviewer, stale or
  invalid result, uncovered target/container, or unresolved disagreement
  remains blocking.

When a reviewer-reported conflict is closed, serialize the decision as the
independent, manifest-bound `qa-conflict-resolution/1.0` object in
`handoff_templates.md` and pass it through `--conflict-resolution`. The
resolver may not reuse a reviewer native agent/task identity, and its live
authority artifact must be the exact governing author-intent contract,
evidence registry, definition authority, or supplied deterministic gate.

Do not send a failing candidate to diction or final consistency. Prepare the
current-hash QA manifest, collect the required isolated findings, validate
coverage, apply only bounded controller patches, and re-review changed and
dependent units. After the semantic gate passes, diction edits require another
semantic re-review. When literature audit is triggered, run deterministic
citation integrity and obtain the independent, current-hash
`literature-coverage-audit/1.0` result through its separate
`literature-audit-assignment/1.0` record, without adding that role to the
five-role assignment registry. Any candidate byte change invalidates both
literature artifacts. Run `scripts/validate_literature_audit.py` over their
live inputs and require its `literature-audit-validation/1.0` pass; neither a
role self-report nor deterministic citation pass alone closes the gate. Then
run the final deterministic conservation audit and
Main-Text Sufficiency and Conservation Role. Treat `metric_unavailable`,
`audit_incomplete`, `clarification_required`, `evidence_conflict`, unapproved
`approval_required`, and `fail` as stop conditions, not passes.

## Final Integration Output

For large tasks, return:

```text
Integrated decision:
What changed:
What was preserved:
Artifact-gate status:
Semantic-QA status and reviewed manuscript hash:
Literature-coverage and citation-integrity status:
Conservation-ledger status:
Conflicts resolved:
Remaining non-semantic TODOs or blocking statuses:
Next recommended pass:
```

Do not expose long internal role transcripts unless the user asks. Summarize what matters for the paper.
