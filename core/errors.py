"""User-facing exception types with stable machine-readable error codes."""

from __future__ import annotations


class PLAnalyzerError(Exception):
    """Base exception for recoverable application errors."""

    def __init__(self, message: str, *, code: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail


class ConfigurationError(PLAnalyzerError):
    """Raised when application configuration is missing or invalid."""


class DataImportError(PLAnalyzerError):
    """Raised when a source cannot produce a valid spectrum."""


class AnalysisError(PLAnalyzerError):
    """Raised when an analysis request is structurally invalid."""


class ExportError(PLAnalyzerError):
    """Raised when a result or figure cannot be exported."""
