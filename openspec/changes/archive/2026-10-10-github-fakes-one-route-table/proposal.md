# Proposal

## Why

The tests have two fake GitHub hosts. One runs in the test process and answers through a transport, with routes scripted per
test. The other is an HTTP server for the tests that run the whole tick as a process, and it carries its own handlers for
the pull list, pull update, comment and status routes and its own copy of the pull state, re-synchronised with the first on
every request. A route that one needs is written again for the other, and a route that only the server's tests reach is not
written for the first. The first time the process tests ran the whole tick, a reply route had no handler anywhere, and the
only handler for it was scripted inside one unrelated test.

## What Changes

- **One table of routes:** each route is a method, a path pattern and a handler over a single state: pull requests, reviews,
  review comments, labels, statuses and the ids they get.
- **Both hosts dispatch through it:** the in-process host and the HTTP server are shells around the same table, and the
  duplicate pull state and its synchronisation are removed.
- **Scripted routes stay,** as an override in front of the table, for the tests that need a particular answer.
- **A guard:** no route is handled outside the table.

## Impact

- agent-build-kit: test support only. Every existing test passes unchanged.
