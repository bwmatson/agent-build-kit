"""Drafting abk.yaml and writing the planning repo around it.

`draft_config` turns what `detect` read off each checkout into a
`WorkspaceConfig` a human then reviews: a deploy rule skeleton per service
directory, the dev stack and its credentials array when the script is there,
`consumes` from the dependency refs unless the caller says otherwise.

`write_planning_repo` lays out everything the pipeline expects to find —
the git repo, the OpenSpec project, the state directory,
the skills — and is idempotent: a second run writes only what is missing.
The two files a person edits, `abk.yaml` and `openspec/config.yaml`, are
never overwritten without `force`. The one exception is the stock
`config.yaml` that `openspec init` itself just wrote: it holds nothing but
the schema name, so replacing it loses nothing.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

import yaml

from agent_build_kit import forges, openspec, skills
from agent_build_kit.config import (
    CONFIG_FILENAME,
    CredentialsConfig,
    DeployConfig,
    DeployRule,
    DevStackConfig,
    NamesFrom,
    ProjectConfig,
    RepoConfig,
    WorkspaceConfig,
    dump,
)
from agent_build_kit.init.detect import RepoDetection

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"

# The version of the rules block this framework writes. An installation is
# expected to reword these rules for its own repos and conventions, so the
# stamp — not the text — is what says whether its rules predate the
# framework's. Bump it whenever the template gains or changes a rule, and say
# what changed in RULES_CHANGES so `abk doctor` can report it.
RULES_VERSION = 2

# version -> what that version added or changed, in an installation's terms.
RULES_CHANGES: dict[int, list[str]] = {
    1: ["the initial rules"],
    2: ["a file that moves or is renamed moves with `git mv`, alone in its commit"],
}

# The stamp a rendered rules block carries, derived from the version rather
# than written beside it: the two drifted apart the first time the version was
# bumped, so every fresh `abk init` wrote a file the doctor then reported as
# out of date.
RULES_HEADER = f"# abk-rules: v{RULES_VERSION}"
# What a slug looks like until the person fills it in.
PLACEHOLDER_OWNER = "todo-owner"


class ScaffoldError(Exception):
    """The planning repo could not be laid out."""


# --- drafting ------------------------------------------------------------------


def _ordered(names: Sequence[str], consumes: Mapping[str, list[str]]) -> list[str]:
    """`names` with every repo after the ones it consumes, so abk.yaml reads
    in deploy order."""
    ordered: list[str] = []

    def visit(name: str, path: tuple[str, ...]) -> None:
        if name in ordered or name in path:
            return
        for consumed in consumes.get(name, []):
            if consumed in names:
                visit(consumed, (*path, name))
        ordered.append(name)

    for name in names:
        visit(name, ())
    return ordered


def draft_config(
    detections: Mapping[str, RepoDetection],
    *,
    planning_dir: Path,
    consumes_overrides: Mapping[str, list[str]] | None = None,
) -> WorkspaceConfig:
    overrides = dict(consumes_overrides or {})
    consumes = {name: overrides.get(name, d.consumes) for name, d in detections.items()}
    for name, consumed in consumes.items():
        unknown = [other for other in consumed if other not in detections]
        if unknown:
            raise ScaffoldError(f"{name} consumes {', '.join(unknown)}, which is not a repo here")

    repos: dict[str, RepoConfig] = {}
    for name in _ordered(list(detections), consumes):
        detection = detections[name]
        credentials = None
        if detection.credentials_array and detection.dev_stack_script:
            credentials = CredentialsConfig(
                names_from=NamesFrom(
                    file=detection.dev_stack_script, shell_array=detection.credentials_array
                )
            )
        # Each host names a repo its own way, and writes the keys it says it
        # requires, so the drafted file is one that loads. A repo whose origin
        # no forge recognised is drafted as GitHub with a placeholder owner,
        # which is the line a human then edits.
        identity = detection.identity
        forge = forges.get(identity.forge) if identity else forges.get("github")
        named = (
            forge.config_entry(identity)
            if identity
            else {"slug": detection.slug or f"{PLACEHOLDER_OWNER}/{name}"}
        )
        # Validated rather than constructed, because which keys name the repo
        # is the forge's answer and differs per host.
        repos[name] = RepoConfig.model_validate(
            {
                "path": detection.path,
                "forge": forge.name,
                **named,
                "default_branch": detection.default_branch,
                "profile": detection.profile,
                "languages": list(detection.languages),
                "projects": [
                    ProjectConfig(
                        path=project.path,
                        languages=list(project.languages),
                        profile=project.profile,
                    )
                    for project in detection.projects
                ],
                "consumes": list(consumes[name]),
                "dev_stack": DevStackConfig(script=detection.dev_stack_script)
                if detection.dev_stack_script
                else None,
                "deploy": DeployConfig(
                    rules=[DeployRule(prefix=f"{d}/") for d in detection.service_dirs],
                    credentials=credentials,
                ),
            }
        )
    return WorkspaceConfig(repos=repos)


# --- rendering ------------------------------------------------------------------


def template(name: str) -> str:
    return (TEMPLATES / name).read_text()


def _repo_words(repos: Sequence[str]) -> dict[str, str]:
    return {
        "repo_names": ", ".join(repos) or "(none yet)",
        "repo_tags": ", ".join(f"[{name}]" for name in repos) or "[<repo>]",
        "example_repo": repos[0] if repos else "repo",
    }


def render_rules(repos: Sequence[str]) -> str:
    """The `rules:` block of openspec/config.yaml for these repos, stamped with
    the version it was written against."""
    body = template("openspec_rules.yaml").format(**_repo_words(repos))
    return f"{RULES_HEADER}\n{body}"


_RULES_STAMP = re.compile(r"^#\s*abk-rules:\s*v(?P<version>\d+)\s*$", re.M)


def rules_version(text: str) -> int | None:
    """The `# abk-rules: vN` stamp in a config.yaml, or None when it has none
    (written before the stamp existed, or by hand)."""
    match = _RULES_STAMP.search(text)
    return int(match["version"]) if match else None


def rules_of(text: str) -> dict:
    """The `rules` and `operations` mappings in a config.yaml (or rendered
    rules) text, for comparing one with another."""
    loaded = yaml.safe_load(text) or {}
    if not isinstance(loaded, dict):
        return {}
    return {key: loaded[key] for key in ("rules", "operations") if key in loaded}


def render_context(config: WorkspaceConfig) -> str:
    paragraphs = []
    for name, repo in config.repos.items():
        parts = [
            f"**{name}** — checked out at `{repo.path}`, GitHub `{repo.slug}`, "
            f"default branch `{repo.default_branch}`"
        ]
        if repo.languages:
            parts[0] += f", languages: {', '.join(repo.languages)}"
        parts[0] += "."
        if repo.description.strip():
            parts.append(repo.description.strip())
        if repo.consumes:
            parts.append(
                f"{name} consumes {', '.join(repo.consumes)}: a change to a shape "
                f"{name} imports lands there first."
            )
        if repo.relationships.strip():
            parts.append(repo.relationships.strip())
        paragraphs.append(" ".join(parts))
    repos_text = "\n\n".join(paragraphs) or "(no repos configured yet)"
    return template("openspec_context.md").format(repos=repos_text)


def render_openspec_config(config: WorkspaceConfig) -> str:
    context = "\n".join(
        f"  {line}" if line.strip() else "" for line in render_context(config).splitlines()
    )
    return f"schema: spec-driven\n\ncontext: |\n{context}\n\n{render_rules(list(config.repos))}"


def render_systemd(planning_dir: Path, *, tool_path: str = "") -> dict[str, str]:
    """Unit file name -> rendered text. `tool_path` is appended to the unit's
    PATH, each directory with its own leading colon."""
    return {
        path.name: path.read_text().format(planning_dir=planning_dir, tool_path=tool_path)
        for path in sorted((TEMPLATES / "systemd").iterdir())
        if path.suffix in (".service", ".timer")
    }


# --- writing --------------------------------------------------------------------


def is_unconfigured_openspec_config(path: Path) -> bool:
    """The stock config.yaml `openspec init` writes: only the schema, every
    other key a comment."""
    try:
        loaded = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        return False
    return isinstance(loaded, dict) and set(loaded) <= {"schema"}


def _write(path: Path, text: str, *, overwrite: bool, written: list[Path]) -> None:
    if path.exists() and not overwrite:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    written.append(path)


def write_planning_repo(
    planning_dir: Path,
    config: WorkspaceConfig,
    *,
    run_openspec: openspec.Run | None = None,
    force: bool = False,
) -> list[Path]:
    """Lay out the planning repo; returns the files written this time."""
    planning = planning_dir.expanduser().resolve()
    planning.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if not (planning / ".git").exists():
        result = subprocess.run(
            ["git", "init", "-q", "-b", "main"],
            cwd=planning,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            raise ScaffoldError(f"git init failed in {planning}: {result.stderr.strip()}")

    if not (planning / "openspec").exists():
        result = openspec.run(
            ["init", "--tools", "claude", "--no-animation"], cwd=planning, run=run_openspec
        )
        if result.returncode:
            raise ScaffoldError(
                f"openspec init failed in {planning}:\n{result.stdout}\n{result.stderr}".strip()
            )

    _write(planning / CONFIG_FILENAME, dump(config), overwrite=force, written=written)

    openspec_config = planning / "openspec" / "config.yaml"
    _write(
        openspec_config,
        render_openspec_config(config),
        overwrite=force or is_unconfigured_openspec_config(openspec_config),
        written=written,
    )

    state = planning / config.planning.state_dir
    _write(state / ".gitkeep", "", overwrite=False, written=written)
    _write(state / "units.json", '{"units": []}\n', overwrite=False, written=written)
    _write(planning / ".gitignore", template("gitignore"), overwrite=False, written=written)
    _write(planning / ".env.example", template("env.example"), overwrite=False, written=written)
    _write(
        planning / "CLAUDE.md",
        template("planning-CLAUDE.md").format(**_repo_words(list(config.repos))),
        overwrite=False,
        written=written,
    )
    # No systemd units here. One carries an absolute `WorkingDirectory`, so a
    # unit written at init time names whoever ran init and is wrong for everyone
    # who clones the repo afterwards. `abk install-timers` renders them on the
    # machine that will run them, named for this installation.

    installed, _refused = skills.install(planning / ".claude" / "skills")
    written.extend(installed)
    return written
