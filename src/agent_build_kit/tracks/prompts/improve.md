# Mission: improve phase — project `__PROJECT__`

You are running unattended, read-only against the `__PROJECT__` repo
(`__PROJECT_DIR__`, GitHub `__PROJECT_REPO__`): __PROJECT_DESCRIPTION__
See its `CLAUDE.md` for the full picture. Your job: find concrete "this
could be better" findings — code quality, drift from documented
conventions, staleness — as opposed to `health.md`'s "is something
actually broken" findings (a separate, daily phase). **Do not edit any
file in `__PROJECT__`, do not create a branch, do not open a PR.** That's
`implement.md`'s job, run afterward with its own budget. This phase does
update `__STATE_DIR__/tracked-issues.md` in the planning repo — that's
bookkeeping, not application code.

## Scope: one project per run

The tracks run once per repo in this workspace; every other repo gets
its own improve run. The workspace:

__WORKSPACE_REPOS__

`__PROJECT__` consumes: __PROJECT_CONSUMES__.

Scan `__PROJECT__`'s code only, and judge it by *its own* `CLAUDE.md`
conventions and tooling config — repos in a workspace differ (their own
pre-commit scope, their own workspace members, their own documented
rules). Where `__PROJECT__` consumes another repo (a shared package or a
service it hosts, per its `CLAUDE.md`), a finding about how
`__PROJECT__` *uses* it is in scope; a finding about the other repo's
own code is not — note it in one line as "belongs to <repo>" and move on.

## 1. Refresh the tracked-issues list

Read `__STATE_DIR__/tracked-issues.md` before anything else (create it
with empty "Pending resolution" and "Rejected" sections if it doesn't
exist yet). For each entry under "Pending resolution" (every project's),
check its PR's real state: `gh pr view <url> --json state -q .state`.

- `MERGED` → remove that entry. The fix landed; if the same problem
  shows up again in this run's findings (step 4), it's a fresh finding,
  not a duplicate.
- `CLOSED` (without merging) → move it to the "Rejected" section instead.
- `OPEN` → leave it as-is.

The pipeline commits these edits with everything else you write in the planning repo.

## 2. Check whether last run's open candidates have already been resolved

Read the immediately-prior `__STATE_DIR__/*-__PROJECT__-improve.md` run
(if any — skip this step on the first-ever run for this project) for
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

Use the `Agent` tool to run these 4 playbooks from
`__PROMPTS_DIR__/categories/improve/` in parallel — the ones that don't
change hour to hour, hence weekly rather than daily:

- `lint-and-types`
- `dependency-staleness`
- `readme-drift`
- `convention-adherence`

Tell each subagent which project this is (`__PROJECT__`, at
`__PROJECT_DIR__`) and where the run logs live (`__STATE_DIR__`). Each
should report back concrete findings (not vague observations) —
file/service, what's wrong, and a rough sense of fix size — or plainly
state it found nothing.

## 4. Cross-reference against tracked issues

For each subagent's findings, check the (now-refreshed) "Pending
resolution" and "Rejected" sections of `tracked-issues.md` for a match —
same underlying problem, not necessarily identical wording. Use your own
judgment: a match doesn't need identical wording, but it should be the
same root cause, not just the same category.

- Matches "Pending resolution" → don't list it as a new actionable
  candidate. Mention it in Findings as already in flight (which PR).
- Matches "Rejected" → don't list it as a candidate either. Mention it
  was already considered and declined, if worth noting at all.
- No match → genuinely new. This is what "Actionable candidates" below
  is for.

## 5. Write the run log entry and update the tracker

Write `__RUN_LOG__` in the planning repo (`__PLANNING_DIR__`, not
`__PROJECT__`) — that exact path, not a timestamp you generate yourself.
Shape:

```markdown
# Improve __RUN_ID__ — __PROJECT__

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
rejected, write "None this run" here rather than manufacturing a
candidate)
```

The pipeline commits and pushes what you write in the planning repo (this file and your `tracked-issues.md` edits) — don't run git there, and leave its branch as it is. If you run out of budget before
finishing every category, write the log entry anyway with whatever you
have, and say explicitly which categories didn't finish.
