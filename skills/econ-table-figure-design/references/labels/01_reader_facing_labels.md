# Reader-Facing Labels And Bilingual Notes

Use this reference for every paper-facing table or figure. Treat it as the
single authority for titles, panels, row and column names, axes, legends,
colorbars, annotations, captions, and notes. Keep artifact-specific layout rules
in their existing table, figure, and visual-style references.

## Contents

1. Two-level acceptance
2. Concision and information placement
3. Chinese and English writing
4. Display mapping and unresolved meaning
5. Deterministic manifest and review
6. Typed exceptions
7. Final acceptance checklist

## 1. Two-Level Acceptance

### Basic identity gate

Give a cold reader only the artifact title or caption, panel headings, row and
column names, axes, legends, colorbar labels, and reader-visible annotations.
Require the reader to identify, at the level needed to read the numbers or
visual pattern:

- the economic or model object;
- the reported statistic, parameter, decomposition item, or relationship;
- the compared groups, periods, scenarios, or specifications;
- the subtraction, reference, or ordering direction when reversing it would
  change interpretation.

Fail this gate when a label is merely `Baseline`, `Difference`, `High group`,
`Low group`, `Coverage differs`, `Value`, `group1`, or a fluent-looking rewrite
of an internal variable name. Do not let a note or main-text paragraph rescue a
title-and-label layer that the reader cannot identify.

### Full recoverability gate

Next give the reviewer the nearest table or figure note, the registered full
definitions, and only the manuscript excerpts needed to interpret the
artifact. Require recovery of every applicable detail:

- unit and scale;
- sample, period, geography, and unit of observation;
- baseline, omitted group, and group threshold;
- numerator, denominator, and difference direction;
- log, residualization, standardization, normalization, or index construction;
- estimator, fixed effects, controls, standard-error or clustering convention;
- confidence-interval, bootstrap, resampling, weighting, or binning method;
- meanings of dashes, blanks, suppression markers, and other display symbols.

Return `clarification_required` rather than inventing a definition when any of
these details would change the public label or the way a reader interprets the
artifact.

## 2. Concision And Information Placement

- Use short, complete noun phrases for titles and labels. Avoid internal
  predicate fragments such as `the share differs` or `progress is different`.
- Put shared context in the title, a spanning header, or a panel heading. Keep
  row and column labels focused on what distinguishes them.
- Put construction details in the nearest note or manuscript definition when
  the title-and-label layer already supplies basic identity.
- Use controlled wrapping or a hierarchical header before shrinking type.
- Do not impose a universal character or word limit. Treat possible excess
  length as a review warning and decide it from the final rendering.
- Do not require every row to repeat the unit, sample, formula, or common
  comparison when an adjacent header states it unambiguously.
- The same short label may recur under different, explicit panel or spanning
  headers. Treat a cross-concept repetition as a hash-bound warning for the
  basic-identity cold reader, not as an automatic failure; it passes only when
  the visible hierarchy disambiguates every occurrence. An ambiguous repeat
  within one visible scope must receive a non-pass basic-identity verdict.

## 3. Chinese And English Writing

Maintain separate Chinese and English display-label maps. Bind both to the same
concept IDs and semantic signatures, but let each language use its natural
syntax. Do not default to mixed-language labels or literal line-by-line
translation.

### Chinese artifacts

- Use natural Chinese academic noun phrases. Prefer concrete objects such as
  `城市就业增幅` or `高收入组与低收入组之差（高−低）` to code-like or translated
  fragments.
- Avoid English word order, unexplained internal shorthand, stacked nouns, and
  the mechanical pattern `……不同` when the intended statistic is a difference,
  contribution, decomposition component, or counterfactual change.
- Start a table or figure note with `注：`. Write complete, economical Chinese
  sentences rather than telegraphic English templates.
- Write units and directions in standard Chinese forms such as `百分点`,
  `高收入组−低收入组`, or `相对政策实施前一年` when applicable.
- Retain standard forms such as GDP, DID, R², Q1/Q4, formal classification
  codes, and defined mathematical symbols only when they remain conventional
  and intelligible in the Chinese artifact.

