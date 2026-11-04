from __future__ import annotations

import subprocess
from pathlib import Path

from docsteward.config import Config
from docsteward.markdown import Doc, analyze
from docsteward.tokens import Counter


# The estimator at grace 1.0: 4 chars per token, and caps exactly as written.
def counter() -> Counter:
    return Counter('test', 1.0)


def doc(text: str, rel: str = 'docs/guide.md') -> Doc:
    return analyze(rel, text, counter())


def config(**sections) -> Config:
    return Config({k.replace('_', '-'): v for k, v in sections.items()})


def rules(**severities: str) -> Config:
    return Config({'rules': {
        rule_id.replace('_', '-'): {'severity': severity}
        for rule_id, severity in severities.items()
    }})


# `n` tokens of prose for the estimator, split into lines short enough that
# prose-line-long stays quiet.
def prose(tokens: int) -> str:
    line = 'word ' * 15 + '\n'
    out = line * (tokens * 4 // len(line) + 1)
    return out[: tokens * 4]


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ['git', '-c', 'user.name=t', '-c', 'user.email=t@t', *args],
        cwd=root, capture_output=True, text=True, check=True,
    )
    return result.stdout


def write(root: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')


def repo(root: Path, files: dict[str, str] | None = None) -> Path:
    git(root, 'init', '-q', '-b', 'main')
    if files:
        commit(root, files)
    return root


def commit(root: Path, files: dict[str, str], message: str = 'c') -> str:
    write(root, files)
    git(root, 'add', '-A')
    git(root, 'commit', '-q', '-m', message)
    return git(root, 'rev-parse', 'HEAD').strip()
