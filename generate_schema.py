#!/usr/bin/env python3
"""Generate Hyprland option schema from ConfigDescriptions.hpp.

Parses the C++ header and emits:
  - schema.json                      — machine-readable option schema
  - src/hyprland_schema/_data.py     — importable Python module with baked-in data

No C++ compiler needed. Uses the parser from hyprland_schema._parser.
"""

import argparse
import ast
import functools
import json
import shutil
import subprocess
import sys
import warnings
from collections.abc import Sequence
from dataclasses import fields as dataclass_fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hyprland_schema._migration import build_options, compute_diff
from hyprland_schema._model import HyprOption
from hyprland_schema._parser import RAW_URL_TEMPLATE, fetch_header, parse_header
from hyprland_schema._schema import SOURCE_URL_TEMPLATE, Schema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class SchemaError(Exception):
    """Raised when schema generation fails."""


def _write_json(path: Path, data: dict[str, Any]) -> None:
    """Write a JSON file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@functools.cache
def _find_ruff() -> str | None:
    """Find the ruff binary, caching the result."""
    return shutil.which("ruff")


def _run_ruff(path: Path) -> None:
    """Format a file with ruff if available."""
    ruff = _find_ruff()
    if ruff:
        result = subprocess.run([ruff, "format", str(path)], capture_output=True, text=True)
        if result.returncode != 0:
            warnings.warn(
                f"ruff format failed for {path.name}: {result.stderr.strip()}", stacklevel=2
            )


def _fetch_or_read(input_path: Path | None, version: str) -> str:
    """Read the C++ header from a local file or fetch from GitHub."""
    if input_path:
        return input_path.read_text(encoding="utf-8")

    from urllib.error import HTTPError, URLError

    print(f"Fetching {RAW_URL_TEMPLATE.format(version=version)}", file=sys.stderr)
    try:
        return fetch_header(version)
    except (HTTPError, URLError) as e:
        detail = f"HTTP {e.code}" if isinstance(e, HTTPError) else str(e.reason)
        raise SchemaError(
            f"{detail} fetching version {version}\nHint: use --input to parse a local file instead"
        ) from e


def _parse_or_fail(content: str) -> list[HyprOption]:
    """Parse header content, raising SchemaError if no options are found."""
    options = parse_header(content)
    if not options:
        raise SchemaError("No options found — file format may have changed")
    return options


def _count_sections(options: Sequence[HyprOption]) -> int:
    """Count distinct top-level sections."""
    return len({o.section[0] for o in options if o.section})


# ---------------------------------------------------------------------------
# JSON emitter
# ---------------------------------------------------------------------------


def emit_json(options: Sequence[HyprOption], version: str, output_dir: Path) -> Path:
    """Write schema.json to the output directory."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    schema = Schema(version=version, options=tuple(options))
    data = schema.to_dict()
    data["generated_at"] = now
    path = output_dir / "schema.json"
    _write_json(path, data)
    return path


# ---------------------------------------------------------------------------
# Python module emitter
# ---------------------------------------------------------------------------


_MAX_LINE = 100
_INDENT = " " * 8  # field indent inside HyprOption(...) in emitted code


def repr_value(val: Any) -> str:
    """Return a Python repr suitable for embedding in generated code.

    Lists and tuples are emitted as tuples (trailing comma only for single-element).
    """
    if isinstance(val, (list, tuple)):
        inner = ", ".join(repr_value(v) for v in val)
        return f"({inner},)" if len(val) == 1 else f"({inner})"
    return repr(val)


def repr_field(name: str, val: Any) -> list[str]:
    """Return one or more lines for a dataclass field assignment.

    Wraps long string values into parenthesized multi-line concatenation
    so every emitted line stays within the line-length limit.
    """
    simple = f"{_INDENT}{name}={repr_value(val)},"
    if len(simple) <= _MAX_LINE:
        return [simple]

    # Only string values can be meaningfully split.
    if not isinstance(val, str):
        return [simple]

    # Use implicit string concatenation inside parentheses.
    # Each continuation line: 12 spaces + repr(chunk)  (8 indent + 4 extra)
    cont_indent = _INDENT + "    "
    # repr() adds 2 chars for quotes; leave margin for escape characters.
    chunk_width = _MAX_LINE - len(cont_indent) - 8

    out = [f"{_INDENT}{name}=("]
    remaining = val
    while remaining:
        size = min(chunk_width, len(remaining))
        out.append(f"{cont_indent}{repr(remaining[:size])}")
        remaining = remaining[size:]
    out.append(f"{_INDENT}),")
    return out


