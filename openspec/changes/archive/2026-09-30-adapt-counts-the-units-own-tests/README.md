# adapt-counts-the-units-own-tests

Work out which tests a unit actually added by asking git, not by pattern-matching the text of
a diff — so the adapt step stops demanding decisions about tests the unit never touched.

Successor to adapt-asks-for-what-changed, which narrows *which* of a unit's tests need a
decision. This fixes the list it narrows: today that list is contaminated by any test function
that happens to sit near an edited line.
