# Artifact State And Freeze Protocol

## Contents

1. Purpose and scope
2. Storage roles and authority
3. Two-dimensional state model
4. Allowed transitions
5. Mandatory freeze bundle
6. Registry schema
7. Freeze procedure
8. Safe replacement and superseded audit bundles
9. Manuscript integration
10. Rejection and cleanup
11. Compatibility with manuscript conservation

## 1. Purpose And Scope

Use this protocol for a multi-step paper project or major paper section that
creates, approves, freezes, replaces, rejects, or inserts tables, figures,
maps, measures, specifications, model outputs, or other research objects.

Do not impose a full current-artifact store on a bounded prose edit or a small
one-off diagnostic unless the user requests it. Once a project uses
`frozen-current`, every frozen object must follow this complete protocol.

## 2. Storage Roles And Authority

Keep these roles distinct:

- **candidate workspace**: exploratory and candidate revisions; never present
  it as the authoritative current result;
- **current-artifact store**: exactly one verified current revision for each
  stable artifact ID or paper role;
- **superseded audit store**: immutable, recoverable snapshots of formerly
  frozen revisions;
- **authoritative current plan**: the latest accepted paper role, placement,
  terminology, limitations, and authorization boundary;
- **task log**: chronological process and decisions; not a substitute for
  frozen files, manifests, or registry entries.

Apply authority in this order: explicit user decision, nearest project
instructions, verified journal or submission constraints, then this protocol.
Never infer author approval from successful generation, validation, favorable
feedback, or manuscript usefulness.

## 3. Two-Dimensional State Model

Record lifecycle and manuscript integration separately.

```text
artifact_state:
  exploratory | candidate | author-confirmed | frozen-current | rejected | superseded

manuscript_state:
  not-integrated | manuscript-integrated
```

`artifact_state` describes the research object's authority. `manuscript_state`
describes whether a particular frozen revision has been inserted into at least
one identified manuscript version. It does not replace `artifact_state`.

Use a stable `artifact_id` for the logical paper object and a unique
`revision_id` for each immutable revision. A frozen current revision and its
superseded predecessor may share the same `artifact_id` but must never share a
`revision_id`.

## 4. Allowed Transitions

Use only these default transitions:

```text
exploratory -> candidate
exploratory -> rejected
candidate -> author-confirmed
candidate -> rejected
author-confirmed -> candidate
author-confirmed -> frozen-current
author-confirmed -> rejected
frozen-current -> superseded
```

Apply these rules:

- `author-confirmed` requires explicit substantive approval.
- `frozen-current` requires a separate freeze approval and a verified freeze
  bundle and registry entry.
- `rejected` applies to an exploratory, candidate, or author-confirmed revision
  that never became current.
- `superseded` applies only to a formerly `frozen-current` revision replaced by
  a newly approved and verified current revision.
- Revise a frozen object by creating a new candidate outside the current store.
  Never mutate the only frozen current copy in place.
- Change `manuscript_state` only through the separate integration procedure.
- Reopening a rejected or superseded idea creates a new candidate event and
  revision ID; it does not silently restore the old authority state.

## 5. Mandatory Freeze Bundle

Every `frozen-current` revision must have a recoverable freeze bundle. The
bundle may reference immutable external raw inputs rather than duplicating
large files, but every dependency must be recoverable and verifiable.

Include:

1. executable generating code or an immutable code snapshot;
2. the exact generation command, parameters, environment or tool versions,
   and repository commit when applicable;
3. an input manifest with every local file's SHA-256;
4. an immutable version, query, or local snapshot for remote/database inputs;
5. final rendered outputs and machine-readable values where applicable;
6. validation reports, logs, and substantive audit records;
7. the substantive contract: measure, sample, specification, displayed
   content, layout, terminology, known limitations, and paper role;
8. the author approval record;
9. a freeze manifest and `SHA256SUMS.txt`.

Use SHA-256 lower-case hexadecimal digests. Record paths relative to the
bundle root when possible. `SHA256SUMS.txt` must cover all frozen local code,
input-manifest or input-snapshot, output, validation, and registry-snapshot
files except the checksum file itself.

Do not mark a freeze complete when a mutable remote input lacks an immutable
version or local snapshot, when executable code is dirty but not copied into
the bundle, or when a required file cannot be hashed. Record the freeze as
blocked and ask the user before adopting a weaker contract.

## 6. Registry Schema

Maintain a machine-readable registry entry for every frozen artifact. Use this
minimum schema; projects may add stricter fields.

