## From `forge-landed-checks/1`

- A reply that is found to have landed records only the reply's node id. A reply posted directly records that id plus the id of the empty review it creates. The poller skips empty review bodies, so nothing goes wrong. If both paths should record identical ids, have `comment_exists` return a list of ids and add the review lookup.
