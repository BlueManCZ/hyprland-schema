"""Tests for generate_schema.py functions."""

import ast
import json
from pathlib import Path

import pytest

from generate_schema import (
    SchemaError,
    chain_ops_count,
    current_data_version,
    emit_json,
    emit_python,
    is_up_to_date,
    prune_redundant_migrations,
    repr_field,
    repr_value,
    resolve_version,
    update_registry,
    write_migration,
    write_snapshot,
)
from hyprland_schema._model import HyprOption

# ---------------------------------------------------------------------------
# _repr_value
# ---------------------------------------------------------------------------


class TestReprValue:
    def test_none(self) -> None:
        assert repr_value(None) == "None"

    def test_bool_true(self) -> None:
        assert repr_value(True) == "True"

    def test_bool_false(self) -> None:
        assert repr_value(False) == "False"

    def test_string(self) -> None:
        assert repr_value("hello") == "'hello'"

    def test_int(self) -> None:
        assert repr_value(42) == "42"

    def test_float(self) -> None:
        assert repr_value(3.14) == "3.14"

    def test_tuple(self) -> None:
        assert repr_value(("a", "b")) == "('a', 'b')"

    def test_single_element_tuple(self) -> None:
        assert repr_value(("a",)) == "('a',)"

    def test_list_emitted_as_tuple(self) -> None:
        assert repr_value(["a", "b"]) == "('a', 'b')"

    def test_nested(self) -> None:
        assert repr_value((1.0, 2.0)) == "(1.0, 2.0)"


# ---------------------------------------------------------------------------
# _repr_field
# ---------------------------------------------------------------------------


class TestReprField:
    def test_short_field_single_line(self) -> None:
        lines = repr_field("name", "short")
        assert len(lines) == 1
        assert lines[0].strip() == "name='short',"

    def test_long_string_wrapped(self) -> None:
        long_str = "x" * 200
        lines = repr_field("description", long_str)
        assert len(lines) > 1
        assert lines[0].strip() == "description=("
        assert lines[-1].strip() == "),"

    def test_all_lines_within_limit(self) -> None:
        long_str = "a" * 200
        lines = repr_field("description", long_str)
        for line in lines:
            assert len(line) <= 100

    def test_string_with_double_quotes(self) -> None:
        long_str = 'a "quoted" value ' * 12
        lines = repr_field("description", long_str)
        assert len(lines) > 1
        # Each chunk line must be a valid Python string literal.
        for line in lines[1:-1]:
            ast.literal_eval(line.strip())

    def test_non_string_not_split(self) -> None:
        lines = repr_field("default", 42)
        assert len(lines) == 1


# ---------------------------------------------------------------------------
# _current_data_version / is_up_to_date
# ---------------------------------------------------------------------------


class TestVersionDetection:
    def test_current_data_version(self, tmp_path: Path) -> None:
        pkg = tmp_path / "src" / "hyprland_schema"
        pkg.mkdir(parents=True)
        (pkg / "_data.py").write_text('HYPRLAND_VERSION = "v0.54.2"\n')
        assert current_data_version(tmp_path) == "v0.54.2"

    def test_current_data_version_missing(self, tmp_path: Path) -> None:
        assert current_data_version(tmp_path) is None

    def test_is_up_to_date_true(self, tmp_path: Path) -> None:
        pkg = tmp_path / "src" / "hyprland_schema"
        pkg.mkdir(parents=True)
        (pkg / "_data.py").write_text('HYPRLAND_VERSION = "v0.54.2"\n')
        assert is_up_to_date("v0.54.2", tmp_path) is True

    def test_is_up_to_date_false_wrong_version(self, tmp_path: Path) -> None:
        pkg = tmp_path / "src" / "hyprland_schema"
        pkg.mkdir(parents=True)
        (pkg / "_data.py").write_text('HYPRLAND_VERSION = "v0.54.1"\n')
        assert is_up_to_date("v0.54.2", tmp_path) is False

    def test_is_up_to_date_false_missing(self, tmp_path: Path) -> None:
        assert is_up_to_date("v0.54.2", tmp_path) is False


# ---------------------------------------------------------------------------
# resolve_version
# ---------------------------------------------------------------------------


