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
                 [--no-exec] [--reviewer remote [--remote-timeout s]]
/maktab:momayezi --review-only --base <sha> --head <sha> [--ledger f] [--intent f] [--json]
```

Or ask for it: "review loop on this branch", "review and fix until clean".
Target defaults to the branch diff plus uncommitted changes; files, docs,
plans and specs work too.

- **Lenses**: correctness, security, spec-fit, simplicity, tests, performance,
  docs, accuracy, clarity. Picked from the changed paths alone by `rg` rules in
  [lenses.md](../skills/momayezi/references/lenses.md), so local runs and CI agree;
  capped at `momayezi_max_reviewers` (default 2), highest risk first. `--lenses`
  overrides and is never trimmed. `docs` uses `tahrir scan` when it is on PATH.
- **Findings** carry `file:line`, quoted evidence, severity and confidence;
  below 80 is dropped unless critical. Critical, major and minor get fixed; nits are offered
  at the end. `--verify` adds a verifier pass before fixes.
- **Ledger**: typed JSON ([ledger.schema.json](../skills/momayezi/references/ledger.schema.json)),
  the one thing reviewers, the remote reviewer and the editor exchange.
- **Gate**: for code, the project's check/test command is run as a baseline
  and after every round. Red blocks a clean stop.
- **Disputes**: the editor may decline a finding with evidence; a reviewer
  re-raises only with new evidence; anything left goes to you.

## Smart

`--smart` sizes the review from `git diff --shortstat` and untracked files,
without reading the diff: a four-tier table sets reviewers and rounds, and a
path matching the `security` rule bumps one tier. A small, mechanical change
reviews on `sonnet`. With a `floor>escalate` model (or `base>escalated`
effort) setting, a Large/Max or risky change moves up to the second, and the
announcement and ledger notes say why. Explicit flags win; tiers live in
[smart.md](../skills/momayezi/references/smart.md).

## Review-only

One review round, no edits, flags only (never your `/config`), smart on.
A prior `--ledger` narrows it to the diff since that ledger's head plus
uncited files. nameless's `momayez` check run executes:

```
claude -p "/maktab:momayezi --review-only --base … --head … --ledger … --intent … --json" \
  --permission-mode dontAsk --tools Read,Bash,Agent,WebFetch,WebSearch \
  --allowedTools "Bash(rg *)" "Bash(git diff *)" … --disallowedTools Edit,Write,NotebookEdit,"mcp__*" \
  --output-format json --json-schema "$(cat ledger.schema.json)"   # ledger in .structured_output
```

Reviewers get `Execution: off`, as with `--no-exec`. `dontAsk` denies reads
outside the checkout, so on the runner:

- user or managed settings must allow `Read(~/.claude/plugins/cache/maktab/**)`
  (an untrusted workspace's project settings are ignored);
- write `--ledger` and `--intent` inside the checkout.

## Remote reviewer

`--reviewer remote`, its backends, PR comments and the wire protocol:
[momayezi-remote.md](momayezi-remote.md).

## Config

Set in `/config` or when enabling the plugin. Reviewers run on the stronger
of the editor's model and the floor; smart drops a Small, plain change to
`sonnet` and escalates a heavy one; `--model` beats all.

| Option | Default | |
|---|---|---|
| `momayezi_reviewer_model` | `opus` | Floor (`sonnet`, `opus`, `fable`), or `floor>escalate` such as `sonnet>opus`. |
| `momayezi_reviewer_effort` | empty | Reviewer and verifier effort, or `base>escalated` such as `medium>xhigh`; empty keeps the agent's `high`. |
| `momayezi_queue_timeout` | empty | Seconds a remote review may sit queued; empty: the whole remote timeout. |
| `momayezi_max_rounds` | `3` | Round cap; the capped round reviews at full scope. |
| `momayezi_max_reviewers` | `2` | Most lenses auto-picked per round, and most reviewers at once. |
| `momayezi_smart` | `off` | `on` sizes every run like `--smart`; `--no-smart` turns it off per run. |
| `momayezi_reviewer_backend` | `repo` | `--reviewer remote`'s backend; `repo` reads `.momayez.toml`, else `gh-label`. |
| `momayezi_pr_comments` | `auto` | `all`, `none` (direct), or `auto` by backend. |

## Read-only

The reviewer's tools are `Read, Bash, WebFetch, WebSearch`. Plugin agents
can't set `permissionMode`, and Grep/Glob aren't available in every Claude
Code build, so Bash is kept for search, git history and running tests unless
the brief says `Execution: off`; its definition forbids writes. It runs in
the real tree, not a worktree, so it sees uncommitted edits.
