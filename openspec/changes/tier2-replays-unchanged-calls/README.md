# tier2-replays-unchanged-calls

Tier-2 acceptance tests record the calls their code makes to things outside the stack (the model provider, the
package index, a code host) after a live pass, and replay one only when the request is identical; any difference
goes live and is recorded anew, and a recording that stops being used is held for review, not dropped.
