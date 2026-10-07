`CHANGELOG.md` opens with a `## Unreleased` section, and released versions follow it,
newest first. A pull request that changes what someone using the tool sees adds one
bullet under Unreleased, beside the bullets for related work, written for that person:
what changed and why, in plain words, wrapped with a two-space continuation. An entry
never names an installation, its repos or products, a pull-request or issue number, or
a dated story. Bullets are separated by one blank line, never run together, never
repeated, and never outside a `##` section. Add your bullet and leave the others as
they are, and never leave a conflict marker in the file. One change is one bullet, even
across several pull requests: fold later work into the bullet that already describes it
instead of adding another. The file merges with git's union driver, so concurrent
bullets from other pull requests coexist without a conflict.
