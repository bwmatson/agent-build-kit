## From `ui-review/1`

- The thread POST accepts any commit that resolves in the checkout, not only commits from this unit's branch. Consider checking that the commit is in the unit's history. Commits from before a rewrite must stay legitimate anchors.
- src/agent_build_kit/serve/server.py:270 — A thread's `commit` is accepted if it resolves to any commit in the checkout. Nothing checks that it is the unit's branch or one of its ancestors, so a sha from `main` or from another unit's branch is stored as the anchor.

## From `ui-review/2`

- web/src/api.ts:120 — `postAction` could be written on top of the new `sendJson` so that a refused write is turned into an error in one place only.
- web/src/review/tab.tsx:237 — when the locate request is refused (unknown commit, branch not in the checkout), the tab shows 'no longer in the diff'. Show the server's reason instead, and keep that note for `{line: null}`.
- web/src/review/tab.tsx:169 — disable Request changes and Approve once the current round has a recorded decision, instead of relying on the server's 409.
- src/agent_build_kit/serve/server.py:345 — `/review/locate` accepts any commit that resolves in the checkout. This is the same open point as the thread POST's ancestry check in this change's follow-ups, so settle both together.
- web/src/api.ts:120 — `sendJson` and `postAction` (api.ts:106) each build a JSON request and turn a refusal into its `detail` in their own way. `postAction` is `sendJson("POST", path, {})` followed by reading `message`.
- web/src/review/tab.tsx:237 — When the locate request fails for any reason, the tab says the line is no longer in the diff. That includes the server's 409 for a commit not in the checkout and its 409 for a branch not in the checkout.
- web/src/review/tab.tsx:169 — Request changes and Approve stay enabled after the round has a recorded decision. The second click is only stopped by the server's 409.

## From `ui-review/3`

- Comments from the host forge (as opposed to the UI) still get side 'new' by default, because the forges' `review_notes` don't say which side a comment is on. As a result, a host comment on a deleted line gets the wrong line marked. When a forge can report the side, set `ReviewNote.side` from it.

## From `ui-review/4`

- web/src/test/recorded/review-working-context.json is written by hand: its commit hash and index line are made up. It does follow the exact form of a `git diff` hunk with function context, and the real @pierre/diffs parser reads it. Recording it from a real `git diff` of a small Python file would match the folder's name and keep it honest if the parser's handling of the header changes.
