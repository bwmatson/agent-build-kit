import pytest


def test_old():
    assert True


@pytest.fixture
def test_repo():
    return 1


def test_new():
    assert False
