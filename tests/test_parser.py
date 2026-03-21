"""Tests for the hyprland_schema._parser module."""

import pytest

from hyprland_schema._model import HyprOption
from hyprland_schema._parser import parse_header

# Minimal C++ header snippet for testing parse_header.
_SAMPLE_HEADER = """
inline static const std::vector<SConfigOptionDescription> CONFIG_OPTIONS = {
    SConfigOptionDescription{
        .value = "general:border_size",
        .description = "size of the border around windows",
        .type = CONFIG_OPTION_INT,
        .data = SConfigOptionDescription::SRangeData{1, 0, 20},
    },
    SConfigOptionDescription{
        .value = "general:no_border_on_floating",
        .description = "disable borders for floating windows",
        .type = CONFIG_OPTION_BOOL,
        .data = SConfigOptionDescription::SBoolData{false},
    },
    SConfigOptionDescription{
        .value = "general:gaps_out",
        .description = "gaps between windows"
                       " and monitor edges",
        .type = CONFIG_OPTION_STRING_SHORT,
        .data = SConfigOptionDescription::SStringData{"5"},
    },
    SConfigOptionDescription{
        .value = "decoration:blur:enabled",
        .description = "enable kawase window background blur",
        .type = CONFIG_OPTION_BOOL,
        .data = SConfigOptionDescription::SBoolData{true},
    },
    SConfigOptionDescription{
        .value = "general:col.active_border",
        .description = "border color for the active window",
        .type = CONFIG_OPTION_GRADIENT,
        .data = SConfigOptionDescription::SGradientData{"0xffffffff"},
    },
    SConfigOptionDescription{
        .value = "general:layout",
        .description = "which layout to use",
        .type = CONFIG_OPTION_CHOICE,
        .data = SConfigOptionDescription::SChoiceData{0, "dwindle,master"},
    },
    SConfigOptionDescription{
        .value = "misc:vfr",
        .description = "variable frame rate",
        .type = CONFIG_OPTION_FLOAT,
        .data = SConfigOptionDescription::SFloatData{1.0f, 0.0f, 1.0f},
    },
    SConfigOptionDescription{
        .value = "decoration:col.shadow",
        .description = "shadow color",
        .type = CONFIG_OPTION_COLOR,
        .data = SConfigOptionDescription::SColorData{0xee1a1a2e},
    },
    SConfigOptionDescription{
        .value = "general:resize_corner",
        .description = "corner for resizing",
        .type = CONFIG_OPTION_INT,
        .data = SConfigOptionDescription::SRangeData{.value = 0, .min = 0, .max = 4},
    },
    SConfigOptionDescription{
        .value = "decoration:blur:offset",
        .description = "blur offset",
        .type = CONFIG_OPTION_VECTOR,
        .data = SConfigOptionDescription::SVectorData{{0.0f, 0.0f}, {-5.0f, -5.0f}, {5.0f, 5.0f}},
    },
    SConfigOptionDescription{
        .value = "general:empty_string",
        .description = "empty default",
        .type = CONFIG_OPTION_STRING_SHORT,
        .data = SConfigOptionDescription::SStringData{STRVAL_EMPTY},
    },
};
"""


class TestParseHeader:
    @classmethod
    def setup_class(cls) -> None:
        cls._options = parse_header(_SAMPLE_HEADER)
        cls._by_key = {o.key: o for o in cls._options}

    def test_returns_hypr_options(self) -> None:
        assert all(isinstance(o, HyprOption) for o in self._options)

    def test_option_count(self) -> None:
        assert len(self._options) == 11

    def test_int_option(self) -> None:
        opt = self._by_key["general:border_size"]
        assert opt.type == "int"
        assert opt.default == 1
        assert opt.min == 0
        assert opt.max == 20
        assert opt.section == ("general",)
        assert opt.name == "border_size"

    def test_bool_option(self) -> None:
        opt = self._by_key["general:no_border_on_floating"]
        assert opt.type == "bool"
        assert opt.default is False

    def test_string_option(self) -> None:
        opt = self._by_key["general:gaps_out"]
        assert opt.type == "string"
        assert opt.default == "5"

    def test_multiline_description(self) -> None:
        opt = self._by_key["general:gaps_out"]
        assert "gaps between windows" in opt.description
        assert "monitor edges" in opt.description

    def test_nested_section(self) -> None:
        opt = self._by_key["decoration:blur:enabled"]
        assert opt.section == ("decoration", "blur")
        assert opt.name == "enabled"

    def test_gradient_option(self) -> None:
        opt = self._by_key["general:col.active_border"]
        assert opt.type == "gradient"
        assert opt.default == "0xffffffff"

    def test_choice_option(self) -> None:
        opt = self._by_key["general:layout"]
        assert opt.type == "choice"
        assert opt.default == 0
        assert opt.default_str == "dwindle"
        assert opt.enum_values == ("dwindle", "master")

    def test_float_option(self) -> None:
        opt = self._by_key["misc:vfr"]
        assert opt.type == "float"
        assert opt.default == 1.0
        assert opt.min == 0.0
        assert opt.max == 1.0

    def test_color_option(self) -> None:
        opt = self._by_key["decoration:col.shadow"]
        assert opt.type == "color"
        assert opt.default == "0xee1a1a2e"

    def test_named_initializer(self) -> None:
        """Test C++ named struct initializers (.value = ..., .min = ...)."""
        opt = self._by_key["general:resize_corner"]
        assert opt.type == "int"
        assert opt.default == 0
        assert opt.min == 0
        assert opt.max == 4

    def test_vector_option(self) -> None:
        opt = self._by_key["decoration:blur:offset"]
        assert opt.type == "vec2"
        assert opt.default == (0.0, 0.0)
        assert opt.default_min == (-5.0, -5.0)
        assert opt.default_max == (5.0, 5.0)

    def test_strval_empty(self) -> None:
        opt = self._by_key["general:empty_string"]
        assert opt.type == "string"
        assert opt.default == ""

    def test_sections_are_tuples(self) -> None:
        for opt in self._options:
            assert isinstance(opt.section, tuple)

    def test_enum_values_are_tuples(self) -> None:
        for opt in self._options:
            if opt.enum_values is not None:
                assert isinstance(opt.enum_values, tuple)

    def test_frozen(self) -> None:
        with pytest.raises(AttributeError):
            self._options[0].key = "other"  # type: ignore[misc]

    def test_empty_header(self) -> None:
        assert parse_header("") == []
        assert parse_header("no config options here") == []
