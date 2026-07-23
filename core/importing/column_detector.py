"""Automatic wavelength/intensity column detection shared by every reader."""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from core.errors import DataImportError


@dataclass(frozen=True, slots=True)
class ColumnDetection:
    """Detected source column indexes and traceability labels."""

    wavelength_column: int
    intensity_column: int
    data_start_row: int
    wavelength_label: str
    intensity_label: str
    confidence: float


@dataclass(frozen=True, slots=True)
class PreparedSpectrumColumns:
    """Validated, sorted arrays produced from detected columns."""

    wavelength_nm: NDArray[np.float64]
    intensity_au: NDArray[np.float64]
    diagnostics: tuple[str, ...]


class ColumnDetector:
    """Detect spectral columns from aliases, then numeric structure."""

    def detect(self, rows: Sequence[Sequence[Any]]) -> ColumnDetection:
        """Return the most credible wavelength and intensity columns."""

        if not rows:
            raise DataImportError(
                "The sheet is empty.",
                code="E_IMPORT_EMPTY_SHEET",
            )

        header_detection = self._detect_from_headers(rows)
        if header_detection is not None:
            return header_detection

        numeric_detection = self._detect_from_numeric_structure(rows)
        if numeric_detection is not None:
            return numeric_detection

        raise DataImportError(
            "Could not identify distinct wavelength and intensity columns.",
            code="E_IMPORT_COLUMNS_NOT_FOUND",
            detail="Use recognizable headers such as Wavelength (nm) and Intensity (a.u.).",
        )

    def prepare(
        self,
        rows: Sequence[Sequence[Any]],
        detection: ColumnDetection,
    ) -> PreparedSpectrumColumns:
        """Extract finite pairs, sort wavelengths, and merge duplicate wavelengths."""

        wavelengths: list[float] = []
        intensities: list[float] = []
        skipped_rows = 0

        for row in rows[detection.data_start_row :]:
            wavelength_cell = (
                row[detection.wavelength_column] if detection.wavelength_column < len(row) else None
            )
            intensity_cell = (
                row[detection.intensity_column] if detection.intensity_column < len(row) else None
            )
            wavelength = _as_finite_float(wavelength_cell)
            intensity = _as_finite_float(intensity_cell)
            if wavelength is None or intensity is None:
                if wavelength_cell not in (None, "") or intensity_cell not in (None, ""):
                    skipped_rows += 1
                continue
            wavelengths.append(wavelength)
            intensities.append(intensity)

        if len(wavelengths) < 3:
            raise DataImportError(
                "Fewer than three valid wavelength/intensity rows were found.",
                code="E_IMPORT_TOO_FEW_POINTS",
            )

        wavelength_array = np.asarray(wavelengths, dtype=np.float64)
        intensity_array = np.asarray(intensities, dtype=np.float64)
        diagnostics: list[str] = []

        order = np.argsort(wavelength_array, kind="stable")
        if not np.array_equal(order, np.arange(order.size)):
            diagnostics.append("WAVELENGTH_SORTED")
        wavelength_array = wavelength_array[order]
        intensity_array = intensity_array[order]

        unique_wavelengths, inverse, counts = np.unique(
            wavelength_array,
            return_inverse=True,
            return_counts=True,
        )
        if np.any(counts > 1):
            sums = np.bincount(inverse, weights=intensity_array)
            intensity_array = sums / counts
            wavelength_array = unique_wavelengths
            diagnostics.append("DUPLICATE_WAVELENGTH_AVERAGED")

        if wavelength_array.size < 3:
            raise DataImportError(
                "Fewer than three unique wavelength values were found.",
                code="E_IMPORT_TOO_FEW_UNIQUE_POINTS",
            )
        if skipped_rows:
            diagnostics.append(f"SKIPPED_ROWS:{skipped_rows}")

        return PreparedSpectrumColumns(
            wavelength_nm=wavelength_array,
            intensity_au=intensity_array,
            diagnostics=tuple(diagnostics),
        )

    def _detect_from_headers(
        self,
        rows: Sequence[Sequence[Any]],
    ) -> ColumnDetection | None:
        best: tuple[float, int, int, int, str, str] | None = None
        for row_index, row in enumerate(rows[:30]):
            wavelength_scores = [
                (self._wavelength_header_score(cell), column_index)
                for column_index, cell in enumerate(row)
            ]
            intensity_scores = [
                (self._intensity_header_score(cell), column_index)
                for column_index, cell in enumerate(row)
            ]
            for wavelength_score, wavelength_column in wavelength_scores:
                for intensity_score, intensity_column in intensity_scores:
                    if wavelength_column == intensity_column:
                        continue
                    if wavelength_score < 5 or intensity_score < 5:
                        continue
                    score = wavelength_score + intensity_score
                    candidate = (
                        score,
                        row_index,
                        wavelength_column,
                        intensity_column,
                        _cell_label(row[wavelength_column], wavelength_column),
                        _cell_label(row[intensity_column], intensity_column),
                    )
                    if best is None or candidate[0] > best[0]:
                        best = candidate

        if best is None:
            return None
        score, row_index, wavelength_column, intensity_column, wavelength_label, intensity_label = (
            best
        )
        return ColumnDetection(
            wavelength_column=wavelength_column,
            intensity_column=intensity_column,
            data_start_row=row_index + 1,
            wavelength_label=wavelength_label,
            intensity_label=intensity_label,
            confidence=min(score / 20.0, 1.0),
        )

    def _detect_from_numeric_structure(
        self,
        rows: Sequence[Sequence[Any]],
    ) -> ColumnDetection | None:
        column_count = max((len(row) for row in rows), default=0)
        numeric_columns: dict[int, list[tuple[int, float]]] = {}
        for column_index in range(column_count):
            values: list[tuple[int, float]] = []
            for row_index, row in enumerate(rows):
                cell = row[column_index] if column_index < len(row) else None
                number = _as_finite_float(cell)
                if number is not None:
                    values.append((row_index, number))
            if len(values) >= 3:
                numeric_columns[column_index] = values

        if len(numeric_columns) < 2:
            return None

        wavelength_candidates: list[tuple[float, int]] = []
        for column_index, indexed_values in numeric_columns.items():
            values = np.asarray([value for _, value in indexed_values], dtype=np.float64)
            differences = np.diff(values)
            nonzero_differences = differences[differences != 0]
            if nonzero_differences.size == 0:
                continue
            increasing_ratio = float(np.mean(nonzero_differences > 0))
            decreasing_ratio = float(np.mean(nonzero_differences < 0))
            monotonic_ratio = max(increasing_ratio, decreasing_ratio)
            span = float(np.ptp(values))
            unique_ratio = float(np.unique(values).size / values.size)
            if monotonic_ratio < 0.8 or span <= 0 or unique_ratio < 0.8:
                continue
            median = float(np.median(values))
            plausible_wavelength = 100.0 <= median <= 5000.0
            coverage = min(values.size / 20.0, 1.0)
            score = (5.0 * monotonic_ratio) + (2.0 * unique_ratio) + coverage
            if plausible_wavelength:
                score += 3.0
            wavelength_candidates.append((score, column_index))

        if not wavelength_candidates:
            return None
        wavelength_candidates.sort(reverse=True)

        for wavelength_score, wavelength_column in wavelength_candidates:
            intensity_choices: list[tuple[float, int, int]] = []
            wavelength_rows = dict(numeric_columns[wavelength_column])
            for intensity_column, indexed_values in numeric_columns.items():
                if intensity_column == wavelength_column:
                    continue
                paired = [
                    (row_index, value)
                    for row_index, value in indexed_values
                    if row_index in wavelength_rows
                ]
                if len(paired) < 3:
                    continue
                intensity_values = np.asarray([value for _, value in paired], dtype=np.float64)
                if float(np.ptp(intensity_values)) <= 0:
                    continue
                pair_count = len(paired)
                variability = math.log10(float(np.std(intensity_values)) + 1.0)
                intensity_choices.append((pair_count + variability, intensity_column, pair_count))

            if not intensity_choices:
                continue
            intensity_choices.sort(reverse=True)
            _, intensity_column, pair_count = intensity_choices[0]
            wavelength_rows_set = set(wavelength_rows)
            intensity_rows_set = {row for row, _ in numeric_columns[intensity_column]}
            paired_rows = sorted(wavelength_rows_set & intensity_rows_set)
            if len(paired_rows) < 3:
                continue
            return ColumnDetection(
                wavelength_column=wavelength_column,
                intensity_column=intensity_column,
                data_start_row=paired_rows[0],
                wavelength_label=f"Column {wavelength_column + 1}",
                intensity_label=f"Column {intensity_column + 1}",
                confidence=min(0.55 + 0.02 * pair_count + 0.02 * wavelength_score, 0.85),
            )
        return None

    @staticmethod
    def _wavelength_header_score(cell: Any) -> float:
        normalized = _normalize_header(cell)
        if not normalized:
            return 0.0
        score = 0.0
        if "wavelength" in normalized or "波长" in normalized:
            score += 10.0
        if "lambda" in normalized or normalized in {"wl", "λ"}:
            score += 8.0
        if "nm" in normalized:
            score += 2.0
        return score

    @staticmethod
    def _intensity_header_score(cell: Any) -> float:
        normalized = _normalize_header(cell)
        if not normalized:
            return 0.0
        score = 0.0
        if "intensity" in normalized or "强度" in normalized:
            score += 10.0
        if any(token in normalized for token in ("counts", "count", "计数", "signal", "cps")):
            score += 8.0
        if normalized in {"pl", "plintensity", "i"}:
            score += 7.0
        if "a.u" in normalized or "arb" in normalized:
            score += 2.0
        return score


def _normalize_header(value: Any) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    return re.sub(r"[\s_\-()\[\]{}]+", "", text)


def _cell_label(value: Any, column_index: int) -> str:
    text = str(value).strip() if value is not None else ""
    return text or f"Column {column_index + 1}"


def _as_finite_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
    else:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
    return number if math.isfinite(number) else None
