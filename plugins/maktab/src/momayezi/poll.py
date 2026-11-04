"""Waiting for a momayez review: one poll, and the loop the waiter and the channel share."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from . import ledger as ledgers
from .github import Gh, GhError, Target, run_ledger
from .protocol import POLL_BACKOFF, POLL_FIRST, POLL_MAX, WAIT_TIMEOUT

Result = dict[str, Any]


def known(gh: Gh, head: str) -> set[int]:
    """The check runs already on `head`: a review requested now is a run not in this set."""
    return {run['id'] for run in gh.runs(head)}


def check(gh: Gh, target: Target, head: str, seen: set[int]) -> Result | None:
    """The finished review of `head`, or None while it is pending."""
    for run in gh.runs(head):
        if run['id'] in seen or run.get('status') != 'completed':
            continue
        base = {**target.meta(), 'head_sha': head, 'url': run.get('html_url', '')}
        found = run_ledger(run)
        if found is None:
            return {**base, 'status': 'failed', 'conclusion': run.get('conclusion')}
        return {**base, 'status': 'done', 'verdict': found['verdict'], 'ledger': found}
    return None


def intervals() -> Callable[[], float]:
    delay = [POLL_FIRST]

    def step() -> float:
        current = delay[0]
        delay[0] = min(current * POLL_BACKOFF, POLL_MAX)
        return current
    return step


def wait(gh: Gh, target: Target, head: str, seen: set[int], timeout: float = WAIT_TIMEOUT,
         sleep: Callable[[float], None] = time.sleep,
         clock: Callable[[], float] = time.monotonic) -> Result:
    """Poll until the review lands or `timeout` passes. A failed poll is retried, not fatal."""
    deadline = clock() + timeout
    nxt = intervals()
    while True:
        try:
            result = check(gh, target, head, seen)
        except (GhError, ledgers.LedgerError, KeyError, ValueError):
            result = None
        if result:
            return result
        remaining = deadline - clock()
        if remaining <= 0:
            return {**target.meta(), 'head_sha': head, 'status': 'timeout'}
        sleep(min(nxt(), remaining))
