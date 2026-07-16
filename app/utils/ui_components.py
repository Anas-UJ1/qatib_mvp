"""
Shared UI helpers for RTL Streamlit pages.
"""

import html
import os
import markdown as md_lib
import streamlit as st
from core.lang_utils import is_arabic_text
from core.schemas import ComplianceAuditReport, DueDiligenceLevel, KYCRiskProfile, RiskSeverity

_SEVERITY_BADGE = {
    RiskSeverity.HIGH: "🔴",
    RiskSeverity.MEDIUM: "🟡",
    RiskSeverity.LOW: "🟢",
}

_DILIGENCE_BADGE = {
    DueDiligenceLevel.ENHANCED: "🔴",
    DueDiligenceLevel.STANDARD: "🟡",
    DueDiligenceLevel.SIMPLIFIED: "🟢",
}


def _esc(text: str) -> str:
    """Escape LLM-generated text before it's interpolated into a raw HTML
    string (unlike render_bidi_markdown, this content never passes through
    the markdown library, so nothing else escapes it first)."""
    return html.escape(text or "").replace("\n", "<br>")

_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
# qatib_logo_light.svg is filled dark (#000000) -- visible against light
# backgrounds. qatib_logo_dark.svg is filled cream (#fcf7f0) -- visible
# against dark backgrounds.
LOGO_FOR_LIGHT_BG = os.path.join(_ASSETS_DIR, "qatib_logo_light.svg")
LOGO_FOR_DARK_BG = os.path.join(_ASSETS_DIR, "qatib_logo_dark.svg")

RTL_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"], .stApp,
    .block-container, p, div, span, label, li,
    h1, h2, h3, h4, h5, h6,
    button, input, textarea,
    section[data-testid="stSidebar"], .stChatMessage,
    .stMarkdown, .stButton, .stTextInput, .stTextArea, .stSelectbox, .stMetric {
        font-family: 'IBM Plex Sans Arabic', sans-serif !important;
    }

    /* The rule above also matches Streamlit's own icon <span>s (they're
       plain <span> elements too), which breaks their ligature-based glyph
       rendering -- "keyboard_double_arrow_left" showing as literal text
       instead of the arrow icon, chat avatars showing "face" as text, etc.
       Restore their icon font with higher selector specificity. */
    [data-testid="stIconMaterial"] {
        font-family: "Material Symbols Rounded" !important;
    }

    .block-container, p, div, h1, h2, h3, h4, h5, h6,
    section[data-testid="stSidebar"], .stChatMessage {
        direction: RTL;
        text-align: right;
    }
    .stDownloadButton {
        direction: LTR;
    }

    /* LLM output can be Arabic OR English depending on the query language
       (see the language-matching system prompts) -- the blanket RTL rule
       above is wrong for English responses (bullet markers end up on the
       right, text hugs the wrong edge). render_bidi_markdown() wraps
       content in one of these classes based on its actual detected
       language instead of the page's static RTL default. */
    .qatib-bidi-rtl, .qatib-bidi-rtl * {
        direction: rtl !important;
        text-align: right !important;
    }
    .qatib-bidi-ltr, .qatib-bidi-ltr * {
        direction: ltr !important;
        text-align: left !important;
    }

    /* Streamlit's sidebar collapse animation hardcodes a leftward slide
       assuming an LTR sidebar docked at the left edge. Our RTL layout
       docks it on the right instead, so that same leftward slide just
       relocates it to the middle of the screen (still fully visible,
       with its squeezed contents wrapping into an unreadable column)
       rather than off-screen. Slide it right by its own width instead,
       and force-collapse the box itself as a safety net. The button
       this hides is redundant with Streamlit's own separate
       stExpandSidebarButton that appears once collapsed. */
    section[data-testid="stSidebar"][aria-expanded="false"] {
        width: 0px !important;
        min-width: 0px !important;
        overflow: hidden !important;
        transform: translateX(100%) !important;
    }
