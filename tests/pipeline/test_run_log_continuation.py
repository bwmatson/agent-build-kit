"""A reply of several lines in a unit's log: the first line carries the stamp,
each further line is indented, so the file stays parsable by line."""

from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.pipeline.run_log import RunLog, run_log_dir
from tests.factories import unit

START = datetime(2026, 9, 23, 22, 44, 5, tzinfo=UTC)


def start_run(directory: Path) -> RunLog:
    return RunLog(
        directory,
        unit("add-marker/1", change="add-marker"),
        step="implement",
        model="model-x",
        base="main",
        started=START,
    )


def body_of(directory: Path, run: RunLog) -> list[str]:
    text = (directory / run.name).read_text()
    return text.split("\n\n", 1)[1].splitlines()


def indent_of(line: str) -> str:
    return line[: len(line) - len(line.lstrip())]


def test_a_multi_line_message_is_written_with_indented_continuation_lines(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    run = start_run(directory)

    run.emit("[22:44:10]   says: first paragraph\n\nsecond paragraph\n  nested")
    run.emit("[22:44:12] next line")

    first, blank, second, nested, following = body_of(directory, run)
    assert first == "[22:44:10]   says: first paragraph"
    assert blank.startswith(" ") and not blank.strip(), "a blank line of the reply stays in it"
    assert second.strip() == "second paragraph" and indent_of(second)
    assert nested.strip() == "nested"
    assert indent_of(nested) == indent_of(second) + "  ", "a line's own indent is kept"
    assert following == "[22:44:12] next line"


def test_a_one_line_message_is_written_as_it_always_was(tmp_path: Path) -> None:
    directory = run_log_dir(tmp_path)
    run = start_run(directory)

    run.emit("[22:44:10] opened #1")
    run.close("opened #1")

    assert body_of(directory, run) == ["[22:44:10] opened #1", "", "outcome: opened #1"]
