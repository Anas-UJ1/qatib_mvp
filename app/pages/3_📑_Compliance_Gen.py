import streamlit as st
import os, sys, json
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from app.utils.ui_components import apply_rtl_style, render_sidebar_brand, render_bidi_markdown, render_kyc_profile
from app.utils.engine_loader import get_report_generator, get_rag_engine, get_llm_router
from app.utils.history_store import load_history, save_history, clear_history
from config.settings_loader import get_settings
from core.lang_utils import is_arabic_text
from core.pdf_export import build_kyc_profile_pdf, build_markdown_report_pdf
from core.schemas import KYCRiskProfile

HISTORY_KEY = "compliance_gen"

REPORT_TYPES = {
    "STR": "📄 STR — تقرير اشتباه في تعاملات مالية",
    "CTR": "💵 CTR — تقرير معاملة نقدية",
    "SDAIA_BREACH": "🔐 SDAIA — إخطار خرق بيانات شخصية",
    "KYC_PROFILE": "🧾 KYC — تقييم مخاطر العميل",
}

st.set_page_config(page_title="قاطب | توليد التقارير", page_icon="📑", layout="wide")
apply_rtl_style()
render_sidebar_brand()
st.title("📑 توليد التقارير التنظيمية")

settings = get_settings()

if "compliance_gen_history" not in st.session_state:
    st.session_state.compliance_gen_history = load_history(HISTORY_KEY)

with st.sidebar:
    if st.button("🗑️ مسح سجل التقارير"):
        clear_history(HISTORY_KEY)
        st.session_state.compliance_gen_history = []
        st.rerun()

report_generator = get_report_generator()

report_type = st.radio(
    "نوع التقرير المطلوب توليده:",
    list(REPORT_TYPES.keys()),
    format_func=lambda k: REPORT_TYPES[k],
    horizontal=True,
)
st.divider()


def _engine_error_box(what: str) -> None:
    error_reason = st.session_state.get("engine_init_error", "سبب غير معروف.")
    st.error(
        f"⚠️ تعذّر تهيئة {what}. يرجى التحقق من مفتاح "
        "GOOGLE_API_KEY في ملف .env ثم إعادة تشغيل التطبيق.\n\n"
        f"تفاصيل تقنية: `{error_reason}`"
    )


def _download_buttons(json_payload: dict, json_filename: str, pdf_bytes: bytes, pdf_filename: str, key_prefix: str) -> None:
    """Renders a JSON download + PDF download side by side. Shared
    between each fresh-result block and the history list so both places
    offer the same two export formats."""
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            label="📥 تحميل (JSON)",
            data=json.dumps(json_payload, ensure_ascii=False, indent=4),
            file_name=json_filename,
            mime="application/json",
            key=f"{key_prefix}json",
        )
    with col2:
        st.download_button(
            label="📥 تحميل (PDF)",
            data=pdf_bytes,
            file_name=pdf_filename,
            mime="application/pdf",
            key=f"{key_prefix}pdf",
        )


def _get_last_audit_context():
    """Shared STR/CTR handoff: prefer the live session-state result from a
    just-completed Doc Review audit, falling back to the most recently
    persisted audit (a page refresh can reset session state before the
    handoff completes)."""
    last_audit_findings = st.session_state.get("last_audit_findings")
    last_subject_text = st.session_state.get("last_subject_text")
    if not last_audit_findings:
        past_audits = load_history("doc_review")
        if past_audits:
            last_audit_findings = past_audits[-1]["audit_report"]
            last_subject_text = past_audits[-1]["review_text"]
    return last_audit_findings, last_subject_text


