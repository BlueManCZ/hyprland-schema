#!/usr/bin/env python3
"""Track upstream Hyprland releases and turn them into library releases.

Driven by ``.github/workflows/hyprland-update.yml`` and
``.github/workflows/release-on-merge.yml``; CONTRIBUTING.md ("Automated
updates") describes the overall flow.

Subcommands:

  plan           find stable upstream releases newer than ``_data.py`` and
                 pick the next library version
  update         ``generate_schema.py bump`` through every missing release in
                 ascending order, then write the version, changelog and PR body
  propose        push the rolling update branch and open or refresh its PR
  check-release  validate a merged update PR and the tag it should produce
  notes          print the CHANGELOG section for a library version

``propose`` only needs the standard library and git/gh, so the job that holds
a write token never installs or runs project dependencies.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
UPSTREAM = "hyprwm/Hyprland"
REPOSITORY = "BlueManCZ/hyprland-schema"
BASE_BRANCH = "main"
UPDATE_BRANCH = "bot/hyprland-update"
BOT_LOGIN = "github-actions[bot]"
BOT_NAME = "github-actions[bot]"
BOT_EMAIL = "41898282+github-actions[bot]@users.noreply.github.com"

_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
_MARKER = re.compile(r"<!-- hyprland-update (.*?) -->")
_PROJECT_VERSION = re.compile(r'^version = "([^"]+)"$', re.MULTILINE)
_README_VERSION = re.compile(r'(print\(hyprland_schema\.HYPRLAND_VERSION\)  # )"v[\d.]+"')

# Paths a generated update may touch; anything else means something went wrong.
_GENERATED_PATHS = (
    "CHANGELOG.md",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "src/hyprland_schema/_data.py",
    "src/hyprland_schema/_migrations/",
)

# A release that drops this share of options is far more likely a parser that
# no longer understands the upstream file than a real upstream change.
_MAX_REMOVED_SHARE = 0.25

# Field order for the release notes; anything else follows alphabetically.
_FIELD_ORDER = ("type", "default", "min", "max", "enum_values", "default_str", "description")


class ReleaseError(Exception):
    """Raised when automation must stop rather than guess."""


Version = tuple[int, int, int]
Runner = Callable[..., str]


def parse_tag(tag: str) -> Version | None:
    """Return the numeric version of a ``vX.Y.Z`` tag, or None for anything else."""
    m = _TAG.match(tag)
    if not m:
        return None
    major, minor, patch = (int(x) for x in m.groups())
    return major, minor, patch


def _require_tag(tag: str) -> Version:
    version = parse_tag(tag)
    if version is None:
        raise ReleaseError(f"not a vX.Y.Z tag: {tag!r}")
    return version


def _run(cmd: Sequence[str], *, cwd: Path = ROOT, check: bool = True) -> str:
    """Run a command and return its stdout; stderr streams to the log."""
    result = subprocess.run(list(cmd), cwd=cwd, stdout=subprocess.PIPE, text=True)
    if check and result.returncode != 0:
        raise ReleaseError(f"command failed ({result.returncode}): {' '.join(cmd)}")
    return result.stdout


# ---------------------------------------------------------------------------
# Upstream discovery
# ---------------------------------------------------------------------------


def _fetch_json(url: str) -> Any:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "hyprland-schema"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=30) as resp:
        return json.load(resp)


def fetch_releases(
    repo: str = UPSTREAM, fetch: Callable[[str], Any] = _fetch_json, max_pages: int = 20
) -> list[dict[str, Any]]:
    """Return every release of *repo* from the GitHub API."""
    releases: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        batch = fetch(f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}")
        if not isinstance(batch, list):
            raise ReleaseError(f"unexpected releases response for {repo}: {batch!r:.200}")
        if not batch:
            return releases
        releases.extend(batch)
    raise ReleaseError(f"more than {max_pages} pages of releases for {repo}")


def stable_versions(releases: Iterable[dict[str, Any]]) -> list[str]:
    """Published, non-prerelease ``vX.Y.Z`` tags, oldest first."""
    tags = {
        r["tag_name"]
        for r in releases
        if not r.get("draft") and not r.get("prerelease") and parse_tag(r.get("tag_name", ""))
    }
    return sorted(tags, key=_require_tag)


def missing_versions(current: str, stable: Iterable[str]) -> list[str]:
    """Stable versions newer than *current*, oldest first.

    Backports to an older minor line (a v0.55.5 after v0.56.0) are not newer
    and are skipped: the migration chain is linear, newest first.
    """
    cur = _require_tag(current)
    return sorted((v for v in stable if _require_tag(v) > cur), key=_require_tag)


# ---------------------------------------------------------------------------
# Library version policy
# ---------------------------------------------------------------------------


def _parse_library(version: str) -> Version:
    parsed = parse_tag(f"v{version}")
    if parsed is None:
        raise ReleaseError(f"library version {version!r} is not X.Y.Z")
    return parsed


def next_library_version(library: str, current_hyprland: str, missing: Sequence[str]) -> str:
    """Pick the library version for a catch-up from *current_hyprland* through *missing*.

    A new upstream minor (or major) line anywhere in the catch-up is a minor
    library release; patch-line updates only are a patch release. The base is
    the current library version, so earlier library-only bugfix releases
    (0.7.0 → 0.7.1) are carried forward rather than reused.
    """
    if not missing:
        raise ReleaseError("no missing versions to release")
    major, minor, patch = _parse_library(library)
    line = _require_tag(current_hyprland)[:2]
    if any(_require_tag(v)[:2] != line for v in missing):
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def check_new_library_tag(library: str, existing_tags: Iterable[str]) -> None:
    """Refuse a library version that is already tagged or not newer than every tag."""
    new = _parse_library(library)
    tagged = [t for t in existing_tags if parse_tag(t)]
    if f"v{library}" in tagged:
        raise ReleaseError(f"tag v{library} already exists; pyproject.toml is behind the tags")
    newer = [t for t in tagged if _require_tag(t) >= new]
    if newer:
        raise ReleaseError(f"v{library} is not newer than existing tag(s) {', '.join(newer)}")


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Plan:
    base: str
    current_hyprland: str
    current_library: str
    missing: list[str]
    library: str | None

    @property
    def target(self) -> str:
        return self.missing[-1]

    @property
    def title(self) -> str:
        span = self.missing[0] if len(self.missing) == 1 else self.missing[0] + "–" + self.target
        return f"Update schema for Hyprland {span}, release {self.library}"

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "Plan":
        return cls(**json.loads(text))


def read_library_version(root: Path) -> str:
    return tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"][
        "version"
    ]


def read_hyprland_version(root: Path) -> str:
    """HYPRLAND_VERSION from ``_data.py``, read as text so nothing gets imported."""
    text = (root / "src" / "hyprland_schema" / "_data.py").read_text(encoding="utf-8")
    m = re.search(r'^HYPRLAND_VERSION = "([^"]+)"$', text, re.MULTILINE)
    if not m:
        raise ReleaseError("HYPRLAND_VERSION not found in _data.py")
    return m.group(1)


def make_plan(
    root: Path, base: str, releases: Iterable[dict[str, Any]], existing_tags: Iterable[str]
) -> Plan:
    current = read_hyprland_version(root)
    library = read_library_version(root)
    missing = missing_versions(current, stable_versions(releases))
    new_library = None
    if missing:
        new_library = next_library_version(library, current, missing)
        check_new_library_tag(new_library, existing_tags)
    return Plan(base, current, library, missing, new_library)


# ---------------------------------------------------------------------------
# Schema diff and release notes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StepDiff:
    """Forward (old → new) changes between two consecutive Hyprland versions."""

    old_version: str
    new_version: str
    added: list[str]
    removed: list[str]
    changed: list[tuple[str, list[tuple[str, Any, Any]]]]
    option_count: int
    section_count: int

    @property
    def is_noop(self) -> bool:
        return not (self.added or self.removed or self.changed)


def _field_rank(name: str) -> tuple[int, str]:
    return (_FIELD_ORDER.index(name) if name in _FIELD_ORDER else len(_FIELD_ORDER), name)


def diff_step(
    old_version: str,
    old: list[dict[str, Any]],
    new_version: str,
    new: list[dict[str, Any]],
) -> StepDiff:
    """Diff two option lists using the same reverse migration ``bump`` writes."""
    from hyprland_schema._migration import compute_diff

    migration = compute_diff(old, new, old_version, new_version)
    added, removed, changed = [], [], []
    for op in migration["operations"]:
        # Reverse migration: "remove" undoes an upstream addition and vice versa.
        if op["op"] == "remove":
            added.append(op["key"])
        elif op["op"] == "add":
            removed.append(op["option"]["key"])
        else:
            fields = sorted(op["fields"].items(), key=lambda kv: _field_rank(kv[0]))
            changed.append((op["key"], [(name, old_v, new_v) for name, (new_v, old_v) in fields]))
    sections = {tuple(o["section"])[0] for o in new if o.get("section")}
    return StepDiff(old_version, new_version, added, removed, changed, len(new), len(sections))


def check_drift(step: StepDiff, old_count: int) -> None:
    """Fail loudly when a step looks like the parser lost track of upstream."""
    if step.option_count == 0:
        raise ReleaseError(f"{step.new_version}: parsed no options")
    if old_count and len(step.removed) > old_count * _MAX_REMOVED_SHARE:
        raise ReleaseError(
            f"{step.new_version}: {len(step.removed)} of {old_count} options disappeared; "
            "this looks like parser drift, not an upstream change — fix the parser"
        )


def _fmt(value: Any) -> str:
    return "`" + json.dumps(value, ensure_ascii=False) + "`"


def _render_change(field: str, old: Any, new: Any) -> str:
    if field == "description":
        return "description updated"
    if old is None:
        return f"{field} {_fmt(new)} added"
    if new is None:
        return f"{field} {_fmt(old)} dropped"
    return f"{field} {_fmt(old)} → {_fmt(new)}"


def render_step(step: StepDiff) -> list[str]:
    head = (
        f"- **Hyprland {step.new_version} schema** — {step.option_count} options across "
        f"{step.section_count} sections; "
    )
    if step.is_noop:
        return [
            head + "no upstream option changes; the "
            f"`{step.new_version} → {step.old_version}` migration is a no-op"
        ]
    counts = f"{len(step.added)} added, {len(step.removed)} removed, {len(step.changed)} changed"
    lines = [head + counts]
    if step.added:
        lines.append("  - Added: " + ", ".join(f"`{k}`" for k in step.added))
    if step.removed:
        lines.append("  - Removed: " + ", ".join(f"`{k}`" for k in step.removed))
    for key, fields in step.changed:
        lines.append(f"  - `{key}`: " + "; ".join(_render_change(*f) for f in fields))
    return lines


def render_changelog_entry(library: str, date: str, steps: Sequence[StepDiff], minor: bool) -> str:
    lines = [f"## [{library}] - {date}", "", "### Added" if minor else "### Changed", ""]
    for step in reversed(steps):  # newest first, like the hand-written entries
        lines.extend(render_step(step))
    return "\n".join(lines) + "\n"


def insert_changelog_entry(changelog: str, library: str, entry: str) -> str:
    if f"## [{library}]" in changelog:
        raise ReleaseError(f"CHANGELOG.md already has a {library} section")
    head, sep, rest = changelog.partition("\n## [")
    if not sep:
        raise ReleaseError("CHANGELOG.md has no release sections to insert before")
    changelog = f"{head}\n{entry}\n## [{rest}"
    link = f"[{library}]: https://github.com/{REPOSITORY}/releases/tag/v{library}\n"
    first_link = re.search(r"^\[[^\]]+\]: ", changelog, re.MULTILINE)
    if not first_link:
        raise ReleaseError("CHANGELOG.md has no link references to insert before")
    return changelog[: first_link.start()] + link + changelog[first_link.start() :]


def changelog_section(changelog: str, library: str) -> str:
    """Body of the ``## [library]`` section, without its heading."""
    m = re.search(
        rf"^## \[{re.escape(library)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)",
        changelog,
        re.MULTILINE | re.DOTALL,
    )
    if not m or not m.group(1).strip():
        raise ReleaseError(f"CHANGELOG.md has no {library} section")
    return m.group(1).strip() + "\n"


