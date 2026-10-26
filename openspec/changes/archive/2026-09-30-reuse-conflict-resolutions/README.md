# reuse-conflict-resolutions

Let git replay a conflict resolution it has already seen, so a restack asks an agent to
*confirm* a merge rather than derive it again — and leave the replayed hunks unstaged, so a
resolution recorded once cannot slip through unchecked.

The same `CHANGELOG.md` hunk was resolved by two different agents today, from scratch, in two
worktrees of one repository. Git can do that replay itself, and its cache already lives
somewhere both worktrees can see.
