"""k8s-job: the review runs as a Kubernetes Job made from the repo's template; the ledger is the
last `momayez-ledger:v1` marker in its pod's log. Every cluster call goes through `Kubectl`."""

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

from . import ledger as ledgers
from . import poll
from .github import Target
from .protocol import (CONFIGMAP_CAP, EDITOR_MARKER, K8S_HEAD_LABEL, K8S_TARGET_ANNOTATION,
                       LEDGER_KEY, REVIEWER_MARKER)

Runner = Callable[[list[str], str | None], str]
# A branch name safe to put in a template unquoted; the same rule momayez-post applies.
SAFE_REF = re.compile(r'^[A-Za-z0-9._][A-Za-z0-9._/-]*$')
NAME_MAX = 63


class KubeError(RuntimeError):
    def __init__(self, message: str):
        super().__init__(message.strip() or 'kubectl failed')
        self.not_found = '(NotFound)' in message


def run_kubectl(args: list[str], stdin: str | None = None) -> str:
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

    def job(self, name: str) -> dict[str, Any] | None:
        try:
            return self.json('get', 'job', name)
        except KubeError as exc:
            if exc.not_found:
                return None
            raise


def job_name(target: Target, head: str, round_: int) -> str:
    """momayez-<pr|ref>-<head7>-r<round>: a DNS label, so the same request maps to the same Job."""
    tail = f'-{head[:7]}-r{round_}'
    who = f'pr{target.pr}' if target.pr else re.sub(r'[^a-z0-9]+', '-', str(target.ref).lower())
    who = who[:NAME_MAX - len('momayez-') - len(tail)].strip('-') or 'ref'
    return f'momayez-{who}{tail}'


def state(job: dict[str, Any]) -> tuple[str, str]:
    """('Complete' | 'Failed' | 'running', why)."""
    for cond in (job.get('status') or {}).get('conditions') or []:
        if cond.get('status') == 'True' and cond.get('type') in ('Complete', 'Failed'):
            return cond['type'], cond.get('message') or cond.get('reason') or ''
    return 'running', ''


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
        job = self.kubectl.job(name)
        if job and state(job)[0] == 'Failed':
            # A re-request after a failure runs again; a live or finished Job is read as it is.
            self.kubectl('delete', 'job', name, '--ignore-not-found')
            self.kubectl('delete', 'configmap', f'{name}-ledger', '--ignore-not-found')
            job = None
        if job is None:
            self.create(name, target, head, editor)
        return self.handle(target, head, name)

    def create(self, name: str, target: Target, head: str, editor: ledgers.Ledger | None) -> None:
        configmap = f'{name}-ledger'
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

    def check(self, handle: dict[str, Any]) -> dict[str, Any] | None:
        name, head = handle['job'], handle['head_sha']
        base = {**Target.from_meta(handle).meta(), 'head_sha': head, 'job': name}

        def failed(reason: str) -> dict[str, Any]:
            return {**base, 'status': 'failed', 'reason': reason}
        job = self.kubectl.job(name)
        if job is None:
            return failed(f'Job {name} is gone (deleted, or past its TTL)')
        kind, why = state(job)
        if kind == 'running':
            return None
        if kind == 'Failed':
            return failed(f'Job {name} failed: {why}' if why else f'Job {name} failed')
        pods = self.kubectl.json('get', 'pods', '-l', f'batch.kubernetes.io/job-name={name}')['items']
        done = [p for p in pods if (p.get('status') or {}).get('phase') == 'Succeeded']
        if not done:
            return failed(f'Job {name} left no succeeded pod to read')
        pod = max(done, key=created_at)['metadata']['name']
        try:
            found = ledgers.from_marker(self.kubectl('logs', pod, '--tail=-1'), REVIEWER_MARKER)
        except ledgers.LedgerError as exc:
            return failed(f'Job {name} printed an invalid ledger: {exc}')
        if found is None:
            return failed(f'Job {name} printed no ledger')
        if found['target']['head_sha'] != head:
            return failed(f'Job {name} reviewed {found["target"]["head_sha"]}, not {head}')
        return {**base, 'status': 'done', 'verdict': found['verdict'], 'ledger': found}

    def status(self, target: Target, head: str) -> dict[str, Any]:
        jobs = self.kubectl.json('get', 'jobs', '-l', f'{K8S_HEAD_LABEL}={head}')['items']
        mine = [j for j in jobs
                if (j['metadata'].get('annotations') or {}).get(K8S_TARGET_ANNOTATION) == target.label]
        if not mine:
            return {'status': 'none', **target.meta(), 'head_sha': head}
        result = self.check(self.handle(target, head, max(mine, key=created_at)['metadata']['name']))
        if result is None:
            return {'status': 'pending', **target.meta(), 'head_sha': head}
        return poll.summary(result)
