"""The canonical data contract: ``DataStruct``.

Every parser returns one, and every consumer (corrections, fitting, plotting,
export) reads one. Mirrors the MATLAB ``parser.createDataStruct`` contract:

    time     (N,)    independent variable / x-axis
    values   (N, M)  data matrix — N samples, M channels
    labels   (M,)    channel names (deduplicated: 'A','A' -> 'A','A (2)')
    units    (M,)    channel units ('' when unknown)
    metadata         immutable mapping of import metadata

Pure layer — no fastapi/pydantic imports (enforced by test_repo_integrity).
The instance is frozen and its arrays are read-only, honouring the
"raw data is preserved, never mutated in place" rule: compute on copies.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

__all__ = ["DataStruct"]


def _deduplicate(labels: tuple[str, ...]) -> tuple[str, ...]:
    """Append ' (2)', ' (3)', ... to repeated labels (matches MATLAB)."""
    seen: dict[str, int] = {}
    out: list[str] = []
    for lbl in labels:
        if lbl in seen:
            seen[lbl] += 1
            out.append(f"{lbl} ({seen[lbl]})")
        else:
            seen[lbl] = 1
            out.append(lbl)
    return tuple(out)


@dataclass(frozen=True, slots=True)
class DataStruct:
    """Immutable, parser-agnostic dataset. Build via :meth:`create`."""

    time: NDArray[np.float64]
    values: NDArray[np.float64]
    labels: tuple[str, ...] = ()
    units: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        time = np.asarray(self.time, dtype=float).ravel()
        values = np.asarray(self.values, dtype=float)
        if values.ndim == 1:
            values = (
                values.reshape(-1, 1)
                if values.size
                else np.empty((time.shape[0], 0), dtype=float)
            )
        if values.ndim != 2:
            raise ValueError(f"values must be 2-D, got {values.ndim}-D")

        n = time.shape[0]
        if values.shape[0] != n:
            raise ValueError(
                f"time length ({n}) must equal values row count ({values.shape[0]})"
            )
        m = values.shape[1]

        labels = tuple(self.labels) if self.labels else tuple(f"ch{i + 1}" for i in range(m))
        units = tuple(self.units) if self.units else tuple("" for _ in range(m))
        if len(labels) != m:
            raise ValueError(f"expected {m} labels for {m} columns, got {len(labels)}")
        if len(units) != m:
            raise ValueError(f"expected {m} units for {m} columns, got {len(units)}")
        labels = _deduplicate(labels)

        time.flags.writeable = False
        values.flags.writeable = False

        object.__setattr__(self, "time", time)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "labels", labels)
        object.__setattr__(self, "units", units)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    # ── Construction ──────────────────────────────────────────────────────
    @classmethod
    def create(
        cls,
        time: ArrayLike,
        values: ArrayLike,
        *,
        labels: Sequence[str] | None = None,
        units: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> DataStruct:
        """Mirror of MATLAB ``createDataStruct``. Accepts array-likes.

        Raises ``ValueError`` for anything that is not coercible to a float
        array. ``np.asarray(..., dtype=float)`` raises ``TypeError`` for a
        non-numeric payload (a nested dict, say), which is NOT in the
        ``(ValueError, KeyError, IndexError)`` tuple every route that builds a
        DataStruct catches -- so a malformed ``dataset`` on the wire escaped as
        an unhandled HTTP 500 from ~17 handlers across 7 route modules. Every
        such route types the field as ``dict[str, Any]``, so pydantic does not
        filter it.

        Normalizing here rather than widening each route's except tuple is the
        class fix: this is the ONE constructor they all go through, so current
        and future callers are covered without touching a route file.
        """
        try:
            time_arr = np.asarray(time, dtype=float)
            values_arr = np.asarray(values, dtype=float)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"dataset time/values must be numeric arrays: {exc}") from exc
        return cls(
            time=time_arr,
            values=values_arr,
            labels=tuple(labels) if labels is not None else (),
            units=tuple(units) if units is not None else (),
            metadata=dict(metadata) if metadata is not None else {},
        )

    # ── Shape helpers ─────────────────────────────────────────────────────
    @property
    def n_points(self) -> int:
        return int(self.time.shape[0])

    @property
    def n_channels(self) -> int:
        return int(self.values.shape[1])

    def column(self, key: int | str) -> NDArray[np.float64]:
        """Return one channel's data (read-only) by index or label."""
        idx = key if isinstance(key, int) else self.labels.index(key)
        return self.values[:, idx]

    # ── Serialization (route boundary) ────────────────────────────────────
    # NOTE: JSON here is Python-round-trippable (NaN/Inf survive via the
    # stdlib json's non-standard tokens). The HTTP boundary (M1 #5) will map
    # non-finite floats to null for valid wire JSON — that's a routes concern.
    def to_dict(self) -> dict[str, Any]:
        return {
            "time": self.time.tolist(),
            "values": self.values.tolist(),
            "labels": list(self.labels),
            "units": list(self.units),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> DataStruct:
        return cls.create(
            time=payload["time"],
            values=payload["values"],
            labels=payload.get("labels"),
            units=payload.get("units"),
            metadata=payload.get("metadata"),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_json(cls, text: str) -> DataStruct:
        return cls.from_dict(json.loads(text))
