# ScaleScore

[![CI](https://github.com/im-sham/scalescore/actions/workflows/ci.yml/badge.svg)](https://github.com/im-sham/scalescore/actions/workflows/ci.yml)

**Operational Readiness Prediction System**

> Know where you'll break before you break.

---

## What is ScaleScore?

ScaleScore predicts where your organization will hit scaling bottlenecks before they happen. It combines organizational data with heuristic models derived from 15+ years of scaling experience to produce actionable readiness scores and recommendations.

ScaleScore is open source and can run standalone. It is also designed to integrate with OpsOrchestra/Mila as an orchestration layer for execution.

### The Problem

High-growth companies consistently encounter the same failure modes:
- Hiring plans that outpace facility capacity
- Systems that don't scale with transaction volume  
- Vendor dependencies that become single points of failure
- Governance structures that lag organizational complexity

These failures are **predictable but rarely predicted**. Leaders react to fires instead of preventing them.

### The Solution

ScaleScore ingests your organizational data and produces:

1. **Readiness Scores** (0-100) by functional area
2. **Bottleneck Predictions** with timeline estimates
3. **Risk Heat Maps** visualizing constraint interdependencies
4. **Actionable Recommendations** with effort/impact scoring

---

## Quick Start

```bash
# Clone the repository
git clone https://github.com/im-sham/scalescore.git
cd scalescore

# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -e ".[dev]"

# Use development defaults (AUTH_SKIP_AUTH=true for local UI/API flow)
cp .env.example .env

# Run a CLI assessment on demo data
scalescore --dataset-path data

# Start the API server
uvicorn scalescore.api.main:app --reload

# Launch the dashboard
streamlit run ui/streamlit_app.py
```

---

## Choose Your Path

### Technical Teams

- Start with this README and [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md).
- Use the API and CLI for integration workflows.
- Follow [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and ADRs for extension decisions.

### Operational Teams

- Start with [docs/OPERATOR_QUICKSTART.md](docs/OPERATOR_QUICKSTART.md) to run an assessment in about 15 minutes.
- Use the sample CSV structures in [`data/`](data/).
- Focus on "top risks" and "top recommendations" outputs to drive weekly operating reviews.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        ScaleScore                            │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  Connectors  │  │    Core      │  │       API        │   │
│  │              │  │   Engine     │  │                  │   │
│  │ • CSV Import │──│ • Scoring    │──│ • FastAPI REST   │   │
│  │ • HRIS       │  │ • Prediction │  │ • WebSocket      │   │
│  │ • OpsOrch*   │  │ • Recommend  │  │                  │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
└─────────────────────────────────────────────────────────────┘

* OpsOrchestra connector enables bidirectional data sharing
```

---

## OpsOrchestra / Mila Integration

ScaleScore is designed to operate **standalone OR as an OpsOrchestra module**.

| Mode | Data Source | Auth | Storage |
|------|-------------|------|---------|
| **Standalone** | CSV, direct API | Own JWT | SQLite/Postgres |
| **Integrated** | OpsOrchestra knowledge graph | Tenant context | Shared DB |

When integrated, ScaleScore becomes the "strategic layer" for OpsOrchestra/Mila:
- **Layer 1 (OpsOrchestra):** What does the org know?
- **Layer 2 (OpsOrchestra):** How does the org work?
- **Layer 3 (ScaleScore):** Where will the org break?

---

## Key Concepts

### Entities
- **Organization** — Top-level entity with headcount/revenue plans
- **Team** — Departments with their own capacity constraints
- **System** — Software tools with capacity limits and dependencies
- **Vendor** — External dependencies with contract timelines
- **Facility** — Physical locations with seat capacity

### Scoring
- **Growth Signals** — Planned changes that drive capacity needs
- **Capacity Constraints** — Limits that could block scaling
- **Risk Indicators** — Specific risks with probability and impact
- **Readiness Scores** — 0-100 measure of preparedness

---

## Project Structure

```
scalescore/
├── src/scalescore/
│   ├── models/          # Pydantic data models
│   │   ├── core.py      # Entity models (compatible with OpsOrchestra)
│   │   └── scaling.py   # Scoring and risk models
│   ├── core/            # Core business logic
│   ├── scoring/         # Scoring algorithms
│   ├── connectors/      # Data import connectors
│   └── api/             # FastAPI endpoints
├── tests/               # Test suite
├── ui/                  # Streamlit dashboard
├── docs/                # Documentation (see below)
├── data/                # Demo dataset
└── pyproject.toml
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/TECHNICAL_SPEC.md](docs/TECHNICAL_SPEC.md) | Product specifications and requirements |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System design, principles, and patterns |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Implementation roadmap with milestones |
| [docs/SECURITY.md](docs/SECURITY.md) | Security architecture and SOC2 alignment |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | Development standards and practices |
| [docs/OPERATOR_QUICKSTART.md](docs/OPERATOR_QUICKSTART.md) | Non-technical onboarding and 15-minute assessment flow |
| [GOVERNANCE.md](GOVERNANCE.md) | Project governance, roles, and decision model |
| [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) | Community behavior expectations and enforcement |
| [docs/adr/](docs/adr/) | Architecture Decision Records |

---

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md) for the complete implementation plan.

### Current Status: Phase 2 Platform Maturity

| Component | Status |
|-----------|--------|
| Core models | ✅ Complete |
| Scoring engine | ✅ Complete |
| Bottleneck detection | ✅ Complete |
| Recommendation engine | ✅ Complete |
| CSV import | ✅ Complete |
| FastAPI endpoints | ✅ Expanded (assessments + auth + org/entity CRUD + trend history) |
| Auth foundation | ✅ Implemented (JWT + refresh + RBAC guards + user/API key persistence) |
| Streamlit dashboard | ✅ Complete |
| Assessment persistence | ✅ Implemented (SQLite snapshots + retrieval endpoint) |
| Security scanning | ✅ Implemented (dependency audit in CI) |

### Next Focus: Phase 3 Scale & Integration

- OpsOrchestra connector implementation and bidirectional sync
- Async/background assessment execution for larger datasets
- Expanded scoring pillars (financial/people/customer)
- API/SDK documentation and production runbooks

---

## Use Cases

### For Job Interviews
Walk through a demo assessment: "Here's how I'd evaluate your operational readiness for the growth you're planning..."

### For Consulting
Run assessments for clients and deliver actionable reports with prioritized recommendations.

### For Product (Future)
SaaS offering for scale-up companies to continuously monitor their operational readiness.

---

## Author

**Shamim Rehman**  
15+ years scaling technology companies from seed to pre-IPO.

- LinkedIn: [linkedin.com/in/shamimrehman](https://linkedin.com/in/shamimrehman)
- GitHub: [github.com/im-sham](https://github.com/im-sham)

---

## License

MIT License - see [LICENSE](LICENSE) for details.
