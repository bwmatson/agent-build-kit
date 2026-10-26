## ADDED Requirements

### Requirement: Tier-2 tests record external calls after a passing live run

Tier-2 acceptance tests SHALL be able to route the calls their code makes to configured external upstreams (the
model provider, the package index, a code host) through a reverse proxy that records them. Nothing SHALL be
recorded before a live run; the calls of a test SHALL be written only when that test passes, and those of a
failing test SHALL be discarded. The setting `ABK_REPLAY_MODE` SHALL be one of `off` (the default), `record`,
`replay` and `live`; `off` SHALL start no listener and change nothing, and `live` SHALL ignore cassettes.

#### Scenario: A recording is made only after a pass

- **WHEN** a test runs in `record` mode and passes
- **THEN** its calls are written as cassettes, one file per call

#### Scenario: A failing run is discarded

- **WHEN** a test runs in `record` mode and fails
- **THEN** no cassette from it is in the cassette directory

#### Scenario: Off changes nothing

- **WHEN** the mode is `off`
- **THEN** no listener is started and the code under test is given no changed address

#### Scenario: Live ignores cassettes

- **GIVEN** a cassette matching a request
- **WHEN** the mode is `live`
- **THEN** the call goes to the upstream and the answer is recorded after a pass

#### Scenario: The unproven endpoint overrides are listed

- **WHEN** a contributor reads the agent-runtimes documentation
- **THEN** it says how each agent and package tool is pointed at the proxy, or that it could not be

### Requirement: A recording is replayed only for an identical request

The proxy SHALL key a cassette by a canonical hash of method, path, query, the allowlisted headers that change an
answer, and the body after any declared rules. In `replay` mode an exact key match that is not past its age SHALL be
answered from the cassette; any difference SHALL go to the upstream and its answer SHALL be recorded against the new
request. Credentials SHALL NOT be part of a key or be stored, and a response body holding a configured secret SHALL
fail its recording.

#### Scenario: An identical request replays

- **GIVEN** a cassette for a request
- **WHEN** the same request is made in `replay` mode
- **THEN** the cassette answers and the upstream is not called

#### Scenario: A difference goes live

- **WHEN** a request differs from every cassette in its body, query, path or model
- **THEN** it goes to the upstream and a cassette is written under its own key

#### Scenario: A secret is never stored

- **WHEN** a request carries a credential, or a response body holds a configured secret value
- **THEN** the credential is in no key and no file, and the response is not recorded

#### Scenario: Normalisation is declared, recorded and reported

- **GIVEN** two requests differing only in a temporary directory prefix
- **WHEN** no rule is declared
- **THEN** they miss; and with a declared rule they hit, the rule is stored in the cassette and shown in the report

#### Scenario: Streaming replays as the chunk sequence

- **WHEN** a streamed response is recorded and replayed
- **THEN** its chunks arrive in the order received, without their timing

### Requirement: A model call replays only on a static context and ages out

An upstream of kind `<redacted>` SHALL replay only on an exact key over the whole conversation, tools, model and sampling
settings, and not once older than `<redacted>_max_age_days` (default 14). A `deterministic` upstream SHALL replay on an
exact key and not once older than `max_age_days` (default 30); an older cassette SHALL count as a miss and the call
SHALL be recorded again.

#### Scenario: A model call whose context differs

- **WHEN** one message of the conversation differs from the recorded one
- **THEN** the call goes live

#### Scenario: A model recording past its age

- **GIVEN** an `<redacted>` cassette older than its age
- **WHEN** the identical request is made
- **THEN** it goes live and is recorded again

#### Scenario: A deterministic recording past its age

- **GIVEN** a `deterministic` cassette older than `max_age_days`
- **WHEN** the identical request is made
- **THEN** it is a miss and the new answer is recorded

### Requirement: Only calls outside the stack are given a listener

The in-stack host set SHALL be derived from the workspace by one function from exactly these: the URL values of
`verify.env`, each repository's code host, the settings that name stack endpoints, loopback, private ranges,
`host.docker.internal` and single-label names. A listener SHALL exist only for a configured upstream, and an
upstream whose host is in the set SHALL fail the run at startup, naming the upstream.

#### Scenario: A configured upstream inside the stack

