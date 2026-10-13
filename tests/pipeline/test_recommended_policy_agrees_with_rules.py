"""The recommended globs and the command rules agree on the commands both own:
every refused sample the rules forbid is refused by them in a unit's branch, and
a sample only a glob refuses is named in the table."""

from __future__ import annotations

from agent_build_kit.pipeline.command_policy import check_command
from agent_build_kit.runtimes.acp import probe_branch
from agent_build_kit.runtimes.recommended_policy import RECOMMENDED


def test_every_refused_sample_the_rules_forbid_is_refused_by_them() -> None:
    assert RECOMMENDED, "the table is empty"
    glob_only = {s for policy in RECOMMENDED for s in policy.glob_only}
    allowed = [
        sample
        for policy in RECOMMENDED
        for sample in policy.refused_samples
        if sample not in glob_only and check_command(sample, branch=probe_branch()).allowed
    ]
    assert allowed == []


def test_the_samples_only_a_glob_refuses_are_exactly_the_ones_listed() -> None:
    assert RECOMMENDED, "the table is empty"
    judged_allowed = {
        sample
        for policy in RECOMMENDED
        for sample in policy.refused_samples
        if check_command(sample, branch=probe_branch()).allowed
    }
    listed = {s for policy in RECOMMENDED for s in policy.glob_only}
    assert listed == judged_allowed
    for policy in RECOMMENDED:
        assert set(policy.glob_only) <= set(policy.refused_samples)
