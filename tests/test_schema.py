"""Tests for the hyprland_schema package."""

import pytest

from hyprland_schema import (
    HYPRLAND_VERSION,
    OPTIONS,
    OPTIONS_BY_KEY,
    HyprOption,
    get_section,
    get_subsection,
)


class TestImports:
    def test_version_is_string(self) -> None:
        assert isinstance(HYPRLAND_VERSION, str)
        assert HYPRLAND_VERSION.startswith("v")

    def test_options_non_empty(self) -> None:
        assert len(OPTIONS) > 0

    def test_options_is_tuple(self) -> None:
        assert isinstance(OPTIONS, tuple)

    def test_options_by_key_matches(self) -> None:
        assert len(OPTIONS_BY_KEY) == len(OPTIONS)
        for opt in OPTIONS:
            assert OPTIONS_BY_KEY[opt.key] is opt


class TestHyprOption:
    def test_frozen(self) -> None:
        opt = OPTIONS[0]
        with pytest.raises(AttributeError):
            opt.key = "other"  # type: ignore[misc]

    def test_fields(self) -> None:
        opt = OPTIONS_BY_KEY["general:border_size"]
        assert opt.key == "general:border_size"
        assert opt.section == ("general",)
        assert opt.name == "border_size"
        assert opt.type == "int"
        assert opt.default == 1
        assert opt.min == 0
        assert opt.max == 20
        assert isinstance(opt, HyprOption)

    def test_section_is_tuple(self) -> None:
        for opt in OPTIONS:
            assert isinstance(opt.section, tuple), f"{opt.key}: section is {type(opt.section)}"

    def test_enum_values_are_tuple(self) -> None:
        for opt in OPTIONS:
            if opt.enum_values is not None:
                assert isinstance(opt.enum_values, tuple), (
                    f"{opt.key}: enum_values is {type(opt.enum_values)}"
                )


class TestValidate:
    def test_valid_int_in_range(self) -> None:
        opt = HyprOption(
            key="k", section=(), name="k", description="", type="int", default=1, min=0, max=10
        )
        assert opt.validate(5) is None

    def test_below_min(self) -> None:
        opt = HyprOption(
            key="k", section=(), name="k", description="", type="int", default=1, min=0, max=10
        )
        assert opt.validate(-1) is not None

    def test_above_max(self) -> None:
        opt = HyprOption(
            key="k", section=(), name="k", description="", type="int", default=1, min=0, max=10
        )
        assert opt.validate(11) is not None

    def test_at_boundaries(self) -> None:
        opt = HyprOption(
            key="k", section=(), name="k", description="", type="int", default=1, min=0, max=10
        )
        assert opt.validate(0) is None
        assert opt.validate(10) is None

    def test_float_range(self) -> None:
        opt = HyprOption(
            key="k",
            section=(),
            name="k",
            description="",
            type="float",
            default=0.5,
            min=0.0,
            max=1.0,
        )
        assert opt.validate(0.5) is None
        assert opt.validate(1.5) is not None

    def test_no_constraints_passes(self) -> None:
        opt = HyprOption(key="k", section=(), name="k", description="", type="int", default=1)
        assert opt.validate(9999) is None

    def test_enum_valid(self) -> None:
        opt = HyprOption(
            key="k",
            section=(),
            name="k",
            description="",
            type="string",
            default="a",
            enum_values=("a", "b", "c"),
        )
        assert opt.validate("a") is None

    def test_enum_invalid(self) -> None:
        opt = HyprOption(
            key="k",
            section=(),
            name="k",
            description="",
            type="string",
            default="a",
            enum_values=("a", "b", "c"),
        )
        assert opt.validate("z") is not None

    def test_non_numeric_for_int_type(self) -> None:
        opt = HyprOption(
            key="k", section=(), name="k", description="", type="int", default=0, min=0, max=10
        )
        assert opt.validate("notanumber") is not None

    def test_string_type_skips_numeric_check(self) -> None:
        opt = HyprOption(
            key="k", section=(), name="k", description="", type="string", default="hello"
        )
        assert opt.validate("anything") is None

    def test_choice_validated(self) -> None:
        opt = HyprOption(
            key="k", section=(), name="k", description="", type="choice", default=0, min=0, max=2
        )
        assert opt.validate(1) is None
        assert opt.validate(5) is not None


class TestGetSection:
    def test_general(self) -> None:
        opts = get_section("general")
        assert len(opts) > 0
        for opt in opts:
            assert opt.section[0] == "general"

    def test_decoration(self) -> None:
        opts = get_section("decoration")
        assert len(opts) > 0

    def test_unknown_section(self) -> None:
        assert get_section("nonexistent") == []


class TestGetSubsection:
    def test_decoration_blur(self) -> None:
        opts = get_subsection("decoration", "blur")
        assert len(opts) > 0
        for opt in opts:
            assert opt.section == ("decoration", "blur")

    def test_unknown_subsection(self) -> None:
        assert get_subsection("decoration", "nonexistent") == []


class TestAllOptions:
    def test_every_option_has_key(self) -> None:
        for opt in OPTIONS:
            assert opt.key
            assert opt.name
            assert opt.type

    def test_types_are_known(self) -> None:
        known = {
            "bool",
            "int",
            "float",
            "string",
            "color",
            "gradient",
            "vec2",
            "choice",
            "cssgap",
            "font_weight",
        }
        for opt in OPTIONS:
            assert opt.type in known, f"{opt.key}: unknown type {opt.type}"

    def test_int_options_have_range(self) -> None:
        # Upstream may leave an int open-ended (e.g. `input:tablettool:eraser_button_override`
        # declares only `.min`), so only the lower bound is guaranteed.
        for opt in OPTIONS:
            if opt.type == "int":
                assert opt.min is not None, f"{opt.key}: int without min"
                if opt.max is not None:
                    assert opt.max >= opt.min, f"{opt.key}: max {opt.max} below min {opt.min}"

    def test_choice_options_have_enum(self) -> None:
        for opt in OPTIONS:
            if opt.type == "choice":
                assert opt.enum_values is not None, f"{opt.key}: choice without enum_values"
                assert len(opt.enum_values) > 0
