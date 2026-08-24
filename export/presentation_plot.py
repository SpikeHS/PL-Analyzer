"""Reference-style annotated PNG export for a single PL spectrum."""

from __future__ import annotations

import csv
import json
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator

from analysis.presentation import HC_EV_NM, PresentationAnalysis, PresentationAnalyzer
from core.errors import ExportError
from core.models import SpectrumSeries


@dataclass(frozen=True, slots=True)
class PresentationPlotStyle:
    """Versioned visual defaults derived from the original reference slide."""

    width_px: int = 2400
    height_px: int = 1500
    dpi: int = 300
    background: str = "#FFFFFF"
    navy: str = "#172235"
    teal: str = "#2B8C85"
    red: str = "#D42B34"
    raw_red: str = "#F2A1A5"
    blue: str = "#2D65A8"
    gray: str = "#5A6472"
    grid: str = "#D7DCE2"


class PresentationPlotExporter:
    """Analyze and atomically render one presentation-ready PNG."""

    def __init__(self, analyzer: PresentationAnalyzer | None = None) -> None:
        self._analyzer = analyzer or PresentationAnalyzer()

    def export(
        self,
        spectrum: SpectrumSeries,
        path: Path,
        *,
        title: str | None = None,
        smoothing_sigma_points: float = 1.5,
        show_secondary_labels: bool = True,
        style: PresentationPlotStyle | None = None,
        metrics_json_path: Path | None = None,
        processed_csv_path: Path | None = None,
    ) -> PresentationAnalysis:
        """Write a high-resolution PNG and return the explicitly named quick metrics."""

        if path.suffix.casefold() != ".png":
            raise ExportError(
                f"Reference-style export only supports PNG: {path.suffix}",
                code="E_EXPORT_FORMAT",
            )
        style = style or PresentationPlotStyle()
        if style.width_px <= 0 or style.height_px <= 0 or style.dpi <= 0:
            raise ExportError(
                "Reference plot dimensions and DPI must be positive.",
                code="E_EXPORT_PRESENTATION_STYLE",
            )
        analysis = self._analyzer.analyze(
            spectrum,
            smoothing_sigma_points=smoothing_sigma_points,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = _temporary_path(path)
        figure = _build_figure(
            spectrum,
            analysis,
            title=title,
            show_secondary_labels=show_secondary_labels,
            style=style,
        )
        try:
            figure.savefig(
                temp_path,
                format="png",
                dpi=style.dpi,
                facecolor=style.background,
                metadata={
                    "Title": title or f"PL Spectrum — {spectrum.name}",
                    "Description": (
                        "Display-assisted peak and half-height FWHM; see PL Analyzer Pro "
                        "for Raw Peak and fitted metrics."
                    ),
                },
            )
            os.replace(temp_path, path)
            if metrics_json_path is not None:
                _write_metrics_json(spectrum, analysis, metrics_json_path)
            if processed_csv_path is not None:
                _write_processed_csv(spectrum, analysis, processed_csv_path)
        except Exception as exc:
            _remove_if_present(temp_path)
            if isinstance(exc, ExportError):
                raise
            raise ExportError(
                f"Unable to export reference-style plot: {path.name}",
                code="E_EXPORT_WRITE",
                detail=str(exc),
            ) from exc
        finally:
            figure.clear()
        return analysis


def _build_figure(
    spectrum: SpectrumSeries,
    analysis: PresentationAnalysis,
    *,
    title: str | None,
    show_secondary_labels: bool,
    style: PresentationPlotStyle,
) -> Figure:
    figure = Figure(
        figsize=(style.width_px / style.dpi, style.height_px / style.dpi),
        dpi=style.dpi,
        facecolor=style.background,
    )
    axes = figure.add_axes((0.105, 0.18, 0.83, 0.68))
    font_family = ("Microsoft YaHei UI", "DejaVu Sans")
    wavelength = spectrum.wavelength_nm
    raw = spectrum.intensity_au
    smoothed = analysis.smoothed_intensity_au
    metrics = analysis.metrics

    figure.text(
        0.095,
        0.925,
        title or f"PL Spectrum — {spectrum.name}",
        color=style.navy,
        fontsize=20,
        fontweight="bold",
        fontfamily=font_family,
    )
    figure.add_artist(_teal_underline(figure, style.teal))

    axes.plot(wavelength, raw, color=style.raw_red, linewidth=0.8, alpha=0.78)
    axes.plot(wavelength, smoothed, color=style.red, linewidth=1.8)
    axes.vlines(
        metrics.peak_wavelength_nm,
        min(0.0, float(np.percentile(raw, 1))),
        metrics.peak_intensity_au,
        color=style.blue,
        linewidth=1.2,
    )
    axes.hlines(
        metrics.half_max_level_au,
        metrics.fwhm_left_nm,
        metrics.fwhm_right_nm,
        color=style.blue,
        linewidth=1.2,
        linestyles="--",
    )
    axes.plot(
        (metrics.fwhm_left_nm, metrics.fwhm_right_nm),
        (metrics.half_max_level_au, metrics.half_max_level_au),
        linestyle="None",
        marker="|",
        markersize=9,
        markeredgewidth=1.2,
        color=style.blue,
    )

    y_min = min(0.0, float(np.percentile(raw, 1)))
    y_max = max(float(np.max(raw)), float(np.max(smoothed)))
    span = max(y_max - y_min, float(np.finfo(np.float64).eps))
    axes.set_xlim(float(wavelength[0]), float(wavelength[-1]))
    axes.set_ylim(y_min, y_max + 0.08 * span)
    axes.set_xlabel("Wavelength (nm)", color=style.navy, fontfamily=font_family, fontsize=11)
    axes.set_ylabel(
        _intensity_label(spectrum),
        color=style.navy,
        fontfamily=font_family,
        fontsize=11,
    )
    axes.tick_params(colors=style.navy, labelsize=9)
    axes.xaxis.set_major_locator(MaxNLocator(nbins=7))
    axes.yaxis.set_major_locator(MaxNLocator(nbins=5))
    axes.grid(True, color=style.grid, linewidth=0.6, alpha=0.9)
    axes.set_axisbelow(True)
    for spine in axes.spines.values():
        spine.set_color(style.navy)
        spine.set_linewidth(0.8)

    annotation = (
        f"Peak {metrics.peak_wavelength_nm:.1f} nm\n"
        f"Presentation FWHM {metrics.presentation_fwhm_nm:.1f} nm\n"
        f"Energy {metrics.peak_energy_ev:.3f} eV"
    )
    peak_midpoint = 0.5 * float(wavelength[0] + wavelength[-1])
    x_offset = 26 if metrics.peak_wavelength_nm < peak_midpoint else -26
    horizontal_alignment = "left" if x_offset > 0 else "right"
    axes.annotate(
        annotation,
        xy=(metrics.peak_wavelength_nm, metrics.peak_intensity_au),
        xytext=(x_offset, -12),
        textcoords="offset points",
        ha=horizontal_alignment,
        va="top",
        color="#184A7A",
        fontsize=10,
        fontweight="bold",
        fontfamily=font_family,
    )

    if show_secondary_labels:
        for feature in metrics.secondary_features[:2]:
            if feature.relative_height < 0.04:
                continue
            feature_type = "secondary peak" if feature.relative_height >= 0.10 else "weak shoulder"
            axes.annotate(
                f"{feature_type}\n~{feature.wavelength_nm:.0f} nm",
                xy=(feature.wavelength_nm, feature.intensity_au),
                xytext=(14, 18),
                textcoords="offset points",
                color=style.gray,
                fontsize=8,
                fontfamily=font_family,
                arrowprops={"arrowstyle": "-", "color": style.gray, "linewidth": 0.7},
            )

    footer = _metadata_footer(spectrum)
    figure.text(
        0.105,
        0.065,
        footer,
        color=style.gray,
        fontsize=7.5,
        fontfamily=font_family,
    )
    return figure


def _teal_underline(figure: Figure, color: str):
    from matplotlib.lines import Line2D

    return Line2D(
        (0.095, 0.245),
        (0.895, 0.895),
        transform=figure.transFigure,
        color=color,
        linewidth=3,
        solid_capstyle="butt",
    )


def _intensity_label(spectrum: SpectrumSeries) -> str:
    return (
        "PL intensity (mV)"
        if "mv" in spectrum.source.intensity_column.casefold()
        else "PL intensity (a.u.)"
    )


def _metadata_footer(spectrum: SpectrumSeries) -> str:
    values = (
        ("Excitation", spectrum.source.metadata_value("Laser", "—")),
        ("Power", spectrum.source.metadata_value("Power", "—")),
        ("Temperature", spectrum.source.metadata_value("Temperature", "—")),
    )
    conditions = "  •  ".join(f"{label} {value}" for label, value in values)
    return f"{conditions}  •  light smoothing used only for presentation metrics"


def _write_metrics_json(
    spectrum: SpectrumSeries,
    analysis: PresentationAnalysis,
    path: Path,
) -> None:
    payload = {
        "schema_version": 1,
        "metric_semantics": (
            "Display-assisted whole-spectrum metrics. Presentation FWHM is the half height "
            "above an estimated baseline after light Gaussian smoothing; it is not Raw Peak "
            "half-prominence FWHM or model-fit FWHM."
        ),
        "sample_name": spectrum.name,
        "source_file": Path(spectrum.source.file_path).name,
        "source_metadata": {
            key: value
            for key, value in spectrum.source.metadata
            if key.strip().casefold() not in {"folder", "operator"}
        },
        "metrics": asdict(analysis.metrics),
    }
    _atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
    )


