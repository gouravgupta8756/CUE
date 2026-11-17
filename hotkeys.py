"""hotkeys.py - Global hotkeys jo PyQt signals emit karte hain (thread-safe)."""

from __future__ import annotations

import sys
from typing import Callable

from pynput import keyboard
from PyQt6.QtCore import QObject, pyqtSignal


class HotkeyManager(QObject):
    """pynput ke global hotkeys sunta hai aur har ek ke liye Qt signal emit karta hai.

    pynput apne alag thread me chalta hai, isliye callbacks me seedha UI ko
    touch nahi karte. Sirf signal emit hota hai, aur Qt use receiver ke
    thread me queue kar deta hai (agar receiver ek QObject slot ho).
    """

    screenshot_triggered = pyqtSignal()
    voice_toggled = pyqtSignal()
    visibility_toggled = pyqtSignal()
    chat_triggered = pyqtSignal()

    DEFAULT_BINDINGS: dict[str, str] = {
        "screenshot": "<ctrl>+<shift>+s",
        "voice": "<alt>+r",
        "visibility": "<ctrl>+<shift>+v",
        "chat": "<ctrl>+<shift>+c",
    }

    def __init__(self, bindings: dict[str, str] | None = None, parent: QObject | None = None) -> None:
        """Bindings optional hain; None dene par DEFAULT_BINDINGS use hote hain."""
        super().__init__(parent)
        self._bindings = {**self.DEFAULT_BINDINGS, **(bindings or {})}
        self._listener: keyboard.GlobalHotKeys | None = None

    def _build_map(self) -> dict[str, Callable[[], None]]:
        """Hotkey string -> emit callback ka mapping banata hai."""
        return {
            self._bindings["screenshot"]: self.screenshot_triggered.emit,
            self._bindings["voice"]: self.voice_toggled.emit,
            self._bindings["visibility"]: self.visibility_toggled.emit,
            self._bindings["chat"]: self.chat_triggered.emit,
        }

    def start(self) -> None:
        """Listener thread shuru karta hai (already chal raha ho to kuch nahi karta)."""
        if self._listener is not None:
            return
        self._listener = keyboard.GlobalHotKeys(self._build_map())
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        """Listener rokta hai."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None

    def is_running(self) -> bool:
        """True agar listener active hai."""
        return self._listener is not None and self._listener.is_alive()


if __name__ == "__main__":
    from PyQt6.QtCore import QCoreApplication, QTimer

    app = QCoreApplication(sys.argv)
    manager = HotkeyManager()

    manager.screenshot_triggered.connect(lambda: print("[screenshot] Ctrl+Shift+S"))
    manager.voice_toggled.connect(lambda: print("[voice] Alt+R"))
    manager.visibility_toggled.connect(lambda: print("[show/hide] Ctrl+Shift+V"))
    manager.chat_triggered.connect(lambda: print("[chat] Ctrl+Shift+C"))

    manager.start()
    print("Hotkeys active. 30 second me auto-exit. Keys dabake test karo...")

    QTimer.singleShot(30_000, app.quit)
    code = app.exec()
    manager.stop()
    sys.exit(code)