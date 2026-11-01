"""No two test files define the same constant session id: a test names a session by an id
made for it (the `new_session_id` fixture), so no two tests running at once in any worker
start processes carrying the same one."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from tests.session_id_constants import duplicated_session_ids
from tests.time_limit import LOADED_TEST_TIME_LIMIT

TESTS = Path(__file__).resolve().parent


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
def test_no_session_id_is_defined_in_two_test_files() -> None:
    shared = duplicated_session_ids(TESTS)

    assert not shared, "\n".join(
        f"{session_id} is defined in {', '.join(str(p.relative_to(TESTS)) for p in files)}"
        for session_id, files in shared.items()
    )


def test_a_repeat_in_one_file_is_allowed_and_two_files_are_named(tmp_path: Path) -> None:
    shared, alone = str(uuid.uuid4()), str(uuid.uuid4())
    (tmp_path / "sub").mkdir()
    first, second, third = tmp_path / "a.py", tmp_path / "sub" / "b.py", tmp_path / "c.py"
    first.write_text(f'ID = "{shared}"\nOTHER = "{alone}"\nAGAIN = "{alone}"\n')
    second.write_text(f'ID = "{shared}"\n')
    third.write_text('NOT_AN_ID = "0b7e1d52-9c3a"\n')

    assert duplicated_session_ids(tmp_path) == {shared: [first, second]}


def test_an_acp_shaped_id_in_two_files_is_named(tmp_path: Path) -> None:
    first, second = tmp_path / "a.py", tmp_path / "b.py"
    first.write_text('EARLIER = "sess_Ab3Cd4"\n')
    second.write_text('sessions = ("sess_Ab3Cd4",)\n')

    assert duplicated_session_ids(tmp_path) == {"sess_Ab3Cd4": [first, second]}
