from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from momayezi.github import Gh, GhError

FIXTURES = Path(__file__).resolve().parent / 'fixtures'
REPO = 'o/r'
HEAD = '2794d3bbb3fd55ebfeba6d8be8ddee4446dfb9df'


def sample() -> dict[str, Any]:
    return json.loads((FIXTURES / 'ledger-round.json').read_text(encoding='utf-8'))


class FakeRunner:
    """Answers `gh` argv by route. A route maps (method, path) to a value, a list of values
    (one per call, the last repeating), or a GhError to raise. Every call is recorded."""

    def __init__(self, routes: dict[tuple[str, str], Any] | None = None):
        self.routes = dict(routes or {})
        self.calls: list[tuple[str, str, Any]] = []

    def __call__(self, args: list[str], stdin: str | None) -> str:
        if args[0] == 'api':
            method, path = args[2], args[3]
        else:
            method, path = args[0], ' '.join(args[1:3])
        body = json.loads(stdin) if stdin else None
        self.calls.append((method, path, body if body is not None else args))
        answer = self.routes.get((method, path), {})
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if isinstance(answer, GhError):
            raise answer
        if isinstance(answer, str):
            return answer
        return json.dumps(copy.deepcopy(answer))

    def sent(self, method: str, path: str) -> list[Any]:
        return [body for m, p, body in self.calls if (m, p) == (method, path)]


def gh(routes: dict[tuple[str, str], Any] | None = None) -> tuple[Gh, FakeRunner]:
    runner = FakeRunner(routes)
    return Gh(REPO, runner), runner


def runs_path(sha: str = HEAD) -> str:
    return f'repos/{REPO}/commits/{sha}/check-runs?check_name=momayez&per_page=100'


def run(ident: int, ledger: dict[str, Any] | None = None, status: str = 'completed',
        text: str | None = None, completed_at: str = '2026-11-04T10:00:00Z') -> dict[str, Any]:
    from momayezi import ledger as ledgers
    from momayezi.protocol import REVIEWER_MARKER
    if text is None and ledger is not None:
        text = ledgers.to_marker(ledger, REVIEWER_MARKER)
    return {'id': ident, 'status': status, 'conclusion': 'neutral', 'html_url': f'https://x/{ident}',
            'completed_at': completed_at, 'output': {'text': text}}
