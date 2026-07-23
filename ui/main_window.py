"""Main desktop window and presentation-controller event wiring."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Iterable, Mapping
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QCursor,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDockWidget,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QToolBar,
)

from analysis.fit_session import (
    FitResultStore,
    MaterialFitAnalysis,
)
from analysis.fitting import FitConfig, SpectrumFitter
from analysis.raw_peak import RawPeakAnalyzer, RawPeakConfig
from core.configuration import AnalysisDefaults, MaterialDatabase
from core.errors import ExportError, PLAnalyzerError
from core.importing.service import SpectrumImportService
from core.models import (
    AmplitudeMode,
    AxisScale,
    MaterialPeakAnalysis,
    PlotDisplaySettings,
)
from core.persistence import ProjectPersistence
from core.project import MaterialWindowSnapshot, PLProject
from core.workspace import Workspace
from export.fit_table import FitTableExporter
from export.peak_table import PeakTableExporter
from plotting.plot_widget import SpectrumPlotWidget
from ui.fit_panel import FitPanel
from ui.layer_editor import LayerEditorWidget
from ui.log_panel import LogPanel
from ui.peak_panel import PeakPanel
from ui.preferences_dialog import PreferencesDialog, save_analysis_preferences
from ui.sample_panel import SamplePanel
from ui.theme import (
    ThemeMode,
    apply_theme,
    load_theme_preference,
    save_theme_preference,
)


class MainWindow(QMainWindow):
    """PL Analyzer Pro v1.1 desktop composition and UI controller."""

    def __init__(
        self,
        *,
        workspace: Workspace,
        importer: SpectrumImportService,
        analyzer: RawPeakAnalyzer,
        exporter: PeakTableExporter,
        material_database: MaterialDatabase,
        analysis_defaults: AnalysisDefaults,
    ) -> None:
        super().__init__()
        self._workspace = workspace
        self._importer = importer
        self._analyzer = analyzer
        self._exporter = exporter
        self._fit_exporter = FitTableExporter()
        self._fitter = SpectrumFitter()
        self._fit_store = FitResultStore()
        self._analysis_defaults = analysis_defaults
        self._logger = logging.getLogger(__name__)
        self._project_persistence = ProjectPersistence()
        self._project = PLProject(workspace=workspace)
        self._project_path: Path | None = None
        self._dirty = False

        self._theme = load_theme_preference()
        self.setWindowTitle("PL Analyzer Pro — v1.1")
        self.resize(1440, 860)
        self.setMinimumSize(1050, 680)
        self.setAcceptDrops(True)

        self._sample_panel = SamplePanel(self)
        self._plot_widget = SpectrumPlotWidget(self)
        self._plot_widget.set_dark_mode(self._theme is ThemeMode.DARK)
        self._peak_panel = PeakPanel(material_database, self)
        self._fit_panel = FitPanel(self)
        self._default_material_windows = self._peak_panel.material_window_snapshot()
        self._default_fit_settings = self._fit_panel.settings_snapshot()
        self._layer_editor = LayerEditorWidget(self)
        self._log_panel = LogPanel(self)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._sample_panel)
        splitter.addWidget(self._plot_widget)
        analysis_side_tabs = QTabWidget(self)
        analysis_side_tabs.addTab(self._peak_panel, "Raw Peak")
        analysis_side_tabs.addTab(self._fit_panel, "Fit")
        analysis_side_tabs.setMinimumWidth(400)
        splitter.addWidget(analysis_side_tabs)
        splitter.setSizes([230, 790, 420])
        splitter.setStretchFactor(1, 1)
        central_tabs = QTabWidget(self)
        central_tabs.addTab(splitter, "PL Analysis")
        central_tabs.addTab(self._layer_editor, "Layer Editor")
        self.setCentralWidget(central_tabs)

        log_dock = QDockWidget("Log", self)
        log_dock.setObjectName("operator_log_dock")
        log_dock.setAllowedAreas(
            Qt.DockWidgetArea.BottomDockWidgetArea | Qt.DockWidgetArea.TopDockWidgetArea
        )
        log_dock.setWidget(self._log_panel)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, log_dock)
        log_dock.resize(log_dock.width(), 150)

        self._create_actions()
        self._create_menus(log_dock)
        self._create_toolbar()
        self._connect_signals()
        self._sample_panel.set_spectra(self._workspace.spectra)
        self._refresh_views()
        self._set_dirty(False)
        self._log_panel.write("info", "PL Analyzer Pro v1.1 is ready.")

    def import_files(self, paths: Iterable[Path]) -> None:
        """Import paths from dialog or drag/drop through one error boundary."""

        path_list = [path for path in paths]
        if not path_list:
            return
        try:
            report = self._importer.import_paths(path_list)
            added = self._workspace.add_spectra(report.spectra)
            for spectrum in added:
                source_sheet = (
                    f" [{spectrum.source.sheet_name}]" if spectrum.source.sheet_name else ""
                )
                self._log_panel.write(
                    "info",
                    f"Loaded {Path(spectrum.source.file_path).name}{source_sheet} "
                    f"as {spectrum.name} ({spectrum.wavelength_nm.size} points).",
                )
                for diagnostic in spectrum.diagnostics:
                    self._log_panel.write("warning", f"{spectrum.name}: {diagnostic}")
            for issue in report.issues:
                detail = f" — {issue.detail}" if issue.detail else ""
                self._log_panel.write(
                    "error",
                    f"[{issue.code}] {issue.source}: {issue.message}{detail}",
                )

            self._sample_panel.set_spectra(self._workspace.spectra)
            self._refresh_views()
            if added:
                self._set_dirty(True)
                self.statusBar().showMessage(
                    f"Imported {len(added)} spectrum/spectra.",
                    5000,
                )
                self._run_peak_search(show_summary=False)
            if report.issues:
                summaries = "\n".join(
                    f"• {issue.source}: {issue.message}" for issue in report.issues[:6]
                )
                if len(report.issues) > 6:
                    summaries += f"\n• …and {len(report.issues) - 6} more (see Log)."
                QMessageBox.warning(
                    self,
                    "Some data could not be imported",
                    summaries,
                )
        except Exception as exc:
            self._report_exception("Import failed", exc)

    def report_unhandled_exception(self, error: BaseException) -> None:
        """Report a final UI-safe summary for an uncaught Qt callback error."""

        self._log_panel.write("error", f"Unhandled error: {error}")
        QMessageBox.critical(
            self,
            "Unexpected error",
            "An unexpected error occurred. The application will remain open when possible. "
            "See the Log and application log file for details.",
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if any(
            url.isLocalFile()
            and Path(url.toLocalFile()).suffix.casefold() in self._importer.supported_extensions
            for url in urls
        ):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        paths = [
            Path(url.toLocalFile())
            for url in event.mimeData().urls()
            if url.isLocalFile()
            and Path(url.toLocalFile()).suffix.casefold() in self._importer.supported_extensions
        ]
        self.import_files(paths)
        event.acceptProposedAction()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self._confirm_discard_changes():
            event.ignore()
            return
        self._logger.info("Application closed normally.")
        event.accept()

    def _create_actions(self) -> None:
        self._new_project_action = QAction("&New project", self)
        self._new_project_action.setShortcut(QKeySequence.StandardKey.New)
        self._new_project_action.triggered.connect(self._new_project)

        self._open_action = QAction("&Open data…", self)
        self._open_action.setShortcut(QKeySequence.StandardKey.Open)
        self._open_action.triggered.connect(self._choose_files)

        self._open_project_action = QAction("Open &project…", self)
        self._open_project_action.setShortcut("Ctrl+Shift+O")
        self._open_project_action.triggered.connect(self._open_project)
        self._save_project_action = QAction("&Save project", self)
        self._save_project_action.setShortcut(QKeySequence.StandardKey.Save)
        self._save_project_action.triggered.connect(self._save_project)
        self._save_project_as_action = QAction("Save project &as…", self)
        self._save_project_as_action.setShortcut("Ctrl+Shift+S")
        self._save_project_as_action.triggered.connect(self._save_project_as)

        self._export_plot_action = QAction("Export &plot…", self)
        self._export_plot_action.triggered.connect(self._export_plot)
        self._export_peaks_action = QAction("Export peak &table…", self)
        self._export_peaks_action.triggered.connect(self._export_peak_table)
        self._export_fits_action = QAction("Export &fit table…", self)
        self._export_fits_action.triggered.connect(self._export_fit_table)

        self._exit_action = QAction("E&xit", self)
        self._exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self._exit_action.triggered.connect(self.close)

        self._peak_search_action = QAction("&Peak Search", self)
        self._peak_search_action.setShortcut("Ctrl+P")
        self._peak_search_action.triggered.connect(lambda: self._run_peak_search(show_summary=True))
        self._fit_action = QAction("&Fit selected windows", self)
        self._fit_action.setShortcut("Ctrl+F")
        self._fit_action.triggered.connect(lambda: self._run_fit(show_summary=True))

        amplitude_group = QActionGroup(self)
        amplitude_group.setExclusive(True)
        self._raw_action = QAction("&Raw", self, checkable=True)
        self._normalize_action = QAction("&Normalize", self, checkable=True)
        amplitude_group.addAction(self._raw_action)
        amplitude_group.addAction(self._normalize_action)
        if self._workspace.plot_settings.amplitude_mode is AmplitudeMode.RAW:
            self._raw_action.setChecked(True)
        else:
            self._normalize_action.setChecked(True)
        self._raw_action.triggered.connect(lambda: self._set_amplitude_mode(AmplitudeMode.RAW))
        self._normalize_action.triggered.connect(
            lambda: self._set_amplitude_mode(AmplitudeMode.NORMALIZE)
        )

        self._offset_action = QAction("&Offset", self, checkable=True)
        self._offset_action.setChecked(self._workspace.plot_settings.offset_enabled)
        self._offset_action.toggled.connect(self._set_offset)

        scale_group = QActionGroup(self)
        scale_group.setExclusive(True)
        self._linear_action = QAction("&Linear scale", self, checkable=True)
        self._log_action = QAction("Lo&g scale", self, checkable=True)
        scale_group.addAction(self._linear_action)
        scale_group.addAction(self._log_action)
        if self._workspace.plot_settings.y_scale is AxisScale.LINEAR:
            self._linear_action.setChecked(True)
        else:
            self._log_action.setChecked(True)
        self._linear_action.triggered.connect(lambda: self._set_y_scale(AxisScale.LINEAR))
        self._log_action.triggered.connect(lambda: self._set_y_scale(AxisScale.LOG))

        self._legend_action = QAction("&Legend", self, checkable=True)
        self._legend_action.setChecked(self._workspace.plot_settings.legend_visible)
        self._legend_action.toggled.connect(self._set_legend)
        self._grid_action = QAction("&Grid", self, checkable=True)
        self._grid_action.setChecked(self._workspace.plot_settings.grid_visible)
        self._grid_action.toggled.connect(self._set_grid)

        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        self._light_theme_action = QAction("&Light", self, checkable=True)
        self._dark_theme_action = QAction("&Dark", self, checkable=True)
        theme_group.addAction(self._light_theme_action)
        theme_group.addAction(self._dark_theme_action)
        self._light_theme_action.setChecked(self._theme is ThemeMode.LIGHT)
        self._dark_theme_action.setChecked(self._theme is ThemeMode.DARK)
        self._light_theme_action.triggered.connect(lambda: self._set_theme(ThemeMode.LIGHT))
        self._dark_theme_action.triggered.connect(lambda: self._set_theme(ThemeMode.DARK))

        self._preferences_action = QAction("&Preferences…", self)
        self._preferences_action.triggered.connect(self._show_preferences)

        self._about_action = QAction("&About", self)
        self._about_action.triggered.connect(self._show_about)

    def _create_menus(self, log_dock: QDockWidget) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self._new_project_action)
        file_menu.addAction(self._open_project_action)
        file_menu.addAction(self._save_project_action)
        file_menu.addAction(self._save_project_as_action)
        file_menu.addSeparator()
        file_menu.addAction(self._open_action)
        export_menu = file_menu.addMenu("&Export")
        export_menu.addAction(self._export_plot_action)
        export_menu.addAction(self._export_peaks_action)
        export_menu.addAction(self._export_fits_action)
        file_menu.addSeparator()
        file_menu.addAction(self._exit_action)

        analysis_menu = self.menuBar().addMenu("&Analysis")
        analysis_menu.addAction(self._peak_search_action)
        analysis_menu.addAction(self._fit_action)
        analysis_menu.addSeparator()
        analysis_menu.addAction(self._raw_action)
        analysis_menu.addAction(self._normalize_action)
        analysis_menu.addAction(self._offset_action)

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self._linear_action)
        view_menu.addAction(self._log_action)
        view_menu.addSeparator()
        view_menu.addAction(self._legend_action)
        view_menu.addAction(self._grid_action)
        theme_menu = view_menu.addMenu("&Theme")
        theme_menu.addAction(self._light_theme_action)
        theme_menu.addAction(self._dark_theme_action)
        view_menu.addSeparator()
        view_menu.addAction(log_dock.toggleViewAction())

        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.addAction(self._preferences_action)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self._about_action)

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        toolbar.addAction(self._new_project_action)
        toolbar.addAction(self._save_project_action)
        toolbar.addSeparator()
        toolbar.addAction(self._open_action)
        toolbar.addAction(self._peak_search_action)
        toolbar.addAction(self._fit_action)
        toolbar.addSeparator()
        toolbar.addAction(self._raw_action)
        toolbar.addAction(self._normalize_action)
        toolbar.addAction(self._offset_action)
        self.addToolBar(toolbar)

    def _connect_signals(self) -> None:
        self._sample_panel.visibility_changed.connect(self._on_visibility_changed)
        self._sample_panel.remove_requested.connect(self._remove_spectra)
        self._peak_panel.search_requested.connect(lambda: self._run_peak_search(show_summary=True))
        self._peak_panel.copy_requested.connect(self._copy_peak_table)
        self._peak_panel.export_requested.connect(self._export_peak_table)
        self._peak_panel.invalid_window_selected.connect(
            lambda name: QMessageBox.information(
                self,
                "Define a material window",
                f"{name} has no scientifically valid universal range. "
                "Enter its minimum and maximum wavelength before selecting it.",
            )
        )
        self._peak_panel.settings_changed.connect(lambda: self._set_dirty(True))
        self._layer_editor.layers_changed.connect(self._on_layers_changed)
        self._fit_panel.fit_requested.connect(lambda: self._run_fit(show_summary=True))
        self._fit_panel.copy_requested.connect(self._copy_fit_table)
        self._fit_panel.export_requested.connect(self._export_fit_table)
        self._fit_panel.settings_changed.connect(lambda: self._set_dirty(True))

    def _choose_files(self) -> None:
        filenames, _ = QFileDialog.getOpenFileNames(
            self,
            "Open PL spectra",
            "",
            "PL data (*.csv *.xlsx *.xls *.xlsm);;CSV (*.csv);;"
            "Excel (*.xlsx *.xls *.xlsm);;All files (*)",
        )
        self.import_files(Path(filename) for filename in filenames)

    def _run_peak_search(self, *, show_summary: bool) -> None:
        spectra = self._workspace.visible_spectra()
        if not spectra:
            if show_summary:
                QMessageBox.information(self, "Peak Search", "No visible spectra to analyze.")
            return
        windows = self._peak_panel.search_windows
        if not windows:
            if show_summary:
                QMessageBox.information(
                    self,
                    "Peak Search",
                    "Select at least one material with a valid wavelength window.",
                )
            return

        results: dict[str, tuple[MaterialPeakAnalysis, ...]] = {}
        failures: list[str] = []
        self._workspace.clear_peak_results()
        for spectrum in spectra:
            analyses: list[MaterialPeakAnalysis] = []
            for window in windows:
                config = RawPeakConfig(
                    search_min_nm=window.min_nm,
                    search_max_nm=window.max_nm,
                    relative_prominence=self._analysis_defaults.relative_prominence,
                    noise_sigma_factor=self._analysis_defaults.noise_sigma_factor,
                    min_distance_nm=self._analysis_defaults.min_distance_nm,
                    max_peaks=self._analysis_defaults.max_peaks,
                    gap_factor=self._analysis_defaults.gap_factor,
                )
                try:
                    result = self._analyzer.analyze_spectrum(spectrum, config)
                    analyses.append(MaterialPeakAnalysis(window=window, result=result))
                except PLAnalyzerError as exc:
                    if exc.code != "E_PEAK_NO_FINITE_DATA":
                        failures.append(f"{spectrum.name} / {window.material_name}: {exc}")
                        self._log_panel.write(
                            "warning",
                            f"[{exc.code}] {spectrum.name} / {window.material_name}: {exc}",
                        )
            results[spectrum.spectrum_id] = tuple(analyses)
        self._workspace.set_material_peak_results(results)
        self._set_dirty(True)
        self._refresh_views()
        peak_count = len(self._workspace.peak_table_records())
        range_summary = ", ".join(
            f"{window.material_name} {window.min_nm:g}–{window.max_nm:g} nm" for window in windows
        )
        self._log_panel.write(
            "info",
            f"Raw peak analysis completed: {peak_count} unique peak(s); windows: {range_summary}.",
        )
        if show_summary:
            message = (
                f"Found {peak_count} unique raw peak(s) in {len(results)} sample(s) "
                f"across {len(windows)} material window(s)."
            )
            if failures:
                message += f"\n\n{len(failures)} sample(s) were skipped; see Log."
            QMessageBox.information(self, "Peak Search complete", message)

    def _run_fit(self, *, show_summary: bool) -> None:
        """Fit every visible spectrum in every selected material window."""

        spectra = self._workspace.visible_spectra()
        if not spectra:
            if show_summary:
                QMessageBox.information(
                    self,
                    "Model Fit",
                    "No visible spectra to fit.",
                )
            return
        windows = self._peak_panel.search_windows
        if not windows:
            if show_summary:
                QMessageBox.information(
                    self,
                    "Model Fit",
                    "Select at least one material with a valid wavelength window "
                    "on the Raw Peak tab.",
                )
            return

        ui_settings = self._fit_panel.settings
        assignments: list[MaterialFitAnalysis] = []
        failures: list[str] = []
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            for spectrum in spectra:
                for window in windows:
                    config = FitConfig(
                        search_min_nm=window.min_nm,
                        search_max_nm=window.max_nm,
                        model=ui_settings.model,
                        peak_count=ui_settings.peak_count,
                        max_peaks=ui_settings.max_peaks,
                        baseline=ui_settings.baseline,
                        savgol_enabled=ui_settings.savgol_enabled,
                        savgol_window_length=ui_settings.savgol_window_length,
                        savgol_polyorder=ui_settings.savgol_polyorder,
                        min_peak_distance_nm=ui_settings.min_peak_distance_nm,
                    )
                    try:
                        fit_result = self._fitter.fit(
                            spectrum.wavelength_nm,
                            spectrum.intensity_au,
                            config,
                        )
                    except PLAnalyzerError as exc:
                        failure = f"{spectrum.name} / {window.material_name}: [{exc.code}] {exc}"
                        failures.append(failure)
                        self._log_panel.write("warning", failure)
                        continue
                    assignments.append(
                        MaterialFitAnalysis(
                            spectrum_id=spectrum.spectrum_id,
                            sample_name=spectrum.name,
                            window=window,
                            result=fit_result,
                        )
                    )
        finally:
            QApplication.restoreOverrideCursor()

        self._fit_store.replace(tuple(assignments))
        self._set_dirty(True)
        self._refresh_views()
        fitted_peak_count = len(self._fit_store.table_records())
        self._log_panel.write(
            "info",
            f"Model fitting completed: {len(assignments)} successful window fit(s), "
            f"{fitted_peak_count} fitted peak(s), {len(failures)} skipped.",
        )
        if show_summary:
            message = (
                f"Completed {len(assignments)} material-window fit(s) with "
                f"{fitted_peak_count} fitted peak(s)."
            )
            if failures:
                message += f"\n\n{len(failures)} window fit(s) were skipped; see Log."
            QMessageBox.information(self, "Model Fit complete", message)

    def _on_visibility_changed(self, spectrum_id: str, visible: bool) -> None:
        self._workspace.set_visibility(spectrum_id, visible)
        self._set_dirty(True)
        self._refresh_views()

    def _remove_spectra(self, spectrum_ids: object) -> None:
        identifiers = tuple(str(value) for value in spectrum_ids)
        self._workspace.remove_spectra(identifiers)
        self._fit_store.remove_spectra(set(identifiers))
        self._set_dirty(True)
        self._sample_panel.set_spectra(self._workspace.spectra)
        self._refresh_views()
        self._log_panel.write("info", f"Removed {len(identifiers)} sample(s).")

    def _refresh_views(self) -> None:
        self._plot_widget.render(
            self._workspace.spectra,
            self._workspace.peak_results,
            self._workspace.plot_settings,
            self._fit_store.assignments,
        )
        self._peak_panel.set_records(self._workspace.peak_table_records())
        self._fit_panel.set_records(self._fit_store.table_records())

    def _set_amplitude_mode(self, mode: AmplitudeMode) -> None:
        self._workspace.plot_settings.amplitude_mode = mode
        self._set_dirty(True)
        self._refresh_views()

    def _set_offset(self, enabled: bool) -> None:
        self._workspace.plot_settings.offset_enabled = enabled
        self._set_dirty(True)
        self._refresh_views()

    def _set_y_scale(self, scale: AxisScale) -> None:
        self._workspace.plot_settings.y_scale = scale
        self._set_dirty(True)
        self._refresh_views()

    def _set_legend(self, visible: bool) -> None:
        self._workspace.plot_settings.legend_visible = visible
        self._set_dirty(True)
        self._refresh_views()

    def _set_grid(self, visible: bool) -> None:
        self._workspace.plot_settings.grid_visible = visible
        self._set_dirty(True)
        self._refresh_views()

    def _set_theme(self, theme: ThemeMode) -> None:
        self._theme = theme
        apply_theme(QApplication.instance(), theme)
        self._plot_widget.set_dark_mode(theme is ThemeMode.DARK)
        save_theme_preference(theme)
        self._set_dirty(True)
        self._refresh_views()

    def _show_preferences(self) -> None:
        dialog = PreferencesDialog(self._analysis_defaults, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._analysis_defaults = dialog.analysis_defaults()
        save_analysis_preferences(self._analysis_defaults)
        self._set_dirty(True)
        self._log_panel.write("info", "Analysis preferences updated.")

    def _on_layers_changed(self) -> None:
        self._project.layers = list(self._layer_editor.layers)
        self._set_dirty(True)

    def _new_project(self) -> None:
        if not self._confirm_discard_changes():
            return
        current_settings = self._workspace.plot_settings
        workspace = Workspace(
            PlotDisplaySettings(
                amplitude_mode=current_settings.amplitude_mode,
                offset_enabled=current_settings.offset_enabled,
                y_scale=current_settings.y_scale,
                legend_visible=current_settings.legend_visible,
                grid_visible=current_settings.grid_visible,
            )
        )
        self._workspace = workspace
        self._project = PLProject(workspace=workspace)
        self._fit_store.clear()
        self._project_path = None
        self._peak_panel.restore_material_windows(self._default_material_windows)
        self._fit_panel.restore_settings(self._default_fit_settings)
        self._layer_editor.set_layers(())
        self._sample_panel.set_spectra(())
        self._refresh_views()
        self._set_dirty(False)
        self._log_panel.write("info", "Created a new project.")

    def _open_project(self) -> None:
        if not self._confirm_discard_changes():
            return
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open PL Analyzer Pro project",
            "",
            "PL Analyzer Pro project (*.plproj)",
        )
        if not filename:
            return
        path = Path(filename)
        try:
            loaded = self._project_persistence.load(path)
            self._apply_loaded_project(loaded, path)
            self._log_panel.write("info", f"Project opened: {path}")
        except Exception as exc:
            self._report_exception("Open project failed", exc)

    def _save_project(self) -> bool:
        if self._project_path is None:
            return self._save_project_as()
        return self._save_project_to(self._project_path)

    def _save_project_as(self) -> bool:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Save PL Analyzer Pro project",
            "untitled.plproj",
            "PL Analyzer Pro project (*.plproj)",
        )
        if not filename:
            return False
        path = Path(filename)
        if path.suffix.casefold() != ".plproj":
            path = path.with_suffix(".plproj")
        return self._save_project_to(path)

    def _save_project_to(self, path: Path) -> bool:
        try:
            self._sync_project_state()
            self._project_persistence.save(self._project, path)
            self._project_path = path
            self._set_dirty(False)
            self._log_panel.write("info", f"Project saved: {path}")
            self.statusBar().showMessage(f"Saved {path.name}", 5000)
            return True
        except Exception as exc:
            self._report_exception("Save project failed", exc)
            return False

    def _sync_project_state(self) -> None:
        self._project.workspace = self._workspace
        self._project.layers = list(self._layer_editor.layers)
        self._project.material_windows = [
            MaterialWindowSnapshot(
                material_id=str(snapshot["material_id"]),
                display_name=str(snapshot["display_name"]),
                minimum_nm=(float(snapshot["min_nm"]) if snapshot["min_nm"] is not None else None),
                maximum_nm=(float(snapshot["max_nm"]) if snapshot["max_nm"] is not None else None),
                selected=bool(snapshot["selected"]),
            )
            for snapshot in self._peak_panel.material_window_snapshot()
        ]
        self._project.fit_results = self._fit_store.to_project_payload()
        self._project.extensions["theme"] = self._theme.value
        self._project.extensions["fit_ui_settings"] = self._fit_panel.settings_snapshot()
        self._project.extensions["raw_peak_preferences"] = {
            "relative_prominence": self._analysis_defaults.relative_prominence,
            "noise_sigma_factor": self._analysis_defaults.noise_sigma_factor,
            "min_distance_nm": self._analysis_defaults.min_distance_nm,
            "max_peaks": self._analysis_defaults.max_peaks,
            "gap_factor": self._analysis_defaults.gap_factor,
        }
        self._project.validate()

    def _apply_loaded_project(self, project: PLProject, path: Path) -> None:
        self._project = project
        self._workspace = project.workspace
        self._project_path = path
        self._sample_panel.set_spectra(self._workspace.spectra)
        self._layer_editor.set_layers(project.layers)
        self._peak_panel.restore_material_windows(
            [
                {
                    "material_id": window.material_id,
                    "selected": window.selected,
                    "min_nm": window.minimum_nm,
                    "max_nm": window.maximum_nm,
                }
                for window in project.material_windows
            ]
        )
        try:
            self._fit_store = FitResultStore.from_project_payload(project.fit_results)
            valid_spectrum_ids = {spectrum.spectrum_id for spectrum in self._workspace.spectra}
            orphan_spectrum_ids = {
                assignment.spectrum_id
                for assignment in self._fit_store.assignments
                if assignment.spectrum_id not in valid_spectrum_ids
            }
            if orphan_spectrum_ids:
                self._fit_store.remove_spectra(orphan_spectrum_ids)
                self._log_panel.write(
                    "warning",
                    f"Ignored {len(orphan_spectrum_ids)} orphaned fit spectrum reference(s).",
                )
        except PLAnalyzerError as exc:
            self._fit_store.clear()
            self._log_panel.write(
                "warning",
                f"[{exc.code}] Stored fit results were not restored: {exc}",
            )
        fit_settings = project.extensions.get("fit_ui_settings")
        if isinstance(fit_settings, Mapping):
            self._fit_panel.restore_settings(fit_settings)
        raw_peak_preferences = project.extensions.get("raw_peak_preferences")
        if isinstance(raw_peak_preferences, Mapping):
            self._restore_analysis_defaults(raw_peak_preferences)
        self._sync_plot_actions()
        saved_theme = project.extensions.get("theme")
        if isinstance(saved_theme, str):
            try:
                theme = ThemeMode(saved_theme)
                self._theme = theme
                apply_theme(QApplication.instance(), theme)
                self._plot_widget.set_dark_mode(theme is ThemeMode.DARK)
                self._light_theme_action.setChecked(theme is ThemeMode.LIGHT)
                self._dark_theme_action.setChecked(theme is ThemeMode.DARK)
            except ValueError:
                pass
        self._refresh_views()
        self._set_dirty(False)

    def _restore_analysis_defaults(
        self,
        snapshot: Mapping[str, object],
    ) -> None:
        """Restore validated project-local Raw Peak detection settings."""

        try:
            candidate = AnalysisDefaults(
                relative_prominence=float(snapshot["relative_prominence"]),
                noise_sigma_factor=float(snapshot["noise_sigma_factor"]),
                min_distance_nm=float(snapshot["min_distance_nm"]),
                max_peaks=int(snapshot["max_peaks"]),
                gap_factor=float(snapshot["gap_factor"]),
            )
        except (KeyError, TypeError, ValueError):
            self._log_panel.write(
                "warning",
                "Stored Raw Peak preferences were invalid and were ignored.",
            )
            return
        if (
            not 0 <= candidate.relative_prominence <= 1
            or candidate.noise_sigma_factor < 0
            or candidate.min_distance_nm < 0
            or candidate.max_peaks < 1
            or candidate.gap_factor <= 1
        ):
            self._log_panel.write(
                "warning",
                "Stored Raw Peak preferences were outside valid limits and were ignored.",
            )
            return
        self._analysis_defaults = candidate

    def _sync_plot_actions(self) -> None:
        settings = self._workspace.plot_settings
        self._raw_action.setChecked(settings.amplitude_mode is AmplitudeMode.RAW)
        self._normalize_action.setChecked(settings.amplitude_mode is AmplitudeMode.NORMALIZE)
        self._offset_action.setChecked(settings.offset_enabled)
        self._linear_action.setChecked(settings.y_scale is AxisScale.LINEAR)
        self._log_action.setChecked(settings.y_scale is AxisScale.LOG)
        self._legend_action.setChecked(settings.legend_visible)
        self._grid_action.setChecked(settings.grid_visible)

    def _confirm_discard_changes(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Unsaved project changes",
            "Save changes to the current project?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Cancel:
            return False
        if answer == QMessageBox.StandardButton.Save:
            return self._save_project()
        return True

    def _set_dirty(self, dirty: bool) -> None:
        self._dirty = dirty
        name = self._project_path.name if self._project_path else "Untitled"
        marker = "*" if dirty else ""
        self.setWindowTitle(f"{marker}{name} — PL Analyzer Pro v1.1")

    def _copy_peak_table(self, text: str) -> None:
        if not self._workspace.peak_table_records():
            QMessageBox.information(self, "Copy Peak Table", "There are no results to copy.")
            return
        QApplication.clipboard().setText(text)
        self._log_panel.write("info", "Peak table copied to the clipboard.")

    def _export_peak_table(self) -> None:
        filename, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export peak table",
            "PL_peaks.xlsx",
            "Excel workbook (*.xlsx);;CSV (*.csv)",
        )
        if not filename:
            return
        path = Path(filename)
        if not path.suffix:
            path = path.with_suffix(".csv" if "CSV" in selected_filter else ".xlsx")
        try:
            self._exporter.export(self._workspace.peak_table_records(), path)
            self._log_panel.write("info", f"Peak table exported: {path}")
            self.statusBar().showMessage(f"Exported {path.name}", 5000)
        except Exception as exc:
            self._report_exception("Peak table export failed", exc)

    def _copy_fit_table(self, text: str) -> None:
        if not self._fit_store.table_records():
            QMessageBox.information(
                self,
                "Copy Fit Table",
                "There are no fit results to copy.",
            )
            return
        QApplication.clipboard().setText(text)
        self._log_panel.write("info", "Fit table copied to the clipboard.")

    def _export_fit_table(self) -> None:
        filename, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export fit table",
            "PL_fits.xlsx",
            "Excel workbook (*.xlsx);;CSV (*.csv)",
        )
        if not filename:
            return
        path = Path(filename)
        if not path.suffix:
            path = path.with_suffix(".csv" if "CSV" in selected_filter else ".xlsx")
        try:
            self._fit_exporter.export(self._fit_store.table_records(), path)
            self._log_panel.write("info", f"Fit table exported: {path}")
            self.statusBar().showMessage(f"Exported {path.name}", 5000)
        except Exception as exc:
            self._report_exception("Fit table export failed", exc)

    def _export_plot(self) -> None:
        filename, selected_filter = QFileDialog.getSaveFileName(
            self,
            "Export plot",
            "PL_comparison.png",
            "PNG image (*.png);;SVG vector (*.svg);;PDF document (*.pdf)",
        )
        if not filename:
            return
        path = Path(filename)
        if not path.suffix:
            suffixes = {"SVG": ".svg", "PDF": ".pdf"}
            suffix = next(
                (value for name, value in suffixes.items() if name in selected_filter),
                ".png",
            )
            path = path.with_suffix(suffix)
        if path.suffix.casefold() not in {".png", ".svg", ".pdf"}:
            self._report_exception(
                "Plot export failed",
                ExportError(
                    f"Unsupported plot format: {path.suffix}",
                    code="E_EXPORT_FORMAT",
                ),
            )
            return
        try:
            self._plot_widget.save_figure(path)
            self._log_panel.write("info", f"Plot exported: {path}")
            self.statusBar().showMessage(f"Exported {path.name}", 5000)
        except Exception as exc:
            self._report_exception("Plot export failed", exc)

    def _report_exception(self, context: str, exc: BaseException) -> None:
        traceback_text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        self._logger.error(
            "%s: %s\n%s",
            context,
            exc,
            traceback_text,
        )
        code = f" [{exc.code}]" if isinstance(exc, PLAnalyzerError) else ""
        detail = exc.detail if isinstance(exc, PLAnalyzerError) else None
        self._log_panel.write("error", f"{context}{code}: {exc}")
        message = str(exc)
        if detail:
            message += f"\n\nDetails: {detail}"
        QMessageBox.critical(self, context, message)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About PL Analyzer Pro",
            "<b>PL Analyzer Pro v1.1</b><br><br>"
            "Desktop photoluminescence analysis for III–V semiconductor research.<br>"
            "Includes material-labelled Raw Peak analysis and model-based spectral fitting.",
        )
