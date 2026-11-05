# Tahrir

Keeps a repo's docs true to its code. Part of the [maktab](../README.md)
plugin, with:

- the `tahrir` skill — steward pass after code changes, ADR capture when a
  decision is made or asked about;
- a `UserPromptSubmit` doc-gate — on implementation-shaped prompts, a one-line
  reminder to read the conventions and a sibling first, only in a repo that has
  its routing doc or a `.docs.toml`;
- `tahrir` on PATH — a doc-budget gate measuring markdown in weighted tokens,
  with docstring/comment-block rules and stale-doc scanning.

Needs Python 3.12+: found via `$PYTHON`, `uv python find`, then
`python3.14`…`python3.12`, `python3`.

## Use

```
/maktab:tahrir [pass|adr|why|setup] [target] [--base REF]
```

Or ask: "update the docs", "record this decision", "why did we pick X?".
`/maktab:tahrir setup` detects the repo's languages, convention docs, ADR log and
vendored trees, asks one round of questions, writes `.docs.toml` (or edits an
existing one in place), and offers to add the pinned pre-commit hook.

## Config

Per user, set in `/config` or when enabling the plugin. A repo's own doc
rules and `.docs.toml` win over these, except the doc gate: either
`tahrir_proactivity = off` or `[doc-gate] enabled = false` turns it off.

| Option | Default | |
|---|---|---|
| `tahrir_proactivity` | `suggest` | `eager` offers a pass after code changes; `suggest` says what looks stale in one line; `on-request` waits to be asked. |
| `tahrir_steward_consent` | `apply` | `propose` shows planned doc edits before writing. ADRs are always drafted for approval. |
| `tahrir_setup_profile` | `default` | Profile `/maktab:tahrir setup` proposes. |

`tahrir_proactivity = off` is `on-request` that also mutes the doc-gate
reminder for you everywhere.

## CLI

```
tahrir check [files…] [--base REF]  # blocking gate, exit 1 on failure (strict with no files)
tahrir scan [files…] [--base REF]   # advisory report, exit 0 (2 if the config is broken)
tahrir init [--check]               # scaffold .docs.toml + doc guide + docs/adr/
tahrir --explain RULE               # one rule's reasoning and knobs
```

`check` and `scan` also take `--root DIR`, `--config PATH`, `--profile NAME`,
`--json` and `--verbose`; `check` adds `--require-exact` (fail rather than
estimate when tiktoken is missing). `--root` defaults to `$DOCS_ROOT`, then
`$DOC_BUDGET_ROOT`, then the working directory, for `init` as well.

`init` flags: `--root`, `--profile`, `--lang a,b`, `--exclude GLOB` (repeatable),
`--adr-dir DIR` (moves the ADR caps, collision rule and templates; no
wildcards; default: the one a kept `.docs.toml` names, else `docs/adr`),
`--no-guide`, `--no-adr` (keep an existing log), `--no-docs` (both),
`--doc-gate`/`--no-doc-gate`, `--routing-doc PATH`, `--force`. `--check`
compares the landed templates with the shipped ones; give it the
`--no-guide`/`--no-adr`/`--no-docs` flags `init` ran with, and it demands only
the files those leave. Bad flags exit 2.

## Pin it in another repo

The repo root packages the gate as `tahrir` (extra `exact` adds tiktoken).
Pin a tagged commit, never a branch; a release tag `maktab--vX.Y.Z` names
the maktab plugin it ships in (pre-2.0 tags were `mostofi--vX.Y.Z`):

```yaml
# .pre-commit-config.yaml
- repo: https://github.com/Behnam-RK/maktab
  rev: <sha>  # frozen: maktab--v2.2.0
  hooks:
    - id: tahrir
      additional_dependencies: ["tiktoken>=0.9,<1"]
```

```
uvx --from 'tahrir[exact] @ git+https://github.com/Behnam-RK/maktab@<sha>' tahrir check
```

## `.docs.toml`

Every key is optional; `tahrir init` writes a commented starter.

| Key | Meaning |
|---|---|
| `profile` | `default` or `strict` rule severities |
| `[defaults]` `soft`, `hard` | weighted-token caps per doc (1000/1400) |
| `[[overrides]]` `pattern`, `soft`, `hard`, `rules`, `structure_rules`, `status` | per-glob caps/rules, first match wins |
| `[exclude]` `paths`, `always_exempt` | skipped / exempt paths |
| `[rules.<id>]` `severity` + knobs | `fail` / `warn` / `off`; see `--explain` |
| `[python]` `enabled`, `runtime_surfaced_decorators`, `docstring_cap`, `module_docstring_cap`, `cli_help_exempts_module` | docstring rules |
| `[comments]` `enabled`, `prefixes` | comment-block rules |
| `[corpus]` `doc_globs`, `code_globs`, `package_roots` | what is scanned |
| `[doc-gate]` `enabled`, `routing_doc`, `trigger` | the prompt hook: on/off, doc it names (default: `AGENTS.md`, else `CLAUDE.md`), ERE matched per line |
