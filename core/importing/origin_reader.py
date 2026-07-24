"""Native OPJ/OPJU reader exposed through the common tabular contract."""

from __future__ import annotations

from itertools import zip_longest
from pathlib import Path

from core.errors import DataImportError

from .origin_backend import BundledOriginBackend, OriginColumn, OriginProjectBackend
from .readers import TabularReadResult, TabularSheet, TabularSheetError


class OriginProjectReader:
    """Read Origin projects without requiring Origin or a Python installation."""

    _SIGNATURES = {
        ".opj": b"CPYA ",
        ".opju": b"CPYUA ",
    }

    def __init__(self, backend: OriginProjectBackend | None = None) -> None:
        self._backend = backend or BundledOriginBackend()

    def read(self, path: Path) -> tuple[TabularReadResult, ...]:
        """Validate the container and expose every worksheet as rows."""

        extension = path.suffix.casefold()
        expected_signature = self._SIGNATURES.get(extension)
        if expected_signature is None:
            raise DataImportError(
                f"Unsupported Origin project type: {path.suffix or '(none)'}",
                code="E_IMPORT_UNSUPPORTED_FORMAT",
            )
        try:
            with path.open("rb") as source:
                signature = source.read(len(expected_signature))
        except OSError as exc:
            raise DataImportError(
                f"Unable to read Origin project: {path.name}",
                code="E_IMPORT_FILE_READ",
                detail=str(exc),
            ) from exc
        if signature != expected_signature:
            actual = _signature_label(signature)
            expected = expected_signature.decode("ascii").strip()
            raise DataImportError(
                f"{path.name} is not an Origin {extension.upper()} project.",
                code="E_IMPORT_ORIGIN_SIGNATURE",
                detail=f"Expected {expected} signature; found {actual}.",
            )

        worksheets = self._backend.read_project(path)
        if not worksheets:
            raise DataImportError(
                f"No numeric worksheets were found in Origin project: {path.name}",
                code="E_IMPORT_ORIGIN_NO_WORKSHEETS",
            )

        sheets: list[TabularReadResult] = []
        for worksheet in worksheets:
            if not worksheet.x_column_recovered:
                sheets.append(
                    TabularSheetError(
                        name=worksheet.name,
                        error=DataImportError(
                            "Origin worksheet X column could not be decoded safely.",
                            code="E_IMPORT_ORIGIN_X_COLUMN",
                            detail=(
                                "The worksheet was skipped instead of using a synthetic "
                                "row index as wavelength."
                            ),
                        ),
                    )
                )
                continue
            headers = tuple(_column_header(column) for column in worksheet.columns)
            data_rows = tuple(
                tuple(row)
                for row in zip_longest(
                    *(column.values for column in worksheet.columns),
                    fillvalue=None,
                )
            )
            sheets.append(
                TabularSheet(
                    name=worksheet.name,
                    rows=(headers, *data_rows),
                )
            )
        return tuple(sheets)


def _column_header(column: OriginColumn) -> str:
    label = column.label.strip() or column.short_name
    unit = column.unit.strip()
    if not unit or unit.casefold() in label.casefold():
        return label
    if unit.startswith(("[", "(")):
        return f"{label} {unit}"
    return f"{label} ({unit})"


def _signature_label(signature: bytes) -> str:
    text = signature.decode("ascii", errors="replace").strip()
    return text or signature.hex(" ")
