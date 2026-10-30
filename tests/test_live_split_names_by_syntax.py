"""The splits of the kit's live tests are read from their syntax, so the check that every one is
in a derived split imports nothing and takes the same time however loaded the machine is."""

from __future__ import annotations

from pathlib import Path

from tests.live_tag_drift import splits_by_syntax

IMPORT_FAILS = "raise RuntimeError('imported')\n"
OTHER_ATTRIBUTES = (
    "def test_x(installation):\n"
    "    installation.runtime_entry()\n"
    "    x = installation.runtime_name\n"
)


def write(tests_root: Path, name: str, body: str) -> Path:
    path = tests_root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(IMPORT_FAILS + body)
    return path


def test_a_module_marked_with_a_runtime_tag_is_in_that_split_without_being_imported(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    path = write(
        tests,
        "integration/test_a.py",
        "import pytest\n\npytestmark = [pytest.mark.local_stack, pytest.mark.runtime_acp]\n",
    )

    assert splits_by_syntax(tests) == {path: {"acp"}}


def test_a_decorated_test_and_a_parameter_mark_name_their_splits(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    path = write(
        tests,
        "test_b.py",
        "import pytest\n\n\n"
        "@pytest.mark.local_stack\n@pytest.mark.runtime_claude_code\ndef test_x():\n    pass\n\n\n"
        "@pytest.mark.parametrize('v', [pytest.param(1, marks=pytest.mark.runtime_acp)])\n"
        "@pytest.mark.local_stack\ndef test_y(v):\n    pass\n",
    )

    assert splits_by_syntax(tests) == {path: {"acp", "claude_code"}}


def test_a_live_module_naming_no_runtime_tag_is_in_the_rest_split(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    path = write(tests, "test_c.py", "import pytest\n\npytestmark = pytest.mark.local_stack\n")
    write(tests, "test_plain.py", "def test_x():\n    pass\n")

    assert splits_by_syntax(tests) == {path: {"rest"}}


def test_an_attribute_that_starts_with_runtime_but_is_not_a_mark_names_no_split(
    tmp_path: Path,
) -> None:
    tests = tmp_path / "tests"
    path = write(
        tests,
        "test_d.py",
        "import pytest\nfrom pytest import mark\n\npytestmark = pytest.mark.local_stack\n\n\n"
        + OTHER_ATTRIBUTES
        + "\n\n@mark.runtime_acp\ndef test_y():\n    pass\n",
    )
    other = write(
        tests,
        "test_e.py",
        "import pytest\n\npytestmark = pytest.mark.local_stack\n\n\n" + OTHER_ATTRIBUTES,
    )

    assert splits_by_syntax(tests) == {path: {"acp"}, other: {"rest"}}
