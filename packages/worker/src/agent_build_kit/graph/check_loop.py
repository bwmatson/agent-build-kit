"""The check-and-fix routine the stub loop and the checks loop share.

The nodes call `check_round` and `fix_round` through this module (`check_loop.check_round`), so a
test can stand a recording fake in their place. The routine knows nothing about tests: the check
is a callable, and what differs between the loops is the `CheckLoop` a node passes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from agent_build_kit.config import active, models
from agent_build_kit.graph.state import UnitRun
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.stack_runner import person_guidance
from agent_build_kit.pipeline.unit_store import FeedbackSource
from agent_build_kit.redaction import redact_text

if TYPE_CHECKING:
    from agent_build_kit.graph.nodes import BuildPath, Update


class CheckParked(Exception):
    """The check parked the unit instead of passing or failing; `update` is the node's result."""

    def __init__(self, update: Update) -> None:
        super().__init__("parked")
        self.update = update


class CheckLoop(Frozen):
    """What differs between the two loops: the check, where a failure is saved, the counter,
    the fix prompt and the commit rule (`None`: no commit; else a template over `title` and
    `n`, as `fix: {title} (checks, round {n})`).

    `prompt` and `follow_up` take the redacted feedback and the person's guidance; `clears` says
    whether a pass erases the saved feedback; `already_done` says a fix round is already on the
    branch; `on_failure` is told of each failed check with its round; `annotate` adds to the
    failed output before it is saved as feedback; `on_unchanged` is given the round that changed
    nothing and answers with an update in place of the stop, or None to stop; `on_base` is asked
    before either stop, and answers an update that parks the unit on tests that fail on its base,
    or None to stop as before; `retry` is the prompt of one more attempt in the same round after an
    attempt that changed nothing (given the feedback and the guidance), None for a loop that
    makes none."""

    check: Callable[[], tuple[bool, str]]
    source: FeedbackSource
    heading: str
    rounds: str
    commit: str | None
    prompt: Callable[[str, str], str]
    follow_up: Callable[[str, str], str] | None = None
    label: str
    clears: Callable[[UnitRun], bool]
    already_done: Callable[[], bool] | None = None
    on_failure: Callable[[str, int], None] | None = None
    annotate: Callable[[str], str] | None = None
    on_unchanged: Callable[[int], dict[str, Any] | None] | None = None
    on_base: Callable[[], dict[str, Any] | None] | None = None
    retry: Callable[[str, str], str] | None = None
    spent_message: Callable[[int], str]
    unchanged_message: Callable[[int], str]


def out_of_rounds(used: int) -> int | None:
    """`global_limits.max_check_rounds` when `used` fix rounds have spent it, else None;
    `null` is no limit and 0 is spent at once."""
    budget = active().global_limits.max_check_rounds
    return budget if budget is not None and used >= budget else None


def check_round(nodes: BuildPath, state: UnitRun, loop: CheckLoop) -> Update:
    """Run the check. `{"ok": True}` on a pass; on a failure the failure is said, counted,
    saved as feedback and, when the rounds are spent, the stop; a parked check's own update."""
    r, unit = nodes.runner, nodes.unit
    if loop.commit is None:
        nodes.apply_fixers()  # the check sees the formatted tree; the commit follows the pass
    try:
        ok, output = loop.check()
    except CheckParked as parked:
        return parked.update
    used = getattr(state, loop.rounds)
    if ok:
        if loop.clears(state):
            r.store.set_feedback(unit.id, "")
        return {"ok": True}
    nodes.say(output)
    if loop.on_failure is not None:
        loop.on_failure(output, used + 1)
    # Kept before anything can stop the run, so a retry addresses this output.
    if loop.annotate is not None:
        output = loop.annotate(output)
    saved = f"{loop.heading}\n{output}".strip() if loop.heading else output
    r.store.set_feedback(unit.id, saved, source=loop.source)
    if (budget := out_of_rounds(used)) is not None:
        if loop.on_base is not None and (waiting := loop.on_base()) is not None:
            return waiting
        return nodes.stop(loop.spent_message(budget))
    return {}


def fix_round(nodes: BuildPath, state: UnitRun, loop: CheckLoop) -> Update:
    """One fix round: the agent answers the saved feedback, the loop's commit rule is applied,
    and a round that moved neither the head nor the tree stops the unit."""
    r, unit = nodes.runner, nodes.unit
    tree = nodes.tree()
    attempt = getattr(state, loop.rounds) + 1
    if loop.already_done is not None and loop.already_done():
        nodes.say(f"fix round {attempt} is already on the branch")
        return {loop.rounds: attempt}
    # The model that wrote the code fixes it, whatever the configuration says now.
    model = state.build_model or models().implement
    feedback = redact_text(r.store.get(unit.id).feedback, where="fix prompt")
    note = person_guidance(r.store.get(unit.id).guidance)
    before = (r.head(tree), r.tree_state(tree))
    nodes.say(f"fix the failing {loop.label} ({model}), round {attempt}")

    def attempt_once(prompt: str, follow_up: str) -> bool:
        """One agent call and the commit rule; whether the branch moved."""
        nodes.agent(r.run, prompt, cwd=tree, state=state, model=model, follow_up=follow_up)
        if loop.commit is not None:
            nodes.apply_fixers()
            r.commit(
                loop.commit.format(title=unit.title, n=attempt), cwd=tree, base=nodes.ref(state)
            )
        return (r.head(tree), r.tree_state(tree)) != before

    follow_up = loop.follow_up(feedback, note) if loop.follow_up else ""
    if attempt_once(loop.prompt(feedback, note), follow_up):
        return {loop.rounds: attempt}
    if loop.on_base is not None and (waiting := loop.on_base()) is not None:
        return waiting
    if loop.retry is not None:
        nodes.say(f"fix round {attempt} changed nothing; one more attempt")
        if attempt_once(loop.retry(feedback, note), ""):
            return {loop.rounds: attempt}
    if loop.on_unchanged is not None and (answer := loop.on_unchanged(attempt)) is not None:
        return answer
    return nodes.stop(loop.unchanged_message(attempt))
