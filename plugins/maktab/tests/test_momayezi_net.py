from __future__ import annotations

import subprocess

import pytest

from momayezi import github, k8s, net
from momayezi.github import GhError


def flaky(*errors):
    calls = []

    def call():
        calls.append(1)
        if len(calls) <= len(errors):
            raise errors[len(calls) - 1]
        return 'ok'
    return call, calls


@pytest.mark.parametrize('message, idempotent, retried', [
    ('net/http: TLS handshake timeout', False, True),
    ('read: connection reset by peer', False, True),
    ('dial tcp: connection refused', True, True),
    ('HTTP 503: Service Unavailable', True, True),
    ('HTTP 502: Bad Gateway', False, False),
    ('HTTP 404: Not Found', True, False),
    ('HTTP 422: Unprocessable', True, False),
])
def test_only_transient_errors_retry(message, idempotent, retried):
    call, calls = flaky(GhError(message))
    slept = []
    if retried:
        assert net.retrying(call, idempotent, slept.append) == 'ok'
        assert calls == [1, 1] and slept == [1.0]
    else:
        with pytest.raises(GhError):
            net.retrying(call, idempotent, slept.append)
        assert calls == [1] and slept == []


def test_three_retries_then_the_error_stands():
    error = GhError('HTTP 504')
    call, calls = flaky(error, error, error, error)
    slept = []
    with pytest.raises(GhError):
        net.retrying(call, True, slept.append)
    assert len(calls) == 4 and slept == [1.0, 2.0, 4.0]


@pytest.mark.parametrize('args, read', [
    (['api', '-X', 'GET', 'x'], True),
    (['api', 'x'], True),
    (['api', '-X', 'POST', 'x'], False),
    (['workflow', 'run', 'w'], False),
    (['run', 'download', '1'], True),
])
def test_gh_reads(args, read):
    assert github.reads(args) is read


@pytest.mark.parametrize('args, name', [
    (['--context', 'c', '-n', 'ns', 'get', 'job'], 'get'),
    (['-n', 'ns', 'create', '-f', '-'], 'create'),
    ([], ''),
])
def test_kubectl_verb(args, name):
    assert k8s.verb(args) == name


def test_run_gh_and_kubectl_retry_a_gateway_read(monkeypatch):
    answers = [subprocess.CompletedProcess([], 1, '', 'HTTP 503'), subprocess.CompletedProcess([], 0, 'ok', '')]
    monkeypatch.setattr(net.time, 'sleep', lambda s: None)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: answers.pop(0))
    assert github.run_gh(['api', 'x']) == 'ok'
    answers[:] = [subprocess.CompletedProcess([], 1, '', 'connection refused'),
                  subprocess.CompletedProcess([], 0, 'made', '')]
    assert k8s.run_kubectl(['-n', 'ns', 'create', '-f', '-']) == 'made'
