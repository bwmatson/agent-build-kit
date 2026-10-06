"""What an agent is told about the changelog, in the words AGENTS.md carries.

The text is the body of the `## Changelog` section of the repository's
AGENTS.md, and a test keeps the two equal. It holds no braces: it is placed in
prompts that are format strings.
"""

CHANGELOG_CONVENTION = """\
`CHANGELOG.md` opens with a `## Unreleased` section, and released versions follow it,
newest first. A pull request that changes what someone using the tool sees adds one
bullet under Unreleased, written for that person: what changed and why, in plain words,
wrapped with a two-space continuation. Bullets are separated by one blank line, never
run together, never repeated, and never outside a `##` section. Add your bullet and
leave the others as they are, and never leave a conflict marker in the file. One change
is one bullet, even across several pull requests: fold later work into the bullet that
already describes it instead of adding another.
"""

CHANGELOG_NOTE = "\nThe changelog convention:\n\n" + CHANGELOG_CONVENTION
