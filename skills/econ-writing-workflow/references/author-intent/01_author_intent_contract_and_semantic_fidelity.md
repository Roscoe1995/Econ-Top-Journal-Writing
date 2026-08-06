# Author Intent Contract And Semantic Fidelity

## Contents

1. Purpose and scope
2. Authority and compatibility
3. Contract levels and storage
4. Minimum contract schema
5. Elicitation and teach-back
6. Freeze and drafting permission
7. Writing within the contract
7A. Caveat placement without defensive repetition
8. Evidence conflicts
9. Change control
10. Semantic-fidelity audit
11. Mechanical-edit exception

## 1. Purpose And Scope

Use this protocol before writing or substantively rewriting claim-bearing
economics prose, including abstracts, introductions, literature positioning,
theory, research design, results, mechanisms, heterogeneity, contributions,
conclusions, proposals, captions, notes, and meaning-sensitive translations.

The objective is semantic fidelity: improve expression without allowing the
agent to add, delete, strengthen, weaken, reinterpret, or relocate a research
claim beyond the author's confirmed intent.

Do not apply the full elicitation protocol to spelling, citation format,
layout, or grammar-only edits when the author explicitly requires meaning to
remain unchanged. Use the narrow exception in section 11.

## 2. Authority And Compatibility

Apply two independent constraints:

- the author is the authority over what the paper is intended to say,
  emphasize, exclude, qualify, or avoid implying;
- inspected evidence is the authority over the strongest claim the paper can
  responsibly support.

Neither constraint overrides the other. Do not write an unsupported claim
merely because the author requests it. Do not silently replace the author's
meaning with a more defensible, fashionable, or rhetorically convenient claim.
Return the applicable gate state and request a contract revision.

Keep this contract distinct from:

- the paper-wide scope contract, which fixes the question, contribution
  structure, must-preserve content, non-goals, and terminology;
- the research-object lifecycle registry, which freezes tables, figures,
  measures, estimates, model outputs, code, inputs, and validation;
- the multiagent manuscript `artifact_contract`, which protects manuscript
  baseline content, length, placement, and main-text sufficiency.

Style, journal adaptation, diction cleanup, compression, literature framing,
and table/figure advice operate downstream of the current author-intent
contract. They cannot silently override it.

## 3. Contract Levels And Storage

Use the least granular level that makes the intended meaning unique:

1. **paper level**: central message, contribution order, evidence strength,
   paper-wide non-claims, and terminology;
2. **section level**: section function, required propositions, evidence role,
   relation to adjacent sections, and material that must not be introduced or
   repeated there;
3. **high-risk passage level**: subject, object, comparison, direction, claim
   type, mechanism status, scope conditions, qualifiers, implications, and
   forbidden frames.

Do not require paragraph-by-paragraph approval when a frozen paper- or
section-level entry uniquely governs the text. Create a passage-level entry
only when local ambiguity or risk remains.

For multi-step projects, keep one authoritative current contract in the
current-plan repository, or keep one separate contract file that the current
plan identifies by exact path and intent revision. Record the separate file's
SHA-256 in the current plan or task manifest when feasible; do not put a file's
self-hash inside the file being hashed. Do not maintain competing files that
look current. For a bounded task without a project repository, a compact
contract in the author-facing task record is sufficient.

Do not apply the research-object freeze bundle, generating-code manifest, or
input/output registry to an author-intent contract. Intent freezing requires
an authoritative current location, a unique intent revision, explicit author
confirmation (which normally supplies freeze authorization in the same act),
and recoverable supersession history.

A file hash proves that the approved contract text did not change; it does not
prove that the agent understood the author correctly. Explicit confirmation
and the post-draft semantic audit remain mandatory.

## 4. Minimum Contract Schema

Use this minimum structure. JSON is consumed directly. A sole authoritative
source in Markdown (`.md`/`.markdown`), YAML (`.yaml`/`.yml`), or plain text
(`.txt`/`.text`) is acceptable through the confirmed JSON QA-view adapter
defined by the multiagent protocol; version 1 does not accept an open-ended or
`unknown` adapter format. Keep the fields and meanings stable.

