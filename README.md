# maktab

Personal Claude Code marketplace. Its own tools ship as one plugin,
[`maktab`](plugins/maktab/README.md), so each is `maktab:<tool>`. Upstream
plugins are rebuilt weekly with small patches (`patches/<name>.sh`), versioned
`<upstream>+<sha>` so auto-update picks up every upstream change. A patch that
stops applying fails the `sync upstreams` workflow and opens an issue.

```
/plugin marketplace add Behnam-RK/maktab
```

Upstream licenses are kept in each `plugins/<name>/` (MIT, Elastic-2.0).
