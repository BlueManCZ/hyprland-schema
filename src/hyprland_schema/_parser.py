"""Low-level parser for Hyprland config option metadata.

Supports two upstream formats:

- **Legacy** (`src/config/ConfigDescriptions.hpp`, used through v0.54.x):
  ``SConfigOptionDescription{.value=..., .type=..., .data=...}`` records.
- **New** (`src/config/values/ConfigValues.cpp`, on `main` since hyprwm/Hyprland#13817):
  ``MS<Type>("name", "description", default, {.min=..., .max=..., .map=...})`` calls.

`parse_header` auto-detects the format from the content, and `fetch_header`
tries the new-format URL first, falling back to the legacy URL for older tags.
No C++ compiler needed. Pure stdlib.
"""

import re
import warnings
from collections.abc import Callable
from typing import Any

from hyprland_schema._model import HyprOption

# GitHub URL for fetching raw ConfigDescriptions.hpp content (legacy format,
# used by every released version through v0.54.x).
RAW_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/hyprwm/Hyprland/{version}/src/config/ConfigDescriptions.hpp"
)
# New-format URL — single source of truth on `main` since hyprwm/Hyprland#13817.
RAW_URL_TEMPLATE_NEW = (
    "https://raw.githubusercontent.com/hyprwm/Hyprland/{version}/src/config/values/ConfigValues.cpp"
)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_VALUE_RE = re.compile(r'\.value\s*=\s*"([^"]+)"')
_TYPE_RE = re.compile(r"\.type\s*=\s*(CONFIG_OPTION_\w+)")
_DESC_RE = re.compile(r'\.description\s*=\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', re.DOTALL)
_DATA_RE = re.compile(
    r"\.data\s*=\s*SConfigOptionDescription::(\w+)\{(.*)\}",
    re.DOTALL,
)
_QUOTED_STR_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
_HEX_COLOR_RE = re.compile(r"(0x[0-9a-fA-F]+)")

# Named-initializer patterns for numeric data (int / float).
# The float pattern also matches integer literals, so one set covers both types.
_NAMED_VALUE_RE = re.compile(r"\.value\s*=\s*(-?[\w.]+f?)")
_NAMED_MIN_RE = re.compile(r"\.min\s*=\s*(-?[\w.]+f?)")
_NAMED_MAX_RE = re.compile(r"\.max\s*=\s*(-?[\w.]+f?)")

# Vector inner-brace pattern.
_INNER_BRACE_RE = re.compile(r"\{([^{}]*)\}")

# Choice data patterns (named initializer style).
_CHOICE_FIRST_INDEX_RE = re.compile(r"\.firstIndex\s*=\s*(\d+)")
_CHOICE_CHOICES_RE = re.compile(r'\.choices\s*=\s*"([^"]*)"')
# Choice data patterns (positional style).
_CHOICE_POS_INDEX_RE = re.compile(r"^\s*(\d+)\s*,")


# ---------------------------------------------------------------------------
# Literal parsers
# ---------------------------------------------------------------------------


def _parse_int_literal(s: str) -> int:
    s = s.strip()
    if s == "INT_MAX":
        return 2147483647
    return int(s)


def _parse_float_literal(s: str) -> float:
    s = s.strip().rstrip("f")
    return float(s)


# ---------------------------------------------------------------------------
# Per-type data parsers
# ---------------------------------------------------------------------------


