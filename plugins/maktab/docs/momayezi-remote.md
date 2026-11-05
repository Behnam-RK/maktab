# momayezi: the remote reviewer

`--reviewer remote` keeps the loop, but each round commits, pushes (by the
repo's rules), calls `request_review` with the ledger and waits up to
`--remote-timeout` (1200 s), then merges the result by id and replies to each
`wont-fix` and `disputed`. Two timeouts stop it.

The plugin's `momayez` MCP server (stdlib Python, `gh`, and `kubectl` for
k8s-job) has `request_review`, `review_status` and `reply_to_finding`.
`request_review` takes a full editor ledger, or a lean one: `target`,
`round`, and per finding `id`, `state`, `at`, `claim`, `reason`. A lean one is
filled from the last reviewer ledger by id; an id it lacks is refused. Read
`gh` and `kubectl` calls retry a network flake or a 502/503/504 three times;
a dispatch or create retries only when the request never left.

## Backends

The backend decides what starts a round. It comes from
`$MOMAYEZI_REVIEWER_BACKEND`, then `momayezi_reviewer_backend`, then
`backend` in the repo's `.momayez.toml`, then `gh-label`.

| Backend | Starts the round by | Ledger comes back from | The repo needs |
|---|---|---|---|
| `gh-label` | the `review` label (a branch: a dispatch with `ref`, `ledger`) | the `momayez` check run | `momayez.yaml` and `momayez-post.yaml` |
| `gh-dispatch` | a `momayez.yaml` dispatch with `pr` or `ref`, `head`, `ledger`, `post` | the check run, or with `post=false` the run's `momayez-ledger` artifact | those inputs, and `run-name: momayez <pr/N or ref>@<head>` |
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
# .momayez.toml
backend = "k8s-job"
[k8s]
template = "ops/momayez-job.yaml"  # placeholders: ${name} ${namespace} ${repo}
namespace = "momayez"              #   ${target_flag} ${target} ${head} ${ledger_configmap}; $$ is a literal $
context = "staging"                # optional kubectl context
```

`.momayez.toml` is trusted like the repo's code: it can point `kubectl` at a
context and a template. Setting the backend in the env or
`momayezi_reviewer_backend` to a gh-* one leaves the file unread; k8s-job
always takes `[k8s]` from it.

**k8s-job** works as follows:
- The Job is named `momayez-pr<N>-<head7>-r<round>`, or for a branch
  `momayez-<ref, lowercased, other characters as ->-…`, cut to 63 characters. A repeat request
  reuses a live or finished Job; a failed one is replaced.
- The ConfigMap `<name>-ledger` holds the editor ledger under `ledger.json`
  and is owned by the Job, so `ttlSecondsAfterFinished` removes both.
- The caller needs: on `jobs`, create, get, list and delete; on
  `configmaps`, create, get, patch and delete; on `pods`, get and list; on
  `pods/log`, get.
- The container runs
  `momayezi-review --repo ${repo} ${target_flag} "${target}" --head ${head}
  --ledger-file <mounted ledger.json>`. The image needs `git`, `gh`, and
  `claude` with the maktab plugin enabled in user settings, which must also
  allow `Read(~/.claude/plugins/cache/maktab/**)` (the session runs with
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
