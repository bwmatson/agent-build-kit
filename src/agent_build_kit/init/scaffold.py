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
import os
import re
import textwrap
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

import yaml

from agent_build_kit import forges, openspec, skills
from agent_build_kit.config import (
    CLAUDE_CODE,
    CONFIG_FILENAME,
    OVERLAY_FILENAME,
    CredentialsConfig,
    DeployConfig,
    DeployRule,
    DevStackConfig,
    DraftedEnvironment,
    EnvironmentConfig,
    LimitsConfig,
    ModelsConfig,
    NamesFrom,
    ProjectConfig,
    RepoConfig,
    RuntimeConfig,
    RuntimeModelsConfig,
    WorkspaceConfig,
    dump,
)
from agent_build_kit.init.detect import RepoDetection
from agent_build_kit.init.environment import detect_environment, lock_patterns, unrecognised
from agent_build_kit.init.runtime_choice import merge_values
from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.changelog_convention import packaged_convention
from agent_build_kit.pipeline.file_lock import append_missing_lines
from agent_build_kit.pipeline.original_copy import COPY_PATTERN
from agent_build_kit.pipeline.planning_repo import toplevel
from agent_build_kit.pipeline.shell import git
from agent_build_kit.scrub_terms import LOCAL_LIST

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

    # A repo that holds the planning directory is named relative to it: `.` or `..`.
    planning_root = planning_dir.expanduser().resolve()
    top = toplevel(planning_root)
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
                "environment": detect_environment(
                    detection.path, framework=False, profile=detection.profile
                ),
                "path": Path(os.path.relpath(detection.path, planning_root))
                if holds_planning(top, planning_root, detection.path)
                else detection.path,
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
        global_limits=LimitsConfig(generated_files=tuple(patterns)),
        # The roles are the runtime's own names, written under it and not as a flat block.
        runtimes={
            CLAUDE_CODE: RuntimeConfig(
                models=RuntimeModelsConfig.model_validate(ModelsConfig().model_dump())
            )
        },
    )


def read_lines(path: Path) -> tuple[dict, list[str]]:
    """The parsed abk.yaml at `path` and its lines, the last one newline-terminated."""
    text = path.read_text()
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    return yaml.safe_load(text) or {}, lines


def _note(environment: EnvironmentConfig | None) -> str:
    return environment.note if isinstance(environment, DraftedEnvironment) else ""


def _block(key: str, value: object, indent: str, note: str = "") -> list[str]:
    """`key: value` dumped as block YAML, every line indented, under `note` as comments."""
    text = yaml.safe_dump({key: value}, sort_keys=False, default_flow_style=False)
    comments = [f"{indent}# {line}\n" for line in note.splitlines()]
    return comments + [f"{indent}{line}\n" for line in text.splitlines()]


# The `review` section as a fresh abk.yaml shows it: on, with every default, commented out.
REVIEW_BLOCK = """
# The review policy (see docs/configuration.md). Only a person edits it; uncomment to use it.
# review:
#   protected_paths: []
#   protected_defaults: true
#   classes: {}
#   auto_land: {min_samples: 20, min_clean_rate: 0.95, classes: []}
#   audit: {sample_rate: 0.1}
#   demotion: {window: 30, min_agreement: 0.9}
#   brief: true
"""


def dump_with_notes(config: WorkspaceConfig) -> str:
    """`dump(config)` with each drafted environment's note as comments above its section, and
    the commented `review` block at the end."""
    lines = dump(config).splitlines(keepends=True)
    sections = [(None, config.environment)] + [(n, r.environment) for n, r in config.repos.items()]
    for name, environment in reversed(sections):
        note = _note(environment)
        if not note:
            continue
        start, stop = 0, len(lines)
        if name is not None:
            repos = key_line(lines, "repos", top=True)
            at = key_line(
                lines, name, start=(repos or 0) + 1, stop=top_level_end(lines, repos or 0)
            )
            if at is None:
                continue
            start = at + 1
        found = key_line(lines, "environment", start=start, stop=stop, top=name is None)
        if found is None:
            continue
        indent = lines[found][: indent_of(lines[found])]
        lines[found:found] = [f"{indent}# {line}\n" for line in note.splitlines()]
    return "".join(lines) + REVIEW_BLOCK


def child_indent(lines: list[str], at: int, parent: int) -> str:
    """The indent of the first entry under `lines[at]`, else two more than its parent's."""
    for line in lines[at + 1 :]:
        body = line.strip()
        if not body or body.startswith("#"):
            continue
        indent = indent_of(line)
        return " " * indent if indent > parent else " " * (parent + 2)
    return " " * (parent + 2)


