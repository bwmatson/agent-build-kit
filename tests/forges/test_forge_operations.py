"""The operation table: every forge protocol method declares how it may be repeated."""

from __future__ import annotations

import inspect

import pytest

from agent_build_kit import forges
from agent_build_kit.forges.base import Forge
from agent_build_kit.forges.operations import OPERATIONS
from agent_build_kit.forges.resilient import ResilientForge


def protocol_methods() -> list[str]:
    return sorted(
        {
            name
            for klass in Forge.__mro__
            for name, member in vars(klass).items()
            if inspect.isfunction(member) and not name.startswith("_")
        }
    )


def test_every_protocol_method_has_an_entry() -> None:
    missing = [name for name in protocol_methods() if name not in OPERATIONS]

    assert protocol_methods()
    assert missing == []


def test_the_table_names_no_method_the_protocol_lacks() -> None:
    assert sorted(set(OPERATIONS) - set(protocol_methods())) == []


def test_only_a_create_names_the_read_that_shows_it_landed() -> None:
    assert OPERATIONS
    for name, spec in OPERATIONS.items():
        assert (spec.lands is not None) == (spec.kind == "create"), name


@pytest.mark.parametrize(
    "name, kind, lands",
    [
        ("find_pr", "read", None),
        ("list_prs", "read", None),
        ("pr_files", "read", None),
        ("review_notes", "read", None),
        ("stack_of", "read", None),
        ("update_pr", "idempotent_write", None),
        ("post_status", "idempotent_write", None),
        ("close_pr", "idempotent_write", None),
        ("rerun_checks", "idempotent_write", None),
        ("add_label", "advisory", None),
        ("set_exclusive_label", "advisory", None),
        ("remove_label", "idempotent_write", None),
        ("create_pr", "create", "find_pr"),
        ("post_comment", "create", "comment_exists"),
        ("post_reply", "create", "comment_exists"),
        ("create_stack", "create", "stack_of"),
        ("add_to_stack", "create", "stack_of"),
        ("set_draft", "advisory", None),
    ],
)
def test_an_operation_is_declared_with_the_kind_its_effect_calls_for(
    name: str, kind: str, lands: str | None
) -> None:
    assert OPERATIONS[name].kind == kind
    assert OPERATIONS[name].lands == lands


def test_failed_check_logs_is_a_read_that_is_contained_with_an_empty_neutral() -> None:
    spec = OPERATIONS["failed_check_logs"]

    assert spec.kind == "read"
    assert spec.contains
    assert spec.neutral == ""


def test_the_wrapper_offers_every_protocol_method() -> None:
    for name in protocol_methods():
        assert callable(getattr(ResilientForge, name, None)), name


@pytest.mark.parametrize("name", ["github", "azure_devops"])
def test_the_registry_returns_wrapped_forges(name: str) -> None:
    forge = forges.get(name)

    assert isinstance(forge, ResilientForge)
    assert forge.name == name
