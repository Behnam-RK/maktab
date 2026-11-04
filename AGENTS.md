# maktab

A Claude Code marketplace (`.claude-plugin/marketplace.json`) with two kinds of
plugin under `plugins/`:

- **Upstream** (`mattpocock-skills`, `context-mode`): rebuilt weekly by
  `scripts/sync.sh` from the URLs in `scripts/upstreams`, then
  `patches/<name>.sh`. Never edit them in place; the next sync overwrites
  it. Change the patch script, then run `scripts/sync.sh <name>`.
- **Own** (`maktab`): edited here. One plugin, so every tool shares the
  `maktab:` namespace: `tahrir`, `momayezi`, `tarahi` (skills) and `momayez`
  (momayezi's reviewer agent). `plugins/maktab/README.md` indexes them;
  `docs/<tool>.md` is each tool's user doc; `skills/<tool>/SKILL.md` is what
  the agent reads. Settings in `plugin.json` are prefixed by tool.

## Before changing the maktab plugin

- Read the tool's doc and a sibling file of the same kind (a skill reference,
  an analyzer, a test) and mirror it.
- tahrir's engine is `plugins/maktab/src/docsteward`. Its tests:
  `uv run --group test coverage run -m pytest && uv run --group test coverage report`
  (fails under 100% line and branch coverage). The doc gate on this repo: `uv run tahrir
  check`, configured by `.docs.toml` (upstream plugins excluded).
- Skill and reference prose is measured by that gate; keep SKILL.md under its
  hard cap and move detail into `references/`.

## Releasing

Bump `plugins/maktab/.claude-plugin/plugin.json` `version` and
`plugins/maktab/src/docsteward/__init__.py` together (the `tahrir init` pins
derive from it), and the `# frozen:` pin in `plugins/maktab/docs/tahrir.md`.
Tag every release, annotated: `git tag -a maktab--vX.Y.Z`. pre-commit and uvx
pin that tag, so `plugins/maktab/skills/tahrir/references/setup.md` resolves
its `^{}` commit. Pre-2.0 `mostofi--v*` tags stay for existing pins.
