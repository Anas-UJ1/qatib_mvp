import os
import logging
from datetime import datetime
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from tenacity import retry, wait_exponential, stop_after_attempt
from config.settings_loader import get_settings
from core.lang_utils import is_arabic_text

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _require_api_key() -> None:
    if not os.environ.get("GOOGLE_API_KEY", "").strip():
        raise ValueError("Missing or empty Google API Key.")


llm_retry = retry(
    wait=wait_exponential(min=1, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)

# The report's language previously defaulted to Arabic no matter what
# language the subject/transaction fields were typed in, because the
# prompt itself was one hardcoded Arabic template that the LLM just
# mimicked. Two full templates -- picked in Python from the actual input
# language -- fixes that deterministically.
STR_SYNTHESIS_PROMPT_AR = """You are an official Anti-Money Laundering (AML) Reporting Officer for a Saudi financial institution.
Synthesize the provided compliance anomalies into a formal, standardized Suspicious Transaction Report (STR).
The report must be entirely in professional Arabic. Ensure output uses Markdown formatting.

# مسودة تقرير اشتباه في تعاملات مالية (STR)
**تاريخ ومسببات التقرير:** {current_date}
**حالة التقرير:** مسودة أولية - بانتظار مراجعة واعتماد مسؤول الالتزام البشري

---
### أولاً: معلومات الجهة المبلغة
* **اسم المنصة:** قاطب للخدمات التنظيمية
* **نوع المنشأة:** متناهية الصغر / صغيرة / عمل حر

### ثانياً: تفاصيل أطراف التعاملات المشبوهة
* **الطرف المشتبه به:** {subject_name}

### ثالثاً: ملخص النشاط المالي والعمليات
* **نوع العمليات:** {transaction_type}
* **الوصف الفني للمؤشرات:**
{anomaly_details}

### رابعاً: التحليل التنظيمي ومسببات الاشتباه
{llm_audit_findings}

### خامساً: الإجراءات الاحترازية الموصى بها
1. تجميد مؤقت للتعاملات.
2. طلب وثائق إثبات الدخل.
"""

STR_SYNTHESIS_PROMPT_EN = """You are an official Anti-Money Laundering (AML) Reporting Officer for a Saudi financial institution.
Synthesize the provided compliance anomalies into a formal, standardized Suspicious Transaction Report (STR).
The report must be entirely in professional English. Ensure output uses Markdown formatting.

# Suspicious Transaction Report (STR) Draft
**Report Date & Basis:** {current_date}
**Report Status:** Initial Draft - Pending Human Compliance Officer Review & Approval

---
### I. Reporting Entity Information
* **Platform Name:** Qatib Regulatory Services
* **Entity Type:** Micro / Small / Freelance

### II. Suspicious Transaction Party Details
* **Subject of Suspicion:** {subject_name}

### III. Financial Activity & Transaction Summary
* **Transaction Type:** {transaction_type}
* **Technical Description of Indicators:**
{anomaly_details}

### IV. Regulatory Analysis & Grounds for Suspicion
{llm_audit_findings}

### V. Recommended Precautionary Measures
1. Temporary freeze on transactions.
2. Request proof-of-income documentation.
"""


class ComplianceReportGenerator:
    def __init__(self, model_name: str = None):
        _require_api_key()
        settings = get_settings()
        resolved_model = model_name or settings["llm"]["model_name"]

        self.llm = ChatGoogleGenerativeAI(
            model=resolved_model,
            temperature=settings["llm"]["report_temperature"],
        )

        # --- LCEL chains (one per language, picked at call time) ---
        self.chain_ar = PromptTemplate.from_template(STR_SYNTHESIS_PROMPT_AR) | self.llm | StrOutputParser()
        self.chain_en = PromptTemplate.from_template(STR_SYNTHESIS_PROMPT_EN) | self.llm | StrOutputParser()

    @llm_retry
    def _invoke_chain(self, chain, **kwargs) -> str:
        return chain.invoke(kwargs)

    def generate_fiu_str(
        self,
        subject_name: str,
        transaction_type: str,
        anomaly_details: str,
        llm_audit_findings: str,
    ) -> str:
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        combined_input = f"{subject_name} {transaction_type} {anomaly_details}"
        chain = self.chain_ar if is_arabic_text(combined_input) else self.chain_en
        try:
            return self._invoke_chain(
                chain,
                current_date=current_date,
                subject_name=subject_name,
                transaction_type=transaction_type,
                anomaly_details=anomaly_details,
                llm_audit_findings=llm_audit_findings,
            )
        except Exception as e:
            logger.error(f"Failed to generate STR after retries: {str(e)}")
            return "حدث خطأ أثناء صياغة تقرير الاشتباه التنظيمي. يرجى المحاولة مرة أخرى."
