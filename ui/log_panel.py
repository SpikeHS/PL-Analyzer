"""Bottom operator log that remains available after recoverable errors."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QPlainTextEdit, QWidget


class LogPanel(QPlainTextEdit):
    """Timestamped, read-only in-application event log."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(2000)
        self.setPlaceholderText("Application events will appear here.")

    def write(self, level: str, message: str) -> None:
        """Append one concise operator-facing event."""

        timestamp = datetime.now().strftime("%H:%M:%S")
        self.appendPlainText(f"{timestamp}  {level.upper():<7}  {message}")
