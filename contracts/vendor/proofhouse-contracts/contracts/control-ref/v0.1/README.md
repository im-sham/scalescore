# ControlRef V0.1

`ControlRef` is a private, immutable, metadata-only transport contract. Workflow Context is the semantic owner, sensitivity authority, and sole initial producer. Governance and Readiness are the only initial consumers. Governance is a carrier and consumer only and is never a producer.

The accepted authority is USMI protected main `9c63e4d674a7b4742a6ed75cb9a1814d46861063`, `decisions/2026-07-18-wp-ri-03-control-ref-d12-owner-acceptance.md`. Product-source mapping is Workflow Context protected main `f9304d7ffb6626599d4b66c02258016ea553a95a`, especially `app/workflows/models.py` and `app/workflows/service.py`. The accepted decision overrides product-source drift, including the prior full `control_statement` transport and the `evidence_status` field name.

## Bounded wire shape

The envelope fixes the producer, owner, and `summary_snapshot` cache policy. `ref` carries only:

- bounded reference and immutable snapshot/version identity;
- tenant, environment, workflow, control, and assignment identity;
- an authenticated Workflow Context dereference URI;
- a bounded summary;
- diagnostic implementation state: `planned`, `in_progress`, `implemented`, or `waived`;
- diagnostic linkage state: `missing`, `linked`, `verified`, or `not_applicable`; and
- an owning metadata-only `WorkflowRef` aligned across organization/tenant, environment, and workflow.

At least one of `snapshot_id` or `version` is required on both the control reference and owning `WorkflowRef`. Conformance validators enforce cross-field alignment that JSON Schema cannot express.

## Non-authority and sensitivity boundary

The reference and every status are diagnostic only. They grant no policy decision, Governance approval, use approval, release approval, external-use approval, gate completion, or permission to act. This repository distributes metadata and conformance assets only; it owns no `ControlRef` semantics or canonical Workflow Context truth.

The contract excludes full control statements, raw/source/customer payloads, customer data, credentials, and canonical Workflow Context, Governance, policy-decision, use-approval, or use-authority truth. Canonical detail is available only by dereferencing through an authenticated, tenant-scoped Workflow Context interface. Consumers must not reconstruct canonical detail from this contract, fixtures, bindings, caches, or carrier envelopes.

All fixtures are deterministic and synthetic. Shape similarity does not create canonical identity, status, detail, or authority.

## Migration and rollback

No historical distributed `ControlRef` artifact existed; this family does not fabricate one. Later producer and consumer migrations must retain their prior local adapter for one release, pin this immutable contract and corpus, and support pin-based rollback by restoring the prior implementation pin and retained adapter. Migration order is Contracts → Workflow Context producer → Governance consumer → Readiness consumer. A prior stage does not prove a later stage complete.

`PolicyDecisionRef` and `UseApprovalRef` are outside this family and are not implemented here.
