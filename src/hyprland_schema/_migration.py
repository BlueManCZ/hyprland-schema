"""Migration engine for versioned Hyprland schemas.

Provides structured reverse diffs between schema versions and the machinery
to apply them, enabling reconstruction of any supported older schema from
the latest version.
"""

import functools
import json
import logging
import os
from collections.abc import Sequence
from importlib import resources
from pathlib import Path
from typing import Any

from hyprland_schema._model import HyprOption

logger = logging.getLogger(__name__)


class MigrationError(Exception):
    """Raised when a migration cannot be applied."""


# ---------------------------------------------------------------------------
# Apply a single migration
# ---------------------------------------------------------------------------


def apply_migration(
    options: list[dict[str, Any]], migration: dict[str, Any]
) -> list[dict[str, Any]]:
    """Apply a reverse migration to a list of option dicts.

    Returns a new list — the input is not modified.
    """
    result = [{**o} for o in options]
    by_key = {o["key"]: o for o in result}
    keys_to_remove: set[str] = set()

    for op in migration["operations"]:
        if op["op"] == "remove":
            key = op["key"]
            if key not in by_key:
                raise MigrationError(f"remove: option '{key}' not found")
            keys_to_remove.add(key)
            del by_key[key]

        elif op["op"] == "add":
            option = {**op["option"]}
            key = option["key"]
            if key in by_key:
                raise MigrationError(f"add: option '{key}' already exists")
            result.append(option)
            by_key[key] = option
            keys_to_remove.discard(key)

        elif op["op"] == "modify":
            key = op["key"]
            if key not in by_key:
                raise MigrationError(f"modify: option '{key}' not found")
            target = by_key[key]
            for field_name, (new_val, old_val) in op["fields"].items():
                current = target.get(field_name)
                if current != new_val:
                    raise MigrationError(
                        f"modify: '{key}.{field_name}' expected {new_val!r}, got {current!r}"
                    )
                target[field_name] = old_val

        else:
            raise MigrationError(f"unknown operation: {op['op']!r}")

    if keys_to_remove:
        result = [o for o in result if o["key"] not in keys_to_remove]

    return result


# ---------------------------------------------------------------------------
# Compute diff between two option sets
# ---------------------------------------------------------------------------


def compute_diff(
    old_options: list[dict[str, Any]],
    new_options: list[dict[str, Any]],
    old_version: str,
    new_version: str,
) -> dict[str, Any]:
    """Compute a reverse migration from new_version to old_version.

    The resulting migration, when applied to new_options, produces old_options.
    """
    old_by_key = {o["key"]: o for o in old_options}
    new_by_key = {o["key"]: o for o in new_options}

    operations: list[dict[str, Any]] = []

    # For each option in the new version: if absent in old, remove it (going backward);
    # if present in both, record any field changes as a modify operation.
    for key, new_opt in new_by_key.items():
        if key not in old_by_key:
            operations.append({"op": "remove", "key": key})
            continue
        old_opt = old_by_key[key]
        changed_fields: dict[str, list[Any]] = {}
        for field_name in old_opt.keys() | new_opt.keys():
            old_val = old_opt.get(field_name)
            new_val = new_opt.get(field_name)
            if old_val != new_val:
                changed_fields[field_name] = [new_val, old_val]
        if changed_fields:
            operations.append({"op": "modify", "key": key, "fields": changed_fields})

    # Options removed in new version → add back when going backward.
    for key in old_by_key:
        if key not in new_by_key:
            operations.append({"op": "add", "option": old_by_key[key]})

    return {
        "format_version": 1,
        "from_version": new_version,
        "to_version": old_version,
        "operations": operations,
    }


# ---------------------------------------------------------------------------
# Migration / snapshot loading
# ---------------------------------------------------------------------------

_MIGRATIONS_PACKAGE = "hyprland_schema._migrations"


def _load_bundled_json(filename: str) -> dict[str, Any]:
    """Load a JSON file from the bundled _migrations package."""
    ref = resources.files(_MIGRATIONS_PACKAGE).joinpath(filename)
    return json.loads(ref.read_text(encoding="utf-8"))  # type: ignore[arg-type]


def load_migration(from_version: str, to_version: str) -> dict[str, Any]:
    """Load a migration JSON from the bundled _migrations package."""
    return _load_bundled_json(f"{from_version}_to_{to_version}.json")