def emit_python(options: Sequence[HyprOption], version: str, output_dir: Path) -> Path:
    """Write src/hyprland_schema/_data.py to the output directory."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    source = SOURCE_URL_TEMPLATE.format(version=version)

    lines: list[str] = []
    lines.append("# AUTO-GENERATED by generate_schema.py, DO NOT EDIT")
    lines.append(f"# Hyprland version: {version}")
    lines.append(f"# Generated: {now}")
    lines.append(f"# Source: {source}")
    lines.append("")
    lines.append("from hyprland_schema._model import HyprOption")
    lines.append("")
    lines.append(f"HYPRLAND_VERSION = {version!r}")
    lines.append("")
    lines.append("")
    lines.append("OPTIONS: tuple[HyprOption, ...] = (")

    for opt in options:
        lines.append("    HyprOption(")
        for f in dataclass_fields(HyprOption):
            val = getattr(opt, f.name)
            if f.name not in HyprOption._REQUIRED_FIELDS and val is None:
                continue
            if f.name == "description":
                lines.extend(repr_field(f.name, val))
            else:
                lines.append(f"        {f.name}={repr_value(val)},")
        lines.append("    ),")

    lines.append(")")
    lines.append("")

    pkg_dir = output_dir / "src" / "hyprland_schema"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    path = pkg_dir / "_data.py"
    path.write_text("\n".join(lines), encoding="utf-8")

    # Let ruff handle final formatting (quote style, line wrapping).
    _run_ruff(path)

    return path


# ---------------------------------------------------------------------------
# Input resolution
# ---------------------------------------------------------------------------


def resolve_version(args_version: str | None, output_dir: Path) -> str:
    """Determine the Hyprland version tag to use."""
    if args_version:
        return args_version
    current = current_data_version(output_dir)
    if current:
        return current
    raise SchemaError("no --version given and no existing _data.py to read version from")


def current_data_version(output_dir: Path) -> str | None:
    """Read the HYPRLAND_VERSION from the current _data.py, if it exists."""
    data_path = output_dir / "src" / "hyprland_schema" / "_data.py"
    if not data_path.exists():
        return None
    with data_path.open() as f:
        for line in f:
            if line.startswith("HYPRLAND_VERSION"):
                # HYPRLAND_VERSION = "v0.54.2"
                _, _, rhs = line.partition("=")
                if rhs:
                    return ast.literal_eval(rhs.strip())
    return None


def is_up_to_date(version: str, output_dir: Path) -> bool:
    """Check if _data.py already matches the requested version."""
    return current_data_version(output_dir) == version


# ---------------------------------------------------------------------------
# Migration helpers
# ---------------------------------------------------------------------------

_SNAPSHOT_OPS_THRESHOLD = 100  # Suggest a snapshot when cumulative ops exceed this.


def _version_key(v: str) -> tuple[int, ...]:
    """Parse a version tag like 'v0.54.2' into a comparable tuple."""
    return tuple(int(x) for x in v.lstrip("v").split("."))


def _migrations_dir(output_dir: Path) -> Path:
    return output_dir / "src" / "hyprland_schema" / "_migrations"


def write_migration(
    migration: dict[str, Any],
    output_dir: Path,
) -> Path:
    """Write a migration JSON file to _migrations/."""
    filename = f"{migration['from_version']}_to_{migration['to_version']}.json"
    path = _migrations_dir(output_dir) / filename
    _write_json(path, migration)
    return path


def write_snapshot(
    options: Sequence[HyprOption],
    version: str,
    output_dir: Path,
) -> Path:
    """Write a full snapshot JSON file to _migrations/."""
    path = _migrations_dir(output_dir) / f"{version}_snapshot.json"
    _write_json(
        path,
        {
            "format_version": 1,
            "type": "snapshot",
            "version": version,
            "options": [o.to_dict() for o in options],
        },
    )
    return path


def chain_ops_count(output_dir: Path, versions: list[str], snapshots: set[str]) -> int:
    """Count total operations in the migration chain from latest to oldest."""
    mig_dir = _migrations_dir(output_dir)
    total = 0
    for from_ver, to_ver in zip(versions, versions[1:]):
        mig_file = mig_dir / f"{from_ver}_to_{to_ver}.json"
        if mig_file.exists():
            mig = json.loads(mig_file.read_text(encoding="utf-8"))
            total += len(mig.get("operations", []))
        if to_ver in snapshots:
            break
    return total


def update_registry(output_dir: Path) -> tuple[Path, list[str], set[str]]:
    """Scan _migrations/ and regenerate _registry.py.

    Returns (path, sorted_versions, snapshots).
    """
    mig_dir = _migrations_dir(output_dir)
    mig_dir.mkdir(parents=True, exist_ok=True)

    # Collect all versions from migration filenames and snapshots.
    versions: set[str] = set()
    snapshots: set[str] = set()

    for f in mig_dir.iterdir():
        if f.suffix != ".json":
            continue
        if f.name.endswith("_snapshot.json"):
            ver = f.name.removesuffix("_snapshot.json")
            versions.add(ver)
            snapshots.add(ver)
        elif "_to_" in f.name:
            parts = f.stem.split("_to_")
            versions.add(parts[0])
            versions.add(parts[1])

    # Always include the current version from _data.py.
    current = current_data_version(output_dir)
    if current:
        versions.add(current)
        snapshots.add(current)  # latest is implicitly a snapshot

    # Sort versions descending (newest first) using version tuple comparison.
    sorted_versions = sorted(versions, key=_version_key, reverse=True)

    lines = [
        "# AUTO-GENERATED by generate_schema.py, DO NOT EDIT",
        "",
        "VERSIONS: tuple[str, ...] = (",
    ]
    for v in sorted_versions:
        lines.append(f'    "{v}",')
    lines.append(")")
    lines.append("")
    lines.append("SNAPSHOTS: frozenset[str] = frozenset({")
    for v in sorted(snapshots, key=_version_key, reverse=True):
        lines.append(f'    "{v}",')
    lines.append("})")
    lines.append("")

    path = mig_dir / "_registry.py"
    path.write_text("\n".join(lines), encoding="utf-8")

    _run_ruff(path)

    return path, sorted_versions, snapshots


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_snapshot(version: str | None, output_dir: Path) -> None:
    """Handle snapshot subcommand: write a snapshot JSON."""
    version = version or resolve_version(None, output_dir)
    snap_options = build_options(version)

    path = write_snapshot(snap_options, version, output_dir)
    print(f"Wrote snapshot {path.name}", file=sys.stderr)
    update_registry(output_dir)  # return value unused — just regenerate the file


def _cmd_bump(version: str, input_path: Path | None, output_dir: Path) -> None:
    """Handle --bump: version bump workflow."""
    old_version = current_data_version(output_dir)
    if old_version and old_version == version:
        raise SchemaError(f"_data.py is already at {version}. Nothing to bump.")

    content = _fetch_or_read(input_path, version)
    new_options = _parse_or_fail(content)

    if old_version:
        from hyprland_schema._data import OPTIONS as OLD_OPTIONS

        old_dicts = [o.to_dict() for o in OLD_OPTIONS]
        new_dicts = [o.to_dict() for o in new_options]
        migration = compute_diff(old_dicts, new_dicts, old_version, version)
        mig_path = write_migration(migration, output_dir)
        n_ops = len(migration["operations"])
        print(f"Wrote migration {mig_path.name} ({n_ops} operations)", file=sys.stderr)

    py_path = emit_python(new_options, version, output_dir)
    print(f"Wrote {py_path.name}", file=sys.stderr)

    reg_path, version_list, snapshot_set = update_registry(output_dir)
    print(f"Updated {reg_path.name}", file=sys.stderr)

    _maybe_create_mid_chain_snapshot(output_dir, version_list, snapshot_set)

    print(
        f"\nhyprland-schema-gen {version}: "
        f"{len(new_options)} options, {_count_sections(new_options)} sections",
        file=sys.stderr,
    )


def _maybe_create_mid_chain_snapshot(
    output_dir: Path, version_list: list[str], snapshots: set[str]
) -> None:
    """Auto-create a mid-chain snapshot if the migration chain has grown heavy."""
    if len(version_list) <= 2:
        return

    total_ops = chain_ops_count(output_dir, version_list, snapshots)
    if total_ops <= _SNAPSHOT_OPS_THRESHOLD:
        return

    mid_ver = version_list[len(version_list) // 2]
    if mid_ver in snapshots:
        return

    mid_opts = build_options(mid_ver)
    snap_path = write_snapshot(mid_opts, mid_ver, output_dir)
    update_registry(output_dir)
    print(
        f"Auto-created snapshot {snap_path.name} (chain had {total_ops} operations)",
        file=sys.stderr,
    )


def _cmd_generate(
    version: str,
    input_path: Path | None,
    output_dir: Path,
    *,
    write_json: bool,
    write_python: bool,
    force: bool,
) -> None:
    """Handle default workflow: generate _data.py and optionally schema.json."""
    if not force and is_up_to_date(version, output_dir):
        print(f"Already up to date for {version}.", file=sys.stderr)
        return

    content = _fetch_or_read(input_path, version)
    options = _parse_or_fail(content)

    json_path = emit_json(options, version, output_dir) if write_json else None
    py_path = emit_python(options, version, output_dir) if write_python else None

    print(f"\nhyprland-schema-gen {version}", file=sys.stderr)
    print(
        f"Parsed {len(options)} options across {_count_sections(options)} sections",
        file=sys.stderr,
    )
    if json_path:
        print(f"Wrote {json_path.name} ({json_path.stat().st_size // 1024} KB)", file=sys.stderr)
    if py_path:
        print(f"Wrote {py_path.name} ({py_path.stat().st_size // 1024} KB)", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Hyprland option schema from ConfigDescriptions.hpp"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent,
        help="Where to write output files (default: script directory)",
    )
    # Defaults for generate-specific args so they exist even without a subcommand.
    parser.set_defaults(
        command=None, version=None, input=None, json=False, no_python=False, force=False
    )
    subparsers = parser.add_subparsers(dest="command")

    # --- generate (also the default when no subcommand is given) ---
    gen_parser = subparsers.add_parser(
        "generate",
        help="Generate _data.py and optionally schema.json",
    )
    gen_parser.add_argument(
        "--version",
        help="Hyprland tag to fetch (default: version from _data.py)",
    )
    gen_parser.add_argument(
        "--input",
        type=Path,
        help="Use a local ConfigDescriptions.hpp instead of fetching",
    )
    gen_parser.add_argument(
        "--json",
        action="store_true",
        help="Also generate a standalone schema.json",
    )
    gen_parser.add_argument(
        "--no-python",
        action="store_true",
        help="Skip generating _data.py",
    )
    gen_parser.add_argument(
        "--force",
        action="store_true",
        help="Re-generate even if _data.py already matches the version",
    )

    # --- bump ---
    bump_parser = subparsers.add_parser(
        "bump",
        help="Bump to a new Hyprland version with migration",
    )
    bump_parser.add_argument(
        "version",
        help="New Hyprland version tag (e.g. v0.55.0)",
    )
    bump_parser.add_argument(
        "--input",
        type=Path,
        help="Use a local ConfigDescriptions.hpp instead of fetching",
    )

    # --- snapshot ---
    snap_parser = subparsers.add_parser(
        "snapshot",
        help="Write a snapshot JSON for faster version reconstruction",
    )
    snap_parser.add_argument(
        "version",
        nargs="?",
        help="Version to snapshot (default: current version)",
    )

    # --- update-registry ---
    subparsers.add_parser(
        "update-registry",
        help="Regenerate _registry.py from existing migration files",
    )

    args = parser.parse_args()
    output_dir: Path = args.output_dir

    try:
        if args.command == "bump":
            _cmd_bump(args.version, args.input, output_dir)
        elif args.command == "snapshot":
            _cmd_snapshot(args.version, output_dir)
        elif args.command == "update-registry":
            path, _, _ = update_registry(output_dir)
            print(f"Updated {path}", file=sys.stderr)
        else:
            # No subcommand or explicit "generate".
            version = resolve_version(args.version, output_dir)
            _cmd_generate(
                version,
                args.input,
                output_dir,
                write_json=args.json,
                write_python=not args.no_python,
                force=args.force,
            )
    except SchemaError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
