## ADDED Requirements

### Requirement: Cards are reconciled from the units

After each round's poll the pipeline SHALL compute the cards the units call for, compare them with the stored set,
show each card not yet shown and clear each stored card no longer called for. A unit in review with no rework
pending SHALL call for a review card, a failed unit for a failure card, and a held unit that needs a person for a
held card. Reconciliation SHALL read the unit store only.

#### Scenario: A card appears once

- **GIVEN** a unit that has just entered review with no rework pending
- **WHEN** the tick reconciles and then a second tick reconciles with the unit unchanged
- **THEN** the provider's `show` is called once, with the card's id, title, body and link
- **AND** the second tick makes no call
- Test level: unit

#### Scenario: A failed unit's card clears when it is requeued

- **GIVEN** a shown failure card for a failed unit
- **WHEN** the unit is requeued and the next tick reconciles
- **THEN** the provider's `clear` is called with the card's id and the stored set no longer holds it
- Test level: unit

#### Scenario: A merged pull request clears the review card

- **GIVEN** a shown review card
- **WHEN** the unit's pull request merges and the next tick reconciles
- **THEN** the card is cleared
- Test level: unit

#### Scenario: Rework clears the card and its return shows it again

- **GIVEN** a shown review card
- **WHEN** the unit goes to rework, then returns to review
- **THEN** the card is cleared when the unit goes to rework, and shown once more when it is back in review
- Test level: unit

#### Scenario: A hold that clears itself calls for no card

- **GIVEN** a unit held for stack depth, and another held by the reviewer's own hold
- **WHEN** the tick reconciles
- **THEN** neither unit has a card
- Test level: unit

#### Scenario: A paused round still reconciles

- **GIVEN** a round that stops at a usage pause, and a unit that has failed since the last tick
- **WHEN** the round runs
- **THEN** the failure card is shown from the stored units
- Test level: unit

### Requirement: Cards are delayed, remembered and reminded

A card SHALL NOT be shown until it has been called for continuously for `delay_minutes` (default 10), and a card
that stops being called for within the delay SHALL never be shown. A shown card SHALL be shown again, through the
same `show`, once `remind_after_minutes` (default 30) have passed since it was last sounded and it is still called
for. The stored set SHALL live in `notifications.json` in the state directory, so a restart neither repeats a shown
card nor loses one, and two overlapping ticks SHALL NOT show one card twice.

#### Scenario: A quick fix never shows

- **GIVEN** a unit that fails and is requeued within `delay_minutes`
- **WHEN** ticks reconcile throughout
- **THEN** the provider is never called for it
- Test level: unit

#### Scenario: A reminder after the interval

- **GIVEN** a card shown, still called for, with `remind_after_minutes` of 30
- **WHEN** a tick reconciles 31 minutes after it was sounded
- **THEN** the card is shown again, and not again until another 30 minutes pass
- Test level: unit

#### Scenario: A restart keeps the set

- **GIVEN** a shown card and a new process reading the same state directory
- **WHEN** the new process reconciles with the unit unchanged
- **THEN** no call is made to the provider
- Test level: unit

#### Scenario: Overlapping ticks

- **GIVEN** two reconciliations racing over one state directory with one new card called for
- **WHEN** both complete
- **THEN** the provider's `show` was called once
- Test level: unit

### Requirement: Notifications are off unless configured and never fail a tick

`notifications.provider` SHALL default to off, and when it is off the reconciler SHALL call nothing. A provider that
raises, exits non-zero or times out SHALL be logged and counted, SHALL NOT change a tick's outcome, and its card
SHALL be tried again on the next tick: a failed `show` is not recorded as shown, and a failed `clear` leaves the
id stored.

#### Scenario: Disabled

- **GIVEN** a workspace with no `notifications` section
- **WHEN** a tick runs with a unit in review
- **THEN** no provider is built and nothing is written to `notifications.json`
- Test level: unit

#### Scenario: A provider that fails

- **GIVEN** a provider whose `show` raises
- **WHEN** the tick reconciles
- **THEN** the failure is logged, the tick's outcome is unchanged, and the next tick calls `show` again
- Test level: unit

### Requirement: Providers sit behind one interface

Every provider SHALL implement `Notifier`, with `show(id, title, body, link)` and `clear(id)`, and
`notifications.provider` SHALL be one of the members of a closed set (`off`, `command`, `windows`) naming
which is built. The reconciler SHALL know no provider by name.

#### Scenario: A fake provider drives the reconciler

