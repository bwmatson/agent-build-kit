# adapt-asks-for-what-changed

Ask the adapt step to account only for the tests whose fate is genuinely uncertain, and —
when its accounting is incomplete — ask it for the rest instead of failing the unit.

A unit died this week because a 97-turn adapt run produced decisions for every test it had
added but one. Nothing was wrong with the code, the omission was named precisely by the
checker, and the fix was one missing line.
