"""The landing pass: the pipeline merges a unit the landing decision allows and records it."""

from __future__ import annotations

from collections.abc import Callable

from agent_build_kit import config
from agent_build_kit.forges.base import MergeRefused, PullRequest
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import landing_intent
from agent_build_kit.pipeline.landing_decision import LandingFacts, decide_landing
from agent_build_kit.pipeline.ui_review import ui_listing
from agent_build_kit.pipeline.unit_store import HeldBy, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, parent_landed
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VERDICTS, latest_verdict


def land_units(
    inst: Installation,
    store: UnitStore,
    *,
    dispatch: Callable[..., bool],
    say: Callable[[str], None],
) -> None:
    """Land every unit in review the landing decision allows, one after another: the intent,
    the forge's merge at the approved head, then the merge recorded through `dispatch`. An
    error landing one unit is logged to `say` and the others are still tried."""
    review = config.active().review
    if not review.enabled or not review.auto_land.classes:
        return
    pulls: dict[str, list[PullRequest]] = {}
    landed: set[str] = set()
    for listed in store.all():
        try:
            if _land_unit(inst, store, listed.id, review, pulls, landed, dispatch, say):
                landed.add(listed.id)
                # A merge moves what is stacked on it and changes the host's listing.
                pulls.pop(listed.repo, None)
        except Exception as error:  # noqa: BLE001 — one unit's landing never stops the others.
            say(f"{listed.id}: landing failed — {type(error).__name__}: {error}")


def _land_unit(
    inst: Installation,
    store: UnitStore,
    unit_id: str,
    review: config.ReviewConfig,
    pulls: dict[str, list[PullRequest]],
    landed: set[str],
    dispatch: Callable[..., bool],
    say: Callable[[str], None],
) -> bool:
    """Try to land the unit; whether the merge was recorded. The unit is read afresh, since a
    landing earlier in the pass may have moved it."""
    unit = store.get(unit_id)
    if unit.state != IN_REVIEW or unit.pr is None:
        return False
    if landed.intersection(unit.depends_on):
        # Its base moved with the parent's merge; it is looked at again on the next tick.
        return False
    forge, repo_id = inst.forge_of(unit.repo)
    if unit.repo not in pulls:
        pulls[unit.repo] = ui_listing(inst, store, unit.repo)()
    pull = next((pr for pr in pulls[unit.repo] if pr.number == unit.pr), None)
    if pull is None:
        say(f"{unit.id}: not landed — no pull request #{unit.pr} listed")
        return False
    if pull.state == MERGED:
        # A person merged it before the poll saw it: record it, merge nothing.
        dispatch("merged", unit.pr, repo=unit.repo)
        return True
    entry = latest_verdict(inst.state_dir / VERDICTS, unit.id)
    final = entry if entry is not None and entry.final else None
    units = store.all()
    decision = decide_landing(
        LandingFacts(
            review_enabled=review.enabled,
            state=unit.state,
            feedback_pending=bool(unit.feedback),
            held=unit.held_by is not HeldBy.NONE,
            verdict_tier=final.tier if final else None,
            unit_class=final.unit_class if final else None,
            listed_classes=tuple(review.auto_land.classes),
            forge_merges=forge.merges,
            pr_open=pull.state == "open",
            draft=pull.draft,
            conflicting=pull.mergeable is False,
            labels=pull.labels,
            changes_requested=pull.review_decision == "changes_requested",
            head=unit.pushed or "",
            approved_head=unit.approved or None,
            unmerged_parents=tuple(
                parent.id
                for parent in units
                if parent.id in unit.depends_on and not parent_landed(parent, units)
            ),
            checks=pull.checks,
        )
    )
    if not decision.may_land:
        # Only a unit the verdict clears for landing is told it did not: for any other the
        # landing step has nothing to say, and its note is left as it is.
        if final is not None and final.tier is ReviewTier.AUTO:
            say(f"{unit.id}: not landed — {decision.reason}")
            if unit.note != decision.reason:
                store.record_event(unit.id, "landing_declined", decision.reason)
        return False
    intents = inst.state_dir / landing_intent.LANDING
    try:
        landing_intent.record_intent(intents, repo=unit.repo, pr=unit.pr, unit=unit.id)
    except landing_intent.IntentNotWritten as error:
        store.record_event(unit.id, "landing_declined", str(error))
        say(f"{unit.id}: not landed — {error}")
        return False
    try:
        forge.merge_pr(repo_id, unit.pr, head=unit.approved)
    except MergeRefused as refusal:
        landing_intent.clear_intent(intents, repo=unit.repo, pr=unit.pr)
        store.record_event(unit.id, "landing_refused", refusal.reason)
        say(f"{unit.id}: the host refused the merge — {refusal.reason}")
        return False
    except Exception:
        # The host may have merged before it failed: keep the intent then, so the poller
        # records the merge as the pipeline's own.
        if forge.merge_commit(repo_id, unit.pr) is None:
            landing_intent.clear_intent(intents, repo=unit.repo, pr=unit.pr)
        raise
    dispatch("merged", unit.pr, repo=unit.repo)
    say(f"{unit.id}: landed without a person")
    return True
