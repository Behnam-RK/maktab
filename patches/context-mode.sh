#!/bin/bash
# Keep the ctx_* MCP tools and session memory; caveman owns output condensing, so drop
# the tool-rewriting PreToolUse hooks, the SessionStart routing block and the ctx-* skills.
set -euo pipefail
python3 <<'PY'
import json
path = "hooks/hooks.json"
d = json.load(open(path))
d["hooks"].pop("PreToolUse")
json.dump(d, open(path, "w"), indent=2)

path = ".claude-plugin/plugin.json"
d = json.load(open(path))
d.pop("skills")
json.dump(d, open(path, "w"), indent=2, ensure_ascii=False)
PY
rm -rf skills

old='let additionalContext = ROUTING_BLOCK;'
grep -qF "$old" hooks/sessionstart.mjs || { echo "patch: routing block line moved upstream" >&2; exit 1; }
sed -i.bak "s/$old/let additionalContext = \"\";/" hooks/sessionstart.mjs && rm hooks/sessionstart.mjs.bak

# Self-heal code hard-codes the upstream plugin key and re-enables it in settings.json on start.
grep -rlF 'context-mode@context-mode' --include='*.mjs' . | xargs sed -i.bak 's/context-mode@context-mode/context-mode@maktab/g'
find . -name '*.mjs.bak' -delete

# Don't deploy a global ~/.claude/hooks/context-mode-cache-heal.mjs + SessionStart hook into the
# user's settings.json on every server start (it only heals the upstream marketplace's cache).
python3 - <<'PY'
import sys
p = "start.mjs"; s = open(p).read()
anchor = "try {\n  const { buildHookCommand, selfHealCacheHealHook"
if anchor not in s:
    sys.exit("patch: cache-heal deploy block moved upstream")
open(p, "w").write(s.replace(anchor, "if (false) " + anchor, 1))
PY
