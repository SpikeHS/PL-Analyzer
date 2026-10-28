"""Excel exporter for the operator-checked PL curves.

Each checked curve becomes one complete numeric sheet (every wavelength and
intensity point, in stored order) so the workbook is directly usable for
replotting or further analysis. When peaks were accepted, a trailing ``Peaks``
sheet lists exactly those rows; no summary or overview sheet is produced.

Only the curves passed in are written, so the caller decides the selection
(the Samples list checkboxes). The adapter never mutates spectra and never
performs any scientific transformation: intensities are the imported
``intensity_au`` values.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from core.errors import ExportError
from core.models import PeakTableRecord, SpectrumSeries
from export._atomic import remove_if_present, temporary_path

if TYPE_CHECKING:
    from openpyxl import Workbook
    from openpyxl.worksheet.worksheet import Worksheet


class SpectrumTableExporter:
    """Export the complete data of every checked curve and its accepted peaks."""

    _PEAK_SHEET = "Peaks"
    _DATA_HEADERS = ("Wavelength (nm)", "Intensity (a.u.)")
    _PEAK_HEADERS = (
        "Sample",
        "Material",
        "Peak",
        "Position (nm)",
        "Height (a.u.)",
        "FWHM (nm)",
        "Prominence (a.u.)",
        "Quality Flags",
    )
    # Excel allows 1,048,576 rows per sheet; keep headroom for the header row.
    _MAX_DATA_ROWS = 1_048_000

    def export(
        self,
        spectra: Sequence[SpectrumSeries],
        path: Path,
        *,
        peak_records: Iterable[PeakTableRecord] = (),
    ) -> None:
        """Write the checked curves and accepted peaks to one ``.xlsx`` file."""

        ordered_spectra = tuple(spectra)
        if not ordered_spectra:
            raise ExportError(
                "There are no checked spectra to export.",
                code="E_EXPORT_NO_RESULTS",
            )
        if path.suffix.casefold() != ".xlsx":
            raise ExportError(
                f"Unsupported spectrum export format: {path.suffix}",
                code="E_EXPORT_FORMAT",
            )
        self._export_xlsx(ordered_spectra, path, tuple(peak_records))

    def _export_xlsx(
        self,
        spectra: Sequence[SpectrumSeries],
        path: Path,
        peak_records: Sequence[PeakTableRecord],
    ) -> None:
        try:
            from openpyxl import Workbook
        except ImportError as exc:
            raise ExportError(
                "Excel export requires openpyxl.",
                code="E_EXPORT_DEPENDENCY",
            ) from exc

        accepted_records = tuple(record for record in peak_records if record.included)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = temporary_path(path)
        try:
            workbook = Workbook()
            workbook.remove(workbook.active)
            used_names: set[str] = set()
            if accepted_records:
                used_names.add(self._PEAK_SHEET.casefold())
            for spectrum in spectra:
                self._write_spectrum_sheets(workbook, spectrum, used_names)
            if accepted_records:
                self._write_peak_sheet(workbook, accepted_records)
            workbook.save(temp_path)
            os.replace(temp_path, path)
        except Exception as exc:
            remove_if_present(temp_path)
            if isinstance(exc, ExportError):
                raise
            raise ExportError(
                f"Unable to export spectra to Excel: {path.name}",
                code="E_EXPORT_WRITE",
                detail=str(exc),
            ) from exc

    def _write_spectrum_sheets(
        self,
        workbook: Workbook,
        spectrum: SpectrumSeries,
        used_names: set[str],
    ) -> None:
        wavelengths = spectrum.wavelength_nm.tolist()
        intensities = spectrum.intensity_au.tolist()
        for start in range(0, len(wavelengths), self._MAX_DATA_ROWS):
            stop = min(start + self._MAX_DATA_ROWS, len(wavelengths))
            worksheet = workbook.create_sheet(_unique_sheet_name(spectrum.name, used_names))
            _write_header(worksheet, self._DATA_HEADERS)
            for wavelength, intensity in zip(
                wavelengths[start:stop],
                intensities[start:stop],
                strict=True,
            ):
                worksheet.append((wavelength, intensity))
            _set_widths(worksheet, (20, 22))

    def _write_peak_sheet(
        self,
        workbook: Workbook,
        accepted_records: Sequence[PeakTableRecord],
    ) -> None:
        # ``_PEAK_SHEET`` is reserved before the curve sheets are written, so it
        # always keeps its canonical name even when a sample is called "Peaks".
        worksheet = workbook.create_sheet(self._PEAK_SHEET)
        _write_header(worksheet, self._PEAK_HEADERS)
        for record in accepted_records:
            worksheet.append(
                (
                    record.sample_name,
                    ", ".join(record.material_names),
                    record.peak_number,
                    record.position_nm,
                    record.height_au,
                    record.fwhm_nm,
                    record.prominence_au,
                    ", ".join(record.quality_flags),
                )
            )
        _set_widths(worksheet, (24, 22, 9, 16, 18, 14, 20, 28))


def _write_header(worksheet: Worksheet, headers: Sequence[str]) -> None:
    from openpyxl.styles import Font, PatternFill

    worksheet.append(tuple(headers))
    for cell in worksheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="24527A")
    worksheet.freeze_panes = "A2"


def _set_widths(worksheet: Worksheet, widths: Sequence[float]) -> None:
    for column_index, width in enumerate(widths, start=1):
        letter = worksheet.cell(row=1, column=column_index).column_letter
        worksheet.column_dimensions[letter].width = width


def _unique_sheet_name(base: str, used_names: set[str]) -> str:
    """Return a valid, unique Excel sheet name derived from the sample name."""

    cleaned = _sanitize_sheet_name(base) or "Spectrum"
    candidate = cleaned[:31]
    suffix = 2
    while candidate.casefold() in used_names:
        tail = f" ({suffix})"
        candidate = f"{cleaned[: 31 - len(tail)]}{tail}"
        suffix += 1
    used_names.add(candidate.casefold())
    return candidate


def _sanitize_sheet_name(value: str) -> str:
    """Strip characters Excel rejects and clamp to the 31-character limit."""

    forbidden = "[]:*?/\\"
    translation = str.maketrans({character: "-" for character in forbidden})
    cleaned = " ".join(value.translate(translation).split())
    return cleaned.strip("' ")[:31]
