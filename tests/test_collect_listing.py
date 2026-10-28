"""A listing of what a few paths collect, read in a child pytest that skips the whole suite."""

from __future__ import annotations

from tests.child_pytest import collect_listing

FOLDER = "tests/child_modules"
SIBLING = "tests/test_child_modules_not_collected.py"


def test_a_listing_of_the_folder_and_a_sibling_names_the_sibling_and_nothing_of_the_folder() -> (
    None
):
    run = collect_listing(FOLDER, SIBLING)

    assert run.code == 0, run.output
    assert f"{SIBLING}::test_no_file_of_the_folder_is_named_like_a_test" in run.output
    assert [line for line in run.output.splitlines() if "child_modules/" in line] == []


def test_a_listing_names_only_the_paths_it_was_given() -> None:
    run = collect_listing(SIBLING)

    listed = [line for line in run.output.splitlines() if "::" in line]
    assert listed
    assert all(line.startswith(f"{SIBLING}::") for line in listed), run.output
