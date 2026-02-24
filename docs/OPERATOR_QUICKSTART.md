# ScaleScore Operator Quickstart

> **Audience:** Operations-focused users with limited coding experience  
> **Goal:** Generate your first useful readiness assessment in about 15 minutes

---

## What You Will Get

At the end of this flow, you will have:
- An overall readiness score (0-100).
- A breakdown by functional area.
- Top risks to address first.
- Recommended mitigation actions.

---

## Before You Start

You need:
- A running ScaleScore API and dashboard from your team (or from your own local setup).
- Six CSV files:
  - `organizations.csv`
  - `teams.csv`
  - `systems.csv`
  - `vendors.csv`
  - `facilities.csv`
  - `growth_signals.csv`

If you are starting from scratch, copy the examples in `/data` and replace sample values with your own.

---

## 15-Minute Workflow

1. Open the dashboard  
   Ask your technical owner for the dashboard URL (typically a local Streamlit app).

2. Prepare your CSV files  
   Use the sample headers from `/data/*.csv`. Keep IDs stable across files (for example, use the same `org_id` consistently).

3. Upload all six files  
   In the dashboard, upload each CSV in its matching input.

4. Run the assessment  
   Select **Run Assessment** and wait for the report.

5. Capture decisions immediately  
   Record:
   - Top 3 risks
   - Top 3 recommended actions
   - Owner and due date for each action

---

## How to Read the Output

## Overall Score

- `80-100`: Strong readiness with manageable gaps.
- `60-79`: Moderate risk; targeted mitigation needed.
- `<60`: High operational fragility; immediate action advised.

## Functional Area Scores

Use area-level scores to prioritize where mitigation starts:
- Lowest score first.
- Highest risk concentration second.
- Fastest high-impact remediation third.

## Recommendations

Prioritize recommendations with:
- High impact
- Low/medium effort
- Short estimated implementation time

---

## Weekly Operating Rhythm

1. Refresh source CSVs weekly.
2. Re-run assessment.
3. Compare score trend and risk count.
4. Track whether prior recommendations were completed.
5. Escalate any new critical risk in your weekly ops review.

---

## Troubleshooting

## "I got an upload error"

- Confirm all six CSV files are present.
- Confirm column headers match the sample files exactly.
- Confirm date and numeric fields are valid.

## "The score looks wrong"

- Check whether IDs are aligned across files (`org_id`, entity IDs, dependencies).
- Verify `growth_signals.csv` reflects current plan assumptions.
- Re-run with the demo dataset to confirm system behavior.

## "I cannot access the API/dashboard"

- Contact your technical owner to verify the API is running and authentication is configured.

---

## Handoff to Technical Team

Use this minimal handoff request:

> "Please validate my six CSV files against ScaleScore schema, run the same dataset through API, and confirm whether any parsing or auth errors are occurring."

---

## Next Step

After your first successful run, move to:
- `docs/adr/0017-open-source-auth-provider-strategy.md` for auth deployment policy (OSS default and optional managed SSO path).
- `README.md` for technical integration options.
