# ADR-0003: Constraint-Based Scoring Algorithm

**Status**: Accepted  
**Date**: 2026-01-15  
**Author**: Shamim Rehman  
**Reviewers**: -

## Context

ScaleScore's core value is predicting where organizations will hit scaling bottlenecks. We need a scoring algorithm that:

- Produces actionable 0-100 scores by functional area
- Incorporates capacity constraints, risks, and growth plans
- Is explainable (users understand why they got a score)
- Is calibratable (weights can be tuned based on real-world validation)
- Scales computationally with entity count

## Decision Drivers

- **Explainability**: Users must understand score drivers
- **Calibratability**: Algorithm must be tunable without code changes
- **Simplicity**: Avoid over-engineering before validation
- **Extensibility**: Add new constraint types without redesign
- **Performance**: Score 1000+ entities in < 5 seconds

## Considered Options

### Option 1: Constraint-Based Penalty Model

Start with perfect score (100), subtract penalties for constraints and risks.

```
score = base_score - Σ(constraint_penalties) - Σ(risk_penalties)
```

**Pros:**
- Intuitive: "Here's what's reducing your score"
- Explainable: Can list each penalty contribution
- Configurable: Weights in config, not code
- Simple: Easy to implement and validate

**Cons:**
- May need calibration to avoid score clustering
- Additive model may not capture interactions

### Option 2: ML-Based Prediction

Train a model on historical scaling outcomes.

**Pros:**
- Could capture complex patterns
- Potentially more accurate with good data

**Cons:**
- Requires labeled training data (we don't have)
- Black box (hard to explain)
- Harder to calibrate
- Overkill for MVP

### Option 3: Rule-Based Expert System

Codified rules from scaling expertise.

**Pros:**
- Captures domain knowledge
- Fully explainable

**Cons:**
- Brittle: rules need constant updating
- Hard to maintain as complexity grows
- Doesn't handle novel scenarios

### Option 4: Weighted Factor Model

Assign weights to various factors, sum to produce score.

**Pros:**
- Common approach in assessments
- Easy to understand

**Cons:**
- Less intuitive than penalty model
- Harder to explain "why" specific score

## Decision

**Use Constraint-Based Penalty Model** for scoring.

Formula:
```python
area_score = base_score - (constraint_penalty + risk_penalty) * growth_multiplier

where:
  constraint_penalty = Σ(severity × breach_probability × time_proximity)
  risk_penalty = Σ(impact_score × probability × severity_multiplier)
  growth_multiplier = 1.0 + (avg_growth_magnitude / 200)  # 1.0 to 2.0
```

Rationale:
1. Most intuitive model for target users (ops leaders)
2. Directly explainable: "Your score is X because of Y constraints"
3. Configurable weights enable calibration without code changes
4. Simple enough to validate quickly, extensible for future ML

## Consequences

### Positive
- Users understand score derivation
- Can show penalty breakdown in UI
- Easy to add new constraint types
- Configuration-driven weight tuning

### Negative
- May not capture complex interactions (acceptable for MVP)
- Needs calibration to avoid all scores clustering in same range
- Linear model assumptions may not hold

### Neutral
- Opens path to ML enhancement later (penalties as features)

## Implementation Notes

```python
@dataclass(frozen=True)
class ScoringConfig:
    base_score: float = 100.0
    growth_multiplier_cap: float = 2.0
    constraint_severity: dict[ConstraintType, float] = field(
        default_factory=lambda: {
            ConstraintType.CAPACITY: 15.0,
            ConstraintType.DEPENDENCY: 12.0,
            ConstraintType.GOVERNANCE: 8.0,
            ConstraintType.FINANCIAL: 20.0,
            ConstraintType.TALENT: 10.0,
            ConstraintType.TIMELINE: 5.0,
        }
    )
    risk_multipliers: dict[RiskLevel, float] = field(
        default_factory=lambda: {
            RiskLevel.LOW: 0.5,
            RiskLevel.MEDIUM: 1.0,
            RiskLevel.HIGH: 1.5,
            RiskLevel.CRITICAL: 2.5,
        }
    )
```

### Explainability Output

```python
ReadinessScore(
    score=72.5,
    sub_scores={
        "constraint_penalty": 15.3,
        "risk_penalty": 8.2,
        "growth_multiplier": 1.5,
    },
    constraints=["cap_sys_billing", "cap_fac_hq"],
    risks=["concentration_sys_data"],
)
```

## Calibration Strategy

1. Run algorithm on known outcomes (historical scaling failures)
2. Adjust weights until algorithm would have predicted issues
3. Validate on holdout set
4. Establish score ranges: 90+ (green), 70-89 (yellow), <70 (red)

## Related Decisions

- ADR-0001: Pydantic for model definitions

## Notes

- Future enhancement: ML model trained on penalty features
- Consider: Industry-specific weight profiles
