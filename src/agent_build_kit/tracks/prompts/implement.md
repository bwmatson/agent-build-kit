# Mission: implement phase — project `__PROJECT__`

You are running unattended, inside a fresh git worktree of `__PROJECT__`
(`__PROJECT_DIR__`, GitHub `__PROJECT_REPO__`): __PROJECT_DESCRIPTION__
This phase runs weekly, right after `improve.md` and (a different day)
after `recommend.md`, and also on-demand right after a non-OK
`health.md` result or when triggered standalone: turn already-identified
findings into reviewable PRs against `__PROJECT_REPO__`. Never merge
anything yourself.

## Scope: this project's repo only

The tracks run once per repo in this workspace, and every other repo
gets its own implement run. The workspace:

__WORKSPACE_REPOS__

`__PROJECT__` consumes: __PROJECT_CONSUMES__.

**Only act on candidates whose fix lives entirely in `__PROJECT__`'s
repo.** A candidate from another repo's run is that repo's to act on —
skip it. A candidate whose correct fix needs coordinated changes in more
than one repo (e.g. a wire-model or contract change between
`__PROJECT__` and a repo it consumes or is consumed by, per the contract
sections of their `CLAUDE.md`s) is never a single-repo PR: leave it, and
say so in your log entry — a human sequences those.

## 0. Refresh the tracked-issues list

Read `__STATE_DIR__/tracked-issues.md` before anything else (create it
with empty "Pending resolution" and "Rejected" sections if it doesn't
exist yet) — same refresh `health.md`/`improve.md`/`recommend.md`
already do, but don't skip it here even though one of them may have just
run: this phase can also be triggered standalone, on-demand, when the
tracker could be stale (e.g. you merged a PR by hand since the last
scheduled run). For each "Pending resolution" entry (every project's),
check its PR's real state: `gh pr view <url> --json state -q .state`.

- `MERGED` → remove that entry.
- `CLOSED` (without merging) → move it to the "Rejected" section instead.
- `OPEN` → leave it as-is.

Commit these edits together with everything else at the end (step 5).

## 1. Find something to act on

Focus for this run: __FOCUS_HINT__

Read the recent entries for this project under `__STATE_DIR__/` —
`*-__PROJECT__-health.md`, `*-__PROJECT__-improve.md`, and
`*-__PROJECT__-recommend.md` all carry an "Actionable candidates" section
in the same shape — most recent first (weighted toward the focus above,
if one was given). Note: most recommend entries will have none — that
phase mostly produces human-facing recommendations, not bounded fixes,
by design. Skip anything already marked `[actioned — PR #N]` on its own
line (see step 3 — this is the direct, reliable signal). Also skip
anything in `tracked-issues.md`'s "Pending resolution" (just refreshed
in step 0) or "Rejected."

Two different things, don't conflate them: don't go *looking* for
already-resolved candidates beyond what you're already reading for step
1's own purpose (finding something to act on) — that's the "don't dig"
part. But if evaluating a candidate *as part of that normal process*
leads you to conclude it's already been resolved outside the tracks' PR
flow (a human's direct hand-edit, or anything else not from a PR a track
opened) — not a maybe, a clear conclusion you've already reached —
marking it is not optional. You already did the work to know; the only
thing left is writing it down. Mark it right there the same way step 3
marks your own PRs, but with a commit instead:
`[actioned — commit <short-hash>](__PROJECT_REPO_URL__/commit/<hash>)`.

Group what's left by **issue** — the specific underlying problem or
improvement a candidate actually addresses, not which service the code
happens to live in and not which category originally found it. An issue
can span multiple services within this repo: "SSRF protection" could
touch fetch call sites in more than one service. What makes two
candidates the same issue is that they resolve or improve the same
specific thing, not that they're in the same file or subsystem — two
candidates in the same single file can just as easily be different
issues (a lint fix and a missing test in that file have nothing in
common). Within an issue that has more than one candidate, pick only the
single highest-value one — the goal is breadth across genuinely
different issues, not thoroughness within one. "Highest-value": a
security gap or an active bug generally outweighs a style/convention
fix, all else equal, but use judgment — this isn't a strict ranking.

Then choose up to __IMPLEMENT_MAX_PRS__ **distinct issues** (not
__IMPLEMENT_MAX_PRS__ candidates that happen to fall into however many
issues they land in) — one PR per issue, each meeting these bars:

- **Well-evidenced and independently mergeable** — the finding cites
  something concrete (not a vague "could be better"), and one PR doesn't
  depend on another (in this repo or any other).
