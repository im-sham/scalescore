from __future__ import annotations

from io import BytesIO
from textwrap import wrap

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from scalescore.models.scaling import ClaimsSuitabilitySummary, ScaleScoreReport


def generate_executive_summary(report: ScaleScoreReport) -> str:
    """Generate a concise narrative summary for executive readers."""
    if report.workflow_context is not None:
        workflow = report.workflow_context
        workflow_score = (
            report.workflow_readiness_score
            if report.workflow_readiness_score is not None
            else report.overall_score
        )
        workflow_grade = report.workflow_readiness_grade or report.overall_grade
        readiness = "strong"
        if workflow_score < 85:
            readiness = "moderate"
        if workflow_score < 70:
            readiness = "fragile"

        top_gap = (
            report.top_trust_gaps[0]
            if report.top_trust_gaps
            else "Trust gaps have not yet been prioritized for this workflow."
        )
        top_action = (
            report.prioritized_remediation_actions[0]
            if report.prioritized_remediation_actions
            else (
                report.immediate_actions[0]
                if report.immediate_actions
                else "Prioritize remediation for the highest-impact workflow gap."
            )
        )
        rollup_phrase = (
            report.org_rollup.note
            if report.org_rollup is not None and report.org_rollup.note
            else "Use this workflow score as one input into the organization-level rollup."
        )
        operational_learning_phrase = ""
        if report.operational_learning_suitability is not None:
            operational_learning = report.operational_learning_suitability
            operational_learning_phrase = (
                " Operational Learning suitability is "
                f"{operational_learning.status.value.replace('_', ' ')} "
                f"(eval suitability score {operational_learning.eval_suitability.score:.1f}, "
                "training suitability score "
                f"{operational_learning.internal_training_candidacy.score:.1f}). "
                "This is not training approval; Governance approval is required before "
                "any internal training use. "
                f"{operational_learning.governance_dependency_state.summary}"
            )
        claims_phrase = ""
        if report.claims_suitability is not None:
            claims = report.claims_suitability
            claims_phrase = (
                " Claims suitability is "
                f"{claims.status.value.replace('_', ' ')} "
                f"for {claims.profile_id} with score {claims.score:.1f}; "
                f"Governance dependency is {claims.governance_dependency_state}."
            )

        return (
            f"{workflow.name} currently shows {readiness} AI operational readiness with a workflow score "
            f"of {workflow_score:.1f} ({workflow_grade}) for {report.org_name or report.org_id}. "
            f"The workflow is owned by {workflow.owner} and scoped to {workflow.business_function} with the "
            f"AI role defined as {workflow.ai_role}. Top trust gap: {top_gap}. "
            f"Recommended immediate action: {top_action}. {rollup_phrase}"
            f"{operational_learning_phrase}"
            f"{claims_phrase}"
        )

    score = report.overall_score
    readiness = "strong"
    if score < 85:
        readiness = "moderate"
    if score < 70:
        readiness = "fragile"

    trend_phrase = {
        "improving": "Readiness is improving relative to recent assessments.",
        "declining": "Readiness is declining and should be stabilized quickly.",
        "stable": "Readiness is currently stable.",
    }.get(report.overall_trend, "Readiness trend is currently stable.")

    risk_phrase = (
        f"The assessment identified {report.total_risks} risks, including "
        f"{report.critical_risks} critical and {report.high_risks} high-priority items."
    )
    constraints_phrase = (
        f"A total of {report.total_constraints} constraints were detected across "
        f"{len(report.area_scores)} functional areas."
    )

    top_finding = report.key_findings[0] if report.key_findings else "No major findings were recorded."
    top_action = (
        report.immediate_actions[0]
        if report.immediate_actions
        else "Prioritize mitigation for the highest-impact risk cluster."
    )

    return (
        f"{report.org_name or report.org_id} currently demonstrates {readiness} AI-enabled operational "
        f"readiness with an overall score of {report.overall_score:.1f} ({report.overall_grade}). "
        f"{trend_phrase} {constraints_phrase} {risk_phrase} "
        f"Top finding: {top_finding}. Recommended immediate action: {top_action}."
    )


