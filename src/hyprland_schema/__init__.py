"""Hyprland configuration option schema."""

import functools
from types import MappingProxyType

from hyprland_schema._data import HYPRLAND_VERSION as HYPRLAND_VERSION
from hyprland_schema._data import OPTIONS as OPTIONS
from hyprland_schema._model import HyprOption as HyprOption
from hyprland_schema._schema import Schema as Schema

__all__ = [
    "HYPRLAND_VERSION",
    "HyprOption",
    "OPTIONS",
    "OPTIONS_BY_KEY",
    "Schema",
    "available_versions",
    "get_json",
    "get_section",
    "get_subsection",
    "load",
]


@functools.cache
def _get_latest_schema() -> Schema:
    return Schema(version=HYPRLAND_VERSION, options=OPTIONS)


OPTIONS_BY_KEY: MappingProxyType[str, HyprOption] = _get_latest_schema().options_by_key


def get_section(section: str) -> list[HyprOption]:
    """Return all options whose top-level section matches."""
    return _get_latest_schema().get_section(section)


def get_subsection(section: str, subsection: str) -> list[HyprOption]:
    """Return all options in a nested subsection."""
    return _get_latest_schema().get_subsection(section, subsection)


def get_json(*, indent: int | None = 2) -> str:
    """Return the full schema as a JSON string.

    Produces the same format as the schema.json that the generator emits.
    """
    return _get_latest_schema().get_json(indent=indent)


@functools.lru_cache(maxsize=32)
def load(version: str) -> Schema:
    """Load the schema for a specific Hyprland version.

    Resolution order:
    1. Latest bundled version — instant (pre-parsed).
    2. Older bundled version — reconstructed via reverse migrations.
    3. Disk cache at ~/.cache/hyprland-schema/ — no network needed.
    4. Download from GitHub — fetches ConfigDescriptions.hpp and parses it.

    Results are cached in memory for repeated calls.
    """
    from hyprland_schema._migration import build_options

    opts = build_options(version)
    return Schema(version=version, options=opts)


def available_versions() -> list[str]:
    """Return all bundled Hyprland versions, newest first."""
    from hyprland_schema._migrations._registry import VERSIONS

    return list(VERSIONS)