- **Bounded blast radius, not bounded diff size.** Diff size isn't the
  bar — a mechanical multi-file rename can be safer than a one-line
  change to the wrong thing. Judge each candidate on: how easily could
  this be reverted if wrong (one file/one `git revert` vs. a rebuild +
  restart of shared stateful infra), and is there really only one
  reasonable way to do it (vs. a design decision with multiple
  defensible answers, which belongs to a human). A config-only change to
  a single service — even one other services depend on — is fair game
  if it's easily revertible and the finding already has hard evidence
  (logs, a documented recommendation, a confirmed root cause): e.g. a
  wrong env var on one service, evidenced by specific log lines, with a
  one-line fix. Still stays a recommendation, not a candidate: anything
  touching a rebuild or restart of genuinely stateful shared infra (a
  database instance is the standing example), anything that changes an
  interface another repo consumes (see the project's `CLAUDE.md`), and
  anything that's actually a design decision, not a fix.
- Genuinely worth a human's review time, not noise.

If there's nothing actionable for this project — every candidate already
actioned, belonging elsewhere, or the log has none — that's a valid
outcome. Write the log entry (step 5) saying so and stop. Don't
manufacture work to justify the run.

## 2. Implement each chosen candidate

For each, on its own branch:
- Make the smallest correct fix for what the finding actually is —
  "smallest correct" is about not overreaching past the finding, not
  about capping how big the finding itself is allowed to be (see the
  blast-radius framing above). Follow existing patterns in the file/
  service you're touching — don't introduce new abstractions the codebase
  doesn't already use.
- **Ship a unit test with the change.** If it touches a workflow that
  spans multiple components, add an integration test too, following
  whatever integration-test convention this project already has (its
  `CLAUDE.md`/READMEs/test config say — e.g. a marker for tests that
  need a live stack).
- Run the project's pre-commit hooks and the relevant package's test
  command (its `CLAUDE.md` says what they are — e.g. `pre-commit run
  --all-files` and `uv run pytest`, or its integration variant) before
  considering the change done. Zero lint/type violations, tests passing
  — non-negotiable.
- If the change touches a service's exposed API, outbound calls, or core
  logic flow, update that service's `README.md` in the same change (when
  the project's `CLAUDE.md` documents that convention — most do).

## 3. Open the PR and track it

`gh pr create` against `__PROJECT_REPO__` for each finished candidate,
with a description that states the *finding* (why this change exists,
and which run — health, improve, or recommend — it came from) before the
diff summary. Never `gh pr merge` — that tool is not available to you for
a reason.

For each PR you open, add an entry under
`__STATE_DIR__/tracked-issues.md`'s "Pending resolution" section (short
id, project: `__PROJECT__`, one-line summary, which run first found it,
the PR URL, and this run's id as "opened by"). This is what lets
`health.md`/`improve.md`/`recommend.md` recognize the same problem next
time and not propose it again while your PR is still open — skipping it
breaks that.

Also go back and edit the source run-log entry's own list item — the
one exception to `__STATE_DIR__` being append-only for anything other
than `tracked-issues.md`, and deliberately narrow: change only that one
candidate's `[not-yet-actioned]` marker to
`[actioned — PR #N](<PR URL>)`, leaving the rest of the line (the
finding text) untouched. This is what makes the original `health`/
`improve`/`recommend` entry self-documenting — a human (or a future run)
can see what happened to a candidate right there, without cross-
referencing every later `implement.md` entry to piece it together.

## 4. If you get stuck

If a fix turns out riskier than the finding suggested — not "bigger than
expected" on its own (that's fine per step 1's framing), but genuinely
unclear intended behavior, or a design decision hiding inside what
looked like a fix — stop rather than pushing something half-right. Write
that in the log instead of a PR — a human deciding "not worth it yet" is
a fine outcome; a rushed PR is not. Move on to the next candidate (if
any) rather than letting one stuck candidate block the rest.

## 5. Write the run log entry

Write `__RUN_LOG__` in the planning repo (`__PLANNING_DIR__`) — that
exact path, not a timestamp you generate yourself — covering: the issues
you identified and which candidate you picked for each (and why it beat
other candidates on the same issue, if any), what you did, the PR
link(s) (or why you stopped without one), and any candidate you skipped
because it belongs to another repo or needs a multi-repo change. Commit
and push this file together with your `tracked-issues.md` edits from
steps 0 and 3, and any source run-log marker edits from steps 1 and 3,
all in one commit, directly to the planning repo's default branch (the
branch it's checked out on) — bookkeeping, not application code, so
none of it needs its own PR. Stage only those files by path — never
`git add -A` in the planning repo.
