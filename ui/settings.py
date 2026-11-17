"""Settings dialog: edit key options and save them to .env."""

from __future__ import annotations

from dataclasses import replace

from dotenv import set_key
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QWidget,
)

from config import CHOICES, Settings

# (env var, label, Settings attribute)
COMBOS = [
    ("SPEECH_PROVIDER", "Speech provider", "speech_provider"),
    ("WHISPER_CAPTURE_MODE", "Capture mode", "whisper_capture_mode"),
    ("WHISPER_RESPONSE_TARGET", "Response target", "whisper_response_target"),
]


class SettingsDialog(QDialog):
    """Edit API key, speech provider, capture mode and response target."""

    def __init__(self, settings: Settings, env_path: str = ".env", parent: QWidget | None = None) -> None:
        """Fill the form from current settings."""
        super().__init__(parent)
        self.setWindowTitle("CUE Settings")
        self._base, self.env_path = settings, env_path
        self.key = QLineEdit(settings.gemini_api_key)
        self.key.setEchoMode(QLineEdit.EchoMode.Password)
        form = QFormLayout(self)
        form.addRow("Gemini API key", self.key)
        self.combos: dict[str, QComboBox] = {}
        for env, label, attr in COMBOS:
            box = QComboBox()
            box.addItems(CHOICES[env])
            box.setCurrentText(getattr(settings, attr))
            self.combos[attr] = box
            form.addRow(label, box)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def settings(self) -> Settings:
        """Return Settings built from the current form values."""
        return replace(
            self._base,
            gemini_api_key=self.key.text().strip(),
            **{attr: box.currentText() for attr, box in self.combos.items()},
        )

    def _save(self) -> None:
        """Write values to .env and close (API key is required)."""
        s = self.settings()
        if not s.gemini_api_key:
            self.key.setFocus()
            return
        set_key(self.env_path, "GEMINI_API_KEY", s.gemini_api_key)
        for env, _, attr in COMBOS:
            set_key(self.env_path, env, getattr(s, attr))
        self.accept()


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    dlg = SettingsDialog(Settings(gemini_api_key="demo"), env_path="demo.env")
    if dlg.exec():
        print("saved:", dlg.settings(), "-> demo.env")