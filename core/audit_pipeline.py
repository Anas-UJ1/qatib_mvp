"""
Shared compliance-audit pipeline for Doc Review. Both the "paste text"
and "upload a file" input modes funnel through the same run() entry
point -- only chunk preparation differs by input mode -- so there is one
place that owns retrieval, structured extraction, dedup, and scoring.
"""

import logging
from typing import Callable, List, Optional, Tuple

from langchain.schema import Document

from core.document_parser import RegulatoryDocumentParser
from core.lang_utils import is_arabic_text
from core.llm_router import RegulatoryLLMRouter
from core.rag_engine import RegulatoryRAGEngine
from core.schemas import ComplianceAuditReport, RiskFlag, RiskSeverity
from config.settings_loader import get_settings

logger = logging.getLogger(__name__)

# Below this length, treat pasted text as a single chunk -- skips the
# chunk/retrieve/extract loop entirely for the common short
# transaction-description case, matching the original single-pass UX
# instead of over-engineering that path.
SINGLE_PASS_CHAR_THRESHOLD = 1500

_SEVERITY_ORDER = {RiskSeverity.HIGH: 3, RiskSeverity.MEDIUM: 2, RiskSeverity.LOW: 1}
_SEVERITY_WEIGHT = {RiskSeverity.HIGH: 30, RiskSeverity.MEDIUM: 15, RiskSeverity.LOW: 5}