def set_project_version(pyproject: str, version: str) -> str:
    new, count = _PROJECT_VERSION.subn(f'version = "{version}"', pyproject)
    if count != 1:
        raise ReleaseError(f"expected one version line in pyproject.toml, found {count}")
    return new


def marker(plan: Plan) -> str:
    return f"<!-- hyprland-update target={plan.target} library={plan.library} base={plan.base} -->"


def parse_marker(text: str | None) -> dict[str, str]:
    m = _MARKER.search(text or "")
    if not m:
        return {}
    return dict(part.split("=", 1) for part in m.group(1).split() if "=" in part)


def render_pr_body(plan: Plan, entry: str) -> str:
    notes = entry.split("\n", 2)[2].strip()  # drop the "## [x.y.z] - date" heading
    steps = f" ({', '.join(plan.missing)})" if len(plan.missing) > 1 else ""
    return (
        f"Catches up from Hyprland {plan.current_hyprland} to {plan.target}{steps} "
        f"and releases hyprland-schema {plan.library}.\n\n"
        f"Generated by `hyprland-update.yml` from `{BASE_BRANCH}` @ {plan.base[:12]} with "
        "`generate_schema.py bump`, one version at a time. Generated data must not be "
        "edited by hand; regenerate instead.\n\n"
        f"**Merging this PR releases {plan.library}**: `release-on-merge.yml` tags "
        f"`v{plan.library}` at the merge commit, creates the GitHub release from the "
        "CHANGELOG entry and dispatches `publish.yml` (PyPI, `pypi` environment).\n\n"
        f"## Release notes\n\n{notes}\n\n{marker(plan)}\n"
    )