def key_line(
    lines: list[str], key: str, *, start: int = 0, stop: int | None = None, top: bool = False
) -> int | None:
    """The index of the first line that is `key:` alone (a comment may follow);
    with `top`, one that is not indented."""
    margin = "" if top else r"\s*"
    pattern = re.compile(rf"^{margin}['\"]?{re.escape(key)}['\"]?:\s*(#.*)?$")
    for index in range(start, len(lines) if stop is None else stop):
        if pattern.match(lines[index].rstrip("\n")):
            return index
    return None


def top_level_end(lines: list[str], start: int) -> int:
    """The index of the next top-level key after `lines[start]`, or the end."""
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.startswith((" ", "#", "\t")):
            return index
    return len(lines)


def block_end(lines: list[str], at: int, inside: Callable[[str], bool]) -> int:
    """The index after the block opened at `lines[at]`: its last line `inside` accepts,
    not counting the blank and comment lines that trail it, which belong to what follows."""
    end = at + 1
    for index in range(at + 1, len(lines)):
        body = lines[index].strip()
        if not body or body.startswith("#"):
            continue
        if not inside(lines[index]):
            break
        end = index + 1
    return end


def indent_of(line: str) -> int:
    return len(line) - len(line.lstrip())


def key_at(lines: list[str], key: str, *, start: int, stop: int, indent: int) -> int | None:
    """Like `key_line`, but only a `key:` indented exactly `indent` (one nested deeper, or
    inside a block scalar, is not the key)."""
    at = key_line(lines, key, start=start, stop=stop)
    while at is not None and indent_of(lines[at]) != indent:
        at = key_line(lines, key, start=at + 1, stop=stop)
    return at


def repo_block(lines: list[str], repo: str) -> tuple[int, int, int] | None:
    """Where `repo`'s block entry under a block `repos:` is: the index of its key line, the
    index after its last content line and the width of its indent; None when it has none
    (no `repos:`, a flow-style repo)."""
    repos = key_line(lines, "repos", top=True)
    if repos is None:
        return None
    width = len(child_indent(lines, repos, 0))
    at = key_at(lines, repo, start=repos + 1, stop=top_level_end(lines, repos), indent=width)
    if at is None:
        return None
    return at, block_end(lines, at, lambda line: indent_of(line) > width), width


def checked(path: Path, updated: str, expected: object) -> None:
    """Raise `ScaffoldError` naming `path` unless the edited text `updated` parses to exactly
    the document `expected`."""
    try:
        loaded = yaml.safe_load(updated)
    except yaml.YAMLError:
        loaded = None
    if loaded != expected:
        raise ScaffoldError(f"{path}: the entry did not produce a valid file; left alone")


def add_project(path: Path, repo: str, entry: Mapping[str, str]) -> None:
    """Append `entry` to `repo`'s `projects:` list in the abk.yaml at `path`, creating the
    list when the repo has none. Every other line stays as it is. A layout whose place
    cannot be found as a block (a flow-style repo or `projects: []`), or a result that does
    not parse to the file plus the entry, raises `ScaffoldError` and leaves the file alone."""
    raw, lines = read_lines(path)
    entry_raw = (raw.get("repos") or {}).get(repo)
    block = repo_block(lines, repo)
    if block is None or not isinstance(entry_raw, dict):
        raise ScaffoldError(f"{path}: cannot find a block entry for repo {repo!r} under `repos:`")
    at, repo_end, width = block
    child = child_indent(lines, at, width)
    projects = key_at(lines, "projects", start=at + 1, stop=repo_end, indent=len(child))
    if projects is None and "projects" in entry_raw:
        raise ScaffoldError(f"{path}: `projects:` of {repo!r} is not a block list; edit it by hand")
    if projects is None:
        lines[repo_end:repo_end] = [
            f"{child}projects:\n",
            *_list_item(entry, child + "  "),
        ]
    else:
        listed = block_end(
            lines,
            projects,
            lambda line: (
                indent_of(line) > len(child)
                or (indent_of(line) == len(child) and line.lstrip().startswith("-"))
            ),
        )
        existing = next(
            (line for line in lines[projects + 1 : listed] if line.lstrip().startswith("- ")),
            None,
        )
        indent = " " * indent_of(existing) if existing else child + "  "
        lines[listed:listed] = _list_item(entry, indent)
    updated = "".join(lines)

    expected = {**raw, "repos": {**raw["repos"]}}
    expected["repos"][repo] = {
        **entry_raw,
        "projects": [*(entry_raw.get("projects") or []), dict(entry)],
    }
    checked(path, updated, expected)
    path.write_text(updated)


