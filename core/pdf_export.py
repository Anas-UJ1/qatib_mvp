"""
PDF export for a ComplianceAuditReport.

Library choice: fpdf2 + arabic-reshaper + python-bidi. All three are pure
Python / pip-installable with no native system dependencies -- this
matters on Windows, where WeasyPrint (needs GTK) and wkhtmltopdf (external
binary) are painful to install during a hackathon.

Neither fpdf2 nor reportlab shape Arabic automatically: plain Unicode
Arabic text is stored in logical order using unjoined letterforms, but PDF
text layout is strict left-to-right stream order. arabic_reshaper joins
letters into their correct isolated/initial/medial/final presentation
forms; python-bidi's get_display() then reorders the shaped string into
visual (LTR-storage) order so it renders correctly on the page. Every
Arabic string must go through _shape() right before being written.
"""

import os
import re
from typing import Optional

import arabic_reshaper
from bidi.algorithm import get_display
from fpdf import FPDF

from core.schemas import ComplianceAuditReport, DueDiligenceLevel, KYCRiskProfile, RiskSeverity

_FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "app", "assets", "fonts")
_FONT_REGULAR = os.path.join(_FONT_DIR, "IBMPlexSansArabic-Regular.ttf")
_FONT_BOLD = os.path.join(_FONT_DIR, "IBMPlexSansArabic-Bold.ttf")

_SEVERITY_COLORS = {
    RiskSeverity.HIGH: (211, 47, 47),
    RiskSeverity.MEDIUM: (245, 124, 0),
    RiskSeverity.LOW: (56, 142, 60),
}

_DILIGENCE_COLORS = {
    DueDiligenceLevel.ENHANCED: (211, 47, 47),
    DueDiligenceLevel.STANDARD: (245, 124, 0),
    DueDiligenceLevel.SIMPLIFIED: (56, 142, 60),
}


def _shape(text: str) -> str:
    if not text:
        return ""
    return get_display(arabic_reshaper.reshape(text))


class _AuditReportPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.add_font("PlexArabic", "", _FONT_REGULAR)
        self.add_font("PlexArabic", "B", _FONT_BOLD)
        self.set_auto_page_break(auto=True, margin=15)


def _make_line_writer(pdf: FPDF, rtl: bool):
    """Returns a line(text, size, bold, color) closure bound to pdf/rtl,
    shared by all PDF builders below so the RTL cursor-reset fix and
    Arabic shaping only need to live in one place."""
    align = "R" if rtl else "L"

    def line(text: str, size: int = 11, bold: bool = False, color=(0, 0, 0)) -> None:
        pdf.set_font("PlexArabic", "B" if bold else "", size)
        pdf.set_text_color(*color)
        # multi_cell(align="R") leaves the cursor at the right margin
        # instead of resetting to the left margin -- without this, the
        # next call sees ~0 available width and raises FPDFException.
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 7, _shape(text) if rtl else text, align=align)

    return line


def build_audit_report_pdf(
    report: ComplianceAuditReport,
    source_filename: Optional[str] = None,
    generated_at: str = "",
) -> bytes:
    pdf = _AuditReportPDF()
    pdf.add_page()
    rtl = report.language == "ar"
    line = _make_line_writer(pdf, rtl)

    line(
        "تقرير تدقيق الامتثال التنظيمي" if rtl else "Regulatory Compliance Audit Report",
        size=18, bold=True,
    )
    meta = generated_at + (f" | {source_filename}" if source_filename else "")
    if meta.strip():
        line(meta, size=10)
    pdf.ln(2)

    score_line = (
        f"مستوى المخاطر الإجمالي: {report.overall_risk_score}/100 ({report.overall_severity.value})" if rtl
        else f"Overall Risk Score: {report.overall_risk_score}/100 ({report.overall_severity.value})"
    )
    line(score_line, size=14, bold=True, color=_SEVERITY_COLORS[report.overall_severity])
    line(report.summary, size=11)
    pdf.ln(4)

    for idx, flag in enumerate(report.flags, start=1):
        line(f"{idx}. [{flag.severity.value}] {flag.category}", size=12, bold=True, color=_SEVERITY_COLORS[flag.severity])
        line(flag.description, size=10)
        if flag.regulation_source:
            ref = flag.regulation_reference or ""
            reg_line = (
                f"المرجع التنظيمي: {flag.regulation_source} ({ref})" if rtl
                else f"Regulatory reference: {flag.regulation_source} ({ref})"
            )
            line(reg_line, size=10)
        if flag.contract_reference:
            doc_line = (
                f"موقع الإشارة في الوثيقة: {flag.contract_reference}" if rtl
                else f"Document location: {flag.contract_reference}"
            )
            line(doc_line, size=10)
        if flag.recommendation:
            rec_line = f"التوصية: {flag.recommendation}" if rtl else f"Recommendation: {flag.recommendation}"
            line(rec_line, size=10)
        pdf.ln(3)

    if not report.flags:
        line("لا توجد مخالفات مسجلة." if rtl else "No flags recorded.", size=10)

    return bytes(pdf.output())


