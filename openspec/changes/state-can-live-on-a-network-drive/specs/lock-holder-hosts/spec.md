## ADDED Requirements

### Requirement: A lock holder's record names its host

A lease, a branch lock and the e2e-test lock's record SHALL carry the name of the host that wrote them. A record without a host SHALL be read as this host's, so records written before this change keep their meaning.

#### Scenario: New records carry the host

- **GIVEN** a host named `box`
- **WHEN** a lease is taken, a branch lock is taken and the e2e-test lock is held
- **THEN** each record's `host` is `box`

#### Scenario: An old record is this host's

- **GIVEN** a lease file written without a `host`
- **WHEN** the lease is read on any host
- **THEN** it is judged by this host's process table as before

### Requirement: A holder on another host is never taken over

A record whose host is not this host SHALL be treated as held: this host's process table SHALL NOT be consulted for it. A lease SHALL refuse a second holder and show its host and `stale` false; `branch_lock` SHALL raise `BranchBusy` naming the host and the file; `lock_holder_gone` and `branch_held` SHALL answer from the record's host; the e2e-test lock's wait message SHALL name the host and say its process cannot be checked from here. No record of another host SHALL be removed or rewritten by this host except `Leases.drop`, which a person's command calls.

#### Scenario: A foreign lease is not stale

- **GIVEN** a lease recording host `other`, a pid that does not exist here and a start time that matches nothing
- **WHEN** another holder takes the unit's lease on host `box`
- **THEN** the take returns False and `attachment` shows host `other` and `stale` false

#### Scenario: A foreign branch lock is not removed

- **GIVEN** a branch lock recording host `other` and a pid that is not alive here
- **WHEN** `branch_lock` is asked for the branch on host `box`
- **THEN** it raises `BranchBusy` naming `other` and the file, and the file is unchanged

#### Scenario: A foreign e2e-test record is waited for

- **GIVEN** an e2e-test lock held by a handle and a record naming host `other`
- **WHEN** the waiting message is built on host `box`
- **THEN** it names `other` and says the process cannot be checked from here, and does not say the process is gone

#### Scenario: A local dead holder is still reclaimed

- **GIVEN** a branch lock recording host `box` and a pid that is not alive
- **WHEN** `branch_lock` is asked for the branch on host `box`
- **THEN** the lock is taken as before