def _list_item(entry: Mapping[str, str], indent: str) -> list[str]:
    """One list item, dumped as block YAML and indented."""
    text = yaml.safe_dump([dict(entry)], sort_keys=False, default_flow_style=False)
    return [f"{indent}{line}\n" for line in text.splitlines()]


def fill_missing_environment(
    path: Path, drafted: WorkspaceConfig, *, dry_run: bool = False
) -> dict[str, str]:
    """Add what an existing abk.yaml lacks of the environment: the planning
    section, each listed repo's section, and the generated-file patterns.
    Every line the file already has stays as it is; what is missing is added
    as text, a block at a time. A part whose place in the file cannot be found
    as a block (a flow-style `limits: {}`) is left for a person. Returns, for
    each part filled (or that would be), its drafted YAML."""
    raw, lines = read_lines(path)
    drafted_raw = yaml.safe_load(dump(drafted)) or {}
    filled: dict[str, str] = {}

    # A planning section nothing was recognised for is not added to a file that
    # loads without it: empty commands would stop it loading.
    if "environment" not in raw and drafted_raw.get("environment", {}).get("sync"):
        block = _block("environment", drafted_raw["environment"], "", _note(drafted.environment))
        lines += block
        filled["environment"] = "".join(block)

    for name, entry in (raw.get("repos") or {}).items():
        wanted = drafted_raw.get("repos", {}).get(name, {}).get("environment")
        if not (isinstance(entry, dict) and "environment" not in entry and wanted):
            continue
        section = key_line(lines, "repos", top=True)
        if section is None:
            continue
        at = key_line(lines, str(name), start=section + 1, stop=top_level_end(lines, section))
        if at is None:
            continue
        parent = indent_of(lines[at])
        indent = child_indent(lines, at, parent)
        note = _note(drafted.repos[name].environment) if name in drafted.repos else ""
        lines[at + 1 : at + 1] = _block("environment", wanted, indent, note)
        filled[f"repos.{name}.environment"] = "".join(_block("environment", wanted, "", note))

    patterns = drafted_raw.get("global_limits", {}).get("generated_files")
    # An existing `limits` block is the old spelling of `global_limits`: extended as it is.
    key = "limits" if "global_limits" not in raw and "limits" in raw else "global_limits"
    limits = raw.get(key)
    if patterns and "generated_files" not in (limits or {}):
        at = key_line(lines, key, top=True)
        if at is not None:
            lines[at + 1 : at + 1] = _block("generated_files", patterns, child_indent(lines, at, 0))
        elif key not in raw:
            lines += _block(key, {"generated_files": patterns}, "")
        if at is not None or key not in raw:
            filled[f"{key}.generated_files"] = "".join(_block("generated_files", patterns, ""))

    if filled and not dry_run:
        path.write_text("".join(lines))
    return filled


def record_in_file(path: Path, fragment: Mapping[str, Any]) -> None:
    """Lay `fragment` over an abk.yaml that is kept: each top-level key it names is
    replaced by its merge with the file's, and every other line stays as it is."""
    raw, lines = read_lines(path)
    for key, value in fragment.items():
        block = _block(key, merge_values(raw.get(key), value, at=key), "")
        start = next((i for i, line in enumerate(lines) if line.startswith(f"{key}:")), None)
        if start is None:
            lines += block
        else:
            lines[start : top_level_end(lines, start)] = block
    path.write_text("".join(lines))


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


# What an installation keeps to itself: the configuration overlay, the local scrub list and the
# redaction originals.
LOCAL_IGNORES = (OVERLAY_FILENAME, LOCAL_LIST, COPY_PATTERN)


def _ensure_ignored(path: Path, lines: tuple[str, ...], *, written: list[Path]) -> None:
    if append_missing_lines(path, lines) and path not in written:
        written.append(path)


def holds_planning(top: Path | None, planning_root: Path, repo_path: Path) -> bool:
    """Whether the repo at `repo_path` (relative to `planning_root` unless absolute) is the
    repository whose top is `top`, the one the planning directory is in. The one rule for
    a planning repo that is also a code repo."""
    return top is not None and (planning_root / repo_path).expanduser().resolve() == top


