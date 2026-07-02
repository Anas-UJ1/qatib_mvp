"""
End-to-end smoke test for the Qatib RAG pipeline:

    PDF parsing -> chunking -> embedding/indexing -> vector retrieval
    -> Gemini chat routing -> risk-flagging -> STR generation

Runs against a throwaway ChromaDB directory (never touches the real
data/vector_db used for the live demo) and against one small real PDF
from data/raw_documents/. Requires a valid GOOGLE_API_KEY in .env --
this makes real Gemini API calls (a handful of small requests).

Usage:
    python scripts/test_pipeline.py
"""

import os
import sys
import shutil
import tempfile
import traceback

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

# Force UTF-8 stdout so Arabic text and status markers render on any
# Windows console codepage (e.g. cp1256) instead of raising
# UnicodeEncodeError mid-test.
sys.stdout.reconfigure(encoding="utf-8")

PASS = "[PASS]"
FAIL = "[FAIL]"
failures = []


def step(name):
    print(f"\n--- {name} ---")


def check(condition, description):
    mark = PASS if condition else FAIL
    print(f"{mark} {description}")
    if not condition:
        failures.append(description)
    return condition


def main():
    step("0. Environment")
    api_key = os.environ.get("GOOGLE_API_KEY", "").strip()
    if not check(bool(api_key), "GOOGLE_API_KEY is set and non-empty"):
        print("\nCannot continue without an API key. Aborting.")
        sys.exit(1)

    from core.document_parser import RegulatoryDocumentParser
    from core.rag_engine import RegulatoryRAGEngine
    from core.llm_router import RegulatoryLLMRouter
    from core.report_generator import ComplianceReportGenerator
    from config.settings_loader import get_settings

    settings = get_settings()
    raw_dir = settings["paths"]["raw_documents"]

    step("1. PDF discovery")
    pdf_files = sorted(f for f in os.listdir(raw_dir) if f.lower().endswith(".pdf"))
    check(len(pdf_files) > 0, f"Found {len(pdf_files)} PDF(s) in {raw_dir}")
    if not pdf_files:
        sys.exit(1)

    # Use the smallest file for a fast smoke test.
    target_file = min(
        pdf_files, key=lambda f: os.path.getsize(os.path.join(raw_dir, f))
    )
    print(f"    Using: {target_file}")

    step("2. Parsing + chunking")
    parser = RegulatoryDocumentParser(
        chunk_size=settings["rag"]["chunk_size"],
        chunk_overlap=settings["rag"]["chunk_overlap"],
    )
    chunks = parser.process_document(os.path.join(raw_dir, target_file))
    check(len(chunks) > 0, f"Produced {len(chunks)} chunks")
    check(
        all(c.metadata.get("source") and c.metadata.get("page_number") for c in chunks),
        "Every chunk carries source + page_number metadata",
    )

    step("3. Indexing into a throwaway vector DB")
    tmp_db_dir = tempfile.mkdtemp(prefix="qatib_test_vdb_")
    try:
        engine = RegulatoryRAGEngine(persist_directory=tmp_db_dir)
        engine.index_documents(chunks)
        count = engine.vector_store._collection.count()
        check(count == len(chunks), f"Vector store holds {count} rows (expected {len(chunks)})")

        step("3b. Idempotent re-indexing (dedup check)")
        engine.index_documents(chunks)
        count_after = engine.vector_store._collection.count()
        check(
            count_after == count,
            f"Re-indexing the same chunks kept row count at {count_after} (no duplicates)",
        )

        step("4. Vector retrieval")
        sample_query = "ما هي عقوبات مخالفة الأنظمة التنظيمية؟"
        retrieved = engine.retrieve_context(sample_query, top_k=settings["rag"]["top_k"])
        check(len(retrieved) > 0, f"Retrieved {len(retrieved)} chunk(s) for a sample query")

        step("5. Gemini chat routing (grounded Q&A)")
        router = RegulatoryLLMRouter(
            model_name=settings["llm"]["model_name"],
            temperature=settings["llm"]["chat_temperature"],
        )
        answer = router.generate_regulatory_response(sample_query, retrieved)
        check(bool(answer) and "خطأ" not in answer, "Received a non-error Arabic answer")
        print(f"    Answer preview: {answer[:120]}...")

        step("6. Compliance risk flagging")
        sample_transaction = (
            "قامت الشركة بتحويل مبلغ 500,000 ريال إلى حساب خارجي دون توثيق مصدر الأموال "
            "أو الغرض من التحويل، وذلك خلال يوم واحد من فتح الحساب."
        )
        risk_flags = router.analyze_compliance_risks(sample_transaction, retrieved)
        check(bool(risk_flags) and "خطأ" not in risk_flags, "Received a non-error risk analysis")

        step("7. STR generation")
        report_gen = ComplianceReportGenerator(model_name=settings["llm"]["model_name"])
        str_report = report_gen.generate_fiu_str(
            subject_name="منشأة تجريبية (اختبار)",
            transaction_type="تحويل بنكي دولي",
            anomaly_details=sample_transaction,
            llm_audit_findings=risk_flags,
        )
        check(bool(str_report) and "خطأ" not in str_report, "STR draft generated successfully")

    finally:
        shutil.rmtree(tmp_db_dir, ignore_errors=True)

    step("Summary")
    if failures:
        print(f"{FAIL} {len(failures)} check(s) failed:")
        for f in failures:
            print(f"   - {f}")
        sys.exit(1)
    else:
        print(f"{PASS} All checks passed. Pipeline is healthy end-to-end.")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print(f"\n{FAIL} Unhandled exception during pipeline test:")
        traceback.print_exc()
        sys.exit(1)