# =====================================================================
# STR -- Suspicious Transaction Report (requires a prior Doc Review audit)
# =====================================================================
if report_type == "STR":
    last_audit_findings, last_subject_text = _get_last_audit_context()
    if not last_audit_findings:
        st.warning("⚠️ لا توجد نتائج تدقيق سابقة أو صالحة. يرجى العودة لصفحة الفحص وإجراء تدقيق جديد أولاً.")
        st.page_link("pages/2_📄_Doc_Review.py", label="↩️ الانتقال إلى صفحة فحص الوثائق", icon="📄")
        st.stop()

    with st.form("str_generation_form"):
        col1, col2 = st.columns(2)
        with col1:
            subject_name = st.text_input("اسم الطرف المشتبه به:")
        with col2:
            transaction_type = st.text_input("نوع المعاملة/الوثيقة:")
        anomaly_details = st.text_area(
            "ملخص وصفي للمؤشر المشبوه:",
            value=(last_subject_text or "")[:200] + "...",
            height=100,
        )
        generate_btn = st.form_submit_button("⚙️ توليد مسودة التقرير (STR)")

    if generate_btn:
        if not subject_name or not transaction_type:
            st.error("يرجى تعبئة اسم الطرف المشتبه به ونوع المعاملة قبل المتابعة.")
        elif not report_generator:
            _engine_error_box("مولد التقارير")
        else:
            with st.spinner("جاري صياغة التقرير المعتمد..."):
                generated_str = report_generator.generate_fiu_str(
                    subject_name=subject_name,
                    transaction_type=transaction_type,
                    anomaly_details=anomaly_details,
                    llm_audit_findings=last_audit_findings,
                )
                st.success("تم توليد التقرير بنجاح!")
                with st.container(border=True):
                    render_bidi_markdown(generated_str)

                str_lang = "ar" if is_arabic_text(generated_str) else "en"
                _download_buttons(
                    json_payload={"generated_at": datetime.now().isoformat(), "raw_report_markdown": generated_str},
                    json_filename="STR.json",
                    pdf_bytes=build_markdown_report_pdf(generated_str, language=str_lang),
                    pdf_filename="STR.pdf",
                    key_prefix="str_fresh_",
                )

                st.session_state.compliance_gen_history.append({
                    "report_type": "STR",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "subject_name": subject_name,
                    "transaction_type": transaction_type,
                    "anomaly_details": anomaly_details,
                    "generated_str": generated_str,
                })
                save_history(HISTORY_KEY, st.session_state.compliance_gen_history)

# =====================================================================
# CTR -- Cash Transaction Report (standalone, RAG-grounded)
#
# Unlike STR, a CTR is a routine filing triggered by the transaction
# AMOUNT itself, not by suspicion -- it must NOT be gated behind a prior
# Doc Review "suspicious finding", and its fields/wording must not imply
# wrongdoing when there may be none.
# =====================================================================
elif report_type == "CTR":
    with st.form("ctr_generation_form"):
        col1, col2, col3 = st.columns(3)
        with col1:
            subject_name = st.text_input("اسم الطرف:")
        with col2:
            transaction_amount = st.text_input("قيمة المعاملة النقدية:")
        with col3:
            currency = st.text_input("العملة:", value="SAR")
        transaction_date = st.date_input("تاريخ المعاملة:").strftime("%Y-%m-%d")
        transaction_details = st.text_area(
            "وصف تفاصيل المعاملة النقدية (اختياري):",
            height=100,
        )
        generate_btn = st.form_submit_button("⚙️ توليد مسودة التقرير (CTR)")

    if generate_btn:
        rag_engine = get_rag_engine()
        llm_router = get_llm_router()
        if not subject_name or not transaction_amount:
            st.error("يرجى تعبئة اسم الطرف وقيمة المعاملة قبل المتابعة.")
        elif not (report_generator and rag_engine and llm_router):
            _engine_error_box("مولد التقارير")
        else:
            with st.spinner("جاري صياغة التقرير المعتمد..."):
                retrieval_query = f"{transaction_amount} {currency} {transaction_details}"[:500]
                retrieved_docs = rag_engine.retrieve_context(
                    query=retrieval_query,
                    top_k=settings["rag"]["top_k"],
                    regulatory_body="SAMA",
                )
                regulatory_context = llm_router.format_context(retrieved_docs) if retrieved_docs else ""

                generated_str = report_generator.generate_ctr(
                    subject_name=subject_name,
                    transaction_amount=transaction_amount,
                    currency=currency,
                    transaction_date=transaction_date,
                    transaction_details=transaction_details or "-",
                    regulatory_context=regulatory_context,
                )
                st.success("تم توليد التقرير بنجاح!")
                with st.container(border=True):
                    render_bidi_markdown(generated_str)

                sources = [
                    {"source": doc.metadata.get("source"), "page": doc.metadata.get("page_number")}
                    for doc in retrieved_docs
                ]
                if sources:
                    with st.expander("🔗 اللوائح التي تم الاعتماد عليها"):
                        for s in sources:
                            st.markdown(f"**- {s['source']} (صفحة {s['page']})**")

                ctr_lang = "ar" if is_arabic_text(generated_str) else "en"
                _download_buttons(
                    json_payload={"generated_at": datetime.now().isoformat(), "raw_report_markdown": generated_str},
                    json_filename="CTR.json",
                    pdf_bytes=build_markdown_report_pdf(generated_str, language=ctr_lang),
                    pdf_filename="CTR.pdf",
                    key_prefix="ctr_fresh_",
                )

                st.session_state.compliance_gen_history.append({
                    "report_type": "CTR",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "subject_name": subject_name,
                    "transaction_amount": transaction_amount,
                    "currency": currency,
                    "transaction_date": transaction_date,
                    "transaction_details": transaction_details,
                    "generated_str": generated_str,
                    "sources": sources,
                })
                save_history(HISTORY_KEY, st.session_state.compliance_gen_history)

