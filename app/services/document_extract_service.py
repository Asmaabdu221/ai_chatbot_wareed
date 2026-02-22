"""
Document extraction service - Extract text from PDF, DOCX, TXT.
For prescription analysis from document files.
"""

import io
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ALLOWED_DOC_EXT = {".pdf", ".docx", ".doc", ".txt"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def _extract_pdf(content: bytes) -> str:
    """Extract text from PDF using pypdf."""
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ValueError("PDF processing is currently unavailable. Please try again later.")

    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        logger.warning("Failed to parse PDF: %s", exc)
        raise ValueError("Failed to read the PDF file. Please upload a valid PDF.")

    parts = []
    for page in reader.pages:
        try:
            text = page.extract_text()
        except Exception as exc:
            logger.warning("Failed to extract text from PDF page: %s", exc)
            continue
        if text:
            parts.append(text)
    return "\n".join(parts).strip()


def _extract_docx(content: bytes) -> str:
    """Extract text from DOCX using python-docx."""
    try:
        from docx import Document
    except ImportError:
        raise ValueError("DOCX processing is currently unavailable. Please try again later.")

    try:
        doc = Document(io.BytesIO(content))
    except Exception as exc:
        logger.warning("Failed to parse DOCX: %s", exc)
        raise ValueError("Failed to read the document file. Please upload a valid DOCX file.")

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
        raise ValueError("The uploaded file is empty.")
    if len(content) > MAX_FILE_SIZE:
        raise ValueError("File size exceeds 10 MB.")

    ext = Path(filename or "").suffix.lower()
    if ext == ".pdf":
        text = _extract_pdf(content)
    elif ext in (".docx", ".doc"):
        text = _extract_docx(content)
    elif ext == ".txt":
        text = _extract_txt(content)
    else:
        raise ValueError("Unsupported file format. Use PDF, DOCX, DOC, or TXT.")

    if not text or not text.strip():
        raise ValueError("No text could be extracted from the file. Ensure the file contains selectable text.")

    return text.strip()