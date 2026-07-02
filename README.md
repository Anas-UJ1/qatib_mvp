# قاطب (Qatib) — منصة الامتثال التنظيمي الذكية

مساعد حواري ذكي مبني على تقنية RAG، يهدف لمساعدة الشركات الصغيرة والمستقلين في السعودية على
فهم تشريعات SAMA و ZATCA و CMA و SDAIA، وكشف المخاطر التنظيمية، وتوليد مسودات تقارير الامتثال.

> ⚠️ **MVP Disclaimer**: هذه نسخة تجريبية (Human-in-the-Loop). جميع المخرجات يجب مراجعتها
> واعتمادها من قبل مسؤول امتثال بشري معتمد قبل أي استخدام رسمي.

---

## التشغيل السريع

```bash
# Use Python 3.10 or 3.11 -- see the note at the top of requirements.txt
# (Python 3.12 fails to install chromadb on Windows without a C++ compiler).
py -3.11 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\Activate.ps1

pip install --upgrade pip
pip install -r requirements.txt

cp .env.example .env            # ثم أدخل GOOGLE_API_KEY الخاص بك

# ضع ملفات PDF التنظيمية داخل data/raw_documents/ ثم:
python scripts/build_index.py

streamlit run app/main.py
```

سيفتح التطبيق على: `http://localhost:8501`

---

## ما الذي تم إصلاحه في هذه النسخة

| # | الإصلاح | الملف |
|---|---|---|
| 1 | `unsafe_with_html` → `unsafe_allow_html` | جميع صفحات Streamlit (الآن مركزية عبر `ui_components.py`) |
| 2 | `st.form_submit_submit_button` → `st.form_submit_button` | `3_📑_Compliance_Gen.py` |
| 3 | تحميل محركات RAG/LLM مركزي ومشترك (لا تكرار) | `app/utils/engine_loader.py` |
| 4 | مسح حالة الجلسة القديمة قبل كل تدقيق جديد | `2_📄_Doc_Review.py` |
| 5 | اسم النموذج مركزي في `settings.yaml` | `config/settings_loader.py` |
| 6 | تقطيع نصوص محسّن لحدود المواد القانونية العربية | `core/document_parser.py` |
| 7 | فهرسة متكررة بدون تكرار بيانات (idempotent) | `core/rag_engine.py` |
| 8 | `top_k=4` موحّد عبر كل الملفات | `config/settings.yaml` |
| 9 | حد أقصى لحجم الملفات المرفوعة (25MB) | `core/document_parser.py` |
| 10 | تحقق صارم من مفتاح API | جميع ملفات `core/` |
| 11 | إعادة محاولة تلقائية (retry) عند تجاوز حدود الاستخدام | `tenacity` في `llm_router.py` و `report_generator.py` |
| 12 | تحويل سلاسل LLM إلى صيغة LCEL الحديثة | `core/llm_router.py`, `core/report_generator.py` |

---

## خارطة الطريق (Post-Hackathon)

- طبقة إخفاء الهوية (PII Anonymization) قبل إرسال البيانات لأي API خارجي
- إعادة الترتيب (Reranking) لتحسين دقة الاسترجاع
- دعم تعدد المستخدمين وعزل بيانات كل منشأة (Multi-tenancy)
