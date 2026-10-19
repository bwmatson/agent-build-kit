"""A real agent reuses, generalizes and shares as the builders' prompts ask.

Three cases, each one unit built once by Claude Code, in a scratch app that tempts duplication.
Every assertion is structural: it counts definitions and call sites in what the agent wrote,
never a model's reading of it. A red run is one of three
things, told apart in this order by the failure message: the prompt was not delivered (the
prompt test fails), the agent ignored it (the prompt test passes and a structural one fails
with a copy in the diff), or the assertion was too strict (the diff shows no copied logic).
No assertion is loosened to turn a run green.

Needs a Claude Code account, node for the OpenSpec CLI and uv. The prompts are recorded by a
wrapper set as `runtimes.claude_code.command` (`tests/claude_recorder.py`); the ACP form of that
check is a separate module. Bills on demand and takes minutes per case, so it is marked
e2e-test and excluded from the default suite.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator

import pytest

from agent_build_kit.pipeline.reuse_guidance import reuse_guidance
from tests.dry_checks import (
    Definition,
    calls_by_name,
    claude_session_prompts,
    definitions,
    diff_definitions,
    is_copy,
    literal_count,
    reaches_by_name,
    source_at,
)
from tests.dry_scratch import (
    SQUEEZE,
    UPPER,
    DryRun,
    evidence,
    fake_host,
    old_tests_pass,
    ticked_case,
)
from tests.forges.github_server import FakeGitHub
from tests.prompt_text import flat
from tests.runtime_scratch import CLAUDE_CODE_PARAMS

pytestmark = [
    pytest.mark.local_stack,
    pytest.mark.skipif(shutil.which("npx") is None, reason="npx is not on PATH"),
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]

TESTS_STEP = "Work ONLY the test tasks"


@pytest.fixture(scope="module")
def github_host() -> Iterator[FakeGitHub]:
    with fake_host() as server:
        yield server


def case(
    tmp_path_factory: pytest.TempPathFactory, github: FakeGitHub, name: str, runtime: str
) -> Iterator[DryRun]:
    with ticked_case(tmp_path_factory, github, name, runtime) as run:
        yield run


# The one parameter carries the module's one runtime tag, `runtime_claude_code`.
@pytest.fixture(scope="module", params=CLAUDE_CODE_PARAMS)
def reuse(request, tmp_path_factory, github_host) -> Iterator[DryRun]:
    yield from case(tmp_path_factory, github_host, "reuse", request.param)


@pytest.fixture(scope="module", params=CLAUDE_CODE_PARAMS)
def generalize(request, tmp_path_factory, github_host) -> Iterator[DryRun]:
    yield from case(tmp_path_factory, github_host, "generalize", request.param)


@pytest.fixture(scope="module", params=CLAUDE_CODE_PARAMS)
def share(request, tmp_path_factory, github_host) -> Iterator[DryRun]:
    yield from case(tmp_path_factory, github_host, "share", request.param)


def only(found: list, run: DryRun, what: str):
    """The one item of `found`, or a failure that carries the evidence."""
    assert len(found) == 1, f"expected one {what}, found {len(found)}\n{evidence(run)}"
    return found[0]


def existing_slugify(run: DryRun) -> Definition:
    found = [d for d in definitions(run.repo, "main") if d.name == "slugify"]
    return only(found, run, "slugify on main")


def source_of(run: DryRun, name: str) -> str:
    """The branch's file holding the definition `name`."""
    found = [d for d in definitions(run.repo, run.branch) if d.name == name]
    return source_at(run.repo, run.branch, only(found, run, f"definition of {name}").path)


def added_by(run: DryRun) -> tuple[Definition, ...]:
    return diff_definitions(run.repo, "main", run.branch).added


# (a) A task names a helper an existing function already covers.


def test_reuse_adds_no_function_carrying_the_existing_helpers_logic(reuse: DryRun) -> None:
    original = existing_slugify(reuse)

    copies = [d.name for d in added_by(reuse) if is_copy(original.source, d.source)]

    assert copies == [], evidence(reuse)
    assert literal_count(reuse.repo, reuse.branch, SQUEEZE) == 1, evidence(reuse)