def holding_repo(planning: Path, config: WorkspaceConfig) -> Path | None:
    """The top of the repository the planning directory is in when that repository is one of
    the configured repos, else None: the planning repo is then also a code repo."""
    root = planning.expanduser().resolve()
    top = toplevel(root)
    return top if any(holds_planning(top, root, r.path) for r in config.repos.values()) else None


_IGNORE_OPEN = "# abk:planning v1"
_IGNORE_CLOSE = "# /abk:planning"
_IGNORE_START = re.compile(r"# abk:planning v\w+")
_IGNORE_END = re.compile(re.escape(_IGNORE_CLOSE))
_ORIENT_OPEN = "<!-- abk:planning v1 -->"
_ORIENT_CLOSE = "<!-- /abk:planning -->"
_ORIENT_START = re.compile(r"<!-- abk:planning v\w+ -->")
_ORIENT_END = re.compile(re.escape(_ORIENT_CLOSE))


def _state_ignores(state_dir: str) -> list[str]:
    """The template's lines about the state directory and the redaction originals."""
    lines = [line.strip() for line in template("gitignore").splitlines()]
    return [
        f"{state_dir}/{line.removeprefix('runs/')}" if line.startswith("runs/") else line
        for line in lines
        if line.startswith("runs/") or line == COPY_PATTERN
    ]


def _read_text(path: Path) -> str:
    """The file's text, byte for byte; a file that is not UTF-8 is a `ScaffoldError`, since
    writing it back would change its bytes."""
    try:
        return path.read_bytes().decode()
    except UnicodeDecodeError:
        raise ScaffoldError(f"{path} is not valid UTF-8; add the abk block to it by hand") from None


def missing_state_ignores(text: str, state_dir: str) -> list[str]:
    """The state-directory lines the template ignores that `text` lacks; none for a state
    outside the repository, which has nothing to ignore."""
    if Path(state_dir).expanduser().is_absolute():
        return []
    present = {line.strip() for line in text.splitlines()}
    return [line for line in _state_ignores(state_dir) if line not in present]


def _local_ignores(text: str, state_dir: str) -> list[str]:
    """For a state outside the repository, the lines the block still carries that `text` lacks."""
    if not Path(state_dir).expanduser().is_absolute():
        return []
    present = {line.strip() for line in text.splitlines()}
    template_lines = [line.strip() for line in template("gitignore").splitlines()]
    kept = [line for line in template_lines if line in (".env", ".last-runs/")]
    return [line for line in (*kept, *LOCAL_IGNORES) if line not in present]


def _ignore_block(text: str, state_dir: str) -> str:
    """The `.gitignore` text with the state lines it lacks in one marker block."""
    span = find_block(text, _IGNORE_START, _IGNORE_END)
    outside = text if span is None else text[: span[0]] + text[span[1] :]
    missing = [*missing_state_ignores(outside, state_dir), *_local_ignores(outside, state_dir)]
    if not missing:
        return text
    eol = _eol(text)
    block = eol.join([_IGNORE_OPEN, *missing, _IGNORE_CLOSE]) + eol
    return splice_block(text, _IGNORE_START, _IGNORE_END, block, eol=eol, blank=False)


def _shown(inst: Installation, path: Path, prefix: str) -> str:
    """A path as the orientation names it: under the planning directory with `prefix`, or the
    absolute path when it is elsewhere."""
    shown = inst.shown(path)
    return shown if Path(shown).is_absolute() else f"{prefix}{shown}"


def _orientation(inst: Installation, prefix: str) -> str:
    body = template("planning-orientation.md").format(
        prefix=prefix,
        specs_dir=inst.config.planning.specs_dir,
        state_dir=_shown(inst, inst.state_dir, prefix),
        graph_page=_shown(inst, inst.graph_page, prefix),
    )
    return f"{_ORIENT_OPEN}\n{body}{_ORIENT_CLOSE}\n"


def _rewrite(path: Path, text: str, *, written: list[Path]) -> None:
    """Writes `text` as `path`'s bytes when they differ."""
    if not path.exists() or path.read_bytes() != text.encode():
        _put(path, text, False)
        written.append(path)


