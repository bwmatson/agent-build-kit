"""What can be read off a checkout without asking anyone.

`abk init` drafts a repo's entry in abk.yaml from this: the GitHub slug from
its origin, the default branch, the languages its tooling files imply, the
directories that look like deployable services, its dev-stack script, and
which other workspace repos it depends on. Everything is a guess a human
reviews in the generated file; nothing here is authoritative afterwards —
`abk doctor` re-runs it only to point out where abk.yaml has drifted.

Every git call goes through an injectable runner; the tests use real
temporary repos, and a caller with a recorded answer can pass its own.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path

from agent_build_kit import forges
from agent_build_kit.forges import RepoId
from agent_build_kit.model import Frozen

Run = Callable[..., subprocess.CompletedProcess]

# `git@github.com:owner/name.git`, `https://github.com/owner/name`,
# `ssh://git@github.com/owner/name.git`, `alias:owner/name.git` (an ssh host
# alias carrying a deploy key).
_ORIGIN = re.compile(
    r"^(?:[\w.@-]+:(?!//)|[a-z+]+://[^/]+/)(?P<owner>[\w.-]+)/(?P<name>[\w.-]+?)(?:\.git)?/?$"
)

# Files that are not code for the purpose of "does this repo have code yet".
_NOT_CODE_NAMES = {".gitignore", "pyproject.toml", "package.json"}
_LOCKFILES = {"uv.lock", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock"}
_NOT_CODE_DIRS = {".github", "docs"}

_PYTHON_MARKERS = ("pyproject.toml", "uv.lock", "setup.py", "requirements.txt")
_NODE_MARKERS = ("package.json",)
# A file that declares a project. The rest of the markers above are satellites:
# a `requirements.txt` is as often a deployment manifest sitting inside a
# project - an Azure Functions directory beside the code it ships - as it is a
# project of its own, and a lockfile never declares one.
_DECLARES_PROJECT = ("pyproject.toml", "setup.py", "package.json")
_SERVICE_MARKERS = ("Dockerfile", "pyproject.toml", "package.json")
_SKIP_DIRS = {"node_modules", ".venv", "venv", "dist", "build"}

# How far below the root a project may sit and still be found. A checkout does
# not always keep its tooling at the top: `<repo>/pipelines/poc/pyproject.toml`
# with `<repo>/pipelines/poc/web/package.json` beside it is one repo with two
# projects, and reading only the root reported no language at all. Three levels
# reaches that web app; deeper is the owner's to name in abk.yaml, and the bound
# is what keeps a large checkout from being walked end to end.
_SCAN_DEPTH = 3

DEV_STACK_SCRIPT = "scripts/dev-stack.sh"
_CREDENTIALS_ARRAY = re.compile(r"^\s*(?P<name>[A-Z_]+_CREDENTIALS)=\(", re.M)


class ProjectDetection(Frozen):
    """One project inside a checkout: where its tooling is, and what it is.

    A repo is not always one project. A Python service with a web app beneath
    it is two, each with its own toolchain, and the repo-level profile can only
    name one of them - so each is recorded here, and abk.yaml shows both.
    """

    # Relative to the repo root; `.` when the root itself is the project.
    path: str
    languages: list[str] = []
    profile: str = "python-uv"


class RepoDetection(Frozen):
    path: Path
    # The directory name: the repo's name in abk.yaml unless overridden.
    name: str
    is_git: bool
    # The GitHub owner/name, when that is what this repo has. Kept because
    # `resolve_consumes` matches dependency refs against it.
    slug: str | None
    # Which host the origin says this is, and the repo's identity there. None
    # when no forge recognised the remote.
    identity: RepoId | None = None
    default_branch: str
    languages: list[str]
    profile: str
    # Every project found, root first, in scan order. Defaulted so a hand-built
    # detection - the tests, a recorded answer - need only give what it asserts on.
    projects: list[ProjectDetection] = []
    has_code: bool
    service_dirs: list[str]
    dev_stack_script: str | None
    credentials_array: str | None
    # Git URLs and package specs this repo depends on, for `consumes`.
    dependency_refs: list[str]
    # Other workspace repos this one depends on; filled by `resolve_consumes`.
    consumes: list[str] = []


def parse_slug(url: str) -> str | None:
    match = _ORIGIN.match(url.strip())
    return f"{match['owner']}/{match['name']}" if match else None


def _git(run: Run, path: Path, *args: str) -> str | None:
    """stdout of a git command, or None if it failed or git is absent."""
    try:
        result = run(["git", *args], cwd=path, capture_output=True, text=True, check=False)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _is_code(tracked: str) -> bool:
    first = tracked.split("/", 1)[0]
    name = tracked.rsplit("/", 1)[-1]
    if first in _NOT_CODE_DIRS:
        return False
    if name in _NOT_CODE_NAMES or name in _LOCKFILES or name.endswith(".md"):
        return False
    upper = name.upper()
    return not (upper.startswith("README") or upper.startswith("LICENSE"))


def _pyproject(path: Path) -> dict:
    try:
        return tomllib.loads((path / "pyproject.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _package_json(path: Path) -> dict:
    try:
        loaded = json.loads((path / "package.json").read_text())
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _holds_marker(directory: Path) -> bool:
    for marker in _PYTHON_MARKERS + _NODE_MARKERS:
        try:
            if (directory / marker).exists():
                return True
        except OSError:
            return False
    return False


def _children(directory: Path) -> list[Path]:
    """The directories worth descending into, or none when this one cannot be
    read: a checkout holds runtime data as well as source, and a directory a
    service wrote as another user must not end the scan."""
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return []
    children = []
    for child in entries:
        if child.name.startswith(".") or child.name in _SKIP_DIRS:
            continue
        try:
            if child.is_dir():
                children.append(child)
        except OSError:
            continue
    return children


def project_dirs(path: Path) -> list[Path]:
    """Every directory holding a tooling file, the root first, breadth first.

    Bounded by `_SCAN_DEPTH`, and never inside a vendored or virtualenv
    directory: `node_modules` holds thousands of `package.json` files that say
    nothing about what this repo is written in.
    """
    found: list[Path] = []
    level = [path]
    for depth in range(_SCAN_DEPTH + 1):
        if not level:
            break
        found += [directory for directory in level if _holds_marker(directory)]
        if depth == _SCAN_DEPTH:
            break
        level = [child for directory in level for child in _children(directory)]
    return found


def _languages_of(directory: Path) -> tuple[list[str], str]:
    """What one project directory is written in, and the profile that fits it."""
    languages: list[str] = []
    profile = ""
    if any((directory / marker).exists() for marker in _PYTHON_MARKERS):
        languages.append("python")
        # The only Python profile; a repo without uv still gets the closest fit.
        profile = "python-uv"
    if (directory / "package.json").exists():
        languages.append("javascript")
        if (directory / "tsconfig.json").exists():
            languages.append("typescript")
        if not profile:
            profile = "node-npm"
    return languages, profile or "python-uv"


def detect_projects(path: Path) -> list[ProjectDetection]:
    """Every project in the checkout, root first, in scan order.

    A directory with only satellite markers counts when nothing above it is
    already a project, and does not when something is: that is the difference
    between a repo that declares itself with a `requirements.txt` and a
    deployment directory inside one that declares itself properly.
    """
    projects = []
    claimed: list[Path] = []
    for directory in project_dirs(path):
        declares = any((directory / marker).exists() for marker in _DECLARES_PROJECT)
        if not declares and any(parent in claimed for parent in directory.parents):
            continue
        languages, profile = _languages_of(directory)
        relative = "." if directory == path else directory.relative_to(path).as_posix()
        projects.append(ProjectDetection(path=relative, languages=languages, profile=profile))
        claimed.append(directory)
    return projects


def _languages(projects: list[ProjectDetection]) -> tuple[list[str], str]:
    """The repo's languages across every project, in a fixed order.

    Python wins the profile wherever it was found: a repo with a Python service
    and a web app beneath it is driven by the Python toolchain. The per-project
    profiles above are what a caller needs to run either one's tooling.
    """
    found = {language for project in projects for language in project.languages}
    languages = [name for name in ("python", "javascript", "typescript") if name in found]
    profile = (
        "python-uv" if "python" in found else "node-npm" if "javascript" in found else "python-uv"
    )
    return languages, profile


def _dependency_refs(pyproject: dict, package: dict) -> list[str]:
    refs: list[str] = []
    sources = pyproject.get("tool", {}).get("uv", {}).get("sources", {})
    for value in sources.values() if isinstance(sources, dict) else ():
        if isinstance(value, dict) and isinstance(value.get("git"), str):
            refs.append(value["git"])
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        section = package.get(key)
        if isinstance(section, dict):
            refs.extend(f"{name}@{spec}" for name, spec in section.items() if isinstance(spec, str))
    return refs


def _service_dirs(path: Path) -> list[str]:
    found = []
    for child in _children(path):
        try:
            if any((child / marker).exists() for marker in _SERVICE_MARKERS):
                found.append(child.name)
        except OSError:
            continue
    return found


PrBases = Callable[[RepoId], list[str]]


def _integration_branch(
    identity: RepoId | None,
    pr_bases: PrBases | None,
    on_remote: list[str],
) -> str | None:
    """The branch this repo's pull requests actually target, if its host says.

    `origin/HEAD` is a pointer somebody set once and nobody updates, so a repo
    that moved its integration to `dev` still answers `main` - and every unit
    would then be built on a branch the work is not on, where the files a
    change names are simply absent.

    Only a branch that exists on the remote counts: stacked work targets its
    parent branch, which is a common target and never the repo's default.
    """
    if identity is None or pr_bases is None:
        return None
    try:
        bases = pr_bases(identity)
    except Exception:  # noqa: BLE001 - init runs before credentials need to be in place
        return None
    counted = Counter(base for base in bases if base and (not on_remote or base in on_remote))
    return counted.most_common(1)[0][0] if counted else None


def detect_repo(
    path: Path,
    *,
    run: Run | None = None,
    pr_bases: PrBases | None = None,
    remote_branches: list[str] | None = None,
) -> RepoDetection:
    run = run or subprocess.run
    path = path.expanduser().resolve()
    is_git = (path / ".git").exists()

    slug = None
    identity = None
    default_branch = "main"
    has_code = False
    if is_git:
        origin = _git(run, path, "remote", "get-url", "origin")
        identity = forges.identify(origin) if origin else None
        slug = parse_slug(origin) if origin and identity and identity.forge == "github" else None
        head = _git(run, path, "symbolic-ref", "refs/remotes/origin/HEAD")
        if head:
            default_branch = head.rsplit("/", 1)[-1]
        on_remote = remote_branches
        if on_remote is None:
            listed = _git(run, path, "branch", "-r", "--format=%(refname:short)") or ""
            on_remote = [
                line.removeprefix("origin/").strip()
                for line in listed.splitlines()
                if line.strip().startswith("origin/") and "->" not in line
            ]
        default_branch = _integration_branch(identity, pr_bases, on_remote) or default_branch
        commits = _git(run, path, "rev-list", "--count", "HEAD")
        tracked = _git(run, path, "ls-files") or ""
        has_code = bool(commits and commits != "0") and any(
            _is_code(line) for line in tracked.splitlines() if line
        )

    pyproject = _pyproject(path)
    package = _package_json(path)
    projects = detect_projects(path)
    languages, profile = _languages(projects)

    script = path / DEV_STACK_SCRIPT
    credentials = None
    if script.is_file():
        match = _CREDENTIALS_ARRAY.search(script.read_text())
        credentials = match["name"] if match else None

    return RepoDetection(
        path=path,
        name=path.name,
        is_git=is_git,
        slug=slug,
        identity=identity,
        default_branch=default_branch,
        languages=languages,
        profile=profile,
        projects=projects,
        has_code=has_code,
        service_dirs=_service_dirs(path),
        dev_stack_script=DEV_STACK_SCRIPT if script.is_file() else None,
        credentials_array=credentials,
        dependency_refs=_dependency_refs(pyproject, package),
    )


def resolve_consumes(detections: Mapping[str, RepoDetection]) -> dict[str, RepoDetection]:
    """Fill each detection's `consumes` with the other workspace repos whose
    slug appears among its dependency refs."""
    resolved: dict[str, RepoDetection] = {}
    for name, detection in detections.items():
        consumes = [
            other
            for other, candidate in detections.items()
            if other != name
            and candidate.slug
            and any(candidate.slug.lower() in ref.lower() for ref in detection.dependency_refs)
        ]
        resolved[name] = detection.model_copy(update={"consumes": consumes})
    return resolved
