"""The guard that a test carrying the `integration` selector can run in CI (spec: marker-taxonomy).

`check_tests` returns one message per problem: a test with the selector (on the test, its class
or the module) that loads a settings model with a required field it gives no override for, reads
an environment variable with no default, starts a real agent or calls a host other than
loopback, when the baseline does not name it; and a baseline entry that no longer is one.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

TESTS_ROOT = Path(__file__).parent
BASELINE_FILE = TESTS_ROOT / "ci_runnable_baseline.txt"


def load_baseline(path: Path = BASELINE_FILE) -> frozenset[str]:
    """The violators of today, as `path::test` entries under the tests root."""
    raise NotImplementedError


def required_settings_fields() -> Mapping[str, frozenset[str]]:
    """The required field names of each settings model of the kit, by class name."""
    raise NotImplementedError


def check_tests(
    root: Path = TESTS_ROOT,
    *,
    baseline: frozenset[str],
    required_fields: Mapping[str, frozenset[str]],
) -> list[str]:
    """One message per problem in the test modules under `root`."""
    raise NotImplementedError
