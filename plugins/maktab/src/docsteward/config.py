from __future__ import annotations

import copy
import re
import tomllib
from fnmatch import fnmatchcase
from pathlib import Path
from string import Formatter
from typing import Any, NamedTuple


CONFIG_NAME = '.docs.toml'
FAIL, WARN, OFF = 'fail', 'warn', 'off'
SEVERITIES = (FAIL, WARN, OFF)

DEFAULT_SOFT, DEFAULT_HARD = 1000, 1400

# READMEs are the first doc an agent reads, so they are measured rather than
# exempted; an accepted ADR is a record of a past decision, so editing one to fit
# a budget rewrites history. Both keep the house shape a repo can override.
BUILTIN_OVERRIDES: tuple[dict[str, Any], ...] = (
    {'pattern': '**/README.md', 'soft': 2000, 'hard': 3000},
    {'pattern': 'docs/adr/**', 'soft': 1200, 'hard': 2000, 'structure_rules': False,
     'rules': {'stale-file-ref': OFF}},
)

BUILTIN_EXCLUDE = (
    '**/*_pb2.py',
    '**/*_pb2_grpc.py',
    '**/*_pb2.pyi',
    '**/*_pb2_grpc.pyi',
)
BUILTIN_ALWAYS_EXEMPT = ('CHANGELOG.md', '*.prompt.md')

# The one place a rule is declared: its default severity, the prose
# `tahrir --explain` prints, and its knobs. Adding a rule is one edit here.
# A rule absent from a profile keeps these.
RULE_DEFAULTS: dict[str, dict[str, Any]] = {
    'over-hard-cap': {
        'severity': FAIL,
        'help': 'A doc past its hard cap stops being read. Split it or cut it.',
    },
    'over-soft-cap': {
        'severity': WARN,
        'help': 'Early warning that a doc is heading for its hard cap.',
    },
    'wall-of-text': {
        'severity': WARN,
        'help': 'Too many tokens per heading — the doc cannot be navigated or split.',
        'tokens_per_heading': 450,
        'floor': 400,
    },
    'over-fragmented': {
        'severity': WARN,
        'help': 'Many thin sections cost more in headings than they carry.',
        'min_headings': 6,
        'tokens_per_heading': 60,
    },
    'cross-doc-duplicate': {
        'severity': WARN,
        'help': 'Two docs stating the same rule drift apart. Link, do not copy.',
        'min_tokens': 40,
    },
    'doc-code-ratio': {
        'severity': OFF,
        'help': 'A long doc propping up code that is hard to follow means the code needs the work.',
        'ratio': 0.15,
        'floor': 20_000,
    },
    'prose-line-long': {
        'severity': WARN,
        'help': 'Long prose lines make diffs unreadable.',
        'max_chars': 110,
    },
    'table-cell-crammed': {
        'severity': WARN,
        'help': 'A crammed cell is a paragraph wearing a table.',
        'max_chars': 120,
    },
    'list-item-long': {
        'severity': WARN,
        'help': 'A long list item is a paragraph wearing a bullet.',
        'max_chars': 600,
    },
    'docstring': {
        'severity': OFF,
        'help': 'A docstring no runtime surfaces is a comment that costs an import.',
    },
    'comment-block': {
        'severity': WARN,
        'help': 'A long comment block is documentation in the wrong place.',
        'max_lines': 3,
    },
    'stale-file-ref': {
        'severity': WARN,
        'help': (
            'A reference to a file that no longer exists sends a reader nowhere. '
            'Resolved relative to the doc, the repo root, the doc\'s package '
            '([corpus] package_roots) and the nearest sub-project with a manifest '
            '(pyproject.toml, package.json, go.mod…); docs/adr/** (or the --adr-dir '
            'override init writes) is exempt, as history; '
            'a target matching ignore_patterns is skipped; '
            '`<!-- docs: allow stale-file-ref -->` on the line or the one above '
            'allows one. resolve_by_suffix also accepts a path any tracked file ends with.'
        ),
        'ignore_patterns': ['*/v[0-9]*', '*/vX.*'],
        'resolve_by_suffix': False,
    },
    'adr-number-collision': {
        'severity': WARN,
        'help': (
            'Two ADRs holding one number is two pull requests that each took the next '
            'free one. Reports every file sharing a number, and an index row that '
            'links a missing file or an ADR the index omits (index = "" skips that). '
            'A repo whose ADRs are named by slug sets adr_glob to match them, e.g. '
            '"docs/adr/*.md"; the index and template.md are never counted as ADRs.'
        ),
        'adr_glob': 'docs/adr/[0-9][0-9][0-9][0-9]-*.md',
        'index': 'docs/adr/README.md',
    },
    'changelog-unreleased-tagged': {
        'severity': WARN,
        'help': (
            'A `## [X.Y.Z] - Unreleased` heading whose git tag exists was released and '
            'never dated. Needs the tags: a CI checkout fetches none by default '
            '(fetch-tags: true). tag_patterns maps a CHANGELOG glob to a tag template '
            'with {version}; default_tag covers the rest.'
        ),
        'tag_patterns': {},
        'default_tag': 'v{version}',
    },
    'changed-without-docs': {
        'severity': OFF,
        'help': 'Code moved and no doc did. Confirm the change is invisible.',
    },
    'todo-marker': {
        'severity': OFF,
        'help': 'A TODO in a shipped doc is a promise nobody tracks.',
        'markers': ['TODO', 'FIXME', 'HACK', 'XXX'],
    },
    'open-checkbox': {
        'severity': OFF,
        'help': 'An open checkbox in a shipped doc is state, not documentation.',
    },
    'section-citation': {
        'severity': OFF,
        'help': 'A cited section that no longer exists is a dangling cross-reference.',
    },
}

