## From `init-writes-changelog-conventions/2`

- tests/integration/test_init_conventions_workspace.py: the first run only checks that `git status --porcelain` is non-empty. Checking each repo's exact untracked set (CHANGELOG.md, .gitattributes, and AGENTS.md or CLAUDE.md as modified or new) would pin 'without touching anything else' at the acceptance tier, not only in the unit-test tests.
- The third fixture repo is called `worker`. AGENTS.md lists `app` and `platform` as the neutral repo names, so a third repo would need a name added to that list, or the fixture convention could be widened to say other neutral names are fine. The scrub check passes either way.