def commit_message(plan: Plan) -> str:
    return (
        f"{plan.title}\n\n"
        f"Generated by hyprland-update.yml from {plan.base}.\n\n"
        f"Hyprland-Target: {plan.target}\n"
        f"Library-Version: {plan.library}\n"
        f"Base-Commit: {plan.base}\n"
    )


def parse_trailers(message: str) -> dict[str, str]:
    keys = {"Hyprland-Target": "target", "Library-Version": "library", "Base-Commit": "base"}
    out: dict[str, str] = {}
    for line in message.splitlines():
        name, sep, value = line.partition(": ")
        if sep and name in keys:
            out[keys[name]] = value.strip()
    return out


# ---------------------------------------------------------------------------
# Update (runs bump for each missing release)
# ---------------------------------------------------------------------------


def dump_options(versions: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
    """Reconstruct each bundled version through the package's own migration chain."""
    from hyprland_schema import available_versions, load

    bundled = set(available_versions())
    out = {}
    for v in versions:
        if v not in bundled:
            raise ReleaseError(f"{v} is not bundled after the update")
        out[v] = [o.to_dict() for o in load(v).options]
    return out


def check_changed_paths(paths: Iterable[str]) -> None:
    unexpected = sorted(p for p in paths if not p.startswith(_GENERATED_PATHS))
    if unexpected:
        raise ReleaseError(f"update touched unexpected paths: {', '.join(unexpected)}")


def run_update(plan: Plan, root: Path, run: Runner = _run, date: str | None = None) -> str:
    """Apply *plan* to the working tree at *root* and return the PR body."""
    if not plan.missing or plan.library is None:
        raise ReleaseError("plan has nothing to update")
    if read_hyprland_version(root) != plan.current_hyprland:
        raise ReleaseError("working tree does not match the plan")

    for version in plan.missing:
        # One process per bump: bump imports the current _data.py, which must
        # be the one the previous bump just wrote.
        run([sys.executable, "generate_schema.py", "bump", version], cwd=root)

    # Fresh process again, so the notes come from the regenerated package.
    chain = [plan.current_hyprland, *plan.missing]
    dumped = json.loads(
        run([sys.executable, "scripts/hyprland_release.py", "dump-options", *chain], cwd=root)
    )
    steps = []
    for old_v, new_v in zip(chain, chain[1:]):
        step = diff_step(old_v, dumped[old_v], new_v, dumped[new_v])
        check_drift(step, len(dumped[old_v]))
        steps.append(step)

    minor = _parse_library(plan.library)[2] == 0
    entry = render_changelog_entry(
        plan.library, date or datetime.now(UTC).strftime("%Y-%m-%d"), steps, minor
    )

    pyproject = root / "pyproject.toml"
    pyproject.write_text(set_project_version(pyproject.read_text("utf-8"), plan.library), "utf-8")
    changelog = root / "CHANGELOG.md"
    changelog.write_text(
        insert_changelog_entry(changelog.read_text("utf-8"), plan.library, entry), "utf-8"
    )
    readme = root / "README.md"
    readme.write_text(
        _README_VERSION.sub(rf'\1"{plan.target}"', readme.read_text("utf-8")), "utf-8"
    )
    run(["uv", "lock"], cwd=root)

    status = run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=root)
    check_changed_paths(line[3:] for line in status.splitlines() if line)
    return render_pr_body(plan, entry)


