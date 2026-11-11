"""A repository's default deselection of the integration and e2e kinds, for the tests of the
by-id runs (spec: integration-tests-run-in-the-unit-gate): the one pyproject text they share."""

from __future__ import annotations

from pathlib import Path

CONFIG = Path(__file__).resolve().parent / "child_modules" / "red_check_by_id"
# A pyproject whose pytest configuration deselects the integration and e2e kinds by default.
PYPROJECT = (CONFIG / "default_deselection_config.txt").read_text()
# The marker expression of that configuration, and what a run of named tests uses in its place:
# the integration kind let through, every other exclusion kept.
DEFAULT_MARKERS = "not integration and not e2e"
BY_ID_MARKERS = f"integration or ({DEFAULT_MARKERS})"
