"""Test support: finds the lines of a test module that walk the checkout by hand."""


def hand_walks(source: str) -> list[int]:
    """The 1-based lines of a module's source that run `git ls-files`, or call `rglob` or `glob`
    on the checkout root; none when the module imports `tests.tracked_files`."""
    raise NotImplementedError