# `strict` reproduces the policy the gate enforced before extraction: docstrings
# are deleted unless a runtime surfaces them. What it promotes is the frozen
# part -- a suppression it carried for a noisy rule lifts when the noise does.
PROFILES: dict[str, dict[str, dict[str, Any]]] = {
    'default': {},
    'strict': {
        'docstring': {'severity': FAIL},
        'doc-code-ratio': {'severity': WARN},
    },
}

DEFAULT_COMMENT_PREFIXES: dict[str, str] = {
    '.ts': '//', '.tsx': '//', '.js': '//', '.jsx': '//', '.mjs': '//', '.cjs': '//',
    '.go': '//', '.rs': '//', '.java': '//', '.kt': '//', '.swift': '//', '.c': '//',
    '.h': '//', '.cc': '//', '.cpp': '//', '.hpp': '//', '.cs': '//', '.scala': '//',
    '.php': '//', '.dart': '//', '.zig': '//', '.proto': '//', '.svelte': '//',
    '.sh': '#', '.bash': '#', '.zsh': '#', '.yaml': '#', '.yml': '#', '.toml': '#',
    '.tf': '#', '.tfvars': '#', '.rb': '#', '.pl': '#', '.r': '#', '.nix': '#',
    '.sql': '--', '.lua': '--', '.hs': '--', '.elm': '--',
    '.el': ';', '.clj': ';', '.lisp': ';',
}


class Rule(NamedTuple):
    id: str
    severity: str
    opts: dict[str, Any]

    @property
    def on(self) -> bool:
        return self.severity != OFF


class ConfigError(ValueError):
    pass


def _check_severity(rule_id: str, severity: Any, where: str = '') -> str:
    if severity not in SEVERITIES:
        prefix = f'{where}: ' if where else ''
        raise ConfigError(
            f'{prefix}{rule_id}: severity must be one of '
            f'{", ".join(SEVERITIES)}, got {severity!r}'
        )
    return severity


# `a whole number` is what the message below promises, so a fractional float is
# rejected rather than truncated: `soft = 0.5` coerced to 0 and put every doc in
# the repo over the cap, silently, from a value the validator had accepted.
def _whole_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    return isinstance(value, int) or (isinstance(value, float) and value.is_integer())


def _same_shape(default: Any, value: Any) -> bool:
    # TOML booleans are their own type, but Python makes bool a subclass of int,
    # so `enabled = 1` would otherwise pass for a boolean knob.
    if isinstance(default, bool) or isinstance(value, bool):
        return isinstance(default, bool) and isinstance(value, bool)
    # A whole-number knob is read as a count, so `max_chars = 1.5` is not one.
    if isinstance(default, int):
        return _whole_number(value)
    if isinstance(default, int | float):
        return isinstance(value, int | float)
    return isinstance(value, type(default))


