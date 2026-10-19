"""Claude scenarios with no ACP sibling are listed and compared with the document, never refused."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from tests.live_tag_drift import (
    claude_without_acp,
    documented_gaps,
    find_live_modules,
    warn_gap_list_drift,
)
from tests.runtime_tag_collection import ROOT

DOCUMENT = ROOT / "docs" / "agent-runtimes.md"
HEADER = "import pytest\n\npytestmark = pytest.mark.local_stack\n"
CLAUDE_ONLY = f"{HEADER}\n\n@pytest.mark.runtime_claude_code\ndef test_builds_a_unit():\n    pass\n"
ACP_ONLY = f"{HEADER}\n\n@pytest.mark.runtime_acp\ndef test_lists_sessions():\n    pass\n"
BOTH_RUNTIMES = f"""{HEADER}
from tests.runtime_scratch import RUNTIME_PARAMS


@pytest.mark.parametrize("runtime", RUNTIME_PARAMS)
def test_runs_a_unit(runtime):
    pass
"""
CLAUDE_PARAMS = BOTH_RUNTIMES.replace("RUNTIME_PARAMS", "CLAUDE_CODE_PARAMS")
EXCUSED = CLAUDE_ONLY + '\nCLAUDE_ONLY_REASONS = {"test_builds_a_unit": "only claude has hooks"}\n'


def gaps(pytester: pytest.Pytester, **modules: str) -> list[str]:
    pytester.syspathinsert(ROOT)
    pytester.makepyfile(**modules)
    items, _ = pytester.inline_genitems()
    return claude_without_acp(items)


def document_listing(tmp_path: Path, *entries: str) -> Path:
    path = tmp_path / "runtimes.md"
    bullets = "".join(f"- `{e}`\n" for e in entries)
    path.write_text(
        "# Runtimes\n\n### Claude scenarios without an ACP sibling\n\n"
        f"{bullets}\n### Another section\n\n- `not_a.py::gap`\n"
    )
    return path


def warned(pytester: pytest.Pytester, document: Path, **modules: str) -> list[str]:
    pytester.syspathinsert(ROOT)
    pytester.makepyfile(**modules)
    items, _ = pytester.inline_genitems()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warn_gap_list_drift(items, document)
    assert all(issubclass(w.category, UserWarning) for w in caught)
    return [str(w.message) for w in caught]


def test_a_claude_scenario_with_no_acp_sibling_is_listed(pytester: pytest.Pytester) -> None:
    found = gaps(pytester, test_claude_only=CLAUDE_ONLY)

    assert found == ["test_claude_only.py::test_builds_a_unit"]


def test_a_scenario_with_both_runtimes_is_not_listed(pytester: pytest.Pytester) -> None:
    assert gaps(pytester, test_both=BOTH_RUNTIMES) == []


def test_an_acp_only_scenario_is_not_listed(pytester: pytest.Pytester) -> None:
    assert gaps(pytester, test_acp_only=ACP_ONLY) == []


def test_a_parametrised_claude_only_scenario_is_listed_once(pytester: pytest.Pytester) -> None:
    found = gaps(pytester, test_claude_param=CLAUDE_PARAMS)

    assert found == ["test_claude_param.py::test_runs_a_unit"]


def test_a_scenario_with_a_claude_only_reason_is_not_listed(pytester: pytest.Pytester) -> None:
    assert gaps(pytester, test_excused=EXCUSED) == []


def test_the_list_is_sorted(pytester: pytest.Pytester) -> None:
    found = gaps(pytester, test_b=CLAUDE_ONLY, test_a=CLAUDE_ONLY)

    assert found == ["test_a.py::test_builds_a_unit", "test_b.py::test_builds_a_unit"]


def test_the_documents_list_is_read_from_its_heading_only(tmp_path: Path) -> None:
    document = document_listing(tmp_path, "test_a.py::test_x", "test_b.py::test_y")

    assert documented_gaps(document) == ["test_a.py::test_x", "test_b.py::test_y"]


def test_a_gap_missing_from_the_document_warns_naming_it(
    pytester: pytest.Pytester, tmp_path: Path
) -> None:
    messages = warned(pytester, document_listing(tmp_path), test_new=CLAUDE_ONLY)

    assert len(messages) == 1
    assert "test_new.py::test_builds_a_unit" in messages[0]


def test_a_document_entry_that_is_no_longer_a_gap_warns_naming_it(
    pytester: pytest.Pytester, tmp_path: Path
) -> None:
    document = document_listing(tmp_path, "test_old.py::test_runs_a_unit")
    messages = warned(pytester, document, test_old=BOTH_RUNTIMES)

    assert len(messages) == 1
    assert "test_old.py::test_runs_a_unit" in messages[0]


def test_a_list_that_matches_the_document_warns_of_nothing(
    pytester: pytest.Pytester, tmp_path: Path
) -> None:
    document = document_listing(tmp_path, "test_same.py::test_builds_a_unit")

    assert warned(pytester, document, test_same=CLAUDE_ONLY) == []


def test_the_kits_current_list_equals_the_documents(pytester: pytest.Pytester) -> None:
    modules = find_live_modules(ROOT / "tests")
    items, _ = pytester.inline_genitems(*(str(m) for m in modules))

    current = claude_without_acp(items)

    assert current == sorted(current)
    assert {entry.split("::")[0] for entry in current} >= {
        "test_build_unit.py",
        "test_graph_unit.py",
        "test_telemetry_stack.py",
    }
    assert documented_gaps(DOCUMENT) == current
