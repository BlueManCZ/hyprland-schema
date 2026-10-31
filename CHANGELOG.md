# Changelog

All notable changes to hyprland-schema will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] - 2026-10-31

### Added

- **Hyprland v0.57.0 schema** — 407 options across 22 sections; 55 added, 1 removed, 16 changed
  - Added: `decoration:blur:variant`, `decoration:blur:proportional`, `decoration:blur:glass:refraction`, `decoration:blur:glass:size`, `decoration:blur:glass:roughness`, `decoration:blur:acrylic:refraction`, `decoration:blur:acrylic:bulb`, `decoration:blur:acrylic:clarity`, `decoration:blur:acrylic:aberration`, `decoration:blur:acrylic:tint`, `decoration:blur:drops:speed`, `decoration:blur:heat_shimmer:speed`, `decoration:blur:aurora:speed`, `decoration:blur:aurora:intensity`, `decoration:blur:aurora:color1`, `decoration:blur:aurora:color2`, `decoration:blur:haze:intensity`, `decoration:blur:haze:iridescence`, `decoration:blur:ripple:strength`, `decoration:blur:ripple:radius`, `decoration:blur:ripple:width`, `decoration:blur:ripple:duration`, `decoration:blur:water:strength`, `decoration:blur:water:radius`, `decoration:blur:water:speed`, `decoration:blur:water:damping`, `decoration:blur:water:duration`, `decoration:blur:fluid_jar:color`, `decoration:blur:fluid_jar:speed`, `decoration:blur:fluid_jar:fill_amount`, `decoration:blur:fluid_jar:mass`, `decoration:blur:fluid_jar:precision`, `decoration:blur:fluid_jar:turbulence`, `decoration:blur:fluid_jar:distortion`, `decoration:wobble:enabled`, `decoration:wobble:mesh`, `decoration:wobble:stiffness`, `decoration:wobble:damping`, `decoration:wobble:mass`, `decoration:wobble:intensity`, `decoration:wobble:value_epsilon`, `decoration:wobble:velocity_epsilon`, `input:swallow_focus_click`, `input:tablet:enabled`, `misc:bell_sound`, `misc:new_float_force_onscreen`, `misc:float_force_onscreen`, `layers:allow_new_top_layers_over_existing_fullscreen`, `layers:layers_hog_keyboard_focus`, `binds:client_requested_fs_uses_layout_handler`, `binds:drag_center_window`, `render:async_commit`, `render:not_shown_fifo_lock`, `cursor:warp_on_monitor_change`, `debug:invalidate_buffers`
  - Removed: `debug:fifo_pending_workaround`
  - `decoration:rounding`: max `20` → `100`
  - `decoration:rounding_power`: min `2` → `1`
  - `decoration:shadow:scale`: min `0` → `0.05`; max `1` → `2`
  - `decoration:blur:enabled`: description updated
  - `input:scroll_factor`: max `2` → `100`
  - `input:touchpad:scroll_factor`: max `2` → `100`
  - `group:drag_into_group`: enum_values `["disabled", "enabled", "only when dragging into the groupbar"]` → `["disabled", "enabled", "only_into_groupbar"]`
  - `group:groupbar:indicator_height`: min `1` → `0`
  - `group:groupbar:rounding`: max `20` → `40`
  - `group:groupbar:rounding_power`: min `2` → `1`
  - `group:groupbar:gradient_rounding`: max `20` → `40`
  - `group:groupbar:gradient_rounding_power`: min `2` → `1`
  - `misc:exit_window_retains_fullscreen`: type `"bool"` → `"choice"`; enum_values `["disable", "enable", "only_when_grouped", "only_when_nongrouped"]` added; default_str `"disable"` added; description updated
  - `binds:workspace_back_and_forth`: type `"bool"` → `"choice"`; enum_values `["disabled", "all_monitors", "per_monitor"]` added; default_str `"disabled"` added; description updated
  - `scrolling:follow_focus`: type `"bool"` → `"int"`; description updated
  - `quirks:skip_non_kms_dmabuf_formats`: default `false` → `true`

## [0.7.2] - 2026-10-19

### Changed

- **Hyprland v0.56.2 schema** — 353 options across 21 sections; no upstream option changes; the `v0.56.2 → v0.56.1` migration is a no-op

## [0.7.1] - 2026-07-31

### Fixed

- **`choice` options now validate against their names *and* their indices.** `validate()` ran the numeric bounds check and the enum-name check on every choice value, so both forms Hyprland accepts were rejected: the integer Hyprland actually stores (`general:resize_corner` = `2`) failed the name check, and the name (`"top_right"`) failed the numeric check. Choices are now checked as name-or-index, where the index is the value's position in `enum_values`. https://github.com/BlueManCZ/hyprland-state/issues/4
- **`load()` accepts the version with or without the `v` prefix.** Bundled versions, snapshot filenames and the GitHub fetch URL are all keyed on the git tag (`v0.55.4`), but `hyprctl` reports the bare number (`0.55.4`), so callers passing it through — as hyprland-state does — missed every bundled version, spent a doomed network round-trip on a tag that does not exist, and ended up on whatever the caller's fallback was. Both spellings now resolve to the same schema, and `Schema.version` always reports the tag spelling.

## [0.7.0] - 2026-07-28

### Added

- **Hyprland v0.56.1 schema** — patch release with no upstream option changes; the `v0.56.1 → v0.56.0` migration is a no-op
- **Hyprland v0.56.0 schema** — 353 options across 21 sections; new `input-capture` section (`capture_modifiers`, `enforce_barriers`), motion blur (`decoration:motion_blur:*`), tablet tool eraser and pressure range controls (`input:tablettool:*`), `group:groupbar:disable_when_only`, `misc:session_lock_blur`, `misc:initial_workspace_token_timeout`, and `master:focus_master_on_close`

### Changed

- **Shadow and glow colors are now gradients** — `decoration:shadow:color`, `decoration:shadow:color_inactive`, `decoration:glow:color`, and `decoration:glow:color_inactive` changed type from `color` to `gradient` upstream, and the two `color_inactive` options now default to empty
- **`experimental:wp_cm_1_2`** default flipped from `false` to `true`
- **`general:layout`** accepts `scrolling`, `monocle`, and `lua:<name>` in addition to `dwindle` and `master`
- **Int options may be open-ended** — upstream can declare an int with only a lower bound (`input:tablettool:eraser_button_override`), so `max` is no longer guaranteed to be set; `validate()` already treated a missing bound as unbounded

## [0.6.3] - 2026-06-12

### Changed

- **Hyprland v0.55.4 schema** — patch release with no upstream option changes; the `v0.55.4 → v0.55.3` migration is a no-op

## [0.6.2] - 2026-06-08

### Changed

- **Hyprland v0.55.3 schema** — patch release with no upstream option changes; the `v0.55.3 → v0.55.2` migration is a no-op

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

[0.8.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.8.0
[0.7.2]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.7.2
[0.7.1]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.7.1
[0.7.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.7.0
[0.6.3]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.6.3
[0.6.2]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.6.2
[0.6.1]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.6.1
[0.6.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.6.0
[0.5.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.5.0
[0.4.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.4.0
[0.3.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.3.0
[0.2.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.2.0
[0.1.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.1.0
