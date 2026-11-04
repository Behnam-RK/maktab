#!/usr/bin/env bash
# Runs a momayezi command (post, prior, wait, channel) on the plugin's own src/.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=find-python.sh source-path=SCRIPTDIR
. "$here/scripts/find-python.sh"
find_python || { echo "momayezi: $python_missing" >&2; exit 1; }

exec "$py" -P -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); from momayezi.cli import main; raise SystemExit(main())' \
  "$here/src" "$@"
