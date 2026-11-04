#!/usr/bin/env bash
# UserPromptSubmit hook: on implementation-shaped prompts, remind the agent to
# read the repo's conventions and a sibling first. Never blocks.
# Configured under [doc-gate] in .docs.toml and by `tahrir_proactivity` (docs/tahrir.md).

set -uo pipefail

# The user's own switch: plugin option `tahrir_proactivity` = `off` silences tahrir
# entirely, this reminder included. Any other value, unset or empty is on: what an
# unset option expands to is not documented, and the shipped default is `suggest`.
case "$(printf '%s' "${CLAUDE_PLUGIN_OPTION_TAHRIR_PROACTIVITY:-}" | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')" in
  off) exit 0 ;;
esac

# python, not jq: jq is not a Claude Code dependency, so requiring it meant the
# hook silently never fired without it.

payload=$(cat 2>/dev/null) || exit 0
[ -n "$payload" ] || exit 0

root="${CLAUDE_PROJECT_DIR:-$PWD}"
config="$root/.docs.toml"

read -r -d '' gate_reader <<'PY' || true
import json
import sys
import tomllib

# The payload arrives on stdin, not in argv: a prompt carrying a pasted file is
# megabytes, and an argv that size fails with E2BIG on every candidate below —
# which read as "no interpreter" and stopped the hook firing at all.
payload, config = sys.stdin.read(), sys.argv[1]

try:
    prompt = json.loads(payload).get('prompt') or ''
except (ValueError, AttributeError):
    prompt = ''

gate = {}
try:
    with open(config, 'rb') as handle:
        gate = tomllib.load(handle).get('doc-gate') or {}
except (OSError, tomllib.TOMLDecodeError, AttributeError):
    # A broken or absent config must not disable the reminder; it falls back to
    # the shipped defaults, which is what a repo that never configured it gets.
    gate = {}

# `doc-gate = "yes"` parses fine and is not a table. Reading it as one raised
# out here, past the except above, and the shell then blamed the interpreter.
if not isinstance(gate, dict):
    gate = {}

enabled = gate.get('enabled', True)
if isinstance(enabled, str):
    enabled = enabled.strip().lower() not in ('false', 'no', '0', 'off')


def first_line(value: object) -> str:
    # First line, not collapsed whitespace: a user's ERE may contain a literal
    # double space or tab, and squashing it silently changes what it matches.
    return str(value).split('\n', 1)[0] if value else ''


# Three single-line fields, then the prompt, which keeps its newlines because
# the trigger is deliberately ^-anchored and matches per line.
print('yes' if enabled else 'no')
print(first_line(gate.get('routing_doc')))
print(first_line(gate.get('trigger')))
print(prompt)
PY

# macOS ships 3.9 as /usr/bin/python3 (no tomllib); share the shim's discovery.
# shellcheck source=find-python.sh source-path=SCRIPTDIR
. "$(dirname "${BASH_SOURCE[0]}")/find-python.sh"
fields=''
find_python && fields=$("$py" -P -c "$gate_reader" "$config" <<<"$payload" 2>/dev/null)

if [ -z "$fields" ]; then
  echo "[doc-gate] $python_missing — hook skipped." >&2
  exit 0
fi

# `IFS=` on each read: with the default IFS, read strips leading and trailing
# whitespace, so a trigger written as "^refactor " lost the space its author put
# there and then also matched "refactorX". The reader does not squash it either.
{
  IFS= read -r enabled
  IFS= read -r routing_doc
  IFS= read -r trigger
  prompt=$(cat)
} <<<"$fields"

[ "$enabled" = 'yes' ] || exit 0
[ -n "$prompt" ] || exit 0
curly=$(printf '\342\200\231')
[ -n "$trigger" ] || trigger='^[[:space:]]*(please[,:]?[[:space:]]+|can you[[:space:]]+|could you[[:space:]]+|let('\''|'"$curly"')s[[:space:]]+|go[[:space:]]+)?(implement|build|refactor|enhanc|migrat(e|ion)|(add|create) (a |an |new )|new (model|resource|service|endpoint|mutation|field|hook|webhook))'

# The default takes a curly apostrophe too: phones and editors type one.
# Anchor the imperative to the start of a line so "how do I implement X?" and
# "should I refactor Y?" do not trip it -- only directives do.

# A here-string, not `printf | grep`: `grep -q` closes the pipe on its first
# match, printf dies of SIGPIPE, and `pipefail` makes that the pipeline's
# status -- so a prompt over the 64K pipe buffer read as a miss.
grep -qiE -e "$trigger" <<<"$prompt" || exit 0

# Only where conventions exist, never naming a missing file. Unconfigured,
# AGENTS.md or CLAUDE.md counts, the first present named.
if [ -z "$routing_doc" ]; then
  for candidate in AGENTS.md CLAUDE.md; do
    [ -f "$root/$candidate" ] && { routing_doc=$candidate; break; }
  done
fi

if [ -n "$routing_doc" ] && [ -f "$root/$routing_doc" ]; then
  first="read ${routing_doc} → "
elif [ -f "$config" ]; then
  first='read '
else
  exit 0
fi

echo "[doc-gate] Before non-trivial code: ${first}this layer's convention doc → one sibling implementation; mirror it."