def render_report_pdf(report: ScaleScoreReport) -> bytes:
    """Render a polished, single-report PDF document."""
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=LETTER)
    page_width, page_height = LETTER
    margin = 54
    line_height = 14
    bottom_margin = 52
    page_number = 1

    def draw_frame() -> float:
        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(margin, page_height - 32, "ScaleScore Assessment Report")
        pdf.setFont("Helvetica", 9)
        pdf.drawRightString(
            page_width - margin,
            page_height - 32,
            report.generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        )
        pdf.drawRightString(page_width - margin, 30, f"Page {page_number}")
        return page_height - 68

    y = draw_frame()

    def new_page() -> None:
        nonlocal y, page_number
        pdf.showPage()
        page_number += 1
        y = draw_frame()

    def ensure_space(lines: int = 1, spacing: int = line_height) -> None:
        nonlocal y
        if y - (lines * spacing) < bottom_margin:
            new_page()

    def draw_heading(text: str) -> None:
        nonlocal y
        ensure_space(lines=2, spacing=18)
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(margin, y, text)
        y -= 20

    def draw_text(text: str, *, font: str = "Helvetica", size: int = 11, width: int = 95) -> None:
        nonlocal y
        lines = wrap(text, width=width) or [text]
        for line in lines:
            ensure_space()
            pdf.setFont(font, size)
            pdf.drawString(margin, y, line)
            y -= line_height
        y -= 2

    def draw_bullets(items: list[str], *, width: int = 92) -> None:
        nonlocal y
        if not items:
            draw_text("- None")
            return
        for item in items:
            lines = wrap(item, width=width) or [item]
            for idx, line in enumerate(lines):
                ensure_space()
                prefix = "- " if idx == 0 else "  "
                pdf.setFont("Helvetica", 11)
                pdf.drawString(margin, y, f"{prefix}{line}")
                y -= line_height
            y -= 1

    title = (
        f"{report.workflow_context.name} Workflow Readiness Report"
        if report.workflow_context is not None
        else f"{report.org_name or report.org_id} Readiness Report"
    )
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(margin, y, title)
    y -= 26
    pdf.setFont("Helvetica", 11)
    pdf.drawString(margin, y, f"Report ID: {report.report_id}")
    y -= 18

    draw_heading("Executive Summary")
    draw_text(report.executive_summary or generate_executive_summary(report))

    draw_heading("Score Snapshot")
    draw_text(f"Overall score: {report.overall_score:.1f} ({report.overall_grade})")
    draw_text(f"Overall trend: {report.overall_trend}")
    draw_text(
        "Risk counts: "
        f"total={report.total_risks}, critical={report.critical_risks}, high={report.high_risks}"
    )
    draw_text(f"Constraint count: {report.total_constraints}")

    if report.workflow_context is not None:
        workflow = report.workflow_context
        draw_heading("Workflow Readiness Profile")
        draw_text(
            f"Workflow score: {(report.workflow_readiness_score or report.overall_score):.1f} "
            f"({report.workflow_readiness_grade or report.overall_grade})"
        )
        draw_text(f"Business function: {workflow.business_function}")
        draw_text(f"AI role: {workflow.ai_role}")
        draw_text(f"Owner: {workflow.owner}")
        draw_text(f"Blast radius: {workflow.blast_radius.value}")
        draw_text(
            "Systems touched: "
            + (", ".join(workflow.systems_touched) if workflow.systems_touched else "Not documented")
        )
        draw_text(
            "Escalation path: "
            + (
                " -> ".join(workflow.human_escalation_path)
                if workflow.human_escalation_path
                else "Not documented"
            )
        )

        draw_heading("Workflow Readiness Pillars")
        if report.workflow_pillar_scores:
            for pillar in report.workflow_pillar_scores:
                draw_text(
                    f"{pillar.pillar.value}: {pillar.score:.1f} ({pillar.grade}) | {pillar.rationale}"
                )
        else:
            draw_text("No workflow pillar scores recorded.")

        draw_heading("Top Trust Gaps")
        draw_bullets(report.top_trust_gaps)

        if report.operational_learning_suitability is not None:
            operational_learning = report.operational_learning_suitability
            draw_heading("Operational Learning Suitability")
            draw_text(
                "Status: "
                f"{operational_learning.status.value} | "
                f"Eval suitability score: {operational_learning.eval_suitability.score:.1f} | "
                "Training suitability score: "
                f"{operational_learning.internal_training_candidacy.score:.1f}"
            )
            draw_text(
                "This is not training approval; Governance approval is required before "
                "any internal training use."
            )
            draw_text(operational_learning.governance_dependency_state.summary)
            if operational_learning.top_blockers:
                draw_text("Top blockers:")
                draw_bullets(operational_learning.top_blockers[:3])
            else:
                draw_text("Top reasons:")
                draw_bullets(operational_learning.top_reasons[:3])
            draw_text("Recommended next actions:")
            draw_bullets(operational_learning.recommended_next_actions[:3])

        if report.claims_suitability is not None:
            draw_heading("Claims Suitability")
            for line in _claims_suitability_lines(report.claims_suitability):
                draw_text(line)
            if report.claims_suitability.top_blockers:
                draw_text("Top blockers:")
                draw_bullets(report.claims_suitability.top_blockers[:5])
            if report.claims_suitability.top_reasons:
                draw_text("Top reasons:")
                draw_bullets(report.claims_suitability.top_reasons[:5])
            draw_text("Recommended next actions:")
            draw_bullets(report.claims_suitability.recommended_next_actions[:5])

    draw_heading("Key Findings")
    draw_bullets(report.key_findings)

    draw_heading("Immediate Actions")
    action_items = (
        report.prioritized_remediation_actions
        or report.immediate_actions
        or [rec.title for rec in report.recommendations[:3]]
    )
    draw_bullets(action_items)

    if report.org_rollup is not None:
        draw_heading("Organization Rollup")
        draw_text(
            f"Workflow count: {report.org_rollup.workflow_count} | "
            f"Average workflow score: {report.org_rollup.average_workflow_score:.1f} "
            f"({report.org_rollup.overall_grade})"
        )
        draw_text(report.org_rollup.note or "No rollup note recorded.")

    draw_heading("Top Risks")
    if report.top_risks:
        for risk in report.top_risks[:8]:
            draw_text(
                f"{risk.title} | level={risk.risk_level.value} | "
                f"score={risk.risk_score:.2f} | area={risk.functional_area.value}"
            )
    else:
        draw_text("No top risks recorded.")

    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()


def _claims_suitability_lines(claims: ClaimsSuitabilitySummary) -> list[str]:
    return [
        f"Profile ID: {claims.profile_id}",
        f"Status: {claims.status.value} | Score: {claims.score:.1f}",
        f"Governance dependency: {claims.governance_dependency_state}",
        f"Evidence gap: {claims.evidence_gap_state}",
        f"PHI/redaction: {claims.phi_redaction_state}",
        f"Rate-source traceability: {claims.rate_source_traceability_state}",
        f"Downstream consistency: {claims.downstream_consistency_state}",
        f"Savings lifecycle: {claims.savings_lifecycle_state}",
    ]
