"""Attachment utility helpers extracted from message_service.

Behavior must remain identical to original helper logic.
"""

from __future__ import annotations

import logging
import os
import tempfile

logger = logging.getLogger(__name__)


def transcribe_audio_bytes(audio_bytes: bytes, filename: str = "voice-message.webm") -> str:
    """Transcribe raw audio bytes using Whisper API and return text."""
    if not audio_bytes:
        raise ValueError("Empty audio data.")
    suffix = os.path.splitext(filename)[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_audio:
        temp_audio.write(audio_bytes)
        temp_audio_path = temp_audio.name
    try:
        try:
            from openai import OpenAI
        except Exception:
            raise ValueError("Voice transcription service is currently unavailable.")
        client = OpenAI()
        with open(temp_audio_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
        return (getattr(transcript, "text", "") or "").strip()
    except Exception as exc:
        logger.warning("Audio transcription failed: %s", exc)
        raise ValueError("Failed to transcribe the voice message. Please try again.")
    finally:
        try:
            os.remove(temp_audio_path)
        except Exception:
            pass