```text
schema_version: "1.0"
intent_contract_id:
intent_revision_id:
intent_status: proposed | frozen-current | superseded
gate_status: ready | clarification_required | evidence_conflict | fail
scope:
  level: paper | section | passage
  target_path_or_artifact:
  section_or_location:
source_context:
  manuscript_paths_or_versions:
  current_plan_path_or_version:
  evidence_anchors:
purpose:
reader_takeaway:
propositions:
  - intent_id:
    must_express:
    claim_type: descriptive | associational | causal | theoretical | normative
    subject:
    object_or_outcome:
    comparison:
    direction_or_relationship:
    mechanism_status:
    scope_conditions:
    evidence_anchors:
    required_qualifiers:
must_preserve:
must_not_claim:
must_not_imply:
forbidden_terms_or_frames:
terminology:
allowed_discretion:
caveat_placement_policy:  # optional frozen semantics and repetition policy
  - caveat_id:
    intent_id:
    boundary_meaning:
    preferred_first_location:
    permitted_repeat_triggers:
unresolved_material_questions:
approval_record:
  confirmed_by:
  confirmed_at:  # ISO-8601 with timezone
  confirmed_scope: complete | complete_author_intent | complete_author_intent_contract
  confirmation_source:
  freeze_authorized_by:
  freeze_authorized_at:  # same authorization event and timestamp as confirmation
  explicit_hold_reason:
supersedes_intent_revision_id:
superseded_by_intent_revision_id:
```

Do not invent an answer merely to fill a field. Omit an inapplicable field or
mark a material question unresolved and ask the author. A nonempty
`unresolved_material_questions` field requires `intent_status: proposed` and a
`clarification_required` gate; it can never coexist with `frozen-current` or
`ready`. Keep
`forbidden_terms_or_frames` optional unless the author identifies a wording or
frame whose presence itself would distort the intended message. Freeze
semantics by default, not every word.

Keep `required_qualifiers` backward compatible: an existing string or list
continues to state the semantic boundary. The optional
`caveat_placement_policy` freezes that boundary's preferred first location and
the material triggers that permit repetition. Keep any optional
`caveat_placement_registry` pointer in paper state or a handoff record, outside
this frozen contract. The derived registry must not convert one qualifier into
a sentence copied after every result, make mutable unit IDs part of the frozen
author meaning, or force a new author-intent hash whenever manuscript units
change.

## 5. Elicitation And Teach-Back

Before asking, inspect the relevant manuscript passages, current plan,
tables/figures, model or empirical evidence, author decisions, and terminology.
Do not ask for information already explicit and consistent in those sources.

If more than one materially different meaning remains possible, ask the
smallest grouped set of questions that would change the draft. Prioritize:

1. the proposition and intended reader takeaway;
2. descriptive, associational, causal, theoretical, or normative claim type;
3. subject, object, comparison, direction, and scope;
4. mechanism status and evidence strength;
5. necessary qualifiers and claims or implications to avoid;
6. required terminology and any genuinely forbidden frame.

Then teach the proposed contract back to the author in a short author-facing
block:

```text
My understanding for [scope]:
- Must express: ...
- Must preserve or qualify: ...
- Must not claim or imply: ...
- Evidence supports at most: ...
- I may change only: ...

Please correct any item. If accurate, please confirm. Unless you explicitly say
that it is only a candidate or that writing should remain paused, confirmation
will freeze it as the sole current intent contract for this drafting scope.
```

Do not draft the affected paper-facing text in the same turn when the proposed
meaning was reconstructed or remains unconfirmed. An explicit author
instruction may itself establish the contract without another confirmation
round only when it states one uniquely determined meaning, fixes the material
boundaries, and clearly authorizes the requested writing.

## 6. Freeze And Drafting Permission

Use these contract states:

```text
proposed -> frozen-current -> superseded
```

An explicit author confirmation of the teach-back normally both confirms the
meaning and freezes it as the sole current contract for the stated drafting
scope. Do not ask for a redundant second freeze approval. An initial author
instruction likewise enters `frozen-current` without another round when it
states one uniquely determined meaning, fixes the material boundaries, and
requests writing from that meaning.

When confirmation auto-freezes the contract, record the same author response,
scope, and timestamp in both the confirmation and freeze-authorization fields;
this is one approval event recorded in two audit fields, not two approvals.

Keep the contract `proposed` even after the author confirms your understanding
when any of these exceptions applies:

- the author explicitly says it is only a candidate, asks the agent not to
  write yet, reserves a coauthor or later decision, or otherwise withholds use;
- `unresolved_material_questions` is nonempty;
- an `evidence_conflict` blocks the intended claim.

The author-intent protocol has no separate writable `author-confirmed` state.
If an existing task record uses that label and contains a recoverable explicit
author confirmation for the stated scope, normalize it: with no exception
above it becomes `frozen-current`; otherwise it remains `proposed`. If the label
has no recoverable confirmation source, return `clarification_required`. Do not infer confirmation
from silence, favorable feedback, source consistency, or the fact that the
proposed meaning appears reasonable. This normalization applies only to author
intent; it does not merge confirmation, freeze, or manuscript-integration
approvals for research artifacts.

Use these gate outcomes:

- `ready`: one frozen-current contract covers the requested scope,
  `unresolved_material_questions` is empty, and no evidence conflict or explicit
  hold blocks it;
