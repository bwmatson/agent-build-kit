"""When the target repo's own commit gate rejects a unit's commit.

The gate here is a real git pre-commit hook in a real repository: what it
prints and how it exits is the whole interface, and what `git commit` does
with it is part of what is being tested. Only the agent is a stand-in.

Two rejections are told apart by what happens next:

- **The gate rewrote the files** (a formatter, a whitespace fixer). The fix is
  already on disk, so committing again succeeds. No agent call.
- **The gate found something** (a lint rule). Committing again fails the same
  way, so the gate's own output goes to the agent that wrote the work.

Bounded either way, and never around the gate: no skipped hooks, no narrowed
set of paths, no commit at all rather than one that skipped verification.
"""

import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import Unit
from agent_build_kit.pipeline.wiring import (
    COMMIT_FIX_ROUNDS,
    CommitRejected,
    build_commit,
)
from tests.conftest import make_installation
from tests.factories import init_repo

# What ruff prints for a line it will not accept: the file, the line, the rule.
LINT_OUTPUT = "src/app/marker.py:3:101: E501 Line too long (105 > 100)"
LONG_LINE = "x = '" + "a" * 100 + "'\n"

# pre-commit's trailing-whitespace fixer: it rewrites the file and exits 1 so
# the author looks again.
WHITESPACE_FIXER = """\
#!/bin/sh
if git diff --cached --name-only | xargs grep -l ' $' >/dev/null 2>&1; then
    for f in $(git diff --cached --name-only); do sed -i 's/ *$//' "$f"; done
    echo 'trim trailing whitespace.................................................Failed'
    echo '- hook id: trailing-whitespace'
    echo '- exit code: 1'
    echo '- files were modified by this hook'
    exit 1
fi
exit 0
"""

# A linter: rejects a long line in any staged file, and changes nothing.
LINTER = f"""\
#!/bin/sh
for f in $(git diff --cached --name-only); do
    if git show ":$f" | grep -qE '^.{{101,}}$'; then
        echo 'ruff.....................................................................Failed'
        echo '- hook id: ruff'
        echo '- exit code: 1'
        echo
        echo '{LINT_OUTPUT}'
        echo 'Found 1 error.'
        exit 1
    fi
done
exit 0
"""

pytestmark = pytest.mark.usefixtures("scripted_engine")


def repo_with_gate(tmp_path: Path, hook: str) -> Path:
    repo = init_repo(tmp_path / "repo")
    (repo / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=repo, check=True)
    gate = repo / ".git" / "hooks" / "pre-commit"
    gate.write_text(hook)
    gate.chmod(0o755)
    return repo


def commits(repo: Path) -> int:
    out = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout
    return int(out.strip())


class Agent:
    """The agent the fix round hands the gate's output to."""

    def __init__(self, edit=None, *, limit: int = 10) -> None:
        self.prompts: list[str] = []
        self.cwds: list[Path] = []
        self.edit = edit
        self.limit = limit

    def __call__(self, prompt: str, *, cwd: Path, model: str = "") -> str:
        self.prompts.append(prompt)
        self.cwds.append(cwd)
        if len(self.prompts) > self.limit:
            pytest.fail(f"the fix round was not bounded: {len(self.prompts)} agent calls")
        if self.edit:
            self.edit(cwd)
        return "done"


