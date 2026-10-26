# Tasks

Acceptance: none — a setting, a packaged text and command, and prompt wiring inside the
pipeline; tier-1 tests over fixture repos prove it. The end-to-end run is the acceptance
group of `init-writes-changelog-conventions`.

## 1. [agent-build-kit] [tier1] The changelog convention and check for any repo

Done when a repo with the setting on gets the convention in its prompts and the check in
tier 1, from its own section or the packaged text, and a repo with it off gets neither.

- [x] 1.1 Test: `changelog: <path>` and `changelog: null` load; the default is
      `CHANGELOG.md`; doctor warns on a set path whose file is absent.
- [x] 1.2 Test: `changelog_convention` returns the repo's `AGENTS.md` section, else its
      `CLAUDE.md` section, else the packaged text when on, else empty; fixture repos
      cover each, and the packaged text names no installation.
- [x] 1.3 Test: the build, rework, test-writing, resolver and review prompts carry
      their changelog parts for a repo with no section of its own and none for a repo with
      it off.
- [x] 1.4 Test: `abk changelog check` reports each problem with path and line, exits
      non-zero on one, exits zero on a well-formed file and on an absent file with a note,
      and takes the path from the repo's setting.
- [x] 1.5 Test: the Python profile's extra checks include the command when the setting is
      on and nothing when off, and tier 1 fails the checks round on a problem.
- [x] 1.6 Add the setting, the packaged text, the loader with its repo argument, move the
      checker into the package and add the command, add the profile hook, and re-point the
      prompts.
- [x] 1.7 Make this repo's own test call the packaged check and assert its section equals
      the packaged text or carries the override marker.
- [x] 1.8 Document the setting, the command and the loader's order in
      `docs/configuration.md`, the `abk-config` skill and `docs/architecture.md`, and add a
      changelog entry.
