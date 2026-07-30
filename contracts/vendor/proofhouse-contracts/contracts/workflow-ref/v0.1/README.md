# WorkflowRef V0.1

`WorkflowRef` V0.1 is the owner-approved closed, metadata-only reference to
Workflow Context-owned immutable workflow state. Workflow Context is sole
semantic owner, sensitivity authority, and canonical producer. Readiness is the
sole initial strict consumer. This private Contracts repository distributes
immutable artifacts only and gains no workflow semantics, records, sensitivity,
producer, runtime, access, use, or release authority.

## Exact wire

The closed envelope contains exactly `contract_version`, `contract_name`,
`producer_capability`, `producer_system`, `canonical_owner`, `issued_at`,
`cache_policy`, and `ref`. Constants require
`proofhouse-shared-contracts/v0.1`, `WorkflowRef`, `workflow_context`,
`proofhouse-workflow-context`, `workflow_context`, and `ref_only`.

The closed core contains exactly `ref_id`, `ref_type`, `source_capability`,
`organization_id`, `environment_id`, `external_uri`, `snapshot_id`, `version`,
`created_at`, and `workflow_id`. Every field is required. `ref_id` is
`workflow:<workflow_id>`; `ref_type=workflow` and
`source_capability=workflow_context`. Organization and environment are explicit,
non-placeholder scope. `external_uri` is a non-empty opaque locator for
owner-controlled authenticated dereference. `snapshot_id` and `version` are
non-empty immutable pins for the same referenced workflow state. `created_at`
is that immutable state's RFC 3339 creation time; envelope `issued_at` is the
separate RFC 3339 reference issuance time.

Unknown properties, scalar coercion, explicit null, blank or placeholder scope,
inferred project scope, missing identity or pins, mutable or timestamp-surrogate
pins, malformed timestamps, and mismatched `ref_id`/`workflow_id` fail canonical
validation. Consumers must not synthesize, repair, infer, or replace owner data.

## Validation and producer assertions

Raw JSON Schema is the portable structural layer. Generated strict Pydantic and
TypeScript/Ajv semantic validators additionally reject case-varied scope and pin
sentinels and enforce `ref_id`/`workflow_id` correspondence. Both pins are
required and independently validated as immutable. They are opaque identifiers
in potentially different namespaces, so string equality is not a valid
same-state check. Workflow Context must derive both from one canonical state and
test their co-reference against owner data. The V0.1 wire carries no mapping by
which Contracts or an offline consumer could independently infer that owner
truth. Authenticated owner dereference may apply separately authorized checks.

The deterministic indexed corpus covers constants, closure, required fields,
nulls, no coercion, scope sentinels, identity alignment, required immutable pins,
mutable and timestamp-shaped pins, RFC 3339 treatment, forbidden mutable fields,
recursive raw/source/customer/sensitive markers, the broad legacy shape, and
nested alignment lookalikes.

## Content and authority boundary

Canonical workflow truth remains in Workflow Context. The schema, fixtures,
corpus, bindings, manifests, digests, logs, and diagnostics contain no workflow
body, title, summary, subject, owner, review or workflow status, steps, controls,
evidence, policy, readiness result, incident, asset lineage, rights, approvals,
payload, source or customer content, personal or health data, payments,
credentials, secrets, or another capability's canonical truth.

Possession, validation, immutable pins, or successful dereference grants no
access, use, policy decision, approval, rights, release, export, product
readiness, remediation, gate state, external claim, or permission to act.
Contracts is not a consumer. Governance, Forge, Operational Learning, Scaffold,
IntakeEngine, Analyst, adapters, exports, and unnamed capabilities receive no
canonical producer or consumer assignment.

The nested `AttestedSpecRef` V0.2 `workflow_ref` remains immutable
Scaffold-local lineage/alignment metadata. It is not this canonical envelope and
is neither renamed nor mutated here. Other nested workflow alignment objects are
also noncanonical unless independently validated as this complete envelope at an
accepted immutable artifact pin.

## Compatibility, parity, and rollback

Workflow Context's prior broad `summary_snapshot` shape may remain only as an
explicitly legacy or noncanonical surface for one complete Workflow Context
release after canonical producer adoption. Readiness may temporarily adapt that
legacy input into this exact core before strict validation. Contracts never
distributes the broad shape as canonical.

This branch is a candidate dependent on later Workflow Context producer and
Readiness consumer parity against the identical corpus and digests. It is not
immutable publication. Candidate review does not claim publication, adoption,
runtime activation, public release, work-package completion, or gate closure.
Publication must precede downstream protected-main pin changes. Consumers pin a
full Contracts commit, schema SHA-256, every binding SHA-256, deterministic
corpus SHA-256, ownership metadata, and manifest digest; mutable refs, tags,
branches, abbreviated SHAs, sibling imports, and unpinned copies are forbidden.

Before downstream adoption, rollback is protected-main reversion of an affected
Contracts publication without rewriting accepted bytes. After adoption, each
product restores its prior exact immutable pin and retained noncanonical
compatibility mode independently. Released artifacts and accepted history stay
preserved.
