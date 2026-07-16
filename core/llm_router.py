import os
import json
import logging
import re
from typing import List
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser, PydanticOutputParser
from langchain.schema import Document
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type
from config.system_prompts import (
    REGTECH_CHAT_PROMPT,
    RISK_FLAG_PROMPT,
    CONTRACT_CHUNK_RISK_EXTRACTION_PROMPT,
    FLAG_SUMMARY_PROMPT,
    KYC_RISK_ASSESSMENT_PROMPT,
)
from config.settings_loader import get_settings
from core.schemas import ChunkRiskExtraction, KYCRiskProfile

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

_SENTENCE_END_CHARS = set(".!?؟…\"'”’)»")


def _text_ends_cleanly(text: str) -> bool:
    """Heuristic: a genuinely-finished piece of generated prose almost
    always ends on sentence-terminating punctuation. A truncated
    generation cuts off mid-word/mid-clause instead, with no such
    trailing character."""
    if not text:
        return True
    tail = text.rstrip()
    return not tail or tail[-1] in _SENTENCE_END_CHARS


def _flags_look_complete(extraction: ChunkRiskExtraction) -> bool:
    return all(
        _text_ends_cleanly(flag.description) and _text_ends_cleanly(flag.recommendation)
        for flag in extraction.flags
    )


def _kyc_profile_looks_complete(profile: KYCRiskProfile) -> bool:
    return _text_ends_cleanly(profile.summary)


