# Design

## Diff

The server runs `git diff` between the unit's base and branch, with the base chosen as the pipeline
chooses it (the open dependency's branch, or the trunk) and, for a stacked or restacked branch, from
the point where the unit's own work starts. The branch is resolved to a commit once and the diff and
every thread are pinned to it. A thread whose commit is no longer the branch tip is shown as outdated
and its line is relocated where the lines still match.

## Component

A diff component library renders the patch: `@pierre/diffs` is the first choice (Apache-2.0,
unified-diff input, line annotations and selection for threads, virtualised for large diffs, a worker
for highlighting, dark mode), with `@git-diff-view/react` as the fallback. The UI wraps either in a
thin viewer and annotation adapter so replacing it touches one module. The file tree is built from the
parsed file list. A diff of 200 files and several thousand lines is prototyped first. Review verdict and
draft state stay in the pipeline's own store, not in the component.

## Review store

Threads, replies, the summary and the decision are kept per unit in a file in the state directory.
Each thread has an id, a path, a side, a line or range, the commit it anchors to, a body, replies and a
resolved flag.

## Feedback

`forge.list_prs` is wrapped by the UI-review source (`with_ui_review`, applied in `poll_all`), so the
poller sees UI comments as host comments: new thread and reply ids are new comments, a Request changes
is a changes-requested decision, and Approve records the approval without merging. The ids carry the
store's `ui-` prefix so they cannot collide with a host's. Replies the agent posts are written back into
the thread, reusing `pr_replies`' marker, `own_posts` and `ignored` so they are not read back as new
comments. Everything after that — rework, seen state, replies kept until posted, the marker on the
agent's own posts — is the existing path.

## Hunk in the prompt

A review note gains the diff hunk for its line when the diff has one: the hunk is a field of
`ReviewNote`, rendered by `note_words` under the `path:line — body` line, which is the one place every
note is turned into prompt text. A comment on a line the diff no longer contains keeps the
existing stale handling.
