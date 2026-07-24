"""Sample visibility model regression tests."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from core.models import SourceInfo, SpectrumSeries
from ui.sample_panel import SampleListModel


def test_sample_visibility_accepts_qt_check_state_values(qapp: object) -> None:
    """The model must handle both enum and integer check-state payloads."""

    spectrum = SpectrumSeries(
        spectrum_id="sample-1",
        name="AGA017",
        wavelength_nm=np.array([860.0, 870.0, 880.0]),
        intensity_au=np.array([1.0, 3.0, 1.0]),
        source=SourceInfo(
            file_path="C:/data/AGA017.csv",
            sheet_name=None,
            wavelength_column="Wavelength",
            intensity_column="Intensity",
        ),
    )
    model = SampleListModel()
    model.replace([spectrum])
    index = model.index(0, 0)
    changes: list[tuple[str, bool]] = []
    model.visibility_changed.connect(
        lambda spectrum_id, visible: changes.append((spectrum_id, visible))
    )

    assert model.setData(
        index,
        Qt.CheckState.Unchecked,
        Qt.ItemDataRole.CheckStateRole,
    )
    assert spectrum.display.visible is False
    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Unchecked

    assert model.setData(
        index,
        Qt.CheckState.Checked.value,
        Qt.ItemDataRole.CheckStateRole,
    )
    assert spectrum.display.visible is True
    assert model.data(index, Qt.ItemDataRole.CheckStateRole) == Qt.CheckState.Checked
    assert changes == [("sample-1", False), ("sample-1", True)]

    for invalid_value in ("not-a-check-state", True, 3):
        assert (
            model.setData(
                index,
                invalid_value,
                Qt.ItemDataRole.CheckStateRole,
            )
            is False
        )
        assert spectrum.display.visible is True
