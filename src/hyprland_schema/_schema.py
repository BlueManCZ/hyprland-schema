"""Schema container for a specific Hyprland version."""

import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from hyprland_schema._model import HyprOption

# GitHub URL for human-readable links to ConfigDescriptions.hpp.
SOURCE_URL_TEMPLATE = (
    "https://github.com/hyprwm/Hyprland/blob/{version}/src/config/ConfigDescriptions.hpp"
)


@dataclass(frozen=True, slots=True)
class Schema:
    """Immutable snapshot of a Hyprland configuration schema for a specific version."""

    version: str
    options: tuple[HyprOption, ...]
    options_by_key: MappingProxyType[str, HyprOption] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "options_by_key", MappingProxyType({o.key: o for o in self.options})
        )

    def get_section(self, section: str) -> list[HyprOption]:
        """Return all options whose top-level section matches."""
        return [o for o in self.options if o.section and o.section[0] == section]

    def get_subsection(self, section: str, subsection: str) -> list[HyprOption]:
        """Return all options in a nested subsection."""
        return [o for o in self.options if o.section == (section, subsection)]

    def to_dict(self) -> dict[str, Any]:
        """Return the schema as a JSON-serializable dict."""
        return {
            "hyprland_version": self.version,
            "generator": "hyprland-schema",
            "source": SOURCE_URL_TEMPLATE.format(version=self.version),
            "options": [o.to_dict() for o in self.options],
        }

    def get_json(self, *, indent: int | None = 2) -> str:
        """Return the schema as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
