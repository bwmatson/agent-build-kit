"""The body of a build commit: why the change exists, composed without a model call."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.pipeline.stack_runner import GroupStep


def commit_body(steps: Sequence[GroupStep], *, tests: bool) -> str:
    """The body of the tests commit (`tests`) or the implementation commit for these groups:
    the first sentence of each change's proposal Why, once, then the groups' goals. Empty when
    there is neither."""
    raise NotImplementedError
