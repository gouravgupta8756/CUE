"""stt.py - Speech-to-text: faster-whisper (local, default) ya Azure Speech, hallucination filter ke saath."""

from __future__ import annotations

import os
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


# ---------- settings ----------

@dataclass
class SttConfig:
    """STT settings. Defaults env variables se aate hain."""

    backend: str = field(default_factory=lambda: os.getenv("STT_BACKEND", "whisper").lower())  # whisper | azure
    whisper_model: str = field(default_factory=lambda: os.getenv("WHISPER_MODEL", "small"))
    whisper_device: str = field(default_factory=lambda: os.getenv("WHISPER_DEVICE", "auto"))
    whisper_compute: str = field(default_factory=lambda: os.getenv("WHISPER_COMPUTE", "int8"))
    language: str | None = field(default_factory=lambda: os.getenv("STT_LANGUAGE") or None)  # None = auto-detect
    azure_key: str | None = field(default_factory=lambda: os.getenv("AZURE_SPEECH_KEY"))
    azure_region: str | None = field(default_factory=lambda: os.getenv("AZURE_SPEECH_REGION"))
    azure_language: str = field(default_factory=lambda: os.getenv("AZURE_SPEECH_LANGUAGE", "en-US"))


# ---------- hallucination filter ----------

# Normalize karne ke baad (lowercase, bina punctuation) ye poora text ho to phantom maana jayega.
_EXACT_PHANTOMS: set[str] = {
    "thank you", "thanks", "thank you very much", "thanks for watching",
    "thank you for watching", "thanks for listening", "thank you for listening",
    "please subscribe", "like and subscribe", "bye", "bye bye", "goodbye",
    "you", "the end", "see you next time", "see you in the next video",
    "see you in the next one", "ill see you in the next video",
    "subtitles by the amaraorg community", "okay", "so", "uh", "um", "hmm", "mm",
}

# Ye patterns kisi bhi jagah mile to segment drop ho jata hai (YouTube-subtitle jaisi aadatein).
_PHANTOM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"thank(s| you) for (watching|listening)",
        r"(please |don'?t forget to )?(like and )?subscribe (to|and)",
        r"like and subscribe",
        r"subscribe to (my|the|our) channel",
        r"amara\.org",
        r"subtitles? (by|from)",
        r"captions? by",
        r"transcribed by",
        r"translated by",
        r"see you (in the )?next (video|time|one)",
    )
]

# [Music], (applause), *silence*, ♪ jaise non-speech tags.
_TAG_ONLY = re.compile(r"^\s*[\[\(\*♪].*[\]\)\*♪]?\s*$")


