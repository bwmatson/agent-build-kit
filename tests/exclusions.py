"""The table of what this repository must not contain, and the one read it is checked on.

An `Entry` says what is forbidden (a predicate over a line, or a check over the whole checkout),
where it is looked for (folders, root files, suffixes, whether the specification folder is read),
what is exempt and why, and why the entry exists. `tests/test_exclusions.py` runs each entry over
the repository and over a temporary tree, from the entry's own examples. A new rule is a new entry.

The table is term-free by design: the words that would identify an installation never appear here,
only the shapes of a leak. The term-based half is `abk scrub-check`.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from agent_build_kit import skills
from agent_build_kit.model import Frozen
from tests.factories import git, init_repo
from tests.installation_leaks import (
    ABSOLUTE_HOME_PATH,
    ANECDOTE,
    DATED_ANECDOTE,
    ENV_ALLOWED,
    ENV_LITERAL,
    HOME_PATH,
    HOME_PRODUCT_DIR,
    NOREPLY,
    ROOT_FILES,
    SCANNED,
    SELF,
    TEXT,
    foreign_azure_orgs,
    foreign_slug_owners,
    in_specs_folder,
    overlay_leaks,
    repo_path_leaks,
)
from tests.tracked_files import (
    ROOT,
    PlanningDirs,
    guarded_files,
    lines_of,
    planning_dirs,
    test_tree_folders,
)

OVERLAY = "abk.local.yaml"
HOME_LINE = "see /home/someone/work for the checkout\n"
PACKAGE = Path(skills.SKILLS_DIR).parent.relative_to(ROOT).as_posix()
SHIPPED = tuple(f"{PACKAGE}/{name}" for name in ("skills", "templates", "recommendations"))
GUIDE = "docs/claude-code-second-account.md"
SPECIFICATION_FILE = "openspec/specs/x/spec.md"


class Case(Frozen):
    """A file written into a temporary tree. `line` is the one line that has a finding (none when
    the findings are about a file, not a line); `in_report` and `not_in_report` are text the
    findings must and must not hold. A `state` other than `none` makes the tree a git repository."""

    path: str
    text: str
    line: int | None = 1
    state: Literal["none", "repo", "ignored", "committed"] = "none"
    in_report: tuple[str, ...] = ()
    not_in_report: tuple[str, ...] = ()


class Exemption(Frozen):
    """A path an entry does not read: by file name or by path prefix, with the reason, and an
    example path that the exemption covers."""

    path: str
    reason: str
    names: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()

    def covers(self, relative: str) -> bool:
        return Path(relative).name in self.names or relative.startswith(self.prefixes)


class Entry(Frozen):
    """One forbidden thing. `found` is a predicate over a line, `in_specs` the rule for a line of
    the specification folder where it differs, and `check` a finding about the whole checkout, for
    what is no line of a file. `offends` are examples that must be reported and `passes` examples
    that must not."""

    name: str
    reason: str
    offends: tuple[Case, ...]
    passes: tuple[Case, ...] = ()
    found: Callable[[str], object] | None = None
    in_specs: Callable[[str], object] | None = None
    check: Callable[[Path], list[str]] | None = None
    under: tuple[str, ...] = SCANNED
    names: tuple[str, ...] = (*ROOT_FILES, "AGENTS.md")
    suffixes: frozenset[str] | None = frozenset(TEXT)
    specs: bool = True
    exemptions: tuple[Exemption, ...] = ()


SPELLING = tuple(
    Exemption(
        path=f"tests/{name}",
        names=(name,),
        reason="spells the patterns, or fixtures of what they catch, as text",
    )
    for name in sorted(SELF)
)
GENERATED = Exemption(
    path="web/package-lock.json",
    names=("package-lock.json",),
    reason="a generated lock file holds package addresses, not the repository's own text",
)
ENV_EXEMPT = (
    *(
        Exemption(
            path=f"src/agent_build_kit/{name}",
            names=(name,),
            reason="the settings layer, or the one module that reads a setting the layer cannot",
        )
        for name in sorted(ENV_ALLOWED)
    ),
    Exemption(
        path="tests/test_x.py",
        prefixes=tuple(f"{folder}/" for folder in test_tree_folders()),
        reason="a test sets the environment it reads",
    ),
)
DATED_EXEMPT = (
    Exemption(
        path="CHANGELOG.md",
        names=("CHANGELOG.md",),
        reason="a changelog entry is dated on purpose",
    ),
    Exemption(
        path="docs/reports/20260101-health.md",
        prefixes=("docs/reports/",),
        reason="a track's report is a dated record",
    ),
)

ENTRIES: tuple[Entry, ...] = (
    Entry(
        name="home-product-directory",
        reason="a product's config directory under the home directory names an installation",
        found=HOME_PRODUCT_DIR.search,
        offends=(Case(path="src/x.py", text='cfg = Path.home() / ".someproduct"\n'),),
        passes=(Case(path="src/x.py", text='cfg = Path.home() / ".claude"\n'),),
        exemptions=(*SPELLING, GENERATED),
    ),
    Entry(
        name="home-path",
        reason="a home-directory path names a user's machine; a tilde-relative path in the "
        "specification folder names no user, so only an absolute one is a hit there",
        found=HOME_PATH.search,
        in_specs=ABSOLUTE_HOME_PATH.search,
        offends=(
            Case(path="docs/x.md", text=HOME_LINE),
            Case(
                path="openspec/changes/feature/specs/x/spec.md",
                text="# Spec\n\n" + HOME_LINE,
                line=3,
            ),
            Case(path=SPECIFICATION_FILE, text="# Spec\n/home/someone/app\n", line=2),
            Case(path="docs/x.md", text="path: ~/work/app\n"),
            Case(path="runs/units.json", text='{"units": [\n"/home/someone/work"\n]}\n', line=2),
        ),
        passes=(
            Case(path=SPECIFICATION_FILE, text="path: ~/work/app\n"),
            Case(path="runs/unit-logs/feature-1.json", text=HOME_LINE),
            Case(path="runs/ledger.json", text=HOME_LINE),
            Case(path="README.md", text="A framework.\n"),
        ),
        exemptions=(*SPELLING, GENERATED),
    ),
    Entry(
        name="github-slug-outside-the-fixture-and-upstream-owners",
        reason="an address names an owner; only a fixture's and an upstream project's may appear",
        found=lambda line: bool(foreign_slug_owners(line)),
        offends=(
            Case(
                path="abk.yaml",
                text="repos:\n  app:\n    path: .\n    url: https://github.com/contoso/app\n",
                line=4,
            ),
            Case(
                path="abk.yaml",
                text="repos:\n  app:\n    path: .\n"
                "    url: https://api.github.com/repos/acme-corp/x/issues\n",
                line=4,
            ),
        ),
        passes=(
            Case(
                path="abk.yaml",
                text="repos:\n  app:\n    path: .\n"
                "    url: https://api.github.com/repos/example/app/issues\n"
                "    docs: https://docs.github.com/en/rest/issues/issues\n",
            ),
        ),
        exemptions=(*SPELLING, GENERATED),
    ),
    Entry(
        name="azure-organisation-outside-the-fixture",
        reason="an Azure DevOps address names an organisation; only a fixture's may appear",
        found=lambda line: bool(foreign_azure_orgs(line)),
        offends=(
            Case(path="docs/x.md", text="https://dev.azure.com/contoso-real/Project/_git/Repo\n"),
            Case(path="docs/x.md", text="git@ssh.dev.azure.com:v3/contoso-real/Project/Repo\n"),
            Case(path="docs/x.md", text="https://acme@dev.azure.com/contoso-real/Project\n"),
        ),
        passes=(
            Case(path="docs/x.md", text="https://dev.azure.com/example/Project/_git/Repo\n"),
            Case(path="docs/x.md", text="git@ssh.dev.azure.com:v3/acme/Project/Repo\n"),
        ),
        exemptions=(*SPELLING, GENERATED),
    ),
    Entry(
        name="personal-noreply-address",
        reason="a noreply address carries a person's account number and name",
        found=NOREPLY.search,
        offends=(Case(path="docs/x.md", text="12345+someone@users.noreply.github.com\n"),),
        exemptions=(*SPELLING, GENERATED),
    ),
    Entry(
        name="issue-or-pull-request-anecdote",
        reason="a repository name, a hash sign and a number is a story about one installation",
        found=ANECDOTE.search,
        offends=(Case(path="docs/x.md", text="fixed in contoso#15\n"),),
        passes=(Case(path="docs/x.md", text="see example/app#15\n"),),
        exemptions=(*SPELLING, GENERATED),
    ),
    Entry(
        name="dated-anecdote",
        reason="a date beside a verb of what was decided or observed is a story about one "
        "installation",
        found=DATED_ANECDOTE.search,
        offends=(Case(path="docs/x.md", text="decided on 2026-01-02 to wait\n"),),
        exemptions=(*SPELLING, GENERATED, *DATED_EXEMPT),
    ),
    Entry(
        name="environment-read-by-literal-name",
        reason="the environment is read through the settings layer, so a setting has one home",
        found=ENV_LITERAL.search,
        offends=(Case(path="src/x.py", text='value = os.environ["SOME_KEY"]\n'),),
        exemptions=(*SPELLING, GENERATED, *ENV_EXEMPT),
    ),
    Entry(
        name="configuration-names-a-repository-path-outside-the-checkout",
        reason="a tracked configuration that leaves the checkout names a machine's layout",
        check=repo_path_leaks,
        offends=tuple(
            Case(
                path="abk.yaml",
                text=f"repos:\n  platform:\n    path: .\n  app:\n    path: {path}\n"
                "    slug: example/app\n",
                line=None,
                in_report=("repos.app.path",),
                not_in_report=("sibling-x",),
            )
            for path in ("../sibling-x", "/srv/sibling-x", "~/sibling-x")
        ),
        passes=(
            Case(path="abk.yaml", text="repos:\n  app:\n"),
            Case(path="abk.yaml", text="repos: []\n"),
            Case(path="abk.yaml", text="repos:\n  app: .\n"),
            Case(path="abk.yaml", text="repos:\n  app:\n    path: .\n    slug: example/app\n"),
            Case(
                path="abk.yaml",
                text="repos:\n  app:\n    path: vendor/sub\n    slug: example/app\n",
            ),
        ),
    ),
    Entry(
        name="tracked-or-unignored-overlay",
        reason="the local overlay holds one machine's settings, so it is ignored and untracked",
        check=overlay_leaks,
        offends=(
            Case(
                path=OVERLAY,
                text="verify:\n  env:\n    HOME_DIR: /home/someone/work\nrepos:\n  other:\n"
                "    path: ../sibling-x\n",
                line=3,
                state="committed",
                in_report=("tracked", "repos.other.path"),
                not_in_report=("sibling-x",),
            ),
            Case(
                path=OVERLAY,
                text="verify:\n  env: {}\n",
                line=None,
                state="repo",
                in_report=("not ignored",),
                not_in_report=("tracked by git",),
            ),
            Case(
                path=OVERLAY,
                text="verify:\n  env: {}\n",
                line=None,
                in_report=("not ignored",),
                not_in_report=("tracked by git",),
            ),
        ),
        passes=(
            Case(
                path=OVERLAY,
                text="verify:\n  env:\n    HOME_DIR: /home/someone/work\n",
                state="ignored",
            ),
            Case(path="README.md", text="A framework.\n", state="repo"),
        ),
    ),
    Entry(
        name="shipped-text-names-a-home-path",
        reason="a shipped skill, template or seed is read by every installation",
        found=re.compile(r"/home/").search,
        under=SHIPPED,
        names=(),
        suffixes=None,
        specs=False,
        offends=(Case(path=f"{SHIPPED[0]}/x/SKILL.md", text="see /home/someone\n"),),
    ),
    Entry(
        name="shipped-text-names-a-tilde-path",
        reason="a shipped skill, template or seed is read by every installation",
        found=re.compile("~" + "/").search,
        under=SHIPPED,
        names=(),
        suffixes=None,
        specs=False,
        offends=(Case(path=f"{SHIPPED[1]}/x.md", text="in ~/work\n"),),
    ),
    Entry(
        name="shipped-text-names-a-pull-request",
        reason="a shipped skill, template or seed is read by every installation",
        found=re.compile(r"\b[\w.-]+/[\w.-]+#\d+").search,
        under=SHIPPED,
        names=(),
        suffixes=None,
        specs=False,
        offends=(Case(path=f"{SHIPPED[2]}/x.md", text="fixed in owner/name#12\n"),),
    ),
    Entry(
        name="guide-holds-a-real-home-path",
        reason="a guide shows paths as placeholders, never one user's, on any system",
        found=re.compile(r"/(?:home|Users)/\w+").search,
        under=("docs",),
        names=(),
        suffixes=frozenset({".md"}),
        specs=False,
        offends=(
            Case(path=GUIDE, text="cp key /Users/someone/.config\n"),
            Case(path=GUIDE, text="cp key /home/someone/.config\n"),
        ),
        passes=(Case(path=GUIDE, text="cp key $HOME/.config\n"),),
    ),
)


def build(root: Path, case: Case) -> None:
    """Write `case` into `root`, as a git repository in the state the case names."""
    if case.state != "none":
        init_repo(root)
        (root / ".gitignore").write_text(f"{case.path}\n" if case.state == "ignored" else "")
        git(root, "add", ".gitignore")
        git(root, "commit", "-qm", "base")
    path = root / case.path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(case.text)
    if case.state == "committed":
        git(root, "add", case.path)
        git(root, "commit", "-qm", "file")


class Reading:
    """The files the entries read, listed and read once however many entries run: each distinct
    scope is listed once, each file's lines are read once, and the checkout's configuration is
    parsed once."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.dirs: PlanningDirs = planning_dirs(root)
        self._listed: dict[tuple, list[Path]] = {}
        self._lines: dict[Path, list[str]] = {}

    def files(self, entry: Entry) -> list[Path]:
        scope = (entry.under, entry.names, entry.suffixes, entry.specs)
        if scope not in self._listed:
            self._listed[scope] = guarded_files(
                self.root,
                under=entry.under,
                names=entry.names,
                suffixes=entry.suffixes,
                specs=entry.specs,
                dirs=self.dirs,
            )
        return self._listed[scope]

    def lines(self, path: Path) -> list[str]:
        if path not in self._lines:
            self._lines[path] = lines_of(path, errors="replace")
        return self._lines[path]

    def findings(self, entry: Entry) -> list[str]:
        """What the entry forbids and `root` holds, as `path:line: clipped line` (a check's own
        wording for a finding about the checkout)."""
        if entry.check is not None:
            return entry.check(self.root)
        assert entry.found is not None, entry.name
        found = []
        for path in self.files(entry):
            relative = path.relative_to(self.root)
            if any(exempt.covers(relative.as_posix()) for exempt in entry.exemptions):
                continue
            rule = entry.found
            if entry.in_specs and in_specs_folder(self.root, path, self.dirs):
                rule = entry.in_specs
            found += [
                f"{relative.as_posix()}:{number}: {line.strip()[:100]}"
                for number, line in enumerate(self.lines(path), start=1)
                if rule(line)
            ]
        return found
