"""momayezi-review: one review-only round on a fresh clone of the head, the reviewer end of every
backend. It prints the ledger as the `momayezi-ledger:v2` marker on its last line; a failure is a
last `momayezi-error:` line instead. With --out, ledger.json or error.json is also written there."""

from __future__ import annotations

import base64
import json
import os
import posixpath
import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path

from . import failure as failures
from . import ledger as ledgers
from . import poll
from .github import Gh, Target
from .post import place
from .protocol import REVIEWER_MARKER

Proc = Callable[..., str]
SECRETS = ('GH_TOKEN', 'GITHUB_TOKEN')


# Claude Code's own import depth; a project's memory files, read from the base branch.
MEMORY_FILES = ('CLAUDE.md', 'AGENTS.md')
MEMORY_HOPS = 4
# Linux caps one argv string at 128 KiB; the memory goes in as one.
MEMORY_CAP = 120_000
CODE = re.compile(r'```.*?```|`[^`\n]*`', re.S)
IMPORT = re.compile(r'(?<![\w@])@([^\s`()<>\[\]]*[/.][^\s`()<>\[\]]*)')
# Concise: the orchestrating session's own prose, never the reviewers'. No MCP server: review-only
# calls none, and each would cost tool definitions and startup.
SESSION = ['--settings', json.dumps({'outputStyle': 'Concise'}),
           '--strict-mcp-config', '--mcp-config', json.dumps({'mcpServers': {}})]


class ReviewError(RuntimeError):
    def __init__(self, message: str, failure: failures.Failure | None = None):
        super().__init__(message)
        self.failure = failure or {'status': 'failed', 'reason': message}


def run_proc(argv: list[str], cwd: Path | None = None, env: Mapping[str, str] | None = None,
             check: bool = True, stdin: str | None = None) -> str:
    try:
        done = subprocess.run(argv, cwd=cwd, env=None if env is None else dict(env), input=stdin,
                              capture_output=True, text=True)
    except FileNotFoundError:
        raise ReviewError(f'{argv[0]} is not installed or not on PATH') from None
    if check and done.returncode != 0:
        raise ReviewError(f'{argv[0]} failed: {(done.stderr or done.stdout).strip()[-2000:]}')
    return done.stdout


def moved(target: Target, head: str, live: str, why: str = '') -> ReviewError:
    return ReviewError(f'{target.label} moved from {head} to {live}{why}: request it again')


def resolve(gh: Gh, target: Target, head: str, follow_rebase: bool = False) -> tuple[str, str | None, str]:
    """The tip the review diffs against, the PR's intent, and the live head; refuses a fork, and
    a moved head unless `follow_rebase` (the caller then checks the change is the same)."""
    if target.pr:
        pull = gh.api(f'repos/{{repo}}/pulls/{target.pr}')
        if (pull['head'].get('repo') or {}).get('full_name') != gh.repo:
            raise ReviewError(f'#{target.pr} comes from a fork: no review')
        live = pull['head']['sha']
        if live != head and not follow_rebase:
            raise moved(target, head, live)
        return pull['base']['sha'], f'# {pull["title"]}\n\n{pull.get("body") or ""}\n', live
    live = gh.api(f'repos/{{repo}}/commits/{target.ref}')['sha']
    if live != head and not follow_rebase:
        raise moved(target, head, live)
    return gh.api(f'repos/{{repo}}/commits/{gh.default_branch()}')['sha'], None, live


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


def patch_id(proc: Proc, where: str, tip: str, head: str) -> str:
    """The change `head` makes on its branch, line numbers and whitespace aside."""
    base = proc(['git', '-C', where, 'merge-base', tip, head]).strip()
    diff = proc(['git', '-C', where, 'diff', base, head])
    return (proc(['git', '-C', where, 'patch-id', '--stable'], stdin=diff).split() or [''])[0]


def same_change(proc: Proc, where: str, tip: str, old: str, new: str, env: Mapping[str, str]) -> bool:
    """Whether `new` is `old` rebased: the same patch-id over each one's merge-base..head. An old
    head GitHub no longer serves can't be compared, so it isn't the same."""
    try:
        proc(['git', '-C', where, 'fetch', '-q', '--no-tags', 'origin', old], env=git_env(env))
    except ReviewError:
        return False
    found = patch_id(proc, where, tip, old)
    return bool(found) and found == patch_id(proc, where, tip, new)


def imports(text: str) -> list[str]:
    """The `@path` imports of a memory file, outside code, as Claude Code reads them."""
    return [m.rstrip('.,;:!?') for m in IMPORT.findall(CODE.sub('', text))]


