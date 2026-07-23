"""Light and dark Qt themes with persistent user preference."""

from __future__ import annotations

from enum import StrEnum

from PySide6.QtCore import QSettings
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


class ThemeMode(StrEnum):
    """Supported explicit application themes."""

    LIGHT = "light"
    DARK = "dark"


def load_theme_preference() -> ThemeMode:
    """Load the last explicit theme, defaulting safely to light."""

    value = QSettings().value("ui/theme", ThemeMode.LIGHT.value)
    try:
        return ThemeMode(str(value))
    except ValueError:
        return ThemeMode.LIGHT


def save_theme_preference(theme: ThemeMode) -> None:
    """Persist the selected theme for the next launch."""

    QSettings().setValue("ui/theme", theme.value)


def apply_theme(app: QApplication, theme: ThemeMode) -> None:
    """Apply a coherent Qt palette without changing Matplotlib data colors."""

    if theme is ThemeMode.LIGHT:
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet(
            """
            QToolTip {
                color: #202020;
                background-color: #fffbe6;
                border: 1px solid #a0a0a0;
                padding: 4px;
            }
            """
        )
        return

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#24272b"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#f0f0f0"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#191b1e"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#2d3136"))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor("#30343a"))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor("#f0f0f0"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#f0f0f0"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#30343a"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#f0f0f0"))
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.Link, QColor("#68aee8"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#356f9f"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#9aa0a6"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#777b80"))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#777b80"),
    )
    app.setPalette(palette)
    app.setStyleSheet(
        """
        QToolTip {
            color: #f0f0f0;
            background-color: #30343a;
            border: 1px solid #5d636b;
            padding: 4px;
        }
        QMenuBar, QMenu, QToolBar, QStatusBar {
            background-color: #2b2f34;
        }
        QHeaderView::section {
            background-color: #30343a;
            color: #f0f0f0;
            padding: 5px;
            border: 1px solid #454a50;
        }
        """
    )
