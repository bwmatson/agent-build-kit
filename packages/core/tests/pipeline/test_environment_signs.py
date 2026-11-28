"""The sign table and the rule that confirms a sign with its probe (spec: environment-signs)."""

from __future__ import annotations

from typing import Any

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.pipeline.environment_signs import (
    Probes,
    Verdict,
    confirm,
    distrusted_input,
    parked_sign,
    seen,
)
from agent_build_kit.pipeline.git_output import transport_failure
from agent_build_kit.runtimes.claude_code import login_rejection
from agent_build_kit.runtimes.network import network_failure

NOT_LOGGED_IN = "Not logged in · Please run /login"
EXPIRED = "Failed to authenticate. API Error: 401 OAuth access token has expired"
WRONG_KEY = 'Failed to authenticate. API Error: 401 {"error":{"message":"invalid x-api-key"}}'
GRAPHQL = "POST graphql: Something went wrong while executing your query"
CLIENT_ID = (
    "Failed: AA_LIVE_CLIENT_ID is not set, or is blank "
    "(referenced at connections.entra_app.client_id): set it"
)
NUGET = (
    "error NU1301: Unable to load the service index for source "
    "https://pkgs.dev.azure.com/o/_packaging/f/nuget/v3/index.json"
)
UV_FETCH = "error: Failed to fetch: `https://pypi.org/simple/x/`"
PNPM_MISSING = "bash: line 1: pnpm: command not found"
ASSERTION = "FAILED tests/test_x.py::test_y - assert 1 == 2\n1 failed in 0.1s"

REPO = "app"
BRANCH = "spec/feature/1"


def repo_with(**settings: Any) -> RepoConfig:
    return RepoConfig.model_validate({"path": "app", **settings})


def found(output: str, step: str, tools: tuple[str, ...] = ()) -> list[tuple[str, str | None]]:
    return [(item.sign, item.subject) for item in seen(output, step, tools=tools)]


@pytest.mark.parametrize(
    ("step", "output", "expected"),
    [
        ("agent", NOT_LOGGED_IN, ("login", None)),
        ("agent", "OAuth access token has expired", ("login", None)),
        ("agent", EXPIRED, ("login", None)),
        ("agent", WRONG_KEY, None),
        ("e2e", NOT_LOGGED_IN, None),
        ("agent", "getaddrinfo EAI_AGAIN api.example.test", ("network", None)),
        ("agent", "connect ECONNREFUSED 127.0.0.1:443", ("network", None)),
        ("agent", "API Error: 503 Service Unavailable", None),
        (
            "exception",
            "fatal: unable to access 'https://h/r.git/': The requested URL returned error: 503",
            ("code_host", None),
        ),
        ("exception", "fatal: Could not resolve host: h.example.test", ("code_host", None)),
        ("exception", "remote: Repository not found.", None),
        ("exception", GRAPHQL, ("code_host_api", None)),
        ("exception", "GET /repos/o/r/pulls: host answered 502", ("code_host_api", None)),
        ("checks", GRAPHQL, None),
        ("checks", "npm error code E401", ("package_feed", None)),
        ("checks", "ERR_PNPM_FETCH_401", ("package_feed", None)),
        ("checks", NUGET, ("package_feed", "pkgs.dev.azure.com")),
        ("unit-test", UV_FETCH, ("package_feed", "pypi.org")),
        (
            "e2e",
            "WARNING: Could not fetch URL https://pypi.org/simple/x/: connection error",
            ("package_feed", "pypi.org"),
        ),
        ("e2e", CLIENT_ID, ("live_credential", "AA_LIVE_CLIENT_ID")),
        (
            "e2e",
            "environment variable AA_LIVE_KEY_VAULT_URL is required",
            ("live_credential", "AA_LIVE_KEY_VAULT_URL"),
        ),
        ("e2e", "value is not set", None),
        ("unit-test", CLIENT_ID, None),
        ("checks", CLIENT_ID, None),
        ("checks", PNPM_MISSING, ("missing_tool", "pnpm")),
        ("unit-test", "/bin/sh: 1: dotnet: not found", ("missing_tool", "dotnet")),
        (
            "e2e",
            "FileNotFoundError: [Errno 2] No such file or directory: 'dotnet'",
            ("missing_tool", "dotnet"),
        ),
        ("checks", "Failed to spawn: `node`", ("missing_tool", "node")),
        (
            "checks",
            "'git' is not recognized as an internal or external command",
            ("missing_tool", "git"),
        ),
        ("checks", "gti: command not found", None),
        ("checks", "Failed to spawn: `pre-commit`", None),
        ("checks", "./build.sh: not found", None),
        *[(step, ASSERTION, None) for step in ("agent", "exception", "checks", "unit-test", "e2e")],
        *[(step, "", None) for step in ("agent", "exception", "checks", "unit-test", "e2e")],
    ],
)
def test_the_signs_in_an_output_are_read_for_the_step_it_came_from(
    step: str, output: str, expected: tuple[str, str | None] | None
) -> None:
    assert found(output, step) == ([expected] if expected else [])


