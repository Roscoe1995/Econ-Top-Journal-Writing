# Literature Coverage And Citation Integrity

Use this protocol for a full paper or proposal, major revision or restructure,
substantive literature change, project-specific literature target, or final
audit of a manuscript with references. Use the lighter grounding protocol for
a bounded wording edit that neither changes claims nor changes citations.

The objective is a closed, auditable citation system. A long bibliography is
not evidence of adequate coverage, and a short bibliography is not by itself a
failure. Coverage is judged against the paper's functions and an explicit
project contract; citation integrity is judged against the manuscript and its
authoritative metadata.

## 1. Authority Layers

Keep these layers distinct:

1. `reference-library-manifest/1.0` is the sole authority over bibliographic
   metadata and may point to one or more `.bib` files. Multiple files are one
   logical library only when the manifest lists them and their hashes.
2. `literature-registry/1.0` records whether each item is `candidate`,
   `inspected`, `admitted`, `rejected`, or `superseded`, and which coverage or
   evidence role it may serve. It does not duplicate the full metadata.
3. The existing `text_to_evidence_ledger` maps manuscript unit IDs and claim
   IDs to admitted citekeys and the exact support relationship.
4. The final visible bibliography is derived from citekeys used in the
   manuscript plus explicitly authorized `nocite` items. It is an output, not
   a competing metadata authority.

The `literature-coverage-contract/1.0` governs which functional clusters must
be covered and when searching or inspection may stop. It constrains all four
layers but does not replace any of them.

An unused item may remain in an authoritative `.bib` library. Do not delete it
merely because a sentence or cite command was removed. An item that appears in
the final visible bibliography without a manuscript citation or explicit
`nocite` authorization fails closure.

## 2. Literature Coverage Contract

Use this minimum machine-readable shape:

```text
schema_id: literature-coverage-contract/1.0
schema_version: "1.0"
contract_id:
contract_revision:
reference_library_manifest_sha256:
literature_registry_sha256:
manuscript_id_or_path:
baseline_or_candidate_manuscript_hash:  # optional; final audit binds the live candidate
task_stage:
search_scope:
  databases_or_closed_corpus:
  languages:
  coverage_end_date:       # ISO-8601 date
  source_types:
  inclusion_criteria:
  exclusion_criteria:
coverage_clusters:
  - cluster_id:
    function: closest_contribution | theory_mechanism | data_measurement_institution |
      method_identification_model | contrary_evidence_alternative_explanation |
      recent_frontier | project_specific
    applicable: true | false
    rationale:
    known_gap:
    gap_disposition: resolved | fail | not_applicable
source_count_policy:
  minimum_verified_sources:       # optional
  target_range:                   # optional
  provenance: author_requirement | journal_rule | comparable_paper_sample
  provenance_record:
  enforcement: advisory | hard | required | approval_required  # optional; default advisory
nocite_authorizations:            # optional; covered by this contract's approval_record
  - citekeys:
    status: approved | authorized | confirmed | current
    reason:
stop_condition:
unresolved_gaps:
approval_record:
  confirmed_by:
  confirmed_at:
```

Evaluate these clusters when applicable:

- the closest work needed to locate the contribution;
- theoretical foundations and mechanism evidence;
- data, measurement, institutional, and historical sources;
- method, identification, estimator, or model precedents;
- contrary evidence and credible alternative explanations;
- the recent frontier up to the contract's coverage date;
- any field- or project-specific cluster the author records.

Mark a cluster inapplicable with a reason rather than silently omitting it.
Every paper-level contract must therefore contain at least one declaration for
each of the six standard functions above; `project_specific` may add further
clusters but cannot replace a standard declaration. An empty or partial
functional universe is `audit_incomplete`, not evidence that the omitted
functions are inapplicable.
Finding many papers in one cluster cannot compensate for a missing applicable
cluster. An unresolved applicable cluster remains `fail`; author approval may
narrow or revise the contract, but it does not turn a known coverage gap into a
passing audit.

This skill has no global minimum reference count. A project may set
`minimum_verified_sources` or a target range only when the contract records a
recoverable author instruction, journal rule, or reproducible sample of
comparable papers. Omit the numerical fields when no such provenance exists;
when they do exist, count unique inspected and admitted sources rather than
candidate or duplicate versions. Operationally, a counted source must be an
`admitted` registry entry with recoverable `inspection_evidence`; an
`inspected`-only entry has not yet been admitted to the paper. Do not invent a
numerical target from field intuition. Conversely, meeting a configured count
does not close an unresolved cluster.

