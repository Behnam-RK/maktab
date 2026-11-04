# maktab

One Claude Code plugin, one namespace: every tool here is `maktab:<tool>`.

| Tool | What it does | Doc |
|---|---|---|
| `/maktab:tahrir` | Keeps docs true to code: steward pass, ADR capture, the `tahrir` doc-budget gate on PATH and a prompt-time doc-gate reminder. | [docs/tahrir.md](docs/tahrir.md) |
| `/maktab:momayezi` | Review ↔ fix loop: you edit, fresh read-only `maktab:momayez` reviewers critique each round until clean, capped or stalled. | [docs/momayezi.md](docs/momayezi.md) |
| `/maktab:tarahi` | Drafts and revises shaping docs in one house format; publishes each version to Linear on confirm. | [docs/tarahi.md](docs/tarahi.md) |

## Install

```
/plugin marketplace add Behnam-RK/maktab
/plugin install maktab@maktab
```

Settings live in `/config`, one panel for the plugin, each key prefixed by
the tool it tunes (`tahrir_*`, `momayezi_*`); each tool's doc lists its own.
