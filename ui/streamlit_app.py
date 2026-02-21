import requests
import streamlit as st

API_BASE_URL = "http://localhost:8000/api/v1"

st.set_page_config(page_title="ScaleScore MVP", layout="wide")


def switch_to_dashboard() -> None:
    st.session_state["view"] = "dashboard"
    st.session_state["selected_area"] = None


def switch_to_area(area: str) -> None:
    st.session_state["view"] = "deep_dive"
    st.session_state["selected_area"] = area


def _constraint_matches_area(constraint: dict, area: str) -> bool:
    entity_type = constraint.get("entity_type", "")
    if area == "facilities" and entity_type == "facility":
        return True
    if area == "operations" and entity_type in ("system", "vendor"):
        return True
    return False


def render_recommendations_panel(report: dict) -> None:
    recommendations = report.get("recommendations", [])
    if not recommendations:
        return

    st.subheader("Top Recommendations")

    for rec in recommendations[:5]:
        effort = rec.get("effort", "medium")
        impact = rec.get("impact", "medium")
        priority = rec.get("priority_score", 0)

        effort_badge = {"low": "🟢 Low", "medium": "🟡 Medium", "high": "🔴 High"}.get(
            effort, effort
        )
        impact_badge = {"low": "🟢 Low", "medium": "🟡 Medium", "high": "🔴 High"}.get(
            impact, impact
        )

        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**{rec.get('title', 'Recommendation')}**")
                st.caption(rec.get("description", ""))
            with col2:
                st.caption(f"Priority: {priority:.2f}")
                st.caption(f"Effort: {effort_badge}")
                st.caption(f"Impact: {impact_badge}")

            if rec.get("estimated_time_days"):
                st.caption(f"Est. time: {rec['estimated_time_days']} days")


def render_top_risks(report: dict) -> None:
    risks = report.get("top_risks", [])
    if not risks:
        return

    st.subheader("Top Risks")

    for risk in risks[:5]:
        level = risk.get("risk_level", "medium")
        level_colors = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
        level_icon = level_colors.get(level, "⚪")
        level_label = level.title()

        with st.container(border=True):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"{level_icon} **{risk.get('title', 'Unknown Risk')}**")
                st.caption(risk.get("description", ""))
                area = risk.get("functional_area", "").replace("_", " ").title()
                st.caption(f"Area: {area}")
            with col2:
                st.metric("Level", level_label)


def render_dashboard(report: dict) -> None:
    st.header("Assessment Results")

    col_score, col_stats = st.columns([1, 2])

    with col_score:
        score = report.get("overall_score", 0)
        grade = report.get("overall_grade", "N/A")
        trend = report.get("overall_trend", "stable")
        trend_icon = {"improving": "↑", "declining": "↓", "stable": "→"}.get(trend, "")
        st.metric(
            label="Overall Readiness Score", value=f"{score:.1f}/100", delta=f"{grade} {trend_icon}"
        )

    with col_stats:
        stat_cols = st.columns(4)
        with stat_cols[0]:
            st.metric("Constraints", report.get("total_constraints", 0))
        with stat_cols[1]:
            st.metric("Total Risks", report.get("total_risks", 0))
        with stat_cols[2]:
            st.metric("Critical Risks", report.get("critical_risks", 0))
        with stat_cols[3]:
            st.metric("Recommendations", report.get("total_recommendations", 0))

    if report.get("key_findings"):
        st.subheader("Key Findings")
        for finding in report["key_findings"]:
            st.warning(finding)

    st.subheader("Functional Area Breakdown")
    st.caption("Click an area to see detailed constraints and risks")

    area_scores = report.get("area_scores", [])
    if area_scores:
        rows = [area_scores[i : i + 4] for i in range(0, len(area_scores), 4)]
        for row in rows:
            cols = st.columns(len(row))
            for col, area in zip(cols, row, strict=True):
                with col:
                    area_name = area["functional_area"].replace("_", " ").title()
                    area_score = area["score"]
                    area_grade = area.get("grade", "")
                    area_trend = area.get("trend", "stable")
                    trend_icon = {"improving": "↑", "declining": "↓", "stable": ""}.get(
                        area_trend, ""
                    )

                    constraint_count = area.get("constraint_count", 0)
                    risk_count = area.get("risk_count", 0)

                    with st.container(border=True):
                        st.metric(
                            label=area_name,
                            value=f"{area_score:.1f}",
                            delta=f"{area_grade} {trend_icon}",
                        )
                        st.caption(f"{constraint_count} constraints, {risk_count} risks")
                        if st.button("Details", key=f"btn_{area['functional_area']}"):
                            switch_to_area(area["functional_area"])
                            st.rerun()
    else:
        st.info("No functional area scores available.")

    render_recommendations_panel(report)
    render_top_risks(report)

    with st.expander("View Raw JSON Response"):
        st.json(report)


