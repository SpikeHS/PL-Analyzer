"""Project-domain models for epitaxial structures and durable PL workspaces."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from uuid import uuid4

from core.workspace import Workspace

type JSONScalar = None | bool | int | float | str
type JSONValue = JSONScalar | list[JSONValue] | dict[str, JSONValue]


@dataclass(slots=True)
class Layer:
    """One epitaxial layer in substrate-to-surface project order.

    Material, composition, and dopant naming intentionally remain free-form.
    This permits new III-V material systems without changing the project schema.
    Physical quantities use unit-bearing field names.
    """

    material: str
    thickness_nm: float
    composition: str = ""
    doping_type: str = ""
    doping_concentration_cm3: float | None = None
    layer_id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self) -> None:
        self.layer_id = self.layer_id.strip()
        self.material = self.material.strip()
        self.composition = self.composition.strip()
        self.doping_type = self.doping_type.strip()

        if not self.layer_id:
            raise ValueError("A layer must have a stable, non-empty ID.")
        if not self.material:
            raise ValueError("A layer material must not be empty.")
        self.thickness_nm = _finite_number(self.thickness_nm, "thickness_nm")
        if self.thickness_nm <= 0:
            raise ValueError("Layer thickness_nm must be greater than zero.")
        if self.doping_concentration_cm3 is not None:
            concentration = _finite_number(
                self.doping_concentration_cm3,
                "doping_concentration_cm3",
            )
            if concentration < 0:
                raise ValueError("Layer doping_concentration_cm3 must not be negative.")
            self.doping_concentration_cm3 = concentration


@dataclass(frozen=True, slots=True)
class MaterialWindowSnapshot:
    """Project-local copy of one material peak-search window."""

    material_id: str
    display_name: str
    minimum_nm: float | None
    maximum_nm: float | None
    selected: bool = True

    def __post_init__(self) -> None:
        material_id = self.material_id.strip()
        display_name = self.display_name.strip()
        if not material_id:
            raise ValueError("A material window must have a stable ID.")
        if not display_name:
            raise ValueError("A material window must have a display name.")
        minimum_nm = (
            None if self.minimum_nm is None else _finite_number(self.minimum_nm, "minimum_nm")
        )
        maximum_nm = (
            None if self.maximum_nm is None else _finite_number(self.maximum_nm, "maximum_nm")
        )
        if minimum_nm is not None and minimum_nm <= 0:
            raise ValueError("Material window minimum_nm must be positive.")
        if maximum_nm is not None and maximum_nm <= 0:
            raise ValueError("Material window maximum_nm must be positive.")
        if minimum_nm is not None and maximum_nm is not None and minimum_nm >= maximum_nm:
            raise ValueError("A material window minimum_nm must be below maximum_nm.")
        if self.selected and (minimum_nm is None or maximum_nm is None):
            raise ValueError("A selected material window must have valid bounds.")
        object.__setattr__(self, "material_id", material_id)
        object.__setattr__(self, "display_name", display_name)
        object.__setattr__(self, "minimum_nm", minimum_nm)
        object.__setattr__(self, "maximum_nm", maximum_nm)


@dataclass(slots=True)
class PLProject:
    """Complete editable state that belongs in one ``.plproj`` file.

    ``fit_results`` is deliberately JSON-shaped and opaque to the core project
    model. Fit modules may evolve independently while project persistence keeps
    their versioned result payloads intact.
    """

    workspace: Workspace
    layers: list[Layer] = field(default_factory=list)
    material_windows: list[MaterialWindowSnapshot] = field(default_factory=list)
    fit_results: dict[str, JSONValue] = field(default_factory=dict)
    extensions: dict[str, JSONValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.workspace, Workspace):
            raise TypeError("workspace must be a Workspace instance.")
        self.layers = list(self.layers)
        self.material_windows = list(self.material_windows)
        self.fit_results = dict(self.fit_results)
        self.extensions = dict(self.extensions)
        self.validate()

    def validate(self) -> None:
        """Validate stable identities without imposing an artificial layer limit."""

        layer_ids = [layer.layer_id for layer in self.layers]
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("Layer IDs must be unique within a project.")
        material_ids = [window.material_id for window in self.material_windows]
        if len(material_ids) != len(set(material_ids)):
            raise ValueError("Material window IDs must be unique within a project.")

    def add_layer(self, layer: Layer) -> None:
        """Append an epitaxial layer while preserving stable identity rules."""

        if any(existing.layer_id == layer.layer_id for existing in self.layers):
            raise ValueError(f"Duplicate layer ID: {layer.layer_id}")
        self.layers.append(layer)

    def remove_layer(self, layer_id: str) -> Layer:
        """Remove and return a layer by stable ID."""

        for index, layer in enumerate(self.layers):
            if layer.layer_id == layer_id:
                return self.layers.pop(index)
        raise KeyError(f"Unknown layer ID: {layer_id}")

    def move_layer(self, layer_id: str, new_index: int) -> None:
        """Move a layer to a new substrate-to-surface list position."""

        if not 0 <= new_index < len(self.layers):
            raise IndexError("Layer destination is outside the project.")
        layer = self.remove_layer(layer_id)
        self.layers.insert(new_index, layer)


def _finite_number(value: object, field_name: str) -> float:
    """Return a finite float while rejecting booleans and non-numeric values."""

    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be a finite number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a finite number.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be a finite number.")
    return number
