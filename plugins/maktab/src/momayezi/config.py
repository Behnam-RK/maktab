"""Which reviewer backend runs a remote review, and whether momayezi writes to the PR.

The backend: $MOMAYEZI_REVIEWER_BACKEND, then the user's `momayezi_reviewer_backend` setting
(unless `repo`), then `.momayezi.toml`'s `backend`, then gh-label. gh-dispatch's ref is
`.momayezi.toml`'s `dispatch_ref`. PR writes come from the
user's `momayezi_pr_comments` setting. The MCP server sees the two settings as
MOMAYEZI_USER_* (plugin.json maps them), apart from the shell override.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .protocol import BACKENDS, CONFIG_FILE, OLD_CONFIG_FILE, PR_COMMENTS


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class K8s:
    template: Path
    namespace: str
    context: str | None = None


@dataclass(frozen=True)
class Settings:
    backend: str
    pr_comments: str  # resolved: 'all' or 'none'
    k8s: K8s | None = None
    dispatch_ref: str | None = None  # gh-dispatch's ref; None is the repo's default branch


def _set(value: str | None) -> str:
    """A setting's value; an unsubstituted `${user_config...}` or an empty one is unset."""
    value = (value or '').strip()
    return '' if value.startswith('${') else value


def _file(root: Path) -> dict:
    path = root / CONFIG_FILE
    if not path.is_file():
        # Silently falling back to gh-label would press a label that may fire the repo's CI.
        if (root / OLD_CONFIG_FILE).is_file():
            raise ConfigError(f'{OLD_CONFIG_FILE} was renamed {CONFIG_FILE} in maktab 2.5.0: rename it')
        return {}
    try:
        return tomllib.loads(path.read_text(encoding='utf-8'))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f'{CONFIG_FILE}: {exc}') from None


def _k8s(root: Path, table: object) -> K8s:
    if not isinstance(table, dict) or not table.get('template') or not table.get('namespace'):
        raise ConfigError(f'k8s-job needs [k8s] template and namespace in {CONFIG_FILE}')
    context = table.get('context')
    return K8s(root / str(table['template']), str(table['namespace']), str(context) if context else None)


def load(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    root = Path(env.get('CLAUDE_PROJECT_DIR') or os.getcwd())
    user = _set(env.get('MOMAYEZI_USER_REVIEWER_BACKEND'))
    chosen = _set(env.get('MOMAYEZI_REVIEWER_BACKEND')) or (user if user != 'repo' else '')
    # The repo file is read only when it decides something: the backend, k8s-job's [k8s],
    # or gh-dispatch's `dispatch_ref`.
    repo = _file(root) if chosen in ('', 'k8s-job', 'gh-dispatch') else {}
    backend = chosen or str(repo.get('backend') or '') or 'gh-label'
    if backend not in BACKENDS:
        raise ConfigError(f'unknown reviewer backend {backend!r}: one of {", ".join(BACKENDS)}')
    comments = _set(env.get('MOMAYEZI_USER_PR_COMMENTS')) or 'auto'
    if comments not in PR_COMMENTS:
        raise ConfigError(f'unknown pr_comments {comments!r}: one of {", ".join(PR_COMMENTS)}')
    if comments == 'auto':
        comments = 'none' if backend == 'k8s-job' else 'all'
    if backend == 'gh-label' and comments == 'none':
        raise ConfigError('gh-label needs PR comments: a label carries no ledger. '
                          'Use gh-dispatch or k8s-job for pr_comments=none')
    k8s = _k8s(root, repo.get('k8s')) if backend == 'k8s-job' else None
    ref = str(repo.get('dispatch_ref') or '') if backend == 'gh-dispatch' else ''
    return Settings(backend, comments, k8s, ref or None)
