"""One test per kind the kit's default run tells apart."""

import pytest


def test_plain():
    pass


@pytest.mark.integration
def test_integration():
    pass


@pytest.mark.e2e
def test_e2e():
    pass
