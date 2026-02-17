"""
OCR API - Medical prescription image and document processing.
- Images: Vision-Language Model for handwritten prescription analysis.
- Documents: PDF, DOCX, TXT text extraction for prescription analysis.
"""

import logging
from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.services.document_extract_service import extract_text_from_document
from app.services.ocr_service import is_supported_file
from app.services.prescription_vision_service import process_prescription_image

logger = logging.getLogger(__name__)

router = APIRouter()

DOC_ALLOWED_EXT = {".pdf", ".docx", ".doc", ".txt"}


@router.post(
    "/extract-text",
    summary="Process prescription image (VLM-based)",
    description="Upload JPEG or PNG of handwritten prescription. Returns structured test list and availability.",
)
async def extract_prescription_text(
    file: UploadFile = File(..., description="Prescription image (JPEG, PNG)"),
) -> dict:
    content_type = file.content_type or ""
    filename = file.filename or ""

    if not is_supported_file(filename, content_type):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported file type. Only JPEG and PNG are allowed.",
        )

    try:
        image_bytes = await file.read()
    except Exception as e:
        logger.error("Failed to read uploaded file: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to read uploaded file.",
        )

    try:
        result = await run_in_threadpool(
            process_prescription_image, image_bytes, content_type
        )
    except ValueError as e:
        logger.warning("Image validation error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.exception("Prescription processing failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="فشل معالجة الصورة. يرجى التأكد من وضوح الصورة والمحاولة مرة أخرى.",
        )

    return {
        "success": result.get("success", True),
        "extracted_text": result.get("response_message", ""),
        "response_message": result.get("response_message", ""),
        "detected_tests": result.get("detected_tests", []),
        "available_tests": result.get("available_tests", []),
        "unavailable_tests": result.get("unavailable_tests", []),
        "contact_number": result.get("contact_number", "800-122-1220"),
        "language": "arabic",
        "type": "handwritten_prescription",
    }


def _is_doc_supported(filename: str) -> bool:
    ext = "." + (filename or "").rsplit(".", 1)[-1].lower() if "." in (filename or "") else ""
    return ext in DOC_ALLOWED_EXT


@router.post(
    "/extract-document",
    summary="Extract text from document (PDF, DOCX, TXT)",
    description="Upload PDF, DOCX, DOC, or TXT. Returns extracted text for prescription/analysis.",
)
async def extract_document_text(
    file: UploadFile = File(..., description="Document (PDF, DOCX, DOC, TXT)"),
) -> dict:
    filename = file.filename or ""
    if not _is_doc_supported(filename):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="صيغة غير مدعومة. استخدم PDF أو DOCX أو TXT.",
        )
    try:
        content = await file.read()
    except Exception as e:
        logger.error("Failed to read document: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="فشل قراءة الملف.",
        )
    try:
        text = await run_in_threadpool(
            extract_text_from_document, content, filename
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Document extraction failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="فشل استخراج النص من الملف. تأكد من أن الملف صالح.",
        )
    return {
        "success": True,
        "extracted_text": text,
        "response_message": text,
        "type": "document",
    }
