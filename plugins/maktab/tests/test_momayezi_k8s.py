from __future__ import annotations

import json
import subprocess

import pytest
from gh_fake import HEAD, REPO, sample

from momayezi import k8s
from momayezi import ledger as ledgers
from momayezi.github import Target
from momayezi.k8s import K8sJob, KubeError, Kubectl
from momayezi.protocol import REVIEWER_MARKER

PR = Target(pr=4)
NAME = f'momayez-pr4-{HEAD[:7]}-r1'
TEMPLATE = """apiVersion: batch/v1
kind: Job
metadata:
  name: ${name}
spec:
  template:
    spec:
      containers:
        - name: review
          command: [momayezi-review, --repo, ${repo}, ${target_flag}, "${target}", --head, ${head}]
          env: [{name: COST, value: "$$0"}]
      volumes: [{name: ledger, configMap: {name: ${ledger_configmap}}}]
"""
NOT_FOUND = KubeError('Error from server (NotFound): jobs.batch "x" not found')


class FakeKube:
    """Answers kubectl argv (after --context/-n) by the longest matching prefix in `routes`:
    a value, a list (one per call, the last repeating) or a KubeError. Calls are recorded."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.calls: list[tuple[list[str], str | None]] = []

    def __call__(self, args, stdin):
        self.calls.append((args, stdin))
        body = args[args.index('-n') + 2:]
        match = max((k for k in self.routes if tuple(body[:len(k)]) == k), key=len, default=None)
        answer = self.routes.get(match, '')
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            answer = answer(stdin)
        return answer if isinstance(answer, str) else json.dumps(answer)

    def verbs(self):
        return [tuple(a[a.index('-n') + 2:][:2]) for a, _ in self.calls]


def job(conditions=(), name=NAME, created='2026-11-05T10:00:00Z', target='#4'):
    return {'metadata': {'name': name, 'creationTimestamp': created,
                         'annotations': {'momayez.maktab/target': target}},
            'status': {'conditions': list(conditions)}}


COMPLETE = {'type': 'Complete', 'status': 'True'}


def pod(name, phase='Succeeded', created='2026-11-05T10:00:00Z'):
    return {'metadata': {'name': name, 'creationTimestamp': created}, 'status': {'phase': phase}}


def backend(routes=None, tmp_path=None, template=TEMPLATE, context=None):
    runner = FakeKube(routes)
    path = None
    if tmp_path is not None:
        path = tmp_path / 'job.yaml'
        path.write_text(template, encoding='utf-8')
    return K8sJob(Kubectl('momayez', context, runner), repo=REPO, template=path), runner


def test_run_kubectl(monkeypatch):
    def missing(*a, **k):
        raise FileNotFoundError
    monkeypatch.setattr(subprocess, 'run', missing)
    with pytest.raises(KubeError, match='not installed'):
        k8s.run_kubectl(['version'])
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 1, '', NOT_FOUND.args[0]))
    with pytest.raises(KubeError) as raised:
        k8s.run_kubectl(['get', 'job', 'x'])
    assert raised.value.not_found
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 0, 'ok', ''))
    assert k8s.run_kubectl(['version']) == 'ok'
    assert str(KubeError(' ')) == 'kubectl failed'


def test_kubectl_scopes_every_call_and_reads_a_missing_job_as_none():
    runner = FakeKube({('get', 'job'): [NOT_FOUND, KubeError('Unauthorized')]})
    kubectl = Kubectl('ns', 'ctx', runner)
    assert kubectl.job('x') is None
    assert runner.calls[0][0][:4] == ['--context', 'ctx', '-n', 'ns']
    with pytest.raises(KubeError, match='Unauthorized'):
        kubectl.job('x')
    Kubectl('ns', run=runner)('version')
    assert runner.calls[-1][0] == ['-n', 'ns', 'version']


def test_job_names_are_dns_labels():
    assert k8s.job_name(PR, HEAD, 1) == NAME
    assert k8s.job_name(Target(ref='Feat/Some_thing'), HEAD, 2) == f'momayez-feat-some-thing-{HEAD[:7]}-r2'
    long = k8s.job_name(Target(ref='a' * 80 + '-b'), HEAD, 10)
    assert len(long) == 63 and long.endswith(f'-{HEAD[:7]}-r10')
    assert k8s.job_name(Target(ref='___'), HEAD, 1) == f'momayez-ref-{HEAD[:7]}-r1'


def test_state_reads_terminal_conditions():
    assert k8s.state({}) == ('running', '')
    assert k8s.state(job([{'type': 'SuccessCriteriaMet', 'status': 'True'}])) == ('running', '')
    assert k8s.state(job([{'type': 'Failed', 'status': 'False'}])) == ('running', '')
    assert k8s.state(job([{'type': 'Failed', 'status': 'True', 'reason': 'DeadlineExceeded'}])) == (
        'Failed', 'DeadlineExceeded')
    assert k8s.state(job([COMPLETE])) == ('Complete', '')


def dry_run(stdin):
    assert '${' not in stdin and '"$0"' in stdin
    return {'kind': 'Job', 'metadata': {'labels': {'app': 'momayez'}}, 'spec': {}, 'echo': stdin}


def test_request_creates_the_configmap_the_job_and_the_owner_link(tmp_path):
    made = {'metadata': {'uid': 'u-1'}}
    kube, runner = backend({('get', 'job'): NOT_FOUND, ('create', '--dry-run=client'): dry_run,
                            ('create', '-f'): made}, tmp_path, context='staging')
    handle = kube.request(PR, HEAD, None)
    assert handle == {'backend': 'k8s-job', 'pr': '4', 'head_sha': HEAD, 'job': NAME, 'namespace': 'momayez',
                      'context': 'staging'}
    assert runner.verbs() == [('get', 'job'), ('create', '--dry-run=client'), ('apply', '-f'),
                              ('create', '-f'), ('patch', 'configmap')]
    configmap = json.loads(runner.calls[2][1])
    assert configmap['metadata'] == {'name': f'{NAME}-ledger', 'labels': {'momayez.maktab/head': HEAD}}
    assert configmap['data'] == {'ledger.json': ''}
    rendered = runner.calls[1][1]
    assert f'--repo, {REPO}, --pr, "4", --head, {HEAD}' in rendered and f'name: {NAME}-ledger' in rendered
    manifest = json.loads(runner.calls[3][1])
    assert manifest['metadata']['name'] == NAME and manifest['metadata']['namespace'] == 'momayez'
    assert manifest['metadata']['labels'] == {'app': 'momayez', 'momayez.maktab/head': HEAD}
    assert manifest['metadata']['annotations'] == {'momayez.maktab/target': '#4'}
    patch = json.loads(runner.calls[4][0][-1])
    assert patch['metadata']['ownerReferences'][0] == {'apiVersion': 'batch/v1', 'kind': 'Job',
                                                       'name': NAME, 'uid': 'u-1'}


def test_request_sends_the_editor_ledger_and_names_the_next_round(tmp_path):
    kube, runner = backend({('get', 'job'): NOT_FOUND, ('create', '--dry-run=client'): dry_run,
                            ('create', '-f'): {'metadata': {'uid': 'u'}}}, tmp_path)
    handle = kube.request(Target(ref='feat'), HEAD, sample())
    assert handle['job'] == f'momayez-feat-{HEAD[:7]}-r{sample()["round"] + 1}' and 'context' not in handle
    assert ledgers.loads(json.loads(runner.calls[2][1])['data']['ledger.json']) == sample()
    assert '--ref, "feat"' in runner.calls[1][1]


def test_a_live_job_is_reused_and_a_failed_one_replaced(tmp_path):
    kube, runner = backend({('get', 'job'): job()}, tmp_path)
    assert kube.request(PR, HEAD, None)['job'] == NAME and runner.verbs() == [('get', 'job')]
    failed = job([{'type': 'Failed', 'status': 'True'}])
    kube, runner = backend({('get', 'job'): failed, ('create', '--dry-run=client'): dry_run,
                            ('create', '-f'): {'metadata': {'uid': 'u'}}}, tmp_path)
    kube.request(PR, HEAD, None)
    assert runner.verbs()[:4] == [('get', 'job'), ('delete', 'job'), ('delete', 'configmap'),
                                  ('create', '--dry-run=client')]


@pytest.mark.parametrize('template, routes, message', [
    ('name: ${nope}', {}, 'bad placeholder'),
    ('cost: $5', {}, 'write a literal $ as $$'),
    (TEMPLATE, {('create', '--dry-run=client'): {'kind': 'List'}}, 'exactly one Job, not List'),
])
def test_bad_templates_are_errors(tmp_path, template, routes, message):
    kube, runner = backend({('get', 'job'): NOT_FOUND, **routes}, tmp_path, template=template)
    with pytest.raises(KubeError, match=message.replace('$', r'\$')):
        kube.request(PR, HEAD, None)
    assert ('apply', '-f') not in runner.verbs()  # no orphaned ConfigMap


def test_request_needs_a_template_and_a_safe_ref(tmp_path):
    with pytest.raises(KubeError, match='needs a repo and a Job template'):
        K8sJob(Kubectl('ns', run=FakeKube())).request(PR, HEAD, None)
    kube, _ = backend({}, tmp_path)
    with pytest.raises(KubeError, match='not a branch name'):
        kube.request(Target(ref='-x'), HEAD, None)


HANDLE = {'backend': 'k8s-job', 'pr': '4', 'head_sha': HEAD, 'job': NAME, 'namespace': 'momayez'}


def marker(ledger):
    return 'cloning\nreviewing\n' + ledgers.to_marker(ledger, REVIEWER_MARKER) + '\n'


def test_check_reads_the_newest_succeeded_pod():
    pods = {'items': [pod('a', created='1'), pod('b', 'Failed', '3'), pod('c', created='2')]}
    kube, runner = backend({('get', 'job'): [job(), job([COMPLETE])], ('get', 'pods'): pods,
                            ('logs', 'c'): marker(sample())})
    assert kube.check(HANDLE)['phase'] == 'running'
    assert kube.check(HANDLE) == {'pr': '4', 'head_sha': HEAD, 'job': NAME, 'status': 'done',
                                  'verdict': 'findings', 'ledger': sample()}
    assert runner.calls[-2][0][-3:] == [f'batch.kubernetes.io/job-name={NAME}', '-o', 'json']
    assert runner.calls[-1][0][-2:] == ['c', '--tail=-1']


@pytest.mark.parametrize('routes, reason', [
    ({('get', 'job'): NOT_FOUND}, 'is gone'),
    ({('get', 'job'): job([{'type': 'Failed', 'status': 'True', 'message': 'BackoffLimitExceeded'}]),
      ('get', 'pods'): {'items': []}}, 'failed: BackoffLimitExceeded'),
    ({('get', 'job'): job([{'type': 'Failed', 'status': 'True'}]), ('get', 'pods'): {'items': [pod('a', 'Failed')]},
      ('logs', 'a'): 'crashed'}, f'Job {NAME} failed'),
    ({('get', 'job'): job([COMPLETE]), ('get', 'pods'): {'items': [pod('a', 'Failed')]}}, 'no succeeded pod'),
    ({('get', 'job'): job([COMPLETE]), ('get', 'pods'): {'items': [pod('a')]},
      ('logs', 'a'): f'<!-- {REVIEWER_MARKER} {{}} -->'}, 'invalid ledger'),
    ({('get', 'job'): job([COMPLETE]), ('get', 'pods'): {'items': [pod('a')]}, ('logs', 'a'): 'crashed'},
     'printed no ledger'),
    ({('get', 'job'): job([COMPLETE]), ('get', 'pods'): {'items': [pod('a')]},
      ('logs', 'a'): marker(dict(sample(), target=dict(sample()['target'], head_sha='c' * 40)))}, 'reviewed cccc'),
])
def test_check_failures_carry_a_reason(routes, reason):
    kube, _ = backend(routes)
    got = kube.check(HANDLE)
    assert got['status'] == 'failed' and reason in got['reason'] and got['job'] == NAME


def test_a_running_job_says_queued_until_its_pod_is_placed():
    unschedulable = dict(pod('a', 'Pending'), status={'phase': 'Pending', 'conditions': [
        {'type': 'PodScheduled', 'status': 'False', 'reason': 'Unschedulable', 'message': '0/3 nodes are available'}]})
    started = dict(pod('b', 'Running'), status={'phase': 'Running', 'startTime': '2026-11-05T11:00:00Z'})
    kube, runner = backend({('get', 'job'): job(), ('get', 'pods'): {'items': []}})
    assert kube.check(HANDLE)['phase'] == 'queued'
    runner.routes[('get', 'pods')] = {'items': [unschedulable]}
    got = kube.check(HANDLE)
    assert got['phase'] == 'queued' and got['reason'] == '0/3 nodes are available' and got['queued_for'] == 7200
    runner.routes[('get', 'pods')] = {'items': [dict(unschedulable, status={'phase': 'Pending'})]}
    assert 'reason' not in kube.check(HANDLE)
    runner.routes[('get', 'pods')] = {'items': [started]}
    got = kube.check(HANDLE)
    assert got['phase'] == 'running' and got['queued_for'] == 3600 and got['ran_for'] == 3600


def test_a_failed_job_says_why_from_its_pod_log():
    limited = 'momayezi-error: {"reason":"hit your limit","resets_at":"2026-11-05T15:00:00Z","status":"limited"}'
    kube, runner = backend({('get', 'job'): job([{'type': 'Failed', 'status': 'True'}]),
                            ('get', 'pods'): {'items': [pod('a', 'Failed')]}, ('logs', 'a'): 'cloning\n' + limited})
    got = kube.check(HANDLE)
    assert got['status'] == 'limited' and got['reason'] == 'hit your limit' and got['resets_at'].startswith('2026')
    assert runner.calls[-1][0][-2:] == ['a', '--tail=50']


def test_a_rebased_review_is_the_review_of_the_requested_head():
    moved = dict(sample(), target=dict(sample()['target'], head_sha='d' * 40, rebased_from=HEAD))
    kube, _ = backend({('get', 'job'): job([COMPLETE]), ('get', 'pods'): {'items': [pod('a')]},
                       ('logs', 'a'): marker(moved)})
    assert kube.check(HANDLE)['status'] == 'done'


def test_status_finds_the_newest_job_for_the_target():
    jobs = {'items': [job(name='old', created='1'), job(name='other', created='3', target='feat'),
                      job(name=NAME, created='2')]}
    kube, runner = backend({('get', 'jobs'): {'items': []}})
    assert kube.status(PR, HEAD) == {'status': 'none', 'pr': '4', 'head_sha': HEAD}
    assert runner.calls[0][0][-4:] == ['-l', f'momayez.maktab/head={HEAD}', '-o', 'json']
    runner.routes = {('get', 'jobs'): jobs, ('get', 'job'): [job(), job([COMPLETE])],
                     ('get', 'pods'): {'items': [pod('p')]}, ('logs', 'p'): marker(sample())}
    assert kube.status(PR, HEAD) == {'status': 'pending', 'pr': '4', 'head_sha': HEAD, 'job': NAME,
                                     'phase': 'running', 'queued_for': 7200, 'ran_for': 0}
    got = kube.status(PR, HEAD)
    assert got['status'] == 'done' and got['ledger'] == sample() and got['failed'] is False
    assert [a for a, _ in runner.calls if a[2:4] == ['get', 'job']][-1][4] == NAME
