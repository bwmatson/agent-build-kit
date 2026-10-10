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

import hashlib
import re
import subprocess
import textwrap
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

import yaml

from agent_build_kit import forges, openspec, skills
from agent_build_kit.config import (
    CONFIG_FILENAME,
    CredentialsConfig,
    DeployConfig,
    DeployRule,
    DevStackConfig,
    LimitsConfig,
    NamesFrom,
    ProjectConfig,
    RepoConfig,
    WorkspaceConfig,
    dump,
)
from agent_build_kit.init.detect import RepoDetection
from agent_build_kit.init.environment import detect_environment, lock_patterns, unrecognised
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.changelog_convention import packaged_convention

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
                "environment": detect_environment(detection.path, framework=False),
                "path": detection.path,
                "forge": forge.name,
                **named,
                "default_branch": detection.default_branch,
                "profile": detection.profile,
                "infra": detection.infra,
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
    planning_environment = detect_environment(planning_dir, framework=True) or unrecognised()
    patterns = lock_patterns(planning_environment, *(r.environment for r in repos.values()))
    return WorkspaceConfig(
        environment=planning_environment,
        repos=repos,
        limits=LimitsConfig(generated_files=tuple(patterns)),
    )


def fill_missing_environment(
    path: Path, drafted: WorkspaceConfig, *, dry_run: bool = False
) -> list[str]:
    """Add what an existing abk.yaml lacks of the environment: the planning
    section, each listed repo's section, and the generated-file patterns.
    What the file already says is not touched. Returns what was (or would be)
    filled."""
    raw = yaml.safe_load(path.read_text()) or {}
    drafted_raw = yaml.safe_load(dump(drafted)) or {}
    filled: list[str] = []
    # A planning section nothing was recognised for is not added to a file that
    # loads without it: empty commands would stop it loading.
    if "environment" not in raw and drafted_raw.get("environment", {}).get("sync"):
        raw["environment"] = drafted_raw["environment"]
        filled.append("environment")
    repos = raw.get("repos") or {}
    for name, entry in repos.items():
        wanted = drafted_raw.get("repos", {}).get(name, {}).get("environment")
        if isinstance(entry, dict) and "environment" not in entry and wanted:
            entry["environment"] = wanted
            filled.append(f"repos.{name}.environment")
    patterns = drafted_raw.get("limits", {}).get("generated_files")
    limits = raw.get("limits") or {}
    if patterns and "generated_files" not in limits:
        raw["limits"] = {**limits, "generated_files": patterns}
        filled.append("limits.generated_files")
    if filled and not dry_run:
        path.write_text(yaml.safe_dump(raw, sort_keys=False, default_flow_style=False))
    return filled


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


# version -> the paragraph an update adds to an installation's `context:` for
# that version, for the versions whose change is a convention the context
# carries. The same sentences are in the context template a fresh `abk init`
# writes (a test holds the two together), so an updated file and a new one say
# the same thing; an installation rewords it afterwards like the rest.
RULES_UPDATES: dict[int, str] = {
    2: (
        "A file that moves or is renamed moves with `git mv`, in a commit that does "
        "nothing else. Git then records a rename rather than a delete beside an add, "
        "so `git log --follow` and `git blame` still reach the file's history and a "
        "reviewer can see at a glance that the contents did not change. Editing it "
        "belongs in a later commit."
    ),
}

_RULES_STAMP = re.compile(r"^#\s*abk-rules:\s*v(?P<version>\d+)\s*$", re.M)


def rules_version(text: str) -> int | None:
    """The `# abk-rules: vN` stamp in a config.yaml, or None when it has none
    (written before the stamp existed, or by hand)."""
    match = _RULES_STAMP.search(text)
    return int(match["version"]) if match else None