def test_a_tool_the_repository_lists_is_read_and_one_it_does_not_is_not() -> None:
    output = "bash: line 1: terraform: command not found"

    assert found(output, "checks", tools=("terraform",)) == [("missing_tool", "terraform")]
    assert found(output, "checks") == []


@pytest.mark.parametrize(
    "sample",
    [NOT_LOGGED_IN, EXPIRED, WRONG_KEY, "OAuth access token has expired", ASSERTION],
)
def test_the_login_sign_answers_as_login_rejection_does(sample: str) -> None:
    signs = [item.sign for item in seen(sample, "agent")]

    assert ("login" in signs) == login_rejection(sample)


@pytest.mark.parametrize(
    "sample",
    ["getaddrinfo EAI_AGAIN h", "connect ECONNREFUSED 1.2.3.4:443", "API Error: 503", ASSERTION],
)
def test_the_network_sign_answers_as_network_failure_does(sample: str) -> None:
    signs = [item.sign for item in seen(sample, "agent")]

    assert ("network" in signs) == (network_failure(sample) is not None)


@pytest.mark.parametrize(
    "sample",
    [
        "The requested URL returned error: 503",
        "Could not resolve host: h",
        "Repository not found",
        ASSERTION,
    ],
)
def test_the_code_host_sign_answers_as_transport_failure_does(sample: str) -> None:
    signs = [item.sign for item in seen(sample, "exception")]

    assert ("code_host" in signs) == (transport_failure(sample) is not None)


ENV_INPUTS = {"environment": {"sync": ["s"], "check": ["c"], "inputs": {"lock": ["deps/*.lock"]}}}
FEED_NAMED = {"environment_signs": {"distrusted": {"package_feed": ["feed/**"]}}}
CREDENTIAL_NAMED = {
    "environment_signs": {"distrusted": {"live_credential": ["agent-assessment/run.yml"]}}
}
TOOL_INPUTS = {
    "environment": {"sync": ["s"], "check": ["c"], "inputs": {"dependencies": ["d.txt"]}}
}


@pytest.mark.parametrize(
    ("sign", "changed", "settings", "expected"),
    [
        ("package_feed", ["web/pnpm-lock.yaml"], {}, "web/pnpm-lock.yaml"),
        ("package_feed", ["a.py", ".NPMRC"], {}, ".NPMRC"),
        ("package_feed", ["src/Global.json"], {}, "src/Global.json"),
        ("package_feed", ["nuget.config"], {}, "nuget.config"),
        ("package_feed", ["Directory.Packages.props"], {}, "Directory.Packages.props"),
        ("package_feed", ["src/app.py"], {}, None),
        ("package_feed", ["deps/x.lock"], ENV_INPUTS, "deps/x.lock"),
        ("package_feed", ["feed/a/b.cfg"], FEED_NAMED, "feed/a/b.cfg"),
        ("package_feed", ["feed/a/b.cfg"], {}, None),
        ("missing_tool", [".tool-versions"], {}, ".tool-versions"),
        ("missing_tool", ["web/.nvmrc"], {}, "web/.nvmrc"),
        ("missing_tool", ["d.txt"], TOOL_INPUTS, "d.txt"),
        ("missing_tool", ["pnpm-lock.yaml"], {}, None),
        ("live_credential", ["agent-assessment/run.yml", "x.py"], {}, None),
        (
            "live_credential",
            ["x.py", "agent-assessment/run.yml"],
            CREDENTIAL_NAMED,
            "agent-assessment/run.yml",
        ),
        ("code_host_api", ["web/pnpm-lock.yaml", ".nvmrc", "src/app.py"], {}, None),
    ],
)
def test_a_sign_is_distrusted_when_the_branch_changes_one_of_its_inputs(
    sign: str, changed: list[str], settings: dict[str, Any], expected: str | None
) -> None:
    assert distrusted_input(sign, changed, repo_with(**settings)) == expected


def test_the_built_in_inputs_are_distrusted_with_no_repository_settings() -> None:
    assert distrusted_input("package_feed", ["uv.lock"], None) == "uv.lock"