```text
schema_version: "1.0"
artifact_id:
revision_id:
artifact_state: frozen-current
manuscript_state: not-integrated | manuscript-integrated
paper_role:
current_paths:
freeze_bundle_path:
checksum_manifest_path:
generator:
  command:
  code_repository:
  code_commit_or_version:
  environment_or_tool_versions:
files:
  code:
    - path:
      sha256:
  inputs:
    - path_or_uri:
      role:
      immutable_version_or_snapshot:
      sha256:
  outputs:
    - path:
      role:
      sha256:
  validation:
    - path:
      status:
      sha256:
substantive_contract:
  measure:
  sample:
  specification:
  displayed_content:
  layout:
  terminology:
  known_limitations:
approval_records:
  substantive:
    approved_by:
    approved_at:
    approved_scope:
  freeze:
    approved_by:
    approved_at:
    approved_scope:
integrations:
  - manuscript_path:
    manuscript_version_or_hash:
    location:
    integrated_revision_id:
    approved_by:
    approved_at:
    integrated_at:
supersedes_revision_id:
superseded_by_revision_id:
created_at:
updated_at:
```

Use an empty `integrations` list with `manuscript_state: not-integrated`.
Derive `manuscript-integrated` only when at least one verified integration
record exists. Do not store invented timestamps, approvals, hashes, or paths.

## 7. Freeze Procedure

After explicit freeze approval:

1. Assign the stable `artifact_id` and new immutable `revision_id`.
2. Assemble the candidate freeze bundle outside the current-artifact store.
3. Generate and verify all SHA-256 values.
4. Run the substantive and rendered-artifact validation appropriate to the
   object; command success alone is insufficient.
5. Create the registry entry and registry snapshot.
6. Regenerate `SHA256SUMS.txt` if the registry snapshot changed, then verify
   every listed file.
7. Place the verified revision at the stable current paths using a recoverable
   switch; do not overwrite the only valid current copy before verification.
8. Update the central registry and authoritative current plan.
9. Recheck the installed/current files against the freeze manifest.
10. Report the freeze complete only after all checks pass.

If no prior current revision exists, the verified candidate becomes
`frozen-current`. If a prior current revision exists, use the replacement
procedure below.

## 8. Safe Replacement And Superseded Audit Bundles

Do not revise a frozen current object in place. Build the proposed revision as
a candidate, obtain substantive approval, freeze approval for the new
revision, and replacement approval for retiring the old current revision.
Validate the proposed replacement before touching stable current paths; none
of these approvals substitutes for another.

Before replacement:

1. Create an immutable superseded audit bundle outside the current-artifact
   store for the old `revision_id`.
2. Include or reference recoverably the old generating code, immutable input
   manifest, old outputs, machine-readable values, validation records, old
   registry entry, approval records, and verified SHA-256 manifest.
3. Verify that the audit bundle reconstructs the old revision and that its
   checksums pass.
4. Record the proposed `supersedes_revision_id` and
   `superseded_by_revision_id`.

Only then switch the verified replacement into the stable current paths.
After the switch:

- mark the old revision `superseded` in the audit registry;
- mark the replacement `frozen-current` in the current registry;
- verify that exactly one revision for the stable artifact ID or paper role is
  current;
- verify stable paths and hashes against the replacement freeze manifest;
- update the authoritative current plan.

Removing the old revision from the current store is current-state cleanup, not
permission to delete its audit bundle, original inputs, or historical
manuscript integration records.

## 9. Manuscript Integration

Freezing never authorizes manuscript edits. Before integration:

1. identify the exact frozen `artifact_id` and `revision_id`;
2. verify current paths and checksums;
3. specify the target manuscript path and version/hash, insertion location,
   caption/note treatment, and anything that will remain untouched;
4. obtain separate manuscript-integration approval;
5. edit and verify the actual Word/LaTeX/PDF artifact under the applicable
   manuscript rules;
6. add an integration record to the registry.

An integration record does not change `artifact_state`. A `frozen-current`
revision remains current after integration. If it is later superseded, retain
its old integration records because an earlier manuscript may still depend on
that revision.

## 10. Rejection And Cleanup

Do not put rejected candidates in the current-artifact store. Record the
rejection decision and enough provenance to prevent accidental reuse.

Clean generated candidate clutter only when the exact targets are known and
the action is recoverable or explicitly authorized. Rejection and supersession
never authorize deletion of original source data, user-provided code,
historical approvals, immutable audit bundles, or manuscript evidence.

## 11. Compatibility With Manuscript Conservation

This protocol governs the authority, reproducibility, and recovery of research
objects. The multiagent manuscript `artifact_contract` governs an accepted
manuscript baseline, rewrite mode, length or depth budgets, main-text
sufficiency, and content conservation.

When a mature manuscript revision uses frozen research objects, maintain both:

- use this lifecycle registry to identify the authoritative object revision;
- use the manuscript artifact contract and conservation ledger to protect
  accepted manuscript content and approved placement.

Do not rename, merge, or substitute the two records. A passing freeze manifest
does not authorize manuscript compression or integration, and a passing
manuscript conservation audit does not freeze a table, figure, measure, model,
or result.
