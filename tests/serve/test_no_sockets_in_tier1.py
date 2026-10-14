"""The guard keeps tier 1 under `tests/serve` free of sockets (spec: chat-tests)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.serve_sockets import SERVE_TESTS, check_serve_tests


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
        "import http.server\n\nSERVER = http.server.ThreadingHTTPServer\n",
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


def test_the_chat_sessions_module_and_the_fixtures_it_draws_on_open_no_socket() -> None:
    # The module takes its `api` from the folder's conftest: both are in the guard's reach.
    assert check_serve_tests(SERVE_TESTS, only={"conftest.py", "test_chat_sessions.py"}) == []
