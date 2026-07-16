"""
Centralized, cached engine loader.

Previously, each Streamlit page redefined its own load_engines() function
with @st.cache_resource. Because each page module had a distinct function
object, Streamlit cached them independently -- resulting in duplicate
ChromaDB clients and duplicate embedding-model warm-ups.

Importing get_rag_engine() / get_llm_router() / get_report_generator()
from this single module ensures every page shares the SAME cached
instances.

Each getter returns None (instead of raising) on initialization failure
-- e.g. a missing/invalid GOOGLE_API_KEY -- so pages can show a friendly
Arabic error instead of Streamlit's raw traceback screen during a live
demo. The reason is logged and also stashed for the page to display.
"""

import logging
import os
import streamlit as st
from core.rag_engine import RegulatoryRAGEngine
from core.llm_router import RegulatoryLLMRouter
from core.report_generator import ComplianceReportGenerator
from core.audit_pipeline import ComplianceAuditPipeline
from core.document_parser import RegulatoryDocumentParser
from config.settings_loader import get_settings

logger = logging.getLogger(__name__)


def _index_is_empty(rag_engine: RegulatoryRAGEngine) -> bool:
    try:
        return len(rag_engine.vector_store.get(limit=1).get("ids", [])) == 0
    except Exception:
        return True


def _auto_build_index(rag_engine: RegulatoryRAGEngine) -> None:
    """Hosted deployments (e.g. Streamlit Community Cloud) rebuild the
    container from the git repo on every restart/redeploy -- data/vector_db
    is gitignored (build artifact) and won't survive that, unlike
    data/raw_documents (the source regulation PDFs), which IS committed.
    Self-heal by rebuilding the index from those PDFs on first load instead
    of requiring a manual `scripts/build_index.py` run post-deploy. No-op
    locally once a real index already exists."""
    settings = get_settings()
    parser = RegulatoryDocumentParser(
        chunk_size=settings["rag"]["chunk_size"], chunk_overlap=settings["rag"]["chunk_overlap"],
    )
    raw_dir = settings["paths"]["raw_documents"]
    if not os.path.isdir(raw_dir):
        logger.warning(f"Cannot auto-build index: {raw_dir} not found.")
        return
    for filename in os.listdir(raw_dir):
        if not filename.lower().endswith(".pdf"):
            continue
        file_path = os.path.join(raw_dir, filename)
        logger.info(f"Auto-indexing {filename} (empty vector store detected)...")
        chunks = parser.process_document(file_path)
        if chunks:
            rag_engine.index_documents(chunks)


@st.cache_resource(show_spinner="جاري تهيئة محرك الذكاء الاصطناعي...")
def get_rag_engine() -> RegulatoryRAGEngine | None:
    try:
        settings = get_settings()
        engine = RegulatoryRAGEngine(persist_directory=settings["paths"]["vector_db"])
        if _index_is_empty(engine):
            with st.spinner("جاري بناء قاعدة اللوائح التنظيمية لأول مرة (قد يستغرق ذلك دقيقة)..."):
                _auto_build_index(engine)
        return engine
    except Exception as e:
        logger.error(f"Failed to initialize RAG engine: {str(e)}")
        st.session_state["engine_init_error"] = str(e)
        return None


@st.cache_resource(show_spinner="جاري تهيئة المستشار التنظيمي...")
def get_llm_router() -> RegulatoryLLMRouter | None:
    try:
        settings = get_settings()
        return RegulatoryLLMRouter(
            model_name=settings["llm"]["model_name"],
            temperature=settings["llm"]["chat_temperature"],
        )
    except Exception as e:
        logger.error(f"Failed to initialize LLM router: {str(e)}")
        st.session_state["engine_init_error"] = str(e)
        return None


@st.cache_resource(show_spinner="جاري تهيئة مولد التقارير...")
def get_report_generator() -> ComplianceReportGenerator | None:
    try:
        settings = get_settings()
        return ComplianceReportGenerator(model_name=settings["llm"]["model_name"])
    except Exception as e:
        logger.error(f"Failed to initialize report generator: {str(e)}")
        st.session_state["engine_init_error"] = str(e)
        return None


@st.cache_resource(show_spinner=False)
def get_document_parser() -> RegulatoryDocumentParser:
    # Parsing needs no API key/network call, so it's kept independent of
    # get_audit_pipeline() -- a user can extract/preview an uploaded file's
    # text even if GOOGLE_API_KEY is missing; only running the actual audit
    # (Stage B) requires the AI engines.
    settings = get_settings()
    return RegulatoryDocumentParser(
        chunk_size=settings["rag"]["chunk_size"], chunk_overlap=settings["rag"]["chunk_overlap"],
    )


@st.cache_resource(show_spinner="جاري تهيئة محرك تدقيق الوثائق...")
def get_audit_pipeline() -> ComplianceAuditPipeline | None:
    try:
        rag_engine, llm_router = get_rag_engine(), get_llm_router()
        if not (rag_engine and llm_router):
            return None
        return ComplianceAuditPipeline(rag_engine=rag_engine, llm_router=llm_router)
    except Exception as e:
        logger.error(f"Failed to initialize audit pipeline: {str(e)}")
        st.session_state["engine_init_error"] = str(e)
        return None
