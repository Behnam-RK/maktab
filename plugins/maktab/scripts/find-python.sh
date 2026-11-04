# shellcheck shell=bash disable=SC2034,SC2015,SC2016
# Sourced, never executed: sets $py to a Python >= 3.12 or returns 1.
# No `set -e` here — the doc-gate hook must survive a miss and exit 0.
find_python() {
  py=''
  local c
  for c in "${PYTHON:-}" "$(command -v uv >/dev/null 2>&1 && uv python find '>=3.12' 2>/dev/null)" \
           python3.14 python3.13 python3.12 python3; do
    [ -n "$c" ] && command -v "$c" >/dev/null 2>&1 || continue
    "$c" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null || continue
    py=$c
    return 0
  done
  return 1
}
python_missing='needs python3 3.12+ (set $PYTHON, or `uv python install 3.12`)'
