"""Waiting for a momayez review: one poll, and the loop the waiter and the channel share."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from .github import Gh, Target, run_ledger
from .protocol import POLL_BACKOFF, POLL_FIRST, POLL_MAX, WAIT_TIMEOUT

if TYPE_CHECKING:  # pragma: no cover
    from .backend import Backend

Result = dict[str, Any]


def known(gh: Gh, head: str) -> set[int]:
    """The check runs already on `head`: a review requested now is a run not in this set."""
    return {run['id'] for run in gh.runs(head)}


def check(gh: Gh, target: Target, head: str, seen: set[int]) -> Result | None:
    """The review of `head` posted as a new `momayez` check run, or None while it is pending."""
    for run in gh.runs(head):
        if run['id'] in seen or run.get('status') != 'completed':
            continue
        base = {**target.meta(), 'head_sha': head, 'url': run.get('html_url', '')}
        found = run_ledger(run)
        if found is None:
            return {**base, 'status': 'failed', 'conclusion': run.get('conclusion')}
        return {**base, 'status': 'done', 'verdict': found['verdict'], 'ledger': found}
    return None


def summary(result: Result) -> Result:
    """A finished review as `review_status` reports it: done, with a ledger or `failed`."""
    out = {k: result[k] for k in ('pr', 'ref', 'head_sha', 'url', 'job') if k in result}
    if result['status'] == 'done':
        return {'status': 'done', **out, 'ledger': result['ledger'], 'verdict': result['verdict'], 'failed': False}
    why = {k: result[k] for k in ('reason', 'conclusion') if k in result}
    return {'status': 'done', **out, 'failed': True, **why}


def intervals() -> Callable[[], float]:
    delay = [POLL_FIRST]

    def step() -> float:
        current = delay[0]
        delay[0] = min(current * POLL_BACKOFF, POLL_MAX)
        return current
    return step


def wait(backend: Backend, handle: dict[str, Any], timeout: float = WAIT_TIMEOUT,
         sleep: Callable[[float], None] = time.sleep,
         clock: Callable[[], float] = time.monotonic) -> Result:
    """Poll until the review lands or `timeout` passes. A failed poll is retried, not fatal."""
    deadline = clock() + timeout
    nxt = intervals()
    while True:
        try:
            result = backend.check(handle)
        except (RuntimeError, OSError, ValueError, KeyError):  # gh, kubectl or a bad answer
            result = None
        if result:
            return result
        remaining = deadline - clock()
        if remaining <= 0:
            return {**Target.from_meta(handle).meta(), 'head_sha': handle['head_sha'], 'status': 'timeout'}
        sleep(min(nxt(), remaining))
