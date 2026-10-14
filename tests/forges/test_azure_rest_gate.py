"""The fake Azure host holds a request at a gate a test releases, instead of a sleep."""

from __future__ import annotations

import threading

import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import RepoId
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost
from tests.waiting import wait_for

pytestmark = pytest.mark.usefixtures("rest_env")

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")


def test_a_request_waits_at_the_gate_until_the_test_releases_it() -> None:
    gate = threading.Event()
    host = RestHost(azure_answers.OPEN, gate=gate)
    worker = threading.Thread(target=lambda: AzureDevOpsForge(http=host).list_prs(REPO))

    worker.start()
    try:
        wait_for(lambda: host.peak >= 1, what="a request to reach the host")
        answered_while_held = list(host.seen)
    finally:
        gate.set()
    worker.join(timeout=10)

    assert answered_while_held == []
    assert not worker.is_alive()
    assert host.seen
