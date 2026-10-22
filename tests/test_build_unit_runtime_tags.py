"""The build live test holds no ACP-only step.

That it runs over every runtime, each parameter carrying its tag, is pinned in
`test_live_test_rewrite.py`. The agent's refusal of a forbidden command and the check that the
agent lists the build's session are added later by the change that adds the ACP-only steps.
"""

from __future__ import annotations

from pathlib import Path

MODULE = Path(__file__).parent / "integration" / "test_build_unit.py"


def test_the_build_test_holds_no_acp_only_step() -> None:
    source = MODULE.read_text().lower()

    assert "amend" not in source
    assert "assert_unit_session_listed" not in source
    assert "runtime_acp" not in source
