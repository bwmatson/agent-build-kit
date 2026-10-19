"""`abk init` as a person runs it, against a stand-in agent on the path.

The real command runs as a process on a machine whose path holds only what it needs and the
stand-ins a test installs (`tests/scripted_abk.py`). A stand-in is the protocol test agent under a
known agent's program name: it records everything it is sent, and a test fails when a prompt
reaches it that is not the policy check's own, so nothing here makes a model call or spends
tokens. The runs pass `--skip-research --skip-propose` (those steps are model calls by design;
the unit tests prove they receive the chosen runtime) and decline the policy check, which is a
prompt for this runtime, in every run but the `--policy-only` ones. Needs node for the OpenSpec
CLI, as the end-to-end init test does.

Run with `uv run pytest -m local_stack tests/integration/test_init_runtime_live_stack.py`; the
last test uses an agent installed on the host, and skips without one.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from agent_build_kit import config
from agent_build_kit.init.runtime_choice import OTHER
from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.acp import AcpRuntime
from agent_build_kit.runtimes.base import ModelSource
from agent_build_kit.runtimes.known_agents import KNOWN_AGENTS, KnownAgent
from tests.factories import coded_repo, git, init_repo, recognised_planning
from tests.runtimes.acp_agent import requests
from tests.scripted_abk import Answers, Machine, Outcome, install_stand_in, machine, run_abk

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
]

# Two known agents that need nothing before they start and have one start command each.
SIMPLE = [a for a in KNOWN_AGENTS if not a.needs and len(a.variants) == 1]
SWIFT, DEEP = "swift-1", "deep-2"

PICK = (r"Which runtime\?[^:]*: ", "")
COMMAND = (r"The command that starts the agent[^:]*: ", "")
ANY_MODEL = (r"Model for \w+ \[[^\]]*\]: ", "")
NOTIFICATIONS = (r"desktop notifications[^?]*\? \[y/N\] ", "n")
PROCEED = (r"write it and proceed\? \[Y/n\] ", "y")
DECLINE_CHECK = (r"spends tokens; run it\? \[y/N\] ", "n")
INIT_ANSWERS: Answers = [PICK, COMMAND, ANY_MODEL, NOTIFICATIONS, PROCEED, DECLINE_CHECK]


class Scratch(Frozen):
    on: Machine
    planning: Path
    app: Path
    root: Path

    def init(self, *flags: str, answers: Answers = ()) -> Outcome:
        args = ["init", str(self.planning), "--repo", str(self.app)]
        args += ["--skip-research", "--skip-propose", *flags]
        return run_abk(self.on, args, cwd=self.planning, answers=answers)

    @property
    def abk_yaml(self) -> Path:
        return self.planning / "abk.yaml"


@pytest.fixture
def scratch(tmp_path: Path) -> Scratch:
    planning = recognised_planning(tmp_path / "planning")
    init_repo(planning)
    git(planning, "add", "-A")
    git(planning, "commit", "-q", "-m", "plan")
    return Scratch(
        on=machine(tmp_path / "machine"),
        planning=planning,
        app=coded_repo(tmp_path / "app", "example/app"),
        root=tmp_path,
    )


def stand_in(scratch: Scratch, agent: KnownAgent, *, models: tuple[str, ...] = (SWIFT, DEEP)):
    """Install the stand-in as `agent`'s program; the file it records what it was sent to."""
    record = scratch.root / f"{agent.program}.jsonl"
    install_stand_in(scratch.on, agent.program, record, models=models)
    return record


def prompts(record: Path) -> list[str]:
    """The text of each prompt the stand-in was sent."""
    return [
        " ".join(block["text"] for block in sent["prompt"])
        for sent in requests(record, "session/prompt")
    ]


def snapshot(root: Path) -> tuple[dict[str, bytes], str]:
    """Every file under `root` but the repository's own, and its commit."""
    files = {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(root).parts
    }
    return files, git(root, "rev-parse", "HEAD") + git(root, "status", "--porcelain")


def repos_state(scratch: Scratch) -> list[tuple[dict[str, bytes], str]]:
    """The planning repo and the code repo `init` may write into, as they stand."""
    return [snapshot(scratch.planning), snapshot(scratch.app)]


def listed(output: str) -> list[str]:
    """The numbered candidate lines of the runtime list, in the order they were shown: those
    between its heading and the person's own configuration, which closes it."""
    shown = output.split("Agent runtimes on this machine:")[1].split(f". {OTHER}")[0]
    return re.findall(r"^ {2}\d+\. .*$", shown, re.M)