def test_reuse_has_the_function_the_task_names_call_the_existing_helper(reuse: DryRun) -> None:
    # Through the branch's own definitions: a task that names `title_slug` is met by a thin
    # function that calls `slugify`, which copies no logic.
    found = definitions(reuse.repo, reuse.branch)

    assert reaches_by_name(found, "page_path", "slugify"), evidence(reuse)


# (b) A task needs a variant of an existing function.


def test_generalize_changes_the_existing_function_and_keeps_its_literal_once(
    generalize: DryRun,
) -> None:
    diff = diff_definitions(generalize.repo, "main", generalize.branch)

    assert [d.name for d in diff.changed if d.name == "slugify"] == ["slugify"], evidence(
        generalize
    )
    assert literal_count(generalize.repo, generalize.branch, SQUEEZE) == 1, evidence(generalize)


def test_generalize_adds_no_function_carrying_the_existing_functions_logic(
    generalize: DryRun,
) -> None:
    original = existing_slugify(generalize)

    copies = [d.name for d in added_by(generalize) if is_copy(original.source, d.source)]

    assert copies == [], evidence(generalize)


def test_generalize_has_the_new_entry_point_call_the_existing_function(generalize: DryRun) -> None:
    entry = [d for d in added_by(generalize) if d.name == "file_stem"]

    # The variant may go into the existing function alone, with no new entry point.
    for definition in entry:
        assert calls_by_name(definition.source, "file_stem", "slugify"), evidence(generalize)


def test_generalize_keeps_the_old_tests_of_the_function_passing(generalize: DryRun) -> None:
    assert old_tests_pass(generalize) == "", evidence(generalize)


# (c) Logic needed at two call sites with no helper.


def test_share_adds_the_two_named_functions_and_exactly_one_other(share: DryRun) -> None:
    added = {d.name for d in added_by(share)}

    assert {"invoice_label", "receipt_label"} <= added, evidence(share)
    assert len(added - {"invoice_label", "receipt_label"}) == 1, evidence(share)


def test_share_defines_the_formatting_once(share: DryRun) -> None:
    assert literal_count(share.repo, share.branch, UPPER) == 1, evidence(share)


def test_share_has_both_named_functions_call_the_one_other_definition(share: DryRun) -> None:
    named = {"invoice_label", "receipt_label"}
    helper = only([d for d in added_by(share) if d.name not in named], share, "other definition")

    for name in sorted(named):
        assert calls_by_name(source_of(share, name), name, helper.name), evidence(share)


# (d) The prompts the agent was sent, recorded at its protocol, in case (a)'s run.


def test_the_tests_step_prompt_held_the_reuse_part_and_the_three_way_instruction(
    reuse: DryRun,
) -> None:
    prompts = [run.text for run in claude_session_prompts(reuse.record)]
    steps = [p for p in prompts if TESTS_STEP in p]
    assert len(steps) == 1, (
        f"{len(steps)} tests-step prompts of {len(prompts)} sent\n"
        + "\n---\n".join(p[:300] for p in prompts)
    )

    assert reuse_guidance() in steps[0]
    for stem in ("(a)", "(b)", "(c)", "reused", "instead of adding"):
        assert stem in steps[0], stem


def test_the_prompt_that_carries_the_do_not_weaken_sentence_holds_the_repointing_line(
    reuse: DryRun,
) -> None:
    prompts = [run.text for run in claude_session_prompts(reuse.record)]

    # Flattened before the search: the continuation wraps the sentence across two lines.
    carrying = [
        squeezed
        for squeezed in map(flat, prompts)
        if "Do not weaken or delete a test to make it pass" in squeezed
    ]

    assert carrying, "no prompt told the agent not to weaken a test"
    for prompt in carrying:
        assert "repoint the test at the existing function with the same assertions" in prompt


def test_no_continuation_prompt_holds_the_reuse_part(reuse: DryRun) -> None:
    runs = claude_session_prompts(reuse.record)
    assert runs, "the wrapper recorded no prompt"
    # A run that resumes the unit's session is sent a continuation; one that starts a session
    # is sent a full prompt.
    continuations = [run for run in runs if run.resume]
    if not continuations:
        pytest.skip("session reuse sent no continuation: no run resumed a session")

    for run in continuations:
        assert reuse_guidance() not in run.text
