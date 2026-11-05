# Smart sizing

Spend review effort in proportion to the change. Decide once, in a line or two,
from the size numbers below; do not read the diff to decide. Explicit
`--max-reviewers`, `--max-rounds`, `--model` and `--lenses` win per setting.

## Measure

A diff target, code or prose: `git diff <base> --shortstat` and `--name-only`
(tracked changes, committed or not), plus untracked new files from
`git ls-files -o --exclude-standard` (files; lines by `wc -l`). Lines =
insertions + deletions + untracked lines. Named files or
documents: `wc -l` over them.

Skip generated files from both counts: paths
`git check-attr linguist-generated -- <paths>` sets, lock files (`*.lock`,
`uv.lock`, `package-lock.json`, `Cargo.lock`), and the comma-separated globs
in `${user_config.momayezi_size_ignore}`. Count them per path with
`git diff --numstat`. Lenses still see every changed path. Print what was
skipped: `Smart: Medium (412 lines, 9 files; 2 generated skipped, plain)`.

## Tier

The higher tier of lines and files wins; a risky path bumps one tier.

| Tier | Lines | Files | Reviewers | Rounds |
|---|---|---|---|---|
| Small | < 200 | ≤ 5 | 1 | 2 |
| Medium | < 800 | any | 2 | 2–3 |
| Large | < 2000 | any | 2 | 3–4 |
| Max | ≥ 2000 | any | 3 | 4–5 |

Reviewers is how many run at once, never more than `max_reviewers`; the
lens set comes from lenses.md alone, so smart on or off picks the same
lenses. Inside a rounds range, take the low end for repetitive or single-module
changes and the high end for entangled or cross-module ones.

**Risky**: the `security` rule in [lenses.md](lenses.md) matches a changed
path. Judge by path only, never by content.

## Model and effort

`sonnet` only for a Small, plain change that is mechanical: renames, moves,
formatting, comment or typo edits, version bumps, generated or dependency
churn. Anything else keeps the normal reviewer-model rule.

**Escalation.** A `floor>escalate` model setting, or a `base>escalated`
effort setting, escalates when the tier is Large or Max, or a risky path
bumped it. The round then runs on the stronger of the escalate value and the
normal pick; escalation only raises. Order efforts
`low < medium < high < xhigh`. A round is escalated only when this raised the
pick: announce `on <model> · effort <e> (escalated: <large|max>, risky)`, and
add the ledger note `Escalated to <model>, effort <e>: <reasons>`, naming only
what rose. Smart off: a pair is its first value.
