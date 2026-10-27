"""`abk doctor`'s git probe replaces `packed-refs` the way `git pack-refs` does and runs
`git log -1` again, and names the path when the step cannot read it (spec: sandbox-git-rewrites)."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from agent_build_kit import sandboxes
from agent_build_kit.cli import doctor
from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.sandboxes import SandboxPolicy
from tests.cli.sandbox_cli_support import CountingBackend, switch_on
from tests.cli.test_doctor import Answers, workspace  # noqa: F401 — fixture
from tests.factories import which_all


class Replacing(CountingBackend):
    """Runs every command as it is. A step that replaces `packed-refs` is refused the new file
    unless the policy reads the git directory as a directory."""

    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[str] = []
        self.policies: list[SandboxPolicy] = []

    def command(self, policy: SandboxPolicy, argv: Sequence[str]) -> list[str]:
        plain = super().command(policy, argv)
        script = argv[-1]
        objects = [p for p in policy.write if p.name == "objects"]
        if not objects or "packed-refs" not in script:
            return plain
        self.scripts.append(script)
        self.policies.append(policy)
        common = objects[0].parent
        if any(common.is_relative_to(p) for p in policy.read):
            return plain
        message = f"fatal: unable to access '{common / 'packed-refs'}': Permission denied"
        return ["sh", "-c", f'echo "{message}" >&2; exit 128']


@pytest.fixture
def replacing() -> Iterator[Replacing]:
    with sandboxes.isolated():
        found = Replacing()
        sandboxes.register(found)
        yield found


def sandbox_checks(config: Path) -> list[Check]:
    checks = run_doctor(config, run=Answers(), which=which_all)
    return [c for c in checks if "sandbox" in c.name]


def test_the_probe_replaces_packed_refs_then_runs_git_log_again(
    workspace: Path,  # noqa: F811 — fixture
    replacing: Replacing,
) -> None:
    switch_on(workspace / "abk.yaml")

    found = sandbox_checks(workspace / "abk.yaml")

    assert replacing.scripts, replacing.asked
    after = replacing.scripts[0].split("packed-refs", 1)[1]
    assert "git log -1" in after
    assert [c.status for c in found] == ["ok"]


def test_the_probe_holds_the_git_directory_back_from_running_as_a_real_step_does(
    workspace: Path,  # noqa: F811 — fixture
    replacing: Replacing,
) -> None:
    switch_on(workspace / "abk.yaml")

    sandbox_checks(workspace / "abk.yaml")

    policy = replacing.policies[0]
    common = next(p.parent for p in policy.write if p.name == "objects")
    assert policy.no_execute == (common,)
    assert common in policy.read


def test_a_policy_of_single_files_fails_the_probe_naming_the_file(
    workspace: Path,  # noqa: F811 — fixture
    replacing: Replacing,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def single_files(tree: Path) -> list[Path]:
        common = tree.resolve() / ".git"
        return [p for p in (common / "config", common / "info") if p.exists()]

    monkeypatch.setattr(doctor, "git_reads", single_files)
    switch_on(workspace / "abk.yaml")

    found = sandbox_checks(workspace / "abk.yaml")

    failed = [c for c in found if c.status == "FAIL"]
    assert failed, found
    assert "packed-refs" in failed[0].detail
