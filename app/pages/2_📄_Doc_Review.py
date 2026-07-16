import streamlit as st
import os, sys
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from app.utils.ui_components import apply_rtl_style, render_sidebar_brand, render_bidi_markdown, render_structured_report
from app.utils.engine_loader import get_audit_pipeline, get_document_parser
from app.utils.upload_handler import handle_uploaded_file
from app.utils.history_store import load_history, save_history, clear_history
from core.audit_pipeline import render_report_as_markdown
from core.document_parser import MAX_UPLOAD_SIZE_MB
from core.pdf_export import build_audit_report_pdf
from core.schemas import ComplianceAuditReport

HISTORY_KEY = "doc_review"
UPLOAD_MODE = "📎 رفع ملف (PDF / DOCX)"
PASTE_MODE = "📝 لصق نص"

st.set_page_config(page_title="قاطب | فحص الوثائق والمعاملات", page_icon="📄", layout="wide")
apply_rtl_style()
render_sidebar_brand()
st.title("📄 تدقيق العقود والمعاملات التنظيمية")

document_parser = get_document_parser()
audit_pipeline = get_audit_pipeline()

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

input_mode = st.radio("طريقة الإدخال:", [PASTE_MODE, UPLOAD_MODE], horizontal=True)
review_text = ""

if input_mode == UPLOAD_MODE:
    uploaded_file = st.file_uploader(
        "ارفع ملف العقد للتدقيق:",
        type=["pdf", "docx"],
        help=f"الحد الأقصى لحجم الملف: {MAX_UPLOAD_SIZE_MB}MB. الصيغ المدعومة: PDF, DOCX.",
    )
    st.caption(
        "⚠️ يتم حالياً إرسال محتوى الملف إلى واجهة Google Gemini السحابية للتحليل "
        "(لا يزال النشر المحلي/on-prem على خارطة الطريق)."
    )

    if uploaded_file is not None:
        if uploaded_file.size > MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            st.error(f"⚠️ حجم الملف يتجاوز الحد المسموح ({MAX_UPLOAD_SIZE_MB}MB).")
        elif st.button("📤 استخراج ومعاينة النص"):
            with st.spinner("جاري استخراج النص من الملف..."):
                parsed = handle_uploaded_file(uploaded_file, document_parser)
            if not parsed.ok:
                st.error(f"⚠️ {parsed.error}")
                st.session_state["pending_documents"] = None
                st.session_state["pending_source_meta"] = None
            else:
                st.session_state["pending_documents"] = parsed.documents
                st.session_state["pending_source_meta"] = {
                    "stored_id": parsed.stored_id,
                    "stored_path": parsed.stored_path,
                    "original_filename": parsed.original_filename,
                }
                st.session_state["pending_preview"] = parsed.preview_text
                st.success(f"✅ تم استخراج {len(parsed.documents)} جزء نصي من '{parsed.original_filename}'.")

    if st.session_state.get("pending_documents") and st.session_state.get("pending_source_meta"):
        # Preview BEFORE spending an LLM call -- garbled PDF extraction
        # (scanned images, unusual encodings) is common enough that the
        # reviewer should get to sanity-check it first.
        st.text_area(
            "معاينة النص المستخرج (أول 3000 حرف تقريباً، للتحقق فقط):",
            value=st.session_state.get("pending_preview", ""),
            height=200,
            disabled=True,
        )
else:
    review_text = st.text_area(
        "أدخل نص العقد أو تفاصيل المعاملات المالية المبدئية هنا:", height=250,
    )
    st.session_state["pending_documents"] = None
    st.session_state["pending_source_meta"] = None

has_content = (
    bool(st.session_state.get("pending_documents"))
    if input_mode == UPLOAD_MODE
    else bool(review_text.strip())
)
audit_button = st.button("🚀 بدء الفحص والتدقيق الآلي", type="primary", disabled=not has_content)

