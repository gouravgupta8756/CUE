"""audio.py - 16 kHz mono recorder: manual start/stop + webrtcvad se auto pause detection."""

from __future__ import annotations

import queue
import sys
import threading
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np
import sounddevice as sd
import webrtcvad


class Recorder:
    """Background thread me mic record karta hai.

    Do modes:
      - Manual: start() ... stop()
      - VAD: vad_mode=True. Bolna shuru hone ke baad `silence_ms` ki chuppi
        par apne aap ruk jata hai aur `on_auto_stop` call karta hai.

    Output int16 numpy array (get_audio / stop) ya PCM .wav file (save_wav).
    """

    SAMPLE_RATE = 16_000
    FRAME_MS = 30  # webrtcvad sirf 10/20/30 ms frames leta hai
    FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 480

    def __init__(
        self,
        vad_mode: bool = False,
        aggressiveness: int = 2,
        silence_ms: int = 1000,
        min_speech_ms: int = 300,
        no_speech_timeout_s: float = 8.0,
        max_seconds: float = 60.0,
        device: int | str | None = None,
        on_auto_stop: Callable[[], None] | None = None,
    ) -> None:
        """
        aggressiveness: 0-3 (3 = noise ko sabse zyada filter karta hai).
        silence_ms: speech ke baad itni chuppi par auto-stop.
        min_speech_ms: itni speech sunne ke baad hi silence count hoga.
        no_speech_timeout_s: VAD mode me kuch na bola to itne sec baad stop.
        max_seconds: hard limit (dono modes me).
        """
        if not 0 <= aggressiveness <= 3:
            raise ValueError("aggressiveness 0 se 3 ke beech hona chahiye")
        self.vad_mode = vad_mode
        self.silence_ms = silence_ms
        self.min_speech_ms = min_speech_ms
        self.no_speech_timeout_s = no_speech_timeout_s
        self.max_seconds = max_seconds
        self.device = device
        self.on_auto_stop = on_auto_stop

        self._vad = webrtcvad.Vad(aggressiveness)
        self._queue: queue.Queue[bytes] = queue.Queue()
        self._frames: list[bytes] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._stream: sd.RawInputStream | None = None
        self._auto_stopped = False

    # ---------- public API ----------

    @property
    def is_recording(self) -> bool:
        """True jab tak recording thread chal raha hai."""
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Recording shuru karta hai (already chal rahi ho to kuch nahi)."""
        if self.is_recording:
            return
        with self._lock:
            self._frames = []
        self._queue = queue.Queue()
        self._stop_event.clear()
        self._auto_stopped = False

        self._stream = sd.RawInputStream(
            samplerate=self.SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=self.FRAME_SAMPLES,
            device=self.device,
            callback=self._on_audio,
        )
        self._stream.start()
        self._thread = threading.Thread(target=self._worker, name="RecorderThread", daemon=True)
        self._thread.start()

    def stop(self) -> np.ndarray:
        """Recording rokta hai aur int16 array return karta hai."""
        self._stop_event.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        return self.get_audio()

    def get_audio(self) -> np.ndarray:
        """Ab tak record hua audio int16 mono array (16 kHz) me deta hai."""
        with self._lock:
            data = b"".join(self._frames)
        return np.frombuffer(data, dtype=np.int16).copy()

    def get_audio_float32(self) -> np.ndarray:
        """Audio float32 [-1, 1] me (faster-whisper seedha yahi leta hai)."""
        return self.get_audio().astype(np.float32) / 32768.0

    def duration(self) -> float:
        """Record hua audio seconds me."""
        with self._lock:
            n = sum(len(f) for f in self._frames) // 2
        return n / self.SAMPLE_RATE

    def save_wav(self, path: str | Path) -> Path:
        """Audio ko 16-bit PCM mono .wav file me save karta hai."""
        path = Path(path)
        audio = self.get_audio()
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(self.SAMPLE_RATE)
            wf.writeframes(audio.tobytes())
        return path

    # ---------- internals ----------

    def _on_audio(self, indata, frames: int, time_info, status) -> None:
        """sounddevice callback: bas bytes queue me daalta hai (fast rakho)."""
        self._queue.put_nowait(bytes(indata))

    def _worker(self) -> None:
        """Queue se frames leta hai, store karta hai, aur VAD mode me silence track karta hai."""
        speech_ms = 0
        silence_ms = 0
        elapsed_ms = 0
        speech_started = False

        try:
            while not self._stop_event.is_set():
                try:
                    frame = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                with self._lock:
                    self._frames.append(frame)
                elapsed_ms += self.FRAME_MS

                if elapsed_ms >= self.max_seconds * 1000:
                    self._auto_stopped = True
                    break

                if not self.vad_mode:
                    continue

                if self._vad.is_speech(frame, self.SAMPLE_RATE):
                    speech_ms += self.FRAME_MS
                    silence_ms = 0
                    if speech_ms >= self.min_speech_ms:
                        speech_started = True
                else:
                    if speech_started:
                        silence_ms += self.FRAME_MS
                        if silence_ms >= self.silence_ms:
                            self._auto_stopped = True
                            break
                    elif elapsed_ms >= self.no_speech_timeout_s * 1000:
                        self._auto_stopped = True
                        break
        finally:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                finally:
                    self._stream = None
            self._stop_event.set()

        if self._auto_stopped and self.on_auto_stop is not None:
            self.on_auto_stop()  # worker thread se call hota hai


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "vad"

    if mode == "manual":
        rec = Recorder(vad_mode=False)
        input("Enter dabao -> recording start... ")
        rec.start()
        input("Recording chal rahi hai. Enter dabao -> stop... ")
        rec.stop()
    else:
        done = threading.Event()
        rec = Recorder(vad_mode=True, silence_ms=1000, on_auto_stop=done.set)
        print("VAD mode: bolo, phir 1 sec chup raho...")
        rec.start()
        done.wait(timeout=70)
        rec.stop()

    out = rec.save_wav("test_recording.wav")
    audio = rec.get_audio()
    print(f"Saved: {out} | {rec.duration():.2f}s | samples={audio.size} | dtype={audio.dtype}")