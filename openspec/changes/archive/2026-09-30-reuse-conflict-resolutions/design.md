# Design

## Why the cache needs no plumbing

`rerere` keeps its recordings in `rr-cache` under the repository's *common* git directory.
Worktrees share that directory, so every unit worktree of a repo reads and writes one cache
without anything being synchronised, copied or cleaned up. Checked directly: from a unit
worktree, `git rev-parse --git-path rr-cache` gives the main checkout's `.git/rr-cache`.

That is what makes this worth doing rather than merely possible. The conflicts that repeat are
precisely the ones inside a stack — same files, same predecessor merge, several successors — and
those are all worktrees of one repository.

## Recording and replaying, without auto-staging

With `rerere.enabled` and `autoUpdate` off:

- when a conflict is resolved and the rebase continues, the resolution is recorded;
- when the same conflict appears again, the recorded resolution is written into the file, but the
  path stays unmerged and unstaged.

So the resolver still sees an unresolved path and still has to act — but the content in front of
it is a proposed merge rather than conflict markers. The saving is the derivation; the check
remains.

Auto-staging is what this deliberately gives up. With `autoUpdate` on, a recorded resolution is
staged and the rebase can complete with no agent involved at all, which is cheaper and wrong for
this pipeline: one agent's mistaken merge would silently become the answer for every later unit
hitting that hunk, with no step that looks at it. The review loop would eventually catch a
semantic error, but it would catch it once per unit, after paying for each.

## Telling the resolver what it is looking at

A file carrying a replayed resolution looks, to an agent, like a file someone else half-fixed —
no markers, still unmerged. Unexplained, that invites either blind staging or a redundant
rewrite. So the resolver's prompt says which paths arrived with a recorded resolution and asks
for a verdict on each: stage it if it is right, correct it if it is not, and say which.

That also makes rejection observable. A resolution the resolver overrides is recorded anew, so a
bad cache entry is corrected rather than argued with forever.

## Not the repository's configuration

`rerere.enabled` written into the repo config would apply to the operator's own work in that
checkout, because a worktree shares `.git/config`. The pipeline instead passes the setting on its
own git invocations, centrally, where it shells out for a restack — so the behaviour is the
pipeline's and an operator opts in separately if they want it.

One consequence to know: the *cache* is shared repo-wide regardless. An operator who enables
`rerere` locally will both benefit from the pipeline's recordings and contribute to them. That is
mostly a feature — a human's resolution teaches the pipeline — but it is worth documenting rather
than discovering.

## Scope

Conflicts during a restack's rebase, and nothing else. Not the adapt step, which re-implements a
unit rather than merging text. Not the build, review or rework steps. And no attempt to prune,
share or version the cache across repositories: a stale entry is corrected the next time an agent
overrides it.
