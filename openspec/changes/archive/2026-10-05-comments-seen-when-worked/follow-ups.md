## From `comments-seen-when-worked/1`

- In tests/pipeline/test_review_comments.py, test_a_review_following_a_host_raised_rework_gets_no_comments_note should assert that events.on_rework returned True and that the stored feedback carries the reason. Without that, the from_person=False check cannot pass just because the requeue never happened.
- tests/pipeline/test_review_comments.py:169 — The test ignores what `events.on_rework` returns and never checks that the feedback was written. If `on_rework` failed to find the unit, the `feedback_from_person is False` assertion would still pass.