# =====================================================================
# SDAIA -- Personal Data Breach Notification (standalone, RAG-grounded)
# =====================================================================
elif report_type == "SDAIA_BREACH":
    with st.form("sdaia_breach_form"):
        incident_description = st.text_area("وصف الحادثة:", height=100)
        col1, col2 = st.columns(2)
        with col1:
            data_categories_affected = st.text_input("فئات البيانات المتأثرة:")
        with col2:
            affected_individuals_count = st.text_input("عدد الأفراد المتأثرين:")
        discovery_date = st.date_input("تاريخ اكتشاف الحادثة:").strftime("%Y-%m-%d")
        containment_measures = st.text_area("إجراءات الاحتواء المتخذة:", height=80)
        generate_btn = st.form_submit_button("⚙️ توليد مسودة الإخطار (SDAIA)")

    if generate_btn:
        rag_engine = get_rag_engine()
        llm_router = get_llm_router()
        if not incident_description.strip():
            st.error("يرجى إدخال وصف الحادثة قبل المتابعة.")
        elif not (report_generator and rag_engine and llm_router):
            _engine_error_box("محرك توليد الإخطارات")
        else:
            with st.spinner("جاري صياغة إخطار خرق البيانات..."):
                retrieved_docs = rag_engine.retrieve_context(
                    query=incident_description[:500],
                    top_k=settings["rag"]["top_k"],
                    regulatory_body="SDAIA",
                )
                regulatory_context = llm_router.format_context(retrieved_docs) if retrieved_docs else ""
                if not retrieved_docs:
                    st.info("لم يتم العثور على مواد تنظيمية محددة من SDAIA لهذه الحادثة؛ سيتم توليد الإخطار دون استشهادات مباشرة.")

                generated_str = report_generator.generate_sdaia_breach_notification(
                    incident_description=incident_description,
                    data_categories_affected=data_categories_affected,
                    affected_individuals_count=affected_individuals_count,
                    discovery_date=discovery_date,
                    containment_measures=containment_measures,
                    regulatory_context=regulatory_context,
                )
                st.success("تم توليد الإخطار بنجاح!")
                with st.container(border=True):
                    render_bidi_markdown(generated_str)

                sources = [
                    {"source": doc.metadata.get("source"), "page": doc.metadata.get("page_number")}
                    for doc in retrieved_docs
                ]
                if sources:
                    with st.expander("🔗 اللوائح التي تم الاعتماد عليها"):
                        for s in sources:
                            st.markdown(f"**- {s['source']} (صفحة {s['page']})**")

                sdaia_lang = "ar" if is_arabic_text(generated_str) else "en"
                _download_buttons(
                    json_payload={"generated_at": datetime.now().isoformat(), "raw_report_markdown": generated_str},
                    json_filename="SDAIA_Breach_Notification.json",
                    pdf_bytes=build_markdown_report_pdf(generated_str, language=sdaia_lang),
                    pdf_filename="SDAIA_Breach_Notification.pdf",
                    key_prefix="sdaia_fresh_",
                )

                st.session_state.compliance_gen_history.append({
                    "report_type": "SDAIA_BREACH",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "incident_description": incident_description,
                    "data_categories_affected": data_categories_affected,
                    "affected_individuals_count": affected_individuals_count,
                    "discovery_date": discovery_date,
                    "containment_measures": containment_measures,
                    "generated_str": generated_str,
                    "sources": sources,
                })
                save_history(HISTORY_KEY, st.session_state.compliance_gen_history)

