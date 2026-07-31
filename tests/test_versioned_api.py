"""Tests for the versioned schema API (load, available_versions, Schema)."""

import functools
import json
import socket
from pathlib import Path
from unittest.mock import patch

import pytest

from hyprland_schema import (
    HYPRLAND_VERSION,
    OPTIONS,
    OPTIONS_BY_KEY,
    Schema,
    available_versions,
    load,
)
from hyprland_schema._migration import (
    MigrationError,
    _load_disk_cache,
    _save_disk_cache,
    build_options,
)
from hyprland_schema._model import HyprOption


@functools.cache
def _check_network() -> bool:
    try:
        socket.create_connection(("github.com", 443), timeout=3).close()
        return True
    except OSError:
        return False


requires_network = pytest.mark.skipif(not _check_network(), reason="no network connectivity")


class TestAvailableVersions:
    def test_returns_list(self) -> None:
        versions = available_versions()
        assert isinstance(versions, list)

    def test_non_empty(self) -> None:
        versions = available_versions()
        assert len(versions) > 0

    def test_latest_is_first(self) -> None:
        versions = available_versions()
        assert versions[0] == HYPRLAND_VERSION

    def test_all_start_with_v(self) -> None:
        for v in available_versions():
            assert v.startswith("v")


class TestLoad:
    def test_load_latest(self) -> None:
        schema = load(HYPRLAND_VERSION)
        assert isinstance(schema, Schema)
        assert schema.version == HYPRLAND_VERSION

    def test_load_latest_matches_globals(self) -> None:
        schema = load(HYPRLAND_VERSION)
        assert schema.options == OPTIONS
        assert schema.options_by_key == OPTIONS_BY_KEY

    @requires_network
    def test_load_invalid_version_raises(self) -> None:
        with pytest.raises(MigrationError, match="Failed to fetch"):
            load("v0.0.0")

    def test_load_accepts_bare_version(self) -> None:
        """hyprctl reports ``0.56.1`` where the git tag reads ``v0.56.1``."""
        schema = load(HYPRLAND_VERSION.removeprefix("v"))
        assert schema.version == HYPRLAND_VERSION
        assert schema.options == OPTIONS

    def test_load_bare_older_version_matches_tagged(self) -> None:
        older = available_versions()[-1]
        assert load(older.removeprefix("v")).options == load(older).options

    def test_load_returns_cached(self) -> None:
        s1 = load(HYPRLAND_VERSION)
        s2 = load(HYPRLAND_VERSION)
        # lru_cache means same object
        assert s1.options is s2.options


class TestSchema:
    def test_frozen(self) -> None:
        schema = load(HYPRLAND_VERSION)
        with pytest.raises(AttributeError):
            schema.version = "other"  # type: ignore[misc]

    def test_get_section(self) -> None:
        schema = load(HYPRLAND_VERSION)
        opts = schema.get_section("general")
        assert len(opts) > 0
        for opt in opts:
            assert opt.section[0] == "general"

    def test_get_subsection(self) -> None:
        schema = load(HYPRLAND_VERSION)
        opts = schema.get_subsection("decoration", "blur")
        assert len(opts) > 0
        for opt in opts:
            assert opt.section == ("decoration", "blur")

    def test_get_json(self) -> None:
        schema = load(HYPRLAND_VERSION)
        data = json.loads(schema.get_json())
        assert data["hyprland_version"] == HYPRLAND_VERSION
        assert data["generator"] == "hyprland-schema"
        assert isinstance(data["options"], list)
        assert len(data["options"]) == len(OPTIONS)

    def test_options_are_hypr_options(self) -> None:
        schema = load(HYPRLAND_VERSION)
        for opt in schema.options:
            assert isinstance(opt, HyprOption)

    def test_options_by_key_consistent(self) -> None:
        schema = load(HYPRLAND_VERSION)
        assert len(schema.options_by_key) == len(schema.options)
        for opt in schema.options:
            assert schema.options_by_key[opt.key] is opt


class TestDiskCache:
    def test_save_and_load(self, tmp_path: Path) -> None:
        """Disk cache roundtrip."""
        fake_version = "v99.99.99-test"

        with patch("hyprland_schema._migration._cache_dir", return_value=tmp_path):
            subset = OPTIONS[:3]
            _save_disk_cache(fake_version, subset)

            loaded = _load_disk_cache(fake_version)
            assert loaded is not None
            assert len(loaded) == 3
            assert loaded == subset

    def test_load_missing_returns_none(self, tmp_path: Path) -> None:
        with patch("hyprland_schema._migration._cache_dir", return_value=tmp_path):
            assert _load_disk_cache("v0.0.0-nonexistent") is None


class TestFetchFallback:
    @requires_network
    def test_fetch_real_old_version(self, tmp_path: Path) -> None:
        """Fetch a real old Hyprland version from GitHub, parse it, and cache."""
        build_options.cache_clear()

        with patch("hyprland_schema._migration._cache_dir", return_value=tmp_path):
            # v0.45.0 is a real Hyprland tag that should have ConfigDescriptions.hpp.
            result = build_options("v0.45.0")
            assert len(result) > 0
            assert all(isinstance(o, HyprOption) for o in result)

            # Should now be cached on disk.
            cached = _load_disk_cache("v0.45.0")
            assert cached is not None
            assert cached == result

        build_options.cache_clear()
