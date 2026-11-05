"""Retrying a `gh` or `kubectl` call through a network flake, never through a real answer.

A call that changes nothing (a GET, `kubectl get`) retries on any transient error, a gateway
502/503/504 included. One that may start something (a dispatch, a POST, `kubectl create`) retries
only when no request reached the server, so a flake never starts a second review. 4xx: never.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar('T')

# Failures before the request went out (a reset while reading the answer is not one).
UNSENT = re.compile(r'TLS handshake timeout|connection refused|(?<!read: )connection reset by peer', re.I)
RESET = re.compile(r'connection reset by peer', re.I)
# gh says `HTTP 503`; kubectl says `Error from server (ServiceUnavailable)` and the like.
GATEWAY = re.compile(r'HTTP 50[234]\b|\((?:ServiceUnavailable|Timeout)\)|Bad Gateway|Gateway Time-?out', re.I)
DELAYS = (1.0, 2.0, 4.0)


def transient(message: str, idempotent: bool) -> bool:
    return bool(UNSENT.search(message) or (idempotent and (GATEWAY.search(message) or RESET.search(message))))


def retrying(call: Callable[[], T], idempotent: bool, sleep: Callable[[float], None] | None = None) -> T:
    """`call()`, retried up to len(DELAYS) times while its RuntimeError is transient."""
    sleep = sleep or time.sleep
    for delay in DELAYS:
        try:
            return call()
        except RuntimeError as exc:
            if not transient(str(exc), idempotent):
                raise
        sleep(delay)
    return call()
