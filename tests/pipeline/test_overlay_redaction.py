"""A `verify.env` provider that only `abk.local.yaml` declares is resolved for verification and
its value is redacted from stored text like any other."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from agent_build_kit import redaction
from agent_build_kit.installation import load_installation
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.factories import stored_unit

VALUE = "overlay-secret-0001"


@pytest.fixture(autouse=True)
def restore_redaction() -> Iterator[None]:
    previous = redaction.active()
    yield
    redaction.activate(previous)


def test_an_overlay_provider_is_resolved_and_redacted(tmp_path: Path) -> None:
    (tmp_path / "stack.env").write_text(f"STACK_KEY={VALUE}\n")
    path = tmp_path / "abk.yaml"
    path.write_text(yaml.safe_dump({"repos": {"app": {"path": ".", "slug": "example/app"}}}))
    (tmp_path / "abk.local.yaml").write_text(
        yaml.safe_dump(
            {
                "verify": {
                    "env": {
                        "STACK_KEY": {
                            "from": "env-file",
                            "file": str(tmp_path / "stack.env"),
                            "key": "STACK_KEY",
                        }
                    }
                }
            }
        )
    )

    inst = load_installation(path)

    assert inst.verify_env() == {"STACK_KEY": VALUE}
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit()])
    store.set_feedback("add-marker/1", f"e2e-test failed with {VALUE} in the output")
    stored = store.get("add-marker/1").feedback
    assert VALUE not in stored
    assert "[redacted:STACK_KEY]" in stored
    assert VALUE not in (tmp_path / "units.json").read_text()
