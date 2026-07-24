"""Translation integrity and localized desktop construction tests."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import pytest
from PySide6.QtCore import QLocale, Qt, QTranslator
from PySide6.QtWidgets import QApplication

from analysis.raw_peak import RawPeakAnalyzer
from core import __version__
from core.configuration import ApplicationSettings, MaterialDatabase, application_root
from core.importing.service import SpectrumImportService
from core.workspace import Workspace
from export.peak_table import PeakTableExporter
from ui.localization import AppLanguage, TranslationLoadError, install_translations
from ui.main_window import MainWindow

PROJECT_ROOT = Path(__file__).resolve().parents[1]
I18N_ROOT = PROJECT_ROOT / "resources" / "i18n"
PLACEHOLDER_PATTERN = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


def test_supported_language_codes_are_strict_and_normalized() -> None:
    """Build and runtime locale spellings must resolve deterministically."""

    assert AppLanguage.parse("en-US") is AppLanguage.EN_US
    assert AppLanguage.parse("zh_CN") is AppLanguage.ZH_CN
    with pytest.raises(ValueError, match="Unsupported application language"):
        AppLanguage.parse("fr_FR")


def test_chinese_translation_sources_are_complete_and_placeholder_safe() -> None:
    """Every extracted source must have a finished, placeholder-compatible translation."""

    tree = ElementTree.parse(I18N_ROOT / "pl_analyzer_zh_CN.ts")
    messages = tree.findall(".//message")
    assert len(messages) >= 200

    for message in messages:
        source = message.findtext("source")
        translation = message.find("translation")
        assert source
        assert translation is not None
        assert translation.get("type") != "unfinished"
        assert translation.text
        assert set(PLACEHOLDER_PATTERN.findall(source)) == set(
            PLACEHOLDER_PATTERN.findall(translation.text)
        )


def test_required_qm_catalogs_load() -> None:
    """Both application and Qt standard-control catalogs must be deployable."""

    for filename in ("pl_analyzer_zh_CN.qm", "qtbase_zh_CN.qm"):
        translator = QTranslator()
        assert translator.load(str(I18N_ROOT / filename))


def test_missing_chinese_catalog_is_a_startup_error(
    qapp: QApplication,
    tmp_path: Path,
) -> None:
    """A localized release must never silently fall back to an English UI."""

    with pytest.raises(TranslationLoadError, match="could not be loaded"):
        install_translations(qapp, AppLanguage.ZH_CN, tmp_path)


def test_chinese_main_window_uses_translated_presentation(
    qtbot: pytest.FixtureRequest,
    qapp: QApplication,
) -> None:
    """The Chinese catalog must affect menus, title, and scientific table chrome."""

    root = application_root()
    installed = install_translations(qapp, AppLanguage.ZH_CN, root)
    settings = ApplicationSettings.from_json(root / "config" / "default_settings.json")
    materials = MaterialDatabase.from_json(root / "config" / "materials.json")
    window = MainWindow(
        workspace=Workspace(settings.plot),
        importer=SpectrumImportService(),
        analyzer=RawPeakAnalyzer(),
        exporter=PeakTableExporter(),
        material_database=materials,
        analysis_defaults=settings.analysis,
    )
    qtbot.addWidget(window)
    try:
        assert window.windowTitle() == f"未命名 — PL Analyzer Pro v{__version__}"
        assert window.menuBar().actions()[0].text() == "文件(&F)"
        assert (
            window._peak_panel._material_model.headerData(
                0,
                Qt.Orientation.Horizontal,
            )
            == "材料"
        )
        assert window._plot_widget._axes.get_xlabel() == "波长 (nm)"
    finally:
        window.close()
        for translator in reversed(installed.translators):
            qapp.removeTranslator(translator)
        QLocale.setDefault(QLocale(AppLanguage.EN_US.value))
