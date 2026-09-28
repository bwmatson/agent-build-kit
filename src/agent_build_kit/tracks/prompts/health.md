# Mission: health phase — project `__PROJECT__`

You are running unattended, read-only against the `__PROJECT__` repo
(`__PROJECT_DIR__`, GitHub `__PROJECT_REPO__`): __PROJECT_DESCRIPTION__
See its `CLAUDE.md` for the full picture, including which other repos it
depends on and how it is deployed. If it runs services (a Docker Compose
stack, say — conventionally the compose project is named `__PROJECT__`),
their live behavior is in scope too. Your job: a fast daily pulse check —
is something actually wrong right now in *this* project — not a thorough
audit. That's `improve.md`'s job, run weekly with its own budget. **Do not
edit any file in `__PROJECT__`, do not create a branch, do not open a
PR.** This phase only reports (it does update
`__STATE_DIR__/tracked-issues.md` in the planning repo — that's
bookkeeping, not application code).

## Scope: one project per run

The tracks run once per repo in this workspace, and every other repo gets
its own health run. The workspace:

__WORKSPACE_REPOS__

`__PROJECT__` consumes: __PROJECT_CONSUMES__.

Stay on `__PROJECT__`: its code, and its own services' behavior. Repos in
a workspace often share infrastructure — one of them may host the
observability stack (logs, traces, metrics) the others report into —
and `__PROJECT__`'s `CLAUDE.md` says where its observability lives and
what it depends on. Use that shared tooling, filtered to this project
(a log label carrying the compose project name, this project's container
and service names). A problem you notice that belongs to a *different*
repo (its container erroring, its code) isn't this run's finding —
mention it in one line under Findings as "belongs to <repo>" and move
on; that repo's own health run owns it.

## 1. Refresh the tracked-issues list

Read `__STATE_DIR__/tracked-issues.md` before anything else (create it
with empty "Pending resolution" and "Rejected" sections if it doesn't
exist yet). For each entry under "Pending resolution" — every project's,
not just this one's; it's cheap and keeps the shared file accurate —
check its PR's real state: `gh pr view <url> --json state -q .state`.

- `MERGED` → remove that entry. The fix landed; if the same problem
  shows up again in this run's findings (step 4), it's a fresh finding,
  not a duplicate.
- `CLOSED` (without merging) → move it to the "Rejected" section instead.
- `OPEN` → leave it as-is.

You'll commit these edits together with everything else at the end
(step 5) — don't commit twice.

## 2. Check whether last run's open candidates have already been resolved

Read the immediately-prior `__STATE_DIR__/*-__PROJECT__-health.md` run (if
any — skip this step on the first-ever run for this project) for
candidates still marked `[not-yet-actioned]`. For each, a quick check
(re-read the specific file/lines it named, or `git log` on them since
that run) — has this clearly already been fixed, by a human directly (an
unrelated hand-edit outside the tracks' own PR flow) or by anything
else? Not a fresh investigation, just confirming or refuting what's
already there.

If unambiguously resolved and you can identify which commit did it, mark
it directly on its line in that source file: `[actioned — commit
<short-hash>](__PROJECT_REPO_URL__/commit/<hash>)` — same mechanic
`implement.md` uses for its own PRs, but pointing at a commit instead of
a PR since this didn't go through the tracks' PR flow. If you can't
clearly tell, leave it as `[not-yet-actioned]` rather than guessing —
this is a bonus check, not a requirement to resolve everything.

## 3. Fan out

Use the `Agent` tool to run these 5 playbooks from
`__PROMPTS_DIR__/categories/health/` in parallel — the ones that can
change day to day and are worth a daily look, security included since a
leaked credential is a problem, not a "could be better":

- `logs-and-errors`
- `resource-usage`
- `llm-observability`
- `pipeline-health`
- `secrets-scan`

Tell each subagent which project this is (`__PROJECT__`, at
`__PROJECT_DIR__`), where the run logs live (`__STATE_DIR__`), and that
it's the **daily** pass: narrow any lookback window to roughly the last
24h (not the 7d/48h a category's own playbook may default to) and keep
it to a quick check of the obvious signals, not an open-ended
investigation. The goal is "does anything here look wrong today," not
exhaustive analysis. A category that has nothing to look at in this
project (e.g. no LLM call sites of its own) should say so in one line,
not go hunting elsewhere.

## 4. Cross-reference against tracked issues

For each subagent's findings, check the (now-refreshed) "Pending
resolution" and "Rejected" sections of `tracked-issues.md` for a match —
same underlying problem, not necessarily identical wording. Use your own
judgment on what counts as "the same issue": a match doesn't need
identical wording, but it should be the same root cause, not just the
same category.

- Matches "Pending resolution" → don't list it as a new actionable
  candidate. Mention it in Findings as already in flight (which PR).
- Matches "Rejected" → don't list it as a candidate either. Mention it
  was already considered and declined, if worth noting at all.
- No match → genuinely new. This is what "Actionable candidates" below
  is for.

## 5. Write the run log entry and update the tracker

Write `__RUN_LOG__` in the planning repo (`__PLANNING_DIR__`, not
`__PROJECT__`) — that exact path, not a timestamp you generate yourself;
the track runner reads this file back by that name right after this
phase exits to decide whether to run `implement.md` early for this
project, so it has to match. Shape:

```markdown
# Health __RUN_ID__ — __PROJECT__

**Status:** <one of exactly `OK`, `PENDING RESOLUTION`, `ATTENTION`, or
`URGENT`, right after the colon — a short reason after it is fine, e.g.
"URGENT — disk at 95% on the host", but that first word (or two, for
PENDING RESOLUTION) is what the track runner parses, so don't reword it>

## Findings

### <category>
<what that subagent reported, verbatim or lightly trimmed — note inline
if a given finding matches a tracked pending/rejected issue>

(repeat per category)

## Actionable candidates for the next implement run

1. [not-yet-actioned] <concrete, specific, genuinely NEW finding in
   `__PROJECT__` — not one already in "Pending resolution" or
   "Rejected" — an implement run could act on in this project's repo>
2. ...

(if everything found is either nothing, or already tracked as pending/
rejected, write "None this run" here — most days should land here; a
genuinely new problem is the exception, not the norm)
```

**Status** rules, most severe wins — for *this project* only:
- Something genuinely new and worth acting on now → `ATTENTION` or
  `URGENT` (your judgment on severity).
- Nothing new, but something for this project is still sitting in
  "Pending resolution" → `PENDING RESOLUTION`. Nothing for `implement.md`
  to do about it right now — it's already being handled.
- Nothing wrong at all (findings clean, nothing pending for this
  project) → `OK`.

Pick it honestly: don't inflate routine noise to ATTENTION just to seem
thorough, and don't downplay something that genuinely looks broken. Only
`ATTENTION`/`URGENT` make the track runner run `implement.md` immediately
after this phase — so make sure "Actionable candidates" only contains
genuinely new findings when you pick either of those, not something
already pending (that would just cost budget re-discovering something
that already has a PR out).

Commit and push both this file and your `tracked-issues.md` edits from
steps 1 and 2 together, directly to the planning repo's default branch
(the branch it's checked out on) — bookkeeping, not application code, so
neither needs its own PR. Stage only those files by path — never
`git add -A` in the planning repo.
