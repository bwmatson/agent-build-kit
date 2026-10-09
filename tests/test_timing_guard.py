"""The guard against timing hazards in the test tree (spec: flaky-tests).

A bare sleep, a thread nothing joins or signals and a fixed port fail the guard in a
file that is neither a shared helper nor on the allowlist; the allowlist may only
shrink, so a file whose uses are gone fails until it is removed from it.
"""

from __future__ import annotations

from pathlib import Path

from tests.timing_hazards import ALLOWLIST, SHARED_HELPERS, TESTS_ROOT, check_tests

NONE: frozenset[str] = frozenset()

SLEEPS = "import time\n\n\ndef test_x():\n    time.sleep(1)\n"


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def test_a_bare_sleep_fails_naming_the_file_and_the_line(tmp_path: Path) -> None:
    root = tree(tmp_path, {"pipeline/test_x.py": SLEEPS})

    problems = check_tests(root, allowlist=NONE, shared=NONE)

    assert len(problems) == 1
    assert "pipeline/test_x.py:5" in problems[0]


def test_an_imported_sleep_is_found_too(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {"test_x.py": "from time import sleep\n\n\ndef test_x():\n    sleep(1)\n"},
    )

    assert any("test_x.py:5" in p for p in check_tests(root, allowlist=NONE, shared=NONE))


def test_a_sleep_in_a_string_or_a_comment_is_not_a_sleep(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {"test_x.py": '# time.sleep(1)\nSCRIPT = "time.sleep(1)"\n\n\ndef test_x():\n    pass\n'},
    )

    assert check_tests(root, allowlist=NONE, shared=NONE) == []


def test_a_thread_nothing_joins_or_signals_fails(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "test_x.py": (
                "import threading\n\n\ndef test_x():\n    threading.Thread(target=print).start()\n"
            )
        },
    )

    problems = check_tests(root, allowlist=NONE, shared=NONE)

    assert len(problems) == 1
    assert "test_x.py:5" in problems[0]


def test_a_thread_that_is_joined_or_signals_an_event_passes(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "test_joined.py": (
                "import threading\n\n\ndef test_x():\n"
                "    worker = threading.Thread(target=print)\n"
                "    worker.start()\n"
                "    worker.join()\n"
            ),
            "test_signalled.py": (
                "import threading\n\n\ndef test_x():\n"
                "    done = threading.Event()\n"
                "    threading.Thread(target=done.set).start()\n"
                "    done.wait(10)\n"
            ),
        },
    )

    assert check_tests(root, allowlist=NONE, shared=NONE) == []


def test_a_fixed_port_fails_and_a_free_one_does_not(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "test_bound.py": (
                "import socket\n\n\ndef test_x():\n    socket.socket().bind(('127.0.0.1', 8080))\n"
            ),
            "test_keyword.py": (
                "import uvicorn\n\n\ndef test_x():\n    uvicorn.run(app, port=9000)\n"
            ),
            "test_free.py": (
                "import socket\n\n\ndef test_x():\n"
                "    socket.socket().bind(('127.0.0.1', 0))\n"
                "    run(port=0)\n"
            ),
        },
    )

    problems = check_tests(root, allowlist=NONE, shared=NONE)

    assert len(problems) == 2
    assert any("test_bound.py:5" in p for p in problems)
    assert any("test_keyword.py:5" in p for p in problems)


def test_a_shared_helper_may_hold_a_hazard(tmp_path: Path) -> None:
    root = tree(tmp_path, {"waiting.py": SLEEPS})

    assert check_tests(root, allowlist=NONE, shared=frozenset({"waiting.py"})) == []


def test_an_allowlisted_file_may_keep_its_hazards(tmp_path: Path) -> None:
    root = tree(tmp_path, {"test_old.py": SLEEPS})

    assert check_tests(root, allowlist=frozenset({"test_old.py"}), shared=NONE) == []


