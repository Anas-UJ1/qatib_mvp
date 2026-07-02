import streamlit as st
import os, sys
import uuid
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from app.utils.ui_components import apply_rtl_style, render_sidebar_brand, get_logo_path, render_bidi_markdown
from app.utils.engine_loader import get_rag_engine, get_llm_router
from app.utils.history_store import load_history, save_history
from config.settings_loader import get_settings

HISTORY_KEY = "chat_regtech"
WELCOME_MESSAGE = {"role": "assistant", "content": "أهلاً بك! أنا قاطب، مساعدك التنظيمي."}


def _new_session() -> dict:
    return {
        "id": uuid.uuid4().hex,
        "title": None,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "messages": [WELCOME_MESSAGE],
    }


def _active_session() -> dict:
    for s in st.session_state.chat_sessions:
        if s["id"] == st.session_state.active_session_id:
            return s
    # Active id got out of sync (e.g. after deleting the active session) --
    # fall back to the most recently created one.
    return st.session_state.chat_sessions[-1]


st.set_page_config(page_title="قاطب | المستشار الحواري", page_icon="💬", layout="wide")
apply_rtl_style()
render_sidebar_brand()
st.title("💬 المستشار التنظيمي الحواري")

settings = get_settings()
rag_engine = get_rag_engine()
llm_router = get_llm_router()
ASSISTANT_AVATAR = get_logo_path()

if "chat_sessions" not in st.session_state:
    # Persisted sessions survive a full page refresh, unlike bare
    # st.session_state which can reset on a new browser session. Discard
    # anything that isn't shaped like a session (e.g. history saved by an
    # older single-thread version of this page) instead of crashing on it.
    loaded = [
        s for s in load_history(HISTORY_KEY)
        if isinstance(s, dict) and "id" in s and "messages" in s
    ]
    st.session_state.chat_sessions = loaded or [_new_session()]
    st.session_state.active_session_id = st.session_state.chat_sessions[-1]["id"]

with st.sidebar:
    if st.button("➕ محادثة جديدة", use_container_width=True):
        session = _new_session()
        st.session_state.chat_sessions.append(session)
        st.session_state.active_session_id = session["id"]
        save_history(HISTORY_KEY, st.session_state.chat_sessions)
        st.rerun()

    st.markdown("**المحادثات السابقة**")
    for session in reversed(st.session_state.chat_sessions):
        label = session["title"] or "محادثة جديدة"
        prefix = "🟢 " if session["id"] == st.session_state.active_session_id else "💬 "
        if st.button(prefix + label, key=f"session_{session['id']}", use_container_width=True):
            st.session_state.active_session_id = session["id"]
            st.rerun()

    st.divider()
    if st.button("🗑️ حذف المحادثة الحالية", use_container_width=True):
        st.session_state.chat_sessions = [
            s for s in st.session_state.chat_sessions
            if s["id"] != st.session_state.active_session_id
        ]
        if not st.session_state.chat_sessions:
            st.session_state.chat_sessions = [_new_session()]
        st.session_state.active_session_id = st.session_state.chat_sessions[-1]["id"]
        save_history(HISTORY_KEY, st.session_state.chat_sessions)
        st.rerun()

active_session = _active_session()

for message in active_session["messages"]:
    avatar = ASSISTANT_AVATAR if message["role"] == "assistant" else None
    with st.chat_message(message["role"], avatar=avatar):
        render_bidi_markdown(message["content"])

if prompt := st.chat_input("اكتب استفسارك التنظيمي هنا..."):
    active_session["messages"].append({"role": "user", "content": prompt})
    if active_session["title"] is None:
        active_session["title"] = (prompt[:40] + "…") if len(prompt) > 40 else prompt
    with st.chat_message("user"):
        render_bidi_markdown(prompt)

    with st.chat_message("assistant", avatar=ASSISTANT_AVATAR):
        if rag_engine and llm_router:
            with st.spinner("جاري استخراج الإجابة..."):
                retrieved_docs = rag_engine.retrieve_context(
                    query=prompt, top_k=settings["rag"]["top_k"]
                )
                if retrieved_docs:
                    answer = llm_router.generate_regulatory_response(
                        query=prompt, retrieved_docs=retrieved_docs
                    )
                    render_bidi_markdown(answer)
                    active_session["messages"].append({"role": "assistant", "content": answer})
                    with st.expander("📚 المراجع والمصادر التشريعية المستخرجة"):
                        for i, doc in enumerate(retrieved_docs):
                            st.markdown(
                                f"**المصدر {i+1}: {doc.metadata.get('source')} "
                                f"(صفحة {doc.metadata.get('page_number')})**"
                            )
                else:
                    warning_msg = "لم أتمكن من العثور على تشريعات متعلقة بهذا الاستفسار."
                    st.warning(warning_msg)
                    active_session["messages"].append({"role": "assistant", "content": warning_msg})
        else:
            error_reason = st.session_state.get("engine_init_error", "سبب غير معروف.")
            error_msg = (
                "⚠️ تعذّر تهيئة محرك الذكاء الاصطناعي. يرجى التحقق من مفتاح "
                "GOOGLE_API_KEY في ملف .env ثم إعادة تشغيل التطبيق.\n\n"
                f"تفاصيل تقنية: `{error_reason}`"
            )
            st.error(error_msg)
            active_session["messages"].append({"role": "assistant", "content": error_msg})

    save_history(HISTORY_KEY, st.session_state.chat_sessions)
