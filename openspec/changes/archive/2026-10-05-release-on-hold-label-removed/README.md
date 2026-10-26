# release-on-hold-label-removed

Removing the `agent-hold` label from a pull request releases the unit it put on
hold. Today adding the label holds the unit but removing it does nothing: the
poller has no event for a label going away, so the unit stayed held for hours
after a person took the label off, until it was requeued by hand.