For a configured `target_range`, falling below the lower endpoint fails the
frozen project target. The upper endpoint is advisory by default because more
verified sources may be substantively necessary; only a recorded hard
enforcement setting returns `approval_required` when the candidate exceeds it.
An unknown enforcement value is `audit_incomplete`, not an implicit advisory
fallback.

The registry is the authority for each source's coverage role. Do not maintain
a second live citekey list inside the contract. If a legacy contract contains
an `admitted_citekeys` snapshot, treat it as optional frozen evidence that must
match the current registry, never as a competing admission authority.

The stop condition must be substantive and auditable, such as saturation of
the active clusters after the stated databases, languages, dates, and
inclusion criteria have been checked. “Enough papers found” is not a stop
condition.

## 3. Reference Library Manifest

Use this minimum shape:

```text
schema_id: reference-library-manifest/1.0
schema_version: "1.0"
library_id:
library_revision:
project_root:
sources:
  - path:
    format: bibtex
    sha256:
normalization_policy:
duplicate_resolution_policy:
generated_at:
```

Each citekey used by the manuscript or registry must resolve to exactly one
current metadata record across the manifested sources. Duplicate citekeys are
errors. Duplicate DOI values are errors until resolved. Normalized-title
matches are review candidates because legitimate translations or versions may
share similar titles.

Prefer the published version when that is the paper actually cited. Keep a
working-paper version only when it is substantively distinct or the author has
a recorded reason. Link superseded versions in the registry instead of leaving
two apparently current identities.

Do not treat a compiled `.bbl`, manually typed reference list, source ledger,
or model-generated citation as bibliographic authority. They must resolve back
to the manifest.

## 4. Literature Registry

Use this minimum shape:

```text
schema_id: literature-registry/1.0
schema_version: "1.0"
registry_id:
registry_revision:
library_id:
library_revision:
library_manifest_sha256:
entries:
  - citekey:
    status: candidate | inspected | admitted | rejected | superseded
    inspection_evidence:
    coverage_cluster_ids:
    allowed_support_roles:
    limitation_or_non_support:
    supersedes_citekey:
    superseded_by_citekey:
    decision_record:
```

Store the registry file's SHA-256 in its consumer manifest, paper state, or
audit report, not inside the registry itself; a file cannot authoritatively
contain its own hash.

Use states consistently:

- `candidate`: discovered but not yet inspected; cannot support manuscript
  claims;
- `inspected`: the relevant source content has been checked, but the item has
  not yet been admitted to this paper;
- `admitted`: approved for at least one recorded coverage or evidence role;
- `rejected`: considered and not admitted;
- `superseded`: replaced by another version or record while retaining
  provenance.

A citation in prose must resolve to an `admitted` item with recoverable
inspection evidence. Inspection evidence should identify the local source or
verified record used; a title, search snippet, or model recollection is not
enough for a substantive support claim. `Inspected` and `admitted` are states,
not two items that may be double-counted; admission retains the inspection
evidence that justified the decision.

## 5. Text-To-Evidence Ledger

Continue using the existing ledger rather than creating a second claim-source
authority. Add citekeys and reader-visible unit IDs when they are absent:

```text
schema_id: text-to-evidence-ledger/1.0
schema_version: "1.0"
ledger_id:
ledger_revision:
qa_manifest_sha256:
manuscript_sha256:
expanded_manuscript_sha256:
literature_registry_sha256:
entries:
  - claim_id:
    unit_id:
    claim_type:
    citekeys:
    support_role:
    support_strength:
    source_locator:
    status:
```

For a new draft, initialize this authority before writing with
`status: pending_candidate`; do not invent sentence IDs. Fill its citekey and
reader-visible unit mappings only after a provisional deterministic manuscript
manifest exists, then hash the completed ledger and use that exact version for
citation and literature audit.

The ledger must distinguish background, definition, method precedent,
motivation, direct evidentiary support, contrary evidence, and contribution
comparison. A paper admitted for background does not automatically support a
causal, mechanism, or magnitude claim.

