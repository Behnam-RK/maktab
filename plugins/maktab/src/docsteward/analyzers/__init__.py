from __future__ import annotations

from pathlib import PurePosixPath

from ..config import Config
from ..findings import Finding
from . import comments, python


# Suffix to analyzer. This was an if/else because the two entry points had
# different arity — only the Python one took a baseline — so a table could not
# hold them.
BY_SUFFIX = {suffix: python.findings_for for suffix in ('.py', '.pyi')}
DEFAULT = comments.findings_for


# PurePosixPath, not a hand-rolled rsplit: `.github/workflows/release` has a dot
# in a directory and no extension on the file, which split into the "suffix"
# `.github/workflows/release`. The comment analyzer asks the same question.
def findings_for(
    rel: str, source: str, baseline: str | None, config: Config
) -> list[Finding]:
    suffix = PurePosixPath(rel).suffix
    return BY_SUFFIX.get(suffix, DEFAULT)(rel, source, baseline, config)


__all__ = ['comments', 'findings_for', 'python']
