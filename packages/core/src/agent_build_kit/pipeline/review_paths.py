"""The paths that never land without a person: the framework's defaults and the installation's."""

from __future__ import annotations

import configparser
import json
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_build_kit.config import WorkspaceConfig
from agent_build_kit.path_patterns import matches
from agent_build_kit.pipeline.shell import git
from agent_build_kit.profiles.protected_config import PROTECTED_CONFIG_DEFAULTS

# Database migrations, CI and deploy configuration, container definitions, secrets and key
# material, and ownership files.
PROTECTED_DEFAULTS: tuple[str, ...] = (
    "**/migrations/**",
    ".github/**",
    ".gitlab-ci.yml",
    ".circleci/**",
    "**/Dockerfile",
    "**/Dockerfile.*",
    "**/docker-compose*.yml",
    "**/docker-compose*.yaml",
    "**/compose*.yml",
    "**/compose*.yaml",
    "**/.env",
    "**/.env.*",
    "**/secrets/**",
    "**/*.pem",
    "**/*.key",
    "**/CODEOWNERS",
)

QUALITY_BASELINE = "quality_baseline.toml"


def protected_config(config: WorkspaceConfig, repo: str) -> dict[str, tuple[str, ...]]:
    """Pattern to key paths for `repo`: the defaults (unless switched off), the workspace's
    entries and the repo's, which add. A pattern with no key path protects the whole file, and
    does so whatever other entries add keys to it."""
    review = config.review
    sources: list[Mapping[str, Any]] = [review.protected_config]
    if repo in config.repos:
        sources.append(config.repos[repo].review.protected_config)
    if review.protected_defaults:
        sources.insert(0, PROTECTED_CONFIG_DEFAULTS)
    merged: dict[str, tuple[str, ...]] = {}
    whole: set[str] = set()
    for source in sources:
        for pattern, keys in source.items():
            if not keys:
                whole.add(pattern)
            merged[pattern] = (*merged.get(pattern, ()), *keys)
    return {p: () if p in whole else tuple(dict.fromkeys(k)) for p, k in merged.items()}


def protected_globs(config: WorkspaceConfig, repo: str) -> tuple[str, ...]:
    """The globs protecting `repo`: the defaults (unless switched off), the workspace's list
    and the repo's own, which only ever adds, and the files protected whole."""
    review = config.review
    own = config.repos[repo].review.protected_paths if repo in config.repos else []
    defaults = PROTECTED_DEFAULTS if review.protected_defaults else ()
    whole = tuple(p for p, keys in protected_config(config, repo).items() if not keys)
    return (*defaults, *review.protected_paths, *own, *whole)


def glob_matches(glob: str, path: str, *, unparsed: bool) -> bool:
    """Whether `glob` matches `path`; `unparsed` is the answer for a glob that does not parse,
    which `abk doctor` reports and a decision must not raise on."""
    try:
        return matches(glob, path)
    except ValueError:
        return unparsed


def is_protected(config: WorkspaceConfig, repo: str, path: str) -> bool:
    """Whether `path` in `repo` is matched by the repo's protected globs. A glob that does not
    parse protects: the safe answer when the policy cannot be read."""
    return any(glob_matches(g, path, unparsed=True) for g in protected_globs(config, repo))


class _Unreadable(Exception):
    """A side of a file could not be read from git."""


_MISSING = object()


def _read(checkout: Path, rev: str, path: str) -> str | None:
    """The file at `rev`, or None when it is absent there."""
    spec = f"{rev}:{path}"
    try:
        if git(checkout, "cat-file", "-e", spec, check=False).returncode != 0:
            return None
        shown = git(checkout, "show", spec, check=False)
    except OSError as error:
        raise _Unreadable from error
    if shown.returncode != 0:
        raise _Unreadable
    return shown.stdout


def _parse(path: str, text: str | None) -> Any:
    """The file's content as a mapping (an absent file is empty); ValueError when it does not
    parse; the text itself for an extension read as a whole file."""
    if text is None:
        return {}
    suffix = path.rsplit(".", 1)[-1]
    try:
        if suffix == "toml":
            return tomllib.loads(text)
        if suffix == "json":
            return json.loads(text)
        if suffix in ("cfg", "ini"):
            parser = configparser.RawConfigParser(interpolation=None, strict=False)
            parser.read_string(text)
            return {name: dict(parser.items(name)) for name in parser.sections()}
    except (ValueError, configparser.Error) as error:
        raise ValueError(str(error)) from error
    return text


