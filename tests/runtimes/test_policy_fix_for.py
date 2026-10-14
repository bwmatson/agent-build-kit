"""What fix to print for a report that leaves a class unenforced."""

from __future__ import annotations

from agent_build_kit.config import RuntimeConfig
from agent_build_kit.runtimes import PolicyReport
from agent_build_kit.runtimes.policy_check import fix_for

UNENFORCED = PolicyReport(
    ok=False, unenforced=("merging a pull request", "pushing to a default branch")
)
ADVISED = PolicyReport(ok=False, unenforced=UNENFORCED.unenforced, fix="the runtime's own advice")


def test_the_installation_s_fix_comes_first() -> None:
    entry = RuntimeConfig(policy_fix=["scripts/constrain-agent.sh", "--strict"])

    assert fix_for("probed", entry, ADVISED) == "scripts/constrain-agent.sh --strict"


def test_without_one_the_runtime_s_own_advice_is_printed() -> None:
    assert fix_for("probed", RuntimeConfig(), ADVISED) == "the runtime's own advice"


def test_with_neither_the_key_to_set_is_named() -> None:
    assert "runtimes.probed.policy_fix" in fix_for("probed", RuntimeConfig(), UNENFORCED)
