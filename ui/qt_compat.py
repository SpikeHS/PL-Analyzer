"""Small compatibility helpers for Qt values passed into UI models."""

from __future__ import annotations

from PySide6.QtCore import Qt


def normalize_check_state(value: object) -> Qt.CheckState | None:
    """Normalize enum and integer check-state payloads from supported PySide6 versions."""

    if isinstance(value, bool):
        return None
    if isinstance(value, Qt.CheckState):
        check_state = value
    else:
        try:
            check_state = Qt.CheckState(value)
        except (TypeError, ValueError):
            return None
    if check_state not in (
        Qt.CheckState.Unchecked,
        Qt.CheckState.PartiallyChecked,
        Qt.CheckState.Checked,
    ):
        return None
    return check_state
