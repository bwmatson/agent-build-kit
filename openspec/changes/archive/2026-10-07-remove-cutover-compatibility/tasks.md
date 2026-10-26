# Tasks

Acceptance: none — deletion of dead code; the suite passing without it, and a tick loading the
live store, prove it.

## 1. [agent-build-kit] [tier1] Remove the unit-graph cutover bridge

Needs: status-not-wording group 1 merged — both groups edit the unit store, the tick and the status command

Done when no code converts units from the old engine, the store rejects the old fields with a
clear error, and nothing in the framework or its documents refers to the conversion.

- [x] 1.1 Check that every unit in `in_review`, `running` or `held` in the live unit store has a
      thread in the thread database; if one does not, stop and report which (it must be
      requeued first). Record the result in the design.
- [x] 1.2 Test: a units store with `review_rounds`, `deferred`, `pending_replies`,
      `person_comments` or `resume_from` on a unit fails to load with one error naming the unit
      and the field; a current store loads.
- [x] 1.3 Test: a tick performs no conversion and logs no "moved onto a thread" line; no module
      imports the conversion module; the unit store has no `resume_from` or `classic_run`.
- [x] 1.4 Delete the conversion module and its call, the two fields and their loader and carry,
      `clear_converted`, the stale comment, the documents' conversion sections and the tests that
      exist only for them.
- [x] 1.5 Add a `Breaking:` changelog entry saying a units store with the old fields no longer
      loads and old work must be finished or requeued first.

## 2. [agent-build-kit] [tier1] Remove the no-recorded-cause bridge

Done when units with no recorded cause need no special log lines or documents, and the status
still lists them.

- [x] 2.1 Test: a planned or held unit with no recorded cause is not readmitted by a running pass,
      and neither the tick nor the pass logs anything about it; `abk status` lists such units.
- [x] 2.2 Test: a stored cause this release does not know still reads as no cause.
- [x] 2.3 Delete the tick-time log lines and the paragraphs in the architecture and CLI documents
      and the pipeline skill that describe handling units with no cause, and the matching changelog
      sentence.
- [x] 2.4 Compare `docs/architecture.md`, `docs/cli.md` and the pipeline skill with the code and fix
      what no longer matches.
