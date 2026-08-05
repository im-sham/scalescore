# Proofhouse Readiness

[![CI](https://github.com/im-sham/scalescore/actions/workflows/ci.yml/badge.svg)](https://github.com/im-sham/scalescore/actions/workflows/ci.yml)

**Workflow-First AI Operational Readiness Scoring**

> Know which AI-enabled workflows are ready to scale, and what will break trust first.

---

## Repository Note

Readiness is the active capability name for this layer inside the Proofhouse platform.

In this migration phase, the technical repo root, Python package, CLI commands, env vars, auth claims, and API routes remain `scalescore`. `ScaleScore` should be treated as the current technical identifier and internal lineage reference, not the preferred market-facing name. The planned repo-root target is `proofhouse-readiness`, but that rename is a later wave and is intentionally separate from runtime identifier changes.

---

## What is Readiness?

Readiness is the scoring and diagnostic layer for **AI-enabled operational readiness**.

It helps Proofhouse operators and operations leaders answer a more specific question than generic company scalability:

**Is this workflow ready to scale with AI without creating fragility, trust failures, or governance gaps?**

The current `scalescore` service still uses traditional operations signals such as capacity, dependencies, governance, and vendor concentration. The difference is that those signals are now interpreted through the lens of AI-assisted work, human oversight, and operational trust.

Readiness can also add a separate **Operational Learning suitability** lens for workflow reports. This sibling score evaluates candidate quality for internal eval use and internal training candidacy without changing `workflow_readiness_score`, and it does not replace Governance approval decisions.

The first flagship workflow profile is regulated document operations: a claims and benefits packet review flow with a normal reviewed case, an escalated exception case, and a redaction-review dependency before internal-eval use.

### Primary Jobs

Readiness produces:

1. **Workflow readiness scores** for AI-enabled use cases
2. **Pillar breakdowns** across stability, resilience, oversight, controls, and blast radius
3. **Top trust gaps** that could block safe AI scale
4. **Prioritized remediation actions** for operations leaders
5. **Organization rollups** derived from multiple workflow assessments
6. **Operational Learning suitability** for internal eval and internal training candidacy

### Examples

- Support triage with AI
- Finance close automation
- Vendor onboarding
- Knowledge intake and routing

---

## Product Boundaries

| Product | Job |
|---------|-----|
| **Workflow Context** | Canonical workflow truth, system of work, evidence linkage, operational context |
| **Readiness** | Readiness scoring, trust-gap diagnosis, remediation prioritization |
| **Governance** | Rights, policy, redaction review, use approvals, export control, manifests, audit-grade use control |
| **Forge** | Incident memory, failure-pattern learning, scoring-model refinement |

Readiness is primarily a Proofhouse suite capability. Any standalone product surface requires an explicit product decision and independent product rationale. Partnership, pilot, live-client, and GTM status remains in a separate non-product lane; its status cannot change Readiness product status or readiness, and partner/customer activation remains separately frozen.

Operational Learning suitability remains a Readiness scoring lens only. Readiness does not become the source of workflow truth, rights profiles, export eligibility, promotion approvals, or asset derivation.

Design-partner, advisor, consulting, customer-discovery, partnership, pilot, and live-client evidence is informative and non-authoritative. It cannot create, prioritize, block, complete, waive, accept, release, or authorize product roadmap work or any safety, security, privacy, legal, data, hosted, operational, release, or external-claim gate. Only an explicitly promoted sanitized, generalized problem with independent product rationale may enter product strategy, and that promotion requires product-owner acceptance.

---

## Compatibility Mode

Readiness is transitioning to workflow-first without breaking the current product surface.

- Current org-level CSV assessment flows remain supported.
- Current HTTP API endpoints remain supported.
- Current async, scheduling, persistence, and staging validation flows remain supported.
- Workflow-first readiness is now available as an additive Python/report contract.

Legacy `OpsOrchestra`, `Mila`, and `ScaleScore` naming is retained only where required for technical backward compatibility. User-facing narrative should prefer `Proofhouse`, `Workflow Context`, `Readiness`, `Governance`, and `Forge`.
Current repo/package/runtime identifiers also remain `scalescore` until a later rename wave.

---

## Quick Start

```bash
# Clone the current technical repository
git clone https://github.com/im-sham/scalescore.git
# The checkout folder can remain "scalescore" until the repo-root rename wave.
cd scalescore

# Create and activate a virtual environment owned by this checkout.
# Use Python 3.11 or 3.12; CI covers both supported minors.
# This example selects Python 3.12 to match its Python 3.12 constraint file.
# Every Git worktree must create its own .venv; never reuse another checkout's.
python3.12 -m venv .venv
source .venv/bin/activate

# This example is for Darwin arm64 with Python 3.12.
# On Linux x86_64, use the matching linux-x86_64 file instead.
# Python 3.11 users must select python3.11 and the matching Python 3.11 target file.
python -m pip install --constraint constraints/darwin-arm64-python3.12-dev.txt -e ".[dev]"

# Optional: install the separately constrained dashboard graph before launching it.
python -m pip install --constraint constraints/darwin-arm64-python3.12-frontend.txt -e ".[frontend]"

# Confirm "Editable project location" is this checkout, then run tests.
python -m pip show scalescore
python scripts/run_tests.py -q --ignore=tests/integration/test_redis_rate_limit.py

# Use development defaults (AUTH_SKIP_AUTH=true for local UI/API flow)
cp .env.example .env

# Run a CLI assessment on demo data
scalescore --dataset-path data

# Start the API server
uvicorn scalescore.api.main:app --reload

# Optional: run async worker runtime (background/broker modes)
# scalescore-worker

# Launch the dashboard
streamlit run ui/streamlit_app.py
```

`scripts/run_tests.py` fails closed if the active interpreter imports `scalescore` from
another checkout. It reports the interpreter, expected source, imported package path, and
commands for rebuilding only this checkout's `.venv`; pytest is not imported or collected
until that provenance check succeeds.

For a runtime-only environment, install `-e .` with the runtime file matching
the target environment (`darwin-arm64` or `linux-x86_64`) and Python minor.
Development installs use `-e ".[dev]"` with the matching development file;
dashboard installs use `-e ".[frontend]"` with the matching frontend file.
The twelve target-specific application constraint sets reproduce these three
accepted Readiness graphs without allowing frontend-only dependencies to
contaminate the core service graph. They are not cross-platform lock files,
do not define a production image, and do not establish rollback retention.

## Shared Request Limiter

Readiness uses one async limiter contract for login, signup, token refresh, API-key
creation, async-assessment submission, and scheduled-assessment creation. Development
and testing default to the bounded process-local backend. Staging and production must set
`RATE_LIMIT_BACKEND=redis` and a TLS `RATE_LIMIT_URL=rediss://...`; invalid or missing
hosted configuration prevents startup. A Redis outage fails closed with a redacted `503`
response and never falls back to process-local state. `RATE_LIMIT_NAMESPACE`,
`RATE_LIMIT_CONNECT_TIMEOUT_SECONDS`, `RATE_LIMIT_SOCKET_TIMEOUT_SECONDS`, and
`RATE_LIMIT_LOCAL_MAX_KEYS` configure isolation, network bounds, and the local-only key cap.

Run the real shared-quota, contention, expiry, and outage proof against a disposable Redis:

```bash
TEST_REDIS_RATE_LIMIT_URL=redis://127.0.0.1:6379/15 \
  python scripts/run_tests.py -q tests/integration/test_redis_rate_limit.py
```

Before downstream reliance, rollback is an isolated revert to
`cb9a84a6dddab2cadd0e178320399752942c3a64`. For any future hosted rollback, disable
traffic or keep an equivalent edge limiter in force; process-local fallback is not an
acceptable hosted rollback.

---

## Workflow-First Contract

The workflow-first contract is additive and currently lives in the Python/report layer while HTTP compatibility is preserved.

```python
from scalescore.core.assessment import run_assessment
from scalescore.models.core import Organization
from scalescore.models.scaling import WorkflowAssessmentContext, WorkflowBlastRadius

workflow = WorkflowAssessmentContext(
    workflow_id="wf_support_triage",
    name="Support Triage",
    business_function="operations",
    owner="COO",
    ai_role="Classify and route inbound support tickets",
    systems_touched=["zendesk", "crm"],
    human_escalation_path=["Support Manager", "COO"],
    control_requirements=["decision logging", "approval traceability"],
    blast_radius=WorkflowBlastRadius.MEDIUM,
    fallback_mode="Manual queue review",
    override_rights=["Support Manager", "COO"],
    error_tolerance="Low",
    reversibility="Routing changes can be reverted within the same shift",
)

report = run_assessment(
    organizations=[Organization(id="org_1", name="Acme")],
    systems=[],
    facilities=[],
    growth_signals=[],
    workflow_context=workflow,
)

print(report.workflow_readiness_score)
print(report.top_trust_gaps)
```

Workflow reports now support:

- `workflow_context`
- `workflow_ref`
- `assessment_ref`
- `workflow_readiness_score`
- `workflow_pillar_scores`
- `top_trust_gaps`
- `prioritized_remediation_actions`
- `operational_learning_suitability`
- optional summary/ref-only `document_operations_profile` input on the current Workflow Context compatibility route
- `org_rollup`

The compact Workflow-facing assessment endpoint defaults to a workflow-readiness
`AssessmentRef` and can explicitly emit an Operational Learning suitability
`AssessmentRef` when that lens was assessed. Both variants preserve the same
canonical WorkflowRef and persisted report alignment; neither grants approval,
training, export, promotion, or activation authority.

---

## Current Status

### Platform Status

| Component | Status |
|-----------|--------|
| Core models and scoring | ✅ Implemented |
| Assessment API and persistence | ✅ Implemented |
| Auth and API keys | ✅ Implemented |
| Async queue and scheduling slice | ✅ Implemented |
| Staging validation gate | ✅ Implemented |
| Workflow-first report contract | ✅ Initial additive slice implemented |
| HTTP workflow submission contract | ✅ Implemented (sync, async, scheduled) |
| Workflow Context integration | ✅ Initial direct integration implemented |
| Operator-facing diagnostic/report surface | 🔄 Planned |

### Next Focus

- align all strategy and product docs around workflow-first AI operational readiness inside Proofhouse
- map current org-level signals into workflow-first readiness pillars
- deepen the Workflow Context-native workflow scoring path beyond the initial direct integration
- refine the Workflow Context-native submission contract as more workflow sources are added
- preserve existing org-level compatibility during the transition

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/TECHNICAL_SPEC.md](docs/TECHNICAL_SPEC.md) | Workflow-first product contract and assessment object |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 90-day roadmap and guardrails |
| [docs/API.md](docs/API.md) | HTTP API reference and compatibility notes |
| [NAMING.md](NAMING.md) | Current product-vs-technical naming rules |
| [CONTRACTS.md](CONTRACTS.md) | Readiness shared-contract ownership and handoff rules |
| [docs/OPERATOR_QUICKSTART.md](docs/OPERATOR_QUICKSTART.md) | Current operator onboarding and compatibility-mode workflow |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Underlying system architecture and platform patterns |
| [docs/STAGING_VALIDATION.md](docs/STAGING_VALIDATION.md) | Staging smoke-test and release-gate checklist |
| [docs/SECURITY.md](docs/SECURITY.md) | Security architecture and control posture |
| [GOVERNANCE.md](GOVERNANCE.md) | Project governance, roles, and decision model |

---

## Use Cases

### In the Proofhouse Platform

- Score whether a Workflow Context workflow is ready for more AI autonomy
- Highlight trust and readiness gaps before Governance rollout
- Feed workflow-level readiness signals from Forge learnings
- Score the regulated document-operations fixture from Workflow Context refs/snapshots while emitting a Readiness-owned `AssessmentRef`

### For Operators

- Run readiness diagnostics for specific AI-enabled workflows
- Review trust-gap and remediation reports
- Use workflow rollups to prioritize where automation should expand next

---

## Author

**Shamim Rehman**  
15+ years scaling technology companies from seed to pre-IPO.

- LinkedIn: [linkedin.com/in/shamimrehman](https://linkedin.com/in/shamimrehman)
- GitHub: [github.com/im-sham](https://github.com/im-sham)

---

## License

MIT License - see [LICENSE](LICENSE) for details.
