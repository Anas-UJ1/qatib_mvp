import streamlit as st
import os, sys, json
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from app.utils.ui_components import apply_rtl_style, render_sidebar_brand, render_bidi_markdown
from app.utils.engine_loader import get_report_generator
from app.utils.history_store import load_history, save_history, clear_history

HISTORY_KEY = "compliance_gen"

st.set_page_config(page_title="قاطب | توليد التقارير", page_icon="📑", layout="wide")
apply_rtl_style()
render_sidebar_brand()
st.title("📑 توليد تقارير الاشتباه المالي (STR)")

if "str_history" not in st.session_state:
    st.session_state.str_history = load_history(HISTORY_KEY)

with st.sidebar:
    if st.button("🗑️ مسح سجل التقارير"):
        clear_history(HISTORY_KEY)
        st.session_state.str_history = []
        st.rerun()

# --- Graceful handling of missing / cleared state ---
last_audit_findings = st.session_state.get("last_audit_findings")
last_subject_text = st.session_state.get("last_subject_text")

if not last_audit_findings:
    # A page refresh can reset st.session_state before the Doc Review ->
    # Compliance Gen handoff completes. Fall back to the most recently
    # persisted audit instead of forcing the user back to Doc Review.
    past_audits = load_history("doc_review")
    if past_audits:
        last_audit_findings = past_audits[-1]["audit_report"]
        last_subject_text = past_audits[-1]["review_text"]

if not last_audit_findings:
    st.warning("⚠️ لا توجد نتائج تدقيق سابقة أو صالحة. يرجى العودة لصفحة الفحص وإجراء تدقيق جديد أولاً.")
    st.page_link("pages/2_📄_Doc_Review.py", label="↩️ الانتقال إلى صفحة فحص الوثائق", icon="📄")
    st.stop()

report_generator = get_report_generator()

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
    # --- FIX: was st.form_submit_submit_button (typo, crashes on render) ---
    generate_btn = st.form_submit_button("⚙️ توليد مسودة التقرير (STR)")

if generate_btn:
    if not subject_name or not transaction_type:
        st.error("يرجى تعبئة اسم الطرف المشتبه به ونوع المعاملة قبل المتابعة.")
    elif not report_generator:
        error_reason = st.session_state.get("engine_init_error", "سبب غير معروف.")
        st.error(
            "⚠️ تعذّر تهيئة مولد التقارير. يرجى التحقق من مفتاح "
            "GOOGLE_API_KEY في ملف .env ثم إعادة تشغيل التطبيق.\n\n"
            f"تفاصيل تقنية: `{error_reason}`"
        )
    else:
        with st.spinner("جاري صياغة التقرير المعتمد..."):
            generated_str = report_generator.generate_fiu_str(
                subject_name=subject_name,
                transaction_type=transaction_type,
                anomaly_details=anomaly_details,
                llm_audit_findings=last_audit_findings,
            )
            st.success("تم توليد التقرير بنجاح!")
            # A native bordered container (instead of a hardcoded-color div)
            # adapts to the active theme, so text stays readable in both
            # light and dark mode.
            with st.container(border=True):
                render_bidi_markdown(generated_str)

            export_payload = {
                "generated_at": datetime.now().isoformat(),
                "raw_report_markdown": generated_str,
            }
            st.download_button(
                label="📥 تحميل التقرير (JSON)",
                data=json.dumps(export_payload, ensure_ascii=False, indent=4),
                file_name="STR.json",
                mime="application/json",
            )

            st.session_state.str_history.append({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "subject_name": subject_name,
                "transaction_type": transaction_type,
                "anomaly_details": anomaly_details,
                "generated_str": generated_str,
            })
            save_history(HISTORY_KEY, st.session_state.str_history)

st.divider()
st.subheader(f"📜 التقارير السابقة ({len(st.session_state.str_history)})")
if not st.session_state.str_history:
    st.caption("لا توجد تقارير سابقة بعد.")
else:
    for i, entry in enumerate(reversed(st.session_state.str_history)):
        with st.expander(f"🕘 {entry['timestamp']} — {entry['subject_name']} — {entry['transaction_type']}"):
            with st.container(border=True):
                render_bidi_markdown(entry["generated_str"])
            st.download_button(
                label="📥 تحميل هذا التقرير (JSON)",
                data=json.dumps(
                    {"generated_at": entry["timestamp"], "raw_report_markdown": entry["generated_str"]},
                    ensure_ascii=False,
                    indent=4,
                ),
                file_name=f"STR_{entry['timestamp'].replace(':', '-').replace(' ', '_')}.json",
                mime="application/json",
                key=f"download_hist_{i}",
            )
