import os
import hashlib
import logging
from typing import List, Optional
from dotenv import load_dotenv
from chromadb.config import Settings as ChromaSettings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_chroma import Chroma
from langchain.schema import Document
from tenacity import retry, wait_exponential, stop_after_attempt

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _require_api_key() -> None:
    """Strict validation: key must exist AND be non-empty after stripping."""
    if not os.environ.get("GOOGLE_API_KEY", "").strip():
        logger.error("GOOGLE_API_KEY is missing or empty.")
        raise ValueError("Missing or empty Google API Key.")


# Embedding calls (both indexing and retrieval) hit the same Gemini API
# rate limits as chat calls, but previously had no retry protection --
# a live test confirmed a 429 here fails silently since index_documents()
# swallows exceptions. Same backoff policy as core/llm_router.py.
embedding_retry = retry(
    wait=wait_exponential(min=1, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)


def _make_chunk_id(source: str, page_number, content: str) -> str:
    """
    Deterministic, stable ID for a chunk based on its source file, page
    number, and content. Re-indexing the same document produces the same
    IDs, so Chroma's add_documents(..., ids=...) performs an UPSERT instead
    of creating duplicate rows.
    """
    raw_key = f"{source}::{page_number}::{content}"
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


class RegulatoryRAGEngine:
    def __init__(self, persist_directory: str = "data/vector_db"):
        self.persist_directory = persist_directory
        _require_api_key()

        # "models/embedding-004" does not exist (404 on embedContent) and
        # "models/embedding-001" / "models/text-embedding-004" have both been
        # retired by Google. "models/gemini-embedding-001" is the current,
        # live-verified embedding model as of this writing.
        self.embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001")
        self.vector_store = Chroma(
            collection_name="qatib_regulations",
            embedding_function=self.embeddings,
            persist_directory=self.persist_directory,
            # Chroma's posthog telemetry call signature drifts across
            # versions and spams "Failed to send telemetry event" to stderr
            # on every operation -- disable it so it doesn't look like a
            # crash during a live demo.
            # is_persistent=True is required here: chromadb.config.Settings
            # defaults to is_persistent=False, and passing client_settings
            # without it silently builds an in-memory-only client (data
            # looks indexed within the process but vanishes on exit) even
            # though persist_directory is also set.
            client_settings=ChromaSettings(anonymized_telemetry=False, is_persistent=True),
        )
        logger.info(f"RAG Engine initialized. Vector DB loaded from {self.persist_directory}")

    @embedding_retry
    def _add_documents_with_retry(self, documents: List[Document], ids: List[str]) -> None:
        self.vector_store.add_documents(documents, ids=ids)

    @embedding_retry
    def _similarity_search_with_retry(self, query: str, **search_kwargs) -> List[Document]:
        return self.vector_store.similarity_search(query, **search_kwargs)

    def index_documents(self, documents: List[Document]) -> bool:
        """Returns True on success, False on failure -- callers (e.g.
        scripts/build_index.py) need this to report an accurate summary
        instead of assuming success just because no exception propagated."""
        if not documents:
            logger.warning("No documents provided for indexing.")
            return False
        try:
            ids = [
                _make_chunk_id(
                    source=doc.metadata.get("source", "unknown"),
                    page_number=doc.metadata.get("page_number", "na"),
                    content=doc.page_content,
                )
                for doc in documents
            ]
            logger.info(
                f"Indexing {len(documents)} document chunks into ChromaDB (idempotent upsert)..."
            )
            self._add_documents_with_retry(documents, ids)
            logger.info("Indexing complete and persisted to disk.")
            return True
        except Exception as e:
            logger.error(f"Error during document indexing after retries: {str(e)}")
            return False

    def retrieve_context(
        self, query: str, top_k: int = 4, regulatory_body: Optional[str] = None
    ) -> List[Document]:
        logger.info(f"Querying Vector DB for: '{query}'")
        search_kwargs = {"k": top_k}
        if regulatory_body:
            search_kwargs["filter"] = {"regulatory_body": regulatory_body}
        try:
            results = self._similarity_search_with_retry(query, **search_kwargs)
            logger.info(f"Retrieved {len(results)} highly relevant chunks.")
            return results
        except Exception as e:
            logger.error(f"Error during retrieval after retries: {str(e)}")
            return []