_SHAPES = {
    int: 'a whole number',
    bool: 'true or false',
    list: 'a list of strings',
    dict: 'a table of strings',
    str: 'a string',
}


# Declared per rule but not configurable, and not knobs.
RESERVED_KEYS = ('severity', 'help')


# Every table `Config` reads, plus `doc-gate`, which the `UserPromptSubmit` hook
# owns rather than the engine. A key outside this set is a typo that silently
# did nothing, which is the failure this config surface exists to stop.
SECTIONS = ('profile', 'defaults', 'overrides', 'exclude', 'rules', 'python',
            'comments', 'corpus', 'doc-gate')

OVERRIDE_KEYS = ('pattern', 'soft', 'hard', 'structure_rules', 'rules', 'status')

# The engine does not read `[doc-gate]` — the UserPromptSubmit hook does, out of
# the same file — but `.docs.toml` is the engine's to validate, and a typo here
# is the silent fallback the rest of this validation exists to stop.
DOC_GATE_KEYS = ('enabled', 'routing_doc', 'trigger')

# The keys each table reads. `rules` has its own per-rule check, and `overrides`
# is a list with its own key set.
SECTION_KEYS: dict[str, tuple[str, ...]] = {
    'defaults': ('soft', 'hard'),
    'exclude': ('paths', 'always_exempt'),
    'python': ('enabled', 'runtime_surfaced_decorators', 'module_docstring_cap',
               'docstring_cap', 'cli_help_exempts_module'),
    'comments': ('enabled', 'prefixes'),
    'corpus': ('doc_globs', 'code_globs', 'package_roots'),
    'doc-gate': DOC_GATE_KEYS,
}


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    # Indexing into a section without checking it is a table turns `exclude =
    # "vendor"` into a substring test that silently accepts, and `defaults = 5`
    # into a TypeError.
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f'[{name}] must be a table, got {value!r}')
    keys = SECTION_KEYS.get(name, ())
    stray = [key for key in value if keys and key not in keys]
    if stray:
        raise ConfigError(
            f'[{name}]: unknown key(s) {", ".join(sorted(stray))} — '
            f'choose from {", ".join(keys)}'
        )
    return value


def _typed(section: str, table: dict[str, Any], key: str, expected: type, default: Any) -> Any:
    if key not in table:
        return default
    value = table[key]
    if expected is bool:
        # TOML has real booleans, and `enabled = "no"` was silently truthy.
        ok = isinstance(value, bool)
    elif expected is int:
        ok = _whole_number(value)
    elif expected is list:
        # A bare string used to be accepted and split into one glob per
        # character, after which the gate matched nothing and passed.
        ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
    elif expected is dict:
        # The values are used as comment prefixes, so a non-string one reaches
        # str.startswith and raises part-way through a run.
        ok = isinstance(value, dict) and all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        )
    else:
        ok = isinstance(value, expected)
    where = f'[{section}]: ' if section else ''
    if not ok:
        raise ConfigError(f'{where}{key} must be {_SHAPES[expected]}, got {value!r}')
    if expected is int and value < 0:
        raise ConfigError(f'{where}{key} must not be negative, got {value!r}')
    return expected(value) if expected in (int, bool) else value


def _check_opts(rule_id: str, configured: dict[str, Any]):
    base = RULE_DEFAULTS[rule_id]
    knobs = sorted(k for k in base if k not in RESERVED_KEYS)
    for key, value in configured.items():
        if key == 'severity':
            continue
        if key not in base or key in RESERVED_KEYS:
            choices = f'choose from {", ".join(knobs)}' if knobs else 'it has no knobs'
            raise ConfigError(f'[rules.{rule_id}]: unknown key {key!r} — {choices}')
        if not _same_shape(base[key], value):
            raise ConfigError(
                f'[rules.{rule_id}]: {key} must be '
                f'{type(base[key]).__name__}, got {value!r}'
            )
        if not isinstance(value, bool | str | list | dict) and value < 0:
            raise ConfigError(f'[rules.{rule_id}]: {key} must not be negative, got {value!r}')
        # Values of a table knob, for the same reason: `tag_patterns = {a = 1}`
        # otherwise reaches `str.format` mid-run.
        if isinstance(base[key], dict) and not all(
            isinstance(k, str) and isinstance(v, str) for k, v in value.items()
        ):
            raise ConfigError(
                f'[rules.{rule_id}]: {key} must be a table of strings, got {value!r}'
            )
        # Elements too, the same as `_typed` does for the section keys: every
        # list knob is a list of strings, and `markers = [1]` otherwise passed
        # here and reached `re.escape` mid-run as a traceback.
        if isinstance(base[key], list) and not all(isinstance(item, str) for item in value):
            raise ConfigError(
                f'[rules.{rule_id}]: {key} must be a list of strings, got {value!r}'
            )