- **GIVEN** a recording implementation of `Notifier`
- **WHEN** the reconciler runs over a set of units
- **THEN** it works through the interface alone
- Test level: unit

### Requirement: The command provider runs a template

The `command` provider SHALL run the configured `show` template with `{id}`, `{title}`, `{body}` and `{link}`
substituted, and the `clear` template with `{id}`, splitting the command into arguments before substituting and
never through a shell. A template using any other placeholder, or a `show` template that is missing, SHALL be a
configuration error naming the key. A non-zero exit or a timeout SHALL be a provider failure.

#### Scenario: Placeholders are substituted

- **GIVEN** a `show` template `notify-send {title} {body} {link}` and a card titled `It's "ready"; now`
- **WHEN** `show` is called
- **THEN** the command receives the title as one argument, unchanged, and no shell runs
- Test level: unit

#### Scenario: An unknown placeholder

- **GIVEN** a `show` template containing `{colour}`
- **WHEN** the configuration is loaded
- **THEN** loading fails with an error naming `notifications.command.show`
- Test level: unit

### Requirement: The Windows provider raises toasts through BurntToast

The `windows` provider SHALL raise a toast from a Windows process (`powershell.exe -NoProfile` under WSL, or locally on
Windows) using the BurntToast module, replacing a repeat of the same id, opening `link` on a click, and removing the
toast on `clear`. It SHALL be the only place that knows BurntToast's cmdlets.

#### Scenario: The command line for a card

- **GIVEN** a fake process runner
- **WHEN** `show` is called for a card whose title contains quotes and spaces
- **THEN** the `powershell.exe -NoProfile` command line carries the title, body, link and id intact
- Test level: unit

#### Scenario: A toast appears, opens and clears (hand-run)

- **GIVEN** a Windows machine with WSL, the module installed, and a unit in review
- **WHEN** a person runs `abk tick`, clicks the toast, and then merges the pull request and ticks again
- **THEN** the toast appeared once, the click opened the pull request, and the card is gone after the second tick
- Test level: acceptance (run by hand)

### Requirement: The first round covers review and failure

The cards of the first round SHALL be ready-for-review, failed and held-for-a-person only. Other states SHALL call
for no card.

#### Scenario: A merged unit

- **GIVEN** a unit that is merged, and a unit that is running
- **WHEN** the tick reconciles
- **THEN** neither has a card
- Test level: unit

### Requirement: Init offers notifications on WSL and Windows

`abk init` SHALL detect whether it runs under WSL (`WSL_DISTRO_NAME` set, or `microsoft` in `/proc/version`),
on Windows, or elsewhere. On WSL or Windows it SHALL ask whether to enable notifications and, on a yes, whether to
install the module, printing the install command
`powershell.exe -NoProfile -Command Install-Module BurntToast -Scope CurrentUser` before asking and running it only
on a yes. Declining notifications SHALL write the provider as off, accepting SHALL write `windows`, and `--yes` SHALL
ask nothing and write off. Elsewhere it SHALL ask nothing.

#### Scenario: The command is shown first and run on a yes

- **GIVEN** `abk init` under WSL with a fake process runner
- **WHEN** the person answers yes to notifications and yes to the install
- **THEN** the command was printed before the question and the runner was called with it once, and `abk.yaml` names `windows`
- Test level: unit

#### Scenario: Declining

- **GIVEN** `abk init` under WSL
- **WHEN** the person answers no to notifications
- **THEN** nothing is run and `abk.yaml` names the provider as off
- Test level: unit

#### Scenario: Another host

- **GIVEN** `abk init` on a host that is neither WSL nor Windows
- **WHEN** it runs
- **THEN** no notification question is asked
- Test level: unit

### Requirement: Doctor checks the notification provider

When `notifications.provider` is not off, `abk doctor` SHALL check the provider's prerequisites, and a missing or
unusable one SHALL be a failure whose fix is the install command. For `windows` the prerequisite is the BurntToast module
listed by `powershell.exe`; for `command` it is that the template's program is on `PATH`. With the provider off it SHALL
report nothing.

#### Scenario: The module is missing

- **GIVEN** the provider is `windows` and the fake runner reports no BurntToast module
- **WHEN** `abk doctor` runs
- **THEN** it reports a failure whose fix is `powershell.exe -NoProfile -Command Install-Module BurntToast -Scope CurrentUser`
- Test level: unit

#### Scenario: Off

- **GIVEN** a workspace with notifications off
- **WHEN** `abk doctor` runs
- **THEN** no notification check is listed
- Test level: unit
