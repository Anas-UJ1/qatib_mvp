# قاطب (Qatib) — منصة الامتثال التنظيمي الذكية

لتجربة المنصة بشكل كامل:
https://amad-qtib.streamlit.app/

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
