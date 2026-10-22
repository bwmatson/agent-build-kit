"""`abk init` as a person runs it, against a stand-in agent on the path.

The real command runs as a process on a machine whose path holds only what it needs, with a home
of its own, and the stand-ins a test installs (`tests/scripted_abk.py`). A stand-in is the
protocol test agent under a known agent's program name: it records everything it is sent, and
every run asserts it was sent no `session/prompt`, so nothing here makes a model call or spends
tokens. The policy step reads the agent's configuration and starts no agent. The runs pass
`--skip-research --skip-propose` (those steps are model calls by design; the unit tests prove
they receive the chosen runtime). The `--policy-only` runs read a configuration in a scratch
agent home, never the host's. Needs node for the OpenSpec CLI, as the end-to-end init test does.

Run with `uv run pytest -m local_stack tests/integration/test_init_runtime_live_stack.py`; the
last test starts the agent installed on the host, is in the `acp` split, and skips without one.
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
from agent_build_kit.runtimes.recommended_policy import matches, patterns
from tests.factories import coded_repo, git, init_repo, recognised_planning
from tests.runtimes.acp_agent import requests
from tests.scripted_abk import Answers, Machine, Outcome, install_stand_in, machine, run_abk
from tests.spelling_rows import AMEND
from tests.split_sources import snapshot_tree

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.runtime_acp,
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
INIT_ANSWERS: Answers = [PICK, COMMAND, ANY_MODEL, NOTIFICATIONS, PROCEED]


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
        name: content
        for name, content in snapshot_tree(root).items()
        if Path(name).parts[0] != ".git"
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


HERMES = next(a for a in KNOWN_AGENTS if a.apply is not None)
UNREFUSED = "git -C . commit --amend --no-edit"


class PolicyHome(Frozen):
    record: Path
    fix_dir: Path
    config: Path


def policy_home(scratch: Scratch) -> PolicyHome:
    """An installation set up by an `init` run against the stand-in as an agent the kit can read
    a policy of, whose scratch agent home holds a deny list that lets one spelling through."""
    assert HERMES.apply is not None
    record = stand_in(scratch, HERMES)
    home = scratch.root / "agent-home"
    home.mkdir()
    scratch.on.env[HERMES.apply.home_env] = str(home)
    config_file = home / HERMES.apply.file
    complete = patterns()
    leaky = [p for p in complete if not matches(p, UNREFUSED)]
    assert len(leaky) < len(complete)

    def write(deny: list[str]) -> str:
        body = "approvals:\n  deny:\n" + "".join(f"    - {json.dumps(p)}\n" for p in deny)
        return body

    config_file.write_text(write(leaky))
    (scratch.root / "complete.yaml").write_text(write(complete))
    done = scratch.init("--yes", "--runtime", "acp")
    assert done.returncode in (0, 1), done.output
    assert prompts(record) == []
    return PolicyHome(record=record, fix_dir=scratch.root, config=config_file)


def policy_only(scratch: Scratch, fix_body: str, home: PolicyHome) -> Outcome:
    fix = home.fix_dir / "fix.sh"
    fix.write_text(f"#!/bin/sh\n{fix_body}\n")
    fix.chmod(0o755)
    return run_abk(
        scratch.on,
        ["init", str(scratch.planning), "--policy-only", "--yes", "--policy-fix", str(fix)],
        cwd=scratch.planning,
    )


def test_a_fix_that_closes_the_spelling_is_seen_to_close_it(scratch: Scratch) -> None:
    home = policy_home(scratch)
    complete = home.fix_dir / "complete.yaml"

    # Only builtins: the path of a stand-in's machine holds no `cp`.
    copy = f'while IFS= read -r line; do printf "%s\\n" "$line"; done < {complete} > {home.config}'
    done = policy_only(scratch, copy, home)

    assert done.returncode == 0, done.output
    assert f"{AMEND}: not refused as `{UNREFUSED}`" in done.output
    assert re.search(rf"{AMEND}: refused as [^|\n]*`{re.escape(UNREFUSED)}`", done.output)
    assert "now refuses every forbidden class" in done.output
    assert prompts(home.record) == []


def test_a_fix_that_changes_nothing_says_so_and_exits_one(scratch: Scratch) -> None:
    home = policy_home(scratch)

    done = policy_only(scratch, "exit 0", home)

    assert done.returncode == 1, done.output
    assert f"the fix made no change; still not refused: `{UNREFUSED}`" in done.output
    assert prompts(home.record) == []


class Installed(Frozen):
    name: str
    command: list[str]


def installed_agents() -> list[Installed]:
    found = AcpRuntime().detect(shutil.which, subprocess.run)
    return [Installed(name=c.label, command=list(c.command)) for c in found if c.usable]


# Why a scenario of this module has no Claude variant. Probed 2026-10-19 on a host with a protocol
# agent installed: the listing finishes with the network proxy variables pointing at a closed port
# and does not finish with an empty agent home, so it needs the agent installed and configured
# with its own credentials, and no model backend.
#
# The rest drive `abk init` against a scripted stand-in for a protocol agent, so they are about the
# protocol agents `abk init` lists and configures, which Claude Code is not.
STAND_IN = "drives abk init against a scripted protocol agent; Claude Code is not one"
ACP_ONLY_REASONS = {
    "test_the_list_puts_the_stand_in_first_and_the_choice_is_recorded": STAND_IN,
    "test_advertised_models_are_shown_with_the_current_one_default_and_the_choice_is_written": (
        STAND_IN
    ),
    "test_an_agent_that_advertises_no_models_says_so_and_leaves_the_roles_empty": STAND_IN,
    "test_nothing_is_written_when_the_confirmation_is_answered_no": STAND_IN,
    "test_yes_with_several_usable_agents_names_them_and_writes_nothing": STAND_IN,
    "test_yes_with_nothing_installed_says_so_and_writes_nothing": STAND_IN,
    "test_a_fix_that_closes_the_spelling_is_seen_to_close_it": STAND_IN,
    "test_a_fix_that_changes_nothing_says_so_and_exits_one": STAND_IN,
    "test_listing_against_the_installed_agent_sends_no_prompt": (
        "lists models through the protocol's session/new, which the Claude runtime does not use; "
        "no model call is made, the installed and configured agent is the only requirement"
    ),
}


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