def _normalize(text: str) -> str:
    """Lowercase + punctuation hata kar compare ke liye text banata hai."""
    text = re.sub(r"[^\w\s]", "", text.lower(), flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _is_repetition_loop(text: str) -> bool:
    """True agar text ka bada hissa ek hi chhote phrase ka repeat ho ("I I I I I I...")."""
    words = _normalize(text).split()
    if len(words) < 6:
        return False
    for n in (1, 2, 3, 4):
        grams = [tuple(words[i:i + n]) for i in range(0, len(words) - n + 1, n)]
        if len(grams) >= 4:
            top = max(set(grams), key=grams.count)
            if grams.count(top) * n >= 0.6 * len(words) and grams.count(top) >= 4:
                return True
    return False


def is_hallucination(text: str) -> bool:
    """True agar text khaali, sirf punctuation, phantom phrase ya repetition loop hai."""
    stripped = text.strip()
    norm = _normalize(stripped)
    if not norm:
        return True
    if _TAG_ONLY.match(stripped) and len(stripped) < 40:
        return True
    if norm in _EXACT_PHANTOMS:
        return True
    if any(p.search(stripped) for p in _PHANTOM_PATTERNS):
        return True
    return _is_repetition_loop(stripped)


def clean_transcript(text: str) -> str:
    """Poore transcript par filter lagata hai; phantom ho to '' return karta hai."""
    text = re.sub(r"\s+", " ", text).strip()
    return "" if is_hallucination(text) else text


# ---------- faster-whisper backend ----------

_models: dict[tuple[str, str, str], object] = {}
_model_lock = threading.Lock()


def _get_model(cfg: SttConfig):
    """WhisperModel ek baar load karke cache karta hai (load slow hota hai)."""
    key = (cfg.whisper_model, cfg.whisper_device, cfg.whisper_compute)
    with _model_lock:
        if key not in _models:
            from faster_whisper import WhisperModel

            _models[key] = WhisperModel(
                cfg.whisper_model, device=cfg.whisper_device, compute_type=cfg.whisper_compute
            )
        return _models[key]


def preload(cfg: SttConfig | None = None) -> None:
    """App start par call karo taaki pehli transcription me delay na aaye."""
    cfg = cfg or SttConfig()
    if cfg.backend == "whisper":
        _get_model(cfg)


def _whisper_transcribe(audio: str | np.ndarray, cfg: SttConfig) -> str:
    """faster-whisper se transcribe; low-confidence segments segment-level par hata deta hai."""
    model = _get_model(cfg)
    segments, _info = model.transcribe(
        audio,
        language=cfg.language,
        beam_size=5,
        vad_filter=True,                       # silence hata ke hallucination kam karta hai
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,      # repetition loops se bachata hai
        no_speech_threshold=0.6,
        log_prob_threshold=-1.0,
        compression_ratio_threshold=2.4,
        temperature=0.0,
    )
    kept: list[str] = []
    for seg in segments:
        if seg.no_speech_prob > 0.6 and seg.avg_logprob < -1.0:
            continue
        if seg.compression_ratio > 2.4:
            continue
        piece = seg.text.strip()
        if piece and not is_hallucination(piece):
            kept.append(piece)
    return " ".join(kept)


# ---------- Azure backend ----------

def _azure_transcribe(wav_path: str, cfg: SttConfig, timeout_s: float = 120.0) -> str:
    """Azure Speech se poori file transcribe karta hai (continuous recognition)."""
    if not cfg.azure_key or not cfg.azure_region:
        raise RuntimeError("AZURE_SPEECH_KEY aur AZURE_SPEECH_REGION set karo")
    import azure.cognitiveservices.speech as speechsdk

    speech_cfg = speechsdk.SpeechConfig(subscription=cfg.azure_key, region=cfg.azure_region)
    speech_cfg.speech_recognition_language = cfg.azure_language
    recognizer = speechsdk.SpeechRecognizer(
        speech_config=speech_cfg,
        audio_config=speechsdk.audio.AudioConfig(filename=wav_path),
    )

    parts: list[str] = []
    errors: list[str] = []
    done = threading.Event()

    def on_recognized(evt) -> None:
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
            parts.append(evt.result.text)

    def on_canceled(evt) -> None:
        if evt.reason == speechsdk.CancellationReason.Error:
            errors.append(evt.error_details)
        done.set()

    recognizer.recognized.connect(on_recognized)
    recognizer.canceled.connect(on_canceled)
    recognizer.session_stopped.connect(lambda _evt: done.set())

    recognizer.start_continuous_recognition()
    finished = done.wait(timeout=timeout_s)
    recognizer.stop_continuous_recognition()

    if errors:
        raise RuntimeError(f"Azure STT error: {errors[0]}")
    if not finished:
        raise TimeoutError("Azure STT timeout")
    return " ".join(parts)


# ---------- public API ----------

def transcribe(wav_path: str | Path, cfg: SttConfig | None = None) -> str:
    """WAV file ko text me badalta hai. Silence/phantom par '' return hota hai.

    Backend `cfg.backend` se tay hota hai: "whisper" (default) ya "azure".
    """
    cfg = cfg or SttConfig()
    path = Path(wav_path)
    if not path.is_file():
        raise FileNotFoundError(path)

    if cfg.backend == "azure":
        raw = _azure_transcribe(str(path), cfg)
    elif cfg.backend == "whisper":
        raw = _whisper_transcribe(str(path), cfg)
    else:
        raise ValueError(f"Unknown STT backend: {cfg.backend!r}")
    return clean_transcript(raw)


def transcribe_array(audio: np.ndarray, cfg: SttConfig | None = None) -> str:
    """Recorder ka array seedha transcribe karta hai (sirf whisper backend, wav file nahi chahiye).

    int16 ya float32 dono chalte hain; 16 kHz mono maana jata hai.
    """
    cfg = cfg or SttConfig()
    if cfg.backend != "whisper":
        raise ValueError("transcribe_array sirf whisper backend ke saath chalta hai")
    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32768.0
    return clean_transcript(_whisper_transcribe(audio.astype(np.float32), cfg))


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # 1) Filter ka offline test (model ki zarurat nahi)
    cases = {
        "Thanks for watching!": True,
        "Thank you.": True,
        "[Music]": True,
        "   ": True,
        "...": True,
        "I I I I I I I I": True,
        "Please subscribe to my channel": True,
        "How do I subscribe to a Kafka topic?": False,
        "Explain binary search with an example": False,
    }
    for text, expected in cases.items():
        got = is_hallucination(text)
        print(f"{'OK  ' if got == expected else 'FAIL'} {text!r} -> hallucination={got}")

    # 2) Asli transcription (optional): python stt.py test_recording.wav [azure]
    if len(sys.argv) > 1:
        config = SttConfig()
        if len(sys.argv) > 2:
            config.backend = sys.argv[2]
        print(f"\nBackend: {config.backend}")
        print("Transcript:", repr(transcribe(sys.argv[1], config)))