def update_rules(config_yaml: Path) -> list[int]:
    """Bring an `openspec/config.yaml` up to this framework's rules version
    without rewriting it, and return the versions applied.

    The file is the installation's own wording, so nothing is regenerated:
    each version since the file's stamp adds its paragraph (`RULES_UPDATES`)
    to the end of the `context:` block, and the stamp becomes the current
    version. Everything else — the comments, the rules, every word the
    installation changed — is left byte for byte. A file with no stamp, or at
    a version whose change this cannot apply, is refused: guessing what it
    lacks is how a hand-written rule gets doubled or dropped.
    """
    text = config_yaml.read_text()
    stamped = rules_version(text)
    if stamped is None:
        raise ScaffoldError(
            f"{config_yaml} carries no `# abk-rules:` stamp, so what it lacks cannot be told; "
            f"add `{RULES_HEADER}` once it has what `abk init` would write"
        )
    if stamped > RULES_VERSION:
        raise ScaffoldError(
            f"{config_yaml} is stamped v{stamped}, newer than this framework's v{RULES_VERSION}"
        )
    versions = list(range(stamped + 1, RULES_VERSION + 1))
    missing = [v for v in versions if v not in RULES_UPDATES]
    if missing:
        raise ScaffoldError(
            f"{config_yaml}: v{missing[0]} changed more than the context, so it cannot be "
            "applied automatically; see `abk doctor` for what changed"
        )
    if not versions:
        return []

    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if re.match(r"^context:\s*\|", line)), None)
    if start is None:
        raise ScaffoldError(f"{config_yaml} has no `context: |` block to add to")
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end][0] in " \t"):
        end += 1
    last = end
    while last > start + 1 and not lines[last - 1].strip():
        last -= 1  # the block's last line of text, before its trailing blank lines
    added = ""
    for version in versions:
        wrapped = textwrap.fill(
            RULES_UPDATES[version], width=78, initial_indent="  ", subsequent_indent="  "
        )
        added += f"\n{wrapped}\n"
    lines[last:last] = [added]
    updated = "".join(lines)
    updated = _RULES_STAMP.sub(RULES_HEADER, updated, count=1)

    loaded = yaml.safe_load(updated)
    context = " ".join(str(loaded.get("context", "")).split()) if isinstance(loaded, dict) else ""
    if not all(RULES_UPDATES[v] in context for v in versions):
        raise ScaffoldError(f"{config_yaml}: the update did not produce a valid file; left alone")
    config_yaml.write_text(updated)
    return versions


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


# --- code repos -----------------------------------------------------------------


Outcome = Literal["created", "updated", "unchanged", "skipped"]
_BLOCK_OPEN = "<!-- abk:changelog v%s -->"
_BLOCK_CLOSE = "<!-- /abk:changelog -->"
_BLOCK_START = re.compile(r"<!-- abk:changelog v\w+ -->")
_BLOCK_END = re.compile(re.escape(_BLOCK_CLOSE))


class ConventionResult(Frozen):
    """What one action did, or with `dry_run` would do, in one code repo.

    `result` is `created`, `updated`, `unchanged` or `skipped`; a skip that is
    a finding to report (mismatched markers, a conflicting merge rule, a repo's
    own changelog section) carries it in `note`."""

    repo: str
    action: Literal["block", "changelog", "gitattributes"]
    path: Path
    result: Outcome
    note: str = ""


def merge_attribute(attributes: str, path: str) -> str | None:
    """What a `.gitattributes` text says of `path`'s merge driver: the driver's name
    (`union`), the token itself for any other form (`-merge`), or None for no word."""
    found = None
    for line in attributes.splitlines():
        pattern, *tokens = line.split() or [""]
        if pattern not in (path, f"/{path}"):
            continue
        for token in tokens:
            if token.startswith("merge="):
                found = token.removeprefix("merge=")
            elif token in ("merge", "-merge", "!merge"):
                found = token
    return found


def _eol(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _block_text(changelog: str, eol: str) -> str:
    body = packaged_convention(changelog)
    inner = f"## Changelog\n\n{body}\n"
    stamp = hashlib.sha256(inner.encode()).hexdigest()[:8]
    block = f"{_BLOCK_OPEN % stamp}\n{inner}{_BLOCK_CLOSE}\n"
    return block.replace("\n", eol)


def _put(path: Path, text: str, dry_run: bool) -> None:
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode())


