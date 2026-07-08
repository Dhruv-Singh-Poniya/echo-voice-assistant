"""Voice I/O — dispatches to the configured voice provider.

  VOICE_PROVIDER=elevenlabs  -> ElevenLabs native API (this file)
  VOICE_PROVIDER=gateway     -> OpenAI-compatible gateway (voice_gateway.py)

Public interface stays the same for the rest of the app:
  speech_to_text(audio_bytes, filename) -> text
  text_to_speech(text)                  -> mp3 bytes
"""
from __future__ import annotations

import httpx

from . import voice_gateway
from .config import settings

_BASE = "https://api.elevenlabs.io/v1"
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_el_client = httpx.AsyncClient(timeout=_TIMEOUT)  # persistent keep-alive connection


# --------------------------------------------------------------------------
# Public dispatchers
# --------------------------------------------------------------------------
async def speech_to_text(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    if settings.voice_provider == "gateway":
        return await voice_gateway.speech_to_text(audio_bytes, filename)
    return await _elevenlabs_stt(audio_bytes, filename)


async def text_to_speech(text: str) -> bytes:
    if settings.voice_provider == "gateway":
        return await voice_gateway.text_to_speech(text)
    return await _elevenlabs_tts(text)


# --------------------------------------------------------------------------
# ElevenLabs native implementation
# --------------------------------------------------------------------------
async def _elevenlabs_stt(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    headers = {"xi-api-key": settings.elevenlabs_api_key}
    files = {"file": (filename, audio_bytes, "application/octet-stream")}
    data = {"model_id": settings.elevenlabs_stt_model}

    resp = await _el_client.post(
        f"{_BASE}/speech-to-text", headers=headers, data=data, files=files
    )
    resp.raise_for_status()
    return (resp.json().get("text") or "").strip()


async def _elevenlabs_tts(text: str) -> bytes:
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }
    body = {
        "text": text,
        "model_id": settings.elevenlabs_tts_model,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }

    resp = await _el_client.post(
        f"{_BASE}/text-to-speech/{settings.elevenlabs_voice_id}",
        headers=headers,
        json=body,
    )
    resp.raise_for_status()
    return resp.content
