from __future__ import annotations

import json
import shlex
from pathlib import Path

import pytest
from gh_fake import HEAD, REPO, FakeRunner, gh, run, runs_path, sample

from momayezi import backend
from momayezi import ledger as ledgers
from momayezi.backend import GhDispatch, GhLabel
from momayezi.config import K8s, Settings
from momayezi.github import Gh, GhError, Target
from momayezi.k8s import K8sJob

PR = Target(pr=4)
DISPATCH = f'repos/{REPO}/actions/workflows/momayez.yaml/dispatches'
RUN = f'repos/{REPO}/actions/runs/7'
ARTIFACTS = f'repos/{REPO}/actions/runs/7/artifacts'
LISTED = f'repos/{REPO}/actions/workflows/momayez.yaml/runs?event=workflow_dispatch&per_page=50'


class Downloads(FakeRunner):
    """`gh run download` writes `files` into the -D directory."""

    def __init__(self, routes=None, files=None):
        super().__init__(routes)
        self.files = files or {}

    def __call__(self, args, stdin):
        out = super().__call__(args, stdin)
        if args[:2] == ['run', 'download']:
            where = Path(args[args.index('-D') + 1])
            for name, text in self.files.items():
                (where / name).write_text(text, encoding='utf-8')
        return out


def dispatch_client(routes=None, files=None):
    runner = Downloads({('GET', f'repos/{REPO}'): {'default_branch': 'develop'},
                        ('POST', DISPATCH): {'workflow_run_id': 7}, **(routes or {})}, files)
    return Gh(REPO, runner), runner


def test_dispatch_names_the_pr_head_and_ledger_and_returns_the_run():
    client, runner = dispatch_client({('GET', runs_path()): {'check_runs': [run(2)]}})
    handle = GhDispatch(client).request(PR, HEAD, sample())
    (body,) = runner.sent('POST', DISPATCH)
    assert body['ref'] == 'develop' and body['return_run_details'] is True
    assert body['inputs'] == {'pr': '4', 'head': HEAD, 'ledger': ledgers.dumps(sample()), 'post': 'true'}
    assert handle == {'backend': 'gh-dispatch', 'pr': '4', 'head_sha': HEAD, 'run_id': 7, 'post': True,
                      'known': [2]}


def test_a_direct_dispatch_skips_the_check_runs_and_says_post_false():
    client, runner = dispatch_client()
    handle = GhDispatch(client, post=False).request(Target(ref='feat'), HEAD, None)
    assert runner.sent('POST', DISPATCH)[0]['inputs'] == {'ref': 'feat', 'head': HEAD, 'ledger': '', 'post': 'false'}
    assert handle['known'] == [] and not runner.sent('GET', runs_path())


def test_a_dispatch_without_run_details_is_an_error():
    client, _ = dispatch_client({('POST', DISPATCH): ''})
    with pytest.raises(GhError, match='no run id'):
        GhDispatch(client, post=False).request(PR, HEAD, None)


def test_a_workflow_without_the_inputs_says_so():
    client, _ = dispatch_client({('POST', DISPATCH): GhError('Unexpected inputs provided: ["pr"] (HTTP 422)')})
    with pytest.raises(GhError, match='may not declare the gh-dispatch inputs pr, ref, head, ledger, post'):
        GhDispatch(client, post=False).request(PR, HEAD, None)
    client, _ = dispatch_client({('POST', DISPATCH): GhError('HTTP 403')})
    with pytest.raises(GhError, match='^HTTP 403$'):
        GhDispatch(client, post=False).request(PR, HEAD, None)


def handle(post=False, **kw):
    return {'backend': 'gh-dispatch', 'pr': '4', 'head_sha': HEAD, 'run_id': 7, 'post': post, 'known': [], **kw}


def test_check_waits_for_the_run_then_reads_its_artifact():
    client, _ = dispatch_client({('GET', RUN): [{'id': 7, 'status': 'in_progress'},
                                                {'id': 7, 'status': 'completed', 'conclusion': 'success',
                                                 'html_url': 'u'}],
                                 ('GET', ARTIFACTS): {'artifacts': [{'name': 'momayez-ledger'}]}},
                                files={'ledger.json': ledgers.dumps(sample()), 'target': '4\n'})
    backend_ = GhDispatch(client, post=False)
    assert backend_.check(handle()) is None
    assert backend_.check(handle()) == {'pr': '4', 'head_sha': HEAD, 'url': 'u', 'status': 'done',
                                        'verdict': 'findings', 'ledger': sample()}


