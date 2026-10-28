"""Fixtures for the tracker tests: the forge's REST environment (a configured PAT and no
subprocess) serves the work item calls too, as they share its credential."""

from __future__ import annotations

from tests.forges.conftest import rest_env  # noqa: F401
