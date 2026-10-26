# window-stops-are-pauses

If a step ends having written nothing while the account's usage window is exhausted,
pause the unit and resume it later — rather than failing it, which is what happens to
any empty step today.

Defensive, not a fix for something observed: the pipeline gates usage *between* steps
and never interrupts one, and the two mid-step cases that do exist are already handled.
What is not handled is a provider refusal that ends a step quietly, which today is
indistinguishable from a step that had nothing to do and from one that failed.
