class Base:
    def test_shared(self):
        raise AssertionError()


class TestA(Base):
    pass