# ---------------------------------------------------------------------------
# Propose (rolling PR)
# ---------------------------------------------------------------------------

Action = Literal["push", "ensure-pr", "skip-maintainer", "skip-rejected"]


@dataclass(frozen=True)
class BranchState:
    remote_sha: str | None  # current head of the update branch, None if absent
    trailers: dict[str, str]  # parsed from that head commit
    foreign_commits: bool  # commits on the branch not made by the bot
    open_pr: int | None
    rejected_target: str | None  # target of the last PR closed without merging


def decide(plan: Plan, state: BranchState) -> Action:
    """What to do with the update branch for *plan*.

    - A maintainer's commits on an open PR are never overwritten.
    - A target the maintainer already closed unmerged is not re-proposed;
      a newer upstream release supersedes it.
    - A branch already holding this target built on this base is left alone,
      so reruns don't churn the PR or its CI.
    - Otherwise the branch is replaced with the fresh build from main.
    """
    if state.open_pr is None and state.rejected_target == plan.target:
        return "skip-rejected"
    if state.remote_sha and state.open_pr is not None and state.foreign_commits:
        return "skip-maintainer"
    if state.remote_sha and not state.foreign_commits:
        if state.trailers.get("target") == plan.target and state.trailers.get("base") == plan.base:
            return "ensure-pr"
    return "push"


