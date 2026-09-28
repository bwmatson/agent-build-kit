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
from collections.abc import Callable, Mapping
from pathlib import Path

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
_SERVICE_MARKERS = ("Dockerfile", "pyproject.toml", "package.json")
_SKIP_DIRS = {"node_modules", ".venv", "venv", "dist", "build"}

DEV_STACK_SCRIPT = "scripts/dev-stack.sh"
_CREDENTIALS_ARRAY = re.compile(r"^\s*(?P<name>[A-Z_]+_CREDENTIALS)=\(", re.M)


class RepoDetection(Frozen):
    path: Path
    # The directory name: the repo's name in abk.yaml unless overridden.
    name: str
    is_git: bool
    slug: str | None
    default_branch: str
    languages: list[str]
    profile: str
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


def _languages(path: Path, pyproject: dict, package: dict) -> tuple[list[str], str]:
    languages: list[str] = []
    profile = ""
    if any((path / marker).exists() for marker in _PYTHON_MARKERS):
        languages.append("python")
        # The only Python profile; a repo without uv still gets the closest fit.
        profile = "python-uv"
    if package or (path / "package.json").exists():
        languages.append("javascript")
        if (path / "tsconfig.json").exists():
            languages.append("typescript")
        if not profile:
            profile = "node-npm"
    return languages, profile or "python-uv"


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
    for child in sorted(path.iterdir()):
        if not child.is_dir() or child.name.startswith(".") or child.name in _SKIP_DIRS:
            continue
        if any((child / marker).exists() for marker in _SERVICE_MARKERS):
            found.append(child.name)
    return found


def detect_repo(path: Path, *, run: Run | None = None) -> RepoDetection:
    run = run or subprocess.run
    path = path.expanduser().resolve()
    is_git = (path / ".git").exists()

    slug = None
    default_branch = "main"
    has_code = False
    if is_git:
        origin = _git(run, path, "remote", "get-url", "origin")
        slug = parse_slug(origin) if origin else None
        head = _git(run, path, "symbolic-ref", "refs/remotes/origin/HEAD")
        if head:
            default_branch = head.rsplit("/", 1)[-1]
        commits = _git(run, path, "rev-list", "--count", "HEAD")
        tracked = _git(run, path, "ls-files") or ""
        has_code = bool(commits and commits != "0") and any(
            _is_code(line) for line in tracked.splitlines() if line
        )

    pyproject = _pyproject(path)
    package = _package_json(path)
    languages, profile = _languages(path, pyproject, package)

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
        default_branch=default_branch,
        languages=languages,
        profile=profile,
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
