"""The guard over agent calls (spec: usage-accounting, every agent call is recorded).

A request built with neither callback, or with only `on_record`, fails the guard in a file that
is not on the allowlist; the allowlist may only shrink, so an entry whose site now records, or
is gone, fails until it is removed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.agent_call_sites import ALLOWLIST, SRC_ROOT, check_sources
from tests.time_limit import LOADED_TEST_TIME_LIMIT

NONE: dict[tuple[str, str], str] = {}

HEAD = "from agent_build_kit.runtimes import AgentRequest\n\n\n"
UNRECORDED = HEAD + "def ask(runtime):\n    return runtime.run(AgentRequest(prompt='x'))\n"
TRANSCRIPT_ONLY = (
    HEAD + "def ask(runtime):\n    return runtime.run(AgentRequest(prompt='x', on_record=tell))\n"
)
ON_RESULT = (
    HEAD + "def ask(runtime):\n    return runtime.run(AgentRequest(prompt='x', on_result=done))\n"
)
HELPER = (
    "from agent_build_kit.pipeline.call_record import recorded\n" + HEAD + "def ask(runtime):\n"
    "    return runtime.run(recorded(AgentRequest(prompt='x'), runtime, node='plan', say=print))\n"
)


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def test_a_request_with_neither_callback_fails_naming_its_file_and_line(tmp_path: Path) -> None:
    root = tree(tmp_path, {"pipeline/ask.py": UNRECORDED})

    problems = check_sources(root, allowlist=NONE)

    assert problems
    assert all("pipeline/ask.py:5" in p for p in problems)


def test_a_request_that_sets_only_on_record_fails(tmp_path: Path) -> None:
    root = tree(tmp_path, {"serve/chat.py": TRANSCRIPT_ONLY})

    assert any("serve/chat.py:5" in p for p in check_sources(root, allowlist=NONE))


def test_a_request_built_through_the_helper_or_setting_on_result_passes(tmp_path: Path) -> None:
    root = tree(tmp_path, {"a.py": HELPER, "b.py": ON_RESULT})

    assert check_sources(root, allowlist=NONE) == []


def test_only_the_request_handed_to_the_helper_by_name_is_recorded(tmp_path: Path) -> None:
    two = (
        "from agent_build_kit.pipeline.call_record import recorded\n" + HEAD + "def ask(runtime):\n"
        "    first = AgentRequest(prompt='x')\n"
        "    second = AgentRequest(prompt='y')\n"
        "    runtime.run(recorded(first, runtime, node='plan', say=print))\n"
        "    return runtime.run(second)\n"
    )
    root = tree(tmp_path, {"pipeline/ask.py": two})

    problems = check_sources(root, allowlist=NONE)

    assert len(problems) == 1
    assert "pipeline/ask.py:7" in problems[0]


def test_an_allowlisted_site_passes(tmp_path: Path) -> None:
    root = tree(tmp_path, {"pipeline/ask.py": UNRECORDED})

    allowed = {("pipeline/ask.py", "ask"): "converted by group 2 of this change"}

    assert check_sources(root, allowlist=allowed) == []


def test_an_entry_whose_site_now_records_must_leave_the_allowlist(tmp_path: Path) -> None:
    root = tree(tmp_path, {"pipeline/ask.py": ON_RESULT})

    problems = check_sources(root, allowlist={("pipeline/ask.py", "ask"): "a reason"})

    assert len(problems) == 1
    assert "pipeline/ask.py" in problems[0]
    assert "allowlist" in problems[0].lower()


def test_an_entry_whose_site_is_gone_must_leave_the_allowlist(tmp_path: Path) -> None:
    root = tree(tmp_path, {"pipeline/ask.py": "def other():\n    pass\n"})

    problems = check_sources(root, allowlist={("pipeline/ask.py", "ask"): "a reason"})

    assert len(problems) == 1
    assert "allowlist" in problems[0].lower()


def test_a_run_that_is_not_a_runtimes_is_left_alone(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "other.py": (
                "import asyncio\nimport subprocess\n\n\n"
                "def go(main):\n"
                "    subprocess.run(['git', 'status'])\n"
                "    asyncio.run(main())\n"
            )
        },
    )

    assert check_sources(root, allowlist=NONE) == []


def test_claude_run_through_subprocess_with_a_prompt_flag_fails(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "usage.py": (
                "import subprocess\n\n\n"
                "def warm():\n"
                "    subprocess.run(['claude', '-p', 'Reply with OK'])\n"
            )
        },
    )

    assert any("usage.py:5" in p for p in check_sources(root, allowlist=NONE))


def test_a_node_name_outside_the_overhead_nodes_fails(tmp_path: Path) -> None:
    typo = HELPER.replace("node='plan'", "node='plna'")
    root = tree(tmp_path, {"pipeline/ask.py": typo})

    problems = check_sources(root, allowlist=NONE)

    assert problems
    assert any("plna" in p for p in problems)


# --- the real source tree ------------------------------------------------------------------


def test_the_allowlist_is_empty() -> None:
    assert ALLOWLIST == {}


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
def test_every_agent_call_in_the_source_records_or_is_on_the_allowlist() -> None:
    assert check_sources(SRC_ROOT, allowlist=ALLOWLIST) == []
