"""The set of known secret values: what is gathered, under which names, and
that it is shown by name only."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

from agent_build_kit import redaction
from agent_build_kit.pipeline.gateway_usage import KEY_ENV, GatewayUsage
from agent_build_kit.settings import CREDENTIAL_FIELDS, Settings
from tests.conftest import make_installation
from tests.fake_gateway import MASTER, serving

VERIFY = "verify-value-0001"
RUNTIME = "runtime-value-002"
LISTED = "listed-value-0003"
TOKEN = "credential-value-4"


def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("GH_TOKEN", "ABK_GH_TOKEN", "ABK_GATEWAY_MASTER_KEY", "LISTED_VAR"):
        monkeypatch.delenv(key, raising=False)


def test_each_source_is_held_under_its_own_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_environment(monkeypatch)
    (tmp_path / ".env").write_text(f"GH_TOKEN={TOKEN}\nLISTED_VAR={LISTED}\n")
    monkeypatch.setenv("FROM_PROCESS", "process-value-005")
    installation = make_installation(
        tmp_path,
        verify={"env": {"STACK_KEY": {"from": "literal", "value": VERIFY}}},
        runtimes={"claude_code": {"command": ["x"], "env": {"EXTRA": RUNTIME}}},
        redact=["LISTED_VAR", "FROM_PROCESS"],
    )

    secrets = redaction.gather(installation)

    assert set(secrets.names) >= {
        "STACK_KEY",
        "gh_token",
        "runtimes.claude_code.EXTRA",
        "LISTED_VAR",
        "FROM_PROCESS",
    }
    assert secrets.redact(VERIFY) == "[redacted:STACK_KEY]"
    assert secrets.redact(TOKEN) == "[redacted:gh_token]"
    assert secrets.redact(RUNTIME) == "[redacted:runtimes.claude_code.EXTRA]"
    assert secrets.redact(LISTED) == "[redacted:LISTED_VAR]"
    assert secrets.redact("process-value-005") == "[redacted:FROM_PROCESS]"


def test_every_credential_field_of_the_settings_is_listed() -> None:
    secret_named = {
        name for name in Settings.model_fields if name.endswith(("token", "key", "pat", "secret"))
    }

    assert secret_named <= set(CREDENTIAL_FIELDS)
    assert {"gh_token", "ado_pat", "gateway_master_key", "grafana_token"} <= set(CREDENTIAL_FIELDS)


def test_activating_an_installation_rebuilds_the_set_from_the_reloaded_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_environment(monkeypatch)
    env = tmp_path / ".env"
    env.write_text(f"GH_TOKEN={TOKEN}\n")
    installation = make_installation(tmp_path)
    assert redaction.active().redact(TOKEN) == "[redacted:gh_token]"

    env.write_text("GH_TOKEN=rotated-value-0006\n")
    installation.activate()

    assert redaction.active().redact("rotated-value-0006") == "[redacted:gh_token]"
    assert redaction.active().redact(TOKEN) == TOKEN


def test_the_set_shows_names_only_when_printed() -> None:
    secrets = redaction.Redactor({"API_KEY": VERIFY, "OTHER": RUNTIME})

    for shown in (repr(secrets), str(secrets), f"{secrets}", f"{secrets!r}"):
        assert "API_KEY" in shown
        assert VERIFY not in shown
        assert RUNTIME not in shown


def test_a_value_whose_provider_fails_is_left_out_with_one_warning_holding_no_value(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    _clean_environment(monkeypatch)
    leaking = (
        "import sys; sys.stderr.write('stderr-leak-value-007'); sys.exit(3)"  # fails, says a value
    )
    installation = make_installation(
        tmp_path,
        verify={
            "env": {
                "BROKEN": {"from": "command", "argv": [sys.executable, "-c", leaking]},
                "FINE": {"from": "literal", "value": VERIFY},
            }
        },
    )

    with caplog.at_level(logging.WARNING):
        secrets = redaction.gather(installation)

    assert "BROKEN" not in secrets.names
    assert secrets.redact(VERIFY) == "[redacted:FINE]"
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1
    assert "BROKEN" in warnings[0].getMessage()
    assert "stderr-leak-value-007" not in caplog.text
    assert VERIFY not in caplog.text


def test_a_minted_gateway_key_is_registered_under_gateway_key() -> None:
    with serving() as gateway:
        client = GatewayUsage(gateway.url, MASTER, lambda _: None, settle_seconds=0.3)
        env, handle = client.begin("add-marker/1:implement:0")
        key = env[KEY_ENV]

        assert redaction.active().redact(f"ran with {key}") == "ran with [redacted:gateway-key]"
        client.finish(handle)

    # Revoking the key does not drop it: text written before the revoke still holds it.
    assert redaction.active().redact(key) == "[redacted:gateway-key]"
