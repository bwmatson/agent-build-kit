"""No text the pipeline writes says a person merges every pull request. That no Markdown file says
it is an entry of the exclusion table (`tests/exclusions.py`)."""

from agent_build_kit.pipeline.command_policy import check_command
from agent_build_kit.pipeline.pr_body import build_pr_body
from tests.factories import stored_unit as unit
from tests.old_merge_rule import statements


def test_the_footer_and_the_refusal_do_not_state_it() -> None:
    body = build_pr_body(unit(), graph=[unit()], base="main")
    reason = check_command("gh pr merge 4", branch="spec/add-marker/1-unit").reason or ""

    assert statements(body) == []
    assert statements(reason) == []
