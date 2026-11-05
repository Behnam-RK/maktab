from __future__ import annotations

import io
import json
import threading

import pytest
from gh_fake import HEAD, REPO, gh, run, runs_path, sample

from momayezi import channel, config
from momayezi import ledger as ledgers
from momayezi.backend import GhLabel
from momayezi.github import GhError
from momayezi.protocol import EDITOR_MARKER, EDITOR_RESET

PULL = f'repos/{REPO}/pulls/4'


class Out(io.StringIO):
    def messages(self):
        return [json.loads(line) for line in self.getvalue().splitlines()]


LABEL_ALL = config.Settings('gh-label', 'all')


def server(routes=None, settings=LABEL_ALL, **kw):
    client, runner = gh(routes)
    out = Out()
    return channel.Server(out, gh=lambda: client, settings=lambda: settings, **kw), out, runner


def handle(seen=(), head=HEAD):
    return {'backend': 'gh-label', 'pr': '4', 'head_sha': head, 'known': sorted(seen)}


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
    monkeypatch.setattr(channel.Server, 'watch',
                        lambda self, b, h, post=False: self.pending.__setitem__((REPO, h['head_sha']), {}))


def test_request_review_on_a_pr_posts_the_editor_ledger_and_presses_the_label(no_thread):
    srv, out, runner = server({('GET', PULL): {'head': {'sha': HEAD}},
                               ('GET', runs_path()): {'check_runs': [run(3, sample()), run(1, sample())]},
                               ('GET', f'repos/{REPO}/issues/4/comments?per_page=100'): [[]]})
    got, error = call(srv, out, 'request_review', {'pr': 4, 'ledger': sample()})
    assert not error and got == {'status': 'requested', 'pr': '4', 'head_sha': HEAD, 'backend': 'gh-label',
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
    text, error = call(srv, out, 'request_review', {'pr': 4, 'ledger': {'version': 'v2'}})
    assert error and 'invalid ledger' in text and not runner.calls


def test_review_status_pending_done_and_none(no_thread):
    routes = {('GET', PULL): {'head': {'sha': HEAD}}, ('GET', runs_path()): {'check_runs': []},
              ('GET', f'repos/{REPO}/issues/4/comments?per_page=100'): [[]]}
    srv, out, runner = server(routes)
    assert call(srv, out, 'review_status', {'pr': 4})[0] == {'status': 'none', 'pr': '4', 'head_sha': HEAD}
    call(srv, out, 'request_review', {'pr': 4, 'ledger': sample()})
    assert call(srv, out, 'review_status', {'pr': 4})[0]['status'] == 'pending'
    srv.pending.clear()
    runner.routes[('GET', runs_path())] = {'check_runs': [run(2, sample())]}
    done = call(srv, out, 'review_status', {'pr': 4})[0]
    assert done['status'] == 'done' and done['ledger'] == sample() and done['failed'] is False


def test_review_status_sees_runs_it_did_not_request_and_keeps_the_last_ledger():
    older = dict(sample(), round=1)
    srv, out, _ = server({('GET', PULL): {'head': {'sha': HEAD}},
                          ('GET', runs_path()): {'check_runs': [run(3, status='in_progress'), run(1, older)]}})
    got = call(srv, out, 'review_status', {'pr': 4})[0]
    assert got['status'] == 'pending' and got['ledger'] == older


def test_review_status_flags_a_run_that_carried_no_ledger():
    srv, out, _ = server({('GET', PULL): {'head': {'sha': HEAD}},
                          ('GET', runs_path()): {'check_runs': [run(5, text='crashed'), run(1, sample())]}})
    got = call(srv, out, 'review_status', {'pr': 4})[0]
    assert got['status'] == 'done' and got['failed'] is True and got['ledger'] == sample()


def test_round_one_requests_carry_no_ledger_and_reset_the_pr_history(no_thread):
    stale = {'id': 9, 'body': f'<!-- {EDITOR_MARKER} {{}} -->'}
    srv, out, runner = server({('GET', PULL): {'head': {'sha': HEAD}}, ('GET', runs_path()): {'check_runs': []},
                               ('GET', f'repos/{REPO}/issues/4/comments?per_page=100'): [[[stale]]],
                               ('GET', f'repos/{REPO}/commits/feat'): {'sha': HEAD}})
    assert not call(srv, out, 'request_review', {'pr': 4})[1]
    (body,) = runner.sent('PATCH', f'repos/{REPO}/issues/comments/9')
    assert body['body'].endswith(EDITOR_RESET) and HEAD in body['body']
    assert not call(srv, out, 'request_review', {'ref': 'feat', 'ledger': ''})[1]
    assert runner.calls[-1][2][-1] == 'ledger='


def test_the_editor_comment_fits_with_its_prefix(no_thread, monkeypatch):
    sizes = []
    real = ledgers.fit
    monkeypatch.setattr(ledgers, 'fit', lambda l, k, cap=65535: sizes.append(cap) or real(l, k, cap))
    srv, out, runner = server({('GET', PULL): {'head': {'sha': HEAD}}, ('GET', runs_path()): {'check_runs': []},
                               ('GET', f'repos/{REPO}/issues/4/comments?per_page=100'): [[]]})
    call(srv, out, 'request_review', {'pr': 4, 'ledger': sample()})
    (body,) = runner.sent('POST', f'repos/{REPO}/issues/4/comments')
    assert sizes == [65535 - len('momayezi editor ledger (round 2)\n')]
    assert body['body'].startswith('momayezi editor ledger (round 2)\n<!-- ')


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
    label = GhLabel(srv.gh)
    srv.pending[(REPO, HEAD)] = {'backend': label, 'handle': handle({1}), 'post': False, 'since': 0.0}
    srv.pending[(REPO, 'old')] = {'backend': label, 'handle': handle(), 'post': False, 'since': -1e9}
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
    srv.watch(GhLabel(srv.gh), handle())
    srv.poller.join(5)
    assert slept.is_set() and srv.poller is None and not srv.pending
    assert out.messages()[0]['params']['meta']['verdict'] == 'findings'


def test_the_poller_keeps_going_while_a_review_is_pending():
    sleeps = []
    srv, out, _ = server({('GET', runs_path()): [{'check_runs': []}, {'check_runs': [run(2, sample())]}]},
                         sleep=sleeps.append)
    srv.watch(GhLabel(srv.gh), handle())
    srv.poller.join(5)
    assert sleeps == [15.0, 22.5] and len(out.messages()) == 1


def test_a_second_watch_reuses_a_live_poller():
    gate = threading.Event()
    srv, out, _ = server({('GET', runs_path()): {'check_runs': [run(2, sample())]}},
                         sleep=lambda s: gate.wait(5))
    srv.watch(GhLabel(srv.gh), handle())
    first = srv.poller
    srv.watch(GhLabel(srv.gh), handle())
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


class Stub:
    """A backend that records requests and answers checks from a list."""

    def __init__(self, name='k8s-job', results=(None,)):
        self.name, self.results, self.requested = name, list(results), []

    def request(self, target, head, editor):
        self.requested.append((target, head, editor))
        return {'backend': self.name, **target.meta(), 'head_sha': head, 'job': 'j', 'namespace': 'ns'}

    def check(self, handle):
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]

    def status(self, target, head):
        return {'status': 'none', **target.meta(), 'head_sha': head}


