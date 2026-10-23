"""The agents abk knows how to start as protocol servers, and the probe of them.

Data and a probe, with no import of the protocol library: on a machine without
its extra an installed known agent is still listed, unusable, with the reason.
Product names appear in this module and nowhere else.
"""

from __future__ import annotations

import importlib.util
import subprocess
from collections.abc import Sequence
from enum import StrEnum
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.base import DOCUMENTED_ONLY, Candidate, Run, Which

# The runtime that speaks to these agents, as `runtimes.<name>` names it.
RUNTIME_NAME = "acp"

# How long a probe waits on a program's `--help`.
HELP_TIMEOUT = 5


class StartVariant(Frozen):
    """One way to start a known agent as a protocol server. `marker` is the text
    its `--help` shows when this is the spelling that version takes; empty for
    an agent whose spelling does not vary."""

    argv: tuple[str, ...]
    marker: str = ""


class ApplyFormat(StrEnum):
    """The configuration formats an applier can write; each has a writer in `policy_apply`."""

    YAML = "yaml"


class YamlVersion(StrEnum):
    """How bare scalars such as `off` are read: as booleans under 1.1, as strings under 1.2."""

    V1_1 = "1.1"
    V1_2 = "1.2"


class Toolset(Frozen):
    """A recommended toolset: the list at `path` the build run is meant to call, never merged."""

    path: tuple[str, ...]
    names: tuple[str, ...]


class ApplyPolicy(Frozen):
    """Where an agent keeps its list of refused commands, so the recommended policy can be
    merged into it: `<home>/<file>`, the home being `$home_env` when set, else `home_default`
    (a directory name under the person's home)."""

    home_env: str
    home_default: str
    file: str
    format: ApplyFormat
    deny_path: tuple[str, ...]
    yaml_version: YamlVersion
    toolset: Toolset | None = None
    verified: str  # how it was checked, or that it was documented only


class KnownAgent(Frozen):
    name: str
    program: str
    variants: tuple[StartVariant, ...]  # in order of preference
    needs: str = ""
    verified: str  # how it was checked, or that it was documented only
    source: str
    # Which forbidden-command spellings it refuses: said covered only where a live check
    # showed it, and UNVERIFIED until then.
    spellings: str = "UNVERIFIED: no live check has shown which spellings it refuses"
    # Set only for an agent whose configuration file and key were verified.
    apply: ApplyPolicy | None = None
    # The agent's own state folders (relative to the home directory), which a sandbox must
    # leave readable and writable; best effort.
    state_folders: tuple[str, ...] = ()


_DOCS = "the agent's own documentation"
_DOCS_ONLY = f"{DOCUMENTED_ONLY}: not run on the machine that wrote this entry"

