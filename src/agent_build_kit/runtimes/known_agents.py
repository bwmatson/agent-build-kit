"""The agents abk knows how to start as protocol servers, and the probe of them.

Data and a probe, with no import of the protocol library: on a machine without
its extra an installed known agent is still listed, unusable, with the reason.
Product names appear in this module and nowhere else.
"""

from __future__ import annotations

import importlib.util
import subprocess

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


_DOCS = "the agent's own documentation"
_DOCS_ONLY = f"{DOCUMENTED_ONLY}: not run on the machine that wrote this entry"

# An entry is UNVERIFIED until a person has run it; `verified` says how far each one has been.
KNOWN_AGENTS: tuple[KnownAgent, ...] = (
    KnownAgent(
        name="Hermes",
        program="hermes",
        variants=(StartVariant(argv=("hermes", "acp")),),
        needs="its own configuration and credentials",
        verified="run where it was installed: session/new returned a session id and modes only",
        source="run on a machine where the agent was installed",
    ),
    KnownAgent(
        name="OpenClaw",
        program="openclaw",
        variants=(StartVariant(argv=("openclaw", "acp")),),
        needs="a running gateway, maybe a password",
        verified="its --help only (an ACP bridge backed by the Gateway)",
        source="the program's own --help",
    ),
    KnownAgent(
        name="OpenCode",
        program="opencode",
        variants=(StartVariant(argv=("opencode", "acp")),),
        verified=_DOCS_ONLY,
        source=_DOCS,
    ),
    KnownAgent(
        name="Goose",
        program="goose",
        variants=(StartVariant(argv=("goose", "acp")),),
        verified=_DOCS_ONLY,
        source=_DOCS,
    ),
    KnownAgent(
        name="Qwen Code",
        program="qwen",
        variants=(StartVariant(argv=("qwen", "--acp")),),
        verified=_DOCS_ONLY,
        source=_DOCS,
    ),
    KnownAgent(
        name="Gemini CLI",
        program="gemini",
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
        variants=(StartVariant(argv=("codex-acp",)),),
        needs="an API key or a login",
        verified=_DOCS_ONLY,
        source="the adapter's package documentation",
    ),
    KnownAgent(
        name="Claude via an adapter",
        program="claude-agent-acp",
        variants=(StartVariant(argv=("claude-agent-acp",)),),
        verified="UNVERIFIED: the standalone run command is not confirmed",
        source="the adapter's package documentation",
    ),
)


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