### English artifacts

- Use concise, idiomatic economics-journal noun phrases. Follow the target
  journal or manuscript capitalization style; otherwise prefer consistent
  sentence case for descriptive labels.
- Avoid Chinese word order, literal translations, unexplained acronym stacks,
  and cosmetic rewrites such as `AI Fit Avg` that merely remove underscores.
- Start a table or figure note with `Notes:`. Use grammatical sentences that
  identify the sample, estimator, uncertainty convention, and special
  definitions when applicable.
- State comparison directions and units naturally, for example `High-income
  minus low-income cities` and `percentage points`.
- Retain standard abbreviations or symbols only when they are conventional or
  defined for the reader.

Apply the target journal's official rule before these defaults. A journal rule
may alter capitalization, note placement, or terminology; it cannot authorize
an opaque label or an unexplained internal identifier.

## 4. Display Mapping And Unresolved Meaning

Keep source identifiers and public display text separate:

```text
internal key -> concept ID -> semantic signature -> public label -> full definition
```

- Change only the display mapping when improving a label. Do not rename source
  variables, rewrite estimation code by regular expression, reorder results,
  or alter data, coefficients, standard errors, stars, or samples.
- Record the internal key even when it is ugly; never use its presence in code
  as a reason to display it.
- Record the object, statistic type, unit, transformation, comparison groups,
  direction, baseline, numerator, denominator, interval method, and time basis
  in a language-neutral semantic signature. Use `not_applicable` only when the
  field truly does not apply.
- Mark meaning as `unresolved` when the available material does not determine
  the label. Do not silently select the most plausible interpretation.
- Preserve the same semantic signature across separately written Chinese and
  English versions. Their public wording and full definitions need not be
  literal translations.

## 5. Deterministic Manifest And Review

For every code-generated paper-facing artifact and every delivery candidate,
run:

```bash
python3 scripts/audit_reader_facing_labels.py \
  --project-root PROJECT_ROOT \
  --manifest LABEL_MANIFEST.json \
  --review LABEL_REVIEW.json \
  --stage generated \
  --output LABEL_AUDIT.json
```

Use `--stage final` for final delivery. Add `--paired-manifest` and
`--paired-review` when validating separate Chinese and English versions
together.

Use `reader-facing-label-manifest/1.0`. Record at minimum:

- manifest identity and revision;
- artifact ID, path, SHA-256, stage, language, and operation type;
- every reader-visible slot, role, internal key, concept ID, public label, full
  definition, meaning status, semantic signature, and definition locations;
- notes and bounded manuscript context used for full recovery;
- numeric-content hashes appropriate to a new artifact or label-only revision.

Use these exact field groups rather than inventing parallel names:

- root: `schema_version`, `schema_id`, `manifest_id`,
  `manifest_revision`, and `artifact_family_id`;
- `artifact`: `artifact_id`, `path`, `sha256`, `stage`, `language`, and
  `operation`; use `zh-CN` or `en`, `generated` or `final`, and
  `new_artifact` or `label_only_revision`;
- `numeric_integrity`: a stable `canonicalization_id` plus an actual payload
  file and hash, a `payload_description` identifying the represented numeric
  cells, sample, and result metadata, and a `producer_source_locator` pointing
  to the generating code or deterministic procedure. A new artifact uses
  `numeric_payload_path` and `numeric_payload_sha256`; a label-only revision
  uses distinct `before_path` and `after_path` files with `before_sha256` and
  `after_sha256`. The script reads all declared payload files, verifies their
  hashes, and requires the verified before and after hashes to be equal;
- `note_status`, plus `notes` containing `note_id` and `text`; use
  `note_not_applicable_reason` only when `note_status` is `not_applicable`.
  If a target journal requires a nonstandard note heading, the affected note
  may add `style_exception` with the exact closed record
  `{type: "journal_style", reason, source_locator}`; no other exception type
  changes the language-specific `注：` or `Notes:` requirement;
