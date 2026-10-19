"""A runtime tag agrees with the runtime the test starts."""

from __future__ import annotations

import pytest

from tests.live_tag_drift import drifted

# Each ACP-only scenario states its reason, so only the tag-against-start comparison can name one.
REASONS = 'ACP_ONLY_REASONS = {"test_wrong": "r", "test_adapter": "r", "test_mismatch": "r"}\n'
HEADER = "import pytest\n\npytestmark = pytest.mark.local_stack\n" + REASONS
SCRATCH = "from tests.runtime_scratch import RUNTIME_PARAMS, runtime_scratch\n"
ACP_TAG = "\n\n@pytest.mark.runtime_acp\n"
CLAUDE_TAG = "\n\n@pytest.mark.runtime_claude_code\n"
# A test of the wrong runtime beside the one under test, so the module names exactly one.
MISMATCH = f'{ACP_TAG}def test_mismatch():\n    runtime_scratch("claude_code", None, None)\n'


def module(*parts: str) -> str:
    return HEADER + SCRATCH + "".join(parts)


@pytest.mark.parametrize(
    "body",
    [
        'runtime_scratch("claude_code", None, None)',
        'shutil.which("claude")',
        "claude_account.NAMES",
    ],
    ids=["scratch", "which", "account"],
)
def test_a_test_tagged_acp_that_starts_claude_is_named_with_both_runtimes(
    pytester: pytest.Pytester, body: str
) -> None:
    source = (
        "import shutil\nfrom agent_build_kit import claude_account\n"
        f"{HEADER}{SCRATCH}{ACP_TAG}def test_wrong():\n    {body}\n"
    )

    found = drifted(pytester, test_case=source)

    assert len(found) == 1
    assert "test_wrong" in found[0]
    assert "runtime_acp" in found[0]
    assert "claude_code" in found[0]


def test_a_test_tagged_acp_whose_callspec_holds_claude_code_is_named(
    pytester: pytest.Pytester,
) -> None:
    source = module(
        '\n\n@pytest.mark.parametrize("runtime", [pytest.param("claude_code", '
        "marks=pytest.mark.runtime_acp)])\ndef test_wrong(runtime):\n    pass\n"
    )

    found = drifted(pytester, test_case=source)

    assert len(found) == 1
    assert "test_wrong" in found[0]
    assert "runtime_acp" in found[0]


@pytest.mark.parametrize(
    "body",
    ['runtime_scratch("acp", None, None)', 'os.environ.get("ABK_ACCEPTANCE_ACP_COMMAND")'],
    ids=["scratch", "command"],
)
def test_a_test_tagged_claude_code_that_starts_a_protocol_agent_is_named(
    pytester: pytest.Pytester, body: str
) -> None:
    wrong = f"def test_wrong():\n    {body}\n"
    source = "import os\n" + module(CLAUDE_TAG, wrong)

    found = drifted(pytester, test_case=source)

    assert len(found) == 1
    assert "test_wrong" in found[0]
    assert "runtime_claude_code" in found[0]
    assert "acp" in found[0]


def test_a_test_tagged_acp_that_starts_the_claude_adapter_is_not_named(
    pytester: pytest.Pytester,
) -> None:
    adapter = f'{ACP_TAG}def test_adapter():\n    shutil.which("claude-agent-acp")\n'

    found = drifted(pytester, test_case="import shutil\n" + module(adapter, MISMATCH))

    assert len(found) == 1
    assert "test_mismatch" in found[0]


def test_an_untagged_test_with_a_claude_stub_and_a_correct_parametrisation_are_not_named(
    pytester: pytest.Pytester,
) -> None:
    stub = '\n\ndef test_stub(tmp_path):\n    (tmp_path / "claude").write_text("#!/bin/sh\\n")\n'
    both = (
        '\n\n@pytest.mark.parametrize("runtime", RUNTIME_PARAMS)\n'
        "def test_both(runtime):\n    runtime_scratch(runtime, None, None)\n"
    )

    found = drifted(pytester, test_case=module(stub, both, MISMATCH))

    assert len(found) == 1
    assert "test_mismatch" in found[0]
