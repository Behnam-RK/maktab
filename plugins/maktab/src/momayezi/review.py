"""momayezi-review: one review-only round on a fresh clone of the head, the reviewer end of the
k8s-job backend. It prints the ledger as the `momayez-ledger:v2` marker on its last line."""

from __future__ import annotations

import base64
import json
import os
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from . import ledger as ledgers
from .github import Gh, Target
from .post import place
from .protocol import REVIEWER_MARKER

Proc = Callable[..., str]
SECRETS = ('GH_TOKEN', 'GITHUB_TOKEN')


class ReviewError(RuntimeError):
    pass


def run_proc(argv: list[str], cwd: Path | None = None, env: Mapping[str, str] | None = None,
             check: bool = True) -> str:
    try:
        done = subprocess.run(argv, cwd=cwd, env=None if env is None else dict(env),
                              capture_output=True, text=True)
    except FileNotFoundError:
        raise ReviewError(f'{argv[0]} is not installed or not on PATH') from None
    if check and done.returncode != 0:
        raise ReviewError(f'{argv[0]} failed: {(done.stderr or done.stdout).strip()[-2000:]}')
    return done.stdout


def resolve(gh: Gh, target: Target, head: str) -> tuple[str, str | None]:
    """The tip the review diffs against, and the PR's intent; refuses a fork or a moved head."""
    if target.pr:
        pull = gh.api(f'repos/{{repo}}/pulls/{target.pr}')
        if (pull['head'].get('repo') or {}).get('full_name') != gh.repo:
            raise ReviewError(f'#{target.pr} comes from a fork: no review')
        if pull['head']['sha'] != head:
            raise ReviewError(f'#{target.pr} moved from {head} to {pull["head"]["sha"]}: request it again')
        return pull['base']['sha'], f'# {pull["title"]}\n\n{pull.get("body") or ""}\n'
    tip = gh.api(f'repos/{{repo}}/commits/{target.ref}')['sha']
    if tip != head:
        raise ReviewError(f'{target.ref} moved from {head} to {tip}: request it again')
    return gh.api(f'repos/{{repo}}/commits/{gh.default_branch()}')['sha'], None


def git_env(env: Mapping[str, str]) -> dict[str, str]:
    """The token as an HTTP header in the environment: never in argv or .git/config."""
    out = dict(env, GIT_TERMINAL_PROMPT='0')
    token = env.get('GH_TOKEN') or env.get('GITHUB_TOKEN')
    if token:
        auth = base64.b64encode(f'x-access-token:{token}'.encode()).decode()
        out.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
                   GIT_CONFIG_VALUE_0=f'AUTHORIZATION: basic {auth}')
    return out


def clone(proc: Proc, repo: str, workdir: Path, head: str, tip: str, env: Mapping[str, str]) -> str:
    """A full fetch of the head and the tip (the session's git diff may need any blob); the base."""
    where = str(workdir)
    proc(['git', 'init', '-q', where])
    proc(['git', '-C', where, 'remote', 'add', 'origin', f'https://github.com/{repo}.git'])
    proc(['git', '-C', where, 'fetch', '-q', '--no-tags', 'origin', head, tip], env=git_env(env))
    proc(['git', '-C', where, 'checkout', '-q', '--detach', head])
    return proc(['git', '-C', where, 'merge-base', tip, head]).strip()


def review(gh: Gh, target: Target, head: str, prior: str, workdir: Path, proc: Proc = run_proc,
           env: Mapping[str, str] | None = None) -> ledgers.Ledger:
    env = dict(os.environ) if env is None else dict(env)
    tip, intent = resolve(gh, target, head)
    base = clone(proc, gh.repo, workdir, head, tip, env)
    # Both files sit inside the checkout: the session reads nothing outside it.
    meta = workdir / '.momayez'
    meta.mkdir(exist_ok=True)
    args = ['--review-only', '--base', base, '--head', head, '--json']
    if prior.strip():
        (meta / 'prior.json').write_text(ledgers.dumps(ledgers.loads(prior)), encoding='utf-8')
        args += ['--ledger', '.momayez/prior.json']
    if intent:
        (meta / 'intent.md').write_text(intent, encoding='utf-8')
        args += ['--intent', '.momayez/intent.md']
    # --setting-sources user: a project's env and apiKeyHelper run despite managed settings.
    out = proc(['claude', '-p', '/maktab:momayezi ' + ' '.join(args), '--setting-sources', 'user',
                '--permission-mode', 'dontAsk', '--tools', 'Read,Bash,Agent', '--max-turns', '80',
                '--output-format', 'json', '--json-schema', json.dumps(ledgers.schema())],
               cwd=workdir, env={k: v for k, v in env.items() if k not in SECRETS}, check=False)
    try:
        result = json.loads(out)
    except ValueError:
        raise ReviewError(f'the review printed no JSON: {out.strip()[-500:]}') from None
    found = result.get('structured_output') if isinstance(result, dict) else None
    if not isinstance(found, dict):
        why = (result.get('result') or result.get('subtype') or '') if isinstance(result, dict) else ''
        raise ReviewError(f'the review returned no ledger: {str(why)[-500:]}')
    # The commits this run reviewed, whatever the session wrote.
    found = dict(found, target=dict(found.get('target') or {}, base_sha=base, head_sha=head))
    return ledgers.fit(place(target, gh.repo, found), REVIEWER_MARKER)
