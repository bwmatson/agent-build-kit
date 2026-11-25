"""A real model reviews a plan that cannot end green (spec: plan-review, group 2).

A fixture repository and change are written by the test. The change is shaped as a real one was
before its last group of the first unit was fixed: the unit carrying groups 1 to 12 moves folders
out of `src/`, and the one test file that asserts `src/` changes only in group 14, which a later
unit carries. So the first unit ends with that test red. The review runs through the kit's own
`review_changes` with the real runtime, and what is asserted is the recorded review's findings:
one names the first unit's last group (or any of its groups) and the test file.

Needs Claude Code on this host, logged in as the account the environment names, as the kit's
other claude_code live tests do. Where the `claude` program is missing the test is held (skipped).
The plan repair is turned off, so the recorded findings are the review's own and the seconds are
those of the one review call. Bills on demand, so it is marked e2e-test and excluded from the
default suite. The seconds the review took are in the assertion message and the test's report,
for the pull request.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import pytest

from agent_build_kit import claude_account, config, runtimes
from agent_build_kit.pipeline import plan_review
from agent_build_kit.settings import settings
from tests.conftest import make_private_trees_installation
from tests.factories import git, init_repo
from tests.live_account import environment_account
from tests.tick_pass import stored

pytestmark = [pytest.mark.e2e, pytest.mark.runtime_claude_code]

CLAUDE_ONLY_REASONS = {
    "test_a_real_review_names_the_unit_that_cannot_end_green_and_the_test_that_asserts_src": (
        "the review's model call goes through the runtime the machine names; this group checks "
        "what the model finds, which one runtime shows"
    ),
}

CHANGE = "tidy"
ASSERTING_TEST = "tests/test_layout.py"
FIRST_UNIT_GROUPS = tuple(range(1, 13))
LATER_UNIT_GROUPS = (13, 14)

PROPOSAL = "# Tidy\n\nMove every package folder out of `src/` to the top level of the repo.\n"
DESIGN = (
    "# Design\n\nOne group moves one folder. The layout test asserts where the folders are, "
    "so it is updated once the last folder has moved.\n"
)
SPEC = (
    "## ADDED Requirements\n\n### Requirement: The folders sit at the top level\n\n"
    "The packages SHALL live at the top level of the repository, not under `src/`.\n\n"
    "#### Scenario: The layout (unit)\n- **GIVEN** the repo\n- **WHEN** it is listed\n"
    "- **THEN** no package is under `src/`\n"
)

LAYOUT_TEST = """\
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_every_package_is_under_src() -> None:
    packages = sorted(p.name for p in (ROOT / "src").iterdir() if p.is_dir())
    assert packages == sorted(f"pkg{n}" for n in range(1, 13))
"""


def tasks_text() -> str:
    """Twelve groups that each move one folder out of `src/`, a docs group, and the group that
    updates the layout test, which asserts `src/`."""
    parts = [
        "# Tidy the layout\n\nAcceptance: none: a fixture about plan review\n",
    ]
    for number in FIRST_UNIT_GROUPS:
        last = " Then delete the now-empty `src/`." if number == FIRST_UNIT_GROUPS[-1] else ""
        parts.append(
            f"## {number}. [app] [unit-test] Move pkg{number} out of src\n\n"
            f"- [ ] {number}.1 Move `src/pkg{number}/` to `pkg{number}/` with `git mv`, and fix "
            f"the imports.{last} Verify: the suite passes.\n"
        )
    parts.append(
        "## 13. [app] [unit-test] Describe the layout\n\n"
        "- [ ] 13.1 Describe the new layout in `README.md`. Verify: the suite passes.\n"
    )
    parts.append(
        "## 14. [app] [unit-test] Update the layout test\n\n"
        f"- [ ] 14.1 Test: `{ASSERTING_TEST}` asserts the folders are at the top level. "
        "Verify: green.\n"
    )
    return "\n".join(parts)


@pytest.fixture(scope="module")
def account() -> claude_account.Account | None:
    """The account the environment names, read before the autouse fixture removes it from each
    test; None for the default account."""
    return environment_account("plan-review")


@pytest.fixture
def claude_account_env(
    account: claude_account.Account | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's `claude` runs as the named account, as the other live tests' do."""
    if shutil.which("claude") is None:
        pytest.skip("claude is not on PATH: the kit's runtime: claude_code e2e is not available")
    if account is not None:
        monkeypatch.setenv(claude_account.VARIABLE, str(account.config_dir))
    # The runtime in force is read from the settings, which read the environment once at import.
    monkeypatch.setattr(settings, "runtime", "claude_code")


def write_repo(path: Path) -> None:
    """The app's checkout: twelve folders under `src/` and the test that asserts them."""
    init_repo(path)
    for number in FIRST_UNIT_GROUPS:
        folder = path / "src" / f"pkg{number}"
        folder.mkdir(parents=True)
        (folder / "__init__.py").write_text(f"NAME = 'pkg{number}'\n")
    (path / "tests").mkdir()
    (path / ASSERTING_TEST).write_text(LAYOUT_TEST)
    (path / "README.md").write_text("# app\n")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "the layout")


def test_a_real_review_names_the_unit_that_cannot_end_green_and_the_test_that_asserts_src(
    tmp_path: Path, claude_account_env: None
) -> None:
    # Repairs are off: the review makes one model call and records its own findings unrepaired.
    inst = make_private_trees_installation(
        tmp_path, planning={"review_plans": True, "plan_review_repairs": 0}
    )
    write_repo(inst.repo("app").path)
    folder = inst.changes_dir / CHANGE
    (folder / "specs" / "layout").mkdir(parents=True)
    (folder / "proposal.md").write_text(PROPOSAL)
    (folder / "design.md").write_text(DESIGN)
    (folder / "specs" / "layout" / "spec.md").write_text(SPEC)
    (folder / "tasks.md").write_text(tasks_text())
    units = [
        stored(f"{CHANGE}/1", groups=FIRST_UNIT_GROUPS, title="Move every folder out of src"),
        stored(
            f"{CHANGE}/2",
            groups=LATER_UNIT_GROUPS,
            depends_on=(f"{CHANGE}/1",),
            title="Describe the layout and update its test",
        ),
    ]
    said: list[str] = []

    started = time.monotonic()
    plan_review.review_changes(inst, units, mechanical=lambda path: [], say=said.append)
    seconds = time.monotonic() - started

    review = plan_review.read_reviews(plan_review.record_path(inst)).get(CHANGE)
    log = "\n".join(said)
    assert review is not None, f"the review was not recorded: {log}"
    assert not review.failed, f"the review failed: {review.error}\n{log}"
    named = [
        finding
        for finding in review.findings
        if finding.group in FIRST_UNIT_GROUPS and Path(ASSERTING_TEST).name in finding.evidence
    ]
    # The finding, the model and the seconds are what the pull request records.
    runtime = runtimes.active().name
    model = config.models().plan or "runtime default"
    summary = (
        f"{len(review.findings)} finding(s) in {seconds:.0f}s, model {model}, runtime {runtime}"
    )
    print(f"plan review: {summary}")
    for finding in review.findings:
        print(f"  group {finding.group}, question {finding.question}: {finding.evidence}")
    assert named, (
        f"no finding names a group of unit 1 (groups 1 to 12) and {ASSERTING_TEST}; "
        f"findings: {review.findings}; {summary}"
    )
