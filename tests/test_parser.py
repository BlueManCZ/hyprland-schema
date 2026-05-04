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


# ---------------------------------------------------------------------------
# New format (ConfigValues.cpp, hyprwm/Hyprland#13817 and later)
# ---------------------------------------------------------------------------


# Minimal new-format C++ source covering every type alias and edge case.
_NEW_FORMAT_SAMPLE = """
#include "ConfigValues.hpp"

std::vector<SP<IValue>> Values::getConfigValues() {
#define MS makeConfigValue

    return std::vector<SP<IValue>>{
        MS<Int>("general:border_size", "size of the border around windows", 1,
                {.min = 0, .max = 20, .refresh = Supplementary::REFRESH_WINDOW_STATES}),
        MS<Bool>("general:resize_on_border",
                 "enables resizing windows by clicking and dragging on borders and gaps", false),
        MS<Float>("decoration:active_opacity", "opacity of active windows.", 1,
                  {.min = 0, .max = 1}),
        MS<Float>("layout:tolerance", "tolerance value", 0.1F, {.min = 0.F, .max = 1.F}),
        MS<String>("input:kb_layout", "Appropriate XKB keymap parameter", "us"),
        MS<String>("misc:swallow_regex", "The class regex.", STRVAL_EMPTY),
        MS<String>("group:groupbar:font_family",
                   "font used to display groupbar titles", "[[EMPTY]]"),
        MS<Color>("decoration:shadow:color", "shadow's color.", 0xee1a1a1a),
        MS<Color>("group:groupbar:text_color_inactive", "fall-back-to-default sentinel.", -1),
        MS<Gradient>("general:col.inactive_border", "border color for inactive windows",
                     CHyprColor{0xff444444}),
        MS<Gradient>("group:groupbar:col.active", "active group border color", 0x66ffff00),
        MS<Vec2>("decoration:shadow:offset", "shadow's rendering offset.", Config::VEC2{},
                 {.validator = vec2Range(-250, -250, 250, 250)}),
        MS<Vec2>("layout:aspect_ratio", "fixed aspect ratio", Config::VEC2{1, 2}),
        MS<CssGap>("general:gaps_in", "gaps between windows", 5,
                   {.refresh = Supplementary::REFRESH_LAYOUTS}),
        MS<FontWeight>("group:groupbar:font_weight_active",
                       "weight of the font used to display active groupbar titles"),
        MS<Int>("input:follow_mouse",
                "Specify if and how cursor movement should affect window focus.", 1,
                {.min = 0, .max = 3,
                 .map = OptionMap{{"disabled", 0}, {"follow", 1}, {"detached", 2}, {"separate", 3}},
                 .refresh = Supplementary::REFRESH_INPUT_DEVICES}),
        MS<Int>("binds:drag_threshold", "Movement threshold in pixels.", 0,
                {.min = 0, .max = std::numeric_limits<int>::max()}),
        MS<Int>("input:emulate_discrete_scroll",
                "Emulates discrete scrolling from "
                "high resolution scrolling events.",
                1, {.min = 0, .max = 2,
                    .map = OptionMap{{"disable", 0}, {"non_standard", 1}, {"force_all", 2}}}),
    };

#undef MS
}
"""


