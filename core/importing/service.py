"""Application service for resilient multi-file, multi-sheet imports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from core.errors import DataImportError
from core.models import SourceInfo, SpectrumSeries

from .column_detector import ColumnDetection, ColumnDetector, PreparedSpectrumColumns
from .readers import ReaderRegistry, TabularSheet, TabularSheetError


@dataclass(frozen=True, slots=True)
class ImportIssue:
    """One recoverable file or sheet import failure."""

    source: str
    code: str
    message: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ImportBatchReport:
    """Successful spectra and recoverable issues from one batch."""

    spectra: tuple[SpectrumSeries, ...]
    issues: tuple[ImportIssue, ...]


@dataclass(frozen=True, slots=True)
class _DetectedSheet:
    sheet: TabularSheet
    detection: ColumnDetection
    prepared: PreparedSpectrumColumns


class SpectrumImportService:
    """Import supported files without allowing one bad source to abort a batch."""

    def __init__(
        self,
        registry: ReaderRegistry | None = None,
        detector: ColumnDetector | None = None,
    ) -> None:
        self._registry = registry or ReaderRegistry()
        self._detector = detector or ColumnDetector()

    @property
    def supported_extensions(self) -> frozenset[str]:
        """Return supported source extensions."""

        return self._registry.supported_extensions

    def import_paths(self, paths: list[Path]) -> ImportBatchReport:
        """Import every compatible sheet from every supplied path."""

        spectra: list[SpectrumSeries] = []
        issues: list[ImportIssue] = []
        for path in paths:
            try:
                sheets = self._registry.read(path)
            except DataImportError as exc:
                issues.append(
                    ImportIssue(
                        source=str(path),
                        code=exc.code,
                        message=str(exc),
                        detail=exc.detail,
                    )
                )
                continue

            detected_sheets: list[_DetectedSheet] = []
            sheet_errors: list[ImportIssue] = []
            for sheet in sheets:
                source_label = _source_label(path, sheet.name)
                if isinstance(sheet, TabularSheetError):
                    sheet_errors.append(
                        ImportIssue(
                            source=source_label,
                            code=sheet.error.code,
                            message=str(sheet.error),
                            detail=sheet.error.detail,
                        )
                    )
                    continue
                try:
                    detection = self._detector.detect(sheet.rows)
                    prepared = self._detector.prepare(sheet.rows, detection)
                    detected_sheets.append(
                        _DetectedSheet(
                            sheet=sheet,
                            detection=detection,
                            prepared=prepared,
                        )
                    )
                except DataImportError as exc:
                    sheet_errors.append(
                        ImportIssue(
                            source=source_label,
                            code=exc.code,
                            message=str(exc),
                            detail=exc.detail,
                        )
                    )

            if not detected_sheets:
                issues.extend(sheet_errors)
                if not sheet_errors:
                    issues.append(
                        ImportIssue(
                            source=str(path),
                            code="E_IMPORT_NO_SPECTRUM",
                            message="No compatible spectrum was found.",
                        )
                    )
                continue

            issues.extend(sheet_errors)
            use_sheet_suffix = len(detected_sheets) > 1
            for detected in detected_sheets:
                display_name = path.stem
                if use_sheet_suffix and detected.sheet.name:
                    display_name = f"{path.stem} / {detected.sheet.name}"
                spectra.append(
                    SpectrumSeries(
                        spectrum_id=str(uuid4()),
                        name=display_name,
                        wavelength_nm=detected.prepared.wavelength_nm,
                        intensity_au=detected.prepared.intensity_au,
                        source=SourceInfo(
                            file_path=str(path.resolve()),
                            sheet_name=detected.sheet.name,
                            wavelength_column=detected.detection.wavelength_label,
                            intensity_column=detected.detection.intensity_label,
                        ),
                        diagnostics=detected.prepared.diagnostics,
                    )
                )

        return ImportBatchReport(spectra=tuple(spectra), issues=tuple(issues))


def _source_label(path: Path, sheet_name: str | None) -> str:
    return f"{path} [{sheet_name}]" if sheet_name else str(path)
