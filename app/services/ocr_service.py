"""
OCR Service - Handwritten medical prescription text extraction.
Uses Tesseract OCR with OpenCV preprocessing optimized for handwritten text.
"""

import io
import logging
from typing import Optional, Tuple

import cv2
import numpy as np
import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)

TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png"}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png"}
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB

pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def _preprocess_image(image_array: np.ndarray) -> np.ndarray:
    """Apply OpenCV preprocessing for handwritten text."""
    if len(image_array.shape) == 3:
        gray = cv2.cvtColor(image_array, cv2.COLOR_BGR2GRAY)
    else:
        gray = image_array.copy()

    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    thresh = cv2.adaptiveThreshold(
        blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )
    kernel = np.ones((2, 2), np.uint8)
    morph = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    morph = cv2.morphologyEx(morph, cv2.MORPH_OPEN, kernel)
    return morph


def _validate_image(image_bytes: bytes) -> Tuple[bool, Optional[str]]:
    """Validate image is non-empty and readable."""
    if not image_bytes or len(image_bytes) == 0:
        return False, "Empty image data"
    if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
        return False, "Image size exceeds 10MB limit"
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()
    except Exception as e:
        logger.warning("Image validation failed: %s", e)
        return False, "Corrupted or invalid image"
    return True, None


def extract_text(image_bytes: bytes, content_type: Optional[str] = None) -> str:
    """
    Extract text from handwritten prescription image using Tesseract OCR.
    """
    valid, err = _validate_image(image_bytes)
    if not valid:
        raise ValueError(err or "Invalid image")

    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image")

    processed = _preprocess_image(img)
    config = "--oem 3 --psm 6"
    text = pytesseract.image_to_string(processed, lang="eng", config=config)
    return (text or "").strip()


def is_supported_file(filename: str, content_type: Optional[str] = None) -> bool:
    """Check if file type is supported."""
    ext_ok = False
    if filename and "." in filename:
        ext = "." + filename.rsplit(".", 1)[-1].lower()
        ext_ok = ext in ALLOWED_EXTENSIONS
    elif not filename:
        ext_ok = True

    ct_ok = True
    if content_type:
        ct_ok = content_type.lower() in ALLOWED_CONTENT_TYPES

    return ext_ok and ct_ok
