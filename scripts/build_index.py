"""
Standalone indexing script.

Walks data/raw_documents/, parses every PDF, and indexes the resulting
chunks into ChromaDB. Safe to re-run -- indexing is idempotent thanks to
the stable chunk IDs in core/rag_engine.py.

Usage:
    python scripts/build_index.py
"""

import os
import sys

# Force UTF-8 stdout so the Arabic status line renders on any Windows
# console codepage (e.g. cp1256) instead of raising UnicodeEncodeError.
sys.stdout.reconfigure(encoding="utf-8")

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.document_parser import RegulatoryDocumentParser
from core.rag_engine import RegulatoryRAGEngine
from config.settings_loader import get_settings


def main():
    settings = get_settings()
    parser = RegulatoryDocumentParser(
        chunk_size=settings["rag"]["chunk_size"],
        chunk_overlap=settings["rag"]["chunk_overlap"],
    )
    engine = RegulatoryRAGEngine(persist_directory=settings["paths"]["vector_db"])

    raw_dir = settings["paths"]["raw_documents"]
    if not os.path.isdir(raw_dir):
        print(f"[ERROR] Directory not found: {raw_dir}")
        sys.exit(1)

    pdf_files = [f for f in os.listdir(raw_dir) if f.lower().endswith(".pdf")]
    if not pdf_files:
        print(f"[WARN] No PDF files found in {raw_dir}. Add regulatory PDFs and re-run.")
        sys.exit(1)

    succeeded, failed = [], []
    for filename in pdf_files:
        file_path = os.path.join(raw_dir, filename)
        print(f"Processing: {filename}")
        chunks = parser.process_document(file_path)
        if chunks and engine.index_documents(chunks):
            succeeded.append(filename)
        else:
            failed.append(filename)

    print()
    print(f"[OK]   Indexed: {len(succeeded)}/{len(pdf_files)} file(s)")
    for f in succeeded:
        print(f"       - {f}")
    if failed:
        print(f"[FAIL] Failed to index: {len(failed)} file(s) -- see errors above")
        for f in failed:
            print(f"       - {f}")
        print("قاعدة البيانات الشعاعية غير مكتملة. راجع الأخطاء أعلاه قبل العرض.")
        sys.exit(1)

    print("تم بناء قاعدة البيانات الشعاعية بنجاح.")


if __name__ == "__main__":
    main()