If a manuscript claim lacks adequate support, return `evidence_conflict`; do
not repair it by inserting a plausible citation. If deleting a citation would
leave a claim unsupported or an active coverage cluster empty, stop and ask
for a substantive decision rather than making a mechanical deletion.

Changing the admitted literature in a way that changes contribution
positioning, mechanism, or claim strength is an author-intent change. Reopen
the affected intent entries before revising the manuscript.

## 6. Draft And Final Citation Closure

In draft mode, verify at least:

- every manuscript citekey exists in the manifested library;
- every used citekey is admitted in the registry;
- every ledger citekey and unit ID resolves to current manuscript content;
- duplicate citekeys and duplicate DOI values are resolved;
- every applicable coverage cluster has a valid disposition;
- any configured source-count target is evaluated under its recorded
  provenance.

In final mode, also verify:

- the visible bibliography corresponds exactly to manuscript citekeys plus
  authorized `nocite` entries;
- every visible uncited item has a specific authorization record;
- removed manuscript citations do not survive only because a stale `.bbl` or
  hand-maintained list was reused;
- the manuscript, contracts, manifests, registries, ledgers, source files, and
  audit report are bound by SHA-256.

Final mode requires a fresh build record rather than inferring freshness from
the visible bibliography's existence. Use this minimum artifact and pass it to
`audit_citation_integrity.py` with `--bibliography-build-attestation`:

```text
schema_id: bibliography-build-attestation/1.0
schema_version: "1.0"
status: current
expanded_manuscript_sha256:
reference_library_manifest_sha256:
reference_library_files:
  - path:
    sha256:
visible_bibliography_sha256:
qa_manifest_sha256:
build_timestamp:  # timezone-aware ISO-8601
build_tool:       # compiler, script, or explicit manual-build identity
```

The deterministic report is a citation-integrity gate only. It must carry
`scope: citation_integrity_gate_only`,
`whole_manuscript_delivery_authorized: false`, and no `delivery_status` field.
Only the controller may derive whole-manuscript delivery after every applicable
gate has passed.

An unlisted or unauthorized `nocite` item returns `approval_required`. A stale
or missing required audit returns `audit_incomplete`. An unresolved functional
coverage gap returns `fail`. A claim whose admitted sources do not support its
strength returns `evidence_conflict`. When the format cannot be measured
reliably, return `metric_unavailable` rather than claiming closure.

Plain `.txt` can pass deterministic citation audit only when it contains the
structured citation markers required by the project. Version 1 does not infer
citations from ordinary prose and does not directly parse DOCX; export DOCX to
supported text, Markdown, or TeX without changing citation identities.

## 7. Focused Positioning Versus Full Coverage

A contribution-positioning passage may foreground roughly five to ten of the
closest and most recent papers when that produces a clear narrative. This is a
presentation choice for the focused passage, not a cap on the paper's complete
reference set. Foundations, mechanisms, data and institutional sources,
methods, contrary evidence, and other active clusters may require additional
citations elsewhere.

Do not pad the focused paragraph with every admitted item. Do not use the
focused paragraph's small number to justify an under-researched paper. The
coverage contract governs completeness; the paragraph's function governs
which sources it foregrounds.

## 8. Caveats In Literature Prose

Calibrate literature claims with accurate verbs and support roles. Do not
append a generic disclaimer after every cited finding. State a source-specific
population, period, identification, or evidence limitation when it changes how
the current paper may use that source, and avoid repeating it under unchanged
conditions. Disagreement or contrary evidence should enter the appropriate
coverage cluster, not be reduced to formulaic defensive prose.

## 9. Final Check

Before accepting literature-dependent manuscript text, confirm:

- the active contract and its coverage date match the task;
- all applicable clusters are resolved and the stop condition is met;
- library metadata, registry decisions, ledger links, manuscript citekeys, and
  visible bibliography form one recoverable chain;
- unused library inventory is not mistaken for a final-bibliography error;
- no unauthorized visible bibliography item or `nocite` survives;
- every substantive source claim is based on an inspected, admitted item;
- source deletion has not created an evidence or coverage gap;
- source addition has not silently changed the frozen author intent;
- focused literature prose is concise without being treated as the paper's
  total reference ceiling.
