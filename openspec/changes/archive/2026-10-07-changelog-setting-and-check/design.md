# Design

## Setting

`RepoConfig.changelog: str | None = "CHANGELOG.md"`; `None` (`changelog: null`) is off.
Documented in `docs/configuration.md` and the `abk-config` skill; `abk doctor` warns when
the path is set but the file is absent in the checkout.

## Convention text

Package data `templates/changelog-convention.md`: generic wording, one bullet per change,
where it goes, follow-ups edit the unreleased bullet, shape, content, what never appears
(an installation's names, PR or issue numbers, dated stories), and the union-merge note.
`changelog_convention(worktree, repo)` returns, in order: the repo's own `## Changelog`
section from `AGENTS.md`, else from `CLAUDE.md`; else the packaged text if the setting is
on; else empty. The call sites pass the repo's config (a worktree-to-repo lookup already
exists for forge and profile).

## Check

`changelog_problems(text)` moves from `tests/` into the package; `abk changelog check
[PATH]` prints each problem as `path line N: message` and exits non-zero when there are
any (zero with a one-line note when the file is absent and the setting is on, so a repo
that has not run init does not fail tier 1). The command takes the path from the repo's
setting when no PATH is given.

## Tier 1

The toolchain profile gains an `extra_checks(repo)` hook returning additional tier 1
commands; the Python profile returns `abk changelog check` when the repo's setting is on,
run in the worktree beside the existing lint and test commands, so its output and its
failure feed the same checks-before-review loop. Other profiles get the hook with an
empty default.

## Prompts

`{changelog}` and the resolver rule and review paragraph use the loader above; their
wording is unchanged. They are empty when the setting is off.

## This repo

`tests/test_changelog.py` calls the packaged function over fixtures and over this repo's
file; a test asserts this repo's own section equals the packaged text or that its heading
carries an explicit override marker.

## Out of scope

Writing into a repo (the init change), fragment files per entry.