class TestResolveVersion:
    def test_explicit_version(self, tmp_path: Path) -> None:
        assert resolve_version("v1.0.0", tmp_path) == "v1.0.0"

    def test_from_data_py(self, tmp_path: Path) -> None:
        pkg = tmp_path / "src" / "hyprland_schema"
        pkg.mkdir(parents=True)
        (pkg / "_data.py").write_text('HYPRLAND_VERSION = "v0.54.2"\n')
        assert resolve_version(None, tmp_path) == "v0.54.2"

    def test_missing_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SchemaError, match="no --version"):
            resolve_version(None, tmp_path)


# ---------------------------------------------------------------------------
# _write_migration / _write_snapshot
# ---------------------------------------------------------------------------


class TestWriteMigration:
    def test_writes_json(self, tmp_path: Path) -> None:
        migration = {
            "format_version": 1,
            "from_version": "v2",
            "to_version": "v1",
            "operations": [{"op": "remove", "key": "a"}],
        }
        pkg = tmp_path / "src" / "hyprland_schema" / "_migrations"
        pkg.mkdir(parents=True)
        path = write_migration(migration, tmp_path)
        assert path.name == "v2_to_v1.json"
        data = json.loads(path.read_text())
        assert data["from_version"] == "v2"
        assert len(data["operations"]) == 1


class TestWriteSnapshot:
    def test_writes_json(self, tmp_path: Path) -> None:
        opt = HyprOption(
            key="general:test",
            section=("general",),
            name="test",
            description="desc",
            type="int",
            default=1,
            min=0,
            max=10,
        )
        path = write_snapshot([opt], "v1.0.0", tmp_path)
        assert path.name == "v1.0.0_snapshot.json"
        data = json.loads(path.read_text())
        assert data["type"] == "snapshot"
        assert data["version"] == "v1.0.0"
        assert len(data["options"]) == 1


# ---------------------------------------------------------------------------
# _chain_ops_count
# ---------------------------------------------------------------------------


class TestChainOpsCount:
    def test_counts_operations(self, tmp_path: Path) -> None:
        mig_dir = tmp_path / "src" / "hyprland_schema" / "_migrations"
        mig_dir.mkdir(parents=True)

        # v3 → v2: 3 ops
        (mig_dir / "v3_to_v2.json").write_text(
            json.dumps({"operations": [{"op": "remove"}, {"op": "add"}, {"op": "modify"}]})
        )
        # v2 → v1: 2 ops
        (mig_dir / "v2_to_v1.json").write_text(
            json.dumps({"operations": [{"op": "remove"}, {"op": "modify"}]})
        )

        versions = ["v3", "v2", "v1"]
        assert chain_ops_count(tmp_path, versions, set()) == 5

    def test_stops_at_snapshot(self, tmp_path: Path) -> None:
        mig_dir = tmp_path / "src" / "hyprland_schema" / "_migrations"
        mig_dir.mkdir(parents=True)

        (mig_dir / "v3_to_v2.json").write_text(json.dumps({"operations": [{"op": "remove"}]}))
        (mig_dir / "v2_to_v1.json").write_text(
            json.dumps({"operations": [{"op": "add"}, {"op": "add"}]})
        )

        # v2 is a snapshot, so chain from v3 stops there.
        assert chain_ops_count(tmp_path, ["v3", "v2", "v1"], {"v2"}) == 1

    def test_empty_chain(self, tmp_path: Path) -> None:
        assert chain_ops_count(tmp_path, ["v1"], set()) == 0


# ---------------------------------------------------------------------------
# prune_redundant_migrations
# ---------------------------------------------------------------------------


class TestPruneRedundantMigrations:
    def _mkmig(self, mig_dir: Path, from_ver: str, to_ver: str) -> Path:
        path = mig_dir / f"{from_ver}_to_{to_ver}.json"
        path.write_text(json.dumps({"operations": []}))
        return path

    def test_deletes_when_to_version_is_snapshot(self, tmp_path: Path) -> None:
        mig_dir = tmp_path / "src" / "hyprland_schema" / "_migrations"
        mig_dir.mkdir(parents=True)
        target = self._mkmig(mig_dir, "v3", "v2")
        keep = self._mkmig(mig_dir, "v2", "v1")

        pruned = prune_redundant_migrations(tmp_path, {"v3", "v2"})

        assert pruned == [target]
        assert not target.exists()
        assert keep.exists()

    def test_keeps_when_to_version_not_snapshot(self, tmp_path: Path) -> None:
        mig_dir = tmp_path / "src" / "hyprland_schema" / "_migrations"
        mig_dir.mkdir(parents=True)
        keep = self._mkmig(mig_dir, "v2", "v1")

        assert prune_redundant_migrations(tmp_path, {"v3"}) == []
        assert keep.exists()

    def test_ignores_snapshot_files(self, tmp_path: Path) -> None:
        mig_dir = tmp_path / "src" / "hyprland_schema" / "_migrations"
        mig_dir.mkdir(parents=True)
        snap = mig_dir / "v2_snapshot.json"
        snap.write_text(json.dumps({"options": []}))

        assert prune_redundant_migrations(tmp_path, {"v2"}) == []
        assert snap.exists()

    def test_empty_dir(self, tmp_path: Path) -> None:
        mig_dir = tmp_path / "src" / "hyprland_schema" / "_migrations"
        mig_dir.mkdir(parents=True)
        assert prune_redundant_migrations(tmp_path, set()) == []


