"""Hyprland configuration option model."""

from dataclasses import MISSING, dataclass, fields
from typing import Any, Self


@dataclass(frozen=True, slots=True)
class HyprOption:
    """A single Hyprland configuration option with metadata."""

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
            if f.name in _REQUIRED_FIELDS or val is not None:
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

    def validate(self, value: Any) -> str | None:
        """Check *value* against the option's schema constraints.

        Returns an error message string if validation fails, or ``None`` if
        the value is acceptable. Numeric types are bounds-checked against
        ``min``/``max``; a ``choice`` takes either of the two forms Hyprland
        accepts; any other ``enum_values`` restrict the stringified value to
        the listed choices.
        """
        if self.type == "choice" and self.enum_values:
            return self._validate_choice(value)

        if self.type in ("int", "float", "choice"):
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                return f"expected a numeric value for {self.key!r}, got {value!r}"
            if self.min is not None and numeric < self.min:
                return f"value {value} for {self.key!r} is below minimum {self.min}"
            if self.max is not None and numeric > self.max:
                return f"value {value} for {self.key!r} is above maximum {self.max}"

        if self.enum_values is not None and str(value) not in self.enum_values:
            return f"value {value!r} for {self.key!r} is not one of {self.enum_values}"

        return None

    def _validate_choice(self, value: Any) -> str | None:
        """Accept either a choice name or the integer it maps to.

        Hyprland stores choices as ints numbered from zero in ``enum_values``
        order, and only its Lua parser also takes the name, so both forms
        reach here as legitimate input.
        """
        names = self.enum_values or ()
        if value in names:
            return None

        error = (
            f"value {value!r} for {self.key!r} is not one of {names} "
            f"or an index in 0-{len(names) - 1}"
        )
        try:
            index = int(value)
        except (TypeError, ValueError, OverflowError):
            return error
        return None if 0 <= index < len(names) else error


# Fields without defaults — always included in dict/JSON output.
# Derived automatically so adding a required field can't drift out of sync.
_REQUIRED_FIELDS: frozenset[str] = frozenset(
    f.name for f in fields(HyprOption) if f.default is MISSING and f.default_factory is MISSING
)
