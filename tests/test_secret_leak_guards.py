"""The set of known secret values is not all that stands between the environment and the
output: a test-support model must not print its environment, and a settings field that
looks like a credential must be classified.

The first walks the test-support models under `tests/`: every pydantic class that has an
`env` or `environ` field is built with a sample value and fails, naming the model, when
the value is in its repr.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import BaseModel
from pydantic_settings import BaseSettings

from agent_build_kit import settings as settings_module
from agent_build_kit.settings import Settings

TESTS = Path(__file__).parent
SAMPLE = "sample-env-value-0001"
ENV_FIELDS = {"env", "environ"}


def _models_with_an_environment() -> list[str]:
    """`module:Class` for each class under `tests/` with an `env`/`environ` field."""
    found = []
    for path in sorted(TESTS.rglob("*.py")):
        tree = ast.parse(path.read_text())
        module = ".".join(path.relative_to(TESTS.parent).with_suffix("").parts)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                isinstance(field, ast.AnnAssign)
                and isinstance(field.target, ast.Name)
                and field.target.id in ENV_FIELDS
                for field in node.body
            ):
                found.append(f"{module}:{node.name}")
    return found


MODELS = _models_with_an_environment()


@pytest.mark.parametrize("model", MODELS)
def test_a_test_support_model_does_not_print_its_environment(model: str) -> None:
    module, _, name = model.partition(":")
    cls = getattr(importlib.import_module(module), name)
    if not (isinstance(cls, type) and issubclass(cls, BaseModel)):
        pytest.skip(f"{model} is not a pydantic model")
    field = next(f for f in cls.model_fields if f in ENV_FIELDS)

    shown = repr(cast(Any, cls).model_construct(**{field: {"KEY": SAMPLE}}))

    assert SAMPLE not in shown, f"{model} prints its {field}"


class _WithUnclassified(BaseSettings):
    api_token: str = ""
    signing_key: str = ""
    deploy_pat: str = ""
    client_secret: str = ""
    region: str = ""


def test_the_settings_fields_that_look_like_credentials_are_all_classified() -> None:
    assert settings_module.unclassified_secret_fields(Settings) == ()


def test_an_unclassified_field_is_reported_by_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module, "NOT_SECRET_FIELDS", ("client_secret",))

    reported = settings_module.unclassified_secret_fields(_WithUnclassified)

    assert reported == ("api_token", "deploy_pat", "signing_key")
