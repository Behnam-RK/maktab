"""A thin `gh` adapter: every GitHub call momayezi makes goes through `Gh`."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import ledger as ledgers
from .protocol import ARTIFACT, CHECK_RUN, FINDING_MARKER, REVIEWER_MARKER

Runner = Callable[[list[str], str | None], str]


class GhError(RuntimeError):
    def __init__(self, message: str):
        super().__init__(message.strip() or 'gh failed')
        match = re.search(r'HTTP (\d{3})', message)
        self.status = int(match.group(1)) if match else None


def run_gh(args: list[str], stdin: str | None = None) -> str:
    try:
        done = subprocess.run(['gh', *args], input=stdin, capture_output=True, text=True,
                              cwd=os.environ.get('CLAUDE_PROJECT_DIR') or None)
    except FileNotFoundError:
        raise GhError('gh is not installed or not on PATH') from None
    if done.returncode != 0:
        raise GhError(done.stderr or done.stdout)
    return done.stdout


@dataclass(frozen=True)
class Target:
    """A PR number or a branch name; digits mean a PR, as on every momayezi command line."""

    pr: int | None = None
    ref: str | None = None

    @classmethod
    def parse(cls, text: str) -> Target:
        text = str(text).strip()
        if not text:
            raise ValueError('a PR number or a ref is required')
        return cls(pr=int(text)) if text.isdigit() else cls(ref=text)

    @classmethod
    def from_meta(cls, meta: dict[str, Any]) -> Target:
        """The inverse of meta(): a handle or result names its target this way."""
        return cls(pr=int(meta['pr'])) if meta.get('pr') else cls(ref=str(meta['ref']))

    @property
    def label(self) -> str:
        return f'#{self.pr}' if self.pr else str(self.ref)

    def meta(self) -> dict[str, str]:
        return {'pr': str(self.pr)} if self.pr else {'ref': str(self.ref)}


@dataclass
class Gh:
    repo: str
    run: Runner = field(default=run_gh, repr=False)

    @classmethod
    def here(cls, repo: str | None = None, run: Runner = run_gh) -> Gh:
        repo = repo or os.environ.get('GITHUB_REPOSITORY') or run(
            ['repo', 'view', '--json', 'nameWithOwner', '--jq', '.nameWithOwner'], None).strip()
        return cls(repo, run)

    def api(self, path: str, method: str = 'GET', body: Any = None, pages: bool = False) -> Any:
        args = ['api', '-X', method, path.replace('{repo}', self.repo)]
        if pages:
            args += ['--paginate', '--slurp']
        if body is not None:
            args += ['--input', '-']
        out = self.run(args, None if body is None else json.dumps(body))
        data = json.loads(out) if out.strip() else None
        return [item for page in data for item in page] if pages else data

    # --- reads

    def head(self, target: Target) -> str:
        if target.pr:
            return self.api(f'repos/{{repo}}/pulls/{target.pr}')['head']['sha']
        return self.api(f'repos/{{repo}}/commits/{target.ref}')['sha']

    def runs(self, sha: str) -> list[dict[str, Any]]:
        """The `momayez` check runs on `sha`, newest first."""
        data = self.api(f'repos/{{repo}}/commits/{sha}/check-runs?check_name={CHECK_RUN}&per_page=100')
        return sorted(data['check_runs'], key=lambda r: r['id'], reverse=True)

    def default_branch(self) -> str:
        return self.api('repos/{repo}')['default_branch']

    def workflow_run(self, run_id: int) -> dict[str, Any]:
        return self.api(f'repos/{{repo}}/actions/runs/{run_id}')

    def dispatched_runs(self, workflow: str) -> list[dict[str, Any]]:
        """The workflow's recent dispatch runs, newest first."""
        path = f'repos/{{repo}}/actions/workflows/{workflow}/runs?event=workflow_dispatch&per_page=50'
        return sorted(self.api(path)['workflow_runs'], key=lambda r: r['id'], reverse=True)

    def artifact_ledger(self, run_id: int) -> ledgers.Ledger | None:
        """The ledger a run left in its momayez-ledger artifact; None when it left none."""
        names = {a['name'] for a in self.api(f'repos/{{repo}}/actions/runs/{run_id}/artifacts')['artifacts']}
        if ARTIFACT not in names:
            return None
        with tempfile.TemporaryDirectory() as where:
            self.run(['run', 'download', str(run_id), '--repo', self.repo, '-n', ARTIFACT, '-D', where], None)
            path = os.path.join(where, 'ledger.json')
            if not os.path.isfile(path):
                return None
            with open(path, encoding='utf-8') as handle:
                return ledgers.loads(handle.read())

    def comments(self, pr: int) -> list[dict[str, Any]]:
        return self.api(f'repos/{{repo}}/issues/{pr}/comments?per_page=100', pages=True)

    # --- writes

    def upsert_comment(self, pr: int, kind: str, body: str) -> None:
        """Keep one comment per PR that holds a `kind` marker: edit it, or post it."""
        for comment in self.comments(pr):
            if f'<!-- {kind} ' in comment['body']:
                self.api(f'repos/{{repo}}/issues/comments/{comment["id"]}', 'PATCH', {'body': body})
                return
        self.api(f'repos/{{repo}}/issues/{pr}/comments', 'POST', {'body': body})

    def press(self, pr: int, label: str) -> None:
        """Remove then add `label`: adding one already present fires no `labeled` event."""
        try:
            self.api(f'repos/{{repo}}/issues/{pr}/labels/{label}', 'DELETE')
        except GhError as exc:
            if exc.status != 404:
                raise
        self.api(f'repos/{{repo}}/issues/{pr}/labels', 'POST', {'labels': [label]})

    def dispatch(self, workflow: str, inputs: dict[str, str]) -> None:
        args = ['workflow', 'run', workflow, '--repo', self.repo]
        for key, value in inputs.items():
            args += ['-f', f'{key}={value}']
        self.run(args, None)

    def dispatch_run(self, workflow: str, inputs: dict[str, str]) -> int:
        """Dispatch `workflow` on the default branch and return the run it started."""
        body = {'ref': self.default_branch(), 'inputs': inputs, 'return_run_details': True}
        out = self.api(f'repos/{{repo}}/actions/workflows/{workflow}/dispatches', 'POST', body)
        if not out or not out.get('workflow_run_id'):
            raise GhError('the dispatch returned no run id (GitHub API too old for return_run_details?)')
        return int(out['workflow_run_id'])

    def reply(self, pr: int, finding: str, text: str) -> str:
        """Reply on `finding`'s inline thread, else on the PR, where its summary lives."""
        tag = f'<!-- {FINDING_MARKER}{finding} -->'
        threads = [c for c in self.api(f'repos/{{repo}}/pulls/{pr}/comments?per_page=100', pages=True)
                   if tag in c['body']]
        if threads:
            newest = max(threads, key=lambda c: c['id'])
            self.api(f'repos/{{repo}}/pulls/{pr}/comments/{newest["id"]}/replies', 'POST', {'body': text})
            return 'thread'
        self.api(f'repos/{{repo}}/issues/{pr}/comments', 'POST', {'body': f'**Re {finding}** (momayez): {text}'})
        return 'summary'


def run_ledger(run: dict[str, Any]) -> ledgers.Ledger | None:
    """The ledger a completed check run carries, or None; an invalid marker counts as none."""
    try:
        return ledgers.from_marker((run.get('output') or {}).get('text'), REVIEWER_MARKER)
    except ledgers.LedgerError:
        return None