def _block_action(root: Path, repo: str, changelog: str, dry_run: bool) -> ConventionResult:
    path = next(
        (root / n for n in ("AGENTS.md", "CLAUDE.md") if (root / n).is_file()), root / "AGENTS.md"
    )

    def result(kind: Outcome, note: str = "") -> ConventionResult:
        return ConventionResult(repo=repo, action="block", path=path, result=kind, note=note)

    if not path.is_file():
        _put(path, _block_text(changelog, "\n"), dry_run)
        return result("created")
    text = path.read_bytes().decode(errors="replace")
    eol = _eol(text)
    opens = list(_BLOCK_START.finditer(text))
    closes = list(_BLOCK_END.finditer(text))
    if len(opens) != len(closes) or (opens and opens[0].start() > closes[0].start()):
        return result("skipped", "mismatched abk:changelog markers; fix them by hand")
    block = _block_text(changelog, eol)
    if opens:
        start, end = opens[0].start(), closes[0].end()
        if text[end : end + len(eol)] == eol:
            end += len(eol)
        if text[start:end] == block:
            return result("unchanged")
        _put(path, text[:start] + block + text[end:], dry_run)
        return result("updated")
    if re.search(r"^## changelog", text, re.IGNORECASE | re.MULTILINE):
        return result("skipped", f"{path.name} has its own Changelog section")
    if not text:
        separator = ""
    else:
        separator = eol if text.endswith("\n") else eol * 2
    _put(path, f"{text}{separator}{block}", dry_run)
    return result("updated")


def _changelog_action(root: Path, repo: str, changelog: str, dry_run: bool) -> ConventionResult:
    path = root / changelog
    if path.exists():
        kind: Outcome = "unchanged"
    else:
        _put(path, "# Changelog\n\n## Unreleased\n", dry_run)
        kind = "created"
    return ConventionResult(repo=repo, action="changelog", path=path, result=kind)


def _gitattributes_action(root: Path, repo: str, changelog: str, dry_run: bool) -> ConventionResult:
    path = root / ".gitattributes"

    def result(kind: Outcome, note: str = "") -> ConventionResult:
        return ConventionResult(
            repo=repo, action="gitattributes", path=path, result=kind, note=note
        )

    rule = f"{changelog} merge=union"
    if not path.is_file():
        _put(path, f"{rule}\n", dry_run)
        return result("created")
    text = path.read_bytes().decode(errors="replace")
    merge = merge_attribute(text, changelog)
    if merge == "union":
        return result("unchanged")
    if merge is not None:
        return result("skipped", f"{changelog} already has a merge setting ({merge}); left as is")
    eol = _eol(text)
    lead = "" if not text or text.endswith("\n") else eol
    _put(path, f"{text}{lead}{rule}{eol}", dry_run)
    return result("updated")


def write_code_repo_conventions(
    workspace: WorkspaceConfig, *, dry_run: bool = False
) -> list[ConventionResult]:
    """Put the changelog convention block, the changelog file and the union-merge
    rule into every listed repo whose checkout exists and whose `changelog` is
    set; one result per repo and action. With `dry_run` nothing is written."""
    results: list[ConventionResult] = []
    for name, repo in workspace.repos.items():
        root = repo.path.expanduser()
        if repo.changelog is None or not root.is_dir():
            note = "changelog convention is off" if repo.changelog is None else "no checkout"
            results += [
                ConventionResult(
                    repo=name, action=action, path=root / file, result="skipped", note=note
                )
                for action, file in (
                    ("block", "AGENTS.md"),
                    ("changelog", repo.changelog or "CHANGELOG.md"),
                    ("gitattributes", ".gitattributes"),
                )
            ]
            continue
        results += [
            _block_action(root, name, repo.changelog, dry_run),
            _changelog_action(root, name, repo.changelog, dry_run),
            _gitattributes_action(root, name, repo.changelog, dry_run),
        ]
    return results
