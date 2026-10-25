"""No document, and no text the pipeline writes, says a person merges every pull request."""

from pathlib import Path

from agent_build_kit.pipeline.command_policy import check_command
from agent_build_kit.pipeline.pr_body import build_pr_body
from tests.factories import stored_unit as unit
from tests.old_merge_rule import statements
from tests.repo_docs import repo_markdown

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
EXEMPT = {
    ROOT / "CHANGELOG.md",
    ROOT / "docs" / "agent-efficient-coding-philosophy.md",
    ROOT / "docs" / "risk-tiered-review-design.md",
}


def test_no_markdown_file_states_a_person_merges_every_pull_request() -> None:
    files = repo_markdown([SKILLS, *EXEMPT])
    assert ROOT / "README.md" in files
    found = [
        f"{path.relative_to(ROOT)}:{line}"
        for path in files
        for line in statements(path.read_text(encoding="utf-8"))
    ]

    assert not found, found


def test_the_footer_and_the_refusal_do_not_state_it() -> None:
    body = build_pr_body(unit(), graph=[unit()], base="main")
    reason = check_command("gh pr merge 4", branch="spec/add-marker/1-unit").reason or ""

    assert statements(body) == []
    assert statements(reason) == []