class TestParseNewFormat:
    @classmethod
    def setup_class(cls) -> None:
        cls._options = parse_header(_NEW_FORMAT_SAMPLE)
        cls._by_key = {o.key: o for o in cls._options}

    def test_returns_hypr_options(self) -> None:
        assert all(isinstance(o, HyprOption) for o in self._options)

    def test_option_count(self) -> None:
        # 18 entries in the sample.
        assert len(self._options) == 18

    def test_int_option(self) -> None:
        opt = self._by_key["general:border_size"]
        assert opt.type == "int"
        assert opt.default == 1
        assert opt.min == 0
        assert opt.max == 20
        assert opt.section == ("general",)
        assert opt.name == "border_size"

    def test_bool_option(self) -> None:
        opt = self._by_key["general:resize_on_border"]
        assert opt.type == "bool"
        assert opt.default is False

    def test_float_option_unsuffixed(self) -> None:
        opt = self._by_key["decoration:active_opacity"]
        assert opt.type == "float"
        assert opt.default == 1.0
        assert opt.min == 0
        assert opt.max == 1

    def test_float_option_with_f_suffix(self) -> None:
        opt = self._by_key["layout:tolerance"]
        assert opt.type == "float"
        assert opt.default == 0.1
        assert opt.min == 0.0
        assert opt.max == 1.0

    def test_string_option(self) -> None:
        opt = self._by_key["input:kb_layout"]
        assert opt.type == "string"
        assert opt.default == "us"

    def test_string_strval_empty(self) -> None:
        opt = self._by_key["misc:swallow_regex"]
        assert opt.type == "string"
        assert opt.default == ""

    def test_string_literal_sentinel_preserved(self) -> None:
        # "[[EMPTY]]" is meaningful to Hyprland — keep it verbatim, do not collapse.
        opt = self._by_key["group:groupbar:font_family"]
        assert opt.type == "string"
        assert opt.default == "[[EMPTY]]"

    def test_color_option(self) -> None:
        opt = self._by_key["decoration:shadow:color"]
        assert opt.type == "color"
        assert opt.default == "0xee1a1a1a"

    def test_color_negative_sentinel(self) -> None:
        opt = self._by_key["group:groupbar:text_color_inactive"]
        assert opt.type == "color"
        assert opt.default == -1

    def test_gradient_chyprcolor_wrapper(self) -> None:
        opt = self._by_key["general:col.inactive_border"]
        assert opt.type == "gradient"
        assert opt.default == "0xff444444"

    def test_gradient_bare_hex(self) -> None:
        opt = self._by_key["group:groupbar:col.active"]
        assert opt.type == "gradient"
        assert opt.default == "0x66ffff00"

    def test_vec2_default_constructed(self) -> None:
        opt = self._by_key["decoration:shadow:offset"]
        assert opt.type == "vec2"
        assert opt.default == (0.0, 0.0)

    def test_vec2_explicit(self) -> None:
        opt = self._by_key["layout:aspect_ratio"]
        assert opt.type == "vec2"
        assert opt.default == (1.0, 2.0)

    def test_cssgap_option(self) -> None:
        opt = self._by_key["general:gaps_in"]
        assert opt.type == "cssgap"
        assert opt.default == 5

    def test_font_weight_no_default(self) -> None:
        # FontWeight may omit the default arg — option is still emitted with default=None.
        opt = self._by_key["group:groupbar:font_weight_active"]
        assert opt.type == "font_weight"
        assert opt.default is None

    def test_int_with_map_promotes_to_choice(self) -> None:
        opt = self._by_key["input:follow_mouse"]
        assert opt.type == "choice"
        assert opt.default == 1
        assert opt.default_str == "follow"
        assert opt.enum_values == ("disabled", "follow", "detached", "separate")
        # min/max are dropped for choice — matches legacy schema shape.
        assert opt.min is None
        assert opt.max is None

    def test_numeric_limits_max(self) -> None:
        # std::numeric_limits<int>::max() expands to INT_MAX (2147483647).
        opt = self._by_key["binds:drag_threshold"]
        assert opt.type == "int"
        assert opt.max == 2147483647

    def test_multiline_description(self) -> None:
        opt = self._by_key["input:emulate_discrete_scroll"]
        assert "Emulates discrete scrolling from" in opt.description
        assert "high resolution scrolling events" in opt.description

    def test_nested_section(self) -> None:
        opt = self._by_key["decoration:shadow:color"]
        assert opt.section == ("decoration", "shadow")
        assert opt.name == "color"

    def test_sections_are_tuples(self) -> None:
        for opt in self._options:
            assert isinstance(opt.section, tuple)


def test_format_autodetect_legacy() -> None:
    """parse_header dispatches to the legacy parser when the legacy marker is present."""
    src = """
    SConfigOptionDescription{
        .value = "test:opt",
        .description = "x",
        .type = CONFIG_OPTION_BOOL,
        .data = SConfigOptionDescription::SBoolData{true},
    },
    """
    options = parse_header(src)
    assert len(options) == 1
    assert options[0].key == "test:opt"
    assert options[0].type == "bool"
    assert options[0].default is True


def test_format_autodetect_new() -> None:
    """parse_header dispatches to the new-format parser when MS<...>(...) is present."""
    src = 'MS<Bool>("test:opt", "x", true),'
    options = parse_header(src)
    assert len(options) == 1
    assert options[0].key == "test:opt"
    assert options[0].type == "bool"
    assert options[0].default is True
