"""Central configuration, loaded once from environment / .env file."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load .env sitting next to the `backend/` folder.
BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    # --- Which brain powers the assistant: "ollama" (local), "anthropic" (cloud), or "gateway" ---
    llm_provider: str = os.getenv("LLM_PROVIDER", "ollama").strip().lower()

    # --- Local model via Ollama ---
    ollama_model: str = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
    ollama_host: str = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")

    # --- Anthropic (cloud) ---
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

    # --- AI Gateway (OpenAI-compatible proxy: routes to ElevenLabs / Bedrock / OpenAI) ---
    # Powers both voice and (optionally) the brain through one key.
    gateway_base_url: str = os.getenv("GATEWAY_BASE_URL", "").strip().rstrip("/")
    gateway_api_key: str = (
        os.getenv("GATEWAY_API_KEY", "").strip() or os.getenv("ELEVENLABS_API_KEY", "").strip()
    )
    gateway_chat_model: str = os.getenv("GATEWAY_CHAT_MODEL", "us.anthropic.claude-sonnet-4-6")
    gateway_stt_model: str = os.getenv("GATEWAY_STT_MODEL", "whisper-1")
    gateway_tts_model: str = os.getenv("GATEWAY_TTS_MODEL", "gpt-4o-mini-tts")
    gateway_tts_voice: str = os.getenv("GATEWAY_TTS_VOICE", "alloy")

    # --- Which service does voice (STT + TTS): "elevenlabs" (native) or "gateway" ---
    voice_provider: str = os.getenv("VOICE_PROVIDER", "elevenlabs").strip().lower()

    # --- ElevenLabs ---
    elevenlabs_api_key: str = os.getenv("ELEVENLABS_API_KEY", "")
    elevenlabs_voice_id: str = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    elevenlabs_tts_model: str = os.getenv("ELEVENLABS_TTS_MODEL", "eleven_multilingual_v2")
    elevenlabs_stt_model: str = os.getenv("ELEVENLABS_STT_MODEL", "scribe_v1")

    # --- Assistant behaviour ---
    reply_max_tokens: int = _int("REPLY_MAX_TOKENS", 400)
    assistant_name: str = os.getenv("ASSISTANT_NAME", "Jarvis")
    allow_shell_commands: bool = _bool("ALLOW_SHELL_COMMANDS", False)

    # --- RecallrAI long-term memory ---
    recallrai_enabled: bool = _bool("RECALLRAI_ENABLED", False)
    recallrai_api_key: str = os.getenv("RECALLRAI_API_KEY", "").strip()
    recallrai_project_id: str = os.getenv("RECALLRAI_PROJECT_ID", "").strip()
    recallrai_user_id: str = os.getenv("RECALLRAI_USER_ID", "voice-assistant-user").strip()
    recallrai_base_url: str = os.getenv("RECALLRAI_BASE_URL", "https://api.recallrai.com").strip().rstrip("/")
    recallrai_forward_proxy_url: str = os.getenv("RECALLRAI_FORWARD_PROXY_URL", "").strip()
    recallrai_timeout: int = _int("RECALLRAI_TIMEOUT", 15)
    recallrai_recall_strategy: str = os.getenv("RECALLRAI_RECALL_STRATEGY", "low_latency").strip().lower()
    recallrai_auto_process_after_seconds: int = _int("RECALLRAI_AUTO_PROCESS_AFTER_SECONDS", 600)
    recallrai_last_n_messages: int = _int("RECALLRAI_LAST_N_MESSAGES", 1)
    recallrai_include_system_prompt: bool = _bool("RECALLRAI_INCLUDE_SYSTEM_PROMPT", False)

    # --- Storage ---
    db_path: str = str(BACKEND_DIR / "assistant.db")

    def require_keys(self) -> list[str]:
        """Return a list of human-readable problems, empty if all good."""
        problems = []

        # --- Brain ---
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            problems.append(
                "ANTHROPIC_API_KEY is missing (LLM_PROVIDER=anthropic needs it). "
                "Set LLM_PROVIDER=ollama to run locally instead."
            )
        if self.llm_provider == "gateway" and not self.gateway_base_url:
            problems.append("GATEWAY_BASE_URL is missing (LLM_PROVIDER=gateway needs the gateway's URL).")
        if self.llm_provider not in {"ollama", "anthropic", "gateway"}:
            problems.append(
                f"LLM_PROVIDER must be 'ollama', 'anthropic', or 'gateway', got {self.llm_provider!r}."
            )

        # --- Voice ---
        if self.voice_provider == "gateway":
            if not self.gateway_base_url:
                problems.append("GATEWAY_BASE_URL is missing (VOICE_PROVIDER=gateway needs the gateway's URL).")
            if not self.gateway_api_key:
                problems.append("GATEWAY_API_KEY is missing (needed for gateway voice).")
        elif self.voice_provider == "elevenlabs":
            if not self.elevenlabs_api_key:
                problems.append("ELEVENLABS_API_KEY is missing (needed for voice in/out).")
        else:
            problems.append(f"VOICE_PROVIDER must be 'elevenlabs' or 'gateway', got {self.voice_provider!r}.")

        # --- Memory ---
        if self.recallrai_enabled:
            if not self.recallrai_api_key:
                problems.append("RECALLRAI_API_KEY is missing (RECALLRAI_ENABLED=true needs it).")
            if not self.recallrai_project_id:
                problems.append("RECALLRAI_PROJECT_ID is missing (RECALLRAI_ENABLED=true needs it).")
            if not self.recallrai_user_id:
                problems.append("RECALLRAI_USER_ID must not be empty when RecallrAI is enabled.")
            if self.recallrai_recall_strategy not in {"low_latency", "balanced", "agentic", "deep"}:
                problems.append(
                    "RECALLRAI_RECALL_STRATEGY must be low_latency, balanced, agentic, or deep."
                )

        return problems


settings = Settings()
