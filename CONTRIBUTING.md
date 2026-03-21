# Contributing

## Development setup

```bash
uv sync
```

Run tests, linting, and type checking:

```bash
uv run pytest
uv run ruff check src/ tests/ generate_schema.py
uv run ruff format --check src/ tests/ generate_schema.py
uv run pyright src/ tests/
```

## Regenerating

To regenerate the schema for the current version:

```bash
python generate_schema.py generate
python generate_schema.py generate --force       # even if already up to date
python generate_schema.py generate --json        # also emit schema.json
python generate_schema.py generate --input FILE  # from a local header
```

## Version bumps

When a new Hyprland version is released:

```bash
python generate_schema.py bump v0.55.0
```

This will:

1. Read the old schema from the current `_data.py`.
2. Fetch and parse the new `ConfigDescriptions.hpp`.
3. Compute a reverse migration and save it to `_migrations/`.
4. Regenerate `_data.py` and `_registry.py`.

## Snapshots

For long migration chains, you can create snapshots to speed up version
reconstruction:

```bash
# Snapshot the current version
python generate_schema.py snapshot

# Snapshot a specific older version
python generate_schema.py snapshot v0.52.0
```

The generator automatically creates mid-chain snapshots when the cumulative
operation count exceeds 100.

## Project structure

```
generate_schema.py              CLI tool for schema generation
src/hyprland_schema/
  __init__.py                   Public API
  _model.py                     HyprOption dataclass and constants
  _schema.py                    Schema container class
  _parser.py                    C++ header regex parser
  _migration.py                 Migration engine for versioning
  _data.py                      Baked-in option data (generated)
  _migrations/
    _registry.py                Version registry (generated)
    *.json                      Migration and snapshot files (generated)
```

`_data.py`, `_registry.py`, and the JSON files in `_migrations/` are all
produced by `generate_schema.py` and should not be edited manually.
