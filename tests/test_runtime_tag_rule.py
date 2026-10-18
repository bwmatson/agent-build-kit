"""A live-stack test carries at most one runtime tag, wherever the tags come from
(spec: e2e-runtime-tags)."""

from __future__ import annotations

import pytest

from tests.runtime_tag_collection import collect


def failed_naming(result: pytest.RunResult, *needles: str) -> None:
    assert result.ret != 0
    output = result.stdout.str() + result.stderr.str()
    for needle in needles:
        assert needle in output, output


def test_two_tags_on_the_test_fail_naming_the_test_and_both(pytester: pytest.Pytester) -> None:
    result = collect(
        pytester,
        test_both="""
import pytest


@pytest.mark.local_stack
@pytest.mark.runtime_acp
@pytest.mark.runtime_claude_code
def test_drives_two():
    pass
""",
    )

    failed_naming(result, "test_drives_two", "runtime_acp", "runtime_claude_code")


def test_a_class_tag_and_a_test_tag_fail(pytester: pytest.Pytester) -> None:
    result = collect(
        pytester,
        test_class="""
import pytest


@pytest.mark.runtime_acp
class TestLive:
    @pytest.mark.local_stack
    @pytest.mark.runtime_claude_code
    def test_drives_two(self):
        pass
""",
    )

    failed_naming(result, "test_drives_two", "runtime_acp", "runtime_claude_code")


def test_a_module_tag_and_a_test_tag_fail(pytester: pytest.Pytester) -> None:
    result = collect(
        pytester,
        test_module="""
import pytest

pytestmark = pytest.mark.runtime_acp


@pytest.mark.local_stack
@pytest.mark.runtime_claude_code
def test_drives_two():
    pass
""",
    )

    failed_naming(result, "test_drives_two", "runtime_acp", "runtime_claude_code")


def test_a_parameter_tag_and_a_module_tag_fail_naming_the_item(pytester: pytest.Pytester) -> None:
    result = collect(
        pytester,
        test_param_module="""
import pytest

pytestmark = [pytest.mark.local_stack, pytest.mark.runtime_acp]


@pytest.mark.parametrize(
    "runtime",
    [pytest.param("claude", marks=pytest.mark.runtime_claude_code)],
)
def test_drives_one(runtime):
    pass
""",
    )

    failed_naming(result, "test_drives_one[claude]", "runtime_acp", "runtime_claude_code")


def test_one_tag_collects(pytester: pytest.Pytester) -> None:
    result = collect(
        pytester,
        test_one="""
import pytest


@pytest.mark.local_stack
@pytest.mark.runtime_acp
def test_drives_one():
    pass
""",
    )

    assert result.ret == 0
    result.stdout.fnmatch_lines(["*test_drives_one*"])


def test_no_tag_collects_as_the_base(pytester: pytest.Pytester) -> None:
    result = collect(
        pytester,
        test_none="""
import pytest


@pytest.mark.local_stack
def test_drives_no_agent():
    pass
""",
    )

    assert result.ret == 0
    result.stdout.fnmatch_lines(["*test_drives_no_agent*"])


def test_the_same_tag_twice_collects(pytester: pytest.Pytester) -> None:
    result = collect(
        pytester,
        test_twice="""
import pytest

pytestmark = pytest.mark.runtime_acp


@pytest.mark.local_stack
@pytest.mark.runtime_acp
def test_drives_one():
    pass
""",
    )

    assert result.ret == 0


def test_a_test_that_is_not_live_stack_is_not_checked(pytester: pytest.Pytester) -> None:
    result = collect(
        pytester,
        test_plain="""
import pytest


@pytest.mark.runtime_acp
@pytest.mark.runtime_claude_code
def test_plain():
    pass
""",
    )

    assert result.ret == 0


PARAMETERS_EACH_TAGGED = """
import pytest


@pytest.mark.local_stack
@pytest.mark.parametrize(
    "runtime",
    [
        pytest.param("claude", marks=pytest.mark.runtime_claude_code),
        pytest.param("acp", marks=pytest.mark.runtime_acp),
    ],
)
def test_drives_one(runtime):
    pass
"""


def listed(result: pytest.RunResult) -> list[str]:
    return [line for line in result.outlines if "::test_drives_one[" in line]


def test_parameters_with_one_different_tag_each_collect_as_separate_items(
    pytester: pytest.Pytester,
) -> None:
    both = collect(pytester, test_params=PARAMETERS_EACH_TAGGED)
    acp = collect(pytester, "runtime_acp", test_params=PARAMETERS_EACH_TAGGED)
    claude = collect(pytester, "runtime_claude_code", test_params=PARAMETERS_EACH_TAGGED)

    assert both.ret == 0
    assert len(listed(both)) == 2
    assert [line.split("::")[-1] for line in listed(acp)] == ["test_drives_one[acp]"]
    assert [line.split("::")[-1] for line in listed(claude)] == ["test_drives_one[claude]"]