def _write_processed_csv(
    spectrum: SpectrumSeries,
    analysis: PresentationAnalysis,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_path(path)
    baseline = analysis.metrics.baseline_level_au
    baseline_corrected = np.clip(analysis.smoothed_intensity_au - baseline, 0.0, None)
    normalization = max(float(np.max(baseline_corrected)), float(np.finfo(np.float64).eps))
    try:
        with temp_path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(
                (
                    "Wavelength (nm)",
                    "Imported intensity",
                    "Display-smoothed intensity",
                    "Presentation baseline-corrected intensity",
                    "Presentation normalized intensity",
                    "Photon energy (eV)",
                )
            )
            for values in zip(
                spectrum.wavelength_nm,
                spectrum.intensity_au,
                analysis.smoothed_intensity_au,
                baseline_corrected,
                baseline_corrected / normalization,
                HC_EV_NM / spectrum.wavelength_nm,
                strict=True,
            ):
                writer.writerow(f"{float(value):.10g}" for value in values)
        os.replace(temp_path, path)
    except OSError as exc:
        _remove_if_present(temp_path)
        raise ExportError(
            f"Unable to export processed presentation data: {path.name}",
            code="E_EXPORT_WRITE",
            detail=str(exc),
        ) from exc


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _temporary_path(path)
    try:
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, path)
    except OSError as exc:
        _remove_if_present(temp_path)
        raise ExportError(
            f"Unable to export presentation metrics: {path.name}",
            code="E_EXPORT_WRITE",
            detail=str(exc),
        ) from exc


def _temporary_path(target: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    return Path(name)


def _remove_if_present(path: Path) -> None:
    with suppress(OSError):
        path.unlink(missing_ok=True)
