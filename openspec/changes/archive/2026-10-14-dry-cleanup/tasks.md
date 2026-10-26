# Tasks

Acceptance: none — behaviour-preserving refactors; the existing suite plus characterisation tests and guards prove them.

Priority: 3

## 1. [agent-build-kit] [tier1] Paired metric calls become one function

Needs: dry-guidance group 2 merged — the reuse guidance the cleanup is built under
Needs: flaky-tests group 3 merged — both change the tier 1 checks code, so they are serialised

Done when the six sites that emit a metric and record it locally go through one helper, the metrics page still lists
their instruments, a tier 1 failure is classified once at each site, and the unresolved list is computed once. The
guard (1.7) is the last commit of the group: written before the move it fails by design.

- [x] 1.1 Test: at each of the six pair sites (the tick duration, the usage pause, the unit duration, the rate-limit
      pause, the second usage pause, the review rounds) the telemetry call and the local record give the same name,
      value and attributes through the one helper as the pair did; with telemetry off, the record is still written.
- [x] 1.2 Test: the metrics catalogue still lists `abk.tick.duration`, `abk.usage.pauses`, `abk.unit.duration` and
      `abk.review.rounds`, each with the type and attributes it had before the move.
- [x] 1.3 Test: a tier 1 failure is classified once at each of the two sites that classified it twice, and the
      telemetry and the stored feedback carry the same result, including when the classification falls back to
      "unknown".
- [x] 1.4 Test: the unresolved ids and the rendered open entries of the stack runner's answer come from one
      computation of the open entries.
- [x] 1.5 Add the helper beside the metric records, taking the kind of instrument, its name, value, the unit and
      change and the attributes; teach the metrics catalogue's scan to read the helper's calls (a literal kind and
      a literal name) as it reads the direct calls; move the six sites onto it.
- [x] 1.6 Classify the failure once at each of the two sites and use the result for both purposes; compute the open
      entries once and pass them on.
- [x] 1.7 Test (guard, last commit of the group): no function in the source calls `record_metric` except the helper,
      so a metric with a local record is never emitted by making the two calls separately.
- [x] 1.8 Update `docs/architecture.md` and add a changelog entry.

## 2. [agent-build-kit] [tier1] State files are written by one function

Done when the write-to-a-temporary-then-replace idiom has one definition that the state files' writers use. The
guard (2.5) is the last commit of the group.

- [x] 2.1 Test: the shared atomic write leaves the previous content, and no temporary file, when the write is
      interrupted at any step, and a reader never sees a half-written file.
- [x] 2.2 Test: two writers of one file at once do not share a temporary name, as the writers that already used a
      per-process name did not.
- [x] 2.3 Add the shared atomic write beside the file lock: text in, temporary name per process, the temporary
      removed when anything is raised, the replace last.
- [x] 2.4 Move the writers onto it and delete their copies of the idiom: the pipeline command's marker and ledger
      writes, the redaction command's, the usage command's, the local forge's, the notification store's, the
      environment state's, the label sweep's, the pause marker's, the unit store's, the usage guard's, the usage
      report's, the wait log's, the policy check's and the review store's (fourteen sites). The local forge's and
      the review store's keep the file lock they take around the write.
- [x] 2.5 Test (guard, last commit of the group): no source module outside the shared one calls `os.replace` or
      replaces over a path from a temporary, scratch or partial file name.
- [x] 2.6 Update `docs/architecture.md` and add a changelog entry.

## 3. [agent-build-kit] [tier1] One git runner, one change layout, one definition of each pattern, one tail for the hosts

Done when the plain git calls use the shared runner, the places that spell out where a change lives take it from one
function, the host-address and diff-hunk patterns are each defined once, and the two hosts' parsing helpers share
their validating tail. The restack module is not touched. The guard (3.7) is the last commit of the group.

- [x] 3.1 Test: the remaining plain git calls in the init command (status, add, commit), the commit gate (the three
      reads) and the scaffold (init) give the same results as before when run through the shared runner, including
      a failing command.
- [x] 3.2 Test: the archive step, the graph's planning-branch setup, the change proposal and the init command find a
      change's directory through the one layout function, for a custom specs directory as for the default.
- [x] 3.3 Test: the host-address pattern and the diff-hunk pattern each match what every copy matched, and each is
      imported, not defined, by the other modules that use it.
- [x] 3.4 Test: on GitHub the paths of a pull request's files come from the same single paged call as the full
      listing, which is made once; Azure DevOps and the local forge answer as before.
- [x] 3.5 Test: each host's parsing helpers raise the same transport error naming the endpoint for a body that is
      not the document expected, through the shared validating helper.
- [x] 3.6 Route the init command, the commit gate and the scaffold through `shell.git`; add the layout function
      beside `Installation.changes_dir` for the callers that hold a root and a specs directory, not an installation;
      define the host-address and diff-hunk patterns once and import them; derive GitHub's file paths from its full
      listing; add the shared validating helper to the forge transport and call it from both hosts' `_parse` and
      `_items`; delete the copies.
- [x] 3.7 Test (guard, last commit of the group): no two modules under `src/` define the same module-level compiled
      pattern.
- [x] 3.8 Update `docs/architecture.md` and `docs/code-forges.md` and add a changelog entry.

## 4. [agent-build-kit] [tier1] Test helpers live in one place

Done when each helper that was copied identically is defined once in the shared test modules and its copies are
gone. The guard (4.4) is the last commit of the group.

- [x] 4.1 Test: the shared commit helper writes a file and commits it with the message the restack tests' five
      copies gave, and returns what a caller needs.
- [x] 4.2 Move the five identical restack `commit` helpers into `tests/factories.py`, the two copies of
      `fake_openspec`, the `write_change` copies that write the same tasks file, and the tracks tests' own
      `make_installation` (the shared one is `tests/conftest.py`'s), point the test files at them and delete the
      copies. The commit helpers of the other shapes (a tree and a config, an HTTP call, a file map, a returned
      sha) are different helpers and stay.
- [x] 4.3 Run the whole suite to confirm no test changed other than where it imports from.
- [x] 4.4 Test (guard, last commit of the group): none of the merged helper names is defined in a test file other
      than its shared module, and no two top-level test helpers anywhere share a name and the same body; a
      same-named helper with a different body (`commit`, `inst`, `runner`) is allowed.
- [x] 4.5 Add a changelog entry.
