"""Persistent operator preferences for raw peak detection."""

from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.configuration import AnalysisDefaults


class PreferencesDialog(QDialog):
    """Edit global defaults used for subsequent Raw Peak searches."""

    def __init__(
        self,
        defaults: AnalysisDefaults,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Preferences"))

        self._relative_prominence = QDoubleSpinBox(self)
        self._relative_prominence.setRange(0.0, 100.0)
        self._relative_prominence.setDecimals(2)
        self._relative_prominence.setSuffix(" %")
        self._relative_prominence.setValue(defaults.relative_prominence * 100.0)

        self._noise_sigma = QDoubleSpinBox(self)
        self._noise_sigma.setRange(0.0, 20.0)
        self._noise_sigma.setDecimals(2)
        self._noise_sigma.setValue(defaults.noise_sigma_factor)

        self._minimum_distance = QDoubleSpinBox(self)
        self._minimum_distance.setRange(0.0, 100000.0)
        self._minimum_distance.setDecimals(4)
        self._minimum_distance.setSuffix(" nm")
        self._minimum_distance.setValue(defaults.min_distance_nm)

        self._max_peaks = QSpinBox(self)
        self._max_peaks.setRange(1, 1000)
        self._max_peaks.setValue(defaults.max_peaks)

        self._gap_factor = QDoubleSpinBox(self)
        self._gap_factor.setRange(1.01, 1000.0)
        self._gap_factor.setDecimals(2)
        self._gap_factor.setValue(defaults.gap_factor)

        form = QFormLayout()
        form.addRow(self.tr("Relative prominence"), self._relative_prominence)
        form.addRow(self.tr("Noise threshold (σ)"), self._noise_sigma)
        form.addRow(self.tr("Minimum peak distance"), self._minimum_distance)
        form.addRow(self.tr("Maximum peaks / window"), self._max_peaks)
        form.addRow(self.tr("Large-gap factor"), self._gap_factor)

        explanation = QLabel(
            self.tr(
                "These settings affect Raw Peak candidate detection only. Display "
                "Normalize, Offset and Log never alter analysis input."
            ),
            self,
        )
        explanation.setWordWrap(True)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.RestoreDefaults,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        restore_button = buttons.button(QDialogButtonBox.StandardButton.RestoreDefaults)
        restore_button.clicked.connect(lambda: self._restore(defaults))

        layout = QVBoxLayout(self)
        layout.addWidget(explanation)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def analysis_defaults(self) -> AnalysisDefaults:
        """Return validated values represented by the dialog."""

        return AnalysisDefaults(
            relative_prominence=self._relative_prominence.value() / 100.0,
            noise_sigma_factor=self._noise_sigma.value(),
            min_distance_nm=self._minimum_distance.value(),
            max_peaks=self._max_peaks.value(),
            gap_factor=self._gap_factor.value(),
        )

    def _restore(self, defaults: AnalysisDefaults) -> None:
        self._relative_prominence.setValue(defaults.relative_prominence * 100.0)
        self._noise_sigma.setValue(defaults.noise_sigma_factor)
        self._minimum_distance.setValue(defaults.min_distance_nm)
        self._max_peaks.setValue(defaults.max_peaks)
        self._gap_factor.setValue(defaults.gap_factor)


def load_analysis_preferences(fallback: AnalysisDefaults) -> AnalysisDefaults:
    """Load persisted values, falling back atomically on invalid settings."""

    settings = QSettings()
    try:
        candidate = AnalysisDefaults(
            relative_prominence=float(
                settings.value(
                    "analysis/relative_prominence",
                    fallback.relative_prominence,
                )
            ),
            noise_sigma_factor=float(
                settings.value(
                    "analysis/noise_sigma_factor",
                    fallback.noise_sigma_factor,
                )
            ),
            min_distance_nm=float(
                settings.value(
                    "analysis/min_distance_nm",
                    fallback.min_distance_nm,
                )
            ),
            max_peaks=int(settings.value("analysis/max_peaks", fallback.max_peaks)),
            gap_factor=float(settings.value("analysis/gap_factor", fallback.gap_factor)),
        )
    except (TypeError, ValueError):
        return fallback
    if (
        not 0 <= candidate.relative_prominence <= 1
        or candidate.noise_sigma_factor < 0
        or candidate.min_distance_nm < 0
        or candidate.max_peaks < 1
        or candidate.gap_factor <= 1
    ):
        return fallback
    return candidate


def save_analysis_preferences(defaults: AnalysisDefaults) -> None:
    """Persist Raw Peak defaults."""

    settings = QSettings()
    settings.setValue("analysis/relative_prominence", defaults.relative_prominence)
    settings.setValue("analysis/noise_sigma_factor", defaults.noise_sigma_factor)
    settings.setValue("analysis/min_distance_nm", defaults.min_distance_nm)
    settings.setValue("analysis/max_peaks", defaults.max_peaks)
    settings.setValue("analysis/gap_factor", defaults.gap_factor)
