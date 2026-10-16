"""A reading that cannot be taken is unknown, with a reason, and never raises."""

from __future__ import annotations

import importlib.abc
import logging
import sys
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from agent_build_kit.runtimes.providers import ProviderUnknown, read_usage
from tests.redaction_fakes import SECRET, known

NOW = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)
TOKEN = "sk-" + "a1B2c3D4" * 4


class AuthenticationError(Exception):
    """The class a library's refused login raises."""


class RequestedImports(importlib.abc.MetaPathFinder):
    """Records every top-level name the import system is asked for, and finds none."""

    def __init__(self) -> None:
        self.names: set[str] = set()

    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001, ANN201
        self.names.add(fullname.partition(".")[0])
        return None


def unknown(result: object) -> ProviderUnknown:
    assert isinstance(result, ProviderUnknown), result
    return result


def test_a_library_that_is_not_installed_is_unknown_and_names_the_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "modal", None)

    result = unknown(read_usage("modal", budget_usd=200, now=NOW))

    assert "modal" in result.reason
    assert "acp" not in result.reason


def test_finding_the_library_absent_imports_nothing_else(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "modal", raising=False)
    finder = RequestedImports()
    monkeypatch.setattr(sys, "meta_path", [finder, *sys.meta_path])

    unknown(read_usage("modal", budget_usd=200, now=NOW))

    assert finder.names == {"modal"}


def test_an_authentication_error_is_unknown_with_its_class_and_message_redacted() -> None:
    def refused() -> object:
        raise AuthenticationError(f"token {TOKEN} was refused and so was {SECRET}")

    with known():
        result = unknown(read_usage("modal", budget_usd=200, now=NOW, read=refused))

    assert "AuthenticationError" in result.reason
    assert "was refused" in result.reason
    assert TOKEN not in result.reason
    assert SECRET not in result.reason


@pytest.mark.parametrize("error", [RuntimeError("no network"), TimeoutError("slow"), KeyError("k")])
def test_any_other_exception_is_unknown_and_does_not_propagate(error: Exception) -> None:
    def raises() -> object:
        raise error

    result = unknown(read_usage("modal", budget_usd=200, now=NOW, read=raises))

    assert type(error).__name__ in result.reason


def test_a_log_line_holds_no_more_than_the_parsed_figures_and_the_reason(
    caplog: pytest.LogCaptureFixture,
) -> None:
    breakdown = {"object-id-7f3a9c": Decimal("12.5"), "app-name-private": Decimal("1")}
    given = SimpleNamespace(
        start=datetime(2026, 10, 1, tzinfo=UTC),
        end=datetime(2026, 11, 1, tzinfo=UTC),
        metered_cost=Decimal("173.04285316"),
        metered_cost_breakdown=breakdown,
        adjustments=[{"note": "credit-note-4821"}],
        billed_cost=Decimal("142.99"),
    )

    def refused() -> object:
        raise AuthenticationError(f"token {TOKEN}")

    with caplog.at_level(logging.DEBUG):
        read_usage("modal", budget_usd=200, now=NOW, read=lambda: given)
        read_usage("modal", budget_usd=200, now=NOW, read=refused)

    for private in ("object-id-7f3a9c", "app-name-private", "credit-note-4821", "142.99", TOKEN):
        assert private not in caplog.text