class ComplianceAuditPipeline:
    def __init__(self, rag_engine: RegulatoryRAGEngine, llm_router: RegulatoryLLMRouter):
        self.rag_engine = rag_engine
        self.llm_router = llm_router
        settings = get_settings()
        self.parser = RegulatoryDocumentParser(
            chunk_size=settings["rag"]["chunk_size"],
            chunk_overlap=settings["rag"]["chunk_overlap"],
        )
        self.top_k = settings["rag"]["top_k"]

    def prepare_chunks(
        self, raw_text: str, source_documents: Optional[List[Document]] = None
    ) -> List[Document]:
        """source_documents: page/section-tagged chunks already produced by
        an uploaded-file parse. raw_text: fallback for the paste-text mode."""
        if source_documents:
            return self.parser.text_splitter.split_documents(source_documents)
        if len(raw_text) <= SINGLE_PASS_CHAR_THRESHOLD:
            return [Document(page_content=raw_text, metadata={"page_number": None, "source": "pasted_text"})]
        chunks = self.parser.text_splitter.split_text(raw_text)
        return [
            Document(page_content=c, metadata={"page_number": None, "source": "pasted_text"})
            for c in chunks
        ]

    def run(
        self,
        chunks: List[Document],
        regulatory_body_filter: Optional[str],
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> Tuple[ComplianceAuditReport, List[dict]]:
        lang = "ar" if is_arabic_text(" ".join(c.page_content for c in chunks[:3])) else "en"
        all_flags: List[RiskFlag] = []
        retrieved_sources: List[Document] = []

        # Sequential, not threaded/parallel: tenacity retry on
        # extract_chunk_risks absorbs transient 429s, but firing many
        # chunks concurrently risks simultaneous rate-limit errors right
        # before a demo. Fine to revisit if latency becomes a problem.
        for i, chunk in enumerate(chunks):
            if progress_cb:
                progress_cb(i + 1, len(chunks))
            location_label = self._location_label(chunk, lang)
            retrieved = self.rag_engine.retrieve_context(
                query=chunk.page_content[:500],
                top_k=self.top_k,
                regulatory_body=regulatory_body_filter,
            )
            if not retrieved:
                continue
            retrieved_sources.extend(retrieved)
            context_str = self.llm_router.format_context(retrieved)
            extraction = self.llm_router.extract_chunk_risks(context_str, chunk.page_content, location_label)
            for flag in extraction.flags:
                # The pipeline already knows the correct location -- don't
                # rely on the model faithfully echoing back the exact label
                # it was given (observed drift: appended extra commentary).
                flag.contract_reference = location_label
            all_flags.extend(extraction.flags)

        deduped = self._dedupe(all_flags)
        overall_severity = self._rollup_severity(deduped)
        score = self._risk_score(deduped)
        summary = self.llm_router.summarize_flags(deduped, lang) if deduped else self._no_findings_summary(lang)

        report = ComplianceAuditReport(
            overall_risk_score=score,
            overall_severity=overall_severity,
            summary=summary,
            flags=deduped,
            language=lang,
        )
        return report, self._dedupe_sources(retrieved_sources)

    @staticmethod
    def _location_label(chunk: Document, lang: str) -> str:
        page = chunk.metadata.get("page_number")
        if page is None:
            return "النص المُدخل" if lang == "ar" else "Pasted text"
        source = str(chunk.metadata.get("source", ""))
        is_docx = source.lower().endswith(".docx")
        if lang == "ar":
            return f"{'القسم' if is_docx else 'صفحة'} {page}"
        return f"{'Section' if is_docx else 'Page'} {page}"

    @staticmethod
    def _dedupe(flags: List[RiskFlag]) -> List[RiskFlag]:
        # Chunk overlap means the same violation can be re-detected across
        # adjacent chunks -- dedupe on a coarse key rather than pulling in
        # a fuzzy-matching dependency for a hackathon.
        seen, out = set(), []
        for f in flags:
            key = (
                f.severity,
                f.category.strip().lower(),
                (f.regulation_reference or "").strip().lower(),
                (f.contract_reference or "").strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            out.append(f)
        return out

    @staticmethod
    def _rollup_severity(flags: List[RiskFlag]) -> RiskSeverity:
        if not flags:
            return RiskSeverity.LOW
        return max((f.severity for f in flags), key=lambda s: _SEVERITY_ORDER[s])

    @staticmethod
    def _risk_score(flags: List[RiskFlag]) -> int:
        # Deterministic, auditable rollup -- not a second LLM call. Cheaper,
        # faster, and reproducible for the same flag set.
        return min(100, sum(_SEVERITY_WEIGHT[f.severity] for f in flags))

    @staticmethod
    def _dedupe_sources(docs: List[Document]) -> List[dict]:
        seen, out = set(), []
        for d in docs:
            key = (d.metadata.get("source"), d.metadata.get("page_number"))
            if key in seen:
                continue
            seen.add(key)
            out.append({"source": d.metadata.get("source"), "page": d.metadata.get("page_number")})
        return out

    @staticmethod
    def _no_findings_summary(lang: str) -> str:
        return (
            "لم يتم العثور على مخالفات صريحة أو مخاطر تنظيمية جوهرية."
            if lang == "ar"
            else "No explicit violations or material regulatory risks were found."
        )


def render_report_as_markdown(report: ComplianceAuditReport, source_filename: Optional[str] = None) -> str:
    """Renders a ComplianceAuditReport back down to the same markdown shape
    the old free-form audit_report used, so app/pages/3_Compliance_Gen.py
    (which consumes last_audit_findings / history['audit_report'] as a
    plain string) keeps working unmodified."""
    rtl = report.language == "ar"
    lines: List[str] = []

    if rtl:
        lines.append("**[المخاطر المكتشفة]**")
        lines.append(f"**درجة المخاطر الإجمالية:** {report.overall_risk_score}/100 ({report.overall_severity.value})")
        lines.append("")
        lines.append("**1. الملخص التنفيذي**")
        lines.append(report.summary)
        lines.append("")
        lines.append("**2. مؤشرات المخاطر التنظيمية**")
    else:
        lines.append("**[Anomalies Detected]**")
        lines.append(f"**Overall Risk Score:** {report.overall_risk_score}/100 ({report.overall_severity.value})")
        lines.append("")
        lines.append("**1. Executive Summary**")
        lines.append(report.summary)
        lines.append("")
        lines.append("**2. Regulatory Risk Flags**")

    if not report.flags:
        lines.append("-" if rtl else "None identified.")

    for idx, flag in enumerate(report.flags, start=1):
        lines.append(f"\n**{idx}. [{flag.severity.value}] {flag.category}**")
        lines.append(flag.description)
        if flag.regulation_source:
            ref = f" ({flag.regulation_reference})" if flag.regulation_reference else ""
            label = "المرجع التنظيمي" if rtl else "Regulatory reference"
            lines.append(f"- {label}: {flag.regulation_source}{ref}")
        if flag.contract_reference:
            label = "موقع الإشارة في الوثيقة" if rtl else "Document location"
            lines.append(f"- {label}: {flag.contract_reference}")
        if flag.recommendation:
            label = "التوصية" if rtl else "Recommendation"
            lines.append(f"- {label}: {flag.recommendation}")

    return "\n".join(lines)
