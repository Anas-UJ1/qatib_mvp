import os
import re
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

_WHOLE_RESPONSE_CODE_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*\n(.*)\n```$", re.DOTALL)


def _strip_code_fence(text: str) -> str:
    """Gemini occasionally wraps an entire markdown response in a
    ```language ... ``` fence (observed e.g. with ```arabic). That defeats
    heading/bullet rendering (shown as literal '#'/'*' text instead of
    HTML) and can trip up the frontend's code-block syntax highlighter on
    an unrecognized language tag, rendering garbage. Strip a fence that
    wraps the WHOLE response; leave any fences used inside a longer
    answer alone."""
    if not text:
        return text
    match = _WHOLE_RESPONSE_CODE_FENCE_RE.match(text.strip())
    return match.group(1).strip() if match else text

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

CTR_SYNTHESIS_PROMPT_AR = """You are an official Anti-Money Laundering (AML) Reporting Officer for a Saudi financial institution.
Synthesize the provided cash transaction details into a formal, standardized Cash/Currency Transaction Report (CTR). A CTR is a ROUTINE filing triggered by the transaction amount itself, NOT by suspicion of wrongdoing -- do not imply the party did anything wrong unless the transaction details themselves state so.
The report must be entirely in professional Arabic. Ensure output uses Markdown formatting.

# مسودة تقرير معاملة نقدية (CTR)
**تاريخ ومسببات التقرير:** {current_date}
**حالة التقرير:** مسودة أولية - بانتظار مراجعة واعتماد مسؤول الالتزام البشري

---
### أولاً: معلومات الجهة المبلغة
* **اسم المنصة:** قاطب للخدمات التنظيمية
* **نوع المنشأة:** متناهية الصغر / صغيرة / عمل حر

### ثانياً: تفاصيل الطرف والمعاملة
* **اسم الطرف:** {subject_name}
* **قيمة المعاملة النقدية:** {transaction_amount} {currency}
* **تاريخ المعاملة:** {transaction_date}

### ثالثاً: وصف تفاصيل المعاملة النقدية
{transaction_details}

### رابعاً: الأساس التنظيمي للإبلاغ
{regulatory_context}

### خامساً: الإجراءات الموصى بها
1. توثيق مصدر الأموال النقدية.
2. رفع التقرير لوحدة التحريات المالية خلال المهلة النظامية المقررة لمعاملات نقدية بهذا الحجم.
"""

CTR_SYNTHESIS_PROMPT_EN = """You are an official Anti-Money Laundering (AML) Reporting Officer for a Saudi financial institution.
Synthesize the provided cash transaction details into a formal, standardized Cash/Currency Transaction Report (CTR). A CTR is a ROUTINE filing triggered by the transaction amount itself, NOT by suspicion of wrongdoing -- do not imply the party did anything wrong unless the transaction details themselves state so.
The report must be entirely in professional English. Ensure output uses Markdown formatting.

# Cash/Currency Transaction Report (CTR) Draft
**Report Date & Basis:** {current_date}
**Report Status:** Initial Draft - Pending Human Compliance Officer Review & Approval

---
### I. Reporting Entity Information
* **Platform Name:** Qatib Regulatory Services
* **Entity Type:** Micro / Small / Freelance

### II. Party & Transaction Details
* **Party Name:** {subject_name}
* **Cash Transaction Amount:** {transaction_amount} {currency}
* **Transaction Date:** {transaction_date}

### III. Transaction Detail Description
{transaction_details}

### IV. Regulatory Basis for Reporting
{regulatory_context}

### V. Recommended Actions
1. Document the source of the cash funds.
2. File the report with the Financial Intelligence Unit within the statutory deadline for a cash transaction of this size.
"""

SDAIA_BREACH_PROMPT_AR = """You are an official Data Protection Officer responsible for regulatory notifications under the Saudi Personal Data Protection Law (PDPL), enforced by SDAIA.
Synthesize the provided incident details into a formal data breach notification addressed to SDAIA, grounded strictly in the retrieved PDPL context below.
The report must be entirely in professional Arabic. Ensure output uses Markdown formatting.

# مسودة إخطار خرق بيانات شخصية (SDAIA)
**تاريخ ومسببات الإخطار:** {current_date}
**حالة الإخطار:** مسودة أولية - بانتظار مراجعة واعتماد مسؤول حماية البيانات

---
### أولاً: معلومات الجهة المبلغة
* **اسم المنصة:** قاطب للخدمات التنظيمية

### ثانياً: وصف الحادثة
{incident_description}

