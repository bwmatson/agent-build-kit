def test_old():
    assert True


def test_new():
    def test_inner():
        pass

    raise AssertionError()
