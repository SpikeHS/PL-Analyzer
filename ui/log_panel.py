"""Bottom operator log that remains available after recoverable errors."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QT_TRANSLATE_NOOP
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class LogPanel(QPlainTextEdit):
    """Timestamped, read-only in-application event log."""

    _LEVEL_LABELS = {
        "info": QT_TRANSLATE_NOOP("LogPanel", "INFO"),
        "warning": QT_TRANSLATE_NOOP("LogPanel", "WARNING"),
        "error": QT_TRANSLATE_NOOP("LogPanel", "ERROR"),
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)
        self.setPlaceholderText(self.tr("Application events will appear here."))

    def write(self, level: str, message: str) -> None:
        """Append one concise operator-facing event."""

        timestamp = datetime.now().strftime("%H:%M:%S")
        source_label = self._LEVEL_LABELS.get(level.casefold(), level.upper())
        translated_label = self.tr(source_label)
        self.appendPlainText(f"{timestamp}  {translated_label:<7}  {message}")
