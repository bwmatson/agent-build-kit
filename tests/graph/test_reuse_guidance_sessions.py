"""Which requests carry the reuse part when a role's session is reused.

The part is initial context: the prompt that writes the tests starts the build session
and carries it, a continuation does not repeat it, and a node that starts a new session
(entering past the tests, a fallback, reuse off) carries it in its full prompt. The
lines about the feedback in hand stay in both forms (spec: dry-guidance).
"""

import re
from pathlib import Path

from agent_build_kit.pipeline.reuse_guidance import reuse_guidance
from tests.graph.agent_fakes import distinct_models
from tests.graph.test_session_continuation import (
    REWORK_ASK,
    Sessions,
    agents,
    failing_checks,
    reuse,
)
from tests.graph_driver import fresh, tick
from tests.runner_fakes import approving, rejecting

OTHERS = re.compile(r"look for (the )?others of the (same )?kind", re.IGNORECASE)


def squeezed(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def carries(prompt: str) -> bool:
    return squeezed(reuse_guidance()) in squeezed(prompt)


def test_the_tests_prompt_carries_the_part_and_the_continuations_after_it_do_not(
    tmp_path: Path,
) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    failing_checks(recorder)
    runtime = Sessions()

    tick(tmp_path, recorder, **agents(runtime))

    tests, implement, fix = runtime.built
    assert carries(tests.prompt)
    assert implement.resume_session == "sess-1" and not carries(implement.prompt)
    assert fix.resume_session == "sess-1" and not carries(fix.prompt)


def test_with_reuse_off_every_build_prompt_is_a_full_one_with_the_part(tmp_path: Path) -> None:
    distinct_models()
    reuse(build=False)
    recorder = fresh(tmp_path)
    failing_checks(recorder)
    runtime = Sessions()

    tick(tmp_path, recorder, **agents(runtime))

    assert len(runtime.built) == 3
    assert all(carries(request.prompt) for request in runtime.built)


def test_a_unit_entering_past_the_tests_gets_the_part_in_its_first_prompt(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    recorder.made = 2
    failing_checks(recorder)
    runtime = Sessions()

    tick(tmp_path, recorder, branch_commits=lambda cwd, base: recorder.made, **agents(runtime))

    (fix, *_) = runtime.built
    assert fix.resume_session == ""
    assert carries(fix.prompt)


def test_a_fallback_to_a_new_session_gets_the_part(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    failing_checks(recorder)
    runtime = Sessions(refuses="no conversation found with session id sess-1")

    tick(tmp_path, recorder, **agents(runtime))

    *_, last = runtime.built
    assert last.resume_session == ""
    assert carries(last.prompt)


def test_the_rework_lines_stay_in_the_continuation_without_the_part(tmp_path: Path) -> None:
    distinct_models()
    recorder = fresh(tmp_path)
    runtime = Sessions(verdicts=[rejecting(REWORK_ASK), approving()])

    tick(tmp_path, recorder, **agents(runtime))

    continued = runtime.built[2]
    assert continued.resume_session == "sess-1"
    assert REWORK_ASK in continued.prompt
    assert OTHERS.search(squeezed(continued.prompt))
    assert not carries(continued.prompt)


def test_the_rework_lines_stay_in_the_full_prompt_with_the_part(tmp_path: Path) -> None:
    distinct_models()
    reuse(build=False)
    recorder = fresh(tmp_path)
    runtime = Sessions(verdicts=[rejecting(REWORK_ASK), approving()])

    tick(tmp_path, recorder, **agents(runtime))

    full = runtime.built[2]
    assert full.resume_session == ""
    assert REWORK_ASK in full.prompt
    assert OTHERS.search(squeezed(full.prompt))
    assert carries(full.prompt)
