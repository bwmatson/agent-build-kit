"""Workflow actions run on Node 24 at an exact release, on a pinned runner (spec: ci-workflows)."""

from __future__ import annotations

import pytest

from tests.ci_workflows import FIRST_NODE_24_MAJOR, POINTER, RUNNER, WORKFLOWS, check_workflow

SHA = "3d3c42e5aac5ba805825da76410c181273ba90b1"


def workflow(uses: str = "actions/checkout@v7.0.1", runs_on: str = RUNNER) -> str:
    return f"name: CI\njobs:\n  build:\n    runs-on: {runs_on}\n    steps:\n      - uses: {uses}\n"


def test_the_table_holds_the_first_node_24_majors() -> None:
    assert check_workflow("ci.yml", workflow()) == []
    assert FIRST_NODE_24_MAJOR == {
        "actions/checkout": 5,
        "actions/setup-node": 5,
        "actions/setup-python": 6,
        "astral-sh/setup-uv": 7,
    }


def test_the_shipped_workflows_pass() -> None:
    files = sorted(WORKFLOWS.glob("*.yml"))
    assert files
    problems = [p for f in files for p in check_workflow(f.name, f.read_text())]

    assert problems == []


def test_an_action_below_its_node_24_release_fails_naming_file_job_and_step() -> None:
    problems = check_workflow("ci.yml", workflow(uses="actions/checkout@v4.2.0"))

    assert len(problems) == 1
    assert "ci.yml" in problems[0]
    assert "build" in problems[0]
    assert "actions/checkout@v4.2.0" in problems[0]
    assert "5" in problems[0]


def test_an_action_missing_from_the_table_says_to_add_it() -> None:
    problems = check_workflow("ci.yml", workflow(uses="actions/setup-uv@v3.0.0"))

    assert len(problems) == 1
    assert "add actions/setup-uv to the table" in problems[0]


@pytest.mark.parametrize(
    "uses",
    [
        "astral-sh/setup-uv@v10",
        "astral-sh/setup-uv@main",
        "astral-sh/setup-uv@latest",
        "${{ matrix.action }}",
    ],
)
def test_a_floating_or_expression_reference_fails_naming_it(uses: str) -> None:
    quoted = f"'{uses}'" if uses.startswith("$") else uses

    problems = check_workflow("ci.yml", workflow(uses=quoted))

    assert len(problems) == 1
    assert uses in problems[0]


@pytest.mark.parametrize("runs_on", ["ubuntu-latest", "[self-hosted, macos-latest]"])
def test_a_floating_runner_fails_naming_the_job(runs_on: str) -> None:
    problems = check_workflow("ci.yml", workflow(runs_on=runs_on))

    assert len(problems) == 1
    assert "ci.yml" in problems[0]
    assert "build" in problems[0]


def test_a_matrix_runner_value_ending_in_latest_fails() -> None:
    text = (
        "jobs:\n"
        "  build:\n"
        "    strategy:\n"
        "      matrix:\n"
        "        os: [ubuntu-24.04, windows-latest]\n"
        "    runs-on: ${{ matrix.os }}\n"
        "    steps:\n"
        "      - uses: actions/checkout@v7.0.1\n"
    )

    problems = check_workflow("ci.yml", text)

    assert any("windows-latest" in p and "build" in p for p in problems)


def test_a_sha_a_local_action_and_a_docker_reference_pass() -> None:
    text = (
        "jobs:\n"
        "  build:\n"
        f"    runs-on: {RUNNER}\n"
        "    steps:\n"
        f"      - uses: actions/checkout@{SHA}\n"
        "      - uses: ./.github/actions/local\n"
        "      - uses: docker://alpine:3.20\n"
    )

    assert check_workflow("ci.yml", text) == []


def test_every_failure_message_ends_by_pointing_at_the_policy() -> None:
    assert POINTER == "see AGENTS.md, CI workflows"

    problems = check_workflow(
        "ci.yml", workflow(uses="actions/checkout@v4", runs_on="ubuntu-latest")
    )

    assert len(problems) >= 2
    assert all(p.endswith(POINTER) for p in problems)


def test_a_workflow_with_no_jobs_is_read_without_error() -> None:
    assert check_workflow("empty.yml", "name: Empty\non: push\n") == []
    assert check_workflow("empty.yml", "name: Empty\njobs: {}\n") == []


def test_a_reusable_workflow_job_is_read_without_error() -> None:
    text = "jobs:\n  call:\n    uses: ./.github/workflows/other.yml\n"

    assert check_workflow("ci.yml", text) == []
