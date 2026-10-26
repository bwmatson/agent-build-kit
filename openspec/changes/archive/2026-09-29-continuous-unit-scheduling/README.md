# continuous-unit-scheduling

Keep a tick's build slots full for as long as the pass runs: when a unit
finishes, work out what that unblocked and start it, instead of fixing the
batch when the pass began and idling until every unit in it returns.

Found while watching two changes build: a unit re-queued after a fixed failure
could not join the pass already running, and a chain's second unit could not
start while a slow sibling in another repo held the pass open — with three of
four slots empty the whole time.