# `]` straight after the opening `[` or `[!` is a member, not the close. -1 for an
# unclosed class, which the caller keeps as a literal `[`.
def _class_end(pattern: str, start: int) -> int:
    i = start + 1
    if pattern.startswith('!', i):
        i += 1
    if pattern.startswith(']', i):
        i += 1
    return pattern.find(']', i)


# `[z-a]` is a reversed range: it raised from the first match, after load had
# accepted it. A class the regex engine refuses is the characters it spells.
def _compiles(piece: str) -> bool:
    try:
        re.compile(piece)
    except re.error:
        return False
    return True


# `(?!/)` because a class is one character of a path segment: `[!a]` read as a
# bare negation would match the separator and let `*/v[!x]*` cross directories.
def _class_re(body: str) -> str:
    negate = body.startswith('!')
    members = body[1:] if negate else body
    members = members.replace('\\', '\\\\').replace('[', '\\[').replace('^', '\\^')
    return f'(?!/)[{"^" if negate else ""}{members}]'


# A template that fails here would otherwise raise from `str.format` in the middle
# of a run, or silently build a tag that is never looked up.
def _check_tag_templates(configured: dict[str, Any]) -> None:
    templates = {**configured.get('tag_patterns', {})}
    if 'default_tag' in configured:
        templates['default_tag'] = configured['default_tag']
    for where, template in templates.items():
        try:
            # Parsed, not searched: `{version}` is a substring of `{{version}}`,
            # which formats to the literal text `{version}` and a tag never cut.
            fields = {name for _, name, _, _ in Formatter().parse(template) if name is not None}
            ok = fields == {'version'} and template.format(version='0.0.0')
        except (KeyError, IndexError, ValueError, AttributeError, TypeError):
            ok = False
        if not ok:
            raise ConfigError(
                f'[rules.changelog-unreleased-tagged]: {where}: {template!r} must be a '
                'tag template using {version} and no other placeholder'
            )


def _glob_re(pattern: str) -> re.Pattern[str]:
    out = ['(?s:']
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if pattern.startswith('**/', i):
            out.append('(?:.*/)?')
            i += 3
        elif pattern.startswith('**', i):
            out.append('.*')
            i += 2
        elif char == '*':
            out.append('[^/]*')
            i += 1
        elif char == '?':
            out.append('[^/]')
            i += 1
        elif (
            char == '['
            and (end := _class_end(pattern, i)) != -1
            and _compiles(piece := _class_re(pattern[i + 1 : end]))
        ):
            out.append(piece)
            i = end + 1
        else:
            out.append(re.escape(char))
            i += 1
    out.append(r')\Z')
    return re.compile(''.join(out))


_GLOB_CACHE: dict[str, re.Pattern[str]] = {}


def glob_match(rel: str, pattern: str) -> bool:
    compiled = _GLOB_CACHE.get(pattern)
    if compiled is None:
        compiled = _GLOB_CACHE[pattern] = _glob_re(pattern)
    return compiled.match(rel) is not None


# A bare pattern matches the name or any dotted child, so `strawberry` covers
# `strawberry.type`; `*.x` also matches a bare `x`, so `*.tool` covers `@tool`.
def decorator_matches(dotted: str, pattern: str) -> bool:
    if fnmatchcase(dotted, pattern):
        return True
    if '*' not in pattern and '?' not in pattern:
        return dotted.startswith(pattern + '.')
    if pattern.startswith('*.'):
        return dotted == pattern[2:]
    return False