def project_memory(proc: Proc, where: str, rev: str) -> tuple[str, list[str]]:
    """CLAUDE.md, else AGENTS.md, with its imports, as of `rev`: the repo's rules as merged, so
    a change can't rewrite its own reviewer's. Imports stay inside the checkout."""
    def show(path: str) -> str:
        return proc(['git', '-C', where, 'show', f'{rev}:{path}'], check=False)
    root = next(((path, text) for path in MEMORY_FILES if (text := show(path)).strip()), None)
    if root is None:
        return '', []
    parts: list[str] = []
    notes: list[str] = []
    seen: set[str] = set()

    def visit(path: str, text: str, hops: int) -> None:
        seen.add(path)
        parts.append(f'<!-- {path} -->\n{text.rstrip()}\n')
        for name in imports(text) if hops < MEMORY_HOPS else ():
            child = posixpath.normpath(posixpath.join(posixpath.dirname(path), name))
            if name.startswith(('~', '/')) or child == '..' or child.startswith('../'):
                notes.append(f'project memory: skipped @{name}, outside the checkout')
            elif child not in seen and (body := show(child)).strip():
                visit(child, body, hops + 1)
    visit(*root, 0)
    text = 'The repository\'s project memory, from its base branch:\n\n' + '\n'.join(parts)
    if len(text.encode('utf-8')) > MEMORY_CAP:
        text = text.encode('utf-8')[:MEMORY_CAP].decode('utf-8', 'ignore')
        notes.append(f'project memory: cut to {MEMORY_CAP} bytes')
    return text, notes


def outcome(out: str) -> dict:
    """The ledger claude's JSON output carries; a ReviewError, `limited` or `failed`, says why not."""
    try:
        result = json.loads(out)
    except ValueError:
        message = f'the review printed no JSON: {out.strip()[-500:]}'
        raise ReviewError(message, failures.classify(message, poll.now())) from None
    found = result.get('structured_output') if isinstance(result, dict) else None
    if not isinstance(found, dict):
        why = (result.get('result') or result.get('subtype') or '') if isinstance(result, dict) else ''
        message = f'the review returned no ledger: {str(why)[-500:]}'
        raise ReviewError(message, failures.classify(message, poll.now()))
    return found


def review(gh: Gh, target: Target, head: str, prior: str, workdir: Path, proc: Proc = run_proc,
           env: Mapping[str, str] | None = None, follow_rebase: bool = False,
           memory: bool = True) -> ledgers.Ledger:
    env = dict(os.environ) if env is None else dict(env)
    tip, intent, live = resolve(gh, target, head, follow_rebase)
    base = clone(proc, gh.repo, workdir, live, tip, env)
    notes: list[str] = []
    if live != head:
        if not same_change(proc, str(workdir), tip, head, live, env):
            raise moved(target, head, live, ', a different change')
        notes.append(f'head rebased from {head}; same change')
    # Both files sit inside the checkout: the session reads nothing outside it.
    meta = workdir / '.momayezi'
    meta.mkdir(exist_ok=True)
    args = ['--review-only', '--base', base, '--head', live, '--json']
    if prior.strip():
        (meta / 'prior.json').write_text(ledgers.dumps(ledgers.loads(prior)), encoding='utf-8')
        args += ['--ledger', '.momayezi/prior.json']
    if intent:
        (meta / 'intent.md').write_text(intent, encoding='utf-8')
        args += ['--intent', '.momayezi/intent.md']
    rules, more = project_memory(proc, str(workdir), tip) if memory else ('', [])
    notes += more
    # --setting-sources user: a project's env and apiKeyHelper run despite managed settings. It
    # also drops the project's CLAUDE.md, so its rules come back, from the base, as `rules`.
    argv = ['claude', '-p', '/maktab:momayezi ' + ' '.join(args), '--setting-sources', 'user', *SESSION,
            '--permission-mode', 'dontAsk', '--tools', 'Read,Bash,Agent', '--max-turns', '80',
            '--output-format', 'json', '--json-schema', json.dumps(ledgers.schema())]
    if rules:
        argv += ['--append-system-prompt', rules]
    found = outcome(proc(argv, cwd=workdir, env={k: v for k, v in env.items() if k not in SECRETS}, check=False))
    # The commits this run reviewed, whatever the session wrote, and what it couldn't know.
    stamp = dict(found.get('target') or {}, base_sha=base, head_sha=live)
    if live != head:
        stamp['rebased_from'] = head
    found = dict(found, target=stamp)
    if notes:
        found['notes'] = [*(found.get('notes') or []), *notes]
    return ledgers.fit(place(target, gh.repo, found), REVIEWER_MARKER)
