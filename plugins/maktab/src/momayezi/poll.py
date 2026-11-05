"""Waiting for a momayez review: one poll, and the loop the waiter and the channel share."""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from . import failure as failures
from .github import Gh, Target, run_ledger
from .protocol import POLL_BACKOFF, POLL_FIRST, POLL_MAX, WAIT_TIMEOUT

if TYPE_CHECKING:  # pragma: no cover
    from .backend import Backend

Result = dict[str, Any]


def now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime | None = None) -> str:
    return (moment or now()).strftime('%Y-%m-%dT%H:%M:%SZ')


def _at(text: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(text).replace('Z', '+00:00')) if text else None
    except ValueError:
        return None


def pending(base: Result, phase: str, since: object = None, started: object = None,
            reason: str = '') -> Result:
    """A review still on its way: `phase` is queued or running, timed by the backend's stamps
    (`since` it was requested or created, `started` running), seconds as of now."""
    clock, begun, queued = now(), _at(started), _at(since)
    out = {**base, 'status': 'pending', 'phase': phase,
           'queued_for': int(((begun or clock) - queued).total_seconds()) if queued else 0,
           'ran_for': int((clock - begun).total_seconds()) if begun else 0}
    if reason:
        out['reason'] = reason
    return out


def known(gh: Gh, head: str) -> set[int]:
    """The check runs already on `head`: a review requested now is a run not in this set."""
    return {run['id'] for run in gh.runs(head)}


def check(gh: Gh, target: Target, head: str, seen: set[int], since: str = '') -> Result:
    """The review of `head` posted as a new `momayez` check run, else a pending result: queued
    until a new run is in progress."""
    opened = None
    for run in gh.runs(head):
        if run['id'] in seen:
            continue
        if run.get('status') != 'completed':
            opened = opened or run
            continue
        base = {**target.meta(), 'head_sha': head, 'url': run.get('html_url', '')}
        found = run_ledger(run)
        if found is None:
            why = failures.from_text((run.get('output') or {}).get('text')) or {'status': 'failed'}
            return {**base, **why, 'conclusion': run.get('conclusion')}
        return {**base, 'status': 'done', 'verdict': found['verdict'], 'ledger': found}
    base = {**target.meta(), 'head_sha': head}
    if opened and opened.get('status') == 'in_progress':
        return pending(base, 'running', since, opened.get('started_at'))
    return pending(base, 'queued', since)


def reviewed(found: dict[str, Any], head: str) -> bool:
    """Whether a ledger is the review of `head`: of it, or of the same change rebased."""
    return head in (found['target']['head_sha'], found['target'].get('rebased_from'))


def summary(result: Result) -> Result:
    """A finished review as `review_status` reports it: done, with a ledger or `failed`."""
    out = {k: result[k] for k in ('pr', 'ref', 'head_sha', 'url', 'job') if k in result}
    if result['status'] == 'done':
        return {'status': 'done', **out, 'ledger': result['ledger'], 'verdict': result['verdict'], 'failed': False}
    why = {k: result[k] for k in ('reason', 'conclusion', 'resets_at') if k in result}
    if result['status'] == 'limited':
        why['limited'] = True
    return {'status': 'done', **out, 'failed': True, **why}


def intervals() -> Callable[[], float]:
    delay = [POLL_FIRST]

    def step() -> float:
        current = delay[0]
        delay[0] = min(current * POLL_BACKOFF, POLL_MAX)
        return current
    return step


TIMING = ('phase', 'queued_for', 'ran_for', 'reason')


def wait(backend: Backend, handle: dict[str, Any], timeout: float = WAIT_TIMEOUT,
         queue_timeout: float | None = None, sleep: Callable[[float], None] = time.sleep,
         clock: Callable[[], float] = time.monotonic) -> Result:
    """Poll until the review lands, `timeout` passes, or it has sat queued `queue_timeout`
    seconds. A failed poll is retried, not fatal. A timeout says the phase it stopped in."""
    deadline = clock() + timeout
    nxt = intervals()
    last: Result = {}
    while True:
        try:
            result = backend.check(handle)
        except (RuntimeError, OSError, ValueError, KeyError):  # gh, kubectl or a bad answer
            result = None
        if result and result['status'] != 'pending':
            return {**result, 'phase': 'done'}
        last = result or last
        stuck = (queue_timeout is not None and last.get('phase') == 'queued'
                 and last.get('queued_for', 0) >= queue_timeout)
        remaining = deadline - clock()
        if remaining <= 0 or stuck:
            return {**Target.from_meta(handle).meta(), 'head_sha': handle['head_sha'], 'status': 'timeout',
                    **{k: last[k] for k in TIMING if k in last}}
        sleep(min(nxt(), remaining))
