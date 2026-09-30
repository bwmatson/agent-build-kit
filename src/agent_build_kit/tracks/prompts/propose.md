# Mission: propose phase — project `__PROJECT__`

You are running unattended in the planning repo (`__PLANNING_DIR__`), with
`__PROJECT__`'s checkout (`__PROJECT_DIR__`, `__PROJECT_REPO__`) readable
beside you: __PROJECT_DESCRIPTION__ This phase runs weekly, right after
`improve.md` and (a different day) after `recommend.md`, and also on-demand
right after a non-OK `health.md` result or when triggered standalone.

**Turn already-identified findings into one OpenSpec change that the pipeline
will build.** You do not edit `__PROJECT__`'s code, open a pull request, or
touch its branches. The pipeline turns a change's task groups into branches and
pull requests itself, with a build and review loop around each one; work written
here by hand goes around all of that, and the pipeline would later find it
already done.

## Scope: this project's repo only

The tracks run once per repo in this workspace, and every other repo
gets its own propose run. The workspace:

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
tracker could be stale (e.g. a change was built and merged since the last
scheduled run). For each "Pending resolution" entry (every project's), check
where its change has got to:

- A directory ending `-<change>` under `__PLANNING_DIR__/openspec/changes/archive/`
  → the pipeline built it and it merged. Remove that entry. The fix landed; if
  the same problem shows up again in this run's findings (step 4), it's a
  fresh finding, not a duplicate.
- Still at `__PLANNING_DIR__/openspec/changes/<change>/` → it's in flight.
  Leave it as-is.
- Neither → it was rejected or dropped. Move it to the "Rejected" section.

An older entry names a pull request URL instead, from before tracks wrote
changes. Check those with `gh pr view <url> --json state -q .state`: `MERGED`
→ remove, `CLOSED` (without merging) → "Rejected", `OPEN` → leave.

The pipeline commits these edits with everything else you write in the planning repo.

## 1. Find something to act on

Focus for this run: __FOCUS_HINT__

Read the recent entries for this project under `__STATE_DIR__/` —
`*-__PROJECT__-health.md`, `*-__PROJECT__-improve.md`, and
`*-__PROJECT__-recommend.md` all carry an "Actionable candidates" section
in the same shape — most recent first (weighted toward the focus above,
if one was given). Note: most recommend entries will have none — that
phase mostly produces human-facing recommendations, not bounded fixes,
by design. Skip anything already marked `[proposed — <change>]` or `[actioned — …]` on its own
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

Then choose up to __MAX_ISSUES__ **distinct issues** (not __MAX_ISSUES__
candidates that happen to fall into however many issues they land in) — one
task group per issue, each meeting these bars:

- **Well-evidenced and independently mergeable** — the finding cites
  something concrete (not a vague "could be better"), and one group doesn't
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

## 2. Write one change for what you chose

Write it under `__PLANNING_DIR__/openspec/changes/__PROPOSED_CHANGE__/`, as
the OpenSpec schema and this workspace's rules
(`__PLANNING_DIR__/openspec/config.yaml`) define it: `proposal.md`,
`specs/<capability>/spec.md`, `design.md` where the work warrants one, and
`tasks.md`.

`tasks.md` is the only file the pipeline reads about a change, so it carries
the contract:

```
## <n>. [__PROJECT__] [tier1] <title>

- [ ] <n>.1 Test: <the failing test that states the finding>
- [ ] <n>.2 <the change that makes it pass>
```

- Every group heading names the repo exactly as `abk.yaml` spells it and the
  tier it needs; `tier1` is the ordinary suite, `tier2` needs the real local
  stack.
- Test tasks come before implementation tasks — a unit's first commit is its
  failing tests.
- A group never spans repos. A finding whose fix needs another repo is not
  yours: leave it, and say so in the log.
- Every change has an `[acceptance]` group or a line saying why it has none.
- One group per issue you chose, in the order they should be built.

Ground every group in the finding that produced it: the proposal says *why*
this change exists and which run found it, and a task names the file or the
behaviour it is about rather than describing work in general.

Then check your own work before you finish:

```
abk check          # the OpenSpec artifacts
abk tags __PROPOSED_CHANGE__   # the heading contract above
```

Both must pass. A change that does not validate is worse than no change: the
pipeline will read it, fail to plan it, and report that a tick later with
nobody present.

## 3. Track it

Add an entry under `__STATE_DIR__/tracked-issues.md`'s "Pending resolution"
section for each issue the change covers (short id, project: `__PROJECT__`,
one-line summary, which run first found it, the change name
`__PROPOSED_CHANGE__`, and this run's id as "opened by"). This is what lets
`health.md`/`improve.md`/`recommend.md` recognise the same problem next time
and not propose it again while the change is still in flight — skipping it
breaks that.

Also go back and edit the source run-log entry's own list item — the one
exception to `__STATE_DIR__` being append-only for anything other than
`tracked-issues.md`, and deliberately narrow: change only that one candidate's
`[not-yet-actioned]` marker to `[proposed — __PROPOSED_CHANGE__]`, leaving the
rest of the line untouched. This is what makes the original entry
self-documenting.

## 4. If you get stuck

If a finding turns out riskier than it looked — not "bigger than expected" on
its own (that's fine per step 1's framing), but genuinely unclear intended
behaviour, or a design decision hiding inside what looked like a fix — leave it
out of the change rather than writing task groups that guess. Say so in the
log: a human deciding "not worth it yet" is a fine outcome, and a change built
on a guess spends a whole unit discovering that.

If nothing survives, write no change at all and say so. An empty change
directory left behind is a change the pipeline will try to plan.

## 5. Write the run log entry

Write `__RUN_LOG__` in the planning repo (`__PLANNING_DIR__`) — that
exact path, not a timestamp you generate yourself — covering: the issues
you identified and which candidate you picked for each (and why it beat
other candidates on the same issue, if any), the change you wrote and the task
groups in it (or why you wrote none), and any candidate you skipped because it
belongs to another repo or needs a multi-repo change. The pipeline commits and pushes what you write in the planning repo (this file, your `tracked-issues.md` edits and any source run-log marker edits) — don't run git there, and leave its branch as it is.