def test_check_failures_carry_a_reason():
    done = {'id': 7, 'status': 'completed', 'conclusion': 'success'}
    client, runner = dispatch_client({('GET', RUN): {'id': 7, 'status': 'completed', 'conclusion': 'failure'}})
    got = GhDispatch(client).check(handle())
    assert got['status'] == 'failed' and got['reason'] == 'the review run ended failure'
    runner.routes[('GET', RUN)] = done
    runner.routes[('GET', ARTIFACTS)] = {'artifacts': [{'name': 'other'}]}
    assert GhDispatch(client).check(handle())['reason'] == 'the review run left no ledger'
    runner.routes[('GET', ARTIFACTS)] = {'artifacts': [{'name': 'momayez-ledger'}]}
    assert GhDispatch(client).check(handle())['reason'] == 'the review run left no ledger'  # empty artifact
    other = dict(sample(), target=dict(sample()['target'], head_sha='c' * 40))
    runner.files = {'ledger.json': ledgers.dumps(other)}
    assert 'reviewed cccccc' in GhDispatch(client).check(handle())['reason']
    runner.files = {'ledger.json': '{"version": "v0"}'}
    assert 'left an invalid ledger' in GhDispatch(client).check(handle())['reason']


def test_with_post_the_ledger_comes_from_the_check_run():
    client, _ = dispatch_client({('GET', RUN): {'id': 7, 'status': 'completed', 'conclusion': 'success'},
                                 ('GET', runs_path()): [{'check_runs': []}, {'check_runs': [run(3, sample())]}]})
    assert GhDispatch(client).check(handle(post=True)) is None
    assert GhDispatch(client).check(handle(post=True))['ledger'] == sample()


def test_status_finds_the_run_by_its_name():
    title = f'momayez pr/4@{HEAD}'
    client, runner = dispatch_client({('GET', LISTED): {'workflow_runs': []}})
    direct = GhDispatch(client, post=False)
    assert direct.status(PR, HEAD) == {'status': 'none', 'pr': '4', 'head_sha': HEAD}
    runner.routes[('GET', LISTED)] = {'workflow_runs': [{'id': 7, 'display_title': title},
                                                        {'id': 5, 'display_title': 'momayez other'}]}
    runner.routes[('GET', RUN)] = [{'id': 7, 'status': 'queued'},
                                   {'id': 7, 'status': 'completed', 'conclusion': 'cancelled', 'html_url': 'u'}]
    assert direct.status(PR, HEAD)['status'] == 'pending'
    assert direct.status(PR, HEAD) == {'status': 'done', 'pr': '4', 'head_sha': HEAD, 'url': 'u', 'failed': True,
                                       'reason': 'the review run ended cancelled', 'conclusion': 'cancelled'}
    runner.routes[('GET', LISTED)] = {'workflow_runs': [{'id': 7, 'display_title': 'momayez feat@' + HEAD}]}
    assert direct.status(Target(ref='feat'), HEAD)['status'] == 'done'


def test_status_with_post_reads_the_check_runs():
    client, _ = dispatch_client({('GET', runs_path()): {'check_runs': [run(3, sample())]}})
    got = GhDispatch(client).status(PR, HEAD)
    assert got['status'] == 'done' and got['ledger'] == sample()


def test_make_builds_the_configured_backend(tmp_path):
    client, _ = gh()
    assert isinstance(backend.make(Settings('gh-label', 'all'), client), GhLabel)
    direct = backend.make(Settings('gh-dispatch', 'none'), client)
    assert isinstance(direct, GhDispatch) and direct.post is False
    job = backend.make(Settings('k8s-job', 'none', K8s(tmp_path / 't.yaml', 'ns', 'ctx')), client)
    assert isinstance(job, K8sJob) and job.repo == REPO and job.kubectl.context == 'ctx'


def test_revive_rebuilds_a_backend_from_its_handle():
    client, _ = gh()
    assert isinstance(backend.revive({'backend': 'gh-label'}, lambda: client), GhLabel)
    assert backend.revive({'backend': 'gh-dispatch', 'post': True}, lambda: client).post is True
    job = backend.revive({'backend': 'k8s-job', 'namespace': 'ns'}, lambda: pytest.fail('no gh needed'))
    assert job.kubectl.namespace == 'ns' and job.kubectl.context is None
    with pytest.raises(ValueError, match='unknown backend'):
        backend.revive({'backend': 'routine'}, lambda: client)


def test_wait_hints():
    label = {'backend': 'gh-label', 'pr': '4', 'head_sha': HEAD, 'known': [1, 3]}
    assert backend.wait_hint(PR, HEAD, label) == f'momayezi-wait 4 {HEAD} --known 1,3'
    assert backend.wait_hint(PR, HEAD, dict(label, known=[])) == f'momayezi-wait 4 {HEAD}'
    job = {'backend': 'k8s-job', 'ref': "it's", 'head_sha': HEAD, 'job': 'j', 'namespace': 'ns'}
    hint = backend.wait_hint(Target(ref="it's"), HEAD, job)
    words = shlex.split(hint)
    assert words[:3] == ['momayezi-wait', "it's", HEAD] and json.loads(words[-1]) == job
