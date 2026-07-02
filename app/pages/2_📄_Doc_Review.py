import streamlit as st
import os, sys
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from app.utils.ui_components import apply_rtl_style, render_sidebar_brand, render_bidi_markdown
from app.utils.engine_loader import get_rag_engine, get_llm_router
from app.utils.history_store import load_history, save_history, clear_history
from config.settings_loader import get_settings

HISTORY_KEY = "doc_review"

st.set_page_config(page_title="قاطب | فحص الوثائق والمعاملات", page_icon="📄", layout="wide")
apply_rtl_style()
render_sidebar_brand()
st.title("📄 تدقيق العقود والمعاملات التنظيمية")

settings = get_settings()
rag_engine = get_rag_engine()
llm_router = get_llm_router()

if "doc_review_history" not in st.session_state:
    # Persisted history survives a full page refresh, unlike bare
    # st.session_state which can reset on a new browser session.
    st.session_state.doc_review_history = load_history(HISTORY_KEY)

with st.sidebar:
    if st.button("🗑️ مسح سجل التدقيقات"):
        clear_history(HISTORY_KEY)
        st.session_state.doc_review_history = []
        st.rerun()

reg_scope = st.selectbox(
    "نطاق التشريع المستهدف للفحص:",
    ["الكل (All Frameworks)", "SAMA", "ZATCA", "CMA", "SDAIA"],
)
filter_body = None if reg_scope == "الكل (All Frameworks)" else reg_scope
review_text = st.text_area("أدخل نص العقد أو تفاصيل المعاملات المالية المبدئية هنا:", height=250)
audit_button = st.button("🚀 بدء الفحص والتدقيق الآلي")

# Results render BENEATH the input (not beside it) so the reviewer reads
# top-to-bottom instead of side-by-side.
st.divider()

if audit_button:
    # --- FIX: clear stale state BEFORE running new retrieval, so a
    # failed/empty retrieval never leaves a previous audit's findings
    # lying around for Page 3 to mistakenly attach to a new subject. ---
    st.session_state["last_audit_findings"] = None
    st.session_state["last_subject_text"] = None

    if not review_text.strip():
        st.warning("يرجى إدخال نص للتدقيق قبل بدء الفحص.")
    elif not (rag_engine and llm_router):
        error_reason = st.session_state.get("engine_init_error", "سبب غير معروف.")
        st.error(
            "⚠️ تعذّر تهيئة محرك الذكاء الاصطناعي. يرجى التحقق من مفتاح "
            "GOOGLE_API_KEY في ملف .env ثم إعادة تشغيل التطبيق.\n\n"
            f"تفاصيل تقنية: `{error_reason}`"
        )
    else:
        with st.spinner("جاري تحليل المدخلات..."):
            retrieved_docs = rag_engine.retrieve_context(
                query=review_text[:500],
                top_k=settings["rag"]["top_k"],
                regulatory_body=filter_body,
            )
            if retrieved_docs:
                audit_report = llm_router.analyze_compliance_risks(
                    input_data=review_text, retrieved_docs=retrieved_docs
                )
                # Only persist state on a SUCCESSFUL audit with real findings.
                st.session_state["last_audit_findings"] = audit_report
                st.session_state["last_subject_text"] = review_text
                render_bidi_markdown(audit_report)
                with st.expander("🔗 اللوائح التي تم الاعتماد عليها"):
                    for doc in retrieved_docs:
                        st.markdown(
                            f"**- {doc.metadata.get('source')} "
                            f"(صفحة {doc.metadata.get('page_number')})**"
                        )

                st.session_state.doc_review_history.append({
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "regulatory_scope": reg_scope,
                    "review_text": review_text,
                    "audit_report": audit_report,
                    "sources": [
                        {"source": doc.metadata.get("source"), "page": doc.metadata.get("page_number")}
                        for doc in retrieved_docs
                    ],
                })
                save_history(HISTORY_KEY, st.session_state.doc_review_history)
            else:
                st.info("لم يتم العثور على مخالفات صريحة أو تشريعات ذات صلة.")

st.divider()
st.subheader(f"📜 سجل التدقيقات السابقة ({len(st.session_state.doc_review_history)})")
if not st.session_state.doc_review_history:
    st.caption("لا توجد تدقيقات سابقة بعد.")
else:
    for entry in reversed(st.session_state.doc_review_history):
        snippet = entry["review_text"][:60].replace("\n", " ")
        with st.expander(f"🕘 {entry['timestamp']} — {entry['regulatory_scope']} — {snippet}..."):
            st.markdown("**النص المدقق:**")
            st.text(entry["review_text"])
            st.markdown("**نتيجة التدقيق:**")
            render_bidi_markdown(entry["audit_report"])
            if entry.get("sources"):
                st.markdown("**المصادر:**")
                for s in entry["sources"]:
                    st.markdown(f"- {s['source']} (صفحة {s['page']})")
