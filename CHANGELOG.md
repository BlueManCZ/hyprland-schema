# Changelog

All notable changes to hyprland-schema will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.6.1] - 2026-05-16

### Changed

- **Hyprland v0.55.2 schema** — `cursor:no_hardware_cursors` default flipped from `Disabled` (0) to `Auto` (2), letting Hyprland decide per-GPU whether to use hardware cursors

## [0.6.0] - 2026-05-15

### Added

- **Hyprland v0.55.1 schema** — patch release with no upstream option changes; the `v0.55.1 → v0.55.0` migration is a no-op
- **`HyprOption.validate(value)`** — checks a value against the option's schema constraints, returning an error message or `None`; numeric and `choice` types are bounds-checked against `min`/`max`, and `enum_values` (when present) restricts the stringified value to the listed choices

## [0.5.0] - 2026-05-11

### Added

- **Hyprland v0.55.0 schema** — 341 options across 20 sections; new entries include the glow decoration (`decoration:glow:*`), `group:groupbar:middle_click_close`, and `debug:vfr` (moved from `misc:vfr`)
- **New-format parser** — handles `ConfigValues.cpp` introduced in [hyprwm/Hyprland#13817](https://github.com/hyprwm/Hyprland/pull/13817) and used by Hyprland v0.55.0+; `fetch_header()` auto-detects and falls back to the legacy `ConfigDescriptions.hpp` for older tags
- **New type aliases** — `cssgap` (for CSS-style gap options like `general:gaps_in`) and `font_weight`; surfaced as distinct option types so GUI consumers can render specialised widgets
- **`source_url(version)`** — version-aware helper returning the canonical upstream source URL for a Hyprland tag (`ConfigValues.cpp` for v0.55.0+, `ConfigDescriptions.hpp` otherwise); `Schema.to_dict()["source"]` now picks the right file

### Changed

- **Bracket sentinel defaults** — string defaults like `"[[EMPTY]]"` and `"[[Auto]]"` in `ConfigValues.cpp` collapse to `""`, matching how the legacy `STRVAL_EMPTY` was always handled, so consumers don't render the sentinel literal in UI inputs
- **`fetch_header()` return type** — now returns `(content, url)` so callers can report or store the URL that actually served the response
- **`bump` workflow** — after auto-creating a mid-chain snapshot, adjacent migrations whose `to_version` is a snapshot are pruned, since they're never traversed at runtime

### Removed

- **`SOURCE_URL_TEMPLATE`** — replaced by the version-aware `source_url(version)` function. The old constant always pointed at the legacy `ConfigDescriptions.hpp` URL, which 404s for v0.55.0+.

## [0.4.0] - 2026-03-27

### Added

- **Hyprland v0.54.3 schema**
- **`v0.54.3 → v0.54.2` migration**

### Fixed

- **`apply_migration`** handles remove-then-add of the same key without spurious errors

## [0.3.0] - 2026-03-26

### Changed

- **`ConfigDescriptions.hpp` path** — followed Hyprland's move of the file from `src/config/` to `src/config/supplementary/` (hyprwm/Hyprland@8726a736); fetch and source URL templates updated, legacy fallback preserved so older Hyprland tags still resolve

## [0.2.0] - 2026-03-24

### Added

- **`MigrationError`** is now exported from the public API for downstream error handling

### Changed

- **`apply_migration`** copies input option dicts instead of mutating them in place
- Internal refactor — `_REQUIRED_FIELDS` derived once at module level, redundant regex parameters dropped, set operations simplified

## [0.1.0] - 2026-03-21

Initial release — typed Python schema for every Hyprland configuration option.

### Added

- **Option schema** — defaults, ranges, descriptions, choice enums for every Hyprland config option
- **Multi-version `load(version)` API** — load schemas for older Hyprland tags; resolution walks the reverse-migration chain, then disk cache (`~/.cache/hyprland-schema/`), then fetches from GitHub
- **`Schema` dataclass** — frozen, indexable by key, filterable by section/subsection, exportable as JSON
- **Generated from upstream `ConfigDescriptions.hpp`** — no C++ compiler needed; stdlib-only at runtime
- **CLI** — `generate_schema.py` with `generate`, `bump`, `snapshot`, and `update-registry` subcommands

[0.6.1]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.6.1
[0.6.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.6.0
[0.5.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.5.0
[0.4.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.4.0
[0.3.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.3.0
[0.2.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.2.0
[0.1.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.1.0
