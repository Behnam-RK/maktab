"""k8s-job: the review runs as a Kubernetes Job made from the repo's template; the ledger is the
one the runner kept in the Job's ConfigMap, else the last `momayezi-ledger:v2` marker in its pod's
log. Every cluster call goes through `Kubectl`."""

from __future__ import annotations

import json
import os
import re
import string
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import failure as failures
from . import ledger as ledgers
from . import net
from . import poll
from .github import Target
from .protocol import (CONFIGMAP_CAP, EDITOR_MARKER, ERROR_FILE, K8S_HEAD_LABEL, K8S_TARGET_ANNOTATION,
                       LEDGER_KEY, REVIEWER_KEY, REVIEWER_MARKER)

Runner = Callable[[list[str], str | None], str]
# A branch name safe to put in a template unquoted; the same rule momayezi-post applies.
SAFE_REF = re.compile(r'^[A-Za-z0-9._][A-Za-z0-9._/-]*$')
NAME_MAX = 63


class KubeError(RuntimeError):
    def __init__(self, message: str):
        super().__init__(message.strip() or 'kubectl failed')
        self.not_found = '(NotFound)' in message


# Safe to repeat: reads, and the merge patches this module sends (an owner link, one data key).
IDEMPOTENT = ('get', 'logs', 'patch')


def verb(args: list[str]) -> str:
    """The kubectl verb after the `--context x` and `-n ns` scope."""
    rest = list(args)
    while rest and rest[0] in ('--context', '-n'):
        rest = rest[2:]
    return rest[0] if rest else ''


def run_kubectl(args: list[str], stdin: str | None = None) -> str:
    return net.retrying(lambda: _run_kubectl(args, stdin), verb(args) in IDEMPOTENT)


def _run_kubectl(args: list[str], stdin: str | None) -> str:
    try:
        done = subprocess.run(['kubectl', *args], input=stdin, capture_output=True, text=True,
                              cwd=os.environ.get('CLAUDE_PROJECT_DIR') or None)
    except FileNotFoundError:
        raise KubeError('kubectl is not installed or not on PATH') from None
    if done.returncode != 0:
        raise KubeError(done.stderr or done.stdout)
    return done.stdout


@dataclass
class Kubectl:
    namespace: str
    context: str | None = None
    run: Runner = field(default=run_kubectl, repr=False)

    def __call__(self, *args: str, stdin: str | None = None) -> str:
        scope = ['--context', self.context] if self.context else []
        return self.run([*scope, '-n', self.namespace, *args], stdin)

    def json(self, *args: str, stdin: str | None = None) -> Any:
        return json.loads(self(*args, '-o', 'json', stdin=stdin))

    def get(self, kind: str, name: str) -> dict[str, Any] | None:
        """One object, or None when it doesn't exist."""
        try:
            return self.json('get', kind, name)
        except KubeError as exc:
            if exc.not_found:
                return None
            raise


def configmap_ref(text: str) -> tuple[str, str]:
    """`<namespace>/<name>`, as momayezi-review --ledger-configmap takes it."""
    namespace, _, name = text.partition('/')
    if not namespace or not name or '/' in name:
        raise ValueError(f'not <namespace>/<name>: {text!r}')
    return namespace, name


def keep(ref: tuple[str, str], key: str, text: str, run: Runner = run_kubectl) -> None:
    """Merge one key into the Job's ConfigMap: the runner's copy of its result, which outlives the pod.
    The patch goes on stdin: a ledger near CAP is too long for one argv entry."""
    namespace, name = ref
    Kubectl(namespace, run=run)('patch', 'configmap', name, '--type', 'merge', '--patch-file', '/dev/stdin',
                                stdin=json.dumps({'data': {key: text}}))


def ledger_configmap(job: str) -> str:
    """The Job's ConfigMap: the editor ledger in, and with --ledger-configmap the runner's result out."""
    return f'{job}-ledger'


def job_name(target: Target, head: str, round_: int) -> str:
    """momayezi-<pr|ref>-<head7>-r<round>: a DNS label, so the same request maps to the same Job."""
    tail = f'-{head[:7]}-r{round_}'
    who = f'pr{target.pr}' if target.pr else re.sub(r'[^a-z0-9]+', '-', str(target.ref).lower())
    who = who[:NAME_MAX - len('momayezi-') - len(tail)].strip('-') or 'ref'
    return f'momayezi-{who}{tail}'


