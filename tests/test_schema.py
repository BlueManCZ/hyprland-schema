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
        for opt in OPTIONS:
            if opt.type == "int":
                assert opt.min is not None, f"{opt.key}: int without min"
                assert opt.max is not None, f"{opt.key}: int without max"

    def test_choice_options_have_enum(self) -> None:
        for opt in OPTIONS:
            if opt.type == "choice":
                assert opt.enum_values is not None, f"{opt.key}: choice without enum_values"
                assert len(opt.enum_values) > 0
