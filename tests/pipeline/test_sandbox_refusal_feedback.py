"""A unit-test run the sandbox refused a loopback connection or a service socket carries
feedback saying a step that needs a running service is an e2e test (spec: sandbox-e2e-policy).

The failed run is faked at the point the runner binds unit-test, with the output the
interpreter prints; the feedback is what the unit stores for its agent.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.stack_runner import UNIT_TEST_FAILED
from tests.graph_driver import fresh, tick
from tests.runner_fakes import rejecting

UNIT = "add-marker/1"
LOOPBACK = """\
tests/test_client.py:12: in test_fetch
    sock.connect(("127.0.0.1", 8080))
E   PermissionError: [Errno 13] Permission denied
FAILED tests/test_client.py::test_fetch - PermissionError: [Errno 13] Permission denied
"""
LOCALHOST = """\
tests/test_client.py:12: in test_fetch
    requests.get("http://localhost:5432/health")
E   PermissionError: [Errno 13] Permission denied
"""
DOCKER_ERROR = (
    "docker.errors.DockerException: Error while fetching server API version: "
    "('Connection aborted.', PermissionError(13, 'Permission denied'))"
)
SOCKET = f"""\
tests/test_images.py:9: in test_build
    client = docker.from_env()
E   {DOCKER_ERROR}
FAILED tests/test_images.py::test_build - {DOCKER_ERROR}
"""
NODE = """\
Error: connect EACCES 127.0.0.1:8080
    at TCPConnectWrap.afterConnect [as oncomplete] (node:net:1555:16)
"""
NODE_REFUSED = """\
Error: connect ECONNREFUSED ::1:5432
    at TCPConnectWrap.afterConnect [as oncomplete] (node:net:1555:16)
"""
UNRELATED_LINES = "".join(f"    frame {n}\n" for n in range(6))
FILE_WRITE_AND_LOCALHOST = (
    "E   PermissionError: [Errno 13] Permission denied: '/etc/app.conf'\n"
    + UNRELATED_LINES
    + "E   assert url == 'http://localhost/a'\n"
)
NON_LOOPBACK_V6 = """\
Error: connect EACCES fe80::1:8080
    at TCPConnectWrap.afterConnect [as oncomplete] (node:net:1555:16)
"""
ORDINARY_HOST = """\
tests/test_client.py:12: in test_fetch
    requests.get("https://registry.example.test/pkg")
E   PermissionError: [Errno 13] Permission denied: registry.example.test:443
"""
ASSERTION = "FAILED tests/test_widget.py::test_label - assert 'a' == 'b'\n"


def feedback_after(tmp_path: Path, output: str) -> str:
    recorder = fresh(tmp_path)
    recorder.unit_test_ok = False
    recorder.unit_test_output = output
    tick(tmp_path, recorder)
    return recorder.store.get(UNIT).feedback


@pytest.mark.parametrize(
    "output",
    [LOOPBACK, LOCALHOST, SOCKET, NODE, NODE_REFUSED],
    ids=["ip", "name", "socket", "node", "node-refused"],
)
def test_a_refused_loopback_or_service_socket_says_the_step_is_an_e2e_test(
    tmp_path: Path, output: str
) -> None:
    feedback = feedback_after(tmp_path, output)

    assert feedback.startswith(UNIT_TEST_FAILED)
    assert output.strip() in feedback, "the run's own output is kept"
    assert "needs a running service is an e2e test" in feedback
    assert "[e2e-test]" in feedback


@pytest.mark.parametrize(
    "other",
    [ORDINARY_HOST, ASSERTION, FILE_WRITE_AND_LOCALHOST, NON_LOOPBACK_V6],
    ids=["host", "assertion", "file-write", "non-loopback-v6"],
)
def test_the_hint_is_for_a_loopback_refusal_and_not_for_other_failures(
    tmp_path: Path, other: str
) -> None:
    refused = feedback_after(tmp_path / "refused", LOOPBACK)
    feedback = feedback_after(tmp_path / "other", other)

    assert "[e2e-test]" in refused
    assert other.strip() in feedback
    assert "e2e" not in feedback


def test_checks_refused_a_loopback_connection_before_review_carry_the_hint(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.verdicts = [rejecting("rename it")]
    recorder.unit_test_results = [(True, ""), (False, LOOPBACK), (True, "")]

    tick(tmp_path, recorder)

    fix = [p for p in recorder.prompts if "checks (lint" in p]
    assert len(fix) == 1
    assert LOOPBACK.strip() in fix[0]
    assert "needs a running service is an e2e test" in fix[0]
