"""The environment signs: which failed outputs are the environment's, confirmed by a probe."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import partial
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, NamedTuple

from agent_build_kit import path_patterns
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.git_output import transport_failure
from agent_build_kit.redaction import redact_text
from agent_build_kit.runtimes.network import network_failure

if TYPE_CHECKING:
    from agent_build_kit.config import RepoConfig

# The words of a login the CLI rejected; `login_rejection` answers through them.
LOGIN_REJECTION = re.compile(
    r"OAuth access token has expired|Failed to authenticate\b[^\n]*\b401\b[^\n]*\bOAuth\b"
    r"|Not logged in\b[^\n]*\bPlease run /login\b",
    re.IGNORECASE,
)

_NOTE_CUT = 300


class Verdict(StrEnum):
    FAILS = "fails"
    PASSES = "passes"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Probes:
    """The four questions a sign's probe asks; each answers a `Verdict`."""

    forge_read: Callable[[str, str], Verdict]
    feed: Callable[[str, str | None], Verdict]
    credential: Callable[[str], Verdict]
    tool: Callable[[str], Verdict]


class Seen(Frozen):
    sign: str
    subject: str | None
    line: str


class Confirmed(Frozen):
    sign: str
    subject: str | None
    line: str
    note: str


class EnvironmentFailure(RuntimeError):
    """A confirmed environment failure; its text is the note."""

    def __init__(self, confirmed: Confirmed) -> None:
        super().__init__(confirmed.note)
        self.confirmed = confirmed


class ParkedSign(NamedTuple):
    sign: str
    subject: str | None


Reading = tuple[str | None, str]  # the subject and the line that showed the sign
Reader = Callable[[str], Reading | None]

_FEED = re.compile(
    r"npm (?:ERR!|error) code (?:E401|E403|ENOTFOUND|EAI_AGAIN|ETIMEDOUT|ECONNRESET|ECONNREFUSED)"
    r"|ERR_PNPM_(?:META_)?FETCH\w*|NU1301"
    r"|Failed to (?:fetch|download)\b[^\n]*https?://|Could not fetch URL https?://"
)
_URL_HOST = re.compile(r"https?://(?:[^/@\s]*@)?([^/\s:`'\"<>]+)")
_CREDENTIAL = (
    re.compile(r"\b([A-Z][A-Z0-9_]{2,}) is not set"),
    re.compile(
        r"environment variable ([A-Z][A-Z0-9_]{2,}) (?:is )?(?:not set|missing|required|blank)"
    ),
)
_API = re.compile(r"Something went wrong while executing your query|host answered 5\d\d")
MACHINE_TOOLS = (
    "uv", "uvx", "node", "npm", "npx", "pnpm", "yarn", "corepack",
    "dotnet", "git", "gh", "az", "docker", "python3",
)  # fmt: skip


def _first_line(output: str, found: Callable[[str], bool]) -> str:
    lines = output.splitlines()
    return next((line for line in lines if found(line)), next((x for x in lines if x.strip()), ""))


def _words(pattern: re.Pattern[str]) -> Reader:
    def read(output: str) -> Reading | None:
        if not pattern.search(output):
            return None
        return None, _first_line(output, lambda line: bool(pattern.search(line)))

    return read


def _network(output: str) -> Reading | None:
    if network_failure(output) is None:
        return None
    return None, _first_line(output, lambda line: network_failure(line) is not None)


def _code_host(output: str) -> Reading | None:
    if transport_failure(output) is None:
        return None
    return None, _first_line(output, lambda line: transport_failure(line) is not None)


def _feed(output: str) -> Reading | None:
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if _FEED.search(line):
            for near in lines[index : index + 4]:
                host = _URL_HOST.search(near)
                if host:
                    return host.group(1), line
            return None, line
    return None


def _credential(output: str) -> Reading | None:
    for line in output.splitlines():
        for pattern in _CREDENTIAL:
            found = pattern.search(line)
            if found:
                return found.group(1), line
    return None


def _missing_tool(tools: Sequence[str]) -> Reader:
    names = "|".join(re.escape(name) for name in (*MACHINE_TOOLS, *tools))
    pattern = re.compile(
        rf"(?:ba|z|da)?sh: (?:line )?\d+: ({names}): (?:command )?not found"
        rf"|No such file or directory: '({names})'"
        rf"|Failed to spawn: `({names})`"
        rf"|'({names})' is not recognized as an internal or external command"
    )

    def read(output: str) -> Reading | None:
        for line in output.splitlines():
            found = pattern.search(line)
            if found:
                return next(group for group in found.groups() if group), line
        return None

    return read


