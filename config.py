"""CUE configuration loaded from .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

CHOICES: dict[str, tuple[str, ...]] = {
    "SPEECH_PROVIDER": ("whisper", "azure", "none"),
    "WHISPER_CAPTURE_MODE": ("vad", "manual"),
    "WHISPER_RESPONSE_TARGET": ("chat", "overlay", "both"),
}


@dataclass(frozen=True)
class Settings:
    """CUE settings."""

    gemini_api_key: str
    gemini_model: str = "gemini-2.5-flash"
    speech_provider: str = "whisper"
    whisper_model: str = "small"
    whisper_capture_mode: str = "vad"
    whisper_response_target: str = "both"


def _env(name: str, default: str) -> str:
    """Read an env var, validating it against CHOICES if restricted."""
    value = os.getenv(name, "").strip() or default
    if name in CHOICES:
        value = value.lower()
        if value not in CHOICES[name]:
            raise ValueError(f"{name}={value!r} invalid; use one of {CHOICES[name]}")
    return value


def load_settings() -> Settings:
    """Load Settings from .env / environment; raise if GEMINI_API_KEY is missing."""
    load_dotenv()
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise ValueError("GEMINI_API_KEY missing: add it to your .env file.")
    return Settings(
        key,
        _env("GEMINI_MODEL", "gemini-2.5-flash"),
        _env("SPEECH_PROVIDER", "whisper"),
        _env("WHISPER_MODEL", "small"),
        _env("WHISPER_CAPTURE_MODE", "vad"),
        _env("WHISPER_RESPONSE_TARGET", "both"),
    )


if __name__ == "__main__":
    os.environ.pop("GEMINI_API_KEY", None)
    os.environ["GEMINI_API_KEY"] = "test"
    print(load_settings())
    os.environ["SPEECH_PROVIDER"] = "bad"
    try:
        load_settings()
    except ValueError as e:
        print("ok:", e)