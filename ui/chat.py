"""Chat window with scrollable history and streaming replies."""

from __future__ import annotations

from html import escape

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QApplication, QLineEdit, QTextBrowser, QVBoxLayout, QWidget

from ui.overlay import render_md


class ChatWindow(QWidget):
    """Conversation history; call add_message() then append_chunk() to stream."""

    message_sent = pyqtSignal(str)

    def __init__(self) -> None:
        """Build the history view and input box."""
        super().__init__()
        self.setWindowTitle("CUE Chat")
        self.resize(520, 640)
        self.history: list[list[str]] = []  # [role, text]
        self.view = QTextBrowser(openExternalLinks=True)
        self.input = QLineEdit(placeholderText="Ask CUE...")
        self.input.returnPressed.connect(self._send)
        lay = QVBoxLayout(self)
        lay.addWidget(self.view)
        lay.addWidget(self.input)

    def _send(self) -> None:
        """Add the typed text as a user message and emit it."""
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.add_message("user", text)
            self.message_sent.emit(text)

    def add_message(self, role: str, text: str = "") -> None:
        """Start a new message ('user' or 'assistant')."""
        self.history.append([role, text])
        self._render()

    def append_chunk(self, chunk: str) -> None:
        """Append a streamed chunk to the latest message."""
        if not self.history:
            self.add_message("assistant")
        self.history[-1][1] += chunk
        self._render()

    def clear(self) -> None:
        """Erase the history."""
        self.history.clear()
        self._render()

    def _render(self) -> None:
        """Re-render all messages and scroll to the bottom."""
        html = "".join(
            f"<p><b>{'You' if r == 'user' else 'CUE'}</b></p>"
            + (f"<p>{escape(t)}</p>" if r == "user" else render_md(t))
            + "<hr>"
            for r, t in self.history
        )
        self.view.setHtml(html)
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    win = ChatWindow()

    def echo(text: str) -> None:
        """Fake assistant reply for the demo."""
        win.add_message("assistant")
        win.append_chunk(f"You said **{text}**\n\n```python\nprint('ok')\n```")

    win.message_sent.connect(echo)
    win.show()
    sys.exit(app.exec())