- `contexts`: `context_id`, `source_locator`, and the bounded `text` supplied
  to the full-recoverability reviewer;
- `labels`: `slot_id`, `role`, `internal_key`, `concept_id`, `display_text`,
  `meaning_status`, `full_definition`, `definition_locations`, `exceptions`,
  and `semantic_signature`. `role` is one of `title`, `caption`, `panel`,
  `row`, `column`, `axis_x`, `axis_y`, `tick`, `legend`, `colorbar`, or
  `annotation`; `meaning_status` is `confirmed` or `unresolved`. Keep this
  array in the artifact's visible reading order so the cold-reader packet
  preserves panel and spanning-header context.

Every `semantic_signature` uses the same closed language-neutral fields:
`semantic_type`, `object_id`, `statistic_id`, `unit_code`,
`transformation_code`, `comparison_groups`, `direction_code`, `baseline_id`,
`numerator_id`, `denominator_id`, `interval_method_id`, and `time_basis_id`.
Use stable IDs, not translated prose, in these fields. Allowed semantic types
are `artifact_title`, `level`, `difference`, `ratio`, `interaction`,
`growth_rate`, `index`, `interval`, `parameter`, `category`, and `other`.
Use `not_applicable` only for a scalar field that truly does not apply; use an
empty `comparison_groups` list only when group identities do not apply.
For every confirmed `difference`, `interaction`, and `index`, `unit_code` must
name the unit or scale; use an explicit value such as `dimensionless`,
`index_points`, `standard_deviations`, or `percentage_points` rather than
`not_applicable`. Units may be rendered once in a visible shared header or note,
but they may not disappear from the semantic contract.

Use `reader-facing-label-review/1.0`. Bind it to the exact manifest and artifact
hashes. Record:

- the basic-identity verdict and every reviewed slot;
- the full-recoverability verdict and every reviewed slot;
- the language-style verdict;
- the final-render verdict for truncation, overlap, legibility, note display,
  and label fit;
- dispositions and reasons for every deterministic warning;
- whether the review used a native isolated agent or a bounded same-agent pass.

The review root uses `review_id`, `review_revision`, `reviewer`, `reviewed_at`,
`review_mode`, `manifest_sha256`, `artifact_sha256`, `stage`, and `language`.
Serialize `review_mode` as exactly `native_isolated_agent` or
`bounded_same_agent`.
Each of `basic_identity`, `full_recoverability`, and `language_style` contains
`status`, the exact `reviewed_element_ids`, and a substantive `summary`.
The exact sets differ: `basic_identity` covers every label slot;
`full_recoverability` covers every label slot plus every supplied note and
bounded context ID; `language_style` covers every label slot and note ID.
`render` contains `status`, `artifact_sha256`, `inspected_path`, the closed
boolean checks `visible_text_matches_manifest`, `no_truncation`, `no_overlap`,
`legible_without_excessive_font_reduction`, `notes_readable`, and `labels_fit`,
plus `observed_elements` with each `element_id` and normalized visible-text
`text_sha256`. `warning_dispositions` must cite the current `finding_id`, use
`accepted` or `false_positive`, explain the rationale, and repeat the current
reviewer and timestamp. The review also contains a `numeric_integrity` object
with `status`, the same `canonicalization_id` and `producer_source_locator`, a
substantive `summary` of how the payload corresponds to the artifact, and
`verified_payloads` listing the exact path and hash of every payload file.
Relative input and output paths are resolved against `--project-root`. The
output may replace only a prior report of the same schema; it may never collide
with a manifest, review, artifact, or numeric payload, and the script writes it
atomically. Standard output contains only a compact status summary; bounded
review text remains in the project-local report.

The script may prove declared-slot coverage, closed fields, typed exceptions,
hash freshness, paired semantic signatures, numeric-content conservation, and
high-confidence internal-code patterns. It cannot prove that a Chinese phrase
is natural, an English phrase is idiomatic, a definition is economically true,
an image contains every declared label, or a declared numeric payload was
truthfully extracted from the artifact. It proves the declared payload bytes
and their before-after equality; the hash-bound independent attestation must
check that the payload actually represents the artifact. Preserve the agent
review and final render inspection; never report the Python result as semantic
proof.