def state(job: dict[str, Any]) -> tuple[str, str]:
    """('Complete' | 'Failed' | 'running', why)."""
    for cond in (job.get('status') or {}).get('conditions') or []:
        if cond.get('status') == 'True' and cond.get('type') in ('Complete', 'Failed'):
            return cond['type'], cond.get('message') or cond.get('reason') or ''
    return 'running', ''


def failed(base: dict[str, Any], reason: str) -> dict[str, Any]:
    return {**base, 'status': 'failed', 'reason': reason}


def created_at(item: dict[str, Any]) -> str:
    return item['metadata'].get('creationTimestamp') or ''


class K8sJob:
    name = 'k8s-job'

    def __init__(self, kubectl: Kubectl, repo: str | None = None, template: Path | None = None):
        self.kubectl, self.repo, self.template = kubectl, repo, template

    def handle(self, target: Target, head: str, job: str) -> dict[str, Any]:
        out = {'backend': self.name, **target.meta(), 'head_sha': head, 'job': job,
               'namespace': self.kubectl.namespace}
        if self.kubectl.context:
            out['context'] = self.kubectl.context
        return out

    def request(self, target: Target, head: str, editor: ledgers.Ledger | None) -> dict[str, Any]:
        if self.template is None or self.repo is None:
            raise KubeError('k8s-job needs a repo and a Job template to start a review')
        if target.ref and not SAFE_REF.match(target.ref):
            raise KubeError(f'not a branch name k8s-job can pass on: {target.ref!r}')
        name = job_name(target, head, editor['round'] + 1 if editor else 1)
        job = self.kubectl.get('job', name)
        if job and self.stale(self.handle(target, head, name), job):
            self.kubectl('delete', 'job', name, '--ignore-not-found')
            self.kubectl('delete', 'configmap', ledger_configmap(name), '--ignore-not-found')
            job = None
        if job is None:
            self.create(name, target, head, editor)
        return self.handle(target, head, name)

    def stale(self, handle: dict[str, Any], job: dict[str, Any]) -> bool:
        """Whether a re-request runs the Job again: always after a failure, never while it runs,
        and once complete unless it left a ledger to read that isn't degraded."""
        kind = state(job)[0]
        if kind != 'Complete':
            return kind == 'Failed'
        result = self.finished(handle, job)
        return result['status'] != 'done' or result['verdict'] == 'degraded'

    def create(self, name: str, target: Target, head: str, editor: ledgers.Ledger | None) -> None:
        configmap = ledger_configmap(name)
        labels = {K8S_HEAD_LABEL: head}
        values = {'name': name, 'namespace': self.kubectl.namespace, 'repo': self.repo,
                  'target_flag': '--pr' if target.pr else '--ref', 'target': str(target.pr or target.ref),
                  'head': head, 'ledger_configmap': configmap}
        try:
            text = string.Template(Path(self.template).read_text(encoding='utf-8')).substitute(values)
        except (KeyError, ValueError) as exc:
            raise KubeError(f'{self.template}: bad placeholder {exc} (write a literal $ as $$)') from None
        manifest = self.kubectl.json('create', '--dry-run=client', '-f', '-', stdin=text)
        if manifest.get('kind') != 'Job':
            raise KubeError(f'{self.template} must hold exactly one Job, not {manifest.get("kind")}')
        meta = manifest.setdefault('metadata', {})
        meta.update(name=name, namespace=self.kubectl.namespace)
        meta.setdefault('labels', {}).update(labels)
        meta.setdefault('annotations', {})[K8S_TARGET_ANNOTATION] = target.label
        # The ConfigMap only once the template has proven good, so a bad one leaves nothing behind.
        data = ledgers.dumps(ledgers.fit(editor, EDITOR_MARKER, CONFIGMAP_CAP)) if editor else ''
        self.kubectl('apply', '-f', '-', stdin=json.dumps({
            'apiVersion': 'v1', 'kind': 'ConfigMap',
            'metadata': {'name': configmap, 'labels': labels}, 'data': {LEDGER_KEY: data}}))
        made = self.kubectl.json('create', '-f', '-', stdin=json.dumps(manifest))
        # Owned by the Job, the ConfigMap goes when ttlSecondsAfterFinished deletes it.
        owner = {'apiVersion': 'batch/v1', 'kind': 'Job', 'name': name, 'uid': made['metadata']['uid']}
        self.kubectl('patch', 'configmap', configmap, '--type', 'merge',
                     '-p', json.dumps({'metadata': {'ownerReferences': [owner]}}))

    def pods(self, name: str) -> list[dict[str, Any]]:
        return self.kubectl.json('get', 'pods', '-l', f'batch.kubernetes.io/job-name={name}')['items']

    def progress(self, base: dict[str, Any], name: str, job: dict[str, Any]) -> dict[str, Any]:
        """A Job still on its way: queued while its pod is Pending (with the scheduler's word
        when it can't be placed), else running."""
        pods = self.pods(name)
        since = created_at(job)
        if not pods:
            return poll.pending(base, 'queued', since)
        status = max(pods, key=created_at).get('status') or {}
        if status.get('phase') == 'Pending':
            why = [c.get('message') or c.get('reason') or '' for c in status.get('conditions') or []
                   if c.get('type') == 'PodScheduled' and c.get('status') == 'False']
            return poll.pending(base, 'queued', since, reason=why[0] if why else '')
        return poll.pending(base, 'running', since, status.get('startTime'))

    def log(self, name: str, tail: str, phase: str | None = None) -> str | None:
        """The log of the Job's newest pod (in `phase`, if given), or None without one."""
        pods = [p for p in self.pods(name) if phase is None or (p.get('status') or {}).get('phase') == phase]
        return self.kubectl('logs', max(pods, key=created_at)['metadata']['name'], tail) if pods else None

    def kept(self, name: str) -> dict[str, str]:
        """What the runner kept in the Job's ConfigMap (nothing without --ledger-configmap)."""
        return (self.kubectl.get('configmap', ledger_configmap(name)) or {}).get('data') or {}

    @staticmethod
    def base(handle: dict[str, Any]) -> dict[str, Any]:
        return {**Target.from_meta(handle).meta(), 'head_sha': handle['head_sha'], 'job': handle['job']}

    def check(self, handle: dict[str, Any]) -> dict[str, Any]:
        name = handle['job']
        job = self.kubectl.get('job', name)
        if job is None:
            return failed(self.base(handle), f'Job {name} is gone (deleted, or past its TTL)')
        if state(job)[0] == 'running':
            return self.progress(self.base(handle), name, job)
        return self.finished(handle, job)

    def finished(self, handle: dict[str, Any], job: dict[str, Any]) -> dict[str, Any]:
        """A stopped Job's result: the ledger it kept or logged, else why there is none."""
        name, head, base = handle['job'], handle['head_sha'], self.base(handle)
        kind, why = state(job)
        kept = self.kept(name)
        if kind == 'Failed':
            # The runner's own word is a bonus, kept or in its pod's log; the Job's failure stands without it.
            told = failures.loads(kept.get(ERROR_FILE))
            if told is None:
                try:
                    told = failures.from_text(self.log(name, '--tail=50'))
                except KubeError:
                    pass
            return {**failed(base, f'Job {name} failed: {why}' if why else f'Job {name} failed'), **(told or {})}
        text = kept.get(REVIEWER_KEY)
        logged = None if text else self.log(name, '--tail=-1', 'Succeeded')
        if not text and logged is None:
            return failed(base, f'Job {name} left no succeeded pod to read, and kept no ledger in its ConfigMap')
        try:
            found = ledgers.loads(text) if text else ledgers.from_marker(logged, REVIEWER_MARKER)
        except ledgers.LedgerError as exc:
            return failed(base, f'Job {name} left an invalid ledger: {exc}')
        if found is None:
            return failed(base, f'Job {name} printed no ledger')
        if not poll.reviewed(found, head):
            return failed(base, f'Job {name} reviewed {found["target"]["head_sha"]}, not {head}')
        return {**base, 'status': 'done', 'verdict': found['verdict'], 'ledger': found}

    def status(self, target: Target, head: str) -> dict[str, Any]:
        jobs = self.kubectl.json('get', 'jobs', '-l', f'{K8S_HEAD_LABEL}={head}')['items']
        mine = [j for j in jobs
                if (j['metadata'].get('annotations') or {}).get(K8S_TARGET_ANNOTATION) == target.label]
        if not mine:
            return {'status': 'none', **target.meta(), 'head_sha': head}
        result = self.check(self.handle(target, head, max(mine, key=created_at)['metadata']['name']))
        return result if result['status'] == 'pending' else poll.summary(result)
