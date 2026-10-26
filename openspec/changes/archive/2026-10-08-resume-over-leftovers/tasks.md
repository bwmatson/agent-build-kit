# Tasks

Acceptance: none — worktree handling and prompts inside the graph engine; tier-1 tests with a real
git repository and the real worktree setup prove it.

## 1. [agent-build-kit] [tier1] Resume over the work a killed agent left

Done when a node killed mid-agent resumes over its own uncommitted work, passes it to a new
session in the prompt and to a resumed session not at all, and a dirty tree that is not its own
parks the unit.

- [x] 1.0 Test: each agent node writes its name into the thread state before its agent starts and
      clears it when it completes; a node killed before the agent names a session, and a node on a
      runtime that names none, still leave the record behind; a node reached but not started has none.
- [x] 1.1 Test (real repository, real `prepare_worktree`, the existing killed-run helpers): a
      rework killed mid-edit with a recorded session resumes, the unit reaches review, the file
      is in the rework's commit, and the agent's prompt is the interruption prompt with no
      leftover note.
- [x] 1.2 Test: an implement node killed with no session resumes in a new session whose prompt
      names the changed paths (untracked files included, capped) as uncommitted work from an
      interrupted run, the file is still in the tree, and it is committed with the node's commit;
      the same for a recorded session the runtime cannot resume.
- [x] 1.3 Test: a rate limit and a timeout that kill an agent mid-run resume as in 1.1 and 1.2;
      a kill at a clean boundary resumes unchanged.
- [x] 1.4 Test: a dirty tree at a node that does not run an agent, an edit on a unit waiting at an
      agent node that never started, and a hand edit on a unit that was not killed, hold the unit with cause `dirty_worktree`, the paths and the request,
      do not fail it, and clean nothing; a requeue after the tree is cleaned resumes it; the
      status lists it with the reason.
- [x] 1.5 Test: the tests-first order and the approved-commit gate are unchanged by a resume over
      leftovers: a tests node's leftovers are committed as tests, and a head that changed since
      the approval is reviewed again.
- [x] 1.6 Add the `running_node` record and its writes, `allow_dirty` to the worktree setup,
      decide the node's own leftovers from the record and the branch lock, add the packaged leftover note and attach it on the new-session path, add the
      parking path and its cause, and add the log line and counter.
- [x] 1.7 Correct `docs/unit-graph.md` about carrying on from the tree, remove the stale
      mention of the old reclaim in the test comment, document the parked state in the
      `abk-pipeline` skill, and add a changelog entry.