def test_a_file_whose_uses_are_gone_must_leave_the_allowlist(tmp_path: Path) -> None:
    root = tree(tmp_path, {"test_old.py": "def test_x():\n    pass\n"})

    problems = check_tests(root, allowlist=frozenset({"test_old.py"}), shared=NONE)

    assert len(problems) == 1
    assert "test_old.py" in problems[0]
    assert "allowlist" in problems[0].lower()


def test_an_allowlisted_file_that_no_longer_exists_must_leave_the_allowlist(
    tmp_path: Path,
) -> None:
    problems = check_tests(tmp_path, allowlist=frozenset({"gone.py"}), shared=NONE)

    assert len(problems) == 1
    assert "gone.py" in problems[0]


def test_the_suite_has_no_hazard_outside_the_allowlist() -> None:
    assert check_tests(TESTS_ROOT, allowlist=ALLOWLIST, shared=SHARED_HELPERS) == []


def test_a_tuple_argument_to_a_call_that_is_not_an_address_is_not_a_port(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "test_x.py": (
                "def test_x():\n"
                "    for index, name in enumerate((0, 5)):\n"
                "        pass\n"
                "    pairs = []\n"
                "    pairs.append((1, 2))\n"
            )
        },
    )

    assert check_tests(root, allowlist=NONE, shared=NONE) == []


def test_a_fixed_port_in_other_address_calls_is_found(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "test_x.py": (
                "import socket\n\n\ndef test_x():\n"
                "    socket.create_connection(('localhost', 8080))\n"
            )
        },
    )

    assert any("test_x.py:5" in p for p in check_tests(root, allowlist=NONE, shared=NONE))


def test_a_class_of_the_files_own_called_thread_is_not_a_thread(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {"test_x.py": ("class Thread:\n    pass\n\n\ndef test_x():\n    return Thread()\n")},
    )

    assert check_tests(root, allowlist=NONE, shared=NONE) == []


def test_a_thread_imported_from_threading_is_a_thread(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "test_x.py": (
                "from threading import Thread\n\n\ndef test_x():\n"
                "    Thread(target=print).start()\n"
            )
        },
    )

    assert any("test_x.py:5" in p for p in check_tests(root, allowlist=NONE, shared=NONE))


def test_a_string_join_does_not_join_a_thread(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "test_x.py": (
                "import threading\n\n\ndef test_x():\n"
                "    threading.Thread(target=print).start()\n"
                "    assert ', '.join(['a']) == 'a'\n"
                "    assert ''.join(['a']) == 'a'\n"
                "    separator = ','\n"
                "    assert separator.join(['a']) == 'a'\n"
            )
        },
    )

    problems = check_tests(root, allowlist=NONE, shared=NONE)

    assert len(problems) == 1
    assert "test_x.py:5" in problems[0]


def test_a_thread_joined_with_a_timeout_is_joined(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "test_x.py": (
                "import threading\n\n\ndef test_x():\n"
                "    worker = threading.Thread(target=print)\n"
                "    worker.start()\n"
                "    worker.join(5)\n"
            ),
            "test_y.py": (
                "import threading\n\n\ndef test_x():\n"
                "    worker = threading.Thread(target=print)\n"
                "    worker.start()\n"
                "    worker.join(timeout=5)\n"
            ),
        },
    )

    assert check_tests(root, allowlist=NONE, shared=NONE) == []


# The allowlist only shrinks. Adding a file to it means editing this set, which is the
# sign that a new hazard is being silenced instead of removed.
ALLOWLIST_CEILING = frozenset(
    {
        "cli/test_gated_started_units.py",
        "cli/test_round.py",
        "cli/test_tick_host_outage_backoff.py",
        "cli/test_tick_scheduling.py",
        "graph/test_thread_resume.py",
        "integration/test_telemetry_stack.py",
        "pipeline/test_scratch_folder.py",
        "pipeline/test_tier2.py",
        "runtimes/test_acp_outcome.py",
        "serve/test_chat_guards.py",
        "serve/test_serve_binding.py",
        "serve/test_serve_metrics.py",
        "test_telemetry.py",
    }
)


def test_the_allowlist_does_not_grow() -> None:
    assert ALLOWLIST <= ALLOWLIST_CEILING
