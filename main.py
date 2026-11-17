"""CUE entry point: wires hotkeys, capture, audio/STT, prompts and LLM to the UI.

Assumed interfaces of the other modules (give these to each module's prompt):
    config.load_settings() -> Settings  (.language, .hotkeys: dict[str, str], .stealth: bool)
    prompts.build_prompt(language: str, question: str, has_image: bool) -> str
    llm.ask(prompt: str, image: bytes | None = None) -> Iterator[str]   # streams chunks
    capture.grab_screen() -> bytes                                      # PNG bytes
    audio.Recorder().start() / .stop() -> bytes                         # 16 kHz mono PCM16, VAD trimmed
    stt.transcribe(audio: bytes) -> str
    hotkeys.HotkeyManager(bindings: dict[str, Callable[[], None]]).start() / .stop()
    stealth.hide_from_capture(widget: QWidget) -> bool
    ui.overlay.Overlay / ui.chat.ChatWindow:
        .clear(), .append_chunk(str), .show_error(str), .show(), .toggle()
"""
from __future__ import annotations

import logging
import sys
import traceback
from typing import Optional

from PyQt6.QtCore import QObject, QThread, pyqtSignal
from PyQt6.QtWidgets import QApplication

import audio
import capture
import config
import hotkeys
import llm
import prompts
import stealth
import stt
from ui.chat import ChatWindow
from ui.overlay import OverlayWindow

log = logging.getLogger("cue")

TARGET_OVERLAY = "overlay"
TARGET_CHAT = "chat"


