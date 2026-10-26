# Tasks

Acceptance: none — one derivation inside the runner, with no surface a consumer drives; tier-1
tests over a diff with context prove it.

## 1. [agent-build-kit] [tier1] The unit's own tests, not its neighbours'

Needs: adapt-asks-for-what-changed group 1 — that change narrows which of a unit's tests need a
decision, and this makes the set it narrows mean what it says; landing this second keeps the two
effects visible in one step.

Done when a test that only neighbours a unit's edit is no longer counted as the unit's, a test the
unit defined, deleted or edited inside still is, and a failed accounting names what is outstanding.

- [x] 1.1 Test: over a diff where a test definition appears only on a context line, that test is not
      counted as the unit's; a test whose definition the range adds, and one whose definition it
      removes, both are.
- [x] 1.2 Test: a test the unit did not define but whose body its changes edited is counted; a test
      in the same file that the changes did not touch at all is not.
- [x] 1.3 Test: a failed accounting records the outstanding test names on the unit.
- [x] 1.4 Derive the unit's tests from which lines the change added or removed and which test each
      line falls inside, rather than by matching the diff's text.
- [x] 1.5 Say in `docs/architecture.md` where the adapt step is described that the accounting covers
      the tests the unit defined, deleted or edited inside — not those its diff merely passes by.
