"""Voice via an OpenAI-compatible AI gateway.

The gateway proxies to ElevenLabs / OpenAI / Bedrock behind one key, using the
standard OpenAI audio endpoints:
  * speech_to_text -> POST {base}/v1/audio/transcriptions   (e.g. whisper-1)
  * text_to_speech -> POST {base}/v1/audio/speech           (e.g. gpt-4o-mini-tts)
"""
from __future__ import annotations

import httpx

from .config import settings

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

# One persistent client keeps the TLS connection to the gateway alive (keep-alive),
# so repeated STT/TTS/chat calls skip the ~100-300ms handshake each time.
_client = httpx.AsyncClient(timeout=_TIMEOUT)


def _headers() -> dict:
    return {"Authorization": f"Bearer {settings.gateway_api_key}"}


async def speech_to_text(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    files = {"file": (filename, audio_bytes, "application/octet-stream")}
    data = {"model": settings.gateway_stt_model}

    resp = await _client.post(
        f"{settings.gateway_base_url}/v1/audio/transcriptions",
        headers=_headers(),
        data=data,
        files=files,
    )
    resp.raise_for_status()
    return (resp.json().get("text") or "").strip()


async def text_to_speech(text: str) -> bytes:
    body = {
        "model": settings.gateway_tts_model,
        "input": text,
        "voice": settings.gateway_tts_voice,
        "response_format": "mp3",
    }
    headers = {**_headers(), "content-type": "application/json"}

    resp = await _client.post(
        f"{settings.gateway_base_url}/v1/audio/speech",
        headers=headers,
        json=body,
    )
    resp.raise_for_status()
    return resp.content