- `clarification_required`: a material intended meaning is missing,
  ambiguous, competing, or internally inconsistent;
- `evidence_conflict`: the intended claim exceeds, contradicts, or is not
  recoverably linked to the inspected evidence;
- `fail`: a draft already violates a frozen contract.

Only `ready` authorizes claim-bearing drafting. In any other state, stop the
affected scope, explain the exact issue, and request the smallest needed
decision. Do not use a `TODO`, tentative prose, or a plausible agent-selected
interpretation to simulate authorization.

Serialize the applicable `gate_status` in the current contract or its
authoritative paper-state pointer. Deterministic QA preparation must reject a
missing or non-`ready` gate before creating reviewer packets; it must not defer
an unconfirmed-intent failure until after reviewers have spent context.

## 7. Writing Within The Contract

Treat these as semantic invariants unless the frozen contract says otherwise:

- required propositions and reader takeaway;
- claim type and maximum claim strength;
- subject, object, comparison, direction, timing, and scope;
- distinction between design, result, heterogeneity, and mechanism evidence;
- evidence anchors and required qualifiers;
- must-preserve material, non-claims, forbidden implications, and stable terms.

Exercise rhetorical discretion only within `allowed_discretion`, normally
sentence syntax, transitions, ordering within the approved local function,
removal of genuine repetition, and concision that retains every invariant.

Do not silently:

- add an explanation, mechanism, motivation, contribution, policy claim, or
  normative judgment;
- delete a caveat, exception, secondary contribution, comparison, null result,
  or evidence limitation;
- convert association into causality, heterogeneity into mechanism proof, a
  planned test into a result, or suggestive evidence into a settled finding;
- broaden the population, period, geography, outcome, treatment, model domain,
  or external-validity claim;
- replace the author's emphasis because another framing seems stronger;
- use a forbidden term or frame, including through an equivalent implication.

The agent may propose alternatives in an author-facing memo. Label each one as
a candidate and state which frozen entries it would change. Do not insert an
alternative into manuscript prose until the author approves and freezes the
revised contract.

## 7A. Caveat Placement Without Defensive Repetition

Evidence-boundary accuracy and repeated disclaimer writing are different
requirements. Preserve the former and normally remove the latter. First choose
the correct claim type and a calibrated verb; then attach the minimum sample,
period, geography, identification, or evidence qualifier needed to interpret
the claim. Add a separate caveat sentence only when a material misreading would
otherwise remain, and place it at the first location where the issue matters.

Before admitting even the first or only stand-alone negative caveat, run this
admission test:

1. identify the exact preceding claim, number, estimate, threshold, scenario,
   or model object that the caveat would limit;
2. state the concrete and materially stronger reading that a reader could
   otherwise draw;
3. check whether the existing claim type, calibrated verb, or nearby scope
   wording already excludes that reading;
4. check whether the caveat introduces a new outcome, estimand, prediction, or
   policy object only to deny that the paper estimates it; and
5. first try an integrated affirmative explanation of what the object is, what
   it measures, and what interpretation it supports.

`Affirmative` means explanatory rather than favorable: it must not strengthen
the evidence or make the result sound more positive. If steps 2--4 show no
remaining material misreading, delete the negative sentence. If a negative
contrast is still necessary, bind it to the exact object in step 1 and use a
separate sentence only when the distinction cannot be stated clearly inside
the interpretation itself. The agent's conclusion that the contrast is useful
does not authorize manuscript text. If that exact negative proposition is not
already frozen in this contract, return `clarification_required`, show the
author the affirmative alternative and proposed contrast, and freeze it only
after the author's confirmation.

If the author approves the exceptional stand-alone sentence, store its exact
reader-visible wording in a new or superseding `propositions[].must_express`
entry with a distinct intent ID, update the contract revision, confirmation,
freeze record, and hash, and regenerate downstream QA. Do not merely change a
reviewer's `needs_author` verdict to `pass`. If the author rejects it, freeze
the affirmative integration or deletion outcome instead.

A derived `caveat_placement_registry` records where an authorized meaning is
satisfied; it cannot create authorization for a new negative proposition.

Repeat a caveat only when the identification method, sample, period,
geography, extrapolation target, or evidence grade changes; the text actually
draws a long-run, welfare, or external-validity conclusion; a stand-alone
abstract, caption, table or figure note must be self-contained; a specific
identifying assumption or local-validity condition governs the exact result;
or a journal, editor, or referee explicitly requires another statement.

Do not set a rule such as “one caveat per section.” Some sections need none;
others need more than one because their designs or scopes differ. Do not add
generic sentences about non-causality, non-extrapolation, or unavailable
long-run effects merely because a table or figure has appeared.

