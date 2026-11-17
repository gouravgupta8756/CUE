"""Floating, translucent, always-on-top assistant overlay."""

from __future__ import annotations

import markdown
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

STYLE = """
#panel { background: rgba(24, 24, 28, 230); border-radius: 14px; }
QLabel { color: #888; }
QLineEdit, QPushButton { background: rgba(255,255,255,25); color: #fff;
    border: none; border-radius: 8px; padding: 6px 10px; }
QPushButton:checked { background: #4c8dff; }
QTextBrowser { background: transparent; color: #eee; border: none; font-size: 14px; }
"""


def render_md(text: str) -> str:
    """Convert markdown to HTML with Pygments-highlighted code blocks."""
    return markdown.markdown(
        text,
        extensions=["fenced_code", "codehilite"],
        extension_configs={
            "codehilite": {"noclasses": True, "pygments_style": "monokai", "guess_lang": False}
        },
    )


class OverlayWindow(QWidget):
    """Frameless overlay: draggable command bar + streaming markdown answer."""

    screenshot_clicked = pyqtSignal()
    mic_clicked = pyqtSignal()
    text_submitted = pyqtSignal(str)

    def __init__(self) -> None:
        """Build the window, command bar and answer view."""
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(STYLE)
        self.resize(460, 360)
        self._text = ""

        panel = QFrame(self)
        panel.setObjectName("panel")
        QVBoxLayout(self).addWidget(panel)
        self.layout().setContentsMargins(0, 0, 0, 0)

        self.input = QLineEdit(placeholderText="Ask CUE...")
        self.input.returnPressed.connect(self._submit)
        shot, mic = QPushButton("📷"), QPushButton("🎤")
        self.ghost = QPushButton("🖱", checkable=True, toolTip="Click-through")
        close = QPushButton("✕")
        shot.clicked.connect(self.screenshot_clicked)
        mic.clicked.connect(self.mic_clicked)
        self.ghost.toggled.connect(self._apply_click_through)
        close.clicked.connect(self.close)

        bar = QHBoxLayout()
        for w in (QLabel("⠿"), self.input, shot, mic, self.ghost, close):
            bar.addWidget(w)
        self.view = QTextBrowser(openExternalLinks=True)
        lay = QVBoxLayout(panel)
        lay.addLayout(bar)
        lay.addWidget(self.view)

    def mousePressEvent(self, event) -> None:
        """Drag the window from any non-interactive area (handle, bar, padding)."""
        if event.button() == Qt.MouseButton.LeftButton:
            self.windowHandle().startSystemMove()

    def _submit(self) -> None:
        """Emit the typed text and clear the input."""
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.text_submitted.emit(text)

    def _apply_click_through(self, on: bool) -> None:
        """Let mouse events pass through the whole window (or not)."""
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, on)
        self.show()

    def set_click_through(self, on: bool) -> None:
        """Enable/disable click-through (also callable from a hotkey handler)."""
        self.ghost.setChecked(on)

    def append_chunk(self, chunk: str) -> None:
        """Append a streamed text chunk and re-render the markdown."""
        self._text += chunk
        self.view.setHtml(render_md(self._text))
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def clear(self) -> None:
        """Clear the answer area."""
        self._text = ""
        self.view.clear()


if __name__ == "__main__":
    import sys

    from PyQt6.QtCore import QTimer

    DEMO = "# Hello\nThis is **streaming** markdown:\n\n```python\nprint('hi')\n```\n"
    app = QApplication(sys.argv)
    win = OverlayWindow()
    win.show()
    win.screenshot_clicked.connect(lambda: print("screenshot clicked"))
    win.mic_clicked.connect(lambda: print("mic clicked"))
    win.text_submitted.connect(lambda t: print("text:", t))
    chunks = iter([DEMO[i : i + 6] for i in range(0, len(DEMO), 6)])
    timer = QTimer()

    def tick() -> None:
        """Stream the next demo chunk, stop when done."""
        chunk = next(chunks, None)
        win.append_chunk(chunk) if chunk else timer.stop()

    timer.timeout.connect(tick)
    timer.start(60)
    sys.exit(app.exec())