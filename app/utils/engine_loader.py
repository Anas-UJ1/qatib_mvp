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
import streamlit as st
from core.rag_engine import RegulatoryRAGEngine
from core.llm_router import RegulatoryLLMRouter
from core.report_generator import ComplianceReportGenerator
from config.settings_loader import get_settings

logger = logging.getLogger(__name__)


@st.cache_resource(show_spinner="جاري تهيئة محرك الذكاء الاصطناعي...")
def get_rag_engine() -> RegulatoryRAGEngine | None:
    try:
        settings = get_settings()
        return RegulatoryRAGEngine(persist_directory=settings["paths"]["vector_db"])
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