def _parse_bool_data(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if not raw:
        return {"default": False}
    return {"default": raw.lower() == "true"}


def _parse_numeric_data(
    raw: str,
    parse_literal: Callable[[str], int | float],
    fallback: int | float,
) -> dict[str, Any]:
    """Shared parser for SRangeData (int) and SFloatData (float)."""
    raw = raw.strip()
    if ".value" in raw or ".min" in raw or ".max" in raw:
        val_m = _NAMED_VALUE_RE.search(raw)
        min_m = _NAMED_MIN_RE.search(raw)
        max_m = _NAMED_MAX_RE.search(raw)
        return {
            "default": parse_literal(val_m.group(1) if val_m else "0"),
            "min": parse_literal(min_m.group(1) if min_m else "0"),
            "max": parse_literal(max_m.group(1) if max_m else "0"),
        }
    parts = [p.strip() for p in raw.split(",")]
    return {
        "default": parse_literal(parts[0]) if parts and parts[0] else fallback,
        "min": parse_literal(parts[1]) if len(parts) > 1 else fallback,
        "max": parse_literal(parts[2]) if len(parts) > 2 else fallback,
    }


def _parse_range_data(raw: str) -> dict[str, Any]:
    return _parse_numeric_data(raw, _parse_int_literal, 0)


def _parse_float_data(raw: str) -> dict[str, Any]:
    return _parse_numeric_data(raw, _parse_float_literal, 0.0)


def _parse_string_data(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if "STRVAL_EMPTY" in raw:
        return {"default": ""}
    m = _QUOTED_STR_RE.search(raw)
    return {"default": m.group(1) if m else ""}


def _parse_color_data(raw: str) -> dict[str, Any]:
    raw = raw.strip()
    if not raw:
        return {"default": None}
    m = _HEX_COLOR_RE.search(raw)
    if m:
        val = int(m.group(1), 16)
        return {"default": f"0x{val:08x}"}
    return {"default": None}


def _parse_gradient_data(raw: str) -> dict[str, Any]:
    m = _QUOTED_STR_RE.search(raw)
    return {"default": m.group(1) if m else ""}


def _parse_vector_data(raw: str) -> dict[str, Any]:
    inner = _INNER_BRACE_RE.findall(raw)
    pairs: list[tuple[float, ...]] = []
    for content in inner:
        content = content.strip()
        if not content:
            pairs.append((0.0, 0.0))
        else:
            vals = tuple(_parse_float_literal(v) for v in content.split(","))
            pairs.append(vals if len(vals) == 2 else (0.0, 0.0))
    while len(pairs) < 3:
        pairs.append((0.0, 0.0))
    return {
        "default": pairs[0],
        "default_min": pairs[1],
        "default_max": pairs[2],
    }


def _parse_choice_data(raw: str) -> dict[str, Any]:
    if ".firstIndex" in raw or ".choices" in raw:
        idx_m = _CHOICE_FIRST_INDEX_RE.search(raw)
        choices_m = _CHOICE_CHOICES_RE.search(raw)
    else:
        idx_m = _CHOICE_POS_INDEX_RE.search(raw)
        choices_m = _QUOTED_STR_RE.search(raw)
    choice_list = tuple(c.strip() for c in choices_m.group(1).split(",")) if choices_m else ()
    default_idx = int(idx_m.group(1)) if idx_m else 0
    default_str = choice_list[default_idx] if default_idx < len(choice_list) else None
    return {"default": default_idx, "default_str": default_str, "enum_values": choice_list}


# ---------------------------------------------------------------------------
# Type dispatch
# ---------------------------------------------------------------------------

# Parser function: takes raw data string, returns dict of parsed fields.
type _DataParser = Callable[[str], dict[str, Any]]

_TYPE_MAP: dict[str, tuple[str, _DataParser]] = {
    "CONFIG_OPTION_BOOL": ("bool", _parse_bool_data),
    "CONFIG_OPTION_INT": ("int", _parse_range_data),
    "CONFIG_OPTION_FLOAT": ("float", _parse_float_data),
    "CONFIG_OPTION_STRING_SHORT": ("string", _parse_string_data),
    "CONFIG_OPTION_STRING_LONG": ("string", _parse_string_data),
    "CONFIG_OPTION_COLOR": ("color", _parse_color_data),
    "CONFIG_OPTION_GRADIENT": ("gradient", _parse_gradient_data),
    "CONFIG_OPTION_VECTOR": ("vec2", _parse_vector_data),
    "CONFIG_OPTION_CHOICE": ("choice", _parse_choice_data),
}

_DATA_STRUCT_MAP: dict[str, tuple[str, _DataParser]] = {
    "SRangeData": ("int", _parse_range_data),
    "SFloatData": ("float", _parse_float_data),
    "SBoolData": ("bool", _parse_bool_data),
    "SStringData": ("string", _parse_string_data),
    "SColorData": ("color", _parse_color_data),
    "SGradientData": ("gradient", _parse_gradient_data),
    "SVectorData": ("vec2", _parse_vector_data),
    "SChoiceData": ("choice", _parse_choice_data),
}


def _resolve_type(type_const: str, data_struct: str, key: str) -> tuple[str, _DataParser] | None:
    from_type = _TYPE_MAP.get(type_const)
    from_data = _DATA_STRUCT_MAP.get(data_struct)
    if from_type and from_data and from_type[0] != from_data[0]:
        warnings.warn(
            f"type/data conflict for '{key}': {type_const} vs {data_struct} — trusting data struct",
            stacklevel=2,
        )
        return from_data
    return from_data or from_type


# ---------------------------------------------------------------------------
# Description cleanup
# ---------------------------------------------------------------------------


def _parse_description(raw: str) -> str:
    parts = _QUOTED_STR_RE.findall(raw)
    text = "".join(parts)
    text = text.replace("\\n", "\n").replace("\\t", "\t")
    return text.strip()


# ---------------------------------------------------------------------------
# Fetch header from GitHub
# ---------------------------------------------------------------------------


def fetch_header(version: str) -> str:
    """Fetch the C++ option-metadata source from GitHub for the given version tag.

    Tries the new-format URL (`src/config/values/ConfigValues.cpp`) first and
    falls back to the legacy URL (`src/config/ConfigDescriptions.hpp`) on 404.
    Returns the raw text; pass it to ``parse_header`` to extract options.
    """
    from urllib.error import HTTPError
    from urllib.request import urlopen

    url = RAW_URL_TEMPLATE_NEW.format(version=version)
    try:
        with urlopen(url, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except HTTPError as exc:
        if exc.code != 404:
            raise
    # Fall back to legacy path for older tags.
    url = RAW_URL_TEMPLATE.format(version=version)
    with urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


# ---------------------------------------------------------------------------
# Main parser — dispatches to legacy or new format based on content
# ---------------------------------------------------------------------------


def parse_header(content: str) -> list[HyprOption]:
    """Parse C++ option-metadata source into a list of HyprOption.

    Auto-detects between the legacy `ConfigDescriptions.hpp` format and the
    new `ConfigValues.cpp` format. Returns ``[]`` if neither marker is found
    (e.g. empty content or unrelated source).
    """
    if "SConfigOptionDescription{" in content:
        return _parse_legacy_format(content)
    if _MS_OPEN_RE.search(content):
        return _parse_new_format(content)
    return []


# ---------------------------------------------------------------------------
# Legacy format parser (ConfigDescriptions.hpp, v0.54.x and older)
# ---------------------------------------------------------------------------


def _parse_legacy_format(content: str) -> list[HyprOption]:
    """Parse the legacy ConfigDescriptions.hpp format."""
    options: list[HyprOption] = []

    blocks = content.split("SConfigOptionDescription{")
    for block in blocks[1:]:
        brace_depth = 1
        end = 0
        for i, ch in enumerate(block):
            if ch == "{":
                brace_depth += 1
            elif ch == "}":
                brace_depth -= 1
                if brace_depth == 0:
                    end = i
                    break
        entry = block[:end]

        value_m = _VALUE_RE.search(entry)
        type_m = _TYPE_RE.search(entry)
        desc_m = _DESC_RE.search(entry)
        data_m = _DATA_RE.search(entry)

        if not value_m or not type_m:
            continue

        key = value_m.group(1)
        type_const = type_m.group(1)
        description = _parse_description(desc_m.group(1)) if desc_m else ""

        if not data_m:
            warnings.warn(f"no .data for '{key}', skipping", stacklevel=2)
            continue

        data_struct = data_m.group(1)
        data_raw = data_m.group(2)

        resolved = _resolve_type(type_const, data_struct, key)
        if resolved is None:
            warnings.warn(
                f"unknown type {type_const}/{data_struct} for '{key}', skipping",
                stacklevel=2,
            )
            continue

        opt_type, parser = resolved
        data = parser(data_raw)

        key_parts = key.split(":")
        section = key_parts[:-1]
        name = key_parts[-1]

        options.append(
            HyprOption(
                key=key,
                section=tuple(section),
                name=name,
                description=description,
                type=opt_type,
                default=data.get("default"),
                min=data.get("min"),
                max=data.get("max"),
                enum_values=data.get("enum_values"),
                default_str=data.get("default_str"),
                default_min=data.get("default_min"),
                default_max=data.get("default_max"),
            )
        )

    return options


# ---------------------------------------------------------------------------
# New format parser (ConfigValues.cpp, hyprwm/Hyprland#13817 and later)
#
# Each option is one MS<Type>("name", "description", default, {options}) call.
# Types: Bool, Int, Float, String, Color, Gradient, Vec2, CssGap, FontWeight.
# The options block is optional; FontWeight may also omit the default arg.
# .map = OptionMap{{"name", value}, ...} promotes Int to "choice".
# .min, .max, .map feed the schema; .validator and .refresh are ignored.
# ---------------------------------------------------------------------------

# Opens an MS<Type>(...) call. Anchored on word-boundary so we don't match
# inside identifiers (e.g. someClassName::MS<Foo>).
_MS_OPEN_RE = re.compile(r"\bMS<([A-Za-z0-9_]+)>\s*\(")

# Match an OptionMap entry pair: { "name", value }.
_OPTION_MAP_ENTRY_RE = re.compile(r'\{\s*"((?:[^"\\]|\\.)*)"\s*,\s*(-?\d+)\s*\}')

# Find a hex color literal anywhere in an arg.
_HEX_COLOR_VAL_RE = re.compile(r"0x([0-9a-fA-F]+)")

# Body of Config::VEC2{...}.
_VEC2_BODY_RE = re.compile(r"Config::VEC2\s*\{\s*([^}]*)\s*\}")

# New-format type alias -> internal type name. "int" may be promoted to
# "choice" later if a .map is present.
_NEW_TYPE_MAP: dict[str, str] = {
    "Bool": "bool",
    "Int": "int",
    "Float": "float",
    "String": "string",
    "Color": "color",
    "Gradient": "gradient",
    "Vec2": "vec2",
    "CssGap": "cssgap",
    "FontWeight": "font_weight",
}


def _split_top_level_commas(s: str) -> list[str]:
    """Split a comma-separated argument list at depth 0, respecting strings."""
    args: list[str] = []
    depth = 0
    in_str = False
    escape = False
    start = 0
    for i, ch in enumerate(s):
        if escape:
            escape = False
            continue
        if in_str:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "([{<":
            depth += 1
        elif ch in ")]}>":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(s[start:i])
            start = i + 1
    tail = s[start:]
    if tail.strip():
        args.append(tail)
    return [a.strip() for a in args]


def _find_matching(s: str, start: int, open_ch: str, close_ch: str) -> int:
    """Return the index of the close character matching ``s[start]``.

    Respects nested ``open_ch``/``close_ch`` pairs and skips characters inside
    double-quoted strings (so a paren inside a description doesn't confuse us).
    """
    depth = 1
    in_str = False
    escape = False
    i = start + 1
    while i < len(s):
        ch = s[i]
        if escape:
            escape = False
        elif in_str:
            if ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _parse_new_int_literal(s: str) -> int:
    """Parse an integer literal, handling INT_MAX / numeric_limits / hex / signed."""
    s = s.strip()
    if s.startswith("-") and ("INT_MAX" in s or "numeric_limits" in s):
        return -2147483648
    if "INT_MAX" in s or "numeric_limits" in s:
        return 2147483647
    if s.lower().startswith("0x") or s.lower().startswith("-0x"):
        return int(s, 16)
    return int(s)


def _parse_new_float_literal(s: str) -> float:
    s = s.strip().rstrip("fF")
    return float(s)


def _parse_new_default(arg: str, type_name: str) -> Any:
    """Parse the third positional arg (default value) by type."""
    arg = arg.strip()

    if type_name == "bool":
        return arg.lower() == "true"

    if type_name in ("int", "cssgap", "font_weight"):
        try:
            return _parse_new_int_literal(arg)
        except ValueError:
            return 0

    if type_name == "float":
        try:
            return _parse_new_float_literal(arg)
        except ValueError:
            return 0.0

    if type_name == "string":
        if "STRVAL_EMPTY" in arg:
            return ""
        m = _QUOTED_STR_RE.search(arg)
        if not m:
            return ""
        # Concatenate adjacent literals (C++ joins them at compile time).
        parts = _QUOTED_STR_RE.findall(arg)
        text = "".join(parts).replace("\\n", "\n").replace("\\t", "\t")
        return text

    if type_name == "color":
        m = _HEX_COLOR_VAL_RE.search(arg)
        if m:
            val = int(m.group(1), 16)
            return f"0x{val:08x}"
        # Negative sentinel (e.g. -1 means "fall back to another color").
        try:
            return _parse_new_int_literal(arg)
        except ValueError:
            return None

    if type_name == "gradient":
        m = _HEX_COLOR_VAL_RE.search(arg)
        if m:
            val = int(m.group(1), 16)
            return f"0x{val:08x}"
        return ""

    if type_name == "vec2":
        m = _VEC2_BODY_RE.search(arg)
        if not m:
            return (0.0, 0.0)
        body = m.group(1).strip()
        if not body:
            return (0.0, 0.0)
        try:
            parts = [_parse_new_float_literal(p) for p in body.split(",") if p.strip()]
        except ValueError:
            return (0.0, 0.0)
        if len(parts) == 2:
            return (parts[0], parts[1])
        return (0.0, 0.0)

    return None


def _parse_new_options_block(block: str) -> dict[str, Any]:
    """Extract .min, .max, .map from the options-struct designator block."""
    out: dict[str, Any] = {}

    # .min / .max — value runs until the next top-level comma or end-of-block.
    # Use a permissive pattern: capture everything up to the next ".\w" or end.
    for field in ("min", "max"):
        m = re.search(rf"\.{field}\s*=\s*([^,}}]+(?:\([^)]*\))?[^,}}]*)", block)
        if m:
            raw = m.group(1).strip()
            # Try int first, then float.
            try:
                out[field] = _parse_new_int_literal(raw)
            except ValueError:
                try:
                    out[field] = _parse_new_float_literal(raw)
                except ValueError:
                    pass

    # .map = OptionMap{{"name", value}, ...}
    map_idx = block.find(".map")
    if map_idx >= 0:
        # Find the OptionMap opening brace and balance to extract its body.
        om_open = block.find("{", block.find("OptionMap", map_idx))
        if om_open >= 0:
            om_close = _find_matching(block, om_open, "{", "}")
            if om_close > 0:
                pairs = _OPTION_MAP_ENTRY_RE.findall(block[om_open:om_close])
                # Sort by int value (all maps in upstream are 0..N consecutive,
                # but sort defensively in case a non-sequential one is added).
                ordered = sorted(((int(v), n) for n, v in pairs), key=lambda x: x[0])
                names = tuple(n for _, n in ordered)
                values = tuple(v for v, _ in ordered)
                out["map_names"] = names
                out["map_values"] = values

    return out


def _parse_new_format(content: str) -> list[HyprOption]:
    """Parse ConfigValues.cpp into a list of HyprOption."""
    options: list[HyprOption] = []

    for m in _MS_OPEN_RE.finditer(content):
        type_alias = m.group(1)
        if type_alias not in _NEW_TYPE_MAP:
            # Unknown template type — skip silently; future Hyprland may add types.
            continue

        # Find the matching ')' for the MS<...>( opener.
        open_paren = m.end() - 1
        close_paren = _find_matching(content, open_paren, "(", ")")
        if close_paren < 0:
            warnings.warn(f"unbalanced MS<{type_alias}>(...) at offset {m.start()}", stacklevel=2)
            continue

        body = content[open_paren + 1 : close_paren]
        args = _split_top_level_commas(body)
        if len(args) < 2:
            continue  # need at least name + description

        # Arg 0: name (quoted string)
        name_m = _QUOTED_STR_RE.search(args[0])
        if not name_m:
            continue
        key = name_m.group(1)

        # Arg 1: description (one or more quoted strings, possibly multi-line)
        description = _parse_description(args[1])

        # Arg 2: default value (optional for FontWeight)
        type_name = _NEW_TYPE_MAP[type_alias]
        default: Any = None
        if len(args) >= 3:
            default = _parse_new_default(args[2], type_name)
        elif type_name == "font_weight":
            # No default arg — leave as None (matches the C++ default-constructed value).
            default = None
        else:
            warnings.warn(f"missing default for '{key}', skipping", stacklevel=2)
            continue

        # Arg 3 (optional): {.min=…, .max=…, .map=…, .validator=…, .refresh=…}
        opts: dict[str, Any] = {}
        if len(args) >= 4:
            opts_arg = args[3].strip()
            if opts_arg.startswith("{") and opts_arg.endswith("}"):
                opts = _parse_new_options_block(opts_arg[1:-1])

        # Promote Int -> choice when an OptionMap is present.
        opt_min = opts.get("min")
        opt_max = opts.get("max")
        enum_values: tuple[str, ...] | None = None
        default_str: str | None = None

        if "map_names" in opts and type_name == "int":
            type_name = "choice"
            map_names: tuple[str, ...] = opts["map_names"]
            map_values: tuple[int, ...] = opts["map_values"]
            enum_values = map_names
            # default is the raw int; resolve its name via the value map.
            if isinstance(default, int) and default in map_values:
                default_str = map_names[map_values.index(default)]
            # Drop min/max for choice — legacy schema doesn't carry them.
            opt_min = None
            opt_max = None

        key_parts = key.split(":")
        section = tuple(key_parts[:-1])
        opt_name = key_parts[-1]

        options.append(
            HyprOption(
                key=key,
                section=section,
                name=opt_name,
                description=description,
                type=type_name,
                default=default,
                min=opt_min,
                max=opt_max,
                enum_values=enum_values,
                default_str=default_str,
            )
        )

    return options
