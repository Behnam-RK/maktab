from __future__ import annotations

import io
import json
import threading

import pytest
from gh_fake import HEAD, REPO, gh, run, runs_path, sample

from momayezi import channel
from momayezi import ledger as ledgers
from momayezi.github import GhError
from momayezi.protocol import EDITOR_MARKER

PULL = f'repos/{REPO}/pulls/4'


class Out(io.StringIO):
    def messages(self):
        return [json.loads(line) for line in self.getvalue().splitlines()]


def server(routes=None, **kw):
    client, runner = gh(routes)
    out = Out()
    return channel.Server(out, gh=lambda: client, **kw), out, runner


def rpc(srv, method, params=None, ident=1):
    srv.handle(json.dumps({'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params or {}}))


def call(srv, out, name, args):
    rpc(srv, 'tools/call', {'name': name, 'arguments': args})
    result = out.messages()[-1]['result']
    text = result['content'][0]['text']
    return (json.loads(text) if not result['isError'] else text), result['isError']


def test_initialize_declares_the_channel_and_pins_an_old_protocol():
    srv, out, _ = server()
    rpc(srv, 'initialize', {'protocolVersion': '2025-03-26'})
    rpc(srv, 'initialize', {'protocolVersion': '2026-07-28'}, ident=2)
    first, second = (m['result'] for m in out.messages())
    assert first['protocolVersion'] == '2025-03-26' and second['protocolVersion'] == '2025-06-18'
    assert first['capabilities'] == {'experimental': {'claude/channel': {}}, 'tools': {}}
    assert 'plugin:maktab:momayez' in first['instructions']


def test_ping_list_unknown_and_garbage():
    srv, out, _ = server()
    rpc(srv, 'ping')
    rpc(srv, 'tools/list', ident=2)
    rpc(srv, 'nope', ident=3)
    srv.handle('{not json')
    srv.handle(json.dumps({'jsonrpc': '2.0', 'method': 'notifications/initialized'}))
    ping, listing, unknown, garbage = out.messages()
    assert ping['result'] == {}
    assert [t['name'] for t in listing['result']['tools']] == ['request_review', 'review_status', 'reply_to_finding']
    assert unknown['error']['code'] == -32601 and garbage['error']['code'] == -32700


def test_tool_errors_go_back_as_tool_results():
    srv, out, _ = server()
    assert call(srv, out, 'bogus', {}) == ('ToolError: unknown tool bogus', True)
    assert call(srv, out, 'review_status', {})[1]
    assert call(srv, out, 'review_status', {'pr': 1, 'ref': 'x'})[1]
    assert 'id is required' in call(srv, out, 'reply_to_finding', {'pr': 4, 'text': 't'})[0]


@pytest.fixture
def no_thread(monkeypatch):
    monkeypatch.setattr(channel.Server, 'watch', lambda self, t, h, s: self.pending.__setitem__((REPO, h), {}))


def test_request_review_on_a_pr_posts_the_editor_ledger_and_presses_the_label(no_thread):
    srv, out, runner = server({('GET', PULL): {'head': {'sha': HEAD}},
                               ('GET', runs_path()): {'check_runs': [run(3, sample()), run(1, sample())]},
                               ('GET', f'repos/{REPO}/issues/4/comments?per_page=100'): [[]]})
    got, error = call(srv, out, 'request_review', {'pr': 4, 'ledger': sample()})
    assert not error and got == {'status': 'requested', 'pr': '4', 'head_sha': HEAD,
                                 'wait': f'momayezi-wait 4 {HEAD} --known 1,3'}
    (comment,) = runner.sent('POST', f'repos/{REPO}/issues/4/comments')
    assert ledgers.from_marker(comment['body'], EDITOR_MARKER) == sample()
    assert runner.sent('POST', f'repos/{REPO}/issues/4/labels') == [{'labels': ['review']}]


def test_request_review_on_a_branch_dispatches_the_workflow(no_thread):
    srv, out, runner = server({('GET', f'repos/{REPO}/commits/feat'): {'sha': HEAD},
                               ('GET', runs_path()): {'check_runs': []}})
    got, error = call(srv, out, 'request_review', {'ref': 'feat', 'ledger': ledgers.dumps(sample())})
    assert not error and got['wait'] == f'momayezi-wait feat {HEAD}'
    argv = runner.calls[-1][2]
    assert argv[:5] == ['workflow', 'run', 'momayez.yaml', '--repo', REPO]
    assert argv[6] == 'ref=feat' and ledgers.loads(argv[8].removeprefix('ledger=')) == sample()


def test_request_review_rejects_a_bad_ledger():
    srv, out, runner = server()
    text, error = call(srv, out, 'request_review', {'pr': 4, 'ledger': {'version': 'v1'}})
    assert error and 'invalid ledger' in text and not runner.calls


def test_review_status_pending_done_and_none(no_thread):
    routes = {('GET', PULL): {'head': {'sha': HEAD}}, ('GET', runs_path()): {'check_runs': []},
              ('GET', f'repos/{REPO}/issues/4/comments?per_page=100'): [[]]}
    srv, out, runner = server(routes)
    assert call(srv, out, 'review_status', {'pr': 4})[0]['status'] == 'none'
    call(srv, out, 'request_review', {'pr': 4, 'ledger': sample()})
    assert call(srv, out, 'review_status', {'pr': 4})[0]['status'] == 'pending'
    srv.pending.clear()
    runner.routes[('GET', runs_path())] = {'check_runs': [run(2, sample())]}
    done = call(srv, out, 'review_status', {'pr': 4})[0]
    assert done['status'] == 'done' and done['ledger'] == sample()


def test_reply_to_finding():
    srv, out, runner = server({('GET', f'repos/{REPO}/pulls/4/comments?per_page=100'): [[]]})
    assert call(srv, out, 'reply_to_finding', {'pr': 4, 'id': 'F2', 'text': 'no'})[0] == {
        'status': 'posted', 'on': 'summary'}


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_poll_once_emits_finished_reviews_drops_stale_and_survives_errors():
    clock = Clock()
    srv, out, runner = server({('GET', runs_path()): [GhError('HTTP 502'), {'check_runs': [run(2, sample())]}]},
                              clock=clock)
    srv.pending[(REPO, HEAD)] = {'target': channel.Target(pr=4), 'seen': {1}, 'since': 0.0}
    srv.pending[(REPO, 'old')] = {'target': channel.Target(pr=4), 'seen': set(), 'since': -1e9}
    srv.poll_once()
    assert list(srv.pending) == [(REPO, HEAD)] and not out.getvalue()
    srv.poll_once()
    (event,) = out.messages()
    assert event['method'] == 'notifications/claude/channel'
    assert event['params']['meta'] == {'pr': '4', 'head_sha': HEAD, 'verdict': 'findings'}
    assert ledgers.loads(event['params']['content']) == sample() and not srv.pending


def test_a_failed_review_is_pushed_as_a_failure():
    srv, out, _ = server()
    srv.emit({'ref': 'b', 'head_sha': HEAD, 'status': 'failed', 'url': 'u'})
    params = out.messages()[0]['params']
    assert params['meta'] == {'ref': 'b', 'head_sha': HEAD, 'verdict': 'failed'}
    assert json.loads(params['content'])['url'] == 'u'


def test_the_poller_runs_only_while_something_is_pending():
    slept = threading.Event()
    srv, out, _ = server({('GET', runs_path()): {'check_runs': [run(2, sample())]}},
                         sleep=lambda s: slept.set())
    srv.watch(channel.Target(pr=4), HEAD, set())
    srv.poller.join(5)
    assert slept.is_set() and srv.poller is None and not srv.pending
    assert out.messages()[0]['params']['meta']['verdict'] == 'findings'


def test_the_poller_keeps_going_while_a_review_is_pending():
    sleeps = []
    srv, out, _ = server({('GET', runs_path()): [{'check_runs': []}, {'check_runs': [run(2, sample())]}]},
                         sleep=sleeps.append)
    srv.watch(channel.Target(pr=4), HEAD, set())
    srv.poller.join(5)
    assert sleeps == [15.0, 22.5] and len(out.messages()) == 1


def test_a_second_watch_reuses_a_live_poller():
    gate = threading.Event()
    srv, out, _ = server({('GET', runs_path()): {'check_runs': [run(2, sample())]}},
                         sleep=lambda s: gate.wait(5))
    srv.watch(channel.Target(pr=4), HEAD, set())
    first = srv.poller
    srv.watch(channel.Target(pr=4), HEAD, set())
    assert srv.poller is first
    gate.set()
    first.join(5)
    assert srv.poller is None


def test_the_gh_client_is_made_once():
    made = []
    srv = channel.Server(Out(), gh=lambda: made.append(1) or 'client')
    assert srv.gh == 'client' and srv.gh == 'client' and made == [1]


def test_serve_answers_each_line(monkeypatch):
    out = Out()
    lines = io.StringIO('\n' + json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'ping'}) + '\n')
    assert channel.serve(lines, out) == 0
    assert out.messages() == [{'jsonrpc': '2.0', 'id': 1, 'result': {}}]
