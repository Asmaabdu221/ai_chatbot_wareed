"""
Prescription Vision Service - VLM-based handwritten prescription processing.
Uses OpenAI Vision API to extract medical test names from prescription images.
"""

import base64
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from openai import OpenAI
from rapidfuzz import fuzz

from app.core.config import settings
from app.data.knowledge_loader_v2 import get_knowledge_base

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/jpg", "image/png"}
MAX_IMAGE_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
VISION_MODEL = getattr(settings, "OPENAI_VISION_MODEL", "gpt-4o")
WAREED_CONTACT = "800-122-1220"

VISION_PROMPT = """You are a medical prescription analyzer. Analyze this handwritten prescription image and extract ALL medical test/lab test names mentioned.

Return ONLY valid JSON in this exact format (no markdown, no explanation):
{
  "detected_tests": [
    {
      "original_text": "exact text as written in the prescription",
      "normalized_name": "standardized test name in English (e.g. Vitamin D, CBC, TSH)",
      "confidence": 0.0
    }
  ]
}

Rules:
- Extract every lab test, analysis, or investigation mentioned.
- normalized_name: use common medical abbreviations (CBC, TSH, HbA1c) or full names (Vitamin D, Complete Blood Count).
- confidence: 0.0 to 1.0 based on legibility (1.0 = very clear, 0.5 = uncertain, 0.3 = barely readable).
- If no tests are visible, return: {"detected_tests": []}
- Return ONLY the JSON object, nothing else."""


def _validate_image(image_bytes: bytes) -> Tuple[bool, Optional[str]]:
    if not image_bytes or len(image_bytes) == 0:
        return False, "Empty image data"
    if len(image_bytes) > MAX_IMAGE_SIZE_BYTES:
        return False, "Image size exceeds 10MB limit"
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return False, "Failed to decode image"
    except Exception as e:
        logger.warning("Image validation failed: %s", e)
        return False, "Corrupted or invalid image"
    return True, None


def _deskew(img: np.ndarray) -> np.ndarray:
    """Auto-rotate to correct skew using Hough lines."""
    try:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        edges = cv2.Canny(gray, 50, 150)
        lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 100, minLineLength=50, maxLineGap=10)
        if lines is None or len(lines) < 5:
            return img
        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if abs(x2 - x1) > 5:
                angles.append(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
        if not angles:
            return img
        median_angle = np.median(angles)
        if abs(median_angle) < 0.5:
            return img
        h, w = img.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), median_angle, 1.0)
        return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    except Exception:
        return img


def preprocess_image(image_bytes: bytes) -> bytes:
    """Preprocess: deskew, contrast, grayscale, denoise."""
    try:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            return image_bytes

        img = _deskew(img)
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        gray = cv2.bilateralFilter(gray, 9, 75, 75)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
        # No binarization - VLMs read handwritten text better from grayscale with contrast

        _, buf = cv2.imencode(".png", gray)
        return buf.tobytes()
    except Exception as e:
        logger.warning("Preprocessing failed, using original: %s", e)
        return image_bytes


def _parse_vision_response(raw: str) -> Dict[str, Any]:
    raw = (raw or "").strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"detected_tests": []}


def _extract_tests_via_vision(image_bytes: bytes) -> List[Dict[str, Any]]:
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    mime = "image/png" if (len(image_bytes) >= 8 and image_bytes[:8] == b"\x89PNG\r\n\x1a\n") else "image/jpeg"

    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                ],
            }
        ],
        max_tokens=1024,
        temperature=0.1,
    )
    text = response.choices[0].message.content or ""
    parsed = _parse_vision_response(text)
    return parsed.get("detected_tests", [])


def _match_test(normalized_name: str, min_score: int = 55) -> Optional[Dict[str, Any]]:
    kb = get_knowledge_base()
    if not kb.tests:
        return None
    query = normalized_name.strip()
    if not query:
        return None
    results = kb.search_tests(query, min_score=min_score, max_results=1)
    return results[0]["test"] if results else None


def _build_arabic_response(
    detected: List[Dict[str, Any]],
    matches: Dict[int, Optional[Dict[str, Any]]],
) -> str:
    lines = []
    available = []
    unavailable = []
    uncertain = []

    for i, det in enumerate(detected):
        orig = det.get("original_text", "").strip()
        norm = det.get("normalized_name", "").strip()
        conf = float(det.get("confidence", 0.5))
        matched = matches.get(i)

        if conf < 0.5:
            uncertain.append(orig or norm)
        elif matched:
            name_ar = matched.get("analysis_name_ar") or matched.get("analysis_name_en") or norm
            available.append(name_ar)
        else:
            unavailable.append(orig or norm)

    if not detected:
        return "لم يتم التعرف على تحاليل واضحة في الصورة، يرجى رفع صورة أوضح."

    lines.append("**التحاليل المطلوبة في الوصفة:**")
    for a in available:
        lines.append(f"• {a} ✓ (متوفر لدى وريد)")
    for u in unavailable:
        lines.append(f"• {u} (غير متوفر في القائمة)")
    for u in uncertain:
        lines.append(f"• {u} (غير مؤكد - يرجى التحقق)")

    lines.append("")
    lines.append("لمعرفة الأسعار والعروض يرجى التواصل مع خدمة العملاء على الرقم **800-122-1220**.")
    lines.append("")
    lines.append("هل تحتاج إلى مزيد من المعلومات؟")

    return "\n".join(lines)


def process_prescription_image(image_bytes: bytes, content_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Process prescription image: validate, preprocess, extract via Vision API, match, return structured response.
    """
    valid, err = _validate_image(image_bytes)
    if not valid:
        raise ValueError(err or "Invalid image")

    processed = preprocess_image(image_bytes)
    detected = _extract_tests_via_vision(processed)

    if not detected:
        return {
            "success": True,
            "extracted_text": "",
            "response_message": "لم يتم التعرف على تحاليل واضحة في الصورة، يرجى رفع صورة أوضح.",
            "detected_tests": [],
            "available_tests": [],
            "unavailable_tests": [],
            "contact_number": WAREED_CONTACT,
        }

    matches = {}
    for i, det in enumerate(detected):
        norm = det.get("normalized_name", "").strip()
        matches[i] = _match_test(norm) if norm else None

    response_message = _build_arabic_response(detected, matches)
    available = [matches[i] for i in range(len(detected)) if matches[i] is not None]
    unavailable = [
        det.get("original_text") or det.get("normalized_name", "")
        for i, det in enumerate(detected)
        if matches[i] is None and float(det.get("confidence", 0.5)) >= 0.5
    ]

    return {
        "success": True,
        "extracted_text": response_message,
        "response_message": response_message,
        "detected_tests": detected,
        "available_tests": [
            {
                "analysis_name_ar": t.get("analysis_name_ar"),
                "analysis_name_en": t.get("analysis_name_en"),
                "category": t.get("category"),
            }
            for t in available
        ],
        "unavailable_tests": unavailable,
        "contact_number": WAREED_CONTACT,
    }