def load_snapshot(version: str) -> list[dict[str, Any]]:
    """Load a full snapshot JSON from the bundled _migrations package."""
    return _load_bundled_json(f"{version}_snapshot.json")["options"]


# ---------------------------------------------------------------------------
# Build options for a target version
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=32)
def build_options(version: str) -> tuple[HyprOption, ...]:
    """Reconstruct the OPTIONS tuple for a given Hyprland version.

    Resolution order:
    1. Latest version -> return _data.OPTIONS directly.
    2. Bundled version -> walk the reverse migration chain from the nearest snapshot.
    3. Disk cache at ~/.cache/hyprland-schema/ -> load from cache.
    4. Download ConfigDescriptions.hpp from GitHub, parse, and cache.
    """
    from hyprland_schema._data import HYPRLAND_VERSION, OPTIONS
    from hyprland_schema._migrations._registry import SNAPSHOTS, VERSIONS

    if version == HYPRLAND_VERSION:
        return OPTIONS

    if version in VERSIONS:
        return _build_from_migrations(version, OPTIONS, HYPRLAND_VERSION, VERSIONS, SNAPSHOTS)

    # Not bundled — try disk cache, then fetch.
    cached = _load_disk_cache(version)
    if cached is not None:
        return cached

    return _fetch_and_parse(version)


def _build_from_migrations(
    version: str,
    latest_options: tuple[HyprOption, ...],
    latest_version: str,
    versions: tuple[str, ...],
    snapshots: frozenset[str],
) -> tuple[HyprOption, ...]:
    """Walk the migration chain to reconstruct a bundled version."""
    target_idx = versions.index(version)

    # Walk backward (toward newer versions) to find a snapshot.
    snapshot_idx: int | None = None
    for i in range(target_idx, -1, -1):
        if versions[i] in snapshots:
            snapshot_idx = i
            break
    if snapshot_idx is None:
        raise MigrationError(f"No snapshot found in the migration chain for version {version}")

    # Load the snapshot as option dicts.
    snapshot_ver = versions[snapshot_idx]
    if snapshot_ver == latest_version:
        option_dicts = [o.to_dict() for o in latest_options]
    else:
        option_dicts = load_snapshot(snapshot_ver)

    # Apply migrations from snapshot down to target.
    for i in range(snapshot_idx, target_idx):
        from_ver = versions[i]
        to_ver = versions[i + 1]
        migration = load_migration(from_ver, to_ver)
        option_dicts = apply_migration(option_dicts, migration)

    return tuple(HyprOption.from_dict(d) for d in option_dicts)


# ---------------------------------------------------------------------------
# Disk cache for fetched versions
# ---------------------------------------------------------------------------


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return Path(base) / "hyprland-schema"
    return Path.home() / ".cache" / "hyprland-schema"


def _cache_path(version: str) -> Path:
    return _cache_dir() / f"{version}.json"


def _load_disk_cache(version: str) -> tuple[HyprOption, ...] | None:
    """Load a cached version from disk, or return None if not cached."""
    path = _cache_path(version)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return tuple(HyprOption.from_dict(d) for d in data["options"])


def _save_disk_cache(version: str, options: Sequence[HyprOption]) -> None:
    """Save parsed options to the disk cache."""
    path = _cache_path(version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "type": "cache",
                "version": version,
                "options": [o.to_dict() for o in options],
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# On-the-fly fetch for unsupported versions
# ---------------------------------------------------------------------------


def _fetch_and_parse(version: str) -> tuple[HyprOption, ...]:
    """Download ConfigDescriptions.hpp from GitHub, parse it, and cache the result."""
    from urllib.error import HTTPError, URLError

    from hyprland_schema._parser import fetch_header, parse_header

    logger.info("Fetching %s from GitHub", version)

    try:
        content = fetch_header(version)
    except HTTPError as e:
        raise MigrationError(
            f"Failed to fetch version {version!r}: HTTP {e.code}. "
            f"Check that this Hyprland version tag exists on GitHub."
        ) from e
    except URLError as e:
        raise MigrationError(
            f"Failed to fetch version {version!r}: {e.reason}. "
            f"Check your internet connection or use a bundled version."
        ) from e

    options = parse_header(content)
    if not options:
        raise MigrationError(
            f"No options found for version {version!r} — the header format may have changed."
        )

    result = tuple(options)
    _save_disk_cache(version, result)
    return result
