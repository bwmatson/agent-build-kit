# Proposal

## Why

Every unit adds an entry to the changelog, and the entry is where the same small
problems recur: two units add theirs at the same place and the restack conflicts, a
follow-up to an unreleased change is added as a second bullet beside the first instead
of folded into it, a bullet loses its blank line, a name or number that belongs to an
installation slips in. Each is found late: by a conflict at restack, which a resolver
agent settles by hand, or by a reviewer, which costs a rework round, a tier 1 run and
another review for housekeeping.

The build and rework prompts say only that an entry is needed. Nothing checks the
file's shape in tier 1.

## What Changes

- **The prompts say how.** The build, rework and restack-resolver prompts carry the
  changelog convention: one bullet per change, placed beside related ones; a follow-up
  to something unreleased edits that bullet instead of adding another; plain prose about
  behaviour and the reason; no installation names or pull-request numbers; and, on a
  conflict in the file, keep both sides and fold bullets that describe one change.
- **Tier 1 checks the file.** A check, run with the ordinary suite and the pre-commit
  gate, fails on conflict markers, a missing blank line between bullets, a duplicated
  bullet, a bullet outside a section, and the forbidden-name patterns the repo already
  has for source and docs. The agent sees the failure in its checks round, before a
  reviewer is asked.
- **Review leaves it alone.** A reviewer is told that changelog form and wording are not
  findings while the check passes; an entry that is wrong in substance (it claims
  something the code does not do) still is.
- **The merge driver stays.** The file keeps its union merge attribute, so most
  collisions never reach a resolver.