- **GIVEN** an upstream whose host is a `verify.env` value
- **WHEN** the run starts
- **THEN** it fails naming that upstream and the key that put the host in the set

#### Scenario: Nothing else contributes

- **WHEN** a repository's dev stack script, runtime command or deploy rules mention a host
- **THEN** that host is not in the set

### Requirement: Cassettes are kept small and in the repository

Cassettes SHALL be stored one file per call, gzip-compressed, under a directory in the repository that owns the
test, holding a request summary with digests and not the request body. A response body over `max_body_bytes`
SHALL not be recorded and SHALL be reported, and past `max_directory_mb` the report SHALL warn and nothing more
SHALL be promoted. The time of last use SHALL be kept in a gitignored state file and not in a cassette.

#### Scenario: An oversized body

- **WHEN** a response body exceeds `max_body_bytes`
- **THEN** it is not recorded and the report names the call

#### Scenario: Using a cassette does not change it

- **WHEN** a cassette is replayed
- **THEN** the committed file is unchanged and the state file records the use

### Requirement: A replay report says what ran live and what did not

After each run the proxy SHALL report per test and in total the calls hit, the misses that went live with what
differed from the nearest earlier cassette for the same test and call index, the cassettes unused, the aged out,
the declared rules used, and the billed calls avoided. A test that replayed any call SHALL be labelled `replayed`
with N of M external calls replayed and K live; its outcome SHALL be unchanged.

#### Scenario: A miss names the difference

- **WHEN** a call goes live because its request differs
- **THEN** the report gives the key and says where it differs, such as the system prompt or the path

#### Scenario: A replayed result is labelled

- **WHEN** a test passes having replayed calls
- **THEN** it is labelled `replayed` with the counts in the terminal summary and in its properties

### Requirement: A recording that is no longer relevant is held for review

A cassette the run did not ask for, or superseded by a live recording for the same test and call index under a
different key, SHALL be marked `needs_review` with a reason and SHALL NOT be deleted. `abk status` and `abk doctor`
SHALL say how many wait; `abk replay review` SHALL list them with the difference between request summaries and
keep or delete each. A set unreviewed for more than `review_after_runs` runs (default 5) SHALL make the next run
warn and SHALL NOT fail a test.

#### Scenario: A cassette stops being used

- **WHEN** a run does not ask for a cassette, or a live call replaces its request
- **THEN** it is marked `needs_review` and remains on disk

#### Scenario: Status and doctor show the count

- **GIVEN** cassettes waiting for review in a repository with a replay section
- **WHEN** `abk status` and `abk doctor` run
- **THEN** each reports the number, and neither reports it for a repository without the section

#### Scenario: Review decides each cassette

- **WHEN** `abk replay review --keep` or `--delete` names a cassette
- **THEN** the mark is cleared, or the file is removed

#### Scenario: A stale set warns

- **GIVEN** a cassette unreviewed past `review_after_runs` runs
- **WHEN** the next run starts
- **THEN** it warns loudly and no test fails for it

### Requirement: Replay is proven with a live pass, a replay and a changed input

There SHALL be a tier-2 acceptance test that builds one scratch unit in `record` mode and passes, builds it again
in `replay` mode over deterministic fixtures, and builds it a third time with the task text changed. It SHALL
assert the calls with identical keys were replayed with no billed model call for them, that only the affected calls
went live with a new cassette each, and that each old cassette is marked `needs_review` with the difference
reported. It SHALL assert the deterministic upstream first, SHALL report the model hit rate, and SHALL NOT weaken an
assertion to obtain a hit. It SHALL be marked to run where the framework's other acceptance tests run and not in
the default suite.

#### Scenario: A live pass is recorded

- **WHEN** the unit is built in `record` mode and the test passes
- **THEN** cassettes are promoted

#### Scenario: An unchanged rerun replays

- **WHEN** the unit is built again in `replay` mode with nothing changed
- **THEN** calls with identical keys are replayed, the result is labelled `replayed`, and none of them billed

#### Scenario: A changed input goes live

- **WHEN** the task text is edited and the unit is built again
- **THEN** exactly the affected calls go live, a new cassette is written, the old is marked `needs_review`, and
  the report names the difference

#### Scenario: The default suite stays hermetic

- **WHEN** the default test suite runs
- **THEN** the acceptance test and the live proxy are not among it