def read_branch_state(run: Runner, repository: str) -> BranchState:
    ref = f"refs/heads/{UPDATE_BRANCH}"
    remote = run(["git", "ls-remote", "origin", ref]).split()
    remote_sha = remote[0] if remote else None
    trailers: dict[str, str] = {}
    foreign = False
    if remote_sha:
        run(["git", "fetch", "--no-tags", "origin", f"+{ref}:refs/remotes/origin/{UPDATE_BRANCH}"])
        trailers = parse_trailers(run(["git", "log", "-1", "--format=%B", remote_sha]))
        idents = run(
            ["git", "log", "--format=%an <%ae>%n%cn <%ce>", f"origin/{BASE_BRANCH}..{remote_sha}"]
        )
        bot = f"{BOT_NAME} <{BOT_EMAIL}>"
        foreign = any(line != bot for line in idents.splitlines() if line)

    def prs(state: str) -> list[dict[str, Any]]:
        out = run(
            ["gh", "pr", "list", "--repo", repository, "--head", UPDATE_BRANCH, "--base"]
            + [BASE_BRANCH, "--state", state, "--limit", "20"]
            + ["--json", "number,body,closedAt,mergedAt,author"]
        )
        return [
            p for p in json.loads(out) if p["author"]["login"] in (BOT_LOGIN, "app/github-actions")
        ]

    open_prs = prs("open")
    rejected = None
    closed = sorted(prs("closed"), key=lambda p: p["closedAt"] or "", reverse=True)
    if closed and not closed[0]["mergedAt"]:
        rejected = parse_marker(closed[0]["body"]).get("target")
    return BranchState(
        remote_sha, trailers, foreign, open_prs[0]["number"] if open_prs else None, rejected
    )


def propose(
    plan: Plan, bundle: Path, body: Path, repository: str, run: Runner = _run, dry_run: bool = False
) -> Action:
    def mutate(cmd: list[str]) -> None:
        if dry_run:
            print("dry-run, would run:", " ".join(cmd), file=sys.stderr)
        else:
            run(cmd)

    run(["git", "fetch", "--no-tags", str(bundle), "HEAD"])
    commit = run(["git", "rev-parse", "FETCH_HEAD"]).strip()
    parent = run(["git", "rev-parse", f"{commit}^"]).strip()
    if parent != plan.base:
        raise ReleaseError(f"bundle commit {commit} is not based on {plan.base}")

    state = read_branch_state(run, repository)
    action = decide(plan, state)
    print(f"{UPDATE_BRANCH}: {action} ({state})", file=sys.stderr)
    if action.startswith("skip"):
        print(f"::warning::{UPDATE_BRANCH} not updated: {action}", file=sys.stderr)
        return action

    if action == "push":
        lease = f"--force-with-lease=refs/heads/{UPDATE_BRANCH}:{state.remote_sha or ''}"
        mutate(["git", "push", lease, "origin", f"{commit}:refs/heads/{UPDATE_BRANCH}"])

    pr_args = ["--repo", repository, "--title", plan.title, "--body-file", str(body)]
    if state.open_pr is None:
        mutate(["gh", "pr", "create", "--base", BASE_BRANCH, "--head", UPDATE_BRANCH, *pr_args])
    elif action == "push":
        mutate(["gh", "pr", "edit", str(state.open_pr), *pr_args])

    if action == "push" or state.open_pr is None:
        # PRs and pushes made with GITHUB_TOKEN don't trigger pull_request
        # workflows; workflow_dispatch is the documented exception.
        mutate(["gh", "workflow", "run", "ci.yml", "--repo", repository, "--ref", UPDATE_BRANCH])
    return action


# ---------------------------------------------------------------------------
# Release guard
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    sha: str
    tag_exists: bool


