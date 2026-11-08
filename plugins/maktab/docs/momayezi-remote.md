# momayezi: the remote reviewer

`--reviewer remote` keeps the loop, but each round commits, pushes (by the
repo's rules), calls `request_review` with the ledger and waits up to
`--remote-timeout` (1200 s), then merges the result by id and replies to each
`wont-fix` and `disputed`. Two timeouts stop it.

The plugin's `momayezi` MCP server (stdlib Python, `gh`, and `kubectl` for
k8s-job) has `request_review`, `review_status` and `reply_to_finding`.
`request_review` takes a full editor ledger, or a lean one: `target`,
`round`, and per finding `id`, `state`, `at`, `claim`, `reason`. A lean one is
filled from the last reviewer ledger by id; an id it lacks is refused. Read
`gh` and `kubectl` calls retry a network flake or a 502/503/504 three times;
a dispatch or create retries only when the request never left.

## Backends

The backend decides what starts a round. It comes from
`$MOMAYEZI_REVIEWER_BACKEND`, then `momayezi_reviewer_backend`, then
`backend` in the repo's `.momayezi.toml`, then `gh-label`.

| Backend | Starts the round by | Ledger comes back from | The repo needs |
|---|---|---|---|
| `gh-label` | the `review` label (a branch: a dispatch with `ref`, `ledger`) | the `momayezi` check run | `momayezi.yaml` and `momayezi-post.yaml` |
| `gh-dispatch` | a `momayezi.yaml` dispatch with `pr` or `ref`, `head`, `ledger`, `post` | the check run, or with `post=false` the run's `momayezi-ledger` artifact | those inputs, and `run-name: momayezi <pr/N or ref>@<head>` |
| `k8s-job` | a Job from the repo's template, made with the caller's `kubectl` | the last ledger marker in the Job's pod log | a namespace, the template, an image running `momayezi-review`, RBAC below |

A repo avoids `gh-label` when any label fires its CI, as nameless's
`ci.yaml` does. A dispatch fires no `pull_request` workflow.

`momayezi_pr_comments` decides whether the PR is written to:
- `all`: the sticky editor-ledger comment (round 1 resets it), replies to
  `wont-fix` and `disputed`, and the reviewer's post.
- `none`: the editor ledger travels as the backend's input, the reviewer's
  comes back from its output, and nothing is written to the PR.
  `reply_to_finding` says it skipped.
- `auto`, the default: `none` for `k8s-job`, else `all`.

`gh-label` cannot run without comments, since a label carries no ledger. Only
a GitHub App may create check runs, so `k8s-job` under `all` has the caller
post the PR review with its own `gh` token, and no check run. `routine`
(a claude.ai routine) waits until a run's result can be read back.

```toml
# .momayezi.toml
backend = "k8s-job"
[k8s]
template = "ops/momayezi-job.yaml"  # placeholders: ${name} ${namespace} ${repo}
namespace = "momayezi"              #   ${target_flag} ${target} ${head} ${ledger_configmap}; $$ is a literal $
context = "staging"                # optional kubectl context
```

`gh-dispatch` runs `momayezi.yaml` on the default branch. If that takes
unreviewed merges, set `dispatch_ref = "release"` (the trusted branch) in
`.momayezi.toml`. `gh-label`'s branch dispatch ignores it.

2.5.0 renamed every repo-hosted name from `momayez*` (table above;
constants in [momayezi-protocol.md](momayezi-protocol.md)): rename
`momayez.yaml`, `momayez-post.yaml`, their `run-name`, the `momayez-ledger`
artifact in the upload step, the check name in branch protection, and
`.momayez.toml`, which is refused whenever momayezi would read it. A k8s
template carries over unchanged. Pin 2.5.0 on both ends (the CI scripts and
the image): older ones post under the old names, so a round just times out.

`.momayezi.toml` is trusted like the repo's code: it can point `kubectl` at a
context and a template, and pick the branch gh-dispatch runs as. Setting the backend in the env or
`momayezi_reviewer_backend` to `gh-label` leaves the file unread; k8s-job
always takes `[k8s]` from it, and gh-dispatch its `dispatch_ref`.

**k8s-job** works as follows:
- The Job is named `momayezi-pr<N>-<head7>-r<round>`, or for a branch
  `momayezi-<ref, lowercased, other characters as ->-…`, cut to 63 characters. A repeat request
  reuses a live or finished Job; a failed one is replaced.
- The ConfigMap `<name>-ledger` holds the editor ledger under `ledger.json`
  and is owned by the Job, so `ttlSecondsAfterFinished` removes both.
- The caller needs: on `jobs`, create, get, list and delete; on
  `configmaps`, create, get, patch and delete; on `pods`, get and list; on
  `pods/log`, get.
- The container runs
  `momayezi-review --repo ${repo} ${target_flag} "${target}" --head ${head}
  --ledger-file <mounted ledger.json>` (add `--follow-rebase` to taste). The image needs `git`, `gh`, and
  `claude` with the maktab plugin enabled in user settings, which must also
  allow `Read(~/.claude/plugins/cache/maktab/**)` and the Bash list in momayezi.md (the session runs with
  `--setting-sources user` and `dontAsk`; see Review-only in momayezi.md). The pod needs `CLAUDE_CODE_OAUTH_TOKEN` and
  a read-only `GH_TOKEN`, and holds no write token.

**Cost:** Claude tokens dominate, the same on every backend.
- Hosted Actions jobs bill each job rounded up to the minute. With
  `gh-dispatch`, skip `start` on a dispatch and keep `review` on self-hosted
  runners; `post=false` also skips the hosted post job.
- A k8s review waits on the API, so request about 0.25–0.5 vCPU and 1 GiB.
  Spot nodes with `backoffLimit: 0` are cheap: a pre-empted Job fails fast,
  and the next request replaces it.

It polls the backend only while a review is pending. The loop always waits
with `momayezi-wait` (the hint carries `--known` for gh-label, else the
backend's `--handle`); the channel push is extra, under `--channels plugin:maktab@maktab`.
On Team and Enterprise, an Owner sets `channelsEnabled` and lists
`{"marketplace": "maktab", "plugin": "maktab"}` in `allowedChannelPlugins`;
else `--dangerously-load-development-channels` (interactive only).

## Protocol

The wire constants and the CI scripts: [momayezi-protocol.md](momayezi-protocol.md).
