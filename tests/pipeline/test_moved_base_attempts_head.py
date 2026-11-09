"""Only the count decides for the lane whether attempts are spent; the pushed head does not
(spec: unit-scheduling)."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("scripted_engine")
