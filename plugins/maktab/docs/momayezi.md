# Momayezi

A review ↔ fix loop for Claude Code. The main agent is the editor and owns
every change; read-only `maktab:momayez` reviewer subagents critique each round, fresh,
normally on a model at least as strong as the editor's (a Sonnet editor gets Opus
reviewers by default). It stops when a round finds nothing critical or major,
at the round cap, or when progress stalls.

Part of the [maktab](../README.md) plugin.

## Use

```
/maktab:momayezi [target] [--lenses a,b] [--model m] [--max-rounds n] [--max-reviewers n] [--smart|--no-smart] [--verify]
```

Or ask for it: "review loop on this branch", "review and fix until clean".
Target defaults to the branch diff plus uncommitted changes; files, docs,
plans and specs work too.

- **Lenses**: correctness, security, spec-fit, simplicity, tests, performance,
  docs, accuracy, clarity. 1–3 (at most `momayezi_max_reviewers`, default 2) are
  auto-picked and announced; `--lenses` overrides, is never trimmed and runs in
  waves of that size. `docs` uses `tahrir scan` when it is on PATH.
- **Findings** carry `file:line`, quoted evidence, severity and confidence;
  below 80 is dropped unless critical. Critical, major and minor get fixed; nits are offered
  at the end. `--verify` adds a verifier pass before fixes.
- **Gate**: for code, the project's check/test command is run as a baseline
  and after every round. Red blocks a clean stop.
- **Disputes**: the editor may decline a finding with evidence; a reviewer
  re-raises only with new evidence; anything left goes to you.

## Smart

`--smart` spends review effort in proportion to the change. The editor sizes
the target from `git diff <base> --shortstat` (lines, files) plus untracked files, without reading the diff,
then picks reviewers and rounds from a four-tier table; a risky path (judged by path, not content: auth,
shell, SQL, secrets, parsing, migrations, CI) bumps one tier. A small, mechanical
change (rename, formatting, version bump) reviews on `sonnet`, never `haiku`.
Explicit flags win per setting; tiers live in
[smart.md](../skills/momayezi/references/smart.md).

## Config

Set in `/config` or when enabling the plugin:

| Option | Default | |
|---|---|---|
| `momayezi_reviewer_model` | `opus` | Floor; reviewers get the stronger of this and the editor's model. |
| `momayezi_max_rounds` | `3` | Round cap; the capped round reviews at full scope. |
| `momayezi_max_reviewers` | `2` | Most lenses auto-picked per round, and most reviewers at once. |
| `momayezi_smart` | `off` | `on` sizes every run like `--smart`; `--no-smart` turns it off per run. |

## Read-only

The reviewer's tools are `Read, Bash, WebFetch, WebSearch`. Plugin agents
can't set `permissionMode`, and Grep/Glob aren't available in every Claude
Code build, so Bash is kept for search, git history and running tests; its definition forbids
writes. It runs in the real tree, not a worktree, so it sees uncommitted edits.
