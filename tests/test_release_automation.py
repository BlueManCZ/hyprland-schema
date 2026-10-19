"""Offline tests for scripts/hyprland_release.py — no network, git or gh."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.hyprland_release import (
    _README_VERSION,
    BOT_LOGIN,
    UPDATE_BRANCH,
    BranchState,
    Plan,
    ReleaseError,
    StepDiff,
    changelog_section,
    check_changed_paths,
    check_drift,
    check_new_library_tag,
    check_release,
    commit_message,
    decide,
    diff_step,
    fetch_releases,
    insert_changelog_entry,
    make_plan,
    marker,
    missing_versions,
    next_library_version,
    parse_marker,
    parse_trailers,
    propose,
    render_changelog_entry,
    render_pr_body,
    run_update,
    set_project_version,
    stable_versions,
)

ROOT = Path(__file__).resolve().parent.parent
REPO = "BlueManCZ/hyprland-schema"
BASE = "a" * 40
MERGE = "b" * 40

# Fixtures rather than the real files: the bot bumps those, and tests must not
# depend on which version the repository is currently at.
CHANGELOG = """# Changelog

Intro with a [link](https://keepachangelog.com/en/1.1.0/).

## [0.7.1] - 2026-07-31

### Fixed

- a fix

## [0.1.0] - 2026-03-21

Initial release.

### Added

- everything

[0.7.1]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.7.1
[0.1.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v0.1.0
"""
PYPROJECT = '[project]\nname = "hyprland-schema"\nversion = "0.7.1"\n\n[tool.ruff]\n'
README = '```python\nprint(hyprland_schema.HYPRLAND_VERSION)  # "v0.56.1"\n```\n'


def release(tag: str, *, draft: bool = False, prerelease: bool = False) -> dict[str, Any]:
    return {"tag_name": tag, "draft": draft, "prerelease": prerelease}


def option(key: str, **fields: Any) -> dict[str, Any]:
    section, _, name = key.rpartition(":")
    base = {
        "key": key,
        "section": section.split(":"),
        "name": name,
        "description": f"{name} option",
        "type": "int",
        "default": 0,
    }
    return base | fields


def make_tree(tmp_path: Path, hyprland: str = "v0.56.1", library: str = "0.7.1") -> Path:
    """A minimal checkout: the files plan/update/check-release read."""
    pkg = tmp_path / "src" / "hyprland_schema"
    pkg.mkdir(parents=True)
    (pkg / "_data.py").write_text(f'HYPRLAND_VERSION = "{hyprland}"\n')
    (tmp_path / "pyproject.toml").write_text(set_project_version(PYPROJECT, library))
    (tmp_path / "CHANGELOG.md").write_text(CHANGELOG)
    (tmp_path / "README.md").write_text(README)
    return tmp_path


def make_plan_for(
    missing: list[str], library: str | None = "0.7.2", current: str = "v0.56.1"
) -> Plan:
    return Plan(BASE, current, "0.7.1", missing, library)


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


class TestDiscovery:
    def test_ignores_drafts_prereleases_and_odd_tags(self) -> None:
        releases = [
            release("v0.57.0", draft=True),
            release("v0.57.0-rc1"),
            release("v0.56.3", prerelease=True),
            release("nightly"),
            release("v0.56.2"),
        ]
        assert stable_versions(releases) == ["v0.56.2"]

    def test_sorts_numerically_not_lexically(self) -> None:
        releases = [release("v0.9.0"), release("v0.10.0"), release("v0.56.10"), release("v0.56.2")]
        assert stable_versions(releases) == ["v0.9.0", "v0.10.0", "v0.56.2", "v0.56.10"]

    def test_deduplicates(self) -> None:
        assert stable_versions([release("v0.56.2"), release("v0.56.2")]) == ["v0.56.2"]

    def test_missing_are_newer_only_ascending(self) -> None:
        stable = ["v0.55.4", "v0.55.5", "v0.56.0", "v0.56.1", "v0.56.2", "v0.57.0"]
        # v0.55.5 is a backport to an older line: not newer, not caught up.
        assert missing_versions("v0.56.1", stable) == ["v0.56.2", "v0.57.0"]

    def test_none_missing(self) -> None:
        assert missing_versions("v0.56.2", ["v0.56.1", "v0.56.2"]) == []

    def test_fetch_paginates_until_empty(self) -> None:
        pages = {1: [release("v0.56.2")] * 100, 2: [release("v0.56.1")], 3: []}
        urls: list[str] = []

        def fetch(url: str) -> Any:
            urls.append(url)
            return pages[int(url.rsplit("=", 1)[1])]

        assert len(fetch_releases(fetch=fetch)) == 101
        assert urls[0].startswith("https://api.github.com/repos/hyprwm/Hyprland/releases?")
        assert len(urls) == 3

    def test_fetch_rejects_error_payload(self) -> None:
        with pytest.raises(ReleaseError, match="unexpected releases response"):
            fetch_releases(fetch=lambda url: {"message": "API rate limit exceeded"})

    def test_fetch_bounded(self) -> None:
        with pytest.raises(ReleaseError, match="pages"):
            fetch_releases(fetch=lambda url: [release("v0.1.0")], max_pages=3)


# ---------------------------------------------------------------------------
# Version policy
# ---------------------------------------------------------------------------


class TestVersionPolicy:
    def test_patch_line_is_patch_release(self) -> None:
        assert next_library_version("0.6.2", "v0.55.3", ["v0.55.4"]) == "0.6.3"

    def test_minor_line_is_minor_release(self) -> None:
        assert next_library_version("0.6.3", "v0.55.4", ["v0.56.0"]) == "0.7.0"

    def test_carries_library_bugfix_release(self) -> None:
        # 0.7.1 was a library-only fix on top of Hyprland v0.56.1.
        assert next_library_version("0.7.1", "v0.56.1", ["v0.56.2"]) == "0.7.2"

    def test_several_patches_one_release(self) -> None:
        assert next_library_version("0.7.1", "v0.56.1", ["v0.56.2", "v0.56.3"]) == "0.7.2"

    def test_minor_anywhere_in_catch_up_wins(self) -> None:
        missing = ["v0.56.2", "v0.57.0", "v0.57.1"]
        assert next_library_version("0.7.1", "v0.56.1", missing) == "0.8.0"

    def test_upstream_major_is_minor_release(self) -> None:
        assert next_library_version("0.7.1", "v0.56.1", ["v1.0.0"]) == "0.8.0"

    def test_double_digit_patch(self) -> None:
        assert next_library_version("0.7.9", "v0.56.1", ["v0.56.2"]) == "0.7.10"

    def test_nothing_missing(self) -> None:
        with pytest.raises(ReleaseError):
            next_library_version("0.7.1", "v0.56.1", [])

    def test_existing_tag_refused(self) -> None:
        with pytest.raises(ReleaseError, match="already exists"):
            check_new_library_tag("0.7.1", ["v0.7.0", "v0.7.1"])

    def test_tag_newer_than_pyproject_refused(self) -> None:
        with pytest.raises(ReleaseError, match="not newer"):
            check_new_library_tag("0.7.2", ["v0.7.1", "v0.8.0"])

    def test_new_tag_ok(self) -> None:
        check_new_library_tag("0.7.2", ["v0.7.1", "v0.7.0", "not-a-version"])


class TestMakePlan:
    def test_catch_up_plan(self, tmp_path: Path) -> None:
        root = make_tree(tmp_path)
        releases = [release(t) for t in ("v0.57.0", "v0.56.2", "v0.56.1")]
        releases.append(release("v0.57.1", prerelease=True))
        plan = make_plan(root, BASE, releases, ["v0.7.1"])
        assert plan.missing == ["v0.56.2", "v0.57.0"]
        assert plan.library == "0.8.0"
        assert plan.target == "v0.57.0"
        assert plan.title == "Update schema for Hyprland v0.56.2–v0.57.0, release 0.8.0"

    def test_up_to_date_is_noop(self, tmp_path: Path) -> None:
        root = make_tree(tmp_path)
        plan = make_plan(root, BASE, [release("v0.56.1"), release("v0.56.2", draft=True)], [])
        assert plan.missing == []
        assert plan.library is None

    def test_duplicate_tag_stops_plan(self, tmp_path: Path) -> None:
        root = make_tree(tmp_path)
        with pytest.raises(ReleaseError, match="v0.7.2 already exists"):
            make_plan(root, BASE, [release("v0.56.2")], ["v0.7.1", "v0.7.2"])

    def test_round_trips_json(self) -> None:
        plan = make_plan_for(["v0.56.2"])
        assert Plan.from_json(plan.to_json()) == plan


# ---------------------------------------------------------------------------
# Diff and release notes
# ---------------------------------------------------------------------------


class TestDiff:
    def test_classifies_changes(self) -> None:
        old = [
            option("general:a"),
            option("general:gone"),
            option("decoration:shadow:color", type="color", default=-1),
        ]
        new = [
            option("general:a", default=1, description="new text"),
            option("decoration:shadow:color", type="gradient", default=""),
            option("misc:fresh", max=10),
        ]
        step = diff_step("v0.55.4", old, "v0.56.0", new)
        assert step.added == ["misc:fresh"]
        assert step.removed == ["general:gone"]
        assert step.changed == [
            ("general:a", [("default", 0, 1), ("description", "a option", "new text")]),
            ("decoration:shadow:color", [("type", "color", "gradient"), ("default", -1, "")]),
        ]
        assert (step.option_count, step.section_count) == (3, 3)
        assert not step.is_noop

    def test_identical_is_noop(self) -> None:
        opts = [option("general:a")]
        assert diff_step("v0.56.1", opts, "v0.56.2", opts).is_noop

    def test_drift_guard(self) -> None:
        old = [option(f"general:o{i}") for i in range(10)]
        step = diff_step("v1", old, "v2", old[:5])
        with pytest.raises(ReleaseError, match="parser drift"):
            check_drift(step, len(old))

    def test_drift_guard_allows_normal_removals(self) -> None:
        old = [option(f"general:o{i}") for i in range(10)]
        check_drift(diff_step("v1", old, "v2", old[:8]), len(old))

    def test_empty_parse_fails(self) -> None:
        with pytest.raises(ReleaseError, match="no options"):
            check_drift(StepDiff("v1", "v2", [], ["x"], [], 0, 0), 1)


class TestReleaseNotes:
    def steps(self) -> list[StepDiff]:
        old = [option("general:a"), option("general:b", type="bool", default=False)]
        new = [option("general:a"), option("general:b", type="bool", default=True)]
        new2 = [*new, option("misc:c", min=1)]
        return [
            diff_step("v0.56.1", old, "v0.56.2", old),
            diff_step("v0.56.2", old, "v0.57.0", new),
            diff_step("v0.57.0", new, "v0.57.1", new2),
        ]

    def test_entry(self) -> None:
        entry = render_changelog_entry("0.8.0", "2026-10-19", self.steps(), minor=True)
        assert entry == (
            "## [0.8.0] - 2026-10-19\n\n### Added\n\n"
            "- **Hyprland v0.57.1 schema** — 3 options across 2 sections; "
            "1 added, 0 removed, 0 changed\n"
            "  - Added: `misc:c`\n"
            "- **Hyprland v0.57.0 schema** — 2 options across 1 sections; "
            "0 added, 0 removed, 1 changed\n"
            "  - `general:b`: default `false` → `true`\n"
            "- **Hyprland v0.56.2 schema** — 2 options across 1 sections; no upstream option "
            "changes; the `v0.56.2 → v0.56.1` migration is a no-op\n"
        )

    def test_entry_is_deterministic(self) -> None:
        a = render_changelog_entry("0.8.0", "2026-10-19", self.steps(), minor=True)
        b = render_changelog_entry("0.8.0", "2026-10-19", self.steps(), minor=True)
        assert a == b

    def test_patch_entry_heading(self) -> None:
        entry = render_changelog_entry("0.7.2", "2026-10-19", self.steps()[:1], minor=False)
        assert entry.startswith("## [0.7.2] - 2026-10-19\n\n### Changed\n\n- ")

    def test_bound_added_and_dropped(self) -> None:
        step = diff_step("v1", [option("a:b", max=5)], "v2", [option("a:b", min=0)])
        assert step.changed == [("a:b", [("min", None, 0), ("max", 5, None)])]
        text = render_changelog_entry("0.7.2", "d", [step], minor=False)
        assert "`a:b`: min `0` added; max `5` dropped" in text

    def test_insert_and_extract(self) -> None:
        changelog = CHANGELOG
        entry = render_changelog_entry("0.7.2", "2026-10-19", self.steps()[:1], minor=False)
        updated = insert_changelog_entry(changelog, "0.7.2", entry)
        assert updated.index("## [0.7.2]") < updated.index("## [0.7.1]")
        assert updated.index("[0.7.2]: https://") < updated.index("[0.7.1]: https://")
        assert "releases/tag/v0.7.2\n" in updated
        assert changelog_section(updated, "0.7.2") == entry.split("\n", 2)[2].strip() + "\n"
        # Neighbouring sections are untouched.
        assert changelog_section(updated, "0.7.1") == changelog_section(changelog, "0.7.1")

    def test_insert_twice_refused(self) -> None:
        changelog = CHANGELOG
        with pytest.raises(ReleaseError, match="already has"):
            insert_changelog_entry(changelog, "0.7.1", "## [0.7.1] - x\n")

    def test_last_section_extracts(self) -> None:
        changelog = CHANGELOG
        assert changelog_section(changelog, "0.1.0").startswith("Initial release.")

    def test_missing_section(self) -> None:
        with pytest.raises(ReleaseError, match="no 9.9.9 section"):
            changelog_section(CHANGELOG, "9.9.9")

    def test_set_project_version(self) -> None:
        text = set_project_version(PYPROJECT, "0.7.2")
        assert '\nversion = "0.7.2"\n' in text
        with pytest.raises(ReleaseError):
            set_project_version("[project]\n", "0.7.2")

    def test_pr_body_and_marker(self) -> None:
        plan = make_plan_for(["v0.56.2"])
        entry = render_changelog_entry("0.7.2", "2026-10-19", self.steps()[:1], minor=False)
        body = render_pr_body(plan, entry)
        assert "## [0.7.2]" not in body
        assert "migration is a no-op" in body
        assert parse_marker(body) == {"target": "v0.56.2", "library": "0.7.2", "base": BASE}
        assert marker(plan) in body

    def test_trailers(self) -> None:
        plan = make_plan_for(["v0.56.2", "v0.57.0"], "0.8.0")
        assert parse_trailers(commit_message(plan)) == {
            "target": "v0.57.0",
            "library": "0.8.0",
            "base": BASE,
        }

    def test_no_marker(self) -> None:
        assert parse_marker(None) == {}
        assert parse_marker("hand-written PR") == {}


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


class FakeBump:
    """Stands in for subprocess: applies fake bumps to a tree and records calls."""

    def __init__(self, root: Path, schemas: dict[str, list[dict[str, Any]]]) -> None:
        self.root = root
        self.schemas = schemas
        self.calls: list[list[str]] = []
        self.status = ""

    def __call__(self, cmd: list[str], *, cwd: Path, check: bool = True) -> str:
        self.calls.append(cmd)
        if cmd[1:3] == ["generate_schema.py", "bump"]:
            version = cmd[3]
            data = self.root / "src" / "hyprland_schema" / "_data.py"
            data.write_text(f'HYPRLAND_VERSION = "{version}"\n')
            return ""
        if cmd[2:3] == ["dump-options"]:
            return json.dumps({v: self.schemas[v] for v in cmd[3:]})
        if cmd[:2] == ["git", "status"]:
            return self.status
        return ""


class TestRunUpdate:
    schemas = {
        "v0.56.1": [option("general:a")],
        "v0.56.2": [option("general:a")],
        "v0.57.0": [option("general:a"), option("misc:new")],
    }

    def test_bumps_each_version_in_order(self, tmp_path: Path) -> None:
        root = make_tree(tmp_path)
        fake = FakeBump(root, self.schemas)
        fake.status = (
            " M CHANGELOG.md\n M README.md\n M pyproject.toml\n M uv.lock\n"
            " M src/hyprland_schema/_data.py\n M src/hyprland_schema/_migrations/_registry.py\n"
            "?? src/hyprland_schema/_migrations/v0.57.0_to_v0.56.2.json\n"
        )
        plan = make_plan_for(["v0.56.2", "v0.57.0"], "0.8.0")
        body = run_update(plan, root, run=fake, date="2026-10-19")

        bumps = [c[3] for c in fake.calls if c[1:3] == ["generate_schema.py", "bump"]]
        assert bumps == ["v0.56.2", "v0.57.0"]
        assert all(c[0] == sys.executable for c in fake.calls if "bump" in c)
        dump = next(c for c in fake.calls if "dump-options" in c)
        assert dump[3:] == ["v0.56.1", "v0.56.2", "v0.57.0"]
        assert ["uv", "lock"] in fake.calls
        # dump-options runs after the last bump, so notes see the new package.
        assert fake.calls.index(dump) > max(i for i, c in enumerate(fake.calls) if "bump" in c)

        assert 'version = "0.8.0"' in (root / "pyproject.toml").read_text()
        changelog = (root / "CHANGELOG.md").read_text()
        section = changelog_section(changelog, "0.8.0")
        assert "- **Hyprland v0.57.0 schema** — 2 options across 2 sections; 1 added" in section
        assert "`v0.56.2 → v0.56.1` migration is a no-op" in section
        assert '# "v0.57.0"' in (root / "README.md").read_text()
        assert parse_marker(body)["target"] == "v0.57.0"

    def test_unexpected_paths_fail(self, tmp_path: Path) -> None:
        root = make_tree(tmp_path)
        fake = FakeBump(root, self.schemas)
        fake.status = " M src/hyprland_schema/_data.py\n M tests/test_schema.py\n"
        with pytest.raises(ReleaseError, match="tests/test_schema.py"):
            run_update(make_plan_for(["v0.56.2"]), root, run=fake, date="d")

    def test_stale_plan_refused(self, tmp_path: Path) -> None:
        root = make_tree(tmp_path, hyprland="v0.56.2")
        with pytest.raises(ReleaseError, match="does not match"):
            run_update(make_plan_for(["v0.56.2"]), root, run=FakeBump(root, {}), date="d")

    def test_empty_plan_refused(self, tmp_path: Path) -> None:
        root = make_tree(tmp_path)
        with pytest.raises(ReleaseError, match="nothing"):
            run_update(make_plan_for([], None), root, run=FakeBump(root, {}), date="d")

    def test_failed_bump_propagates(self, tmp_path: Path) -> None:
        root = make_tree(tmp_path)

        def run(cmd: list[str], *, cwd: Path, check: bool = True) -> str:
            raise ReleaseError("command failed (1): generate_schema.py bump v0.56.2")

        with pytest.raises(ReleaseError, match="bump"):
            run_update(make_plan_for(["v0.56.2"]), root, run=run, date="d")
        assert 'version = "0.7.1"' in (root / "pyproject.toml").read_text()

    def test_changed_paths(self) -> None:
        check_changed_paths(["uv.lock", "src/hyprland_schema/_migrations/v1_to_v0.json"])
        with pytest.raises(ReleaseError):
            check_changed_paths(["src/hyprland_schema/_parser.py"])


# ---------------------------------------------------------------------------
# Rolling PR
# ---------------------------------------------------------------------------


def state(**kw: Any) -> BranchState:
    defaults: dict[str, Any] = {
        "remote_sha": None,
        "trailers": {},
        "foreign_commits": False,
        "open_pr": None,
        "rejected_target": None,
    }
    return BranchState(**(defaults | kw))


class TestDecide:
    plan = make_plan_for(["v0.56.2"])
    same = {"target": "v0.56.2", "base": BASE}

    def test_new_branch(self) -> None:
        assert decide(self.plan, state()) == "push"

    def test_rerun_is_noop(self) -> None:
        s = state(remote_sha="c" * 40, trailers=self.same, open_pr=7)
        assert decide(self.plan, s) == "ensure-pr"

    def test_branch_without_pr_gets_pr(self) -> None:
        assert decide(self.plan, state(remote_sha="c" * 40, trailers=self.same)) == "ensure-pr"

    def test_main_moved_regenerates(self) -> None:
        s = state(remote_sha="c" * 40, trailers=self.same | {"base": "d" * 40}, open_pr=7)
        assert decide(self.plan, s) == "push"

    def test_new_upstream_release_regenerates(self) -> None:
        s = state(remote_sha="c" * 40, trailers=self.same | {"target": "v0.56.1"}, open_pr=7)
        assert decide(self.plan, s) == "push"

    def test_maintainer_commits_on_open_pr_kept(self) -> None:
        s = state(remote_sha="c" * 40, trailers=self.same, foreign_commits=True, open_pr=7)
        assert decide(self.plan, s) == "skip-maintainer"
        s = state(remote_sha="c" * 40, foreign_commits=True, open_pr=7)
        assert decide(self.plan, s) == "skip-maintainer"

    def test_stale_branch_without_pr_replaced(self) -> None:
        s = state(remote_sha="c" * 40, trailers=self.same, foreign_commits=True)
        assert decide(self.plan, s) == "push"

    def test_rejected_target_not_reproposed(self) -> None:
        assert decide(self.plan, state(rejected_target="v0.56.2")) == "skip-rejected"

    def test_newer_target_supersedes_rejection(self) -> None:
        assert decide(self.plan, state(rejected_target="v0.56.1")) == "push"


class FakeGit:
    """Answers the git/gh queries propose makes; records everything else."""

    def __init__(
        self,
        *,
        remote_sha: str | None = None,
        head_message: str = "",
        idents: str = "",
        open_prs: list[dict[str, Any]] | None = None,
        closed_prs: list[dict[str, Any]] | None = None,
        parent: str = BASE,
    ) -> None:
        self.remote_sha = remote_sha
        self.head_message = head_message
        self.idents = idents
        self.open_prs = open_prs or []
        self.closed_prs = closed_prs or []
        self.parent = parent
        self.calls: list[list[str]] = []

    def __call__(self, cmd: list[str], **_: Any) -> str:
        self.calls.append(cmd)
        if cmd[:2] == ["git", "rev-parse"]:
            return self.parent + "\n" if cmd[2].endswith("^") else "e" * 40 + "\n"
        if cmd[:2] == ["git", "ls-remote"]:
            return f"{self.remote_sha}\trefs/heads/{UPDATE_BRANCH}\n" if self.remote_sha else ""
        if cmd[:3] == ["git", "log", "-1"]:
            return self.head_message
        if cmd[:2] == ["git", "log"]:
            return self.idents
        if cmd[:3] == ["gh", "pr", "list"]:
            return json.dumps(self.open_prs if "open" in cmd else self.closed_prs)
        return ""

    def writes(self) -> list[list[str]]:
        mutating = (["gh", "pr", "create"], ["gh", "pr", "edit"], ["gh", "workflow", "run"])
        return [c for c in self.calls if c[:2] == ["git", "push"] or c[:3] in mutating]


BOT_IDENT = "github-actions[bot] <41898282+github-actions[bot]@users.noreply.github.com>"


def pr(number: int, body: str = "", merged: bool = False, login: str = "app/github-actions"):
    return {
        "number": number,
        "body": body,
        "closedAt": "2026-10-01T00:00:00Z",
        "mergedAt": "2026-10-01T00:00:00Z" if merged else None,
        "author": {"login": login},
    }


class TestPropose:
    plan = make_plan_for(["v0.56.2"])

    def run(self, fake: FakeGit, tmp_path: Path, dry_run: bool = False) -> str:
        return propose(
            self.plan, tmp_path / "b", tmp_path / "body.md", REPO, run=fake, dry_run=dry_run
        )

    def test_first_run_pushes_creates_pr_and_dispatches_ci(self, tmp_path: Path) -> None:
        fake = FakeGit()
        assert self.run(fake, tmp_path) == "push"
        push, create, ci = fake.writes()
        assert push[:3] == ["git", "push", f"--force-with-lease=refs/heads/{UPDATE_BRANCH}:"]
        assert push[-1] == f"{'e' * 40}:refs/heads/{UPDATE_BRANCH}"
        assert create[:3] == ["gh", "pr", "create"]
        assert ci == ["gh", "workflow", "run", "ci.yml", "--repo", REPO, "--ref", UPDATE_BRANCH]

    def test_rerun_does_nothing(self, tmp_path: Path) -> None:
        fake = FakeGit(
            remote_sha="c" * 40,
            head_message=commit_message(self.plan),
            idents=f"{BOT_IDENT}\n{BOT_IDENT}\n",
            open_prs=[pr(7, render_pr_body(self.plan, "## [0.7.2] - d\n\nnotes\n"))],
        )
        assert self.run(fake, tmp_path) == "ensure-pr"
        assert fake.writes() == []

    def test_refresh_uses_lease_on_observed_sha(self, tmp_path: Path) -> None:
        old_msg = commit_message(Plan("d" * 40, "v0.56.1", "0.7.1", ["v0.56.2"], "0.7.2"))
        fake = FakeGit(
            remote_sha="c" * 40,
            head_message=old_msg,
            idents=f"{BOT_IDENT}\n{BOT_IDENT}\n",
            open_prs=[pr(7)],
        )
        assert self.run(fake, tmp_path) == "push"
        writes = fake.writes()
        assert writes[0][2] == f"--force-with-lease=refs/heads/{UPDATE_BRANCH}:{'c' * 40}"
        assert writes[1][:4] == ["gh", "pr", "edit", "7"]
        assert writes[2][:3] == ["gh", "workflow", "run"]

    def test_maintainer_commits_not_overwritten(self, tmp_path: Path) -> None:
        fake = FakeGit(
            remote_sha="c" * 40,
            idents="\n".join(
                [BOT_IDENT, BOT_IDENT, "Ivo <ivo@example.com>", "GitHub <x@github.com>"]
            ),
            open_prs=[pr(7)],
        )
        assert self.run(fake, tmp_path) == "skip-maintainer"
        assert fake.writes() == []

    def test_rejected_not_reopened(self, tmp_path: Path) -> None:
        fake = FakeGit(closed_prs=[pr(6, marker(self.plan))])
        assert self.run(fake, tmp_path) == "skip-rejected"

    def test_merged_previous_pr_is_not_a_rejection(self, tmp_path: Path) -> None:
        fake = FakeGit(closed_prs=[pr(6, marker(self.plan), merged=True)])
        assert self.run(fake, tmp_path) == "push"

    def test_ignores_prs_from_other_authors(self, tmp_path: Path) -> None:
        fake = FakeGit(closed_prs=[pr(6, marker(self.plan), login="someone")])
        assert self.run(fake, tmp_path) == "push"

    def test_bundle_must_sit_on_plan_base(self, tmp_path: Path) -> None:
        with pytest.raises(ReleaseError, match="not based on"):
            self.run(FakeGit(parent="f" * 40), tmp_path)

    def test_dry_run_has_no_side_effects(self, tmp_path: Path) -> None:
        fake = FakeGit()
        assert self.run(fake, tmp_path, dry_run=True) == "push"
        assert fake.writes() == []


# ---------------------------------------------------------------------------
# Release guard
# ---------------------------------------------------------------------------


def merged_event(**overrides: Any) -> dict[str, Any]:
    pull = {
        "merged": True,
        "merge_commit_sha": MERGE,
        "base": {"ref": "main"},
        "head": {"ref": UPDATE_BRANCH, "repo": {"full_name": REPO}},
        "user": {"login": BOT_LOGIN},
    }
    return {"pull_request": pull | overrides}


class TestReleaseGuard:
    def tree(self, tmp_path: Path, library: str = "0.7.2") -> Path:
        root = make_tree(tmp_path, library=library)
        changelog = (root / "CHANGELOG.md").read_text()
        entry = f"## [{library}] - 2026-10-19\n\n### Changed\n\n- notes\n"
        (root / "CHANGELOG.md").write_text(insert_changelog_entry(changelog, library, entry))
        return root

    def test_creates_new_tag(self, tmp_path: Path) -> None:
        info = check_release(merged_event(), REPO, self.tree(tmp_path), {"v0.7.1": "1" * 40})
        assert (info.version, info.tag, info.sha, info.tag_exists) == (
            "0.7.2",
            "v0.7.2",
            MERGE,
            False,
        )

    def test_retry_accepts_tag_at_merge_sha(self, tmp_path: Path) -> None:
        tags = {"v0.7.1": "1" * 40, "v0.7.2": MERGE}
        assert check_release(merged_event(), REPO, self.tree(tmp_path), tags).tag_exists

    def test_tag_elsewhere_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ReleaseError, match="already exists at"):
            check_release(merged_event(), REPO, self.tree(tmp_path), {"v0.7.2": "9" * 40})

    def test_version_behind_tags_refused(self, tmp_path: Path) -> None:
        with pytest.raises(ReleaseError, match="not newer"):
            check_release(merged_event(), REPO, self.tree(tmp_path), {"v0.8.0": "9" * 40})

    @pytest.mark.parametrize(
        ("override", "reason"),
        [
            ({"merged": False}, "PR is merged"),
            ({"base": {"ref": "dev"}}, "base is main"),
            ({"head": {"ref": "feat/hyprland-release-automation", "repo": {"full_name": REPO}}},
             "head is bot/hyprland-update"),
            ({"head": {"ref": UPDATE_BRANCH, "repo": {"full_name": "fork/hyprland-schema"}}},
             "head repo"),
            ({"head": {"ref": UPDATE_BRANCH, "repo": None}}, "head repo"),
            ({"user": {"login": "BlueManCZ"}}, "opened by"),
            ({"merge_commit_sha": None}, "merge commit"),
        ],
    )  # fmt: skip
    def test_rejects_other_prs(self, tmp_path: Path, override: dict[str, Any], reason: str) -> None:
        with pytest.raises(ReleaseError, match=reason):
            check_release(merged_event(**override), REPO, self.tree(tmp_path), {})

    def test_no_event_payload(self, tmp_path: Path) -> None:
        with pytest.raises(ReleaseError, match="not a merged update PR"):
            check_release({}, REPO, self.tree(tmp_path), {})

    def test_missing_changelog_section(self, tmp_path: Path) -> None:
        root = make_tree(tmp_path, library="0.7.2")
        with pytest.raises(ReleaseError, match="no 0.7.2 section"):
            check_release(merged_event(), REPO, root, {})


# ---------------------------------------------------------------------------
# The real repository files keep the anchors the automation edits
# ---------------------------------------------------------------------------


class TestRepositoryFiles:
    def test_pyproject_version_line(self) -> None:
        text = set_project_version((ROOT / "pyproject.toml").read_text(), "99.0.0")
        assert '\nversion = "99.0.0"\n' in text

    def test_changelog_accepts_entry(self) -> None:
        changelog = (ROOT / "CHANGELOG.md").read_text()
        entry = "## [99.0.0] - 2099-01-01\n\n### Changed\n\n- x\n"
        updated = insert_changelog_entry(changelog, "99.0.0", entry)
        assert changelog_section(updated, "99.0.0") == "### Changed\n\n- x\n"
        assert "[99.0.0]: https://github.com/BlueManCZ/hyprland-schema/releases/tag/v99.0.0" in (
            updated
        )

    def test_readme_version_example(self) -> None:
        assert _README_VERSION.search((ROOT / "README.md").read_text())
