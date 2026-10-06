"""The shape `CHANGELOG.md` must have, as a list of what is wrong with it."""


def changelog_problems(text: str) -> list[str]:
    """Each way `text` breaks the changelog's form, one `line N: ...` message per problem.

    Empty when the form holds: no conflict marker, a blank line between
    bullets, no bullet repeated, every bullet under a `##` heading, and the
    headings in order (unreleased first, then versions descending).
    """
    raise NotImplementedError
