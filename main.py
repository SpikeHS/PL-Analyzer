"""PL Analyzer Pro desktop application composition root."""

from __future__ import annotations

import logging
import os
import sys
from contextlib import suppress
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import TracebackType

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from analysis.raw_peak import RawPeakAnalyzer
from core import __version__
from core.configuration import ApplicationSettings, MaterialDatabase, application_root
from core.importing.service import SpectrumImportService
from core.workspace import Workspace
from export.peak_table import PeakTableExporter
from ui.localization import AppLanguage, install_translations
from ui.main_window import MainWindow
from ui.preferences_dialog import load_analysis_preferences
from ui.theme import apply_theme, load_theme_preference


def main(language: AppLanguage = AppLanguage.EN_US) -> int:
    """Create dependencies, install error boundaries, and run the Qt event loop."""

    try:
        app = QApplication(sys.argv)
    except Exception as exc:
        _write_startup_failure_to_stderr(exc)
        return 1

    log_path: Path | None = None
    try:
        log_path = _configure_logging()
        root = application_root()
        installed_translations = install_translations(app, language, root)
        app.setApplicationName("PL Analyzer Pro")
        app.setApplicationDisplayName(QCoreApplication.translate("main", "PL Analyzer Pro"))
        app.setApplicationVersion(__version__)
        app.setOrganizationName("PL Analyzer Pro")
        app.setStyle("Fusion")
        app.setFont(QFont("Microsoft YaHei UI", 9))
        apply_theme(app, load_theme_preference())

        settings = ApplicationSettings.from_json(root / "config" / "default_settings.json")
        analysis_defaults = load_analysis_preferences(settings.analysis)
        material_database = MaterialDatabase.from_json(root / "config" / "materials.json")
        workspace = Workspace(settings.plot)
        window = MainWindow(
            workspace=workspace,
            importer=SpectrumImportService(),
            analyzer=RawPeakAnalyzer(),
            exporter=PeakTableExporter(),
            material_database=material_database,
            analysis_defaults=analysis_defaults,
        )
    except Exception as exc:
        _report_startup_failure(exc, log_path)
        return 1

    previous_hook = sys.excepthook

    def exception_hook(
        exception_type: type[BaseException],
        exception: BaseException,
        trace: TracebackType | None,
    ) -> None:
        logging.getLogger(__name__).critical(
            "Unhandled exception",
            exc_info=(exception_type, exception, trace),
        )
        window.report_unhandled_exception(exception)
        previous_hook(exception_type, exception, trace)

    sys.excepthook = exception_hook
    window.show()
    _ = installed_translations
    smoke_exit_ms = os.environ.get("PL_ANALYZER_PRO_SMOKE_EXIT_MS")
    if smoke_exit_ms is not None:
        try:
            QTimer.singleShot(max(1, int(smoke_exit_ms)), app.quit)
        except ValueError:
            logging.getLogger(__name__).warning(
                "Ignoring invalid PL_ANALYZER_PRO_SMOKE_EXIT_MS value."
            )
    return app.exec()


def _configure_logging() -> Path:
    local_data = Path.home() / "AppData" / "Local" / "PL Analyzer Pro" / "logs"
    local_data.mkdir(parents=True, exist_ok=True)
    log_path = local_data / "pl_analyzer_pro.log"
    handler = RotatingFileHandler(
        log_path,
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    logging.getLogger(__name__).info("Starting PL Analyzer Pro v%s", __version__)
    return log_path


def _report_startup_failure(error: Exception, log_path: Path | None) -> None:
    """Report a post-Qt startup failure without allowing reporting to crash."""

    with suppress(Exception):
        logging.getLogger(__name__).critical(
            "Application startup failed.",
            exc_info=(type(error), error, error.__traceback__),
        )

    if log_path is None:
        log_note = QCoreApplication.translate(
            "main",
            "Application logging was unavailable.",
        )
    else:
        log_note = QCoreApplication.translate(
            "main",
            "Log file: {path}",
        ).format(path=log_path)
    try:
        QMessageBox.critical(
            None,
            QCoreApplication.translate(
                "main",
                "PL Analyzer Pro could not start",
            ),
            f"{error}\n\n{log_note}",
        )
    except Exception as popup_error:
        _write_startup_failure_to_stderr(error, popup_error)


def _write_startup_failure_to_stderr(
    error: Exception,
    popup_error: Exception | None = None,
) -> None:
    """Use stderr as the last-resort startup diagnostic channel."""

    message = f"PL Analyzer Pro startup failed: {error}"
    if popup_error is not None:
        message += f"\nUnable to show the startup dialog: {popup_error}"
    with suppress(Exception):
        print(message, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
