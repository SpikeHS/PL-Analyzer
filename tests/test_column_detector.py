"""Automatic column detection and sanitization tests."""

from __future__ import annotations

import numpy as np

from core.importing.column_detector import ColumnDetector


def test_detects_chinese_headers_and_sorts_data() -> None:
    rows = [
        ("Operator", "MBE"),
        ("波长 (nm)", "PL 强度 (a.u.)"),
        (900, 1),
        (880, 8),
        (890, 4),
    ]
    detector = ColumnDetector()

    detection = detector.detect(rows)
    prepared = detector.prepare(rows, detection)

    assert detection.wavelength_column == 0
    assert detection.intensity_column == 1
    np.testing.assert_allclose(prepared.wavelength_nm, [880, 890, 900])
    np.testing.assert_allclose(prepared.intensity_au, [8, 4, 1])
    assert "WAVELENGTH_SORTED" in prepared.diagnostics


def test_numeric_fallback_and_duplicate_wavelength_average() -> None:
    rows = [
        (860, 1),
        (870, 3),
        (870, 5),
        (880, 9),
        (890, 2),
    ]
    detector = ColumnDetector()

    detection = detector.detect(rows)
    prepared = detector.prepare(rows, detection)

    assert detection.data_start_row == 0
    np.testing.assert_allclose(prepared.wavelength_nm, [860, 870, 880, 890])
    np.testing.assert_allclose(prepared.intensity_au, [1, 4, 9, 2])
    assert "DUPLICATE_WAVELENGTH_AVERAGED" in prepared.diagnostics
