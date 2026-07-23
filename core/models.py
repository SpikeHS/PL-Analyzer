"""Domain models shared by import, analysis, plotting, and presentation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

FloatArray = NDArray[np.float64]


class AmplitudeMode(StrEnum):
    """Available non-destructive intensity display transforms."""

    RAW = "raw"
    NORMALIZE = "normalize"


class AxisScale(StrEnum):
    """Supported vertical-axis scales."""

    LINEAR = "linear"
    LOG = "log"


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """Traceability information for an imported spectrum."""

    file_path: str
    sheet_name: str | None
    wavelength_column: str
    intensity_column: str


@dataclass(slots=True)
class DisplayStyle:
    """Mutable presentation state kept separate from raw spectral data."""

    color: str = ""
    visible: bool = True


@dataclass(slots=True)
class SpectrumSeries:
    """A single immutable raw PL spectrum and its mutable display metadata."""

    spectrum_id: str
    name: str
    wavelength_nm: FloatArray
    intensity_au: FloatArray
    source: SourceInfo
    display: DisplayStyle = field(default_factory=DisplayStyle)
    diagnostics: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        wavelength_nm = np.asarray(self.wavelength_nm, dtype=np.float64)
        intensity_au = np.asarray(self.intensity_au, dtype=np.float64)

        if wavelength_nm.ndim != 1 or intensity_au.ndim != 1:
            raise ValueError("Spectrum arrays must be one-dimensional.")
        if wavelength_nm.size != intensity_au.size:
            raise ValueError("Wavelength and intensity arrays must have equal length.")
        if wavelength_nm.size < 3:
            raise ValueError("A spectrum must contain at least three points.")
        if not np.all(np.isfinite(wavelength_nm)) or not np.all(np.isfinite(intensity_au)):
            raise ValueError("Stored spectrum arrays must contain only finite values.")
        if np.any(np.diff(wavelength_nm) <= 0):
            raise ValueError("Stored wavelength values must be strictly increasing.")

        wavelength_nm.setflags(write=False)
        intensity_au.setflags(write=False)
        self.wavelength_nm = wavelength_nm
        self.intensity_au = intensity_au


@dataclass(frozen=True, slots=True)
class PeakResult:
    """One peak measured directly from raw sampled data."""

    position_nm: float
    height_au: float
    fwhm_nm: float | None
    prominence_au: float
    width_level_au: float | None
    quality_flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PeakAnalysisResult:
    """All peaks and diagnostics produced for one spectrum."""

    peaks: tuple[PeakResult, ...]
    effective_prominence_au: float
    diagnostics: tuple[str, ...]
    algorithm_version: int = 1


@dataclass(frozen=True, slots=True)
class MaterialSearchWindow:
    """One material-labelled wavelength interval selected for analysis."""

    material_id: str
    material_name: str
    min_nm: float
    max_nm: float

    def __post_init__(self) -> None:
        if not self.material_id.strip() or not self.material_name.strip():
            raise ValueError("Material search windows require an ID and display name.")
        if not np.isfinite(self.min_nm) or not np.isfinite(self.max_nm):
            raise ValueError("Material search window bounds must be finite.")
        if self.min_nm <= 0:
            raise ValueError("Material search minimum must be positive.")
        if self.min_nm >= self.max_nm:
            raise ValueError("Material search minimum must be smaller than maximum.")


@dataclass(frozen=True, slots=True)
class MaterialPeakAnalysis:
    """Raw peak results for one spectrum and one material window."""

    window: MaterialSearchWindow
    result: PeakAnalysisResult


@dataclass(slots=True)
class PlotDisplaySettings:
    """Current plot presentation settings."""

    amplitude_mode: AmplitudeMode = AmplitudeMode.RAW
    offset_enabled: bool = False
    y_scale: AxisScale = AxisScale.LINEAR
    legend_visible: bool = True
    grid_visible: bool = True


@dataclass(frozen=True, slots=True)
class PeakTableRecord:
    """Flattened peak result used by table and export adapters."""

    sample_name: str
    material_names: tuple[str, ...]
    peak_number: int
    position_nm: float
    height_au: float
    fwhm_nm: float | None
    prominence_au: float
    quality_flags: tuple[str, ...]
