# Proposal

## Why

`changelog-setting-and-check` makes the convention and its check available to every repo,
from a packaged text, but a person reading a repo, or an agent working in it without the
pipeline's prompt, sees nothing of it. A repo with no changelog has nowhere for an entry to
go, and two units adding entries at the same place conflict on every restack unless git is
told to merge the file by union. Today `abk init` never writes into a code repo.

## What Changes

- **A marked convention block** is written into the repo's conventions file on every
  `abk init`: into `AGENTS.md` if it exists, else `CLAUDE.md` if it exists, else a new
  `AGENTS.md` (no `CLAUDE.md` is created). A re-run replaces only the marked block; a
  version stamp lets a later release update it; the rest of the file is never touched.
- **A changelog file is created** at the repo's configured path when absent, with the
  title and an Unreleased heading.
- **The union-merge rule is ensured in `.gitattributes`** for the changelog path: the file
  is created if absent, the rule appended if missing, nothing changed if it is present,
  never duplicated, no other line rewritten.
- **Repos with the setting off are skipped** entirely.
- **Init shows it first.** `--dry-run` lists, for each repo, the block, the changelog and
  the attribute it would write or leave; nothing is committed, and the files are left in
  the working tree for review.
- **Doctor warns** when a repo with the feature on has no union rule, which is a repo set up
  before this.