class Recorded:
    """The real runner, remembering every command it was given."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.envs: list[dict | None] = []

    def __call__(self, args: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.commands.append(list(args))
        self.envs.append(kwargs.get("env"))
        return subprocess.run(args, capture_output=True, text=True, check=False, **kwargs)


def test_a_gate_that_rewrote_the_files_is_retried_without_an_agent(tmp_path: Path) -> None:
    """A formatter doing its job: the fix is on disk, and committing again is
    the whole of it. Neither an agent call nor a failure."""
    repo = repo_with_gate(tmp_path, WHITESPACE_FIXER)
    (repo / "marker.py").write_text("x = 1   \n")
    agent = Agent()
    before = commits(repo)

    made = build_commit(unit_id="add-marker/1", fix=agent)("test: covers it", cwd=repo)

    assert made == 1
    assert commits(repo) == before + 1
    assert agent.prompts == [], "re-running the commit was the whole fix"
    assert (repo / "marker.py").read_text() == "x = 1\n"
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert status == "", "the formatter's rewrite is in the commit, not left behind"


def test_a_gate_that_found_something_hands_its_own_output_to_the_agent(tmp_path: Path) -> None:
    """The file, the line and the rule, as the gate printed them — the most
    actionable feedback in the pipeline, and the one piece the agent used to
    never see. It fixes it in place and the commit is made."""
    repo = repo_with_gate(tmp_path, LINTER)
    (repo / "marker.py").write_text(LONG_LINE)
    agent = Agent(edit=lambda cwd: (cwd / "marker.py").write_text("x = 'short'\n"))
    before = commits(repo)

    made = build_commit(unit_id="add-marker/1", fix=agent)("test: covers it", cwd=repo)

    assert made == 1
    assert commits(repo) == before + 1
    assert len(agent.prompts) == 1
    assert LINT_OUTPUT in agent.prompts[0], "the gate's words, not a summary of them"
    assert agent.cwds == [repo], "the agent fixes its own work, in the same worktree"
    committed = subprocess.run(
        ["git", "show", "HEAD:marker.py"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert committed == "x = 'short'\n"


def test_a_gate_that_never_accepts_fails_after_a_bounded_number_of_rounds(
    tmp_path: Path,
) -> None:
    """A gate the agent cannot satisfy must not become a loop paid for by the
    round. It ends as it did before — raised — but carrying what the gate said
    last, and with nothing committed."""
    repo = repo_with_gate(tmp_path, LINTER)
    (repo / "marker.py").write_text(LONG_LINE)
    agent = Agent()  # tries, and changes nothing
    recorded = Recorded()
    before = commits(repo)

    with pytest.raises(CommitRejected) as caught:
        build_commit(unit_id="add-marker/1", run=recorded, fix=agent)("test: covers it", cwd=repo)

    assert LINT_OUTPUT in str(caught.value)
    assert len(agent.prompts) == COMMIT_FIX_ROUNDS
    assert all(LINT_OUTPUT in prompt for prompt in agent.prompts), "each round, its gate output"
    attempts = [c for c in recorded.commands if c[:2] == ["git", "commit"]]
    assert len(attempts) == 2 + COMMIT_FIX_ROUNDS, "the first try, the plain retry, each round"
    assert commits(repo) == before, "no commit at all rather than one around the gate"


@pytest.mark.parametrize(
    "shortcut",
    [
        "git commit -q --no-verify -am x",
        "git add -A && git commit -q -n -m x",
        "rm .git/hooks/pre-commit && git commit -q -am x",
        "git -c core.hooksPath=/dev/null commit -q -am x",
    ],
)
def test_a_fix_round_that_commits_around_the_gate_fails_the_unit(
    tmp_path: Path, shortcut: str
) -> None:
    """The agent has `git`, and the fix round is when skipping the gate is most
    tempting. Its own commit leaves nothing staged, which must not read as
    nothing to commit: the gate never passed, so the unit fails."""
    repo = repo_with_gate(tmp_path, LINTER)
    (repo / "marker.py").write_text(LONG_LINE)
    agent = Agent(edit=lambda cwd: subprocess.run(shortcut, shell=True, cwd=cwd, check=True))

    with pytest.raises(CommitRejected) as caught:
        build_commit(unit_id="add-marker/1", fix=agent)("feat: adds it", cwd=repo)

    assert "committed on its own" in str(caught.value)
    assert LINT_OUTPUT in str(caught.value)
    assert len(agent.prompts) == 1, "no further round after the gate was gone around"


def test_a_unit_whose_commit_was_rejected_carries_the_gates_output_on_its_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reason belongs where a unit's state is read, not only in the tick
    log a person would have to go and find."""
    from agent_build_kit.cli import pipeline as cli

    inst = make_installation(tmp_path, planning={"state_dir": "."})
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            Unit(
                id="add-marker/1",
                change="add-marker",
                title="A",
                repo="app",
                tier="tier1",
                groups=(1,),
            )
        ]
    )

    class Rejected:
        def run(self, unit, *, base, graph):
            raise CommitRejected(f"ruff...Failed\n- hook id: ruff\n\n{LINT_OUTPUT}")

    monkeypatch.setattr(cli, "build_runner", lambda unit, **kwargs: Rejected())

    cli.build_unit(inst, store.get("add-marker/1"), store=store)

    unit = store.get("add-marker/1")
    assert unit.state == "failed"
    assert LINT_OUTPUT in unit.history[-1].get("note", "")


GATES = [
    pytest.param(WHITESPACE_FIXER, "x = 1   \n", None, id="rewrote"),
    pytest.param(
        LINTER, LONG_LINE, lambda cwd: (cwd / "marker.py").write_text("x = 1\n"), id="found"
    ),
    pytest.param(LINTER, LONG_LINE, None, id="never-accepts"),
]


@pytest.mark.parametrize(("hook", "content", "edit"), GATES)
def test_no_attempt_goes_around_the_gate(tmp_path: Path, hook: str, content: str, edit) -> None:
    """The gate is the repo's own standard and the reason the pipeline may push
    unattended. Every attempt, the last included, commits everything with the
    hooks on: no skipping flag, no hook path pointed elsewhere, no `SKIP`, no
    subset of paths chosen to dodge it."""
    repo = repo_with_gate(tmp_path, hook)
    (repo / "marker.py").write_text(content)
    (repo / "other.py").write_text("y = 2\n")
    recorded = Recorded()

    try:
        build_commit(unit_id="add-marker/1", run=recorded, fix=Agent(edit=edit))(
            "test: covers it", cwd=repo
        )
    except CommitRejected:
        pass

    attempts = [c for c in recorded.commands if c[:1] == ["git"] and "commit" in c]
    assert len(attempts) >= 2, "a rejected commit is attempted again"
    for command in recorded.commands:
        assert "--no-verify" not in command
        assert "-n" not in command
        assert not any(arg.startswith("core.hooksPath") for arg in command)
    for env in recorded.envs:
        assert not (env or {}).get("SKIP")
    for attempt in attempts:
        after_message = attempt[attempt.index("-m") + 2 :]
        assert after_message == [], f"a commit limited to chosen paths: {attempt}"
        assert not {"-o", "--only", "-i", "--include", "--", "-a"} & set(attempt)
    adds = [c for c in recorded.commands if c[:2] == ["git", "add"]]
    assert adds and all(c == ["git", "add", "-A"] for c in adds), "everything, every time"


def test_the_count_contract_holds_with_a_gate_in_place(tmp_path: Path) -> None:
    """Nothing staged is still zero — the gate is never run for an empty
    commit — and a commit made after a retry is still one."""
    repo = repo_with_gate(tmp_path, WHITESPACE_FIXER)
    agent = Agent()
    commit = build_commit(unit_id="add-marker/1", fix=agent)

    assert commit("test: nothing yet", cwd=repo) == 0

    (repo / "marker.py").write_text("x = 1   \n")
    assert commit("test: something", cwd=repo) == 1
    assert agent.prompts == []