class _Row(NamedTuple):
    sign: str
    where: tuple[str, ...]
    confirmed: bool


_TABLE = (
    _Row("login", ("agent",), False),
    _Row("network", ("agent",), False),
    _Row("code_host", ("exception",), False),
    _Row("code_host_api", ("exception",), True),
    _Row("package_feed", ("checks", "unit-test", "e2e"), True),
    _Row("live_credential", ("e2e",), True),
    _Row("missing_tool", ("checks", "unit-test", "e2e"), True),
)
_CONFIRMED = {row.sign for row in _TABLE if row.confirmed}

_FEED_NAMES = frozenset(
    name.lower()
    for name in (
        "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "uv.lock", "packages.lock.json",
        ".npmrc", ".yarnrc", ".yarnrc.yml", "global.json", "uv.toml", "nuget.config",
        "pip.conf", "Directory.Packages.props",
    )
)  # fmt: skip
_TOOL_NAMES = frozenset(
    (".tool-versions", "mise.toml", ".mise.toml", ".nvmrc", ".node-version", ".python-version",
     "global.json")
)  # fmt: skip
_BUILT_IN = {"package_feed": _FEED_NAMES, "missing_tool": _TOOL_NAMES}


def seen(output: str, step: str, *, tools: Sequence[str] = ()) -> list[Seen]:
    readers: dict[str, Reader] = {
        "login": _words(LOGIN_REJECTION),
        "network": _network,
        "code_host": _code_host,
        "code_host_api": _words(_API),
        "package_feed": _feed,
        "live_credential": _credential,
        "missing_tool": _missing_tool(tools),
    }
    found: list[Seen] = []
    for row in _TABLE:
        if step not in row.where:
            continue
        reading = readers[row.sign](output)
        if reading:
            found.append(Seen(sign=row.sign, subject=reading[0], line=reading[1]))
    return found


def distrusted_input(
    sign: str, changed: Sequence[str], repo_config: RepoConfig | None
) -> str | None:
    names = _BUILT_IN.get(sign, frozenset())
    patterns: list[str] = []
    if repo_config is not None:
        if sign in _BUILT_IN and repo_config.environment is not None:
            inputs = repo_config.environment.inputs
            patterns += [*inputs.dependencies, *inputs.lock, *inputs.other]
        for name, named in repo_config.environment_signs.distrusted.items():
            if name == sign:
                patterns += named
    for path in changed:
        if PurePosixPath(path).name.lower() in names or path_patterns.matches_any(patterns, path):
            return path
    return None


def _verdict(ask: Callable[[], Verdict]) -> Verdict:
    try:
        return ask()
    except Exception:
        return Verdict.UNKNOWN


def _ask(item: Seen, probes: Probes, repo: str, branch: str) -> Verdict:
    subject = item.subject or ""
    if item.sign == "code_host_api":
        return probes.forge_read(repo, branch)
    if item.sign == "package_feed":
        return probes.feed(repo, item.subject)
    if item.sign == "live_credential":
        return probes.credential(subject)
    return probes.tool(subject)


def confirm(
    output: str,
    *,
    where: str,
    repo: str,
    branch: str,
    changed: Sequence[str],
    repo_config: RepoConfig | None,
    probes: Probes,
    say: Callable[[str], None],
) -> Confirmed | None:
    tools = repo_config.environment_signs.tools if repo_config is not None else []
    for item in seen(output, where, tools=tools):
        if item.sign not in _CONFIRMED:
            continue
        label = f"{item.sign} {item.subject}" if item.subject else item.sign
        touched = distrusted_input(item.sign, changed, repo_config)
        if touched:
            say(f"environment sign [{label}] not confirmed: the branch changed {touched}")
            continue
        verdict = _verdict(partial(_ask, item, probes, repo, branch))
        if verdict is not Verdict.FAILS:
            say(f"environment sign [{label}] not confirmed: its probe answered {verdict.value}")
            continue
        line = redact_text(item.line.strip(), where="environment sign")[:_NOTE_CUT]
        return Confirmed(
            sign=item.sign,
            subject=item.subject,
            line=line,
            note=f"environment failure [{label}]: {line}",
        )
    return None


_NOTE = re.compile(r"^environment failure \[(\w+)(?: ([^\]]+))?\]:")


def parked_sign(note: str) -> ParkedSign | None:
    found = _NOTE.match(note)
    if not found or found.group(1) not in _CONFIRMED:
        return None
    return ParkedSign(found.group(1), found.group(2))