Deleting a unique no-information caveat or a later repetition does not weaken
the frozen intent when calibrated wording or the registered first location
still conveys the full boundary to every affected claim. If deletion would
leave a claim open to a materially stronger reading, rewrite the specific
boundary as affirmative interpretation where possible instead of restoring
generic defensive prose.

Do not write current sentence or unit IDs into the frozen author-intent
contract. When deterministic QA exists, maintain a derived registry with this
minimum shape:

```text
schema_id: caveat-placement-registry/1.0
schema_version: "1.0"
author_intent_revision_id:
author_intent_sha256:
manuscript_sha256:
entries:
  - caveat_id:
    intent_id:
    content_obligation_ids:  # optional; every obligation must trace to intent_id
    first_required_location:
    satisfied_by_unit_ids:
    permitted_repeat_triggers:
```

Rebuild and rehash that derived registry after manuscript unit IDs change. It
records presentation coverage only; the frozen intent and
`caveat_placement_policy` remain the semantic authority.

## 8. Evidence Conflicts

When author intent and evidence conflict:

1. identify the exact intended proposition and evidence anchor;
2. state whether the conflict concerns fact, sign, magnitude, causality,
   mechanism, scope, timing, comparison, or normative support;
3. give the strongest wording the evidence would support as an author-facing
   candidate, without substituting it into the manuscript;
4. ask the author whether to revise the intent, provide additional evidence,
   narrow the scope, or leave the affected text unwritten;
5. freeze a revised contract only after explicit approval.

Do not resolve the conflict by obeying unsupported intent or by silently
rewriting the paper into a different argument.

## 9. Change Control

Reopen only the affected intent entries when the author changes emphasis, new
evidence arrives, a source invalidates a claim, a target journal or section
function changes, or a contradiction is discovered.

Create a new `intent_revision_id`, record the reason and approval, and mark the
old revision `superseded`. Update the authoritative current plan when the
project has one; otherwise update the bounded task's authoritative intent
record. Preserve other frozen entries and do not repeat questions whose answers
remain current.

After a change, identify every downstream paragraph, abstract sentence,
conclusion sentence, caption, note, table/figure interpretation, and appendix
pointer that depends on the changed entry. Recheck only that dependency set
unless the change alters the paper-wide spine.

## 10. Semantic-Fidelity Audit

Before delivery or manuscript integration, create an author-facing coverage
ledger when the task is more than a trivial passage:

```text
intent_id | required or prohibited meaning | draft location | status | evidence
```

Check:

1. **coverage**: every `must_express` proposition appears in the approved
   location and retains its function;
2. **non-addition**: no substantive proposition, mechanism, explanation,
   contribution, implication, or policy claim was added without an intent ID;
3. **strength fidelity**: descriptive/associational/causal/theoretical/
   normative status and evidence strength did not change;
4. **scope fidelity**: subjects, comparisons, timing, population, geography,
   outcomes, treatment, and model domain did not broaden or contract silently;
5. **qualifier retention and placement**: every required boundary is conveyed
   by calibrated wording or at an adequate reader-visible location, while
   identical defensive restatements with no new scope or evidence information
   are merged; do not equate sentence repetition with semantic coverage;
6. **negative constraints**: no `must_not_claim`, `must_not_imply`, forbidden
   frame, or equivalent implication appears;
7. **cross-section consistency**: abstract, introduction, body, conclusion,
   captions, notes, and appendix pointers express compatible versions of the
   same intent;
8. **evidence alignment**: every empirical or literature-dependent statement
   remains linked to the approved evidence boundary.

Return `pass` only when all applicable checks succeed. If the prose violates
the contract but the contract remains valid, revise the prose and re-audit. If
repair requires changing meaning, return `clarification_required` or
`evidence_conflict` and ask the author before proceeding.

## 11. Mechanical-Edit Exception

The full elicitation and teach-back sequence is unnecessary only when:

1. the source wording and requested scope are available;
2. the task is limited to spelling, punctuation, citation formatting, layout,
   or grammar-only editing; and
3. either the user explicitly requires meaning to remain unchanged or the
   requested operation has one unambiguously mechanical, meaning-preserving
   correction;
4. the edit does not force a choice among materially different meanings.

Use the source plus the narrow requested operation as the baseline. Verify that
the edited text actually fixes the requested problem, including applicable
subject-verb agreement, pronoun antecedent and number, tense, negation, modifier
attachment, punctuation, and citation consistency. Then verify that no new
ambiguity or implication was introduced.
Preserve propositions, emphasis, uncertainty, qualifiers, logical relations,
and implications. If the mechanical edit exposes ambiguity or would require a
semantic choice, stop that item and return `clarification_required`; do not
silently choose the smoother interpretation.