</style>
"""


def apply_rtl_style() -> None:
    """Apply consistent right-to-left styling across all Qatib pages."""
    st.markdown(RTL_CSS, unsafe_allow_html=True)


def render_bidi_markdown(text: str) -> None:
    """Render markdown content with direction matching its actual language.

    Chat answers, audit reports, and STR drafts can come back in Arabic or
    English depending on the query (see the language-matching system
    prompts). Forcing the page's blanket RTL styling onto English content
    misplaces bullet markers and text alignment, so this picks the correct
    direction per call and renders through it instead.
    """
    css_class = "qatib-bidi-rtl" if is_arabic_text(text) else "qatib-bidi-ltr"
    html_body = md_lib.markdown(text or "", extensions=["extra"])
    st.markdown(f'<div class="{css_class}">{html_body}</div>', unsafe_allow_html=True)


def get_logo_path() -> str:
    """Pick the logo variant that stays visible against the active theme."""
    theme_type = st.context.theme.type
    return LOGO_FOR_DARK_BG if theme_type == "dark" else LOGO_FOR_LIGHT_BG


def render_structured_report(report: ComplianceAuditReport) -> None:
    """Render a ComplianceAuditReport as severity-coded risk cards with an
    overall score, instead of a single markdown wall of text. Shared
    between a fresh Doc Review result and any history entry that has a
    structured_report."""
    rtl = report.language == "ar"
    css_class = "qatib-bidi-rtl" if rtl else "qatib-bidi-ltr"

    score_label = "درجة المخاطر الإجمالية" if rtl else "Overall Risk Score"
    severity_label = "المستوى العام للمخاطر" if rtl else "Overall Severity"
    summary_label = "الملخص التنفيذي" if rtl else "Executive Summary"
    no_flags_msg = (
        "لم يتم العثور على مخالفات صريحة أو مخاطر تنظيمية جوهرية." if rtl
        else "No explicit violations or material regulatory risks were found."
    )
    reg_label = "المرجع التنظيمي" if rtl else "Regulatory reference"
    doc_label = "موقع الإشارة في الوثيقة" if rtl else "Document location"
    rec_label = "التوصية" if rtl else "Recommendation"

    col1, col2 = st.columns(2)
    col1.metric(score_label, f"{report.overall_risk_score}/100")
    col2.metric(severity_label, f"{_SEVERITY_BADGE[report.overall_severity]} {report.overall_severity.value}")
    st.progress(min(report.overall_risk_score, 100) / 100)

    st.markdown(
        f'<div class="{css_class}"><strong>{summary_label}:</strong> {_esc(report.summary)}</div>',
        unsafe_allow_html=True,
    )

    if not report.flags:
        st.success(no_flags_msg)
        return

    st.write("")
    for flag in report.flags:
        with st.container(border=True):
            st.markdown(
                f'<div class="{css_class}">{_SEVERITY_BADGE[flag.severity]} '
                f'<strong>[{flag.severity.value}] {_esc(flag.category)}</strong></div>',
                unsafe_allow_html=True,
            )
            st.markdown(f'<div class="{css_class}">{_esc(flag.description)}</div>', unsafe_allow_html=True)

            citation_bits = []
            if flag.regulation_source:
                ref = f" ({_esc(flag.regulation_reference)})" if flag.regulation_reference else ""
                citation_bits.append(f"📖 {reg_label}: {_esc(flag.regulation_source)}{ref}")
            if flag.contract_reference:
                citation_bits.append(f"📄 {doc_label}: {_esc(flag.contract_reference)}")
            if citation_bits:
                st.markdown(
                    f'<div class="{css_class}" style="opacity:0.75; font-size:0.9em;">{" | ".join(citation_bits)}</div>',
                    unsafe_allow_html=True,
                )

            if flag.recommendation:
                st.markdown(
                    f'<div class="{css_class}">💡 <strong>{rec_label}:</strong> {_esc(flag.recommendation)}</div>',
                    unsafe_allow_html=True,
                )


def render_kyc_profile(profile: KYCRiskProfile) -> None:
    """Render a KYCRiskProfile as a risk-level/due-diligence summary plus
    factor list and required-documents checklist -- styled like
    render_structured_report. Shared between a fresh KYC assessment and
    any history entry that has a kyc_profile."""
    rtl = profile.language == "ar"
    css_class = "qatib-bidi-rtl" if rtl else "qatib-bidi-ltr"

    risk_label = "مستوى المخاطر" if rtl else "Risk Level"
    dd_label = "مستوى العناية الواجبة" if rtl else "Due Diligence Level"
    summary_label = "الملخص التنفيذي" if rtl else "Executive Summary"
    factors_label = "عوامل المخاطر" if rtl else "Risk Factors"
    docs_label = "الوثائق المطلوبة" if rtl else "Required Documents"
    no_factors_msg = "لم يتم تحديد عوامل مخاطر جوهرية." if rtl else "No material risk factors identified."

    col1, col2 = st.columns(2)
    col1.metric(risk_label, f"{_SEVERITY_BADGE[profile.risk_level]} {profile.risk_level.value}")
    col2.metric(dd_label, f"{_DILIGENCE_BADGE[profile.due_diligence_level]} {profile.due_diligence_level.value}")

    st.markdown(
        f'<div class="{css_class}"><strong>{summary_label}:</strong> {_esc(profile.summary)}</div>',
        unsafe_allow_html=True,
    )

    st.write("")
    st.markdown(f'<div class="{css_class}"><strong>{factors_label}</strong></div>', unsafe_allow_html=True)
    if not profile.risk_factors:
        st.info(no_factors_msg)
    else:
        for factor in profile.risk_factors:
            st.markdown(
                f'<div class="{css_class}">{_SEVERITY_BADGE[factor.severity]} '
                f'[{factor.severity.value}] {_esc(factor.factor)}</div>',
                unsafe_allow_html=True,
            )

    if profile.required_documents:
        st.write("")
        st.markdown(f'<div class="{css_class}"><strong>{docs_label}</strong></div>', unsafe_allow_html=True)
        for doc in profile.required_documents:
            st.markdown(f'<div class="{css_class}">📄 {_esc(doc)}</div>', unsafe_allow_html=True)


def render_sidebar_brand() -> None:
    """Show the Qatib logo + name at the top of the sidebar on every page."""
    with st.sidebar:
        col_logo, col_name = st.columns([1, 3])
        with col_logo:
            st.image(get_logo_path(), width=48)
        with col_name:
            st.markdown("**قاطب (Qatib)**")
        st.divider()
