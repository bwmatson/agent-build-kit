# Mission: recommend phase — project `__PROJECT__`

You are running unattended, read-only against the `__PROJECT__` repo
(`__PROJECT_DIR__`, GitHub `__PROJECT_REPO__`): __PROJECT_DESCRIPTION__
See its `CLAUDE.md` for the full picture. Your job: surface genuinely
bigger-picture "how could this project be better" findings — test
coverage gaps, technical debt, architecture opportunities,
cost/performance waste — that `health.md` (daily, "is something broken")
and `improve.md` (weekly, "concrete rule violations") don't cover by
design. **Do not edit any file in `__PROJECT__`, do not create a branch,
do not open a PR.** This phase only reports.

Most findings here are **recommendations for a human to read and decide
on**, not things `propose.md` should act on unattended — "add tests to
8 services" or "restructure X" isn't a bounded fix. Don't force
everything into "actionable" just because that's how `health.md`/
`improve.md` work; a clear-eyed "here's what I found, here's why it
matters, it's not a quick fix" is a complete, valuable answer on its own.

## Scope: one project per run

The tracks run once per repo in this workspace; every other repo gets
its own recommend run. The workspace:

__WORKSPACE_REPOS__

`__PROJECT__` consumes: __PROJECT_CONSUMES__.

Recommend about `__PROJECT__`. Its boundary with the repos it consumes or
is consumed by (see its `CLAUDE.md`) *is* fair game for architecture
findings when the evidence is on `__PROJECT__`'s side of it; the other
repo's internals are not.

## 1. Refresh the tracked-issues list

Read `__STATE_DIR__/tracked-issues.md` before anything else (create it
with empty "Pending resolution" and "Rejected" sections if it doesn't
exist yet), same as `health.md`/`improve.md` do — for each "Pending
resolution" entry (every project's), check where its change has got to: a
directory ending `-<change>` under `__PLANNING_DIR__/openspec/changes/archive/`
→ it merged, remove the entry; still at
`__PLANNING_DIR__/openspec/changes/<change>/` → in flight, leave it; neither →
rejected or dropped, move it to "Rejected." (An older entry that names a PR URL
instead: `gh pr view <url> --json state -q .state`, `MERGED` → remove, `CLOSED`
→ "Rejected.") The pipeline commits these edits with everything else you write in the planning repo.

## 2. Check whether last run's open candidates have already been resolved

Read the immediately-prior `__STATE_DIR__/*-__PROJECT__-recommend.md` run
(if any — skip this step on the first-ever run for this project) for
candidates still marked `[not-yet-actioned]` under "Actionable
candidates" (recommendations in the main body aren't tracked this way —
only the bounded-candidate list is). For each, a quick check (re-read the
specific file/lines it named, or `git log` on them since that run) — has
this clearly already been fixed, by a human directly (an unrelated
hand-edit outside the tracks' own PR flow) or by anything else? Not a
fresh investigation, just confirming or refuting what's already there.

If unambiguously resolved and you can identify which commit did it, mark
it directly on its line in that source file: `[actioned — commit
<short-hash>](__PROJECT_REPO_URL__/commit/<hash>)` — same mechanic
`propose.md` uses to mark what it wrote up as a change, but pointing at a
commit instead, since this was resolved outside the pipeline. If you can't
clearly tell, leave it as `[not-yet-actioned]` rather than guessing —
this is a bonus check, not a requirement to resolve everything.

## 3. Fan out

Use the `Agent` tool to run these 5 playbooks from
`__PROMPTS_DIR__/categories/recommend/` in parallel:

- `test-coverage-gaps`
- `technical-debt`
- `module-design`
- `architecture-opportunities` — the one with real web access
  (`WebSearch`/`WebFetch`); it rotates through its research topics, one
  per run for this project, per its own playbook
- `cost-performance-opportunities`

Tell each subagent which project this is (`__PROJECT__`, at
`__PROJECT_DIR__`) and where the run logs live (`__STATE_DIR__`). Each
one's own playbook explains what "good evidence" looks like for that
category — the common thread across all four is: concrete evidence over
general opinions, and be honest when something is a real recommendation
but not a bounded fix.

## 4. Cross-reference against tracked issues

Same rule as `health.md`/`improve.md`: check the (now-refreshed) "Pending
resolution" and "Rejected" sections of `tracked-issues.md` before listing
anything as an actionable candidate — same underlying problem by your own
judgment, not exact-text matching. A recommendation that isn't bounded
enough to be a candidate at all doesn't need this check (it was never
going to be a candidate either way) — this only matters for the rare
finding that IS small enough to implement.

## 5. Write the run log entry and update the tracker

Write `__RUN_LOG__` in the planning repo (`__PLANNING_DIR__`, not
`__PROJECT__`) — that exact path, not a timestamp you generate yourself.
Shape:

```markdown
# Recommend __RUN_ID__ — __PROJECT__

## Recommendations

### <category>
<the prioritized, evidence-backed findings that category's playbook
asks for — this is the bulk of the value of this run, don't compress it
into a one-liner>

(repeat per category)

## Actionable candidates for the next propose run

1. [not-yet-actioned] <only genuinely small, bounded findings in
   `__PROJECT__` from any category above — most runs should have few or
   none of these; that's expected, this phase's real output is the
   Recommendations section above, not this list>
2. ...

(if nothing is bounded enough, write "None this run" — expected far more
often than not for this phase)
```

The pipeline commits and pushes what you write in the planning repo (this file and your `tracked-issues.md` edits) — don't run git there, and leave its branch as it is.