def _value(document: Any, key: str) -> Any:
    """The value at the dotted `key`, an INI section being named by the whole key."""
    if not isinstance(document, dict):
        return document
    if key in document:
        return document[key]
    node: Any = document
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _baseline_entries(text: str | None) -> dict[tuple[str, ...], dict[str, Any]]:
    document = _parse(QUALITY_BASELINE, text)
    entries: dict[tuple[str, ...], dict[str, Any]] = {}
    for table, identity in (("files", ("path",)), ("functions", ("path", "name"))):
        for entry in document.get(table, []):
            key = (table, *(str(entry.get(field)) for field in identity))
            entries[key] = {k: v for k, v in entry.items() if k not in identity}
    return entries


def _grows(
    before: dict[tuple[str, ...], dict[str, Any]], after: dict[tuple[str, ...], dict[str, Any]]
) -> bool:
    """Whether `after` holds an entry, a measure or a higher value that `before` lacks."""
    for key, measures in after.items():
        if key not in before:
            return True
        for name, value in measures.items():
            if name not in before[key]:
                return True
            old = before[key][name]
            numbers = all(isinstance(v, int | float) for v in (old, value))
            if (numbers and value > old) or (not numbers and value != old):
                return True
    return False


def _baseline_change(checkout: Path, merge_base: str) -> str | None:
    before_text = _read(checkout, merge_base, QUALITY_BASELINE)
    after_text = _read(checkout, "HEAD", QUALITY_BASELINE)
    if after_text is None:
        return "deleted" if before_text is not None else None
    try:
        grown = _grows(_baseline_entries(before_text), _baseline_entries(after_text))
    except (ValueError, AttributeError, TypeError):
        return "does not parse"
    return "grows" if grown else None


def _keyed_changes(checkout: Path, merge_base: str, path: str, keys: tuple[str, ...]) -> list[str]:
    before_text = _read(checkout, merge_base, path)
    after_text = _read(checkout, "HEAD", path)
    try:
        before, after = _parse(path, before_text), _parse(path, after_text)
    except ValueError:
        return ["does not parse"]
    if isinstance(before, str) or isinstance(after, str):
        return [] if before == after else ["changed"]
    return [key for key in sorted(keys) if _value(before, key) != _value(after, key)]


def _merge_base(checkout: Path, base: str) -> str | None:
    try:
        result = git(checkout, "merge-base", base, "HEAD", check=False)
    except OSError:
        return None
    return result.stdout.strip() or None if result.returncode == 0 else None


def protected_settings(
    config: WorkspaceConfig, repo: str, checkout: Path, base: str, paths: tuple[str, ...]
) -> tuple[str, ...]:
    """One description per protected change among `paths`, the branch's changed paths: a key
    path of a keyed file whose value differs between the merge-base and `HEAD`, or a quality
    baseline that grows. Never raises: what cannot be checked is reported as a change."""
    keyed = {p: k for p, k in protected_config(config, repo).items() if k}
    baseline = config.review.protected_defaults
    found: list[str] = []
    merge_base: str | None = None
    looked = False
    for path in paths:
        keys = tuple(
            dict.fromkeys(
                k for p, ks in keyed.items() if glob_matches(p, path, unparsed=False) for k in ks
            )
        )
        judged_baseline = baseline and path == QUALITY_BASELINE
        if not keys and not judged_baseline:
            continue
        if not looked:
            merge_base, looked = _merge_base(checkout, base), True
        if merge_base is None:
            found.append(f"{path}: could not be read")
            continue
        try:
            if judged_baseline:
                change = _baseline_change(checkout, merge_base)
                found.extend([f"{path}: {change}"] if change else [])
            else:
                found.extend(
                    f"{path}: {k}" for k in _keyed_changes(checkout, merge_base, path, keys)
                )
        except _Unreadable:
            found.append(f"{path}: could not be read")
    return tuple(found)