class AskWorker(QThread):
    """Runs STT (optional) and the LLM call off the UI thread, streaming chunks via signals."""

    transcript = pyqtSignal(str)
    chunk = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(
        self,
        language: str,
        image: Optional[bytes] = None,
        audio_data: Optional[bytes] = None,
        question: str = "",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.language = language
        self.image = image
        self.audio_data = audio_data
        self.question = question
        self._cancelled = False

    def cancel(self) -> None:
        """Ask the worker to stop emitting further chunks."""
        self._cancelled = True

    def run(self) -> None:
        """Transcribe if audio is present, build the prompt, stream the answer."""
        try:
            question = self.question
            if self.audio_data:
                question = stt.transcribe(self.audio_data).strip()
                if self._cancelled:
                    return
                if not question and self.image is None:
                    self.failed.emit("Kuch sunai nahi diya. Dobara try karo.")
                    return
                self.transcript.emit(question)

            prompt = prompts.build_prompt(self.language, question, self.image is not None)
            for piece in llm.ask(prompt, self.image):
                if self._cancelled:
                    return
                self.chunk.emit(piece)
        except Exception as exc:  # never let a worker crash the app
            log.error("worker failed:\n%s", traceback.format_exc())
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class HotkeyBridge(QObject):
    """Moves pynput (non-Qt thread) callbacks onto the Qt main thread via signals."""

    screenshot = pyqtSignal()
    voice_toggle = pyqtSignal()
    screenshot_voice = pyqtSignal()
    toggle_overlay = pyqtSignal()
    toggle_chat = pyqtSignal()


class CueApp(QObject):
    """Application controller."""

    def __init__(self) -> None:
        super().__init__()
        self.settings = config.load_settings()
        self.overlay = OverlayWindow()
        self.chat = ChatWindow()
        self.recorder: Optional[audio.Recorder] = None
        self.pending_image: Optional[bytes] = None
        self.worker: Optional[AskWorker] = None
        self.target = TARGET_OVERLAY

        if getattr(self.settings, "stealth", False):
            for w in (self.overlay, self.chat):
                try:
                    stealth.hide_from_capture(w)
                except Exception as exc:
                    log.warning("stealth failed: %s", exc)

        self.bridge = HotkeyBridge()
        self.bridge.screenshot.connect(lambda: self.on_screenshot(voice=False))
        self.bridge.screenshot_voice.connect(lambda: self.on_screenshot(voice=True))
        self.bridge.voice_toggle.connect(self.on_voice_toggle)
        self.bridge.toggle_overlay.connect(self.overlay.toggle)
        self.bridge.toggle_chat.connect(self.chat.toggle)

        self.hotkeys = hotkeys.HotkeyManager(
            {
                "screenshot": self.bridge.screenshot.emit,
                "screenshot_voice": self.bridge.screenshot_voice.emit,
                "voice": self.bridge.voice_toggle.emit,
                "toggle_overlay": self.bridge.toggle_overlay.emit,
                "toggle_chat": self.bridge.toggle_chat.emit,
            }
        )

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        """Show the overlay and start listening for hotkeys."""
        self.overlay.show()
        self.hotkeys.start()

    def stop(self) -> None:
        """Stop hotkeys, workers and any active recording."""
        self.hotkeys.stop()
        self._cancel_worker()
        if self.recorder is not None:
            try:
                self.recorder.stop()
            except Exception:
                pass

    # ---- helpers ---------------------------------------------------------
    @property
    def view(self) -> OverlayWindow | ChatWindow:
        """Current response target widget."""
        return self.chat if self.target == TARGET_CHAT else self.overlay

    def _error(self, message: str) -> None:
        log.error(message)
        self.view.show_error(message)

    def _cancel_worker(self) -> None:
        if self.worker is not None and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(2000)

    def _launch(self, image: Optional[bytes], audio_data: Optional[bytes]) -> None:
        self._cancel_worker()
        # Response target: chat window if it is visible, else the overlay.
        self.target = TARGET_CHAT if self.chat.isVisible() else TARGET_OVERLAY
        self.view.clear()
        self.view.show()

        worker = AskWorker(
            language=self.settings.language, image=image, audio_data=audio_data, parent=self
        )
        worker.transcript.connect(lambda q: self.chat.append_chunk(f"\n**Q:** {q}\n\n")
                                  if self.target == TARGET_CHAT else None)
        worker.chunk.connect(lambda c: self.view.append_chunk(c))
        worker.failed.connect(self._error)
        worker.finished.connect(worker.deleteLater)
        self.worker = worker
        worker.start()

    # ---- hotkey handlers -------------------------------------------------
    def on_screenshot(self, voice: bool) -> None:
        """Capture the screen; ask immediately, or wait for a voice question."""
        try:
            image = capture.grab_screen()
        except Exception as exc:
            self._error(f"Screenshot failed: {exc}")
            return
        if voice:
            self.pending_image = image
            self.on_voice_toggle()
        else:
            self._launch(image=image, audio_data=None)

    def on_voice_toggle(self) -> None:
        """First press starts recording, second press stops and sends."""
        if self.recorder is None:
            try:
                self.recorder = audio.Recorder()
                self.recorder.start()
                self.view.show()
                self.view.clear()
                self.view.append_chunk("🎙 Listening… (dobara hotkey dabao)")
            except Exception as exc:
                self.recorder = None
                self.pending_image = None
                self._error(f"Mic error: {exc}")
            return

        recorder, self.recorder = self.recorder, None
        image, self.pending_image = self.pending_image, None
        try:
            data = recorder.stop()
        except Exception as exc:
            self._error(f"Recording error: {exc}")
            return
        if not data and image is None:
            self._error("Koi audio record nahi hua.")
            return
        self._launch(image=image, audio_data=data or None)


def main() -> int:
    """Run the application."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)

    sys.excepthook = lambda t, v, tb: log.error("uncaught:\n%s", "".join(traceback.format_exception(t, v, tb)))

    cue = CueApp()
    qapp.aboutToQuit.connect(cue.stop)
    cue.start()
    return qapp.exec()


def _selftest() -> None:
    """Headless test of AskWorker with fake backends (no GUI, no network)."""
    from PyQt6.QtCore import QCoreApplication

    app = QCoreApplication([])
    prompts.build_prompt = lambda lang, q, img: f"[{lang}] {q} img={img}"  # type: ignore
    llm.ask = lambda prompt, image=None: iter(["Hel", "lo ", prompt])  # type: ignore
    stt.transcribe = lambda data: "test question"  # type: ignore

    got: list[str] = []
    w = AskWorker("python", image=None, audio_data=b"\x00\x01")
    w.chunk.connect(got.append)
    w.failed.connect(lambda e: got.append(f"ERR {e}"))
    w.finished.connect(app.quit)
    w.start()
    app.exec()
    print("".join(got))
    assert "".join(got).startswith("Hello "), got
    print("selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        sys.exit(main())