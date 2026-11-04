from __future__ import annotations

from typing import NamedTuple


# The currency every rule producer returns and the renderer consumes. It lived
# in rules.py, which made corpus, scanner and both analyzers depend on the
# markdown rule engine for a five-field tuple they share with it.
class Finding(NamedTuple):
    rel: str
    line: int
    rule: str
    severity: str
    message: str
    hint: str = ''
