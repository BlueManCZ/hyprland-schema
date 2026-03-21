# hyprland-schema

Typed Python schema for every Hyprland configuration option — with defaults,
ranges, and descriptions. Generated from Hyprland's
[ConfigDescriptions.hpp](https://github.com/hyprwm/Hyprland/blob/main/src/config/ConfigDescriptions.hpp).
Zero runtime dependencies — stdlib only.

## Installation

```
pip install hyprland-schema
```

## Usage

```python
import hyprland_schema

# Schema version
print(hyprland_schema.HYPRLAND_VERSION)  # "v0.54.2"

# Lookup by key
border = hyprland_schema.OPTIONS_BY_KEY["general:border_size"]
print(border.type, border.default, border.min, border.max)
# int 1 0 20

# Filter by section
for opt in hyprland_schema.get_section("general"):
    print(f"{opt.name}: {opt.type} = {opt.default}")

# Filter by subsection
for opt in hyprland_schema.get_subsection("decoration", "blur"):
    print(f"{opt.name}: {opt.type} = {opt.default}")

# Iterate all options
for opt in hyprland_schema.OPTIONS:
    print(f"{opt.key}: {opt.type}")

# Export as JSON
json_str = hyprland_schema.get_json()
```

### Loading older Hyprland versions

```python
import hyprland_schema

# List all bundled versions (newest first)
print(hyprland_schema.available_versions())

# Load schema for a specific version
schema = hyprland_schema.load("v0.54.2")
print(schema.version, len(schema.options))

# Schema objects have the same filtering API
for opt in schema.get_section("general"):
    print(f"{opt.name}: {opt.type} = {opt.default}")

# Lookup on a Schema
border = schema.options_by_key["general:border_size"]
```

Resolution order for `load()`:

1. **Latest bundled version** — instant (pre-parsed).
2. **Older bundled version** — reconstructed via reverse migrations.
3. **Disk cache** at `~/.cache/hyprland-schema/` — no network needed.
4. **GitHub fetch** — downloads `ConfigDescriptions.hpp` and parses it.

## API

| Symbol                   | Type / Signature                 | Description                                 |
|--------------------------|----------------------------------|---------------------------------------------|
| `HYPRLAND_VERSION`       | `str`                            | Hyprland tag the schema was built from      |
| `OPTIONS`                | `tuple[HyprOption, ...]`         | All configuration options                   |
| `OPTIONS_BY_KEY`         | `dict[str, HyprOption]`          | Lookup by dotted key                        |
| `get_section(s)`         | `(str) -> list[HyprOption]`      | Options in a top-level section              |
| `get_subsection(s, sub)` | `(str, str) -> list[HyprOption]` | Options in a nested subsection              |
| `get_json()`             | `(*, indent=2) -> str`           | Full schema as a JSON string                |
| `load(version)`          | `(str) -> Schema`                | Load schema for a specific Hyprland version |
| `available_versions()`   | `() -> list[str]`                | All bundled versions, newest first          |

### Schema

`Schema` is a frozen dataclass returned by `load()`. It holds options for a
specific Hyprland version.

| Attribute / Method       | Type / Signature                 | Description                    |
|--------------------------|----------------------------------|--------------------------------|
| `version`                | `str`                            | Hyprland version tag           |
| `options`                | `tuple[HyprOption, ...]`         | All options for this version   |
| `options_by_key`         | `dict[str, HyprOption]`          | Lookup by dotted key           |
| `get_section(s)`         | `(str) -> list[HyprOption]`      | Options in a top-level section |
| `get_subsection(s, sub)` | `(str, str) -> list[HyprOption]` | Options in a nested subsection |
| `get_json()`             | `(*, indent=2) -> str`           | Schema as a JSON string        |

## HyprOption fields

| Field         | Type                        | Description                                                             |
|---------------|-----------------------------|-------------------------------------------------------------------------|
| `key`         | `str`                       | `"general:border_size"`                                                 |
| `section`     | `tuple[str, ...]`           | `("general",)`                                                          |
| `name`        | `str`                       | `"border_size"`                                                         |
| `description` | `str`                       | Human-readable text                                                     |
| `type`        | `str`                       | `bool`, `int`, `float`, `string`, `color`, `gradient`, `vec2`, `choice` |
| `default`     | `Any`                       | Default value                                                           |
| `min`         | `int \| float \| None`      | For `int`/`float` types                                                 |
| `max`         | `int \| float \| None`      | For `int`/`float` types                                                 |
| `enum_values` | `tuple[str, ...] \| None`   | For `choice` type                                                       |
| `default_str` | `str \| None`               | Human-readable default for `choice` type                                |
| `default_min` | `tuple[float, ...] \| None` | For `vec2` type                                                         |
| `default_max` | `tuple[float, ...] \| None` | For `vec2` type                                                         |



## Requirements

- Python >= 3.12

## License

MIT