def stub_server(settings, stub, routes=None):
    return server({('GET', PULL): {'head': {'sha': HEAD}}, **(routes or {})}, settings=settings,
                  make=lambda s, g: stub)


def test_a_direct_request_writes_nothing_to_the_pr_and_hands_back_the_handle(no_thread):
    stub = Stub()
    srv, out, runner = stub_server(config.Settings('k8s-job', 'none'), stub)
    got, error = call(srv, out, 'request_review', {'pr': 4, 'ledger': sample()})
    assert not error and got['backend'] == 'k8s-job' and stub.requested[0][2] == sample()
    assert '--handle' in got['wait'] and '"job":"j"' in got['wait']
    assert [c for c in runner.calls if c[0] != 'GET'] == []
    assert call(srv, out, 'reply_to_finding', {'pr': 4, 'id': 'F1', 'text': 'no'})[0]['status'] == 'skipped'
    assert call(srv, out, 'review_status', {'pr': 4})[0]['status'] == 'pending'


def test_k8s_with_pr_comments_posts_the_review_without_a_check_run(no_thread, monkeypatch):
    seen = {}
    monkeypatch.setattr(channel.Server, 'watch', lambda self, b, h, post=False: seen.update(post=post))
    srv, out, _ = stub_server(config.Settings('k8s-job', 'all'), Stub(),
                              {('GET', f'repos/{REPO}/issues/4/comments?per_page=100'): [[]]})
    call(srv, out, 'request_review', {'pr': 4})
    assert seen == {'post': True}
    srv, out, _ = stub_server(config.Settings('gh-dispatch', 'all'), Stub('gh-dispatch'),
                              {('GET', f'repos/{REPO}/issues/4/comments?per_page=100'): [[]]})
    call(srv, out, 'request_review', {'pr': 4})
    assert seen == {'post': False}


def test_the_poller_posts_a_finished_direct_review_once(monkeypatch):
    published = []
    monkeypatch.setattr(channel.post, 'publish',
                        lambda gh, target, ledger, with_check_run=True: published.append((target, with_check_run)))
    done = {'pr': '4', 'head_sha': HEAD, 'status': 'done', 'verdict': 'findings', 'ledger': sample()}
    failed = {'pr': '4', 'head_sha': 'f' * 40, 'status': 'failed', 'reason': 'gone'}
    srv, out, _ = server()
    srv.pending[(REPO, HEAD)] = {'backend': Stub(results=[done]), 'handle': {}, 'post': True, 'since': srv.clock()}
    srv.pending[(REPO, 'f' * 40)] = {'backend': Stub(results=[failed]), 'handle': {}, 'post': True, 'since': srv.clock()}
    srv.poll_once()
    assert published == [(channel.Target(pr=4), False)] and len(out.messages()) == 2


def test_a_failed_post_still_delivers_the_ledger(monkeypatch):
    def broken(*a, **k):
        raise GhError('HTTP 403')
    monkeypatch.setattr(channel.post, 'publish', broken)
    result = {'pr': '4', 'head_sha': HEAD, 'status': 'done', 'verdict': 'findings', 'ledger': sample()}
    srv, out, _ = server()
    srv.pending[(REPO, HEAD)] = {'backend': Stub(results=[result]), 'handle': {}, 'post': True,
                                 'since': srv.clock()}
    srv.poll_once()
    (event,) = out.messages()
    assert event['params']['meta']['post_error'] == 'GhError: HTTP 403'
    assert ledgers.loads(event['params']['content']) == sample()


def test_a_bad_config_is_a_tool_error():
    def bad():
        raise config.ConfigError('unknown reviewer backend')
    srv, out, _ = server({('GET', PULL): {'head': {'sha': HEAD}}})
    srv.settings = bad
    text, error = call(srv, out, 'request_review', {'pr': 4})
    assert error and text == 'ConfigError: unknown reviewer backend'
