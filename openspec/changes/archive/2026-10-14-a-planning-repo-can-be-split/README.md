# a-planning-repo-can-be-split

`abk planning split` moves what belongs to one repo (or one project of a repo) out of a planning repo into another installation: its active changes, archive entries, main specs, unit records and plan records. It reads the working tree, refuses what it cannot move whole, checks every cross-change edge, optionally scrubs the moved text, and by default only prints what it would do.
