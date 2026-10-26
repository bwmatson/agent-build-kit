# Design

## The step

`write_code_repo_conventions(workspace)` beside `write_planning_repo`, called by
`abk init` for every repo the workspace file lists and whose checkout exists. Each of the
three actions returns a result (`created`, `updated`, `unchanged`, `skipped`) so the
planned-work lines and a second run's "nothing to do" come from the same code.

## The block

```
<!-- abk:changelog v1 -->
## Changelog
…the packaged convention text…
<!-- /abk:changelog -->
```

The version in the opening marker is the stamp. On a run: no block → append at the end of
the file (after a blank line); a block with the current stamp and equal body → unchanged;
a block with an older stamp or a different body → replace the text between the markers.
Text outside the markers is never read or changed. If the repo already has its own
`## Changelog` section outside the markers, no block is written (the repo's own wins, as
the loader treats it). Line endings follow the file's existing ones.

## The file

The configured changelog path: created with `# Changelog`, a blank line and `##
Unreleased` if absent; an existing file is never edited.

## `.gitattributes`

The rule is `<path> merge=union`. Parsing is line-based: an existing line for that exact
path with `merge=union` (or `merge=` anything, which is left alone and reported as a
conflict, not rewritten) counts as present. Absent file: created with the rule. Present
file without the rule: the rule appended on its own line (a newline added first if the
file lacks a final one). No other line is changed.

## Dry run

`_planned_work` gains one line per repo and action: "write convention block to
`<repo>/AGENTS.md`", "create `<repo>/CHANGELOG.md`", "add union merge rule to
`<repo>/.gitattributes`", or "leave … (already current)". Nothing is written or committed.

## Doctor

`abk doctor` checks the rule per repo with the feature on and warns, naming the repo and
the fix (`abk init`).

## Risks

Init now edits other repos' tracked files on every run. The block is delimited, the files
are left uncommitted, `--dry-run` shows it, and a repo can opt out. A file that has the
markers mismatched (an opening without a closing marker) is reported and left untouched.

## Out of scope

The setting, the text and the check (`changelog-setting-and-check`), committing the
result.
