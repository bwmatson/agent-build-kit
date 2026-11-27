"""Every integration test file that runs the OpenSpec CLI requests the fixture that probes it."""

from __future__ import annotations

import ast
import re
from pathlib import Path

INTEGRATION = Path(__file__).parent / "integration"
FIXTURE = "openspec_cli"
RUNS_THE_CLI = re.compile(r"openspec\.(run|validate)\(|cmd_check\(")


def runs_the_cli(text: str) -> bool:
    if RUNS_THE_CLI.search(text):
        return True
    return bool(re.search(r"\bmain\(", text) and re.search(r'"(init|check)"', text))


def requests_the_fixture(text: str) -> bool:
    return bool(re.search(rf'usefixtures\(\s*"{FIXTURE}"', text))


def integration_files() -> list[Path]:
    return sorted(
        path
        for path in INTEGRATION.glob("test_*.py")
        if "pytest.mark.integration" in path.read_text()
    )


def test_every_integration_file_that_runs_the_cli_requests_the_fixture_and_no_other_does() -> None:
    needs = {p.name for p in integration_files() if runs_the_cli(p.read_text())}
    requests = {p.name for p in integration_files() if requests_the_fixture(p.read_text())}

    assert needs, "the guard finds no integration file that runs the CLI"
    assert needs - requests == set(), (
        f"runs the OpenSpec CLI without the {FIXTURE} fixture: {sorted(needs - requests)}"
    )
    assert requests - needs == set(), (
        f"requests the {FIXTURE} fixture without running the CLI: {sorted(requests - needs)}"
    )


def test_openspec_cli_sets_the_env_of_a_session_fixture_that_probes_the_cli_once() -> None:
    conftest = INTEGRATION / "conftest.py"
    assert conftest.exists(), "tests/integration/conftest.py defines the fixture"
    functions = {
        node.name: node
        for node in ast.walk(ast.parse(conftest.read_text()))
        if isinstance(node, ast.FunctionDef)
    }
    cache = functions["openspec_cache"]
    fixture = functions[FIXTURE]
    assert "session" in ast.unparse(cache.decorator_list[0])
    assert "scope" not in ast.unparse(fixture.decorator_list[0])
    assert "openspec_cache" in [arg.arg for arg in fixture.args.args]
    assert "setenv" in ast.unparse(fixture)
    # The session fixture reaches `probe` through the warm helper it passes to the shared fetch.
    assert "_warm_openspec" in ast.unparse(cache)
    assert "probe(" in ast.unparse(functions["_warm_openspec"])
    assert "npm_config_cache" in ast.unparse(functions["_openspec_overrides"])