### ثالثاً: فئات البيانات المتأثرة وعدد الأفراد
* **فئات البيانات:** {data_categories_affected}
* **عدد الأفراد المتأثرين:** {affected_individuals_count}
* **تاريخ اكتشاف الحادثة:** {discovery_date}

### رابعاً: إجراءات الاحتواء المتخذة
{containment_measures}

### خامساً: المتطلبات التنظيمية ذات الصلة (وفق نظام حماية البيانات الشخصية)
{regulatory_context}

### سادساً: الإجراءات الموصى بها
1. إخطار الأفراد المتأثرين إن اقتضت الحاجة النظامية ذلك.
2. توثيق الحادثة ضمن سجل حوادث خرق البيانات الداخلي.
"""

SDAIA_BREACH_PROMPT_EN = """You are an official Data Protection Officer responsible for regulatory notifications under the Saudi Personal Data Protection Law (PDPL), enforced by SDAIA.
Synthesize the provided incident details into a formal data breach notification addressed to SDAIA, grounded strictly in the retrieved PDPL context below.
The report must be entirely in professional English. Ensure output uses Markdown formatting.

# Personal Data Breach Notification (SDAIA) Draft
**Notification Date & Basis:** {current_date}
**Notification Status:** Initial Draft - Pending Data Protection Officer Review & Approval

---
### I. Reporting Entity Information
* **Platform Name:** Qatib Regulatory Services

### II. Incident Description
{incident_description}

### III. Affected Data Categories & Individuals
* **Data Categories:** {data_categories_affected}
* **Number of Affected Individuals:** {affected_individuals_count}
* **Discovery Date:** {discovery_date}

### IV. Containment Measures Taken
{containment_measures}

### V. Relevant Regulatory Requirements (per PDPL)
{regulatory_context}

### VI. Recommended Actions
1. Notify affected individuals if required by law.
2. Log the incident in the internal data breach register.
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

        self.ctr_chain_ar = PromptTemplate.from_template(CTR_SYNTHESIS_PROMPT_AR) | self.llm | StrOutputParser()
        self.ctr_chain_en = PromptTemplate.from_template(CTR_SYNTHESIS_PROMPT_EN) | self.llm | StrOutputParser()

        self.sdaia_chain_ar = PromptTemplate.from_template(SDAIA_BREACH_PROMPT_AR) | self.llm | StrOutputParser()
        self.sdaia_chain_en = PromptTemplate.from_template(SDAIA_BREACH_PROMPT_EN) | self.llm | StrOutputParser()

    @llm_retry
    def _invoke_chain(self, chain, **kwargs) -> str:
        return _strip_code_fence(chain.invoke(kwargs))

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

    def generate_ctr(
        self,
        subject_name: str,
        transaction_amount: str,
        currency: str,
        transaction_date: str,
        transaction_details: str,
        regulatory_context: str = "",
    ) -> str:
        """A CTR is a routine, threshold-triggered filing -- unlike an STR,
        it does NOT require a prior Doc Review 'suspicion' finding.
        regulatory_context is optional supporting material (e.g. retrieved
        SAMA cash-reporting-threshold rules), not a suspicion finding."""
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        combined_input = f"{subject_name} {transaction_details}"
        chain = self.ctr_chain_ar if is_arabic_text(combined_input) else self.ctr_chain_en
        try:
            return self._invoke_chain(
                chain,
                current_date=current_date,
                subject_name=subject_name,
                transaction_amount=transaction_amount,
                currency=currency,
                transaction_date=transaction_date,
                transaction_details=transaction_details,
                regulatory_context=regulatory_context or "-",
            )
        except Exception as e:
            logger.error(f"Failed to generate CTR after retries: {str(e)}")
            return "حدث خطأ أثناء صياغة تقرير المعاملة النقدية. يرجى المحاولة مرة أخرى."

    def generate_sdaia_breach_notification(
        self,
        incident_description: str,
        data_categories_affected: str,
        affected_individuals_count: str,
        discovery_date: str,
        containment_measures: str,
        regulatory_context: str = "",
    ) -> str:
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        chain = self.sdaia_chain_ar if is_arabic_text(incident_description) else self.sdaia_chain_en
        try:
            return self._invoke_chain(
                chain,
                current_date=current_date,
                incident_description=incident_description,
                data_categories_affected=data_categories_affected,
                affected_individuals_count=affected_individuals_count,
                discovery_date=discovery_date,
                containment_measures=containment_measures,
                regulatory_context=regulatory_context or "-",
            )
        except Exception as e:
            logger.error(f"Failed to generate SDAIA breach notification after retries: {str(e)}")
            return "حدث خطأ أثناء صياغة إخطار خرق البيانات. يرجى المحاولة مرة أخرى."
