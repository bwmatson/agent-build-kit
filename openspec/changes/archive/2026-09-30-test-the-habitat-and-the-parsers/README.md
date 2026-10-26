# test-the-habitat-and-the-parsers

Two gaps, chosen because tonight's failures came through them and not through the places more
testing is usually aimed.

**The habitat.** Every build runs in a git worktree, through the target repo's real pre-commit
gate, in a uv workspace. There is one integration test in the whole framework and it mentions none
of that — which is why a type checker that cannot see any files in a worktree was discovered by a
unit dying rather than by a test.

**The parsers.** Several functions read messy real-world text — a diff, an agent's transcript, a
provider's refusal — and one of them shipped a bug that cost a unit. They are cheap to test with
realistic input, and where the thing worth testing is private, it is either named properly or
exercised through the public function that uses it.