class Config:
    def __init__(self, data: dict[str, Any] | None = None, source: Path | None = None):
        data = data or {}
        self.source = source
        unknown = [key for key in data if key not in SECTIONS]
        if unknown:
            raise ConfigError(
                f'unknown section(s) {", ".join(sorted(unknown))} — '
                f'choose from {", ".join(sorted(SECTIONS))}'
            )

        # Keys only: the hook reads the values and takes `enabled = "no"` as off.
        _section(data, 'doc-gate')

        self.profile = _typed('', data, 'profile', str, 'default')
        if self.profile not in PROFILES:
            raise ConfigError(
                f'unknown profile {self.profile!r} — choose from {", ".join(sorted(PROFILES))}'
            )

        defaults = _section(data, 'defaults')
        self.soft = _typed('defaults', defaults, 'soft', int, DEFAULT_SOFT)
        self.hard = _typed('defaults', defaults, 'hard', int, DEFAULT_HARD)
        if self.soft > self.hard:
            raise ConfigError(
                f'[defaults]: soft cap {self.soft} is above the hard cap {self.hard}'
            )

        # User overrides are consulted before the shipped ones, so a repo can
        # re-cap docs/adr/ without having to restate the whole table.
        if not isinstance(data.get('overrides', []), list):
            raise ConfigError('[[overrides]] must be a list of tables')
        self.overrides = list(data.get('overrides', [])) + list(BUILTIN_OVERRIDES)
        for override in self.overrides:
            if not isinstance(override, dict):
                raise ConfigError(f'every [[overrides]] entry must be a table, got {override!r}')
            if 'pattern' not in override:
                raise ConfigError('every [[overrides]] entry needs a `pattern`')
            stray = [key for key in override if key not in OVERRIDE_KEYS]
            if stray:
                raise ConfigError(
                    f'{override["pattern"]}: unknown key(s) {", ".join(sorted(stray))} — '
                    f'choose from {", ".join(OVERRIDE_KEYS)}'
                )
            # And it has to be a string: every other message below interpolates
            # it, and `glob_match` takes its len(), so `pattern = 5` used to
            # reach the first matched file as a bare TypeError.
            if not isinstance(override['pattern'], str):
                raise ConfigError(
                    'every [[overrides]] `pattern` must be '
                    f'{_SHAPES[str]}, got {override["pattern"]!r}'
                )
            # Caps too: `caps_for` coerces these with a bare int() during the
            # analysis, so a non-numeric one used to surface as a raw ValueError
            # from the middle of a run rather than as a config error at load.
            for cap in ('soft', 'hard'):
                value = override.get(cap)
                if cap in override and not _whole_number(value):
                    raise ConfigError(
                        f'{override["pattern"]}: {cap} must be {_SHAPES[int]}, got {value!r}'
                    )
                if cap in override and value < 0:
                    raise ConfigError(
                        f'{override["pattern"]}: {cap} must not be negative, got {value!r}'
                    )
            if 'soft' in override and 'hard' in override and override['soft'] > override['hard']:
                raise ConfigError(
                    f'{override["pattern"]}: soft cap {override["soft"]} is above '
                    f'the hard cap {override["hard"]}'
                )
            # Suppression is read by identity, so any other value was ignored
            # in silence: a repo writing `structure_rules = "false"` or
            # `rules = "warn"` had turned off something that never moved.
            if 'structure_rules' in override and not isinstance(
                override['structure_rules'], bool
            ):
                raise ConfigError(
                    f'{override["pattern"]}: structure_rules must be '
                    f'{_SHAPES[bool]}, got {override["structure_rules"]!r}'
                )
            if 'status' in override:
                self._check_status_override(override)
            table = override.get('rules')
            if 'rules' in override and not isinstance(table, dict) and table != OFF:
                raise ConfigError(
                    f'{override["pattern"]}: rules must be a table of rule ids, '
                    f'or the string "{OFF}" to mute the subtree, got {table!r}'
                )
            if isinstance(table, dict):
                unknown = set(table) - set(RULE_DEFAULTS)
                if unknown:
                    raise ConfigError(
                        f'{override["pattern"]}: unknown rule(s): {", ".join(sorted(unknown))}'
                    )
                # Values too, not just keys: validating these lazily in rule()
                # meant a Config that load() had accepted could still raise
                # part-way through an analysis.
                for rule_id, severity in table.items():
                    _check_severity(rule_id, severity, override['pattern'])

        exclude = _section(data, 'exclude')
        self.exclude_paths = (
            _typed('exclude', exclude, 'paths', list, []) + list(BUILTIN_EXCLUDE)
        )
        self.always_exempt = _typed(
            'exclude', exclude, 'always_exempt', list, list(BUILTIN_ALWAYS_EXEMPT)
        )

        self.rules = self._resolve_rules(_section(data, 'rules'))
        self.advisory = False

        python = _section(data, 'python')
        self.python_enabled = _typed('python', python, 'enabled', bool, True)
        self.runtime_surfaced = _typed(
            'python', python, 'runtime_surfaced_decorators', list, []
        )
        self.module_docstring_cap = _typed('python', python, 'module_docstring_cap', int, 0)
        self.docstring_cap = _typed('python', python, 'docstring_cap', int, 0)
        self.cli_help_exempts_module = _typed(
            'python', python, 'cli_help_exempts_module', bool, True
        )

        comments = _section(data, 'comments')
        self.comments_enabled = _typed('comments', comments, 'enabled', bool, True)
        self.comment_prefixes = dict(DEFAULT_COMMENT_PREFIXES)
        self.comment_prefixes.update(_typed('comments', comments, 'prefixes', dict, {}))

        corpus = _section(data, 'corpus')
        self.package_roots = _typed('corpus', corpus, 'package_roots', list, [])
        self.doc_globs = _typed('corpus', corpus, 'doc_globs', list, ['*.md'])
        self.code_globs = _typed('corpus', corpus, 'code_globs', list, ['*.py'])

    # The walk skips a muted file before reading it, so `rules` and
    # `structure_rules` are answered by path alone and cannot wait for a status.
    # A status override carries caps only; anything else would hit every match.
    @staticmethod
    def _check_status_override(override: dict[str, Any]) -> None:
        where = override['pattern']
        status = override['status']
        if not isinstance(status, list) or not all(isinstance(s, str) for s in status):
            raise ConfigError(f'{where}: status must be {_SHAPES[list]}, got {status!r}')
        if not status:
            raise ConfigError(f'{where}: status must not be empty — it could never match')
        for key in ('rules', 'structure_rules'):
            if key in override:
                raise ConfigError(
                    f'{where}: a `status` override sets caps only — {key} is applied '
                    'by path, before the status is known'
                )
        if 'soft' not in override and 'hard' not in override:
            raise ConfigError(f'{where}: a `status` override with no soft or hard does nothing')

    def _resolve_rules(self, configured: dict[str, Any]) -> dict[str, Rule]:
        unknown = set(configured) - set(RULE_DEFAULTS)
        if unknown:
            raise ConfigError(f'unknown rule(s): {", ".join(sorted(unknown))}')
        out: dict[str, Rule] = {}
        profile = PROFILES[self.profile]
        for rule_id, entry in configured.items():
            if not isinstance(entry, dict):
                # `[rules]` + `docstring = "fail"` is an easy confusion with
                # `[rules.docstring]` + `severity = "fail"`, and used to
                # traceback rather than say so.
                raise ConfigError(
                    f'[rules.{rule_id}] must be a table — write '
                    f'[rules.{rule_id}] then severity = {entry!r}'
                )
        # Which severities the repo stated for itself, as opposed to inheriting
        # from a default or a profile. `tahrir scan` promotes the inherited ones
        # and leaves a stated one alone. See CONTEXT.md.
        self.stated_severities = {
            rule_id for rule_id, entry in configured.items() if 'severity' in entry
        }
        for rule_id, base in RULE_DEFAULTS.items():
            _check_opts(rule_id, configured.get(rule_id, {}))
            if rule_id == 'changelog-unreleased-tagged':
                _check_tag_templates(configured.get(rule_id, {}))
            # Deep, because a shallow merge hands every Rule the *same* list
            # object as RULE_DEFAULTS['todo-marker']['markers'] — one process
            # global that any consumer could mutate for everyone.
            merged = copy.deepcopy(
                {**base, **profile.get(rule_id, {}), **configured.get(rule_id, {})}
            )
            severity = _check_severity(rule_id, merged.pop('severity'))
            merged.pop('help', None)
            out[rule_id] = Rule(rule_id, severity, merged)
        return out

    def rule(self, rule_id: str, rel: str | None = None) -> Rule:
        resolved = self.rules[rule_id]
        overridden = False
        if rel is not None:
            for override in self._matching(rel):
                table = override.get('rules')
                if isinstance(table, dict) and rule_id in table:
                    resolved = resolved._replace(severity=table[rule_id])
                    overridden = True
                    break
        if not self.advisory:
            return resolved
        # Advisory applies last, so nothing can smuggle a blocking severity into
        # `tahrir scan`. An `off` the repo stated — globally or for a glob — is a
        # decision it already made, though, so a scan does not repeat it back.

        # A rule that is merely off by default, or off through a profile, has
        # had nothing said about it: showing those is what a scan is for.
        if resolved.severity == OFF and (overridden or rule_id in self.stated_severities):
            return resolved
        return resolved._replace(severity=WARN)

    # Advisory view: nothing blocks, and a rule the repo has not spoken about
    # reports, so it can see what it is not enforcing. Path exclusions and a
    # stated `off` still apply.
    def for_scan(self) -> Config:
        clone = copy.copy(self)
        clone.advisory = True
        return clone

    # Status overrides are not here: they cannot be judged from a path, and every
    # caller of this list asks about a path.
    def _matching(self, rel: str) -> list[dict[str, Any]]:
        return [
            o for o in self.overrides
            if 'status' not in o and glob_match(rel, o['pattern'])
        ]

    def caps_for(self, rel: str, status: str | None = None) -> tuple[int, int]:
        # First match wins, per cap (a soft-only override keeps the next match's
        # hard cap, not [defaults]'s); suppression applies if any match sets it.
        # A status override outranks a plain one: the narrower statement.
        matching = self._status_matching(rel, status) + self._matching(rel)

        def first(cap: str, default: int) -> int:
            return int(next((o[cap] for o in matching if cap in o), default))

        return first('soft', self.soft), first('hard', self.hard)

    # `fnmatchcase`, not `glob_match`: a status is free text, and `*` has to cross
    # a `/` in `Superseded by docs/adr/0004.md`.
    def _status_matching(self, rel: str, status: str | None) -> list[dict[str, Any]]:
        if status is None:
            return []
        return [
            o for o in self.overrides
            if 'status' in o
            and glob_match(rel, o['pattern'])
            and any(fnmatchcase(status, pattern) for pattern in o['status'])
        ]

    def structure_enabled(self, rel: str) -> bool:
        # Caps are first-match-wins, but suppression is not: docs/adr/README.md
        # takes the README cap and still keeps the ADR structure exemption.
        return not any(o.get('structure_rules') is False for o in self._matching(rel))

    def rules_muted(self, rel: str) -> bool:
        return any(o.get('rules') == OFF for o in self._matching(rel))

    def is_excluded(self, rel: str) -> bool:
        return any(glob_match(rel, pattern) for pattern in self.exclude_paths)

    # fnmatchcase, not fnmatch: fnmatch folds case through os.path.normcase, which
    # folds on Windows, so `NOTES.MD` was a doc there and a source file in Linux
    # CI. Git paths are case-sensitive; the answer must not depend on the host.
    def _name_matches(self, rel: str, patterns: list[str]) -> bool:
        name = rel.rsplit('/', 1)[-1]
        return any(
            glob_match(rel, pattern) or fnmatchcase(name, pattern)
            for pattern in patterns
        )

    # No `is_doc`/`is_code` beside this. `doc_globs` and `code_globs` are git
    # pathspecs, asked by handing them to git: a second matcher here read
    # `docs/` as nothing and silently un-measured a whole directory.

    # `always_exempt` is matched in Python and nowhere else, so it keeps the
    # narrower reading a repo expects from a plain glob.
    def is_pattern_exempt(self, rel: str) -> bool:
        return self._name_matches(rel, self.always_exempt)

    def comment_prefix(self, suffix: str) -> str | None:
        return self.comment_prefixes.get(suffix)


def find_config(root: Path) -> Path | None:
    candidate = root / CONFIG_NAME
    return candidate if candidate.is_file() else None


def load(root: Path, explicit: Path | None = None, profile: str | None = None) -> Config:
    path = explicit or find_config(root)
    data: dict[str, Any] = {}
    if path is not None:
        if not path.is_file():
            raise ConfigError(f'no config at {path}')
        try:
            data = tomllib.loads(path.read_text(encoding='utf-8'))
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f'{path}: {exc}') from exc
        except UnicodeDecodeError as exc:
            raise ConfigError(f'{path}: not valid UTF-8 — {exc}') from exc
    if profile:
        data = {**data, 'profile': profile}
    return Config(data, source=path)
