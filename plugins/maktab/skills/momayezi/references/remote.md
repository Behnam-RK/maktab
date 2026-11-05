# Remote reviewer

`--reviewer remote [--remote-timeout <s>]`: each round's review comes from
the remote momayez reviewer, which runs [review-only mode](review-only.md) on
the pushed head through the configured backend. Setup, the ledger, decisions, the gate and the stop rules
stay as in SKILL.md. Only how a round gets its findings changes.

## Setup

- **Where**: the current branch's PR (`gh pr view --json number`), else the
  branch itself, which is reviewed through the backend.
- **Push**: announce
  `Reviewer: remote (commits and pushes each round to <branch>)`. A push
  leaves the machine, so follow the repo's commit and push rules from
  `AGENTS.md` and memory (for example, rebase before push). If there are none
  and the branch is shared, ask first.
- **Lenses and model**: the remote run picks them by the same rules, with
  defaults only. Announce what it will pick.
- **Tools**: the `momayez` MCP server's `request_review`, `review_status` and
  `reply_to_finding`. If they are missing, the server failed to start: say so
  and stop. A tool error about the backend or `.momayez.toml` is a setup
  problem: report it and stop.
- **Backend**: `request_review` starts the round through the configured one
  (`gh-label`, `gh-dispatch` or `k8s-job`) and says which. Announce it.

## Each round

1. **Push**: commit this round's fixes and push. In round 1, push the target
   as it stands.
2. **Request**: call `request_review` with `pr` or `ref`. From round 2 on,
   add your ledger as JSON ([ledger.md](ledger.md)), so the remote round sees
   your `wont-fix` and `disputed` reasons. Round 1 sends none, which resets
   the PR's review history so the remote starts at round 1. Keep the
   ledger's `head_sha` as the head the last remote round reviewed, so the
   remote scope is your fix diff plus uncited files. For the capped round, set
   it to `base_sha` so the remote reviews the full target. The result gives
   the new `head_sha` and a `wait` command.
3. **Wait**: run that command with Bash `run_in_background`, adding
   `--timeout <remote-timeout>` (default 1200) and, when
   `${user_config.momayezi_queue_timeout}` is set, `--queue-timeout` with it. Go on with whichever arrives
   first: the waiter's line, or a `<channel source="plugin:maktab:momayez">`
   event for the same `head_sha`. Ignore the other, and stop the waiter if it
   is still running.
4. **Timeout or failure**: if the status is `timeout` or `failed`, request
   again. After a second one, stop with `stopping: remote unavailable`. A
   `timeout` with `phase: queued` is reported as `no runner picked it up`
   (plus its `reason`), not as reviewer trouble.
5. **Merge**: load the returned ledger and merge it by id (ledger.md). Decide
   each new or re-raised finding as in SKILL.md step 4, then run the gate
   (step 5). For every `wont-fix` and `disputed`, post the reason with
   `reply_to_finding` (PRs only). If it answers `skipped`, PR comments are
   off: the reasons still travel in your ledger, so don't retry.
6. **Report** the round and apply the stop rules as usual.

When the loop stops, commit and push the last fixes without requesting a
review. The final report's `Reviewer:` line counts the requests.
