"""Qt-hosted Matplotlib canvas for non-destructive multi-sample comparison."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import QT_TRANSLATE_NOOP
from PySide6.QtWidgets import QVBoxLayout, QWidget

from analysis.fit_session import MaterialFitAnalysis
from core.models import (
    AmplitudeMode,
    AxisScale,
    PeakAnalysisResult,
    PlotDisplaySettings,
    SpectrumSeries,
)


class SpectrumPlotWidget(QWidget):
    """Render visible spectra without modifying their raw arrays."""

    _PLOT_FONT_FAMILY = ("Microsoft YaHei UI", "DejaVu Sans")
    _TOOLBAR_LABELS = (
        QT_TRANSLATE_NOOP("SpectrumPlotWidget", "Home"),
        QT_TRANSLATE_NOOP("SpectrumPlotWidget", "Back"),
        QT_TRANSLATE_NOOP("SpectrumPlotWidget", "Forward"),
        QT_TRANSLATE_NOOP("SpectrumPlotWidget", "Pan"),
        QT_TRANSLATE_NOOP("SpectrumPlotWidget", "Zoom"),
        QT_TRANSLATE_NOOP("SpectrumPlotWidget", "Subplots"),
        QT_TRANSLATE_NOOP("SpectrumPlotWidget", "Customize"),
        QT_TRANSLATE_NOOP("SpectrumPlotWidget", "Save"),
    )
    _TOOLBAR_TOOLTIPS = (
        QT_TRANSLATE_NOOP("SpectrumPlotWidget", "Reset original view"),
        QT_TRANSLATE_NOOP("SpectrumPlotWidget", "Back to previous view"),
        QT_TRANSLATE_NOOP("SpectrumPlotWidget", "Forward to next view"),
        QT_TRANSLATE_NOOP(
            "SpectrumPlotWidget",
            "Left button pans, Right button zooms\nx/y fixes axis, CTRL fixes aspect",
        ),
        QT_TRANSLATE_NOOP(
            "SpectrumPlotWidget",
            "Zoom to rectangle\nx/y fixes axis",
        ),
        QT_TRANSLATE_NOOP("SpectrumPlotWidget", "Configure subplots"),
        QT_TRANSLATE_NOOP(
            "SpectrumPlotWidget",
            "Edit axis, curve and image parameters",
        ),
        QT_TRANSLATE_NOOP("SpectrumPlotWidget", "Save the figure"),
    )

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._figure = Figure(layout="constrained")
        self._canvas = FigureCanvasQTAgg(self._figure)
        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        self._translate_toolbar()
        self._axes = self._figure.add_subplot(111)
        self._dark_mode = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._canvas, 1)
        self.render((), {}, PlotDisplaySettings())

    def _translate_toolbar(self) -> None:
        """Translate Matplotlib's Python-defined Qt action labels and tooltips."""

        labels = set(self._TOOLBAR_LABELS)
        tooltips = set(self._TOOLBAR_TOOLTIPS)
        for action in self._toolbar.actions():
            if action.text() in labels:
                action.setText(self.tr(action.text()))
            if action.toolTip() in tooltips:
                translated_tooltip = self.tr(action.toolTip())
                action.setToolTip(translated_tooltip)
                action.setStatusTip(translated_tooltip)

    @property
    def figure(self) -> Figure:
        """Expose the Matplotlib figure for supported file export."""

        return self._figure

    def render(
        self,
        spectra: Sequence[SpectrumSeries],
        peak_results: Mapping[str, PeakAnalysisResult],
        settings: PlotDisplaySettings,
        fit_assignments: Sequence[MaterialFitAnalysis] = (),
    ) -> None:
        """Redraw enabled spectra and raw-peak markers."""

        self._axes.clear()
        self._apply_axes_theme()
        visible_spectra = [spectrum for spectrum in spectra if spectrum.display.visible]
        if not visible_spectra:
            self._axes.text(
                0.5,
                0.5,
                self.tr("Import PL data to begin"),
                transform=self._axes.transAxes,
                ha="center",
                va="center",
                color="#777777",
                fontfamily=self._PLOT_FONT_FAMILY,
            )
            self._axes.set_xlabel(
                self.tr("Wavelength (nm)"),
                fontfamily=self._PLOT_FONT_FAMILY,
            )
            self._axes.set_ylabel(
                self.tr("Intensity (a.u.)"),
                fontfamily=self._PLOT_FONT_FAMILY,
            )
            self._axes.grid(settings.grid_visible, alpha=0.25)
            self._canvas.draw_idle()
            return

        offset_step = _offset_step(visible_spectra, settings)
        for display_index, spectrum in enumerate(visible_spectra):
            transformed = _transform_intensity(spectrum.intensity_au, settings)
            vertical_offset = offset_step * display_index if settings.offset_enabled else 0.0
            displayed = transformed + vertical_offset
            if settings.y_scale is AxisScale.LOG:
                displayed = np.where(displayed > 0, displayed, np.nan)

            self._axes.plot(
                spectrum.wavelength_nm,
                displayed,
                color=spectrum.display.color,
                linewidth=1.35,
                label=spectrum.name,
            )
            normalization_factor = _normalization_factor(
                spectrum.intensity_au,
                settings,
            )
            for assignment in fit_assignments:
                if assignment.spectrum_id != spectrum.spectrum_id:
                    continue
                fitted = assignment.result.fitted_intensity_au.astype(
                    np.float64,
                    copy=True,
                )
                if settings.amplitude_mode is AmplitudeMode.NORMALIZE:
                    fitted /= normalization_factor
                fitted += vertical_offset
                if settings.y_scale is AxisScale.LOG:
                    fitted = np.where(fitted > 0, fitted, np.nan)
                self._axes.plot(
                    assignment.result.wavelength_nm,
                    fitted,
                    color=spectrum.display.color,
                    linestyle="--",
                    linewidth=1.2,
                    alpha=0.9,
                    label=self.tr("{sample_name} — {material_name} {model_name} fit").format(
                        sample_name=spectrum.name,
                        material_name=assignment.window.material_name,
                        model_name=assignment.result.model.value,
                    ),
                )
            result = peak_results.get(spectrum.spectrum_id)
            if result is not None and result.peaks:
                peak_positions = np.asarray(
                    [peak.position_nm for peak in result.peaks],
                    dtype=np.float64,
                )
                peak_indexes = np.searchsorted(spectrum.wavelength_nm, peak_positions)
                peak_indexes = np.clip(peak_indexes, 0, spectrum.wavelength_nm.size - 1)
                marker_heights = transformed[peak_indexes] + vertical_offset
                if settings.y_scale is AxisScale.LOG:
                    valid = marker_heights > 0
                    peak_positions = peak_positions[valid]
                    marker_heights = marker_heights[valid]
                self._axes.scatter(
                    peak_positions,
                    marker_heights,
                    color=spectrum.display.color,
                    marker="x",
                    s=36,
                    linewidths=1.3,
                    zorder=4,
                )

        self._axes.set_xlabel(
            self.tr("Wavelength (nm)"),
            fontfamily=self._PLOT_FONT_FAMILY,
        )
        if settings.amplitude_mode is AmplitudeMode.NORMALIZE:
            ylabel = self.tr("Normalized intensity")
        else:
            ylabel = self.tr("Intensity (a.u.)")
        if settings.offset_enabled:
            ylabel += self.tr(" + offset")
        self._axes.set_ylabel(
            ylabel,
            fontfamily=self._PLOT_FONT_FAMILY,
        )
        self._axes.set_yscale(settings.y_scale.value)
        self._axes.grid(settings.grid_visible, alpha=0.25)
        if settings.legend_visible:
            legend = self._axes.legend(loc="best", frameon=False)
            legend_color = "#e8e8e8" if self._dark_mode else "#202020"
            for text in legend.get_texts():
                text.set_color(legend_color)
                text.set_fontfamily(self._PLOT_FONT_FAMILY)
        self._canvas.draw_idle()

    def save_figure(self, path: Path) -> None:
        """Export the current figure using Matplotlib's native backend."""

        self._figure.savefig(path, dpi=300, bbox_inches="tight")

    def set_dark_mode(self, enabled: bool) -> None:
        """Update Matplotlib chrome for the Qt theme."""

        self._dark_mode = enabled

    def _apply_axes_theme(self) -> None:
        foreground = "#e8e8e8" if self._dark_mode else "#202020"
        background = "#202328" if self._dark_mode else "#ffffff"
        self._figure.set_facecolor(background)
        self._axes.set_facecolor(background)
        self._axes.tick_params(colors=foreground)
        self._axes.xaxis.label.set_color(foreground)
        self._axes.yaxis.label.set_color(foreground)
        self._axes.title.set_color(foreground)
        for spine in self._axes.spines.values():
            spine.set_color(foreground)


