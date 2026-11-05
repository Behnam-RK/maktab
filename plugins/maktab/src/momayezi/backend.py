"""Reviewer backends: what starts a remote review and where its ledger comes back from.

A backend's `request` returns a handle, a small JSON object naming the backend and how to find
the review again; `check` turns it into a result, or None while pending. Every backend but
gh-label (whose hint keeps `--known`) puts the handle in the `momayezi-wait --handle` hint, so
the waiter needs no settings.
"""

from __future__ import annotations

import json
import shlex
from collections.abc import Callable
from typing import Any, Protocol

from . import ledger as ledgers
from . import poll
from .config import Settings
from .github import Gh, GhError, Target, run_ledger
from .k8s import K8sJob, Kubectl
from .protocol import DISPATCH_CAP, DISPATCH_INPUTS, EDITOR_MARKER, LABEL, RUN_NAME, WORKFLOW

Handle = dict[str, Any]
Result = dict[str, Any]


class Backend(Protocol):
    name: str

    def request(self, target: Target, head: str, editor: ledgers.Ledger | None) -> Handle: ...

    def check(self, handle: Handle) -> Result: ...

    def status(self, target: Target, head: str) -> Result: ...


def _sent(editor: ledgers.Ledger | None) -> str:
    return ledgers.dumps(ledgers.fit(editor, EDITOR_MARKER, DISPATCH_CAP)) if editor else ''


class GhLabel:
    """The `review` label on a PR (a dispatch with `ref` for a branch); the ledger comes back
    as the `momayez` check run on the head."""

    name = 'gh-label'

    def __init__(self, gh: Gh):
        self.gh = gh

    def request(self, target: Target, head: str, editor: ledgers.Ledger | None) -> Handle:
        seen = poll.known(self.gh, head)
        if target.pr:
            self.gh.press(target.pr, LABEL)  # the editor ledger went in the PR comment
        else:
            self.gh.dispatch(WORKFLOW, {'ref': str(target.ref), 'ledger': _sent(editor)})
        return {'backend': self.name, **target.meta(), 'head_sha': head, 'known': sorted(seen),
                'requested_at': poll.iso()}

    def check(self, handle: Handle) -> Result:
        return poll.check(self.gh, Target.from_meta(handle), handle['head_sha'], set(handle.get('known') or ()),
                          handle.get('requested_at', ''))

    def status(self, target: Target, head: str) -> Result:
        runs = self.gh.runs(head)
        out: Result = {**target.meta(), 'head_sha': head}
        done = [r for r in runs if r.get('status') == 'completed']
        for run in done:
            found = run_ledger(run)
            if found:
                out.update(ledger=found, verdict=found['verdict'], url=run.get('html_url', ''))
                break
        if any(r.get('status') != 'completed' for r in runs):
            return {'status': 'pending', **out}
        if not done:
            return {'status': 'none', **out}
        return {'status': 'done', **out, 'failed': run_ledger(done[0]) is None}


class GhDispatch:
    """A `workflow_dispatch` of momayez.yaml, which fires no `pull_request` workflow. With
    `post`, the ledger comes back as the check run; without, from the run's artifact."""

    name = 'gh-dispatch'

    def __init__(self, gh: Gh, post: bool = True):
        self.gh, self.post = gh, post

    def request(self, target: Target, head: str, editor: ledgers.Ledger | None) -> Handle:
        seen = poll.known(self.gh, head) if self.post else set()
        inputs = {**target.meta(), 'head': head, 'ledger': _sent(editor), 'post': str(self.post).lower()}
        try:
            run_id = self.gh.dispatch_run(WORKFLOW, inputs)
        except GhError as exc:
            if exc.status != 422:
                raise
            raise GhError(f'{WORKFLOW} rejected the dispatch; it may not declare the gh-dispatch inputs '
                          f'{", ".join(DISPATCH_INPUTS)} yet (docs/momayezi-remote.md): {exc}') from None
        return {'backend': self.name, **target.meta(), 'head_sha': head, 'run_id': run_id,
                'post': self.post, 'known': sorted(seen), 'requested_at': poll.iso()}

    def check(self, handle: Handle) -> Result:
        target, head = Target.from_meta(handle), handle['head_sha']
        run = self.gh.workflow_run(int(handle['run_id']))
        if run.get('status') != 'completed':
            since = run.get('created_at') or handle.get('requested_at')
            if run.get('status') == 'in_progress':
                return poll.pending({**target.meta(), 'head_sha': head}, 'running', since, run.get('run_started_at'))
            return poll.pending({**target.meta(), 'head_sha': head}, 'queued', since)
        base = {**target.meta(), 'head_sha': head, 'url': run.get('html_url', '')}
        if run.get('conclusion') != 'success':
            return {**base, 'status': 'failed', 'conclusion': run.get('conclusion'),
                    'reason': f'the review run ended {run.get("conclusion")}'}
        if handle.get('post'):
            return poll.check(self.gh, target, head, set(handle.get('known') or ()), handle.get('requested_at', ''))
        try:
            found = self.gh.artifact_ledger(int(run['id']))
        except ledgers.LedgerError as exc:  # a finished run: retrying reads the same bytes
            return {**base, 'status': 'failed', 'reason': f'the review run left an invalid ledger: {exc}'}
        if found is None:
            return {**base, 'status': 'failed', 'reason': 'the review run left no ledger'}
        if found['target']['head_sha'] != head:
            return {**base, 'status': 'failed',
                    'reason': f'the run reviewed {found["target"]["head_sha"]}, not {head}'}
        return {**base, 'status': 'done', 'verdict': found['verdict'], 'ledger': found}

    def status(self, target: Target, head: str) -> Result:
        if self.post:
            return GhLabel(self.gh).status(target, head)
        title = RUN_NAME.format(target=f'pr/{target.pr}' if target.pr else target.ref, head=head)
        runs = [r for r in self.gh.dispatched_runs(WORKFLOW) if r.get('display_title') == title]
        if not runs:
            return {'status': 'none', **target.meta(), 'head_sha': head}
        result = self.check({**target.meta(), 'head_sha': head, 'run_id': runs[0]['id'], 'post': False})
        return result if result['status'] == 'pending' else poll.summary(result)


def make(settings: Settings, gh: Gh) -> Backend:
    if settings.backend == 'gh-dispatch':
        return GhDispatch(gh, post=settings.pr_comments == 'all')
    if settings.backend == 'k8s-job':
        k8s = settings.k8s
        assert k8s is not None  # config.load requires it for k8s-job
        return K8sJob(Kubectl(k8s.namespace, k8s.context), repo=gh.repo, template=k8s.template)
    return GhLabel(gh)


def revive(handle: Handle, gh: Callable[[], Gh]) -> Backend:
    """The backend a handle names, rebuilt from the handle alone."""
    name = handle.get('backend')
    if name == 'k8s-job':
        return K8sJob(Kubectl(str(handle['namespace']), handle.get('context')))
    if name == 'gh-dispatch':
        return GhDispatch(gh(), post=bool(handle.get('post')))
    if name == 'gh-label':
        return GhLabel(gh())
    raise ValueError(f'unknown backend in the handle: {name!r}')


def wait_hint(target: Target, head: str, handle: Handle) -> str:
    command = f'momayezi-wait {shlex.quote(str(target.pr or target.ref))} {head}'
    if handle['backend'] == 'gh-label':
        known = ','.join(str(i) for i in handle['known'])
        return command + (f' --known {known}' if known else '')
    return f'{command} --handle {shlex.quote(json.dumps(handle, separators=(",", ":")))}'
