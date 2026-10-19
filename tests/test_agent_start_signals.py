"""Whether a live test starts an agent is decided per test from the table of signals."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.live_tag_drift import (
    AGENT_SIGNALS,
    agent_start_notes,
    drift,
    drifted,
)
from tests.runtime_tag_collection import ROOT

HEADER = "import pytest\n\npytestmark = pytest.mark.local_stack\n"
PLAIN = "\n\ndef test_plain():\n    pass\n"
DETECT = "from agent_build_kit.runtimes.acp import AcpRuntime\n"

# One module per signal: `use` is the import, `call` the statement of the test that starts.
SIGNALS = {
    "tick": ("from tests.scratch_tick import run_tick\n", "run_tick(None)"),
    "detect": (DETECT, "AcpRuntime().detect(None, None)"),
    "list_models": (DETECT, 'AcpRuntime().list_models(["agent"])'),
    "which_claude": ("import shutil\n", 'shutil.which("claude")'),
    "scratch": (
        "from tests.runtime_scratch import runtime_scratch\n",
        'runtime_scratch("acp", None, None)',
    ),
    "harness": ("from tests.runtimes.policy_agent_harness import drive\n", 'drive(["agent"])'),
    "command": ("import os\n", 'os.environ.get("ABK_ACCEPTANCE_ACP_COMMAND")'),
}


def module_with(use: str, body: str) -> str:
    return f"{HEADER}{use}{PLAIN}\n\n{body}"


@pytest.mark.parametrize("signal", SIGNALS)
def test_a_test_showing_a_signal_is_named_and_one_that_does_not_is_not(
    pytester: pytest.Pytester, signal: str
) -> None:
    use, call = SIGNALS[signal]

    found = drifted(pytester, test_case=module_with(use, f"def test_starts():\n    {call}\n"))

    assert len(found) == 1
    assert "test_starts" in found[0]


@pytest.mark.parametrize("where", ["in_test", "module_level"])
def test_a_runtime_held_in_a_variable_before_it_is_used_is_found(
    pytester: pytest.Pytester, where: str
) -> None:
    local = "def test_starts():\n    runtime = AcpRuntime()\n    runtime.list_models(['a'])\n"
    shared = "RUNTIME = AcpRuntime()\n\n\ndef test_starts():\n    RUNTIME.detect(None, None)\n"

    found = drifted(
        pytester,
        test_case=module_with(DETECT, local if where == "in_test" else shared),
    )

    assert len(found) == 1
    assert "test_starts" in found[0]


def test_a_signal_in_a_fixture_the_test_requests_is_found(pytester: pytest.Pytester) -> None:
    fixture = "@pytest.fixture\ndef agents():\n    return AcpRuntime().detect(None, None)\n"

    found = drifted(
        pytester,
        test_case=module_with(DETECT, f"{fixture}\n\ndef test_starts(agents):\n    pass\n"),
    )

    assert len(found) == 1
    assert "test_starts" in found[0]


def test_a_signal_in_a_fixture_of_the_modules_conftest_is_found(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(
        f"import pytest\n{DETECT}\n\n@pytest.fixture\ndef agents():\n"
        "    return AcpRuntime().detect(None, None)\n"
    )

    found = drifted(pytester, test_case=module_with("", "def test_starts(agents):\n    pass\n"))

    assert len(found) == 1
    assert "test_starts" in found[0]


def test_a_signal_in_a_called_module_function_is_found_and_one_not_called_is_not(
    pytester: pytest.Pytester,
) -> None:
    helpers = (
        "def installed():\n    return AcpRuntime().detect(None, None)\n\n\n"
        "def unused():\n    return AcpRuntime().detect(None, None)\n"
    )

    found = drifted(
        pytester,
        test_case=module_with(DETECT, f"{helpers}\n\ndef test_starts():\n    installed()\n"),
    )

    assert len(found) == 1
    assert "test_starts" in found[0]


def test_a_stand_in_test_beside_an_agent_starting_test_is_not_named(
    pytester: pytest.Pytester,
) -> None:
    body = (
        "from tests.scripted_abk import install_stand_in\n\n\n"
        "def test_stand_in():\n    install_stand_in(None)\n\n\n"
        "def test_lists_models():\n    AcpRuntime().list_models(['agent'])\n"
    )

    found = drifted(pytester, test_case=module_with(DETECT, body))

    assert len(found) == 1
    assert "test_lists_models" in found[0]


def test_a_fixture_that_cannot_be_resolved_is_not_counted_and_a_note_mentions_it(
    pytester: pytest.Pytester,
) -> None:
    pytester.syspathinsert(ROOT)
    pytester.makepyfile(test_case=module_with("", "def test_mystery(mystery_fixture):\n    pass\n"))
    items, _ = pytester.inline_genitems()

    assert drift(items) == []
    notes = agent_start_notes(items)
    assert len(notes) == 1
    assert "mystery_fixture" in notes[0]
    assert "test_mystery" in notes[0]


def called_names(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = node.func
            names.add(
                function.id if isinstance(function, ast.Name) else getattr(function, "attr", "")
            )
    return names


def agent_calling_helpers() -> dict[str, Path]:
    """The non-test modules under `tests/` that connect to an agent, or start a subprocess in a
    module that reads the agent command: dotted name to path."""
    found = {}
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if path.name.startswith("test_") or path.name == "conftest.py":
            continue
        tree = ast.parse(path.read_text())
        calls = called_names(tree)
        reads_command = any(
            isinstance(n, ast.Name) and n.id == "AGENT_COMMAND" for n in ast.walk(tree)
        )
        spawns = calls & {"create_subprocess_exec", "Popen", "run"}
        if "agent_connection" in calls or (reads_command and spawns):
            dotted = ".".join(path.relative_to(ROOT).with_suffix("").parts)
            found[dotted] = path
    return found


def test_every_helper_module_that_starts_an_agent_is_in_the_table_or_excused_with_a_reason() -> (
    None
):
    helpers = agent_calling_helpers()
    assert helpers
    listed = set(AGENT_SIGNALS.helper_modules)

    unlisted = sorted(set(helpers) - listed - set(AGENT_SIGNALS.excused_helpers))

    assert unlisted == []
    assert [m for m, reason in AGENT_SIGNALS.excused_helpers.items() if not reason.strip()] == []
    assert listed
