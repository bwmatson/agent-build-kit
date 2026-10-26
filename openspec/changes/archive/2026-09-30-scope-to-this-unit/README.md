# scope-to-this-unit

Tell the builder and the reviewer which groups belong to *this* unit and which belong to
the units after it, and hold them to it — so a unit stops implementing its successors'
work. And when a unit does find its work already done, record it as satisfied rather than
failing it.

Working ahead is why one unit landed 5032 lines against a 520-line estimate, why the two
units behind it had nothing left to do, and why their task groups were ticked by a unit
that was never meant to cover them.
