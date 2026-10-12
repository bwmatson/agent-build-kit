"""The recommended policy's globs are held to its own samples, to the policy
check's probe and to the spellings table.

A test loops over the table and names every command at fault, so one failure
shows them all; each opens by asserting the table is not empty.
"""

from __future__ import annotations

from agent_build_kit.pipeline.command_spellings import SPELLINGS, Reader, probe_rows
from agent_build_kit.runtimes.acp import PROBE_CLASSES
from agent_build_kit.runtimes.recommended_policy import (
    KNOWN_FALSE_POSITIVES,
    KNOWN_GAPS,
    RECOMMENDED,
    UNCOVERED,
    ClassPolicy,
    matches,
)
from tests.spelling_rows import FORCE_PUSH, PUSH

GRAPHQL = "merging a pull request through the host's GraphQL API"
# Commands a build run needs, written here so the table is held to a list it did not write.
NEEDED = (
    "git push --force-with-lease origin spec/main-menu/1",
    "git push -u origin spec/master-plan/2",
    "git push origin feature/domain",
    "git -C /tmp/work push origin spec/add-marker/1",
    "gh pr view 1",
    "gh pr create --fill",
    "gh pr checks 1",
    "gh pr list --state open",
    "gh -R example/app pr view 1",
    "gh api repos/example/app/pulls/1",
    "gh api repos/example/app/pulls/1/comments",
    "git -C /tmp/work log --oneline",
    "git -C /tmp/work status",
    "git --no-pager diff",
    "git commit -m 'add the marker'",
    "make test",
)


def covering(policy: ClassPolicy) -> tuple[str, ...]:
    """The globs that cover a class: a force push is covered by the push class's too."""
    if policy.label != FORCE_PUSH:
        return policy.globs
    pushes = [p.globs for p in RECOMMENDED if p.label == PUSH]
    return policy.globs + (pushes[0] if pushes else ())


def every_glob() -> list[str]:
    return [glob for policy in RECOMMENDED for glob in policy.globs]


def refused_by_any(command: str) -> bool:
    return any(matches(glob, command) for glob in every_glob())


def variants(command: str) -> list[str]:
    """The command as a person or an agent might surround it."""
    return [
        command,
        f"echo start && {command}",
        f"false || {command}",
        f"cat log | {command}",
        f"cd . ; {command}",
        f"echo start\n{command}",
        f"{command} && echo done",
        f"{command} | cat",
    ]


def test_the_table_covers_the_classes_the_recommendation_names() -> None:
    labels = {policy.label for policy in RECOMMENDED}
    assert {"amending a commit", PUSH, FORCE_PUSH, "merging a pull request"} <= labels
    assert {"merging a pull request through the host's raw API", GRAPHQL} <= labels
    assert all(policy.refused_samples and policy.allowed_samples for policy in RECOMMENDED)


def test_every_row_the_globs_read_is_a_refused_sample_of_its_class() -> None:
    read = {
        label: {s.command for s in spellings if Reader.GLOB in s.readers}
        for label, spellings in SPELLINGS.items()
    }
    assert any(read.values()), "no row of the spellings table carries the glob reader"
    by_label = {policy.label: policy for policy in RECOMMENDED}
    missing = {
        command
        for label, commands in read.items()
        for command in commands
        if label not in by_label or command not in by_label[label].refused_samples
    }
    assert missing == set()


def test_the_samples_only_a_glob_can_show_are_refused_samples() -> None:
    samples = [s for policy in RECOMMENDED for s in policy.refused_samples]
    graphql = [
        s for policy in RECOMMENDED if policy.label == GRAPHQL for s in policy.refused_samples
    ]
    assert "git amend" in samples
    assert any("refs/heads/main" in s for s in samples)
    assert any("'HEAD:main'" in s or '"HEAD:main"' in s for s in samples)
    assert any("mergePullRequest" in s for s in graphql)


def test_every_refused_sample_matches_a_glob_of_its_class_in_every_surrounding() -> None:
    assert RECOMMENDED, "the table is empty"
    missed = [
        command
        for policy in RECOMMENDED
        for sample in policy.refused_samples
        for command in variants(sample)
        if not any(matches(glob, command) for glob in covering(policy))
    ]
    assert missed == []


def test_no_allowed_sample_matches_any_glob_of_any_class() -> None:
    assert RECOMMENDED, "the table is empty"
    allowed = [s for policy in RECOMMENDED for s in policy.allowed_samples]
    assert [c for c in (*allowed, *NEEDED) if refused_by_any(c)] == []


def test_the_allowed_samples_include_what_a_build_run_needs() -> None:
    allowed = [s for policy in RECOMMENDED for s in policy.allowed_samples]
    assert any("--force-with-lease" in s and "main" in s for s in allowed)
    assert any("push" in s and "master" in s for s in allowed)
    for needed in ("gh pr view", "gh pr create", "gh pr checks", "git -C "):
        assert any(s.startswith(needed) for s in allowed), needed
    assert any(s.startswith("gh api ") and "merge" not in s for s in allowed)


def test_every_probe_row_of_a_covered_class_matches_a_glob_of_it() -> None:
    assert RECOMMENDED, "the table is empty"
    by_label = {policy.label: policy for policy in RECOMMENDED}
    rows = [(label, spelling) for label, spelling in probe_rows() if label in by_label]
    assert rows, "the policy check probes no class the recommendation covers"
    missed = {
        f"{label} ({spelling.name}): {spelling.command}"
        for label, spelling in rows
        if not any(matches(glob, spelling.command) for glob in covering(by_label[label]))
    }
    assert missed == set()


def test_the_classes_the_check_attempts_without_a_glob_are_listed_with_a_reason() -> None:
    covered = {policy.label for policy in RECOMMENDED}
    attempted = {label for _command, label in PROBE_CLASSES}
    assert covered, "the table is empty"
    assert {u.label for u in UNCOVERED} == attempted - covered
    assert all(u.reason.strip() for u in UNCOVERED)
    assert {"skipping the commit gate", "a hard reset", "a bare force push"} <= {
        u.label for u in UNCOVERED
    }


def test_what_the_check_attempts_without_a_glob_is_matched_by_none() -> None:
    uncovered = {u.label for u in UNCOVERED}
    assert uncovered, "no class is listed as uncovered"
    assert [c for c, label in PROBE_CLASSES if label in uncovered and refused_by_any(c)] == []


def test_each_documented_false_positive_still_matches_a_glob() -> None:
    assert KNOWN_FALSE_POSITIVES, "no false positive is documented"
    assert any("--amend" in c for c in KNOWN_FALSE_POSITIVES)
    assert any("push" in c and "main" in c for c in KNOWN_FALSE_POSITIVES)
    assert [c for c in KNOWN_FALSE_POSITIVES if not refused_by_any(c)] == []


def test_each_documented_gap_is_still_matched_by_no_glob() -> None:
    assert KNOWN_GAPS, "no gap is documented"
    assert any("-c " in c for c in KNOWN_GAPS)
    assert any(c.strip() == "git push" for c in KNOWN_GAPS)
    assert [c for c in KNOWN_GAPS if refused_by_any(c)] == []