# ---------------------------------------------------------------------------
# _update_registry
# ---------------------------------------------------------------------------


class TestUpdateRegistry:
    def test_generates_registry(self, tmp_path: Path) -> None:
        mig_dir = tmp_path / "src" / "hyprland_schema" / "_migrations"
        mig_dir.mkdir(parents=True)

        # Create a migration file and a snapshot.
        (mig_dir / "v0.54.2_to_v0.54.1.json").write_text("{}")
        (mig_dir / "v0.54.0_snapshot.json").write_text("{}")

        # Also create a _data.py so current version is detected.
        pkg = tmp_path / "src" / "hyprland_schema"
        (pkg / "_data.py").write_text('HYPRLAND_VERSION = "v0.54.2"\n')

        path, _, _ = update_registry(tmp_path)
        content = path.read_text()

        assert "v0.54.2" in content
        assert "v0.54.1" in content
        assert "v0.54.0" in content
        assert "VERSIONS" in content
        assert "SNAPSHOTS" in content


# ---------------------------------------------------------------------------
# emit_json / emit_python
# ---------------------------------------------------------------------------

_SAMPLE_OPTIONS = [
    HyprOption(
        key="general:border_size",
        section=("general",),
        name="border_size",
        description="size of the border",
        type="int",
        default=1,
        min=0,
        max=20,
    ),
    HyprOption(
        key="general:layout",
        section=("general",),
        name="layout",
        description="which layout to use",
        type="choice",
        default=0,
        default_str="dwindle",
        enum_values=("dwindle", "master"),
    ),
]


class TestEmitJson:
    def test_writes_valid_json(self, tmp_path: Path) -> None:
        path = emit_json(_SAMPLE_OPTIONS, "v0.54.2", tmp_path)
        data = json.loads(path.read_text())
        assert data["hyprland_version"] == "v0.54.2"
        assert data["generator"] == "hyprland-schema"
        assert len(data["options"]) == 2

    def test_options_have_required_fields(self, tmp_path: Path) -> None:
        path = emit_json(_SAMPLE_OPTIONS, "v0.54.2", tmp_path)
        data = json.loads(path.read_text())
        for opt in data["options"]:
            assert "key" in opt
            assert "section" in opt
            assert "type" in opt
            assert "default" in opt

    def test_none_fields_omitted(self, tmp_path: Path) -> None:
        path = emit_json(_SAMPLE_OPTIONS, "v0.54.2", tmp_path)
        data = json.loads(path.read_text())
        int_opt = data["options"][0]
        assert "enum_values" not in int_opt
        assert "default_str" not in int_opt


class TestEmitPython:
    def test_writes_importable_module(self, tmp_path: Path) -> None:
        path = emit_python(_SAMPLE_OPTIONS, "v0.54.2", tmp_path)
        content = path.read_text()
        assert 'HYPRLAND_VERSION = "v0.54.2"' in content
        assert "OPTIONS: tuple[HyprOption, ...]" in content
        assert "general:border_size" in content

    def test_contains_all_options(self, tmp_path: Path) -> None:
        path = emit_python(_SAMPLE_OPTIONS, "v0.54.2", tmp_path)
        content = path.read_text()
        assert "general:border_size" in content
        assert "general:layout" in content

    def test_optional_fields_conditional(self, tmp_path: Path) -> None:
        path = emit_python(_SAMPLE_OPTIONS, "v0.54.2", tmp_path)
        content = path.read_text()
        # int option has min/max but not enum_values
        assert "min=0" in content
        assert "max=20" in content
        # choice option has enum_values
        assert "enum_values=" in content
        assert "default_str=" in content
