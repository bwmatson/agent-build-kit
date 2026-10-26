# resume-over-leftovers

A node killed partway through an agent run resumes over the uncommitted work its agent left,
instead of failing on a dirty-worktree guard. A resumed session already knows its changes; a new
session is told about them; work that is not the node's own parks the unit instead of failing it.
