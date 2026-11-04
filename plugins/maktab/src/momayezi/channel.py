"""The momayez channel: an MCP stdio server that requests remote reviews and pushes them back.

Tools work in any session. The push (`notifications/claude/channel`) reaches Claude only when
the session opted the plugin in with `--channels`; the skill's waiter covers the rest.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable
from typing import IO, Any

from . import ledger as ledgers
from . import poll
from .github import Gh, Target, run_ledger
from .protocol import CAP, DISPATCH_CAP, EDITOR_MARKER, EDITOR_RESET, LABEL, PENDING_TTL, WORKFLOW

PROTOCOLS = ('2024-11-05', '2025-03-26', '2025-06-18')
INSTRUCTIONS = (
    'momayez reviews arrive as <channel source="plugin:maktab:momayez" pr|ref="..." head_sha="..." '
    'verdict="...">, the body being the reviewer ledger JSON (or the failure). Hand it to the running '
    'maktab:momayezi loop, which merges it by finding id; ignore a second event for the same head_sha.'
)
TARGET = {
    'pr': {'type': 'integer', 'description': 'PR number'},
    'ref': {'type': 'string', 'description': 'branch, when there is no PR'},
}
TOOLS = [
    {
        'name': 'request_review',
        'description': 'Ask the remote momayez reviewer to review the pushed head of a PR or branch. '
                       'Attach the editor ledger (omit it in round 1) so wont-fix and disputed reasons '
                       'carry over. Returns the head and the `momayezi-wait` command to run as the waiter.',
        'inputSchema': {'type': 'object',
                        'properties': {**TARGET, 'ledger': {'type': ['object', 'string']}}},
    },
    {
        'name': 'review_status',
        'description': 'pending | done | none for the current head of a PR or branch, with the newest '
                       'ledger on it (if any); `failed` marks a finished run that carried no ledger.',
        'inputSchema': {'type': 'object', 'properties': TARGET},
    },
    {
        'name': 'reply_to_finding',
        'description': "Reply to a momayez finding on its inline thread, or on the PR when it was outside the diff.",
        'inputSchema': {'type': 'object', 'required': ['pr', 'id', 'text'],
                        'properties': {'pr': TARGET['pr'], 'id': {'type': 'string', 'pattern': '^F[1-9][0-9]*$'},
                                       'text': {'type': 'string'}}},
    },
]


class ToolError(Exception):
    pass


def target_of(args: dict[str, Any]) -> Target:
    pr, ref = args.get('pr'), args.get('ref')
    if bool(pr) == bool(ref):
        raise ToolError('pass exactly one of pr or ref')
    return Target(pr=int(pr)) if pr else Target(ref=str(ref))


class Server:
    def __init__(self, out: IO[str], gh: Callable[[], Gh] = Gh.here,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        self.out, self.make_gh, self.sleep, self.clock = out, gh, sleep, clock
        self.lock = threading.Lock()
        self.pending: dict[tuple[str, str], dict[str, Any]] = {}
        self.poller: threading.Thread | None = None
        self._gh: Gh | None = None

    @property
    def gh(self) -> Gh:
        if self._gh is None:
            self._gh = self.make_gh()
        return self._gh

    def send(self, message: dict[str, Any]) -> None:
        with self.lock:
            self.out.write(json.dumps({'jsonrpc': '2.0', **message}) + '\n')
            self.out.flush()

    # --- JSON-RPC

    def handle(self, line: str) -> None:
        try:
            message = json.loads(line)
        except ValueError:
            self.send({'id': None, 'error': {'code': -32700, 'message': 'parse error'}})
            return
        method, ident = message.get('method'), message.get('id')
        if ident is None:
            return  # notifications: initialized, cancelled; nothing to answer
        params = message.get('params') or {}
        if method == 'initialize':
            asked = params.get('protocolVersion')
            result = {
                'protocolVersion': asked if asked in PROTOCOLS else PROTOCOLS[-1],
                'capabilities': {'experimental': {'claude/channel': {}}, 'tools': {}},
                'serverInfo': {'name': 'momayez', 'version': '1'},
                'instructions': INSTRUCTIONS,
            }
        elif method == 'ping':
            result = {}
        elif method == 'tools/list':
            result = {'tools': TOOLS}
        elif method == 'tools/call':
            result = self.call(params.get('name'), params.get('arguments') or {})
        else:
            self.send({'id': ident, 'error': {'code': -32601, 'message': f'unknown method {method}'}})
            return
        self.send({'id': ident, 'result': result})

    def call(self, name: str | None, args: dict[str, Any]) -> dict[str, Any]:
        tools = {'request_review': self.request_review, 'review_status': self.review_status,
                 'reply_to_finding': self.reply_to_finding}
        try:
            if name not in tools:
                raise ToolError(f'unknown tool {name}')
            text, error = json.dumps(tools[name](args)), False
        except Exception as exc:  # every failure goes back to the model as a tool error
            text, error = f'{type(exc).__name__}: {exc}', True
        return {'content': [{'type': 'text', 'text': text}], 'isError': error}

    # --- tools

    def request_review(self, args: dict[str, Any]) -> dict[str, Any]:
        target = target_of(args)
        raw = args.get('ledger')
        if raw in (None, ''):
            editor = None  # round 1: nothing to carry over
        elif isinstance(raw, str):
            editor = ledgers.loads(raw)
        else:
            editor = ledgers.validate(raw)
        gh = self.gh
        head = gh.head(target)
        seen = poll.known(gh, head)
        if target.pr:
            # Naming the head keeps each reset edit distinct, so `updated_at` always moves.
            body = f'momayezi editor ledger: a new loop at {head}, reviewed from scratch\n{EDITOR_RESET}'
            if editor:
                prefix = f'momayezi editor ledger (round {editor["round"]})\n'
                fitted = ledgers.fit(editor, EDITOR_MARKER, CAP - ledgers.size(prefix))
                body = prefix + ledgers.to_marker(fitted, EDITOR_MARKER)
            gh.upsert_comment(target.pr, EDITOR_MARKER, body)
            gh.press(target.pr, LABEL)
        else:
            sent = ledgers.dumps(ledgers.fit(editor, EDITOR_MARKER, DISPATCH_CAP)) if editor else ''
            gh.dispatch(WORKFLOW, {'ref': target.ref, 'ledger': sent})
        self.watch(target, head, seen)
        known = ','.join(str(i) for i in sorted(seen))
        wait = f'momayezi-wait {target.pr or target.ref} {head}' + (f' --known {known}' if known else '')
        return {'status': 'requested', **target.meta(), 'head_sha': head, 'wait': wait}

    def review_status(self, args: dict[str, Any]) -> dict[str, Any]:
        target = target_of(args)
        head = self.gh.head(target)
        runs = self.gh.runs(head)
        out: dict[str, Any] = {**target.meta(), 'head_sha': head}
        done = [r for r in runs if r.get('status') == 'completed']
        for run in done:
            found = run_ledger(run)
            if found:
                out.update(ledger=found, verdict=found['verdict'], url=run.get('html_url', ''))
                break
        if (self.gh.repo, head) in self.pending or any(r.get('status') != 'completed' for r in runs):
            return {'status': 'pending', **out}
        if not done:
            return {'status': 'none', **out}
        return {'status': 'done', **out, 'failed': run_ledger(done[0]) is None}

    def reply_to_finding(self, args: dict[str, Any]) -> dict[str, Any]:
        for key in ('pr', 'id', 'text'):
            if not args.get(key):
                raise ToolError(f'{key} is required')
        where = self.gh.reply(int(args['pr']), str(args['id']), str(args['text']))
        return {'status': 'posted', 'on': where}

    # --- polling: only while something is pending

    def watch(self, target: Target, head: str, seen: set[int]) -> None:
        with self.lock:
            self.pending[(self.gh.repo, head)] = {'target': target, 'seen': seen, 'since': self.clock()}
            if self.poller is None or not self.poller.is_alive():
                self.poller = threading.Thread(target=self.poll, daemon=True)
                self.poller.start()

    def poll_once(self) -> None:
        for key, entry in list(self.pending.items()):
            _, head = key
            if self.clock() - entry['since'] > PENDING_TTL:
                self.pending.pop(key, None)
                continue
            try:
                result = poll.check(self.gh, entry['target'], head, entry['seen'])
            except Exception:  # a transient gh failure; the next poll retries
                continue
            if result:
                self.pending.pop(key, None)
                self.emit(result)

    def poll(self) -> None:
        nxt = poll.intervals()
        while True:
            self.sleep(nxt())
            self.poll_once()
            with self.lock:
                if not self.pending:
                    self.poller = None
                    return

    def emit(self, result: dict[str, Any]) -> None:
        meta = {k: str(result[k]) for k in ('pr', 'ref', 'head_sha') if k in result}
        meta['verdict'] = result.get('verdict') or result['status']
        content = ledgers.dumps(result['ledger']) if 'ledger' in result else json.dumps(result)
        self.send({'method': 'notifications/claude/channel', 'params': {'content': content, 'meta': meta}})


def serve(stdin: IO[str] = sys.stdin, stdout: IO[str] = sys.stdout, **kw: Any) -> int:
    server = Server(stdout, **kw)
    for line in stdin:
        if line.strip():
            server.handle(line)
    return 0