_WHOLE_RESPONSE_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n(.*)\n```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Gemini occasionally wraps an entire markdown response in a
    ```language ... ``` fence (observed e.g. with ```arabic). That defeats
    heading/bullet rendering and can trip up the frontend's code-block
    syntax highlighter on an unrecognized language tag. Strip a fence
    that wraps the WHOLE response; leave fences used inside a longer
    answer alone."""
    if not text:
        return text
    match = _WHOLE_RESPONSE_CODE_FENCE_RE.match(text.strip())
    return match.group(1).strip() if match else text


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

        # --- Structured per-chunk risk extraction (Doc Review upload flow) ---
        self.structured_risk_prompt = PromptTemplate.from_template(CONTRACT_CHUNK_RISK_EXTRACTION_PROMPT)
        self._structured_llm = self.llm.with_structured_output(ChunkRiskExtraction, include_raw=True)
        self.structured_risk_chain = self.structured_risk_prompt | self._structured_llm

        # Fallback path if native structured/tool-call output comes back
        # empty (model- or version-dependent flakiness) -- same prompt,
        # explicit JSON-format instructions, parsed with Pydantic instead
        # of relying on function-calling.
        self._fallback_parser = PydanticOutputParser(pydantic_object=ChunkRiskExtraction)
        self._fallback_prompt = PromptTemplate(
            template=CONTRACT_CHUNK_RISK_EXTRACTION_PROMPT + "\n\n{format_instructions}",
            input_variables=["context", "input_data", "contract_location_label"],
            partial_variables={"format_instructions": self._fallback_parser.get_format_instructions()},
        )
        self._fallback_chain = self._fallback_prompt | self.llm | self._fallback_parser

        self.summary_prompt = PromptTemplate.from_template(FLAG_SUMMARY_PROMPT)
        self.summary_chain = self.summary_prompt | self.llm | StrOutputParser()

        # --- Structured KYC/CDD risk assessment (Compliance Gen) ---
        self.kyc_prompt = PromptTemplate.from_template(KYC_RISK_ASSESSMENT_PROMPT)
        self._structured_kyc_llm = self.llm.with_structured_output(KYCRiskProfile, include_raw=True)
        self.structured_kyc_chain = self.kyc_prompt | self._structured_kyc_llm

        self._kyc_fallback_parser = PydanticOutputParser(pydantic_object=KYCRiskProfile)
        self._kyc_fallback_prompt = PromptTemplate(
            template=KYC_RISK_ASSESSMENT_PROMPT + "\n\n{format_instructions}",
            input_variables=["context", "customer_profile_text", "customer_name"],
            partial_variables={"format_instructions": self._kyc_fallback_parser.get_format_instructions()},
        )
        self._kyc_fallback_chain = self._kyc_fallback_prompt | self.llm | self._kyc_fallback_parser

        logger.info(f"LLM Router initialized using {resolved_model} (LCEL chains ready).")

    def format_context(self, docs: List[Document]) -> str:
        formatted_chunks = []
        for i, doc in enumerate(docs):
            source = doc.metadata.get("source", "Unknown Source")
            page = doc.metadata.get("page_number", "N/A")
            formatted_chunks.append(f"[Chunk {i+1} | Source: {source} (Page {page})]\n{doc.page_content}")
        return "\n\n---\n\n".join(formatted_chunks)

    @llm_retry
    def _invoke_chat_chain(self, context_str: str, query: str) -> str:
        return _strip_code_fence(self.chat_chain.invoke({"context": context_str, "query": query}))

    @llm_retry
    def _invoke_risk_chain(self, context_str: str, input_data: str) -> str:
        return _strip_code_fence(self.risk_chain.invoke({"context": context_str, "input_data": input_data}))

    def generate_regulatory_response(self, query: str, retrieved_docs: List[Document]) -> str:
        logger.info("Generating Arabic regulatory response...")
        context_str = self.format_context(retrieved_docs)
        try:
            return self._invoke_chat_chain(context_str, query)
        except Exception as e:
            logger.error(f"Error during LLM inference after retries: {str(e)}")
            return "عذرًا، حدث خطأ أثناء معالجة الطلب. يرجى المحاولة مرة أخرى بعد قليل."

    def analyze_compliance_risks(self, input_data: str, retrieved_docs: List[Document]) -> str:
        logger.info("Auditing data for regulatory anomalies...")
        context_str = self.format_context(retrieved_docs)
        try:
            return self._invoke_risk_chain(context_str, input_data)
        except Exception as e:
            logger.error(f"Error during risk analysis after retries: {str(e)}")
            return "حدث خطأ أثناء تدقيق البيانات التنظيمية. يرجى المحاولة مرة أخرى بعد قليل."

    def _attempt_chunk_extraction(
        self, context_str: str, input_data: str, contract_location_label: str
    ) -> ChunkRiskExtraction:
        """One attempt at structured risk extraction, trying native
        structured/tool-call output first and falling back to a
        PydanticOutputParser + prompt-enforced-JSON path if the model
        returns no parsed result."""
        try:
            result = self.structured_risk_chain.invoke({
                "context": context_str,
                "input_data": input_data,
                "contract_location_label": contract_location_label,
            })
            parsed = result.get("parsed")
            raw_msg = result.get("raw")
            finish_reason = (getattr(raw_msg, "response_metadata", None) or {}).get("finish_reason")
            # gemini-2.5-flash's internal "thinking" tokens count against
            # max_output_tokens and vary run to run -- a MAX_TOKENS cutoff
            # can still leave a *syntactically* parseable but truncated
            # tool-call payload (e.g. a description cut mid-sentence).
            # Treat that as a failure rather than silently keep it.
            if parsed is not None and finish_reason != "MAX_TOKENS":
                return parsed
            logger.warning(
                f"Structured tool-call for {contract_location_label} was empty or truncated "
                f"(finish_reason={finish_reason}); falling back to JSON-mode parsing."
            )
        except Exception as e:
            logger.warning(f"with_structured_output failed for {contract_location_label}: {e}; falling back.")

        return self._fallback_chain.invoke({
            "context": context_str,
            "input_data": input_data,
            "contract_location_label": contract_location_label,
        })

    @llm_retry
    def extract_chunk_risks(
        self, context_str: str, input_data: str, contract_location_label: str
    ) -> ChunkRiskExtraction:
        """Structured risk extraction for ONE contract chunk (the 'map'
        step of the Doc Review chunked map-reduce pipeline).

        Observed in testing: gemini-2.5-flash's tool-call generation can
        self-terminate mid-sentence (finish_reason legitimately 'STOP',
        not a token-budget issue) on a small fraction of calls, especially
        for longer Arabic text -- e.g. a description cut off mid-word.
        That's a genuinely bad result for a compliance report, so a single
        bounded retry is attempted whenever the text looks incomplete
        (doesn't end on sentence-terminating punctuation).
        """
        extraction = self._attempt_chunk_extraction(context_str, input_data, contract_location_label)
        if not _flags_look_complete(extraction):
            logger.warning(
                f"Flag text for {contract_location_label} looks truncated "
                f"(no terminal punctuation); retrying once."
            )
            extraction = self._attempt_chunk_extraction(context_str, input_data, contract_location_label)
        return extraction

    @llm_retry
    def summarize_flags(self, flags: list, language: str) -> str:
        """Synthesize an executive summary across all flags found (the
        'reduce' step). language is 'ar' or 'en'."""
        flags_json = json.dumps([f.model_dump(mode="json") for f in flags], ensure_ascii=False)
        lang_label = "Arabic" if language == "ar" else "English"
        return _strip_code_fence(self.summary_chain.invoke({"flags_json": flags_json, "language": lang_label}))

    def _attempt_kyc_assessment(
        self, context_str: str, customer_profile_text: str, customer_name: str
    ) -> KYCRiskProfile:
        """One attempt at structured KYC risk assessment -- same
        native-structured-output-first, fallback-to-JSON-mode shape as
        _attempt_chunk_extraction."""
        try:
            result = self.structured_kyc_chain.invoke({
                "context": context_str,
                "customer_profile_text": customer_profile_text,
                "customer_name": customer_name,
            })
            parsed = result.get("parsed")
            raw_msg = result.get("raw")
            finish_reason = (getattr(raw_msg, "response_metadata", None) or {}).get("finish_reason")
            if parsed is not None and finish_reason != "MAX_TOKENS":
                return parsed
            logger.warning(
                f"Structured KYC tool-call for '{customer_name}' was empty or truncated "
                f"(finish_reason={finish_reason}); falling back to JSON-mode parsing."
            )
        except Exception as e:
            logger.warning(f"with_structured_output failed for KYC assessment of '{customer_name}': {e}; falling back.")

        return self._kyc_fallback_chain.invoke({
            "context": context_str,
            "customer_profile_text": customer_profile_text,
            "customer_name": customer_name,
        })

    @llm_retry
    def assess_kyc_risk(
        self, context_str: str, customer_profile_text: str, customer_name: str
    ) -> KYCRiskProfile:
        """Structured KYC/CDD risk assessment for one customer profile,
        grounded in retrieved SAMA KYC/CDD context. Retries once if the
        summary looks truncated, same heuristic as extract_chunk_risks."""
        profile = self._attempt_kyc_assessment(context_str, customer_profile_text, customer_name)
        if not _kyc_profile_looks_complete(profile):
            logger.warning(f"KYC summary for '{customer_name}' looks truncated; retrying once.")
            profile = self._attempt_kyc_assessment(context_str, customer_profile_text, customer_name)
        return profile
