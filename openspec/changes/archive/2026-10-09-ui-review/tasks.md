# Tasks

Acceptance: none — the diff, store and feedback path are proved with a scratch repository, a recorded
review and a fake poller; the end-to-end run is in `local-forge`.

Priority: 5

## 1. [agent-build-kit] [tier1] The diff and review API

Needs: abk-web-ui group 2 merged — the server, the shell and the unit page this extends

Done when the server returns a unit's diff pinned to a commit and stores threads, replies, a summary
and a decision.

- [x] 1.1 Test: for a plain, a stacked and a restacked unit the diff is the unit's own work against
      the right base, and it is pinned to one resolved commit.
- [x] 1.2 Test: threads and replies are stored with their anchor, survive a restart, and are marked
      outdated and relocated when the branch moves.
- [x] 1.3 Test: the decision (request changes, approve) and the summary are stored once per round.
- [x] 1.4 Write the diff endpoint, the review store and the thread operations.

## 2. [agent-build-kit] [tier1] The review tab

Done when the review tab shows the diff with its tree, threads and decision, over a large diff.

- [x] 2.1 Test: the viewer adapter renders a recorded multi-file patch with threads on both sides,
      range selection, outdated threads and collapse, and swapping the library touches only the adapter.
- [x] 2.2 Test: a 200-file patch renders files as they scroll into view.
- [x] 2.3 Test: selecting lines highlights them without creating a thread; an address names a unit,
      a file and a range, opens scrolled to it highlighted, and follows the selection; a finding in the
      verdict highlights its line; an address for a line of an earlier commit opens at the nearest
      matching line or says the line is gone.
- [x] 2.4 Build the tab, the adapter over the chosen library, the file tree, the composer and the
      decision controls; show the reviewer's findings and follow-ups beside the diff.
- [x] 2.5 Document the tab in `docs/architecture.md` and add a changelog entry.

## 3. [agent-build-kit] [tier1] Feedback through the poller, and the hunk in the prompt

Done when UI reviews reach a unit as comments and the agent sees the hunk with every inline comment.

- [x] 3.1 Test: a new UI comment, reply and request-changes each produce one rework event as person
      feedback, are not delivered twice, and the ids cannot collide with a host's.
- [x] 3.2 Test: the agent's replies are written into the thread they answer and not read back as new
      comments; Approve records the approval and merges nothing.
- [x] 3.3 Test: a review note from a host and from the UI carries the hunk for its line, the prompt
      prints it, and a stale line prints none.
- [x] 3.4 Add the UI comment source by wrapping `forge.list_prs` in `poll_all` (`with_ui_review`), the
      replies back-write through `pr_replies`' marker, `own_posts` and `ignored`, the `ui-` thread ids, the
      hunk on `ReviewNote` and in `note_words`.
- [x] 3.5 Update `docs/architecture.md` for the poller and the prompt, and add a changelog entry.

## 4. [agent-build-kit] [tier1] Uncommitted changes and asking the agent

Needs: abk-web-ui group 8 merged — the agent tab and the attachments a turn can carry
Needs: ui-chat-editing group 1 merged — the record of uncommitted changes
Needs: ui-chat-editing group 3 merged — the spec context and the rework prompt that flags a conflict with the spec

Done when a unit's uncommitted changes are shown apart from its commits and a selection can be sent to
the unit's agent as context.

- [x] 4.1 Test: uncommitted changes from a chat appear as their own section marked uncommitted, accept a
      highlight, and refuse a comment with the reason.
- [x] 4.2 Test: choosing to ask the agent about a selection opens the unit's agent tab with one chip
      holding the file, lines, hunk and text, and sending it puts them in the turn's prompt.
- [x] 4.3 Test: a selection that spans uncommitted lines attaches them with the marker that they are
      uncommitted.
- [x] 4.4 Test: a comment made in the review tab that contradicts a requirement of the unit's change is
      answered in its thread with the flag the rework prompt asks for, and the code is not changed for it.
- [x] 4.5 Add the working-changes section, the action on a selection and the hand-off to the agent tab.
- [x] 4.6 Document both in `docs/architecture.md` and add a changelog entry.
