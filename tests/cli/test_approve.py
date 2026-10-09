"""`abk approve <unit>`: record the person's approval of the unit's current review
round at the head its pull request has, and do nothing else (spec: web-ui, Approve
records the person's approval and does nothing else)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent_build_kit.cli import main
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.serve.review import ReviewStore
from agent_build_kit.serve.server import start_server
from tests.conftest import make_installation
from tests.review_approval import (
    give_a_remote,
    refs,
    stored_decisions,
    watch_the_host,
    without_a_branch,
    write_an_old_decision,
)
from tests.review_repo import rev, seed_branches
from tests.serving import seed_pipeline, seed_review_round


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    installation = make_installation(tmp_path / "planning")
    (installation.root / "abk.yaml").write_text(dump(installation.config))
    monkeypatch.chdir(installation.root)
    seed_pipeline(installation)
    return installation


def test_approve_records_an_approved_decision_for_the_round_at_the_head(
    inst: Installation,
) -> None:
    repo = seed_branches(inst)
    seed_review_round(inst, "feature/2", 2)

    assert main(["approve", "feature/2"]) == 0

    [decision] = stored_decisions(inst, "feature/2")
    assert (decision["round"], decision["decision"]) == (2, "approve")
    assert decision["head"] == rev(repo, "spec/feature/2")


def test_it_prints_the_unit_the_head_and_the_round(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = seed_branches(inst)
    seed_review_round(inst, "feature/2", 2)

    main(["approve", "feature/2"])

    out = capsys.readouterr().out
    assert "feature/2" in out
    assert rev(repo, "spec/feature/2") in out
    assert "round 2" in out


def test_the_ui_and_the_command_record_the_same_thing(inst: Installation) -> None:
    repo = seed_branches(inst)

    with start_server(inst) as server, httpx.Client(base_url=server.url) as client:
        assert client.post("/api/units/feature/2/actions/approve", json={}).status_code == 200
    assert main(["approve", "feature/4"]) == 0

    [via_ui] = stored_decisions(inst, "feature/2")
    [via_cli] = stored_decisions(inst, "feature/4")
    shape = ("round", "decision", "summary")
    assert {k: via_ui[k] for k in shape} == {k: via_cli[k] for k in shape}
    assert via_ui["head"] == rev(repo, "spec/feature/2")
    assert via_cli["head"] == rev(repo, "spec/feature/4")


def test_approve_merges_nothing_pushes_nothing_and_calls_no_vote_on_the_host(
    inst: Installation,
) -> None:
    repo = seed_branches(inst)
    remote = give_a_remote(repo)
    host = watch_the_host()
    branches = rev(repo, "spec/feature/2"), rev(repo, "main")

    assert main(["approve", "feature/2"]) == 0

    assert host.requests == []
    assert refs(remote) == ""
    assert (rev(repo, "spec/feature/2"), rev(repo, "main")) == branches


def test_a_unit_with_no_pull_request_is_refused_with_a_reason(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_branches(inst)

    assert main(["approve", "feature/6"]) == 1

    assert "no pull request" in capsys.readouterr().out
    assert stored_decisions(inst, "feature/6") == []


def test_a_unit_with_no_head_is_refused_with_a_reason(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    without_a_branch(inst)

    assert main(["approve", "feature/2"]) == 1

    assert "head" in capsys.readouterr().out
    assert stored_decisions(inst, "feature/2") == []


def test_a_round_that_already_has_a_decision_is_refused_with_a_reason(
    inst: Installation, capsys: pytest.CaptureFixture[str]
) -> None:
    seed_branches(inst)
    ReviewStore(inst.state_dir / "reviews").decide(
        "feature/2", round=1, decision="request_changes", summary="Needs a test"
    )
    before = stored_decisions(inst, "feature/2")

    assert main(["approve", "feature/2"]) == 1

    assert "round 1" in capsys.readouterr().out
    assert stored_decisions(inst, "feature/2") == before


def test_an_unknown_unit_fails(inst: Installation, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["approve", "feature/99"]) == 1

    assert "feature/99" in capsys.readouterr().out


def test_a_decision_recorded_before_heads_is_still_read_and_still_blocks_its_round(
    inst: Installation,
) -> None:
    seed_branches(inst)
    write_an_old_decision(inst, "feature/2", 1)

    assert main(["approve", "feature/2"]) == 1

    [old] = stored_decisions(inst, "feature/2")
    assert old["decision"] == "request_changes"
