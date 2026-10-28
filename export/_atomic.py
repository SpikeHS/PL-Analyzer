"""Shared atomic-write helpers for file export adapters.

Every exporter writes into a sibling temporary file and replaces the target
only after the full content is on disk, so a failed export can never leave a
truncated workbook or CSV behind for the operator.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path


def temporary_path(target: Path) -> Path:
    """Create an empty sibling temporary file used to stage one export."""

    descriptor, name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    os.close(descriptor)
    return Path(name)


def remove_if_present(path: Path) -> None:
    """Best-effort removal of a staged export artifact after a failure."""

    with suppress(OSError):
        path.unlink(missing_ok=True)