_HEADER_RE = re.compile(r"^(#{1,3})\s+(.*)$")
_BULLET_RE = re.compile(r"^[\*\-]\s+(.*)$")
_BOLD_MARKER_RE = re.compile(r"\*\*(.*?)\*\*")

_MARKDOWN_HEADER_SIZES = {1: 16, 2: 14, 3: 12}


def _strip_inline_markup(text: str) -> str:
    """Strips markdown bold markers rather than rendering them. Inline
    bold mid-line would need multiple set_font calls per line, which
    breaks Arabic shaping (the FULL logical line must be reshaped as one
    unit, not fragment-by-fragment) -- not worth it for a free-form
    report where section headers already carry the visual hierarchy."""
    return _BOLD_MARKER_RE.sub(r"\1", text)


def build_markdown_report_pdf(markdown_text: str, language: str) -> bytes:
    """Renders a free-form markdown compliance report (STR/CTR/SDAIA
    breach notification -- anything produced by core/report_generator.py,
    which has no structured Pydantic schema) to PDF via a lightweight
    line-by-line markdown pass: headers, bullets, a drawn rule for '---',
    bold-marker stripping. Not a full markdown renderer, but the
    templates in report_generator.py only use this small subset."""
    pdf = _AuditReportPDF()
    pdf.add_page()
    rtl = language == "ar"
    line = _make_line_writer(pdf, rtl)

    for raw_line in markdown_text.splitlines():
        text = raw_line.strip()
        if not text:
            continue
        if text == "---":
            pdf.ln(1)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.w - pdf.r_margin, y)
            pdf.ln(3)
            continue

        header_match = _HEADER_RE.match(text)
        bullet_match = _BULLET_RE.match(text)

        if header_match:
            level = len(header_match.group(1))
            pdf.ln(2)
            line(_strip_inline_markup(header_match.group(2)), size=_MARKDOWN_HEADER_SIZES.get(level, 12), bold=True)
        elif bullet_match:
            line("• " + _strip_inline_markup(bullet_match.group(1)), size=10)
        else:
            line(_strip_inline_markup(text), size=10)

    return bytes(pdf.output())


def build_kyc_profile_pdf(profile: KYCRiskProfile, generated_at: str = "") -> bytes:
    pdf = _AuditReportPDF()
    pdf.add_page()
    rtl = profile.language == "ar"
    line = _make_line_writer(pdf, rtl)

    line("تقييم مخاطر العميل (KYC)" if rtl else "Customer KYC Risk Profile", size=18, bold=True)
    meta = generated_at + (f" | {profile.customer_name}" if profile.customer_name else "")
    if meta.strip():
        line(meta, size=10)
    pdf.ln(2)

    risk_line = f"مستوى المخاطر: {profile.risk_level.value}" if rtl else f"Risk Level: {profile.risk_level.value}"
    dd_line = (
        f"مستوى العناية الواجبة: {profile.due_diligence_level.value}" if rtl
        else f"Due Diligence Level: {profile.due_diligence_level.value}"
    )
    line(risk_line, size=13, bold=True, color=_SEVERITY_COLORS[profile.risk_level])
    line(dd_line, size=13, bold=True, color=_DILIGENCE_COLORS[profile.due_diligence_level])
    line(profile.summary, size=11)
    pdf.ln(4)

    if profile.risk_factors:
        line("عوامل المخاطر" if rtl else "Risk Factors", size=13, bold=True)
        for factor in profile.risk_factors:
            line(f"[{factor.severity.value}] {factor.factor}", size=10, color=_SEVERITY_COLORS[factor.severity])
        pdf.ln(3)

    if profile.required_documents:
        line("الوثائق المطلوبة" if rtl else "Required Documents", size=13, bold=True)
        for doc in profile.required_documents:
            line(f"• {doc}", size=10)

    return bytes(pdf.output())