# An entry is UNVERIFIED until a person has run it; `verified` says how far each one has been.
KNOWN_AGENTS: tuple[KnownAgent, ...] = (
    KnownAgent(
        name="Hermes",
        program="hermes",
        state_folders=(".hermes",),
        variants=(StartVariant(argv=("hermes", "acp")),),
        needs="its own configuration and credentials",
        verified="run where it was installed: session/new returned a session id and modes only",
        source="run on a machine where the agent was installed",
        apply=ApplyPolicy(
            home_env="HERMES_HOME",
            home_default=".hermes",
            file="config.yaml",
            format=ApplyFormat.YAML,
            deny_path=("approvals", "deny"),
            yaml_version=YamlVersion.V1_1,
            toolset=Toolset(path=("platform_toolsets", "acp"), names=("file", "terminal", "todo")),
            verified="its own merge script, tests and documentation; not a run of this engine",
        ),
    ),
    KnownAgent(
        name="OpenClaw",
        program="openclaw",
        state_folders=(".openclaw",),
        variants=(StartVariant(argv=("openclaw", "acp")),),
        needs="a running gateway, maybe a password",
        verified="its --help only (an ACP bridge backed by the Gateway)",
        source="the program's own --help",
    ),
    KnownAgent(
        name="OpenCode",
        program="opencode",
        state_folders=(".config/opencode", ".local/share/opencode"),
        variants=(StartVariant(argv=("opencode", "acp")),),
        verified=_DOCS_ONLY,
        source=_DOCS,
    ),
    KnownAgent(
        name="Goose",
        program="goose",
        state_folders=(".config/goose", ".local/share/goose"),
        variants=(StartVariant(argv=("goose", "acp")),),
        verified=_DOCS_ONLY,
        source=_DOCS,
    ),
    KnownAgent(
        name="Qwen Code",
        program="qwen",
        state_folders=(".qwen",),
        variants=(StartVariant(argv=("qwen", "--acp")),),
        verified=_DOCS_ONLY,
        source=_DOCS,
    ),
    KnownAgent(
        name="Gemini CLI",
        program="gemini",
        state_folders=(".gemini",),
        variants=(
            StartVariant(argv=("gemini", "--acp"), marker="--acp"),
            StartVariant(argv=("gemini", "--experimental-acp"), marker="--experimental-acp"),
        ),
        verified=f"{DOCUMENTED_ONLY}: the flag varies by version, chosen from --help",
        source=_DOCS,
    ),
    KnownAgent(
        name="Kimi CLI",
        program="kimi",
        state_folders=(".kimi",),
        # The older spelling first: its help names `acp` too, so the newer marker alone
        # would also match it.
        variants=(
            StartVariant(argv=("kimi", "--experimental-acp"), marker="--experimental-acp"),
            StartVariant(argv=("kimi", "acp"), marker="acp"),
        ),
        verified=f"{DOCUMENTED_ONLY}: sources disagree on the spelling, chosen from --help",
        source=_DOCS,
    ),
    KnownAgent(
        name="Codex",
        program="codex-acp",
        state_folders=(".codex",),
        variants=(StartVariant(argv=("codex-acp",)),),
        needs="an API key or a login",
        verified=_DOCS_ONLY,
        source="the adapter's package documentation",
    ),
    KnownAgent(
        name="Claude via an adapter",
        program="claude-agent-acp",
        state_folders=(".claude",),
        variants=(StartVariant(argv=("claude-agent-acp",)),),
        verified="UNVERIFIED: the standalone run command is not confirmed",
        source="the adapter's package documentation",
    ),
)


def agent_for_command(command: Sequence[str]) -> KnownAgent | None:
    """The known agent whose program a runtime's command starts; None for an empty command or
    one the table does not recognise."""
    if not command:
        return None
    program = Path(command[0]).name
    return next((agent for agent in KNOWN_AGENTS if agent.program == program), None)


def probe(which: Which, run: Run) -> list[Candidate]:
    """What a probe finds of every known agent, with no model call."""
    return [_candidate(agent, which, run) for agent in KNOWN_AGENTS]


def _candidate(agent: KnownAgent, which: Which, run: Run) -> Candidate:
    """What a probe finds of one known agent: the program on the path, the library and,
    where its spelling varies, the variant its help shows. Stops at the first that fails."""

    def found(command: tuple[str, ...], reasons: tuple[str, ...] = ()) -> Candidate:
        return Candidate(
            runtime=RUNTIME_NAME,
            command=command,
            label=agent.name,
            usable=not reasons,
            reasons=reasons,
            note=agent.needs,
            verified=agent.verified,
        )

    def unusable(reason: str) -> Candidate:
        return found(agent.variants[0].argv, (reason,))

    if which(agent.program) is None:
        return unusable(f"{agent.program} is not on the path")
    if importlib.util.find_spec(RUNTIME_NAME) is None:
        return unusable("the acp extra is not installed")
    if len(agent.variants) == 1:
        return found(agent.variants[0].argv)
    try:
        helped = run(
            [agent.program, "--help"],
            capture_output=True,
            text=True,
            check=False,
            timeout=HELP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return unusable(f"{agent.program} --help timed out after {HELP_TIMEOUT} seconds")
    except OSError as exc:
        return unusable(f"{agent.program} --help could not run: {exc}")
    shown = f"{helped.stdout}\n{helped.stderr}"
    chosen = next((v for v in agent.variants if v.marker and v.marker in shown), None)
    if chosen is None:
        return unusable(f"{agent.program} --help shows none of the start commands abk knows")
    return found(chosen.argv)