if audit_button:
    st.session_state["last_structured_report"] = None
    st.session_state["last_report_sources"] = None
    st.session_state["last_report_meta"] = None
    st.session_state["last_audit_findings"] = None
    st.session_state["last_subject_text"] = None

    if not (document_parser and audit_pipeline):
        error_reason = st.session_state.get("engine_init_error", "سبب غير معروف.")
        st.error(
            "⚠️ تعذّر تهيئة محرك الذكاء الاصطناعي. يرجى التحقق من مفتاح "
            "GOOGLE_API_KEY في ملف .env ثم إعادة تشغيل التطبيق.\n\n"
            f"تفاصيل تقنية: `{error_reason}`"
        )
    else:
        pending_documents = st.session_state.get("pending_documents")
        source_meta = st.session_state.get("pending_source_meta") or {}

        if input_mode == UPLOAD_MODE and pending_documents:
            chunks = audit_pipeline.prepare_chunks(raw_text="", source_documents=pending_documents)
            subject_text = st.session_state.get("pending_preview", "")
            source_filename = source_meta.get("original_filename")
            stored_id = source_meta.get("stored_id")
            stored_path = source_meta.get("stored_path")
            input_mode_value = "upload"
        else:
            chunks = audit_pipeline.prepare_chunks(raw_text=review_text, source_documents=None)
            subject_text = review_text
            source_filename = None
            stored_id = None
            stored_path = None
            input_mode_value = "paste"

        with st.status("جاري تحليل الوثيقة...", expanded=True) as status:
            def _progress_cb(i: int, n: int) -> None:
                status.update(label=f"🔎 جاري تحليل الجزء {i}/{n}...")

            report, sources = audit_pipeline.run(chunks, filter_body, progress_cb=_progress_cb)
            status.update(label="✅ اكتمل التحليل", state="complete")

        markdown_report = render_report_as_markdown(report, source_filename=source_filename)

        # Backfilled for app/pages/3_Compliance_Gen.py, which consumes
        # these as plain strings -- keeps that page working unmodified.
        st.session_state["last_audit_findings"] = markdown_report
        st.session_state["last_subject_text"] = subject_text

        st.session_state["last_structured_report"] = report
        st.session_state["last_report_sources"] = sources
        st.session_state["last_report_meta"] = {
            "source_filename": source_filename,
            "stored_id": stored_id,
            "stored_path": stored_path,
        }

        st.session_state.doc_review_history.append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "regulatory_scope": reg_scope,
            "input_mode": input_mode_value,
            "review_text": subject_text[:3000],
            "audit_report": markdown_report,
            "structured_report": report.model_dump(mode="json"),
            "sources": sources,
            "source_filename": source_filename,
            "stored_id": stored_id,
            "stored_path": stored_path,
        })
        save_history(HISTORY_KEY, st.session_state.doc_review_history)

        # Clear pending upload state so re-clicking Run doesn't
        # silently re-analyze stale chunks from a prior file.
        st.session_state["pending_documents"] = None
        st.session_state["pending_source_meta"] = None
        st.session_state["pending_preview"] = None
        st.rerun()

st.divider()
st.subheader("📊 نتيجة التدقيق")
current_report = st.session_state.get("last_structured_report")
if current_report:
    render_structured_report(current_report)

    meta = st.session_state.get("last_report_meta") or {}
    pdf_bytes = build_audit_report_pdf(
        current_report,
        source_filename=meta.get("source_filename"),
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
    )
    st.download_button(
        "📥 تحميل التقرير كملف PDF",
        data=pdf_bytes,
        file_name=f"qatib_audit_{meta.get('stored_id') or 'report'}.pdf",
        mime="application/pdf",
    )

    if st.session_state.get("last_report_sources"):
        with st.expander("🔗 اللوائح التي تم الاعتماد عليها"):
            for doc in st.session_state["last_report_sources"]:
                st.markdown(f"**- {doc.get('source')} (صفحة {doc.get('page')})**")
else:
    st.caption("ستظهر نتائج التدقيق هنا بعد تشغيل الفحص.")

st.divider()
st.subheader(f"📜 سجل التدقيقات السابقة ({len(st.session_state.doc_review_history)})")
if not st.session_state.doc_review_history:
    st.caption("لا توجد تدقيقات سابقة بعد.")
else:
    for idx, entry in enumerate(reversed(st.session_state.doc_review_history)):
        snippet = (entry.get("review_text") or "")[:60].replace("\n", " ")
        header_bits = [entry["timestamp"], entry.get("regulatory_scope", "")]
        if entry.get("source_filename"):
            header_bits.append(f"📎 {entry['source_filename']}")
        header = " — ".join(b for b in header_bits if b) + f" — {snippet}..."

        with st.expander(f"🕘 {header}"):
            if entry.get("structured_report"):
                try:
                    hist_report = ComplianceAuditReport(**entry["structured_report"])
                    render_structured_report(hist_report)
                    hist_pdf = build_audit_report_pdf(
                        hist_report,
                        source_filename=entry.get("source_filename"),
                        generated_at=entry["timestamp"],
                    )
                    st.download_button(
                        "📥 تحميل كملف PDF",
                        data=hist_pdf,
                        file_name=f"qatib_audit_{entry.get('stored_id') or idx}.pdf",
                        mime="application/pdf",
                        key=f"pdf_hist_{idx}",
                    )
                except Exception:
                    # Schema drift safety net -- fall back to the markdown
                    # rendering rather than breaking the whole history list.
                    render_bidi_markdown(entry["audit_report"])
            else:
                # Old entries (pre-structured-output) -- exact original
                # rendering path, unchanged.
                st.markdown("**النص المدقق:**")
                st.text(entry["review_text"])
                st.markdown("**نتيجة التدقيق:**")
                render_bidi_markdown(entry["audit_report"])

            if entry.get("sources"):
                st.markdown("**المصادر:**")
                for s in entry["sources"]:
                    st.markdown(f"- {s['source']} (صفحة {s['page']})")
