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

It helps a COO or operations leader answer a more specific question than generic company scalability:

**Is this workflow ready to scale with AI without creating fragility, trust failures, or governance gaps?**

ScaleScore still uses traditional operations signals such as capacity, dependencies, governance, and vendor concentration. The difference is that those signals are now interpreted through the lens of AI-assisted work, human oversight, and operational trust.

Readiness can also add a separate **Operational Learning suitability** lens for workflow reports. This sibling score evaluates candidate quality for internal eval use and internal training candidacy without changing `workflow_readiness_score`, and it does not replace Governance approval decisions.

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
| **Governance** | Runtime governance, control enforcement, compliance evidence |
| **Forge** | Failure-pattern input and scoring-model refinement |

Readiness is primarily a Proofhouse capability layer, with a secondary standalone diagnostic motion for consulting, design partners, and discovery.

Operational Learning suitability remains a Readiness scoring lens only. Readiness does not become the source of workflow truth, rights profiles, export eligibility, promotion approvals, or asset derivation.

---

## Compatibility Mode

Readiness is transitioning to workflow-first without breaking the current product surface.

- Current org-level CSV assessment flows remain supported.
- Current HTTP API endpoints remain supported.
- Current async, scheduling, persistence, and staging validation flows remain supported.
- Workflow-first readiness is now available as an additive Python/report contract.

Legacy `OpsOrchestra` and `ScaleScore` naming is retained only where required for technical backward compatibility. User-facing narrative should prefer `Proofhouse`, `Workflow Context`, and `Readiness`.
Current repo/package/runtime identifiers also remain `scalescore` until a later rename wave.

---

## Quick Start

```bash
# Clone the current technical repository
git clone https://github.com/im-sham/scalescore.git
# The checkout folder can remain "scalescore" until the repo-root rename wave.
cd scalescore

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"
# Optional for Redis broker worker mode:
# pip install -e ".[dev,worker]"

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
- `workflow_readiness_score`
- `workflow_pillar_scores`
- `top_trust_gaps`
- `prioritized_remediation_actions`
- `operational_learning_suitability`
- `org_rollup`

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
| Standalone COO diagnostic packaging | 🔄 Planned |

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

### For COO Diagnostics

- Run readiness diagnostics for specific AI-enabled workflows
- Deliver trust-gap and remediation reports for design partners
- Use workflow rollups to prioritize where automation should expand next

### For Standalone Discovery

- Offer a focused diagnostic/report product without claiming a broad generic operations platform category

---

## Author

**Shamim Rehman**  
15+ years scaling technology companies from seed to pre-IPO.

- LinkedIn: [linkedin.com/in/shamimrehman](https://linkedin.com/in/shamimrehman)
- GitHub: [github.com/im-sham](https://github.com/im-sham)

---

## License

MIT License - see [LICENSE](LICENSE) for details.
