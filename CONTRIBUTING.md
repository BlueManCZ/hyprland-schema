# Contributing

## Development setup

```bash
uv sync
```

Run tests, linting, and type checking:

```bash
uv run pytest
uv run ruff check src/ tests/ scripts/ generate_schema.py
uv run ruff format --check src/ tests/ scripts/ generate_schema.py
uv run pyright src/ tests/ scripts/ generate_schema.py
uv build
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

## Automated updates

New Hyprland releases are picked up by GitHub Actions; a maintainer reviews
and merges the result, and the merge releases the library. Nothing merges or
publishes without that review.

**Schedule.** `.github/workflows/hyprland-update.yml` runs daily at 05:17 UTC
and on demand (*Actions → Hyprland update → Run workflow*; it always builds
from `main`, whichever branch it is started from).

**Detection.** Every release of `hyprwm/Hyprland` is listed through the
GitHub API; drafts, prereleases and tags that are not `vX.Y.Z` are ignored and
the rest are sorted numerically. Every stable version newer than `_data.py` is
caught up, oldest first, with one `generate_schema.py bump` per version, so
each gets its reverse migration (and any automatic snapshot) exactly as a
manual bump would. Backports to an older minor line are not newer than the
bundled version and are skipped.

**Library version.** Independent of the Hyprland version and based on
`pyproject.toml`, so earlier library-only releases carry forward:

| Catch-up contains                         | Library release | Example             |
|-------------------------------------------|-----------------|---------------------|
| only patch releases of the current line   | patch           | 0.7.1 → 0.7.2       |
| any new minor or major upstream line      | minor           | 0.7.1 → 0.8.0       |

A catch-up across several upstream releases is one library release. The run
fails if that version is already tagged or not newer than every existing tag.

**Release notes** are rendered from the reconstructed schemas, one bullet per
upstream version, newest first: option count, added and removed keys, and
per-key type/default/bound/choice changes (description edits are summarised).
A release without option changes says its migration is a no-op. They are
written to `CHANGELOG.md`, which the PR shows and the release copies — edit
them in the PR if they need prose.

**The PR.** `prepare` (read-only token) runs the bumps, sets the version,
updates `CHANGELOG.md`, `README.md` and `uv.lock`, then runs the full test,
Ruff, Pyright and build gates. `propose` pushes a single commit to the fixed
branch `bot/hyprland-update` (with `--force-with-lease`) and opens or
refreshes the one PR from it. Runs are serialised, and:

- nothing newer upstream → no commit, no PR (`Up to date` in the log);
- the branch already holds the same target built on the same `main` commit →
  left alone, so reruns don't churn the PR or its CI;
- `main` moved or upstream released again → the branch is rebuilt from the
  current `main`;
- someone other than the bot committed to the branch while its PR is open →
  the branch is left alone (warning in the log); merge or close the PR and the
  next run picks up from there;
- the PR for a target was closed without merging → that target is not
  proposed again; the next upstream release supersedes it (or reopen the PR).

**Failures stop the run before anything is pushed:** an upstream file that no
longer parses (`bump` fails), a release that drops more than a quarter of the
options (treated as parser drift), a failing gate, a generated change outside
the generated files, or a duplicate library tag. Fix the cause on `main` —
never by relaxing a test to fit the generated data — and rerun.

**CI on the bot PR.** Pushes and PRs made with `GITHUB_TOKEN` do not trigger
`pull_request` workflows, so `propose` starts `ci.yml` on the branch with
`workflow_dispatch`; its checks show on the PR's head commit. Close and reopen
the PR to also get a regular `pull_request` run.

**Release on merge.** `.github/workflows/release-on-merge.yml` reacts only to
a merged PR from `bot/hyprland-update` in this repository, opened by
`github-actions[bot]`, into `main`. It checks that the merge commit is on
`main`, takes the version from `pyproject.toml` there, creates the tag and
GitHub release at that exact commit from the CHANGELOG entry, and dispatches
`publish.yml` on the tag (a release created with `GITHUB_TOKEN` does not fire
the `release` trigger). Reruns are safe: an existing tag is accepted only if
it already points at the merge commit, an existing release is not recreated,
and a version already on PyPI is not dispatched again. Publishing still goes
through the `pypi` environment's trusted publisher; manual releases keep
working as before.

**Repository setting.** Opening the PR needs *Settings → Actions → General →
Workflow permissions → Allow GitHub Actions to create and approve pull
requests*. Without it `propose` fails at `gh pr create` after pushing the
branch; enable it and rerun. No other secrets or settings are needed.

To try a run without touching GitHub, use a throwaway clone:

```bash
uv run python scripts/hyprland_release.py plan --output plan.json
uv run python scripts/hyprland_release.py update --plan plan.json \
    --body pr-body.md --message commit-message.txt
```

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
scripts/hyprland_release.py     Upstream tracking and release automation
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
