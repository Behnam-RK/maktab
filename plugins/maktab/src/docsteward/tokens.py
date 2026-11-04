from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path


# Changing the encoding changes every count, and the shipped caps are derived
# against this exact name.
ENCODING = 'cl100k_base'

# Best of the models measured against cl100k_base (word- and blend-based
# estimators had wider spread): median ratio 1.006, range 0.84-1.34.
ESTIMATE_CHARS_PER_TOKEN = 4.0

# Covers that 1.34 worst-case over-count, so the estimate can never fail a doc
# the real counter would pass. Offline must degrade to permissive, never to
# blocking; CI passes --require-exact so the authoritative number is always real.
ESTIMATE_GRACE = 1.35

COUNTER_ENV = ('DOCS_COUNTER', 'DOC_BUDGET_COUNTER')


class Counter:
    def __init__(self, name: str, grace: float, encode: Callable[[str], list[int]] | None = None):
        self.name = name
        self.grace = grace
        self._encode = encode

    @property
    def exact(self) -> bool:
        return self._encode is not None

    def count(self, text: str) -> int:
        if self._encode is not None:
            return len(self._encode(text))
        return round(len(text) / ESTIMATE_CHARS_PER_TOKEN)


class ExactCountUnavailable(RuntimeError):
    pass


def _estimator() -> Counter:
    return Counter('estimate', ESTIMATE_GRACE)


def _cache_dir() -> Path:
    # Never default into the repo: `git add -A` in a consuming project would
    # otherwise sweep a multi-megabyte BPE blob into the index.
    override = os.environ.get('XDG_CACHE_HOME')
    # The XDG spec requires an absolute path, and a relative one here would put
    # that blob under whatever directory the gate happened to be run from.
    base = Path(override) if override and Path(override).is_absolute() else Path.home() / '.cache'
    return base / 'docsteward' / 'tiktoken'


def _tiktoken() -> Counter:
    os.environ.setdefault('TIKTOKEN_CACHE_DIR', str(_cache_dir()))
    Path(os.environ['TIKTOKEN_CACHE_DIR']).mkdir(parents=True, exist_ok=True)
    import tiktoken

    encoding = tiktoken.get_encoding(ENCODING)

    # A doc quoting `<|endoftext|>` is text to be counted, not a request the
    # encoder refuses with a ValueError that killed the whole run.
    def encode(text: str) -> list[int]:
        return encoding.encode(text, disallowed_special=())

    return Counter(f'tiktoken/{ENCODING}', 1.0, encode)


def _forced_estimate() -> bool:
    return any(os.environ.get(name) == 'estimate' for name in COUNTER_ENV)


def resolve(require_exact: bool = False) -> Counter:
    if _forced_estimate() and not require_exact:
        return _estimator()
    try:
        return _tiktoken()
    except Exception as exc:
        # Offline, no wheel, unwritable cache — a budget gate must not become a
        # network dependency, so degrade unless the caller demands exactness.
        if require_exact:
            raise ExactCountUnavailable(str(exc)) from exc
        return _estimator()
