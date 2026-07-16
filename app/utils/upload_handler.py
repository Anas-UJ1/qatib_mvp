"""
Security-sensitive glue between a Streamlit file_uploader widget and
core.document_parser.RegulatoryDocumentParser: extension whitelisting,
filename sanitization, and audit-trail storage under a UUID filename
(never the user-supplied name, to avoid path traversal/collisions).
"""

import os
import re
import uuid
from dataclasses import dataclass
from typing import List, Optional

from langchain.schema import Document

from core.document_parser import RegulatoryDocumentParser

UPLOAD_DIR = os.path.join("data", "uploaded_contracts")
ALLOWED_EXTENSIONS = {".pdf", ".docx"}


def sanitize_display_filename(filename: str) -> str:
    """Strip any directory components and control characters before a
    filename is ever displayed or stored as metadata."""
    name = os.path.basename(filename or "")
    name = re.sub(r"[\x00-\x1f\x7f]", "", name)
    return name[:200] or "uploaded_file"


@dataclass
class ParsedUpload:
    ok: bool
    error: Optional[str]
    documents: List[Document]
    stored_id: Optional[str]
    stored_path: Optional[str]
    original_filename: Optional[str]
    preview_text: str


def handle_uploaded_file(uploaded_file, parser: RegulatoryDocumentParser) -> ParsedUpload:
    """Validate, parse, and persist a Streamlit UploadedFile. Returns a
    ParsedUpload describing success/failure -- never raises on a bad file,
    so a malformed/malicious upload can't crash the app mid-demo."""
    ext = os.path.splitext(uploaded_file.name or "")[1].lower()
    display_name = sanitize_display_filename(uploaded_file.name)

    if ext not in ALLOWED_EXTENSIONS:
        return ParsedUpload(
            ok=False,
            error="نوع الملف غير مدعوم. يُسمح فقط بملفات PDF أو DOCX.",
            documents=[], stored_id=None, stored_path=None,
            original_filename=display_name, preview_text="",
        )

    file_bytes = uploaded_file.getvalue()
    if ext == ".pdf":
        documents = parser.extract_text_from_pdf_bytes(file_bytes, display_name)
    else:
        documents = parser.extract_text_from_docx_bytes(file_bytes, display_name)

    if not documents:
        return ParsedUpload(
            ok=False,
            error="تعذّر استخراج نص من الملف (قد يكون تالفًا أو فارغًا أو يتجاوز الحجم المسموح).",
            documents=[], stored_id=None, stored_path=None,
            original_filename=display_name, preview_text="",
        )

    # Audit-trail storage: UUID filename only -- the original filename is
    # kept solely as display metadata, never used to build a path on disk.
    stored_id = uuid.uuid4().hex
    stored_path = os.path.join(UPLOAD_DIR, f"{stored_id}{ext}")
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with open(stored_path, "wb") as f:
        f.write(file_bytes)

    preview = "\n\n".join(d.page_content for d in documents[:3])[:3000]
    return ParsedUpload(
        ok=True, error=None, documents=documents,
        stored_id=stored_id, stored_path=stored_path,
        original_filename=display_name, preview_text=preview,
    )