Treat unresolved deterministic warnings as `audit_incomplete`. Re-run after a
display revision instead of marking a still-present warning as fixed.
High-confidence failures take precedence in the top-level status. Strict JSON,
timezone-qualified timestamps, and a final input rehash prevent malformed,
stale, or concurrently changed inputs from being reported as current passes.

Internal diagnostics that will never be reader-facing are outside this gate.
A manually edited exploratory artifact may receive semantic review before a
manifest exists, but it must enter the full gate before code generation or
delivery.

## 6. Typed Exceptions

Allow an internal-looking display only through a closed exception type with a
reason and reader definition:

Every exception covers only its NFC-normalized, case-sensitive exact visible
token. A differently cased token requires its own valid record and cannot borrow
another token's exception. Compatibility-distinct forms that collapse under
NFKC also cannot share one exception record. Unicode combining marks and
connector punctuation, including Unicode identifier-continuation characters,
continue the visible token rather than creating a new boundary.

- `standard_abbreviation`: GDP, DID, R², or another established abbreviation. Conventional mixed-case forms are not a general camelCase escape: the deterministic gate recognizes only a closed set such as `PhD` and `DiD`, and only when the exact visible token has this typed exception;
  traditional dotted abbreviations such as `U.S.`, `Ph.D.`, and `M.Phil.` are
  not code identifiers;
- `mathematical_symbol`: a defined parameter such as α, β, or σ;
- `formal_classification_code`: ISCO-08, HS4, an official geographic code, or a
  survey item that is itself the research object;
- `replication_codebook`: a codebook or replication appendix that pairs the raw
  name with a distinct, non-overlapping reader-facing label in the same display;
  the visible `reader_label` span may not contain or overlap the raw token. It additionally
  requires `reader_label` and a bounded `source_locator`; its `token` must match
  the same label record's non-`not_applicable` `internal_key` exactly after NFC
  normalization, without case folding or compatibility folding. The token must
  itself be one closed raw-name or code expression; whitespace, reader prose, or
  punctuation-joined extra identifiers cannot be wrapped into a phrase-wide
  exception. This is the only
  non-mathematical exception type that can waive raw `_`, `#`, Stata, or
  generic code-token detection. A narrowly formed, defined subscripted symbol
  such as `x_i` or `β_i` may instead use `mathematical_symbol`; a multiword
  snake-case identifier may not;
- `column_number`: `(1)`–`(6)` when a higher header or note identifies the
  specification;
- `proper_name`: a formal product, dataset, institution, or legal name that
  should not be translated. A visible camel/Pascal token is otherwise treated as
  high-confidence code, including acronym-to-word forms such as `GDPGrowth`;
  this typed exception may preserve a genuine name such as `OpenAlex`. It cannot
  waive underscore, Stata, generic, or dotted-code
  detection. A dotted identifier such as `model.result` must use an exactly
  bound `replication_codebook` record when it is legitimately shown.

Do not maintain an unlimited allowlist. An exception does not waive basic
identity, full recoverability, language quality, or final-render review.

## 7. Final Acceptance Checklist

- Confirm that the title and labels alone pass basic identity.
- Confirm that notes and bounded context recover every applicable definition.
- Confirm that Chinese or English display text follows its own writing norms.
- Confirm that every internal key maps to the correct concept and public label.
- Confirm that difference, ratio, interaction, growth, index, and interval
  objects contain their required direction, denominator, baseline, time, or
  method metadata.
- Confirm that all warnings have current-hash dispositions.
- Confirm that any Chinese-English pair shares the same concept IDs and
  semantic signatures.
- Confirm that label-only revision leaves numeric-content hashes unchanged.
- Inspect the rendered PDF, Word page, image, or vector output for truncation,
  overlap, unreadable type, and omitted labels.
- Deliver only when the current report is `pass`; otherwise return the exact
  blocking status and affected slots.