def check_release(
    event: dict[str, Any], repository: str, root: Path, tags: dict[str, str]
) -> ReleaseInfo:
    """Validate that *event* is a merged bot update PR and decide its tag.

    *tags* maps existing tag names to the commit they point at. A tag that
    already points at the merge commit is a retry; pointing anywhere else, or
    a version not newer than every tag, is an error — nothing is overwritten.
    """
    pr = event.get("pull_request") or {}
    checks = {
        "PR is merged": pr.get("merged") is True,
        f"base is {BASE_BRANCH}": pr.get("base", {}).get("ref") == BASE_BRANCH,
        f"head is {UPDATE_BRANCH}": pr.get("head", {}).get("ref") == UPDATE_BRANCH,
        f"head repo is {repository}": (pr.get("head", {}).get("repo") or {}).get("full_name")
        == repository,
        f"opened by {BOT_LOGIN}": pr.get("user", {}).get("login") == BOT_LOGIN,
        "merge commit is known": bool(pr.get("merge_commit_sha")),
    }
    failed = [name for name, ok in checks.items() if not ok]
    if failed:
        raise ReleaseError("not a merged update PR: " + "; ".join(failed))

    sha = pr["merge_commit_sha"]
    version = read_library_version(root)
    tag = f"v{version}"
    changelog_section((root / "CHANGELOG.md").read_text("utf-8"), version)

    if tag in tags:
        if tags[tag] != sha:
            raise ReleaseError(f"{tag} already exists at {tags[tag]}, not merge commit {sha}")
        return ReleaseInfo(version, tag, sha, tag_exists=True)
    check_new_library_tag(version, tags)
    return ReleaseInfo(version, tag, sha, tag_exists=False)


def read_tags(run: Runner = _run) -> dict[str, str]:
    out = run(["git", "for-each-ref", "refs/tags", "--format=%(refname:short) %(objectname)"])
    names = [line.split()[0] for line in out.splitlines() if line]
    # Peel annotated tags to the commit they point at.
    return {n: run(["git", "rev-parse", f"{n}^{{commit}}"]).strip() for n in names}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _set_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for k, v in values.items():
                f.write(f"{k}={v}\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("plan")
    p.add_argument("--output", type=Path, required=True)

    p = sub.add_parser("update")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--body", type=Path, required=True)
    p.add_argument("--message", type=Path, required=True)

    p = sub.add_parser("propose")
    p.add_argument("--plan", type=Path, required=True)
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--body", type=Path, required=True)
    p.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", REPOSITORY))
    p.add_argument("--dry-run", action="store_true")

    p = sub.add_parser("check-release")
    p.add_argument("--event", type=Path, default=os.environ.get("GITHUB_EVENT_PATH"))
    p.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", REPOSITORY))

    p = sub.add_parser("notes")
    p.add_argument("version")

    p = sub.add_parser("dump-options")
    p.add_argument("versions", nargs="+")

    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            base = _run(["git", "rev-parse", "HEAD"]).strip()
            tags = _run(["git", "tag", "--list", "v*"]).split()
            plan = make_plan(ROOT, base, fetch_releases(), tags)
            args.output.write_text(plan.to_json(), encoding="utf-8")
            if plan.missing:
                print(f"{plan.title} (missing: {', '.join(plan.missing)})", file=sys.stderr)
            else:
                print(f"Up to date: {plan.current_hyprland} is the latest stable", file=sys.stderr)
            _set_output(has_update=str(bool(plan.missing)).lower())
        elif args.command == "update":
            plan = Plan.from_json(args.plan.read_text("utf-8"))
            args.body.write_text(run_update(plan, ROOT), encoding="utf-8")
            args.message.write_text(commit_message(plan), encoding="utf-8")
        elif args.command == "propose":
            plan = Plan.from_json(args.plan.read_text("utf-8"))
            propose(plan, args.bundle, args.body, args.repository, dry_run=args.dry_run)
        elif args.command == "check-release":
            event = json.loads(Path(args.event).read_text("utf-8"))
            info = check_release(event, args.repository, ROOT, read_tags())
            print(f"release {info.tag} at {info.sha} (tag exists: {info.tag_exists})")
            _set_output(version=info.version, tag=info.tag, sha=info.sha)
        elif args.command == "notes":
            print(changelog_section((ROOT / "CHANGELOG.md").read_text("utf-8"), args.version))
        elif args.command == "dump-options":
            json.dump(dump_options(args.versions), sys.stdout)
    except ReleaseError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