class AskedProbes:
    """A `Probes` that records each question and answers one verdict, or raises it."""

    def __init__(self, answer: Verdict | Exception) -> None:
        self.asked: list[tuple[Any, ...]] = []
        self._answer = answer

    def _ask(self, *question: Any) -> Verdict:
        self.asked.append(question)
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer

    def probes(self) -> Probes:
        return Probes(
            forge_read=lambda repo, branch: self._ask("forge_read", repo, branch),
            feed=lambda repo, host: self._ask("feed", repo, host),
            credential=lambda name: self._ask("credential", name),
            tool=lambda name: self._ask("tool", name),
        )


def judged(
    output: str,
    step: str,
    answer: Verdict | Exception,
    changed: list[str] | None = None,
    repo_config: RepoConfig | None = None,
):
    probes = AskedProbes(answer)
    said: list[str] = []
    result = confirm(
        output,
        where=step,
        repo=REPO,
        branch=BRANCH,
        changed=changed or [],
        repo_config=repo_config,
        probes=probes.probes(),
        say=said.append,
    )
    return result, probes.asked


@pytest.mark.parametrize(
    ("output", "step", "answer", "changed", "confirmed", "asked"),
    [
        (
            CLIENT_ID,
            "e2e",
            Verdict.FAILS,
            [],
            ("live_credential", "AA_LIVE_CLIENT_ID"),
            [("credential", "AA_LIVE_CLIENT_ID")],
        ),
        (CLIENT_ID, "e2e", Verdict.PASSES, [], None, [("credential", "AA_LIVE_CLIENT_ID")]),
        (CLIENT_ID, "e2e", Verdict.UNKNOWN, [], None, [("credential", "AA_LIVE_CLIENT_ID")]),
        (CLIENT_ID, "e2e", RuntimeError("boom"), [], None, [("credential", "AA_LIVE_CLIENT_ID")]),
        (ASSERTION, "unit-test", Verdict.FAILS, [], None, []),
        (
            PNPM_MISSING,
            "checks",
            Verdict.FAILS,
            ["src/app.py"],
            ("missing_tool", "pnpm"),
            [("tool", "pnpm")],
        ),
        (PNPM_MISSING, "checks", Verdict.FAILS, [".nvmrc"], None, []),
        (NUGET, "checks", Verdict.FAILS, ["web/pnpm-lock.yaml"], None, []),
        (
            NUGET,
            "checks",
            Verdict.FAILS,
            ["src/app.py"],
            ("package_feed", "pkgs.dev.azure.com"),
            [("feed", REPO, "pkgs.dev.azure.com")],
        ),
        (
            GRAPHQL,
            "exception",
            Verdict.FAILS,
            [],
            ("code_host_api", None),
            [("forge_read", REPO, BRANCH)],
        ),
        (
            "npm error code E401\n" + PNPM_MISSING,
            "checks",
            Verdict.FAILS,
            ["package-lock.json"],
            ("missing_tool", "pnpm"),
            [("tool", "pnpm")],
        ),
    ],
)
def test_a_sign_is_confirmed_only_when_its_probe_fails_and_asks_what_its_row_says(
    output: str,
    step: str,
    answer: Verdict | Exception,
    changed: list[str],
    confirmed: tuple[str, str | None] | None,
    asked: list[tuple[Any, ...]],
) -> None:
    result, questions = judged(output, step, answer, changed)

    assert ((result.sign, result.subject) if result else None) == confirmed
    assert questions == asked
    if result:
        subject = f" {result.subject}" if result.subject else ""
        assert result.note.startswith(f"environment failure [{result.sign}{subject}]:")


def test_a_token_in_the_quoted_line_is_redacted_from_the_note() -> None:
    token = "ghp_" + "a1" * 18
    output = f"error: Failed to fetch: `https://user:{token}@pypi.org/simple/x/`"

    result, _ = judged(output, "checks", Verdict.FAILS)

    assert result is not None
    assert token not in result.note
    assert token not in result.line


def test_a_confirmed_note_is_read_back_and_no_other_note_is() -> None:
    result, _ = judged(PNPM_MISSING, "checks", Verdict.FAILS)
    assert result is not None
    feed, _ = judged("npm error code E401", "checks", Verdict.FAILS)
    assert feed is not None

    assert parked_sign(result.note) == ("missing_tool", "pnpm")
    assert parked_sign(feed.note) == ("package_feed", None)
    assert parked_sign(".env has no AA_KEY=") is None
    assert parked_sign("") is None
    assert parked_sign("environment failure [nonesuch x]: a line") is None