def test_the_list_puts_the_stand_in_first_and_the_choice_is_recorded(scratch: Scratch) -> None:
    agent = SIMPLE[0]
    record = stand_in(scratch, agent)

    done = scratch.init(answers=INIT_ANSWERS)

    assert done.returncode == 0, done.output
    shown = listed(done.output)
    assert agent.name in shown[0] and f"({agent.program} " in shown[0], shown
    assert "not usable yet" not in shown[0]
    assert shown[1:]
    reasonless = [line for line in shown[1:] if "not usable yet:" not in line]
    assert not reasonless, reasonless
    for other in KNOWN_AGENTS:
        if other is agent:
            continue
        line = next(line for line in shown[1:] if other.name in line)
        assert f"not usable yet: {other.program} is not on the path" in line, line
    written = config.load(scratch.abk_yaml)
    assert written.runtime == "acp"
    assert written.runtimes["acp"].command == list(agent.variants[0].argv)
    assert requests(record, "session/new"), "the stand-in was asked what it offers"
    assert prompts(record) == []

    doctor = run_abk(
        scratch.on, ["--config", str(scratch.abk_yaml), "doctor"], cwd=scratch.planning
    )
    assert re.search(rf"^ok +runtime: acp \({re.escape(agent.program)} ", doctor.output, re.M), (
        doctor.output
    )
    assert prompts(record) == [], "doctor sends the stand-in no prompt either"


def test_advertised_models_are_shown_with_the_current_one_default_and_the_choice_is_written(
    scratch: Scratch,
) -> None:
    record = stand_in(scratch, SIMPLE[0])
    review = (r"Model for review \[[^\]]*\]: ", "2")

    done = scratch.init(answers=[review, *INIT_ANSWERS])

    assert done.returncode == 0, done.output
    assert f"1. {SWIFT} (default)" in done.output
    assert f"2. {DEEP}" in done.output
    written = yaml.safe_load(scratch.abk_yaml.read_text())
    assert written["models"]["review"] == DEEP
    assert not {SWIFT} & set(written["models"].values()), "Enter kept the agent's own default"
    assert prompts(record) == []


def test_an_agent_that_advertises_no_models_says_so_and_leaves_the_roles_empty(
    scratch: Scratch,
) -> None:
    record = stand_in(scratch, SIMPLE[0], models=())

    done = scratch.init(answers=INIT_ANSWERS)

    assert done.returncode == 0, done.output
    assert "this agent does not list its models; it will use its own" in done.output
    written = yaml.safe_load(scratch.abk_yaml.read_text())
    assert not written.get("models"), written.get("models")
    assert prompts(record) == []


def test_nothing_is_written_when_the_confirmation_is_answered_no(scratch: Scratch) -> None:
    stand_in(scratch, SIMPLE[0])
    before = repos_state(scratch)
    declined = (PROCEED[0], "n")

    done = scratch.init(answers=[declined, *INIT_ANSWERS])

    assert done.returncode == 1, done.output
    assert "nothing written" in done.output
    assert not scratch.abk_yaml.exists()
    assert repos_state(scratch) == before


def test_yes_with_several_usable_agents_names_them_and_writes_nothing(scratch: Scratch) -> None:
    for agent in SIMPLE[:2]:
        stand_in(scratch, agent)
    before = repos_state(scratch)

    done = scratch.init("--yes")

    assert done.returncode == 2, done.output
    assert "several runtimes are usable: name one with --runtime" in done.output
    assert all(agent.name in done.output for agent in SIMPLE[:2])
    assert repos_state(scratch) == before


def test_yes_with_nothing_installed_says_so_and_writes_nothing(scratch: Scratch) -> None:
    before = repos_state(scratch)

    done = scratch.init("--yes")

    assert done.returncode == 2, done.output
    assert "no runtime on this machine is usable yet" in done.output
    for agent in KNOWN_AGENTS:
        assert f"not usable yet: {agent.program} is not on the path" in done.output
    assert repos_state(scratch) == before


class Installed(Frozen):
    name: str
    command: list[str]


def installed_agents() -> list[Installed]:
    found = AcpRuntime().detect(shutil.which, subprocess.run)
    return [Installed(name=c.label, command=list(c.command)) for c in found if c.usable]


def test_listing_against_the_installed_agent_sends_no_prompt(tmp_path: Path) -> None:
    agents = installed_agents()
    if not agents:
        pytest.skip("no protocol agent is installed on this host")
    record = tmp_path / "wire.jsonl"
    proxy = Path(__file__).resolve().parents[1] / "runtimes" / "recording_proxy.py"

    shown = AcpRuntime().list_models([sys.executable, str(proxy), str(record), *agents[0].command])

    lines = [json.loads(line) for line in record.read_text().splitlines()]
    sent = [m["message"].get("method") for m in lines if m["from"] == "client"]
    assert "session/prompt" not in sent, sent
    answered = [
        m["message"]["result"]
        for m in lines
        if m["from"] == "agent"
        and isinstance(m["message"], dict)
        and isinstance(m["message"].get("result"), dict)
    ]
    options = [
        option
        for result in answered
        for option in result.get("configOptions") or []
        if option.get("category") == "model" or option.get("id") == "model"
    ]
    # Flat choices, or groups of them, as the library reads an option's entries.
    advertised = [
        choice["value"]
        for option in options
        for entry in option.get("options") or []
        for choice in (entry["options"] if "options" in entry else [entry])
    ]
    if advertised:
        assert shown.source == ModelSource.ADVERTISED
        assert {m.name for m in shown.models} == set(advertised)
    else:
        assert shown.source == ModelSource.NONE and not shown.models, shown