def _in_repo_blocks(planning: Path, top: Path, config: WorkspaceConfig) -> list[tuple[Path, str]]:
    """The two files init adds a marker block to, with their new text: the planning directory's
    `.gitignore` and the repository's guidance file. Raises `ScaffoldError` before anything is
    written when a file cannot take its block."""
    ignore = planning / ".gitignore"
    guidance = guidance_file(top)
    try:
        ignore_text = _read_text(ignore) if ignore.exists() else ""
        text = _read_text(guidance) if guidance.exists() else ""
        eol = _eol(text)
        prefix = "" if planning == top else f"{planning.relative_to(top).as_posix()}/"
        inst = Installation(config, planning)
        block = _orientation(inst, prefix).replace("\n", eol)
        return [
            (ignore, _ignore_block(ignore_text, inst.shown(inst.state_dir))),
            (guidance, splice_block(text, _ORIENT_START, _ORIENT_END, block, eol=eol)),
        ]
    except MarkersError:
        raise ScaffoldError(
            f"mismatched abk:planning markers in {ignore} or {guidance}; fix them by hand"
        ) from None


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

    top = holding_repo(planning, config)
    blocks = _in_repo_blocks(planning, top, config) if top else []

    if top is None and not (planning / ".git").exists():
        result = git(planning, "init", "-q", "-b", "main", check=False)
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

    _write(planning / CONFIG_FILENAME, dump_with_notes(config), overwrite=force, written=written)

    openspec_config = planning / "openspec" / "config.yaml"
    _write(
        openspec_config,
        render_openspec_config(config),
        overwrite=force or is_unconfigured_openspec_config(openspec_config),
        written=written,
    )

    state = Installation(config, planning).state_dir
    if state.is_relative_to(planning):
        _write(state / ".gitkeep", "", overwrite=False, written=written)
        _write(state / "units.json", '{"units": []}\n', overwrite=False, written=written)
    _write(planning / ".env.example", template("env.example"), overwrite=False, written=written)
    if top:
        # The repo's own files: only a marker block is added to each, nothing else changes.
        for path, text in blocks:
            _rewrite(path, text, written=written)
    else:
        _write(planning / ".gitignore", template("gitignore"), overwrite=False, written=written)
        _ensure_ignored(planning / ".gitignore", LOCAL_IGNORES, written=written)
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


class MarkersError(ValueError):
    """A file holds an opening marker without a closing one after it, or the reverse."""


def find_block(text: str, start: re.Pattern[str], end: re.Pattern[str]) -> tuple[int, int] | None:
    """The span of the one marker-bracketed block in `text`, None when there is none; raises
    `MarkersError` for markers that do not pair up."""
    opens, closes = list(start.finditer(text)), list(end.finditer(text))
    if len(opens) != len(closes) or (opens and opens[0].start() > closes[0].start()):
        raise MarkersError("mismatched markers")
    return (opens[0].start(), closes[0].end()) if opens else None


def splice_block(
    text: str,
    start: re.Pattern[str],
    end: re.Pattern[str],
    block: str,
    *,
    eol: str,
    blank: bool = True,
) -> str:
    """`text` with `block` (ending in `eol`) in place of the block already there, else appended,
    after a blank line when `blank`, or directly after the last line."""
    span = find_block(text, start, end)
    if span:
        first, last = span
        if text[last : last + len(eol)] == eol:
            last += len(eol)
        return text[:first] + block + text[last:]
    if not text:
        return block
    separator = "" if text.endswith("\n") else eol
    return text + separator + (eol if blank else "") + block


def guidance_file(root: Path) -> Path:
    """The repo's own guidance file: `AGENTS.md`, else `CLAUDE.md`, else `AGENTS.md` to create."""
    return next(
        (root / n for n in ("AGENTS.md", "CLAUDE.md") if (root / n).is_file()), root / "AGENTS.md"
    )


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
    path = guidance_file(root)

    def result(kind: Outcome, note: str = "") -> ConventionResult:
        return ConventionResult(repo=repo, action="block", path=path, result=kind, note=note)

    if not path.is_file():
        _put(path, _block_text(changelog, "\n"), dry_run)
        return result("created")
    try:
        text = _read_text(path)
        eol = _eol(text)
        updated = splice_block(text, _BLOCK_START, _BLOCK_END, _block_text(changelog, eol), eol=eol)
    except MarkersError:
        return result("skipped", "mismatched abk:changelog markers; fix them by hand")
    except ScaffoldError as error:
        return result("skipped", str(error))
    if updated == text:
        return result("unchanged")
    if not _BLOCK_START.search(text) and re.search(
        r"^## changelog", text, re.IGNORECASE | re.MULTILINE
    ):
        return result("skipped", f"{path.name} has its own Changelog section")
    _put(path, updated, dry_run)
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
        # init runs before an installation exists, so the configured path is all there is
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
