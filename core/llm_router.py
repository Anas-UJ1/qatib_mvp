import os
import logging
from typing import List
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain.schema import Document
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from config.system_prompts import REGTECH_CHAT_PROMPT, RISK_FLAG_PROMPT
from config.settings_loader import get_settings

load_dotenv()
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _require_api_key() -> None:
    if not os.environ.get("GOOGLE_API_KEY", "").strip():
        raise ValueError("Missing or empty Google API Key.")


# Retry only on transient/retryable errors. We deliberately do NOT retry
# on auth errors (invalid key, permission denied) since retrying those
# just burns time during a live demo without ever succeeding.
def _is_retryable(exc: Exception) -> bool:
    message = str(exc).lower()
    retryable_markers = ["429", "rate limit", "503", "timeout", "deadline exceeded", "unavailable"]
    return any(marker in message for marker in retryable_markers)


llm_retry = retry(
    wait=wait_exponential(min=1, max=10),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type(Exception),
    reraise=True,
)


class RegulatoryLLMRouter:
    def __init__(self, model_name: str = None, temperature: float = None):
        _require_api_key()
        settings = get_settings()

        resolved_model = model_name or settings["llm"]["model_name"]
        resolved_temp = temperature if temperature is not None else settings["llm"]["chat_temperature"]

        self.llm = ChatGoogleGenerativeAI(
            model=resolved_model,
            temperature=resolved_temp,
            max_tokens=settings["llm"]["max_output_tokens"],
        )

        # --- LCEL chains: prompt | llm | output_parser ---
        self.chat_prompt = PromptTemplate.from_template(REGTECH_CHAT_PROMPT)
        self.chat_chain = self.chat_prompt | self.llm | StrOutputParser()

        self.risk_prompt = PromptTemplate.from_template(RISK_FLAG_PROMPT)
        self.risk_chain = self.risk_prompt | self.llm | StrOutputParser()

        logger.info(f"LLM Router initialized using {resolved_model} (LCEL chains ready).")

    def _format_context(self, docs: List[Document]) -> str:
        formatted_chunks = []
        for i, doc in enumerate(docs):
            source = doc.metadata.get("source", "Unknown Source")
            page = doc.metadata.get("page_number", "N/A")
            formatted_chunks.append(f"[Chunk {i+1} | Source: {source} (Page {page})]\n{doc.page_content}")
        return "\n\n---\n\n".join(formatted_chunks)

    @llm_retry
    def _invoke_chat_chain(self, context_str: str, query: str) -> str:
        return self.chat_chain.invoke({"context": context_str, "query": query})

    @llm_retry
    def _invoke_risk_chain(self, context_str: str, input_data: str) -> str:
        return self.risk_chain.invoke({"context": context_str, "input_data": input_data})

    def generate_regulatory_response(self, query: str, retrieved_docs: List[Document]) -> str:
        logger.info("Generating Arabic regulatory response...")
        context_str = self._format_context(retrieved_docs)
        try:
            return self._invoke_chat_chain(context_str, query)
        except Exception as e:
            logger.error(f"Error during LLM inference after retries: {str(e)}")
            return "عذرًا، حدث خطأ أثناء معالجة الطلب. يرجى المحاولة مرة أخرى بعد قليل."

    def analyze_compliance_risks(self, input_data: str, retrieved_docs: List[Document]) -> str:
        logger.info("Auditing data for regulatory anomalies...")
        context_str = self._format_context(retrieved_docs)
        try:
            return self._invoke_risk_chain(context_str, input_data)
        except Exception as e:
            logger.error(f"Error during risk analysis after retries: {str(e)}")
            return "حدث خطأ أثناء تدقيق البيانات التنظيمية. يرجى المحاولة مرة أخرى بعد قليل."
