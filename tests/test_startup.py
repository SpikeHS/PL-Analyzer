"""Startup error-boundary tests for the desktop composition root."""

from __future__ import annotations

from pathlib import Path

import pytest

import main as app_main


def test_logging_initialization_failure_is_caught_and_shown(
    qapp: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialogs: list[tuple[str, str]] = []

    monkeypatch.setattr(app_main, "QApplication", lambda arguments: qapp)
    monkeypatch.setattr(app_main, "load_theme_preference", lambda: "light")
    monkeypatch.setattr(app_main, "apply_theme", lambda app, theme: None)

    def fail_logging() -> Path:
        raise PermissionError("log directory denied")

    def capture_dialog(parent: object, title: str, message: str) -> None:
        dialogs.append((title, message))

    monkeypatch.setattr(app_main, "_configure_logging", fail_logging)
    monkeypatch.setattr(app_main.QMessageBox, "critical", capture_dialog)

    assert app_main.main() == 1
    assert dialogs == [
        (
            "PL Analyzer Pro could not start",
            "log directory denied\n\nApplication logging was unavailable.",
        )
    ]


def test_qapplication_creation_failure_uses_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_qapplication(arguments: list[str]) -> None:
        raise RuntimeError("Qt platform unavailable")

    monkeypatch.setattr(app_main, "QApplication", fail_qapplication)

    assert app_main.main() == 1
    assert "PL Analyzer Pro startup failed: Qt platform unavailable" in capsys.readouterr().err


def test_startup_dialog_failure_falls_back_to_stderr(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fail_dialog(parent: object, title: str, message: str) -> None:
        raise RuntimeError("dialog unavailable")

    monkeypatch.setattr(app_main.QMessageBox, "critical", fail_dialog)

    app_main._report_startup_failure(RuntimeError("configuration invalid"), None)

    stderr = capsys.readouterr().err
    assert "PL Analyzer Pro startup failed: configuration invalid" in stderr
    assert "Unable to show the startup dialog: dialog unavailable" in stderr
