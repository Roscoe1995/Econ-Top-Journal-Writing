# Context Budget Rules

## Default Decision

Do not split small tasks. Multi-agent coordination has overhead and can make short edits worse.

Use the stable workflow or a child skill directly for:

- one paragraph;
- one abstract;
- one table note;
- one figure caption;
- a short translation;
- a narrow style cleanup.

## Split Work When

Use multi-agent or staged-agent coordination when at least one is true:

- the task spans multiple paper sections;
- there are many tables or figures;
- the user asks for a full draft;
- the manuscript and result package cannot fit comfortably in one working context;
- both Chinese and English writing decisions matter;
- literature, empirical design, table/figure placement, and prose all interact;
- revision involves many referee comments or many moving parts.

## Suggested Splits

- **Full paper draft**: frozen author intent, input audit, table/figure and
  argument logic, section drafting, exhaustive semantic QA, diction,
  post-diction re-review, conservation, and final consistency.
- **Major revision**: frozen author intent, referee issue map, table/figure
  changes, patch/reorder, exhaustive semantic QA, bounded repairs, diction
  re-review, and final conservation.
- **Large result package**: table/figure admission first, then argument spine, then prose.
- **Bilingual work**: settle paper facts and intent once, run separate
  language-specific drafting/diction passes, and audit each reader-visible
  language artifact against its own current hash.

## Keep Context Small

- `context budget != manuscript budget`.
- Pass only the fields needed for each role.
- Summarize long tables, but preserve coefficient values, samples, notes, and caveats needed for interpretation.
- Do not pass full papers or long source excerpts to every role.
- Keep handoff metadata and duplicated input context concise. Let the manuscript payload be as long as the section card and artifact contract require.
- Never infer a shorter manuscript from a smaller context budget.
- For long mature sections, return targeted patches, stable block moves, or bounded ledger slices instead of replacing the section with a short summary.
- Store the complete conservation ledger as a durable project artifact and pass only the relevant slice to each role.
- For sentence-level semantic QA, packet each unit with its full paragraph,
  necessary adjacent context, frozen intent and content-obligation slice,
  definition dependencies, evidence anchors, and section card. Do not isolate a
  sentence from context merely to save tokens.
- Partition a long manifest into deterministic packets and track complete unit
  coverage. Packet size may reduce what one reviewer sees at once; it may not
  remove reader-visible objects or sentence/heading targets from the audit
  universe.
- Enforce the QA contract's `max_units_per_packet` and `max_packet_bytes`
  limits. Multiple packets for one role are normal; omitting a packet,
  truncating a target, or treating a packet-size failure as a pass is not.
- Preserve reviewer isolation. Do not compress several nominal reviewers into
  sequential passes by the same agent and count that as independent review.

## Escalation Rule

If a role cannot answer because a non-semantic fact is missing, it should return
`Missing non-semantic information` and stop at a bounded recommendation. A
semantic ambiguity or evidence gap keeps `clarification_required` or
`evidence_conflict`; it must not be demoted to a `TODO`. The role should not
infer beyond the provided evidence.

If required native independent semantic reviewers cannot be provisioned,
return `audit_incomplete`. Context scarcity never authorizes a simulated pass.
