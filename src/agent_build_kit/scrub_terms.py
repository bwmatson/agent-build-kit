"""The words that identify an installation, and the scrub of a text with them.

`terms_for` is the only definition of the term set; `abk scrub-check` scans with it
and anything that scrubs stored text uses it through `scrub_text`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from agent_build_kit.config import EnvFileProvider, YamlProvider
from agent_build_kit.installation import Installation

# Words a deploy rule is made of that describe no installation.
GENERIC = {
    "docker", "compose", "up", "restart", "start", "stop", "down", "build", "pull",
    "gateway", "deploy", "scripts", "main", "master", "service", "services", "test", "tests",
    "config", "reload", "systemctl", "sudo", "true", "false", "none", "null",
}  # fmt: skip
MIN_LENGTH = 3
MIN_LITERAL_LENGTH = 4
# The first directories below home that belong to tools, not to an installation.
TOOL_DIRS = {".claude", ".local", ".config", ".cache", ".ssh", ".volta"}
LOCAL_LIST = "scrub.local"


def _first_below_home(path: Path) -> str | None:
    try:
        parts = path.expanduser().relative_to(Path.home()).parts
    except ValueError:
        return None
    return parts[0] if parts else None


def _local_list(installation: Installation) -> tuple[set[str], set[str]]:
    """The terms `scrub.local` adds and the (lower-case) ones its `!` lines remove."""
    added: set[str] = set()
    removed: set[str] = set()
    try:
        text = (installation.root / LOCAL_LIST).read_text()
    except OSError:
        return added, removed
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("!"):
            removed.add(line[1:].strip().lower())
        elif len(line) >= MIN_LENGTH:
            added.add(line)
    return added, removed


def _config_paths(installation: Installation) -> Iterable[Path]:
    config = installation.config
    for repo in config.repos.values():
        yield repo.path
        yield from (Path(p) for p in repo.deploy.live_written)
        if repo.deploy.ssh_key is not None:
            yield repo.deploy.ssh_key
    for provider in config.verify.env.values():
        if isinstance(provider, EnvFileProvider | YamlProvider):
            yield provider.file
    if config.planning.worktree_root is not None:
        yield config.planning.worktree_root


def terms_for(installation: Installation, *, target: Path | None = None) -> list[str]:
    """The installation-identifying words, longest first.

    A repo whose checkout *is* the target is left out, and so is the planning
    root's own name when the root is the target: the checkout may name itself.
    Credential array names are conventions, not identities, and are left out
    too; the env variable names the live tests get are kept.
    """
    found: set[str] = set()
    config = installation.config
    resolved_target = target.resolve() if target is not None else None
    if resolved_target is None or installation.root.resolve() != resolved_target:
        found.add(installation.root.name)
    for name, repo in config.repos.items():
        if resolved_target is not None and repo.path.expanduser().resolve() == resolved_target:
            continue
        found.add(name)
        # Every segment of the identity, whatever the host calls them: an
        # owner and a name on GitHub, an organisation, project and repo on
        # Azure DevOps.
        _, repo_id = installation.forge_of(name)
        found.update({repo_id.account, repo_id.project, repo_id.name, repo.path.expanduser().name})
        for path in repo.deploy.live_written:
            found.add(Path(path).name)
        if repo.deploy.ssh_key is not None:
            found.add(repo.deploy.ssh_key.name)
        for rule in repo.deploy.rules:
            head = rule.prefix.split("/", 1)[0]
            if "." not in head:
                found.add(head)
            for command in rule.run:
                for word in command:
                    if word.startswith("-") or "/" in word or "." in word:
                        continue
                    found.add(word)
    found.update(config.verify.env)
    for provider in config.verify.env.values():
        if isinstance(provider, EnvFileProvider | YamlProvider):
            found.add(provider.file.name)
            first = _first_below_home(provider.file)
            if first is not None:
                found.add(first)
        elif provider.from_ == "literal":
            if len(provider.value) >= MIN_LITERAL_LENGTH and not provider.value.isdigit():
                found.add(provider.value)
    found.add(Path.home().name)
    for path in _config_paths(installation):
        first = _first_below_home(path)
        if first is not None and first.startswith(".") and first not in TOOL_DIRS:
            found.add(first)

    added, removed = _local_list(installation)
    derived = {t for t in found if len(t) >= MIN_LENGTH and t.lower() not in GENERIC}
    terms = {t for t in derived | added if t.lower() not in removed}
    return sorted(terms, key=lambda t: (-len(t), t))


def scrub_text(text: str, terms: list[str], *, replacement: str = "<redacted>") -> str:
    """`text` with every term replaced, case-insensitively and longest first."""
    if not terms:
        return text
    ordered = sorted(set(terms), key=lambda t: (-len(t), t))
    pattern = re.compile("|".join(re.escape(t) for t in ordered), re.IGNORECASE)
    return pattern.sub(lambda _: replacement, text)