# =====================================================================
# KYC -- Customer Risk Profile (standalone, RAG-grounded, structured)
# =====================================================================
elif report_type == "KYC_PROFILE":
    with st.form("kyc_profile_form"):
        col1, col2 = st.columns(2)
        with col1:
            customer_name = st.text_input("اسم العميل:")
        with col2:
            country = st.text_input("الدولة:")
        business_activity = st.text_input("النشاط التجاري:")
        col3, col4 = st.columns(2)
        with col3:
            expected_monthly_volume = st.text_input("حجم التعاملات الشهري المتوقع:")
        with col4:
            source_of_funds = st.text_input("مصدر الأموال:")
        col5, col6 = st.columns(2)
        with col5:
            is_pep = st.selectbox("هل العميل شخص سياسي معرض للمخاطر (PEP)؟", ["لا", "نعم"])
        with col6:
            high_risk_country_exposure = st.selectbox("هل توجد ارتباطات بدول عالية المخاطر؟", ["لا", "نعم"])
        notes = st.text_area("ملاحظات إضافية (اختياري):", height=80)
        generate_btn = st.form_submit_button("⚙️ توليد تقييم المخاطر (KYC)")

    if generate_btn:
        rag_engine = get_rag_engine()
        llm_router = get_llm_router()
        if not customer_name.strip():
            st.error("يرجى إدخال اسم العميل قبل المتابعة.")
        elif not (rag_engine and llm_router):
            _engine_error_box("محرك تقييم المخاطر")
        else:
            customer_profile_text = (
                f"اسم العميل: {customer_name}\n"
                f"الدولة: {country}\n"
                f"النشاط التجاري: {business_activity}\n"
                f"حجم التعاملات الشهري المتوقع: {expected_monthly_volume}\n"
                f"مصدر الأموال: {source_of_funds}\n"
                f"شخص سياسي معرض للمخاطر (PEP): {is_pep}\n"
                f"ارتباطات بدول عالية المخاطر: {high_risk_country_exposure}\n"
                f"ملاحظات: {notes}"
            )
            with st.spinner("جاري تقييم مخاطر العميل..."):
                retrieved_docs = rag_engine.retrieve_context(
                    query=customer_profile_text[:500],
                    top_k=settings["rag"]["top_k"],
                    regulatory_body="SAMA",
                )
                context_str = llm_router.format_context(retrieved_docs) if retrieved_docs else ""
                if not retrieved_docs:
                    st.info("لم يتم العثور على مواد تنظيمية محددة من SAMA لهذا العميل؛ سيتم بناء التقييم دون استشهادات مباشرة.")

                profile = llm_router.assess_kyc_risk(
                    context_str=context_str,
                    customer_profile_text=customer_profile_text,
                    customer_name=customer_name,
                )
                st.success("تم توليد تقييم المخاطر بنجاح!")
                with st.container(border=True):
                    render_kyc_profile(profile)

                sources = [
                    {"source": doc.metadata.get("source"), "page": doc.metadata.get("page_number")}
                    for doc in retrieved_docs
                ]
                if sources:
                    with st.expander("🔗 اللوائح التي تم الاعتماد عليها"):
                        for s in sources:
                            st.markdown(f"**- {s['source']} (صفحة {s['page']})**")

                generated_at_str = datetime.now().strftime("%Y-%m-%d %H:%M")
                _download_buttons(
                    json_payload={"generated_at": datetime.now().isoformat(), "kyc_profile": profile.model_dump(mode="json")},
                    json_filename="KYC_Risk_Profile.json",
                    pdf_bytes=build_kyc_profile_pdf(profile, generated_at=generated_at_str),
                    pdf_filename="KYC_Risk_Profile.pdf",
                    key_prefix="kyc_fresh_",
                )

                st.session_state.compliance_gen_history.append({
                    "report_type": "KYC_PROFILE",
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "customer_name": customer_name,
                    "customer_profile_text": customer_profile_text,
                    "kyc_profile": profile.model_dump(mode="json"),
                    "sources": sources,
                })
                save_history(HISTORY_KEY, st.session_state.compliance_gen_history)


