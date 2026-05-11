"""Schema container for a specific Hyprland version."""

import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from hyprland_schema._model import HyprOption

# Upstream renamed/relocated the option-metadata file in hyprwm/Hyprland#13817
# (landed for v0.55.0). Earlier tags carry the legacy header, later tags carry
# the new .cpp file. Pick the right one based on the version tag.
_NEW_FORMAT_MIN_VERSION = (0, 55, 0)
_LEGACY_SOURCE_URL = (
    "https://github.com/hyprwm/Hyprland/blob/{version}/src/config/ConfigDescriptions.hpp"
)
_NEW_SOURCE_URL = (
    "https://github.com/hyprwm/Hyprland/blob/{version}/src/config/values/ConfigValues.cpp"
)


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.lstrip("v").split("."))


def source_url(version: str) -> str:
    """Return the canonical upstream source URL for a Hyprland version tag."""
    template = (
        _NEW_SOURCE_URL
        if _version_tuple(version) >= _NEW_FORMAT_MIN_VERSION
        else _LEGACY_SOURCE_URL
    )
    return template.format(version=version)


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
            "source": source_url(self.version),
            "options": [o.to_dict() for o in self.options],
        }

    def get_json(self, *, indent: int | None = 2) -> str:
        """Return the schema as a JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)
