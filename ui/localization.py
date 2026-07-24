"""Qt translation loading for language-specific desktop builds."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLocale, QTranslator


class AppLanguage(StrEnum):
    """Supported application interface languages."""

    EN_US = "en_US"
    ZH_CN = "zh_CN"

    @classmethod
    def parse(cls, value: str) -> AppLanguage:
        """Parse a locale code while accepting dash or underscore separators."""

        normalized = value.strip().replace("-", "_")
        try:
            return cls(normalized)
        except ValueError as exc:
            supported = ", ".join(language.value for language in cls)
            raise ValueError(
                f"Unsupported application language {value!r}; expected one of: {supported}."
            ) from exc


class TranslationLoadError(RuntimeError):
    """Raised when a localized release cannot load a required catalog."""


@dataclass(frozen=True, slots=True)
class InstalledTranslations:
    """Keep installed translators alive for the full application lifetime."""

    language: AppLanguage
    translators: tuple[QTranslator, ...]


def install_translations(
    app: QCoreApplication,
    language: AppLanguage,
    application_root: Path,
) -> InstalledTranslations:
    """Install Qt and application catalogs for the requested language."""

    QLocale.setDefault(QLocale(language.value))
    if language is AppLanguage.EN_US:
        return InstalledTranslations(language=language, translators=())

    translation_directory = application_root / "resources" / "i18n"
    catalog_paths = (
        translation_directory / "qtbase_zh_CN.qm",
        translation_directory / "pl_analyzer_zh_CN.qm",
    )
    translators: list[QTranslator] = []
    for catalog_path in catalog_paths:
        translator = QTranslator(app)
        if not catalog_path.is_file() or not translator.load(str(catalog_path)):
            raise TranslationLoadError(
                f"Required translation catalog could not be loaded: {catalog_path}"
            )
        if not app.installTranslator(translator):
            raise TranslationLoadError(f"Qt rejected translation catalog: {catalog_path}")
        translators.append(translator)
    return InstalledTranslations(
        language=language,
        translators=tuple(translators),
    )
