"""Where the local implementation keeps each kind of artifact, under the state directory.

The only place that names the directories; every other module reaches an artifact by key through
the Artifacts interface.
"""

from __future__ import annotations

from pathlib import Path

RUN_LOGS = "unit-logs"
E2E_OUTPUTS = "e2e-output"
FAILURE_BUNDLES = "test-failures"
TRANSCRIPTS = "transcripts"
SPEC_SNAPSHOTS = "spec-snapshots"


def run_log_dir(state_dir: Path) -> Path:
    """The directory of the unit run logs, under the state directory."""
    return state_dir / RUN_LOGS


def failure_bundles_dir(state_dir: Path) -> Path:
    """The directory of the bundles of failing unit-test runs, under the state directory."""
    return state_dir / FAILURE_BUNDLES


def transcript_dir(state_dir: Path) -> Path:
    """The directory of the transcripts, under the state directory."""
    return state_dir / TRANSCRIPTS


def snapshot_dir(state_dir: Path, unit_id: str, role: str) -> Path:
    """The directory of a unit's spec copies for one role, under the state directory."""
    return state_dir / SPEC_SNAPSHOTS / unit_id / role
