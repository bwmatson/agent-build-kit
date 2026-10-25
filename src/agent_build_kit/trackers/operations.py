"""How each tracker operation may be repeated: one declaration per protocol method."""

from __future__ import annotations

from collections.abc import Mapping

from agent_build_kit.forges.operations import OperationSpec

OPERATIONS: Mapping[str, OperationSpec] = {}
