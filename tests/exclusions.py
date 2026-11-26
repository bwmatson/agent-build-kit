"""The table of what this repository must not contain, and the one read it is checked on.

An `Entry` says what is forbidden (a predicate over a line, or a check over the whole checkout),
where it is looked for (folders, root files, suffixes, whether the specification folder is read),
what is exempt and why, and why the entry exists. `tests/test_exclusions.py` runs each entry over
the repository and over a temporary tree, from the entry's own examples. A new rule is a new entry.

The table is term-free by design: the words that would identify an installation never appear here,
only the shapes of a leak. The term-based half is `abk scrub-check`.
"""

from __future__ import annotations

import ast
import re
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Literal

from agent_build_kit import profiles, runtimes, skills
from agent_build_kit.cli.doctor import OLD_E2E_MARKER
from agent_build_kit.config import RepoConfig
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import agent_commands
from agent_build_kit.pipeline.changelog_convention import changelog_convention
from agent_build_kit.pipeline.reuse_guidance import reuse_guidance
from agent_build_kit.pipeline.scratch import output_convention
from agent_build_kit.pipeline.stack_runner import TESTS_PROMPT
from agent_build_kit.pipeline.wiring import REVIEW_PROMPT
from agent_build_kit.runtimes import known_agents, providers
from tests.factories import git, init_repo, scratch_app
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
    file_hits,
    foreign_azure_orgs,
    foreign_slug_owners,
    in_specs_folder,
    overlay_leaks,
    repo_path_leaks,
)
from tests.old_merge_rule import statements
from tests.prompt_text import flat
from tests.serial_marker import MARKER
from tests.tracked_files import (
    ROOT,
    PlanningDirs,
    guarded_files,
    lines_of,
    planning_dirs,
    source_tree_folders,
    test_tree_folders,
    tracked,
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
    siblings: tuple[tuple[str, str], ...] = ()


class Exemption(Frozen):
    """A path an entry does not read: by file name, by the start of a file name, by path prefix or
    as the track-report folder, with the reason, and an example path that the exemption covers. A
    `stale` exemption is a listing that may only shrink: it is reported when it covers no file the
    entry finds something in."""

    path: str
    reason: str
    names: tuple[str, ...] = ()
    name_starts: tuple[str, ...] = ()
    prefixes: tuple[str, ...] = ()
    reports: bool = False
    stale: bool = False

    def covers(self, relative: str, reports_dir: str = "docs/reports") -> bool:
        return (
            Path(relative).name in self.names
            or Path(relative).name.startswith(self.name_starts)
            or relative.startswith(self.prefixes)
            or (self.reports and relative.startswith(reports_dir.rstrip("/") + "/"))
        )


class Entry(Frozen):
    """One forbidden thing. `found` is a predicate over a line (over a paragraph when
    `by_paragraph`), `in_specs` the rule for a line of the specification folder where it differs,
    `named` a predicate over a file's name, and `check` a finding about the whole checkout, for
    what is no line of a file. `texts` makes the entry one over named texts the product returns
    (a prompt, a skill section, a generated file) and over no file of the repository: `found` is
    applied to each line of each text, and an empty text is a finding. `root_suffixes` adds the
    root files with those suffixes and `where` keeps the files whose path it accepts. `offends`
    are examples that must be reported and `passes` examples that must not."""

    name: str
    reason: str
    offends: tuple[Case, ...]
    passes: tuple[Case, ...] = ()
    found: Callable[[str], object] | None = None
    in_specs: Callable[[str], object] | None = None
    named: Callable[[str], object] | None = None
    check: Callable[[Path], list[str]] | None = None
    texts: Callable[[], dict[str, str]] | None = None
    by_paragraph: bool = False
    under: tuple[str, ...] = SCANNED
    names: tuple[str, ...] = (*ROOT_FILES, "AGENTS.md")
    root_suffixes: frozenset[str] = frozenset()
    suffixes: frozenset[str] | None = frozenset(TEXT)
    where: Callable[[str], bool] | None = None
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


def exempt_files(reason: str, *paths: str) -> tuple[Exemption, ...]:
    """One exemption for each file path, by its file name."""
    return tuple(Exemption(path=p, names=(Path(p).name,), reason=reason) for p in paths)


def exempt_paths(reason: str, *paths: str) -> tuple[Exemption, ...]:
    """One exemption for each file, by its path from the root."""
    return tuple(Exemption(path=p, prefixes=(p,), reason=reason) for p in paths)


CHANGELOG = exempt_files("the changelog keeps the history of released names", "CHANGELOG.md")

# The package managers, manifests and lock files framework source does not name, as a whole word
# and not as part of a hyphenated name. A new ecosystem's manager is one line.
TOKENS: tuple[str, ...] = (
    "uv",
    "pip",
    "poetry",
    "npm",
    "npx",
    "pnpm",
    "yarn",
    "cargo",
    "uv.lock",
    "pyproject.toml",
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "poetry.lock",
    "Cargo.lock",
    "requirements.txt",
)
ECOSYSTEM = re.compile("|".join(rf"(?<![\w.-]){re.escape(token)}(?![\w-])" for token in TOKENS))
TREES = tuple(source_tree_folders())
# Files that name an ecosystem today and should not, relative to a source tree. It may only
# shrink: a file leaves it when its names are removed, and nothing is added.
ALLOWLIST = {
    "cli/doctor.py": "checks `uv run` hook entries against pyproject dependency groups; "
    "belongs behind a profile hook for repository health checks",
    "tracks/runner.py": "the tracks' tool allowlist names `uv run`; belongs to the "
    "profile's allowed tools",
}
# The framework's own tooling, fixed: it is itself started, built and shipped with tools, and
# calls the OpenSpec CLI through one.
OWN_TOOLING = {
    "openspec.py": "the OpenSpec CLI is run through npx",
    "serve/server.py": "the web UI is built with npm",
    "settings.py": "comments on the OpenSpec CLI pin run through npx",
    "config.py": "the openspec.command comment names npx",
    "timers.py": "uv starts a tick, so its availability is checked",
}


def in_trees(*relative: str) -> tuple[str, ...]:
    """Each path, relative to a source tree, as it is named from the root of each tree."""
    return tuple(f"{tree}/{name}" for tree in TREES for name in relative)


ECOSYSTEM_EXEMPT = (
    Exemption(
        path=f"{TREES[0]}/profiles/node.py",
        prefixes=in_trees("profiles/", "init/"),
        reason="toolchain profiles and init detectors are where an ecosystem is named",
    ),
    *(
        Exemption(
            path=f"{TREES[0]}/{name}",
            prefixes=in_trees(name),
            reason=f"{reason} (an allowlisted file, which may only shrink)",
            stale=True,
        )
        for name, reason in ALLOWLIST.items()
    ),
    *(
        Exemption(
            path=f"{TREES[0]}/{name}",
            prefixes=in_trees(name),
            reason=f"the framework's own tooling: {reason}",
            stale=True,
        )
        for name, reason in OWN_TOOLING.items()
    ),
)

# Built in parts so this file carries no old spelling for the entries to find.
TIER = "ti" + "er"
OLD_KIND = re.compile(TIER + r"[-_ ]?([12]|one|two)", re.IGNORECASE)
OLD_GATE = f"{TIER}2_gate"
TOOL_MODULE = "rename_" + "test_kinds"
KIND_UNDER = ("src", "packages", "tests", "web/src", "docs", "scripts", ".github")
KIND_EXEMPT = (
    *exempt_files(
        "writes an old spelling on purpose: the table of them and the tests of it",
        "src/agent_build_kit/compat_names.py",
        "tests/test_compat_names.py",
        "tests/config/test_test_kind_settings_aliases.py",
    ),
    *exempt_files(
        "explains the rename, or cites the old names and earlier changes by their fixed names",
        "docs/designs/agent-efficient-coding-philosophy.md",
        "docs/designs/risk-tiered-review-design.md",
        "docs/runbooks/migrate-to-risk-tiered-review.md",
        "docs/runbooks/hold-a-e2e-split.md",
    ),
    *CHANGELOG,
    Exemption(
        path="tests/config/test_config_migrate_test_kind_keys_x.py",
        name_starts=("test_config_migrate_test_kind_keys",),
        reason="the tests of the settings migration write the old spellings on purpose",
    ),
    Exemption(
        path="docs/reports/20260101-000000-app-health.md",
        reports=True,
        reason="a track's report quotes what it saw, unit ids included",
    ),
)
REPORTS_ELSEWHERE = (("abk.yaml", "planning:\n  reports_dir: docs/track-runs\n"),)

OLD_STEMS = ("test_" + "acp_build_unit", "test_graph_" + "acp_unit")
SERIAL = re.compile(rf"\b{MARKER}\b(?! reruns?\b)")
# The suffixes of a configuration file at the root of a repository (a runner's or a package's).
CONFIG_SUFFIXES = frozenset(
    {".toml", ".ini", ".cfg", ".json", ".yaml", ".yml", ".js", ".mjs", ".cjs", ".ts", ".mts"}
)
OLD_RUNTIME_LISTS = ("runtimes_blocked", "runtimes_allowed", TIER + "2_runtimes")
OLD_LIMITS = re.compile(r"runtimes\.[\w<>]+\.(accounts\.[\w<>]+\.)?limits\b")
OLD_LIMITS_LINE = re.compile(r"^\s*limits:")
RENAME_WORDS = re.compile(r"renamed|deprecated|old name|old spelling", re.IGNORECASE)
REMOVED_KEYS = re.compile(r"review\.enabled|max_unit_lines")
HISTORY = (
    "docs/designs/agent-efficient-coding-philosophy.md",
    "docs/designs/risk-tiered-review-design.md",
)
RUNBOOK = "docs/runbooks/migrate-to-risk-tiered-review.md"
SKILL_FILE = re.compile(rf"{re.escape(SHIPPED[0])}/[^/]+/SKILL\.md")


def a_top_document(relative: str) -> bool:
    """The README, a document directly in `docs/` or a skill's `SKILL.md`: not the designs, the
    runbooks or the reports below `docs/`."""
    return bool(
        re.fullmatch(r"docs/[^/]+\.md|README\.md", relative) or SKILL_FILE.fullmatch(relative)
    )


def shows_old_limits(paragraph: str) -> bool:
    """Whether a paragraph shows the old `limits` spelling as the current one: it names the old
    path, unless it explains the rename, or it has a line that is the old key."""
    text = flat(paragraph)
    explains = RENAME_WORDS.search(text) and "usage_limits" in text
    return bool(
        (OLD_LIMITS.search(text) and not explains)
        or any(OLD_LIMITS_LINE.match(line) for line in paragraph.splitlines())
    )


# The e2e-test mechanism: its modules, and the classes of larger modules it is scanned for alone.
E2E_MODULES = (
    "pipeline/e2e.py",
    "pipeline/e2e_exclusive.py",
    "pipeline/e2e_holds.py",
    "pipeline/e2e_schedule.py",
    "pipeline/e2e_times.py",
    "pipeline/untouched_failures.py",
    "cli/e2e_cmd.py",
    "config_text_edit.py",
)
E2E_CLASSES = (
    ("profiles/base.py", "ToolchainProfile"),
    ("profiles/base.py", "AppliesE2eSelection"),
    ("profiles/base.py", "ListsRegisteredSelectors"),
    ("pipeline/wiring.py", "E2eSession"),
)
# A name from the standard library that merely begins `runtime_`. The provider table's own module
# is the one place a provider is named; it is no module of the mechanism, so it is never read.
STDLIB = {"runtime_checkable"}


def words(node: ast.AST) -> Iterator[tuple[int, str]]:
    """The strings and the names of a syntax tree, with their lines; comments are no syntax."""
    for child in ast.walk(node):
        line = getattr(child, "lineno", 0)
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            yield line, child.value
        elif isinstance(child, ast.Name):
            yield line, child.id
        elif isinstance(child, ast.Attribute):
            yield line, child.attr
        elif isinstance(child, ast.arg):
            yield line, child.arg
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield line, child.name
        elif isinstance(child, ast.alias):
            yield line, child.asname or child.name


def e2e_names(root: Path) -> list[str]:
    """Each runtime, protocol runtime, `runtime_` name or provider named in a string, an
    identifier or a docstring of the e2e-test mechanism, as `path:line: 'name'`. A module of the
    mechanism that `root` does not hold is not read."""
    names = {*runtimes.names(), known_agents.RUNTIME_NAME, *providers.names()}
    trees = [root / "src" / "agent_build_kit", *sorted(root.glob("packages/*/src/agent_build_kit"))]
    found: list[str] = []

    def hits(path: Path, node: ast.AST, note: str = "") -> None:
        for line, text in words(node):
            cleaned = "".join(ch if ch.isalnum() or ch == "_" else " " for ch in text)
            found.extend(
                f"{path.relative_to(root).as_posix()}:{line}: {token!r}{note}"
                for token in sorted(set(cleaned.split()))
                if (token in names or token.startswith("runtime_")) and token not in STDLIB
            )

    for relative, wanted in [(module, "") for module in E2E_MODULES] + list(E2E_CLASSES):
        path = next((tree / relative for tree in trees if (tree / relative).is_file()), None)
        if path is None:
            continue
        module = ast.parse(path.read_text(encoding="utf-8"))
        if not wanted:
            hits(path, module)
            continue
        classes = [n for n in ast.walk(module) if isinstance(n, ast.ClassDef) and n.name == wanted]
        if not classes:
            found.append(f"{path.relative_to(root).as_posix()}: has no class {wanted}")
            continue
        # The decorators are left out: `@runtime_checkable` is a typing name, not a runtime.
        hits(path, ast.Module(body=classes[0].body, type_ignores=[]), f" (in {wanted})")
    return found


E2E_MODULE = f"{TREES[0]}/{E2E_MODULES[0]}"
E2E_CLASS_MODULE = f"{TREES[0]}/{E2E_CLASSES[0][0]}"
RUNTIME = known_agents.RUNTIME_NAME
PROVIDER = providers.names()[0]


def profile_module(profile: str = "    pass\n") -> str:
    """A `profiles/base.py` holding the three classes the mechanism is scanned for there."""
    return (
        f"class ToolchainProfile:\n{profile}\n\nclass AppliesE2eSelection:\n    pass\n\n\n"
        "class ListsRegisteredSelectors:\n    pass\n"
    )


STATE_RUNBOOK = "docs/runbooks/move-agent-build-kit-planning.md"
COMMITTED = re.compile(
    r"units\.json[^\n]*\bCommit it\b"
    r"|units\.json[^.|\n]{0,60}\b(?:is|are|stays?) (?:committed|tracked)"
)
REUSE_HEADING = "Reuse before you write"
BYPASS = "bypasses no limit"


def a_skill_file(relative: str) -> bool:
    return bool(SKILL_FILE.fullmatch(relative))


def a_state_document(relative: str) -> bool:
    """A document directly in `docs/`, a skill's `SKILL.md`, the one runbook that moves the
    store and the changelog."""
    return bool(
        re.fullmatch(r"docs/[^/]+\.md", relative)
        or SKILL_FILE.fullmatch(relative)
        or relative in (STATE_RUNBOOK, "CHANGELOG.md")
    )


# What the packaged prompts, the authoring skill and the generated files must not name: an
# installation, a language, a tool or a path. Each is a named text the product returns.
HASH_NUMBER = re.compile(r"\w+#\d+")
HOME_FRAGMENT = "/home/"
DETERMINISM_TOOLS = (
    "python",
    "pytest",
    "time.sleep",
    "asyncio",
    "unittest",
    "threading",
    "tmp_path",
    "jest",
)
REUSE_TOOLS = ("pytest", "uv ", "npm", "ruff", "cargo", "pip", "jest", "vitest")
STUB_TOOLS = ("pytest", "npm", "ruff", "cargo", "jest", "vitest")
KIT_NAMES = re.compile(r"\b(example|agent[-_]build[-_]kit|abk)\b", re.IGNORECASE)
SOURCE_PATH = re.compile(r"\b(src|tests)/|\.py\b|\.ts\b|\.md\b")
STUB_PATH = re.compile(r"\b(src|tests)/|\.py\b|\.ts\b")
AUTHORING_LEAK = re.compile(r"\w+#\d+|/home/|github\.com")
AUTHORING_FILE = re.compile(r"\.(py|ts|tsx|js|go|rs|java|rb|md|toml|lock)\b")
AUTHORING_KIT = re.compile(r"\b(agent[-_]build[-_]kit|abk)\b", re.IGNORECASE)
AUTHORING_DECLARATION = re.compile(r"\b(def|function|fn|func|class|const|let|var|import)\s")
AUTHORING_CALL = re.compile(r"\w+\([^)]*\)\s*(->|=>|\{|:)")
AUTHORING_HEADING = "## Describe behaviour, not names"
BARE_PROGRAM = re.compile(r"(?<![\w-])(?:python -m pytest|pytest|ruff)\b")
TOOL_WORDS = ["pytest", "vitest", "uv", "npx", "npm", "pre-commit"]
COMPOSER_WORD = re.compile(
    "|".join(rf"(?<![\w-]){re.escape(word)}(?![\w-])" for word in [*profiles.names(), *TOOL_WORDS])
)
STUB_START = "Stubs contain no logic."
STUB_END = "Where a test needs a stand-in"


def mentions(*words: str) -> Callable[[str], bool]:
    """A rule that is met by a line holding any of the words, as written."""
    return lambda line: any(word in line for word in words)


def matches(*patterns: re.Pattern[str], words: tuple[str, ...] = ()) -> Callable[[str], bool]:
    """A rule that is met by a line any of the patterns finds or that holds any of the words."""
    return lambda line: (
        any(pattern.search(line) for pattern in patterns) or any(word in line for word in words)
    )


def squeezed(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def rule_blocks(prompt: str) -> list[str]:
    """The paragraphs and bullets of `prompt` that hold the determinism rules."""
    blocks = [squeezed(b) for b in re.split(r"\n\s*\n|\n- ", prompt)]
    return [b for b in blocks if "sleep" in b or "free port" in b or "background" in b]


def stub_paragraph() -> str:
    """The text of the tests prompt from its stub sentence to its stand-in paragraph."""
    text = flat(TESTS_PROMPT)
    start = text.index(STUB_START)
    return text[start : text.index(STUB_END)].lower()


def raw_section() -> str:
    """The authoring skill's section about describing behaviour, up to the next heading."""
    text = skills.source("abk-authoring")
    assert AUTHORING_HEADING in text, (
        "the authoring skill has no section about describing behaviour"
    )
    return re.split(r"^## ", text.split(AUTHORING_HEADING, 1)[1], maxsplit=1, flags=re.MULTILINE)[0]


def examples() -> list[str]:
    """The good and bad examples of the authoring skill's section, lower-cased."""
    return [
        line.lower()
        for line in raw_section().splitlines()
        if re.match(r"- (good|bad):", line, re.IGNORECASE)
    ]


def determinism_texts() -> dict[str, str]:
    return {
        "tests prompt": "\n".join(rule_blocks(TESTS_PROMPT)),
        "review prompt": "\n".join(rule_blocks(REVIEW_PROMPT)),
    }


def reuse_texts() -> dict[str, str]:
    return {f"reuse guidance, {kind}": reuse_guidance(kind) for kind in ("source", "tests")}


def scratch_instructions() -> dict[str, str]:
    with tempfile.TemporaryDirectory() as folder:
        app = scratch_app(Path(folder) / "app")
        return {"the scratch app's instruction file": (app / "CLAUDE.md").read_text()}


def packaged_changelog_text() -> dict[str, str]:
    """The framework's own convention, which a repository with no conventions file is told."""
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        return {
            "the packaged changelog text": changelog_convention(
                root, RepoConfig(path=root, slug="example/app")
            )
        }


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
    Entry(
        name="ecosystem-name-in-framework-source",
        reason="framework code is language- and tool-independent: a package manager, manifest or "
        "lock file is named only in toolchain profiles and init detectors",
        found=ECOSYSTEM.search,
        under=TREES,
        names=(),
        suffixes=frozenset({".py"}),
        specs=False,
        offends=(
            Case(
                path=f"{TREES[0]}/pipeline/step.py",
                text="x = 1\nRUN = ['npm', 'install']\n",
                line=2,
            ),
            Case(path=f"{TREES[0]}/step.py", text="LOCK = 'pnpm-lock.yaml'\n"),
            Case(path=f"{TREES[0]}/step.py", text="# run it with yarn\n"),
            Case(path=f"{TREES[0]}/step.py", text='TEXT = "install with cargo"\n'),
            Case(path=f"{TREES[0]}/step.py", text='"""Docstring about pyproject.toml."""\n'),
            Case(path=f"{TREES[-1]}/step.py", text="RUN = ['npm', 'install']\n"),
        ),
        passes=(
            Case(
                path=f"{TREES[0]}/step.py",
                text="# a pipeline of uvula, a pip-boy, an npm-like thing, a yarnball\n",
            ),
            Case(path=f"{TREES[0]}/init/environment.py", text="LOCK = 'package-lock.json'\n"),
        ),
        exemptions=ECOSYSTEM_EXEMPT,
    ),
    Entry(
        name="old-test-kind-spelling",
        reason="the test kinds are `unit-test`, `integration-test` and `e2e-test`; an old "
        "numbered spelling, in a file's text or its name, means a rename was missed",
        found=OLD_KIND.search,
        named=OLD_KIND.search,
        under=KIND_UNDER,
        names=("pyproject.toml",),
        root_suffixes=frozenset({".md"}),
        suffixes=None,
        specs=False,
        offends=(
            *(
                Case(path=path, text=f"x = 1\nNAME = '{OLD_GATE}'\n", line=2)
                for path in (
                    "src/agent_build_kit/pipeline/step.py",
                    "tests/pipeline/test_step.py",
                    "docs/guide.md",
                    "web/src/panel.ts",
                    "tests/fixtures/docs/reports/case.py",
                )
            ),
            *(
                Case(path="src/step.py", text=f"# the {spelling} run\n")
                for spelling in (
                    f"{TIER.title()} 1",
                    f"{TIER.upper()}_2",
                    f"{TIER}-2",
                    f"{TIER}1",
                    f"{TIER}_two",
                    f"{TIER} one",
                )
            ),
            *(
                Case(path=path, text=f"# {OLD_GATE}\n")
                for path in ("pyproject.toml", "scripts/ci_scope.py", ".github/ci.yml")
            ),
            *(
                Case(path=path, text=f"OLD = '{OLD_GATE}'\n")
                for path in (
                    f"src/agent_build_kit/{TOOL_MODULE}.py",
                    f"tests/test_{TOOL_MODULE}.py",
                    f"tests/test_{TOOL_MODULE}_shims.py",
                )
            ),
            Case(path=f"tests/{TIER}2_fakes.py", text="x = 1\n", line=None),
            Case(
                path=f"src/agent_build_kit/pipeline/{TIER}2.py",
                text="from agent_build_kit.pipeline.e2e import *\n",
                line=None,
            ),
            Case(
                path="docs/reports/other.md",
                text=f"- {OLD_GATE}\n",
                siblings=REPORTS_ELSEWHERE,
            ),
        ),
        passes=(
            Case(path="src/step.py", text="KINDS = ('unit-test', 'e2e-test')\n"),
            Case(
                path="docs/track-runs/health.md", text=f"- {OLD_GATE}\n", siblings=REPORTS_ELSEWHERE
            ),
        ),
        exemptions=KIND_EXEMPT,
    ),
    Entry(
        name="rename-tool-named",
        reason="the tool that renamed the test kinds is gone, so nothing names it",
        found=lambda line: TOOL_MODULE in line,
        under=KIND_UNDER,
        names=("pyproject.toml",),
        root_suffixes=frozenset({".md"}),
        suffixes=None,
        specs=False,
        offends=tuple(
            Case(path=path, text=f"Run `abk {TOOL_MODULE}` first.\n")
            for path in ("docs/guide.md", "README.md", "AGENTS.md", "pyproject.toml")
        ),
        exemptions=KIND_EXEMPT,
    ),
    Entry(
        name="old-e2e-marker-name",
        reason="the e2e marker was renamed; its old name returning means a rename was missed",
        found=lambda line: OLD_E2E_MARKER in line,
        under=(),
        names=(),
        suffixes=None,
        specs=False,
        offends=tuple(
            Case(path=path, text=f"x = 1\nMARKER = '{OLD_E2E_MARKER}'\n", line=2)
            for path in (
                "src/agent_build_kit/step.py",
                "tests/fixtures/case.py",
                "docs/guide.md",
                "pyproject.toml",
            )
        ),
        passes=(Case(path="src/step.py", text="MARKER = 'e2e'\n"),),
        exemptions=CHANGELOG,
    ),
    Entry(
        name="serial-marker-in-tests-and-configuration",
        reason="a test that cannot run beside others is isolated, not marked",
        found=SERIAL.search,
        under=tuple(test_tree_folders()),
        names=(),
        root_suffixes=CONFIG_SUFFIXES,
        suffixes=None,
        specs=False,
        offends=(
            Case(
                path="tests/test_a.py",
                text=f"import pytest\n\n@pytest.mark.{MARKER}\ndef test_a(): ...\n",
                line=3,
            ),
            Case(
                path="pyproject.toml",
                text=f'[tool.pytest.ini_options]\nmarkers = ["{MARKER}: alone"]\n',
                line=2,
            ),
            Case(path="pytest.ini", text=f"[pytest]\naddopts = -m 'not {MARKER}'\n", line=2),
            Case(
                path="package.json",
                text=f'{{"scripts": {{"test": "vitest --project {MARKER}"}}}}\n',
            ),
            Case(
                path="vitest.config.ts",
                text=f"export default {{ test: {{ include: ['{MARKER}/**'] }} }};\n",
            ),
        ),
        passes=(
            Case(path="tests/test_a.py", text="# the serialiser and a serial_number\n"),
            Case(
                path="tests/test_a.py",
                text=f'assert "two {MARKER} reruns" in prompt\nassert "{MARKER} rerun " in line\n',
            ),
        ),
        exemptions=(
            *exempt_files(
                "holds the word as data for the tests that need it", "tests/serial_marker.py"
            ),
            *SPELLING,
        ),
    ),
    Entry(
        name="old-live-test-module-name",
        reason="the scratch live tests are named for what they drive, not for one runtime; an old "
        "name found again, in a file or as a module, means a reference was missed",
        found=lambda line: any(stem in line for stem in OLD_STEMS),
        named=lambda name: any(stem in name for stem in OLD_STEMS),
        under=(),
        names=(),
        suffixes=None,
        specs=False,
        offends=(
            Case(path="docs/guide.md", text=f"{OLD_STEMS[0]} was renamed.\n"),
            Case(path="tests/integration/test_x.py", text=f"from x import {OLD_STEMS[1]}\n"),
            Case(path=f"tests/integration/{OLD_STEMS[1]}.py", text="x = 1\n", line=None),
        ),
        passes=(Case(path="docs/guide.md", text="test_build_unit was renamed.\n"),),
        exemptions=CHANGELOG,
    ),
    Entry(
        name="e2e-mechanism-names-a-runtime-or-provider",
        reason="the e2e-test mechanism names no split, runtime or provider: they are configuration",
        check=e2e_names,
        offends=(
            Case(path=E2E_MODULE, text=f"RUNTIME = '{RUNTIME}'\n"),
            Case(path=E2E_MODULE, text="runtime_claude_code = 1\n"),
            Case(path=E2E_MODULE, text=f"PROVIDER = '{PROVIDER}'\n"),
            Case(path=E2E_MODULE, text=f'"""Runs on {RUNTIME}."""\n'),
            Case(path=f"{TREES[-1]}/{E2E_MODULES[1]}", text=f"RUNTIME = '{RUNTIME}'\n"),
            Case(
                path=E2E_CLASS_MODULE,
                text=profile_module(f"    kind = '{RUNTIME}'\n"),
                line=2,
            ),
        ),
        passes=(
            Case(
                path=E2E_MODULE, text=f"# {RUNTIME} and {PROVIDER} are named in a comment\nX = 1\n"
            ),
            Case(path=E2E_MODULE, text="@runtime_checkable\nclass Profile:\n    pass\n"),
            Case(path=E2E_CLASS_MODULE, text=f"KNOWN = '{RUNTIME}'\n\n" + profile_module()),
            Case(path=f"{TREES[0]}/pipeline/other.py", text=f"X = '{RUNTIME}'\n"),
        ),
    ),
    Entry(
        name="old-runtime-list-in-a-document",
        reason="the runtime lists were replaced by the split settings; a document naming them is "
        "out of date",
        found=lambda line: any(old in line for old in OLD_RUNTIME_LISTS),
        under=("docs", SHIPPED[0]),
        names=("README.md",),
        suffixes=frozenset({".md"}),
        where=a_top_document,
        specs=False,
        offends=(
            Case(path="docs/x.md", text=f"The {OLD_RUNTIME_LISTS[0]} setting.\n"),
            Case(path="README.md", text=f"The {OLD_RUNTIME_LISTS[1]} setting.\n"),
            Case(
                path=f"{SHIPPED[0]}/abk-config/SKILL.md", text=f"The {OLD_RUNTIME_LISTS[2]} list.\n"
            ),
        ),
        passes=(Case(path="docs/designs/x.md", text=f"The {OLD_RUNTIME_LISTS[0]} setting.\n"),),
    ),
    Entry(
        name="removed-review-key-in-a-document",
        reason="a removed setting is named only where the migration is, so a document never "
        "offers it as a current key",
        found=lambda paragraph: (
            bool(REMOVED_KEYS.search(paragraph)) and "--migrate" not in paragraph
        ),
        by_paragraph=True,
        under=(),
        names=(),
        suffixes=frozenset({".md"}),
        specs=False,
        offends=(
            Case(path="docs/x.md", text="`max_unit_lines` is gone.\n"),
            Case(path="docs/x.md", text="`review.enabled` is removed.\n"),
            Case(
                path="docs/x.md",
                text="Intro.\n\nThe defaults cover migrations, and `max_unit_lines` stays.\n",
                line=3,
            ),
        ),
        passes=(Case(path="docs/x.md", text="Run `abk config --migrate` for `max_unit_lines`.\n"),),
        exemptions=(
            *exempt_paths("a history document keeps the names it records", *HISTORY),
            *exempt_paths("the migration runbook names the keys it migrates", RUNBOOK),
            *CHANGELOG,
        ),
    ),
    Entry(
        name="old-limits-spelling-shown-as-current",
        reason="`usage_limits` is the key; a document shows the old `limits` spelling only to "
        "explain the rename",
        found=shows_old_limits,
        by_paragraph=True,
        under=("docs", SHIPPED[0]),
        names=("README.md",),
        suffixes=frozenset({".md"}),
        where=a_top_document,
        specs=False,
        offends=(
            Case(path="docs/x.md", text="Set `runtimes.<name>.limits` to the window.\n"),
            Case(path="README.md", text="limits:\n  five_hour: 1\n"),
        ),
        passes=(
            Case(
                path="docs/x.md", text="`runtimes.<name>.limits` was renamed to `usage_limits`.\n"
            ),
            Case(path="docs/x.md", text="usage_limits:\n  five_hour: 1\n"),
        ),
    ),
    Entry(
        name="old-merge-rule-in-a-markdown-file",
        reason="a person merges what was not auto-landed and the pipeline merges the rest; a "
        "file stating that a person merges every pull request states the rule that was replaced",
        found=lambda paragraph: bool(statements(paragraph)),
        by_paragraph=True,
        under=(),
        names=(),
        suffixes=frozenset({".md"}),
        specs=False,
        offends=(
            Case(path="docs/x.md", text="A person merges every pull request.\n"),
            Case(path="README.md", text="The pipeline never\nmerges anything.\n"),
            Case(
                path=f"{SHIPPED[0]}/x/SKILL.md", text="Intro.\n\nA human merges each one.\n", line=3
            ),
        ),
        passes=(
            Case(path="docs/x.md", text="A person merges what was not auto-landed.\n"),
            Case(path="docs/x.md", text="A person merges any other pull request.\n"),
        ),
        exemptions=(
            *CHANGELOG,
            Exemption(
                path="docs/reports/20260101-health.md",
                reports=True,
                reason="a track's report quotes the wording it found elsewhere and proposes "
                "removing",
            ),
            *exempt_paths("a history document keeps the wording it records", *HISTORY),
        ),
    ),
    Entry(
        name="document-says-the-unit-store-is-committed",
        reason="the unit store lives in the planning home, so a document, skill or the changelog "
        "never says it is committed",
        found=COMMITTED.search,
        under=("docs", SHIPPED[0]),
        names=("CHANGELOG.md",),
        suffixes=frozenset({".md"}),
        where=a_state_document,
        specs=False,
        offends=(
            Case(path="docs/x.md", text="| `units.json` | Commit it |\n"),
            Case(path=STATE_RUNBOOK, text="The `units.json` file is committed.\n"),
            Case(path="CHANGELOG.md", text="# Changelog\nunits.json stays tracked.\n", line=2),
            Case(path=f"{SHIPPED[0]}/x/SKILL.md", text="units.json are tracked by git.\n"),
        ),
        passes=(
            Case(path="docs/designs/x.md", text="units.json is committed.\n"),
            Case(path="docs/x.md", text="units.json is kept in the planning home.\n"),
        ),
    ),
    Entry(
        name="skill-carries-the-reuse-guidance-text",
        reason="the reuse guidance is one packaged part the prompts carry; no skill repeats it",
        found=lambda line: REUSE_HEADING in line,
        under=(SHIPPED[0],),
        names=(),
        suffixes=frozenset({".md"}),
        where=a_skill_file,
        specs=False,
        offends=(Case(path=f"{SHIPPED[0]}/x/SKILL.md", text=f"{REUSE_HEADING}.\n"),),
        passes=(Case(path="docs/x.md", text=f"{REUSE_HEADING}.\n"),),
    ),
    Entry(
        name="skill-says-priority-zero-bypasses-no-limit",
        reason="priority 0 starts in its own lane with its own cap, so no skill says it "
        "bypasses no limit",
        found=lambda paragraph: BYPASS in flat(paragraph).lower(),
        by_paragraph=True,
        under=(SHIPPED[0],),
        names=(),
        suffixes=frozenset({".md"}),
        where=a_skill_file,
        specs=False,
        offends=(
            Case(path=f"{SHIPPED[0]}/x/SKILL.md", text="Priority 0 Bypasses\nNo Limit at all.\n"),
        ),
        passes=(Case(path="docs/x.md", text=f"Priority 0 {BYPASS}.\n"),),
    ),
    Entry(
        name="determinism-rules-name-a-language-or-tool",
        reason="the determinism rules of the tests prompt and the review prompt are stated for "
        "any language and runner",
        found=mentions(*DETERMINISM_TOOLS),
        texts=determinism_texts,
        offends=(Case(path="the prompt", text="never call time.sleep to wait\n"),),
        passes=(Case(path="the prompt", text="never wait on the clock\n"),),
    ),
    Entry(
        name="output-convention-names-an-installation",
        reason="the long-output convention is carried by every build prompt of every installation",
        found=matches(HASH_NUMBER, words=(HOME_FRAGMENT,)),
        texts=lambda: {"the output convention": output_convention()},
        offends=(
            Case(path="the convention", text="see /home/someone/out\n"),
            Case(path="the convention", text="fixed in contoso#15\n"),
        ),
    ),
    Entry(
        name="reuse-guidance-names-an-installation-language-tool-or-path",
        reason="the reuse guidance is one packaged part, carried by prompts of any language",
        found=matches(HASH_NUMBER, KIT_NAMES, SOURCE_PATH, words=(HOME_FRAGMENT, *REUSE_TOOLS)),
        texts=reuse_texts,
        offends=(
            Case(path="the part", text="see /home/someone\n"),
            Case(path="the part", text="fixed in contoso#15\n"),
            Case(path="the part", text="as the kit does\nask abk first\n", line=2),
            Case(path="the part", text="run uv run it\n"),
            Case(path="the part", text="look in src/helpers\n"),
            Case(path="the part", text="a helper in utils.py\n"),
        ),
        passes=(Case(path="the part", text="search the shared helpers first\n"),),
    ),
    Entry(
        name="stub-guidance-names-an-installation-language-tool-or-path",
        reason="the stub paragraph of the tests prompt is stated for any language",
        found=matches(HASH_NUMBER, STUB_PATH, words=(HOME_FRAGMENT, *STUB_TOOLS)),
        texts=lambda: {"the stub paragraph": stub_paragraph()},
        offends=(
            Case(path="the paragraph", text="fixed in contoso#15\n"),
            Case(path="the paragraph", text="see /home/someone\n"),
            Case(path="the paragraph", text="a file under tests/\n"),
            Case(path="the paragraph", text="run cargo first\n"),
        ),
    ),
    Entry(
        name="authoring-section-names-an-installation-language-tool-or-path",
        reason="the authoring skill's section on describing behaviour is stated for any language",
        found=matches(
            AUTHORING_LEAK,
            AUTHORING_FILE,
            AUTHORING_KIT,
            words=REUSE_TOOLS,
        ),
        texts=lambda: {"the authoring section": raw_section()},
        offends=(
            Case(path="the section", text="see github.com/owner\n"),
            Case(path="the section", text="edit step.py\n"),
            Case(path="the section", text="ask abk\n"),
            Case(path="the section", text="run ruff\n"),
        ),
    ),
    Entry(
        name="authoring-examples-use-language-specific-syntax",
        reason="the examples of the authoring skill's section read the same in any language",
        found=matches(AUTHORING_DECLARATION, AUTHORING_CALL),
        texts=lambda: {"the authoring examples": "\n".join(examples())},
        offends=(
            Case(path="the examples", text="- bad: def helper do it\n"),
            Case(path="the examples", text="- bad: parse(text) -> value\n"),
        ),
        passes=(Case(path="the examples", text="- good: the total is the sum of the lines\n"),),
    ),
    Entry(
        name="scratch-app-instructions-name-a-bare-program",
        reason="a build agent can run only what the profile allows, so the generated "
        "instructions name the profile's commands and never a bare test or lint program",
        found=lambda line: bool(
            BARE_PROGRAM.search(line.replace("uv run pytest", "").replace("uv run pre-commit", ""))
        ),
        texts=scratch_instructions,
        offends=(Case(path="the file", text="Run pytest -q to test.\n"),),
        passes=(Case(path="the file", text="Run uv run pytest -q to test.\n"),),
    ),
    Entry(
        name="command-composer-source-names-a-profile-or-tool-word",
        reason="the module that composes the agent commands names no toolchain: the profile does",
        found=COMPOSER_WORD.search,
        texts=lambda: {"the command composer": Path(agent_commands.__file__).read_text()},
        offends=(
            Case(path="the source", text="RUN = ['npm', 'test']\n"),
            Case(path="the source", text=f"PROFILE = '{profiles.names()[0]}'\n"),
        ),
        passes=(Case(path="the source", text="RUN = 'a pre-commit-like uvula'\n"),),
    ),
    Entry(
        name="packaged-changelog-text-names-an-installation",
        reason="the packaged convention is told to every repository that has none of its own",
        found=matches(HASH_NUMBER, words=(HOME_FRAGMENT,)),
        texts=packaged_changelog_text,
        offends=(
            Case(path="the text", text="see /home/someone\n"),
            Case(path="the text", text="fixed in contoso#15\n"),
        ),
    ),
)


def build(root: Path, case: Case) -> None:
    """Write `case` into `root`, as a git repository in the state the case names."""
    if case.state != "none":
        init_repo(root)
        (root / ".gitignore").write_text(f"{case.path}\n" if case.state == "ignored" else "")
        git(root, "add", ".gitignore")
        git(root, "commit", "-qm", "base")
    for name, text in ((case.path, case.text), *case.siblings):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    if case.state == "committed":
        git(root, "add", case.path)
        git(root, "commit", "-qm", "file")


def text_findings(entry: Entry, texts: dict[str, str]) -> list[str]:
    """What the entry forbids in each named text, as `name:line: clipped line`; a text that is
    empty is a finding too, since a rule over nothing passes whatever the product says."""
    assert entry.found is not None, entry.name
    found: list[str] = []
    for label, text in texts.items():
        if not text.strip():
            found.append(f"{label}: the text is empty, so nothing was checked ({entry.name})")
        found += [
            f"{label}:{number}: {line.strip()[:100]}"
            for number, line in enumerate(text.splitlines(), start=1)
            if entry.found(line)
        ]
    return found


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
        scope = (
            entry.under,
            entry.names,
            entry.suffixes,
            entry.specs,
            entry.root_suffixes,
            entry.where,
        )
        if scope not in self._listed:
            listed = guarded_files(
                self.root,
                under=entry.under,
                names=entry.names,
                suffixes=entry.suffixes,
                specs=entry.specs,
                dirs=self.dirs,
            )
            if entry.root_suffixes:
                listed = sorted(
                    {
                        *listed,
                        *(
                            self.root / path
                            for path in tracked(self.root)
                            if len(path.parts) == 1
                            and path.suffix in entry.root_suffixes
                            and (self.root / path).is_file()
                        ),
                    }
                )
            if entry.where is not None:
                listed = [
                    path for path in listed if entry.where(path.relative_to(self.root).as_posix())
                ]
            self._listed[scope] = listed
        return self._listed[scope]

    def lines(self, path: Path) -> list[str]:
        if path not in self._lines:
            self._lines[path] = lines_of(path, errors="replace")
        return self._lines[path]

    def exempt(self, entry: Entry, path: Path) -> bool:
        relative = path.relative_to(self.root).as_posix()
        return any(
            exemption.covers(relative, self.dirs.reports_dir) for exemption in entry.exemptions
        )

    def paragraphs(self, path: Path) -> Iterator[tuple[int, str]]:
        """Each run of lines with no blank line between, with the number of its first line."""
        start, block = 0, []
        for number, line in enumerate(self.lines(path), start=1):
            if line.strip():
                start = start or number
                block.append(line)
            elif block:
                yield start, "\n".join(block)
                start, block = 0, []
        if block:
            yield start, "\n".join(block)

    def findings(self, entry: Entry) -> list[str]:
        """What the entry forbids and `root` holds, as `path:line: clipped line` (a check's own
        wording for a finding about the checkout; a finding about a file's name has no line)."""
        if entry.check is not None:
            return entry.check(self.root)
        if entry.texts is not None:
            return text_findings(entry, entry.texts())
        assert entry.found is not None or entry.named is not None, entry.name
        found: list[str] = []
        for path in self.files(entry):
            if self.exempt(entry, path):
                continue
            relative = path.relative_to(self.root).as_posix()
            if entry.named is not None and entry.named(path.name):
                found.append(f"{relative}: the file name is forbidden ({entry.name})")
            rule = entry.found
            if rule is None:
                continue
            if entry.in_specs and in_specs_folder(self.root, path, self.dirs):
                rule = entry.in_specs
            if entry.by_paragraph:
                found += [
                    f"{relative}:{number}: {text.split(chr(10))[0].strip()[:100]}"
                    for number, text in self.paragraphs(path)
                    if rule(text)
                ]
            else:
                found += file_hits(self.root, path, rule, self.lines(path))
        return found

    def stale(self, entry: Entry) -> list[str]:
        """Each listing of the entry that may only shrink and covers no file the entry finds
        something in: one that has nothing left to cover is removed."""
        if entry.found is None:
            return []
        rule = entry.found
        stale = []
        for exemption in entry.exemptions:
            if exemption.stale and not any(
                rule(text)
                for path in self.files(entry)
                if exemption.covers(path.relative_to(self.root).as_posix())
                for text in self.lines(path)
            ):
                stale.append(f"{exemption.path}: {exemption.reason}, but covers no name; remove it")
        return stale
