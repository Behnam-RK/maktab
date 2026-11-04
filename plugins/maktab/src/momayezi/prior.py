"""momayezi-prior: the newest ledger a new review round should start from."""

from __future__ import annotations

import json
import os
import sys

from . import ledger as ledgers
from .github import Gh, Target, run_ledger
from .protocol import EDITOR_MARKER


def from_pr(gh: Gh, pr: int) -> ledgers.Ledger | None:
    """The last `momayez` run on the PR's commits, or the editor's sticky ledger if newer."""
    best, when = None, ''
    commits = gh.api(f'repos/{{repo}}/pulls/{pr}/commits?per_page=100', pages=True)
    for commit in reversed(commits):
        done = [(r, run_ledger(r)) for r in gh.runs(commit['sha']) if r.get('status') == 'completed']
        done = [(r, found) for r, found in done if found]
        if done:
            run, best = done[0]
            when = run.get('completed_at') or ''
            break
    for comment in gh.comments(pr):
        try:
            found = ledgers.from_marker(comment['body'], EDITOR_MARKER)
        except ledgers.LedgerError as exc:
            print(f'momayezi-prior: skipping comment {comment["id"]}: {exc}', file=sys.stderr)
            continue
        stamp = comment.get('updated_at') or ''
        if found and stamp > when:
            best, when = found, stamp
    return best


def from_dispatch(env: dict[str, str] | None = None) -> ledgers.Ledger | None:
    """A branch run's prior is the `ledger` input it was dispatched with."""
    path = (env if env is not None else os.environ).get('GITHUB_EVENT_PATH')
    if not path:
        return None
    with open(path, encoding='utf-8') as handle:
        event = json.load(handle)
    text = ((event.get('inputs') or {}).get('ledger') or '').strip()
    return ledgers.loads(text) if text else None


def find(gh: Gh, target: Target) -> ledgers.Ledger | None:
    return from_pr(gh, target.pr) if target.pr else from_dispatch()
