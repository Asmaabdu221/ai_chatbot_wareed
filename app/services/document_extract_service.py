"""
Document extraction service - Extract text from PDF, DOCX, TXT.
For prescription analysis from document files.
"""

import io
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ALLOWED_DOC_EXT = {".pdf", ".docx", ".doc", ".txt"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _extract_pdf(content: bytes) -> str:
    """Extract text from PDF using pypdf."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ValueError("pypdf غير مثبت. قم بتثبيته: pip install pypdf")
    reader = PdfReader(io.BytesIO(content))
    parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _extract_docx(content: bytes) -> str:
    """Extract text from DOCX using python-docx."""
    try:
        from docx import Document
    except ImportError:
        raise ValueError("python-docx غير مثبت. قم بتثبيته: pip install python-docx")
    doc = Document(io.BytesIO(content))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n".join(parts).strip()


def _extract_txt(content: bytes) -> str:
    """Extract text from plain text file."""
    try:
        return content.decode("utf-8").strip()
    except UnicodeDecodeError:
        try:
            return content.decode("cp1256").strip()
        except Exception:
            return content.decode("latin-1", errors="ignore").strip()


def extract_text_from_document(content: bytes, filename: str) -> str:
    """
    Extract text from document (PDF, DOCX, DOC, TXT).
    Returns extracted text or raises ValueError.
    """
    if not content or len(content) == 0:
        raise ValueError("الملف فارغ")
    if len(content) > MAX_FILE_SIZE:
        raise ValueError("حجم الملف يتجاوز 10 ميجابايت")
    ext = Path(filename or "").suffix.lower()
    if ext == ".pdf":
        text = _extract_pdf(content)
    elif ext in (".docx", ".doc"):
        text = _extract_docx(content)
    elif ext == ".txt":
        text = _extract_txt(content)
    else:
        raise ValueError("صيغة غير مدعومة. استخدم PDF أو DOCX أو TXT.")
    if not text or not text.strip():
        raise ValueError("لم يتم استخراج نص من الملف. تأكد من أن الملف يحتوي على نص.")
    return text.strip()