def _transform_intensity(
    intensity_au: np.ndarray,
    settings: PlotDisplaySettings,
) -> np.ndarray:
    values = intensity_au.astype(np.float64, copy=True)
    if settings.amplitude_mode is AmplitudeMode.NORMALIZE:
        values /= _normalization_factor(values, settings)
    return values


def _normalization_factor(
    intensity_au: np.ndarray,
    settings: PlotDisplaySettings,
) -> float:
    if settings.amplitude_mode is not AmplitudeMode.NORMALIZE:
        return 1.0
    positive_maximum = float(np.max(intensity_au))
    denominator = positive_maximum if positive_maximum > 0 else float(np.max(np.abs(intensity_au)))
    return denominator if denominator > 0 else 1.0


def _offset_step(
    spectra: Sequence[SpectrumSeries],
    settings: PlotDisplaySettings,
) -> float:
    if not settings.offset_enabled:
        return 0.0
    if settings.amplitude_mode is AmplitudeMode.NORMALIZE:
        return 1.1
    spans = [float(np.ptp(spectrum.intensity_au)) for spectrum in spectra]
    largest_span = max(spans, default=0.0)
    if largest_span > 0:
        return largest_span * 0.15
    largest_magnitude = max(
        (float(np.max(np.abs(spectrum.intensity_au))) for spectrum in spectra),
        default=1.0,
    )
    return max(largest_magnitude * 0.15, 1.0)
