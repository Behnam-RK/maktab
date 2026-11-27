# momayezi: the k8s-job backend

`k8s-job` runs each remote review as a Kubernetes Job, made from the repo's
template with the caller's `kubectl`. Backends and settings:
[momayezi-remote.md](momayezi-remote.md).

```toml
# .momayezi.toml
backend = "k8s-job"
[k8s]
template = "ops/momayezi-job.yaml"  # placeholders: ${name} ${namespace} ${repo}
namespace = "momayezi"              #   ${target_flag} ${target} ${head} ${ledger_configmap}; $$ is a literal $
context = "staging"                # optional kubectl context
```

## The Job

- The Job is named `momayezi-pr<N>-<head7>-r<round>`, or for a branch
  `momayezi-<ref, lowercased, other characters as ->-…`, cut to 63 characters. A repeat request
  reuses a live Job, or one whose ledger it can read and isn't `degraded`, and replaces the rest.
- The ConfigMap `<name>-ledger` holds the editor ledger under `ledger.json`
  and is owned by the Job, so `ttlSecondsAfterFinished` removes both. With
  `--ledger-configmap` the runner keeps its result there too, so a review
  outlives a pod deleted with its node (spot scale-down).
- The caller needs: on `jobs`, create, get, list and delete; on
  `configmaps`, create, get, patch and delete; on `pods`, get and list; on
  `pods/log`, get. With `--ledger-configmap`, the pod's service account
  needs patch on `configmaps`, and the image `kubectl`. That grant is
  namespace-wide: a review pod could rewrite another Job's kept result, which
  the caller reads before the pod log, so keep the namespace to momayezi.
- The container runs
  `momayezi-review --repo ${repo} ${target_flag} "${target}" --head ${head}
  --ledger-file <mounted ledger.json> --ledger-configmap ${namespace}/${ledger_configmap}`
  (add `--follow-rebase` to taste).
- The image needs `git`, `gh`, and `claude` with the maktab plugin enabled in user settings, which must also
  allow `Read(~/.claude/plugins/cache/maktab/**)` and the Bash list in momayezi.md (the session runs with
  `--setting-sources user` and `dontAsk`; see Review-only in momayezi.md). The pod needs `CLAUDE_CODE_OAUTH_TOKEN` and
  a read-only `GH_TOKEN`, and holds no GitHub write token.

## Cost

A k8s review waits on the API, so request about 0.25–0.5 vCPU and 1 GiB.
Spot nodes with `backoffLimit: 0` are cheap: a pre-empted Job fails fast, and
the next request replaces it. A node removed after the Job completed takes
its pod and log with it; `--ledger-configmap` keeps the review readable.
