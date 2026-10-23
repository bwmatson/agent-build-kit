"""Landing facts the landing tests share: a unit that meets every condition."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import config
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import AutoLandConfig, ReviewConfig
from agent_build_kit.forges.base import Check, CheckStatus, PullRequest
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.landing_decision import LandingFacts
from agent_build_kit.pipeline.landing_intent import LANDING, has_intent
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VERDICTS
from tests.conftest import make_installation
from tests.factories import deep_store
from tests.forges.stand_in import StandInForge
from tests.verdict_fakes import write_verdicts

HEAD = "a" * 40
UNIT = "c/1"
PR = 1


def check(name: str, status: CheckStatus = CheckStatus.PASSED) -> Check:
    return Check(name=name, status=status)


def facts(**changes: Any) -> LandingFacts:
    """A unit that meets every condition; `changes` overrides any fact."""
    base: dict[str, Any] = {
        "review_enabled": True,
        "state": "in_review",
        "verdict_tier": ReviewTier.AUTO,
        "unit_class": "docs",
        "listed_classes": ("docs",),
        "head": HEAD,
        "approved_head": HEAD,
        "checks": (check("build"), check("lint"), check("test")),
    }
    return LandingFacts(**{**base, **changes})


def listed_review(*, enabled: bool = True, listed: tuple[str, ...] = ("docs",)) -> ReviewConfig:
    """A review policy with the class `docs`, of which `listed` are enabled for landing."""
    return ReviewConfig(
        enabled=enabled,
        classes={"docs": ["docs/**"]},
        auto_land=AutoLandConfig(classes=list(listed)),
    )


def apply_review(inst: Installation, review: ReviewConfig) -> None:
    """Make `review` the policy both the installation and the active configuration carry."""
    inst.config = inst.config.model_copy(update={"review": review})
    config.activate(inst.config, config.active_root())


def make_landable(
    inst: Installation, store: UnitStore, forge: StandInForge, units: dict[str, int]
) -> None:
    """Each unit (id to pull request number) is approved at `HEAD` with a final `auto` verdict
    of the class `docs`, and has an open pull request on the forge with passing checks."""
    for unit, pr in units.items():
        store.record_approval(unit, HEAD)
        store.record_push(unit, HEAD)
        forge.prs.append(
            PullRequest(
                number=pr,
                head=f"spec/{unit}",
                base="main",
                state="open",
                checks=(check("build"), check("lint"), check("test")),
            )
        )
    verdicts = inst.state_dir / VERDICTS
    verdicts.parent.mkdir(parents=True, exist_ok=True)
    write_verdicts(verdicts, dict.fromkeys(units, ReviewTier.AUTO), unit_class="docs")


class Landing:
    """A store of units in review, a forge, and the landing pass over them."""

    def __init__(self, tmp_path: Path, patch: pytest.MonkeyPatch, forge: StandInForge) -> None:
        self.inst: Installation = make_installation(tmp_path)
        apply_review(self.inst, listed_review())
        self.inst.state_dir.mkdir(parents=True, exist_ok=True)
        self.store: UnitStore = deep_store(self.inst.state_dir)
        self.forge = forge
        self.restacked: list[tuple[str, str, str]] = []
        self.logged: list[str] = []
        patch.setattr(self.inst, "forge_of", lambda repo: (forge, forge.repo_id()))
        make_landable(self.inst, self.store, forge, {UNIT: PR})
        self.dispatch: Callable[..., bool] = events.build_dispatch(
            self.store,
            restack=lambda **k: self.restacked.append((k["branch"], k["old_base"], k["new_base"])),
            remove_worktree=lambda repo, branch: None,
            delete_branch=lambda repo, branch: None,
            retarget=lambda unit, base: None,
            rebase_cap=2,
            landing_path=self.inst.state_dir / LANDING,
            log=lambda message: None,
        )

    def land(self) -> None:
        cli.land_units(self.inst, self.store, dispatch=self.dispatch, say=self.logged.append)

    def intent(self, pr: int = PR) -> bool:
        return has_intent(self.inst.state_dir / LANDING, repo="app", pr=pr)


def landing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forge: StandInForge | None = None
) -> Landing:
    return Landing(tmp_path, monkeypatch, forge or StandInForge())