# =====================================================================
# History (all report types, backward-compatible with pre-existing
# STR-only entries that predate the report_type field)
# =====================================================================
st.divider()
st.subheader(f"📜 التقارير السابقة ({len(st.session_state.compliance_gen_history)})")
if not st.session_state.compliance_gen_history:
    st.caption("لا توجد تقارير سابقة بعد.")
else:
    for i, entry in enumerate(reversed(st.session_state.compliance_gen_history)):
        entry_type = entry.get("report_type", "STR")
        if entry_type == "STR":
            title = f"🕘 {entry['timestamp']} — STR — {entry.get('subject_name', '')} — {entry.get('transaction_type', '')}"
        elif entry_type == "CTR":
            title = f"🕘 {entry['timestamp']} — CTR — {entry.get('subject_name', '')} — {entry.get('transaction_amount', '')} {entry.get('currency', '')}"
        elif entry_type == "SDAIA_BREACH":
            snippet = (entry.get("incident_description", "") or "")[:60].replace("\n", " ")
            title = f"🕘 {entry['timestamp']} — SDAIA — {snippet}..."
        else:  # KYC_PROFILE
            risk_level = (entry.get("kyc_profile") or {}).get("risk_level", "")
            title = f"🕘 {entry['timestamp']} — KYC — {entry.get('customer_name', '')} — {risk_level}"

        safe_ts = entry["timestamp"].replace(":", "-").replace(" ", "_")

        with st.expander(title):
            if entry_type == "KYC_PROFILE":
                try:
                    hist_profile = KYCRiskProfile(**entry["kyc_profile"])
                    with st.container(border=True):
                        render_kyc_profile(hist_profile)
                    _download_buttons(
                        json_payload={"generated_at": entry["timestamp"], "kyc_profile": entry.get("kyc_profile")},
                        json_filename=f"KYC_{safe_ts}.json",
                        pdf_bytes=build_kyc_profile_pdf(hist_profile, generated_at=entry["timestamp"]),
                        pdf_filename=f"KYC_{safe_ts}.pdf",
                        key_prefix=f"hist_{i}_",
                    )
                except Exception:
                    # Schema drift safety net -- fall back to raw JSON and
                    # skip the PDF button rather than breaking the page.
                    st.json(entry.get("kyc_profile"))
                    st.download_button(
                        label="📥 تحميل (JSON)",
                        data=json.dumps(
                            {"generated_at": entry["timestamp"], "kyc_profile": entry.get("kyc_profile")},
                            ensure_ascii=False, indent=4,
                        ),
                        file_name=f"KYC_{safe_ts}.json",
                        mime="application/json",
                        key=f"download_hist_{i}",
                    )
            else:
                with st.container(border=True):
                    render_bidi_markdown(entry.get("generated_str", ""))
                if entry.get("sources"):
                    st.markdown("**المصادر:**")
                    for s in entry["sources"]:
                        st.markdown(f"- {s['source']} (صفحة {s['page']})")
                hist_lang = "ar" if is_arabic_text(entry.get("generated_str", "")) else "en"
                _download_buttons(
                    json_payload={"generated_at": entry["timestamp"], "raw_report_markdown": entry.get("generated_str", "")},
                    json_filename=f"{entry_type}_{safe_ts}.json",
                    pdf_bytes=build_markdown_report_pdf(entry.get("generated_str", ""), language=hist_lang),
                    pdf_filename=f"{entry_type}_{safe_ts}.pdf",
                    key_prefix=f"hist_{i}_",
                )
