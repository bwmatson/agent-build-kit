"""The guard keeps tier 1 under `tests/serve` free of sockets (spec: chat-tests)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.serve_sockets import ALLOWLIST, SERVE_TESTS, check_serve_tests


def tree(root: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


@pytest.mark.parametrize(
    "source",
    [
        "import uvicorn\n",
        "import socket\n",
        "from socket import socket\n",
        "import http.client\n",
        "from http.client import HTTPConnection\n",
        "from http.server import ThreadingHTTPServer\n",
        "SERVER = http.server.ThreadingHTTPServer\n",
        "from agent_build_kit.serve.server import start_server\n\nstart_server(None)\n",
    ],
)
def test_a_socket_in_a_tier_1_module_is_reported_with_file_and_line(
    tmp_path: Path, source: str
) -> None:
    root = tree(tmp_path, {"test_x.py": "x = 1\n" + source})

    problems = check_serve_tests(root)

    assert len(problems) >= 1
    assert all("test_x.py:" in p for p in problems)
    assert "test_x.py:2" in problems[0]


def test_a_client_of_a_real_base_url_is_reported(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {"test_x.py": "import httpx\n\nCLIENT = httpx.Client(base_url='http://127.0.0.1:9')\n"},
    )

    problems = check_serve_tests(root)

    assert len(problems) == 1
    assert "test_x.py:3" in problems[0]


def test_a_client_of_the_testserver_base_url_passes(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {"test_x.py": "import httpx\n\nCLIENT = httpx.Client(base_url='http://testserver')\n"},
    )

    assert check_serve_tests(root) == []


def test_the_same_import_in_an_integration_module_is_not_reported(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "test_smoke.py": (
                "import pytest\nimport uvicorn\n\npytestmark = pytest.mark.integration\n"
            ),
            "test_listed.py": (
                "import pytest\nimport socket\n\n"
                "pytestmark = [pytest.mark.serial, pytest.mark.integration]\n"
            ),
        },
    )

    assert check_serve_tests(root) == []


def test_a_serial_module_is_scanned_like_an_unmarked_one(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {"test_x.py": "import pytest\nimport uvicorn\n\npytestmark = pytest.mark.serial\n"},
    )

    assert len(check_serve_tests(root)) == 1


def test_a_name_in_a_string_or_a_comment_is_not_a_socket(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {"test_x.py": '# import socket\nSCRIPT = "import uvicorn"\n"""http.client"""\n'},
    )

    assert check_serve_tests(root) == []


def test_only_the_listed_files_are_scanned(tmp_path: Path) -> None:
    root = tree(tmp_path, {"test_a.py": "import socket\n", "test_b.py": "import uvicorn\n"})

    problems = check_serve_tests(root, only={"test_b.py"})

    assert len(problems) == 1
    assert "test_b.py:1" in problems[0]


def test_an_annotated_integration_mark_is_seen(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "test_x.py": (
                "import pytest\nimport uvicorn\n\n"
                "pytestmark: list[pytest.MarkDecorator] = [pytest.mark.integration]\n"
            )
        },
    )

    assert check_serve_tests(root) == []


def test_a_client_imported_by_its_bare_name_is_checked_too(tmp_path: Path) -> None:
    root = tree(
        tmp_path,
        {
            "test_real.py": (
                "from httpx import Client\n\nCLIENT = Client(base_url='http://127.0.0.1:9')\n"
            ),
            "test_aliased.py": (
                "from httpx import Client as Http\n\nCLIENT = Http(base_url='http://127.0.0.1:9')\n"
            ),
            "test_local.py": (
                "from httpx import Client\n\nCLIENT = Client(base_url='http://testserver')\n"
            ),
        },
    )

    problems = check_serve_tests(root)

    assert len(problems) == 2
    assert any("test_real.py:3" in p for p in problems)
    assert any("test_aliased.py:3" in p for p in problems)


def test_an_allowlisted_module_may_keep_its_sockets(tmp_path: Path) -> None:
    root = tree(tmp_path, {"test_x.py": "import socket\n"})

    assert check_serve_tests(root, allowlist={"test_x.py"}) == []


def test_an_allowlisted_module_with_no_socket_left_is_reported_as_stale(tmp_path: Path) -> None:
    root = tree(tmp_path, {"test_x.py": "x = 1\n"})

    problems = check_serve_tests(root, allowlist={"test_x.py"})

    assert len(problems) == 1
    assert "test_x.py" in problems[0]
    assert "allowlist" in problems[0]


def test_the_conftest_is_scanned_like_a_test_module(tmp_path: Path) -> None:
    root = tree(tmp_path, {"conftest.py": "from x import start_server\n"})

    assert any("conftest.py:1" in p for p in check_serve_tests(root))


# The allowlist only shrinks. Adding a module to it means editing this set, which is the
# sign that a socket is being silenced instead of removed.
ALLOWLIST_CEILING = frozenset(
    {
        "test_chat_agent_environment.py",
        "test_chat_commit.py",
        "test_chat_editing.py",
        "test_chat_guards.py",
        "test_chat_permissions.py",
        "test_chat_turns.py",
        "test_serve_approve.py",
        "test_serve_binding.py",
        "test_serve_metrics.py",
        "test_serve_review_store.py",
        "socket_api.py",
    }
)


def test_the_allowlist_does_not_grow() -> None:
    assert ALLOWLIST <= ALLOWLIST_CEILING


def test_every_tier_1_module_under_tests_serve_opens_no_socket_but_the_allowlisted() -> None:
    # `conftest.py` is scanned too: the `api` fixture every module draws on stays in-process.
    assert check_serve_tests(SERVE_TESTS, allowlist=ALLOWLIST) == []


def test_the_chat_sessions_module_and_the_conftest_are_clean_with_no_allowlist() -> None:
    assert check_serve_tests(SERVE_TESTS, only={"conftest.py", "test_chat_sessions.py"}) == []
