"""Hyprland configuration option model."""

import dataclasses
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Self


@dataclass(frozen=True, slots=True)
class HyprOption:
    """A single Hyprland configuration option with metadata."""

    # Fields without defaults — always included in dict/JSON output.
    # Derived automatically so adding a required field can't drift out of sync.
    _REQUIRED_FIELDS: ClassVar[frozenset[str]] = frozenset()  # populated by _init_required_fields

    key: str
    section: tuple[str, ...]
    name: str
    description: str
    type: str
    default: Any
    min: int | float | None = None
    max: int | float | None = None
    enum_values: tuple[str, ...] | None = None
    default_str: str | None = None
    default_min: tuple[float, ...] | None = None
    default_max: tuple[float, ...] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-serializable dict, omitting None optional fields."""
        d: dict[str, Any] = {}
        for f in fields(self):
            val = getattr(self, f.name)
            if f.name in self._REQUIRED_FIELDS or val is not None:
                d[f.name] = list(val) if isinstance(val, tuple) else val
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Deserialize a dict into a HyprOption (lists converted to tuples)."""
        kwargs: dict[str, Any] = {}
        for f in fields(cls):
            if f.name not in d:
                continue
            val = d[f.name]
            kwargs[f.name] = tuple(val) if isinstance(val, list) else val
        return cls(**kwargs)


# Derive _REQUIRED_FIELDS from the dataclass definition after the class is complete.
# This must happen at module level because frozen+slots dataclasses don't allow setattr.
HyprOption._REQUIRED_FIELDS = frozenset(  # type: ignore[misc]
    f.name
    for f in fields(HyprOption)
    if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
)
