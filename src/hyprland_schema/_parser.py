"""Low-level parser for Hyprland ConfigDescriptions.hpp.

Extracts structured option data from the C++ header using regex parsing.
No C++ compiler needed. Pure stdlib.
"""

import re
import warnings
from collections.abc import Callable
from typing import Any

from hyprland_schema._model import HyprOption

# GitHub URL for fetching raw ConfigDescriptions.hpp content.
RAW_URL_TEMPLATE = (
    "https://raw.githubusercontent.com/hyprwm/Hyprland/{version}/src/config/ConfigDescriptions.hpp"
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
    value_re: re.Pattern[str],
    min_re: re.Pattern[str],
    max_re: re.Pattern[str],
) -> dict[str, Any]:
    """Shared parser for SRangeData (int) and SFloatData (float)."""
    raw = raw.strip()
    if ".value" in raw or ".min" in raw or ".max" in raw:
        val_m = value_re.search(raw)
        min_m = min_re.search(raw)
        max_m = max_re.search(raw)
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
    return _parse_numeric_data(
        raw, _parse_int_literal, 0, _NAMED_VALUE_RE, _NAMED_MIN_RE, _NAMED_MAX_RE
    )


def _parse_float_data(raw: str) -> dict[str, Any]:
    return _parse_numeric_data(
        raw,
        _parse_float_literal,
        0.0,
        _NAMED_VALUE_RE,
        _NAMED_MIN_RE,
        _NAMED_MAX_RE,
    )


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
    """Fetch ConfigDescriptions.hpp content from GitHub for the given version tag."""
    from urllib.request import urlopen

    url = RAW_URL_TEMPLATE.format(version=version)
    with urlopen(url, timeout=30) as resp:
        return resp.read().decode("utf-8")


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


def parse_header(content: str) -> list[HyprOption]:
    """Parse ConfigDescriptions.hpp content into a list of HyprOption."""
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
