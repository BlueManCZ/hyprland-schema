"""Tests for the hyprland_schema._migration module."""

import pytest

from hyprland_schema._migration import (
    MigrationError,
    apply_migration,
    compute_diff,
)
from hyprland_schema._model import HyprOption


def _make_option(**overrides: object) -> HyprOption:
    """Create a HyprOption with sensible defaults, overriding specific fields."""
    defaults = {
        "key": "general:test",
        "section": ("general",),
        "name": "test",
        "description": "a test option",
        "type": "int",
        "default": 1,
        "min": 0,
        "max": 10,
    }
    defaults.update(overrides)
    return HyprOption(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# HyprOption.to_dict / HyprOption.from_dict roundtrip
# ---------------------------------------------------------------------------


class TestDictRoundtrip:
    def test_simple_int_option(self) -> None:
        opt = _make_option()
        d = opt.to_dict()
        restored = HyprOption.from_dict(d)
        assert restored == opt

    def test_tuple_fields_become_lists(self) -> None:
        opt = _make_option(section=("decoration", "blur"), enum_values=("a", "b"))
        d = opt.to_dict()
        assert isinstance(d["section"], list)
        assert isinstance(d["enum_values"], list)

    def test_tuple_fields_restored(self) -> None:
        opt = _make_option(
            key="decoration:blur:offset",
            section=("decoration", "blur"),
            type="vec2",
            default=(0.0, 0.0),
            min=None,
            max=None,
            default_min=(-5.0, -5.0),
            default_max=(5.0, 5.0),
        )
        d = opt.to_dict()
        restored = HyprOption.from_dict(d)
        assert restored == opt
        assert isinstance(restored.section, tuple)
        assert isinstance(restored.default, tuple)
        assert isinstance(restored.default_min, tuple)
        assert isinstance(restored.default_max, tuple)

    def test_none_fields_omitted(self) -> None:
        opt = _make_option()
        d = opt.to_dict()
        assert "enum_values" not in d
        assert "default_str" not in d
        assert "default_min" not in d
        assert "default_max" not in d

    def test_choice_option_roundtrip(self) -> None:
        opt = _make_option(
            type="choice",
            default=0,
            min=None,
            max=None,
            default_str="dwindle",
            enum_values=("dwindle", "master"),
        )
        d = opt.to_dict()
        restored = HyprOption.from_dict(d)
        assert restored == opt
        assert isinstance(restored.enum_values, tuple)

    def test_all_real_options_roundtrip(self) -> None:
        """Every option from the actual data should survive a dict roundtrip."""
        from hyprland_schema import OPTIONS

        for opt in OPTIONS:
            d = opt.to_dict()
            restored = HyprOption.from_dict(d)
            assert restored == opt, f"roundtrip failed for {opt.key}"


# ---------------------------------------------------------------------------
# apply_migration
# ---------------------------------------------------------------------------


class TestApplyMigration:
    def test_remove(self) -> None:
        options = [
            {"key": "a", "type": "int", "default": 1},
            {"key": "b", "type": "bool", "default": True},
        ]
        migration = {
            "format_version": 1,
            "from_version": "v2",
            "to_version": "v1",
            "operations": [{"op": "remove", "key": "b"}],
        }
        result = apply_migration(options, migration)
        assert len(result) == 1
        assert result[0]["key"] == "a"

    def test_remove_nonexistent_raises(self) -> None:
        migration = {
            "format_version": 1,
            "operations": [{"op": "remove", "key": "nonexistent"}],
        }
        with pytest.raises(MigrationError, match="not found"):
            apply_migration([], migration)

    def test_add(self) -> None:
        options = [{"key": "a", "type": "int", "default": 1}]
        new_opt = {"key": "b", "type": "bool", "default": False}
        migration = {
            "format_version": 1,
            "operations": [{"op": "add", "option": new_opt}],
        }
        result = apply_migration(options, migration)
        assert len(result) == 2
        assert result[1]["key"] == "b"

    def test_add_duplicate_raises(self) -> None:
        options = [{"key": "a", "type": "int", "default": 1}]
        migration = {
            "format_version": 1,
            "operations": [{"op": "add", "option": {"key": "a"}}],
        }
        with pytest.raises(MigrationError, match="already exists"):
            apply_migration(options, migration)

    def test_modify(self) -> None:
        options = [{"key": "a", "type": "int", "default": 5, "max": 20}]
        migration = {
            "format_version": 1,
            "operations": [
                {"op": "modify", "key": "a", "fields": {"default": [5, 3], "max": [20, 10]}}
            ],
        }
        result = apply_migration(options, migration)
        assert result[0]["default"] == 3
        assert result[0]["max"] == 10

    def test_modify_validates_current_value(self) -> None:
        options = [{"key": "a", "type": "int", "default": 99}]
        migration = {
            "format_version": 1,
            "operations": [{"op": "modify", "key": "a", "fields": {"default": [5, 3]}}],
        }
        with pytest.raises(MigrationError, match="expected 5"):
            apply_migration(options, migration)

    def test_modify_nonexistent_raises(self) -> None:
        migration = {
            "format_version": 1,
            "operations": [{"op": "modify", "key": "x", "fields": {"default": [1, 2]}}],
        }
        with pytest.raises(MigrationError, match="not found"):
            apply_migration([], migration)

    def test_unknown_op_raises(self) -> None:
        migration = {
            "format_version": 1,
            "operations": [{"op": "rename", "key": "a"}],
        }
        with pytest.raises(MigrationError, match="unknown operation"):
            apply_migration([], migration)

    def test_does_not_mutate_input(self) -> None:
        options = [{"key": "a", "type": "int", "default": 5}]
        migration = {
            "format_version": 1,
            "operations": [{"op": "modify", "key": "a", "fields": {"default": [5, 3]}}],
        }
        apply_migration(options, migration)
        assert options[0]["default"] == 5  # original unchanged

    def test_chain(self) -> None:
        """Apply two migrations in sequence."""
        options = [
            {"key": "a", "type": "int", "default": 10},
            {"key": "b", "type": "bool", "default": True},
            {"key": "c", "type": "string", "default": "new"},
        ]
        # v3 → v2: remove "c", modify "a" default 10→5
        mig1 = {
            "format_version": 1,
            "operations": [
                {"op": "remove", "key": "c"},
                {"op": "modify", "key": "a", "fields": {"default": [10, 5]}},
            ],
        }
        # v2 → v1: add "d", modify "b" default True→False
        mig2 = {
            "format_version": 1,
            "operations": [
                {"op": "add", "option": {"key": "d", "type": "float", "default": 0.5}},
                {"op": "modify", "key": "b", "fields": {"default": [True, False]}},
            ],
        }
        v2 = apply_migration(options, mig1)
        v1 = apply_migration(v2, mig2)

        by_key = {o["key"]: o for o in v1}
        assert "c" not in by_key
        assert "d" in by_key
        assert by_key["a"]["default"] == 5
        assert by_key["b"]["default"] is False
        assert by_key["d"]["default"] == 0.5


# ---------------------------------------------------------------------------
# compute_diff
# ---------------------------------------------------------------------------


class TestComputeDiff:
    def test_identical(self) -> None:
        opts = [{"key": "a", "type": "int", "default": 1}]
        diff = compute_diff(opts, opts, "v1", "v2")
        assert diff["operations"] == []

    def test_added_option(self) -> None:
        old = [{"key": "a", "type": "int", "default": 1}]
        new = [
            {"key": "a", "type": "int", "default": 1},
            {"key": "b", "type": "bool", "default": True},
        ]
        diff = compute_diff(old, new, "v1", "v2")
        ops = diff["operations"]
        assert len(ops) == 1
        assert ops[0]["op"] == "remove"
        assert ops[0]["key"] == "b"

    def test_removed_option(self) -> None:
        old = [
            {"key": "a", "type": "int", "default": 1},
            {"key": "b", "type": "bool", "default": True},
        ]
        new = [{"key": "a", "type": "int", "default": 1}]
        diff = compute_diff(old, new, "v1", "v2")
        ops = diff["operations"]
        assert len(ops) == 1
        assert ops[0]["op"] == "add"
        assert ops[0]["option"]["key"] == "b"

    def test_modified_field(self) -> None:
        old = [{"key": "a", "type": "int", "default": 3}]
        new = [{"key": "a", "type": "int", "default": 5}]
        diff = compute_diff(old, new, "v1", "v2")
        ops = diff["operations"]
        assert len(ops) == 1
        assert ops[0]["op"] == "modify"
        assert ops[0]["fields"]["default"] == [5, 3]

    def test_multiple_changes(self) -> None:
        old = [
            {"key": "a", "type": "int", "default": 1},
            {"key": "b", "type": "bool", "default": True},
        ]
        new = [
            {"key": "a", "type": "int", "default": 2},
            {"key": "c", "type": "string", "default": "x"},
        ]
        diff = compute_diff(old, new, "v1", "v2")
        ops_by_type = {}
        for op in diff["operations"]:
            ops_by_type.setdefault(op["op"], []).append(op)
        assert len(ops_by_type["remove"]) == 1  # "c" added in new
        assert len(ops_by_type["add"]) == 1  # "b" removed in new
        assert len(ops_by_type["modify"]) == 1  # "a" changed

    def test_format_version(self) -> None:
        diff = compute_diff([], [], "v1", "v2")
        assert diff["format_version"] == 1
        assert diff["from_version"] == "v2"
        assert diff["to_version"] == "v1"

    def test_roundtrip(self) -> None:
        """Compute diff, then apply it to new_options, should get old_options."""
        old = [
            {"key": "a", "type": "int", "default": 1, "min": 0, "max": 10},
            {"key": "b", "type": "bool", "default": True},
        ]
        new = [
            {"key": "a", "type": "int", "default": 5, "min": 0, "max": 20},
            {"key": "c", "type": "string", "default": "hello"},
        ]
        diff = compute_diff(old, new, "v1", "v2")
        restored = apply_migration(new, diff)
        restored_by_key = {o["key"]: o for o in restored}
        old_by_key = {o["key"]: o for o in old}
        assert restored_by_key == old_by_key
