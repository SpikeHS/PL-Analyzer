"""In-memory workspace that owns spectra, display state, and analysis results."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from core.models import (
    MaterialPeakAnalysis,
    MaterialSearchWindow,
    PeakAnalysisResult,
    PeakResult,
    PeakTableRecord,
    PlotDisplaySettings,
    SpectrumSeries,
)


class Workspace:
    """Mutable application model with stable sample identities."""

    _COLOR_PALETTE = (
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    )

    def __init__(self, plot_settings: PlotDisplaySettings) -> None:
        self.plot_settings = plot_settings
        self._spectra: list[SpectrumSeries] = []
        self._material_peak_results: dict[str, tuple[MaterialPeakAnalysis, ...]] = {}

    @property
    def spectra(self) -> tuple[SpectrumSeries, ...]:
        """Return spectra in operator-visible order."""

        return tuple(self._spectra)

    @property
    def peak_results(self) -> Mapping[str, PeakAnalysisResult]:
        """Return de-duplicated raw peaks keyed by spectrum ID for plotting."""

        aggregated: dict[str, PeakAnalysisResult] = {}
        for spectrum_id, analyses in self._material_peak_results.items():
            unique_peaks = _unique_peaks(
                peak for analysis in analyses for peak in analysis.result.peaks
            )
            diagnostics = tuple(
                dict.fromkeys(
                    diagnostic
                    for analysis in analyses
                    for diagnostic in analysis.result.diagnostics
                )
            )
            effective_prominence = min(
                (analysis.result.effective_prominence_au for analysis in analyses),
                default=0.0,
            )
            aggregated[spectrum_id] = PeakAnalysisResult(
                peaks=unique_peaks,
                effective_prominence_au=effective_prominence,
                diagnostics=diagnostics,
                algorithm_version=max(
                    (analysis.result.algorithm_version for analysis in analyses),
                    default=1,
                ),
            )
        return aggregated

    @property
    def material_peak_results(self) -> Mapping[str, tuple[MaterialPeakAnalysis, ...]]:
        """Return material-labelled raw peak analyses by spectrum ID."""

        return dict(self._material_peak_results)

    def add_spectra(self, spectra: Iterable[SpectrumSeries]) -> tuple[SpectrumSeries, ...]:
        """Add imported spectra while assigning unique names and stable colors."""

        added: list[SpectrumSeries] = []
        existing_names = {spectrum.name.casefold() for spectrum in self._spectra}
        for spectrum in spectra:
            spectrum.name = self._unique_name(spectrum.name, existing_names)
            existing_names.add(spectrum.name.casefold())
            if not spectrum.display.color:
                color_index = len(self._spectra) % len(self._COLOR_PALETTE)
                spectrum.display.color = self._COLOR_PALETTE[color_index]
            self._spectra.append(spectrum)
            added.append(spectrum)
        return tuple(added)

    def remove_spectra(self, spectrum_ids: Iterable[str]) -> None:
        """Remove selected spectra and their derived results."""

        identifiers = set(spectrum_ids)
        self._spectra = [
            spectrum for spectrum in self._spectra if spectrum.spectrum_id not in identifiers
        ]
        for spectrum_id in identifiers:
            self._material_peak_results.pop(spectrum_id, None)

    def set_visibility(self, spectrum_id: str, visible: bool) -> None:
        """Update one sample's display visibility."""

        self._find(spectrum_id).display.visible = visible

    def visible_spectra(self) -> tuple[SpectrumSeries, ...]:
        """Return currently enabled samples."""

        return tuple(spectrum for spectrum in self._spectra if spectrum.display.visible)

    def set_peak_results(
        self,
        results: Mapping[str, PeakAnalysisResult],
    ) -> None:
        """Compatibility adapter for unlabelled custom-window results."""

        labelled: dict[str, tuple[MaterialPeakAnalysis, ...]] = {}
        for spectrum_id, result in results.items():
            spectrum = self._find(spectrum_id)
            labelled[spectrum_id] = (
                MaterialPeakAnalysis(
                    window=MaterialSearchWindow(
                        material_id="custom",
                        material_name="Custom",
                        min_nm=float(spectrum.wavelength_nm[0]),
                        max_nm=float(spectrum.wavelength_nm[-1]),
                    ),
                    result=result,
                ),
            )
        self.set_material_peak_results(labelled)

    def set_material_peak_results(
        self,
        results: Mapping[str, tuple[MaterialPeakAnalysis, ...]],
    ) -> None:
        """Replace material-labelled results for analyzed spectra."""

        valid_ids = {spectrum.spectrum_id for spectrum in self._spectra}
        validated: dict[str, tuple[MaterialPeakAnalysis, ...]] = {}
        for spectrum_id, analyses in results.items():
            if spectrum_id not in valid_ids:
                raise KeyError(f"Unknown spectrum ID: {spectrum_id}")
            validated[spectrum_id] = tuple(analyses)
        self._material_peak_results = validated

    def clear_peak_results(self) -> None:
        """Remove every derived peak result."""

        self._material_peak_results.clear()

    def peak_table_records(self, *, visible_only: bool = True) -> tuple[PeakTableRecord, ...]:
        """Flatten current results in sample and wavelength order."""

        records: list[PeakTableRecord] = []
        for spectrum in self._spectra:
            if visible_only and not spectrum.display.visible:
                continue
            analyses = self._material_peak_results.get(spectrum.spectrum_id, ())
            if not analyses:
                continue
            grouped = _group_peaks_by_material(analyses)
            for peak_number, (peak, material_names) in enumerate(grouped, start=1):
                quality_flags = peak.quality_flags
                if len(material_names) > 1:
                    quality_flags = tuple(
                        dict.fromkeys((*quality_flags, "AMBIGUOUS_MATERIAL_ASSIGNMENT"))
                    )
                records.append(
                    PeakTableRecord(
                        sample_name=spectrum.name,
                        material_names=material_names,
                        peak_number=peak_number,
                        position_nm=peak.position_nm,
                        height_au=peak.height_au,
                        fwhm_nm=peak.fwhm_nm,
                        prominence_au=peak.prominence_au,
                        quality_flags=quality_flags,
                    )
                )
        return tuple(records)

    def _find(self, spectrum_id: str) -> SpectrumSeries:
        for spectrum in self._spectra:
            if spectrum.spectrum_id == spectrum_id:
                return spectrum
        raise KeyError(f"Unknown spectrum ID: {spectrum_id}")

    @staticmethod
    def _unique_name(base_name: str, existing_names: set[str]) -> str:
        clean_name = base_name.strip() or "Untitled sample"
        if clean_name.casefold() not in existing_names:
            return clean_name
        suffix = 2
        while f"{clean_name} [{suffix}]".casefold() in existing_names:
            suffix += 1
        return f"{clean_name} [{suffix}]"


def _unique_peaks(peaks: Iterable[PeakResult]) -> tuple[PeakResult, ...]:
    unique: list[PeakResult] = []
    for peak in sorted(peaks, key=lambda item: item.position_nm):
        if any(abs(peak.position_nm - existing.position_nm) <= 1e-9 for existing in unique):
            continue
        unique.append(peak)
    return tuple(unique)


def _group_peaks_by_material(
    analyses: tuple[MaterialPeakAnalysis, ...],
) -> tuple[tuple[PeakResult, tuple[str, ...]], ...]:
    grouped: list[tuple[PeakResult, list[str]]] = []
    for analysis in analyses:
        for peak in analysis.result.peaks:
            existing = next(
                (item for item in grouped if abs(item[0].position_nm - peak.position_nm) <= 1e-9),
                None,
            )
            if existing is None:
                grouped.append((peak, [analysis.window.material_name]))
            elif analysis.window.material_name not in existing[1]:
                existing[1].append(analysis.window.material_name)
    grouped.sort(key=lambda item: item[0].position_nm)
    return tuple((peak, tuple(names)) for peak, names in grouped)
