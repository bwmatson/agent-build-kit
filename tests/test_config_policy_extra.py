"""`runtimes.<name>.policy_extra`: an installation's own globs, merged after the kit's."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_build_kit.config import RuntimeConfig


def entry(**fields: object) -> RuntimeConfig:
    return RuntimeConfig.model_validate(fields)


BAD_ITEMS = ["", "   ", 3, None, ["x"]]


def test_a_blank_or_non_string_item_fails_naming_the_key() -> None:
    # the key loads, an entry without it is unchanged, and each bad item fails
    assert entry(policy_extra=["git * push --mirror*"]).policy_extra == ["git * push --mirror*"]
    assert entry(command=["some-agent", "acp"]).policy_extra is None
    for item in BAD_ITEMS:
        with pytest.raises(ValidationError, match="policy_extra"):
            entry(policy_extra=["git * push --mirror*", item])
