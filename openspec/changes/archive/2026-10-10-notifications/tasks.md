# Tasks

Acceptance: none — the reconciler and the providers are proven at tier 1 with a fake notifier, clock and process runner; the one thing a fake cannot show, a real toast, is the hand-run task 2.7, which a person runs on a Windows machine.

## 1. [agent-build-kit] [tier1] Reconcile cards from the units and deliver them through a provider

Done when units in review or failed produce one card each, cards clear when their reason ends, and a configured command receives the card.

- [x] 1.1 Test: `tests/notify/test_reconcile.py` covers the desired cards from units (review with no pending rework,
      failed, held for a person; none for depth or the reviewer's hold), a card shown once, no duplicate on a
      second tick, cleared when a failed unit is requeued, cleared when a pull request merges, cleared when it goes to rework
      or rebase and shown again on return to review, reminded after `remind_after_minutes`, a unit that fails
      and is requeued within `delay_minutes` never shown, a failing provider logged and the tick unaffected, and
      disabled meaning no call.
- [x] 1.2 Test: `tests/notify/test_store.py` covers `notifications.json`: a restart keeps the set (no duplicate, no
      lost card), a failed show is retried and a failed clear is retried, and two overlapping writers cannot show one card twice.
- [x] 1.3 Test: `tests/notify/test_command_provider.py` covers the placeholders `{id} {title} {body} {link}` for show and
      `{id}` for clear, substitution per argument with no shell (a title with quotes or `;` is one argument), an
      unknown placeholder refused, a non-zero exit and a timeout reported as a failure.
- [x] 1.4 Test: `tests/test_config.py` (or the file mirroring `config.py`) covers the `notifications` section: defaults
      (off, 30, 10), a negative minute count refused, `command` without a `show` template refused, each error naming the key.
- [x] 1.5 Add `NotificationsConfig` (a `Frozen` model with a `Provider` `StrEnum`) to `config.py` and `WorkspaceConfig`, and a
      `notify/` package: the `Notifier` Protocol, a `CardKind` `StrEnum`, the desired-cards function, the store, the
      reconciler, and the `command` provider; read machine-local facts only through `settings.py`.
- [x] 1.6 Run the reconciler as a `_step` in `run_round` after the poll and the gating steps, and from the stored units when
      the round stops early at a usage pause; log through `log()` and count through `telemetry.count`
      (`abk.notifications`).
- [x] 1.7 Confirm against `StoredUnit` and `Cause` which fields express "no rework pending" and "needs a person", and
      whether `pr_replies.own_posts` can tell a person's activity from the pipeline's without a host call; record the result in
      the design's UNVERIFIED paragraph and the docs.

## 2. [agent-build-kit] [tier1] Windows toasts, the init prompt, the doctor check and the docs

Done when `abk init` offers the install on WSL or Windows, `abk doctor` reports the module, and a toast has been seen to appear and clear by hand.

- [x] 2.1 Test: `tests/notify/test_windows_provider.py` asserts, against a fake process runner, the `powershell.exe -NoProfile` command
      line `show` and `clear` build (title, body, link, identifier), with quoting that survives quotes and spaces, and that a
      non-zero exit is a provider failure.
- [x] 2.2 Test: `tests/init/test_detect.py` asserts WSL is detected from `WSL_DISTRO_NAME` and from `/proc/version`, Windows from
      the platform, and anything else as other.
- [x] 2.3 Test: `tests/cli/test_init.py` asserts that on WSL or Windows the install command is printed before the question and run
      only on a yes, that declining notifications writes the provider as off, that accepting writes `windows`, that `--yes`
      asks nothing and writes off, and that on another host nothing is asked.
- [x] 2.4 Test: `tests/cli/test_doctor.py` asserts the notifications check is absent when the provider is off, fails with the install
      command as its fix when the module is missing, passes when present, and for `command` fails when the program is not on `PATH`.
- [x] 2.5 Add the `windows` provider (BurntToast through `powershell.exe -NoProfile`, the module version pinned in the script), the `Host`
      detection in `init/detect.py`, the `abk init` prompt, and the `abk doctor` check.
- [x] 2.6 Document it in `docs/configuration.md` (the `notifications` section and its defaults), `docs/architecture.md` (the
      reconciliation step and the state table row for `notifications.json`), `docs/init.md`, `docs/cli.md`, the `abk-config` skill, and a
      changelog entry.
- [x] 2.7 Hand-run acceptance, by a person on a Windows machine with WSL: run `abk init`, accept notifications and the install; make a
      unit reach review and a second fail (or use a fake store); run `abk tick` and see a toast for each that opens its link; tick again
      and see no second toast; requeue the failed unit and merge the pull request and see both cards cleared; wait past
      `remind_after_minutes` with one card open and see it sounded again; run `abk doctor` with the module uninstalled and see the
      failure and its fix. Record the BurntToast version, the cmdlet names used for show and clear, and whether clear works from a new
      `powershell.exe` process, in the design's UNVERIFIED list, and correct the provider if they differ.
