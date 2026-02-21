from __future__ import annotations

from io import BytesIO
from textwrap import wrap

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from scalescore.models.scaling import ScaleScoreReport


def generate_executive_summary(report: ScaleScoreReport) -> str:
    """Generate a concise narrative summary for executive readers."""
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
        f"{report.org_name or report.org_id} currently demonstrates {readiness} operational readiness "
        f"with an overall score of {report.overall_score:.1f} ({report.overall_grade}). "
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

    title = f"{report.org_name or report.org_id} Readiness Report"
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

    draw_heading("Key Findings")
    draw_bullets(report.key_findings)

    draw_heading("Immediate Actions")
    action_items = report.immediate_actions or [rec.title for rec in report.recommendations[:3]]
    draw_bullets(action_items)

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
