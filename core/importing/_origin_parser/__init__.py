"""Worksheet-only Origin project reader vendored from quantized-lab.

The public facade intentionally exposes workbook data only. Graphs, matrices,
notes, project-folder trees, and Origin project writing are outside this
vendored subset.
"""

from __future__ import annotations

from pathlib import Path

from .container import OriginProjectError
from .datastruct import DataStruct
from .opj import read_opj_books
from .opju import read_opju_books

__all__ = ["DataStruct", "OriginProjectError", "read_origin_books"]


def read_origin_books(path: Path) -> list[DataStruct]:
    """Read every worksheet/workbook from an ``.opj`` or ``.opju`` file.

    Extra sheets are returned as ``Book@N`` pseudo-books, matching the
    upstream reader. Each :class:`DataStruct` contains one X array in
    ``time`` and all remaining numeric columns in the two-dimensional
    ``values`` array.
    """
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".opj":
        return read_opj_books(source)
    if suffix == ".opju":
        return read_opju_books(source)
    raise OriginProjectError(
        f"unsupported Origin project extension '{source.suffix}'; expected .opj or .opju"
    )