def render_deep_dive(report: dict, selected_area: str) -> None:
    if st.button("← Back to Dashboard"):
        switch_to_dashboard()
        st.rerun()

    area_name = selected_area.replace("_", " ").title()
    st.header(f"Deep Dive: {area_name}")

    area_scores = report.get("area_scores", [])
    area_data = next((a for a in area_scores if a["functional_area"] == selected_area), None)

    if area_data:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Score", f"{area_data['score']:.1f}/100")
        with col2:
            st.metric("Grade", area_data.get("grade", "N/A"))
        with col3:
            trend = area_data.get("trend", "stable")
            trend_display = {
                "improving": "↑ Improving",
                "declining": "↓ Declining",
                "stable": "→ Stable",
            }.get(trend, trend)
            st.metric("Trend", trend_display)

        if area_data.get("sub_scores"):
            st.subheader("Score Breakdown")
            sub_scores = area_data["sub_scores"]
            breakdown_cols = st.columns(len(sub_scores))
            for col, (key, value) in zip(breakdown_cols, sub_scores.items(), strict=False):
                with col:
                    label = key.replace("_", " ").title()
                    st.metric(label, f"{value:.2f}")

    st.subheader("Constraints")
    constraints = report.get("constraints", [])
    area_constraints = [c for c in constraints if _constraint_matches_area(c, selected_area)]

    if area_constraints:
        for constraint in area_constraints:
            with st.container(border=True):
                util = constraint.get("current_utilization", 0)
                prob = constraint.get("breach_probability", 0)

                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(
                        f"**{constraint.get('entity_name', constraint.get('entity_id', 'Unknown'))}**"
                    )
                    st.caption(constraint.get("title", "") or constraint.get("description", ""))
                with col2:
                    st.metric("Utilization", f"{util:.0%}")
                    st.caption(f"Breach prob: {prob:.0%}")

                if constraint.get("mitigation_options"):
                    with st.expander("Mitigation Options"):
                        for option in constraint["mitigation_options"]:
                            st.markdown(f"• {option}")
    else:
        st.info("No constraints identified for this area.")

    st.subheader("Risks")
    risks = report.get("top_risks", [])
    area_risks = [r for r in risks if r.get("functional_area") == selected_area]

    if area_risks:
        for risk in area_risks:
            level = risk.get("risk_level", "medium")
            level_colors = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
            level_icon = level_colors.get(level, "⚪")

            with st.container(border=True):
                st.markdown(f"{level_icon} **{risk.get('title', 'Unknown Risk')}**")
                st.caption(risk.get("description", ""))

                col1, col2 = st.columns(2)
                with col1:
                    st.caption(f"Probability: {risk.get('probability', 0):.0%}")
                with col2:
                    st.caption(f"Impact: {risk.get('impact_score', 0):.0%}")

                if risk.get("recommendations"):
                    with st.expander("Recommendations"):
                        for rec in risk["recommendations"]:
                            st.markdown(f"• {rec}")
    else:
        st.info("No risks identified for this area.")


if "view" not in st.session_state:
    st.session_state["view"] = "dashboard"
if "selected_area" not in st.session_state:
    st.session_state["selected_area"] = None

st.title("ScaleScore MVP")
st.markdown("Upload your organization's data to generate an operational readiness assessment.")

st.subheader("Data Upload")

use_demo = st.button("Use Demo Dataset", type="secondary")

col1, col2 = st.columns(2)

with col1:
    org_file = st.file_uploader("Organizations (organizations.csv)", type=["csv"])
    team_file = st.file_uploader("Teams (teams.csv)", type=["csv"])
    sys_file = st.file_uploader("Systems (systems.csv)", type=["csv"])

with col2:
    vend_file = st.file_uploader("Vendors (vendors.csv)", type=["csv"])
    fac_file = st.file_uploader("Facilities (facilities.csv)", type=["csv"])
    growth_file = st.file_uploader("Growth Signals (growth_signals.csv)", type=["csv"])

run_assessment = st.button("Run Assessment", type="primary")

uploads = {
    "organizations": org_file,
    "teams": team_file,
    "systems": sys_file,
    "vendors": vend_file,
    "facilities": fac_file,
    "growth_signals": growth_file,
}

if use_demo:
    demo_path = "data"
    try:
        response = requests.post(
            f"{API_BASE_URL}/assessments",
            params={"dataset_path": demo_path},
            timeout=30,
        )
    except requests.exceptions.ConnectionError:
        st.error(
            "Could not connect to the API. Is the backend server running at http://localhost:8000?"
        )
    except requests.exceptions.RequestException as exc:
        st.error(f"API request failed: {exc}")
    else:
        if response.status_code != 200:
            st.error(f"API Error ({response.status_code}): {response.text}")
        else:
            report = response.json()
            st.session_state["report"] = report
            st.session_state["view"] = "dashboard"

if run_assessment:
    missing = [name for name, value in uploads.items() if value is None]

    if missing:
        st.error("Please upload all six CSV files to proceed.")
    else:
        files = {
            name: (f"{name}.csv", upload.getvalue(), "text/csv")
            for name, upload in uploads.items()
            if upload is not None
        }

        try:
            with st.spinner("Analyzing data..."):
                response = requests.post(
                    f"{API_BASE_URL}/assessments/upload", files=files, timeout=30
                )

            if response.status_code == 200:
                report = response.json()
                st.session_state["report"] = report
                st.session_state["view"] = "dashboard"
            else:
                st.error(f"API Error ({response.status_code}): {response.text}")

        except requests.exceptions.ConnectionError:
            st.error(
                "Could not connect to the API. Is the backend server running at http://localhost:8000?"
            )
        except requests.exceptions.RequestException as exc:
            st.error(f"API request failed: {exc}")
        except Exception as exc:
            st.error(f"An unexpected error occurred: {str(exc)}")

report = st.session_state.get("report")

if report:
    st.divider()

    if st.session_state["view"] == "dashboard":
        render_dashboard(report)
    elif st.session_state["view"] == "deep_dive":
        render_deep_dive(report, st.session_state["selected_area"])
