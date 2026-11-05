# Review-only mode

```
--review-only --base <sha> --head <sha> [--ledger <file>] [--intent <file>] [--json]
              [--lenses a,b] [--model m] [--max-reviewers n] [--verify]
```

One review round and no edits. This is what the remote `momayez` check run
executes. It uses the same reviewers, lenses and ledger as the loop, so local
and remote findings agree.

## Flags only

Ignore every value substituted from user config, except
`momayezi_reviewer_model`, `momayezi_reviewer_effort` and
`momayezi_size_ignore`: the runner's own user settings, which the host sets
(`momayezi-review` loads no project or local settings). Each other setting
is its flag, else the built-in default SKILL.md names in parentheses (2
reviewers). Smart sizing is always on.

Execution is off. Every reviewer prompt carries `Execution: off`. Your own
Bash is limited to `rg`, `git diff|log|show|blame|ls-files|check-attr`, `ls` and `wc`, run
from the checkout. Never use `git -C`, and never pipe into anything outside
that list. Read files with Read. Measure and pick lenses yourself; the only
subagents are `maktab:momayez` reviewers.

## Steps

1. **Target**: `<base>..<head>`. For smart, measure with
   `git diff --numstat <base> <head>`, skipping generated files (smart.md). Choose lenses from
   `git diff --name-only <base> <head>` (smart.md, lenses.md). Always use the
   full target for this, even when a ledger is given.
2. **Intent**: read `--intent`. If it is missing or unreadable, review against
   the repo's rules (`AGENTS.md`, `CLAUDE.md`, `CONTRIBUTING.md`) and add the
   note `no intent brief`.
3. **Ledger**: load `--ledger` per [ledger.md](ledger.md). Its `wont-fix` and
   `disputed` reasons stand, as in round 2 and later of the loop. `round` is
   its round + 1, else 1.
4. **Model and effort**: SKILL.md Setup step 5, escalation included.
5. **Scope**:
   - No ledger: the full target.
   - With a ledger: `git diff <ledger head_sha> <head> -- <target paths>`,
     plus target files missing from `cited_files`.
   - If that diff fails because the old head was rebased away, use the full
     target and add the note `scope: full (prior head unreachable)`.
6. **Spawn, filter, verify**: SKILL.md "A round", steps 1–3.
7. **Dedupe** against the ledger's ids, then set `in_diff` and the header per
   ledger.md. New findings are `open`. A prior finding raised again (a
   `wont-fix` only with new evidence) becomes `open` with this round's
   evidence and `last_round`. Every other prior finding keeps its state.

Never run step 4 (decide and fix), the gate or the stop rules. Never edit, and
never start a second round.

## Output

With `--json`, the final message is the ledger JSON alone: no prose and no
code fence. Without it, print one line per new finding,
`F<n> <severity> <path:line> — <claim>`, then `Verdict: clean | findings`.
