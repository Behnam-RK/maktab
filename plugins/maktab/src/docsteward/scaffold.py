from __future__ import annotations

import json
import os
from itertools import takewhile
import sys
import tomllib
from pathlib import Path, PurePosixPath

from . import __version__
from .config import (
    BUILTIN_OVERRIDES, CONFIG_NAME, DEFAULT_HARD, DEFAULT_SOFT, PROFILES, RULE_DEFAULTS,
    Config, ConfigError, load as load_config,
)
from .corpus import GitUnavailable, git


TEMPLATES = Path(__file__).resolve().parent / 'templates'

GUIDE = 'documentation-guide.md'
GUIDE_TARGET = 'docs/workflows/documentation-guide.md'
# template file -> its name inside the repo's ADR directory
ADR_FILES = {'adr-template.md': 'template.md', 'adr-README.md': 'README.md'}

ADR_RULE = 'adr-number-collision'
# Where the shipped config expects the decision log, read off the rule that
# polices it so the two cannot disagree.
DEFAULT_ADR_DIR = str(PurePosixPath(RULE_DEFAULTS[ADR_RULE]['index']).parent)
ADR_NAME_GLOB = PurePosixPath(RULE_DEFAULTS[ADR_RULE]['adr_glob']).name

# The ADR index gains a row the moment the repo records a decision, which is the
# scaffold being used as intended. Comparing it byte-for-byte would then report
# drift forever, so it is seeded and never synced.
SEEDED_ONLY = ('adr-README.md',)

LANG_GLOBS = {
    'python': ['*.py'],
    'typescript': ['*.ts', '*.tsx'],
    'javascript': ['*.js', '*.jsx', '*.mjs'],
    'go': ['*.go'],
    'rust': ['*.rs'],
    'shell': ['*.sh'],
}

MARKERS = {
    'pyproject.toml': 'python',
    'setup.py': 'python',
    'tsconfig.json': 'typescript',
    'package.json': 'javascript',
    'go.mod': 'go',
    'Cargo.toml': 'rust',
}

# Found from the files themselves: shell has no manifest, and Python has one
# only sometimes — a manifest-less Python repo reached the default below, which
# one stray `*.sh` was then enough to suppress.
GLOB_MARKERS = {'python': '*.py', 'shell': '*.sh'}

REPO = 'https://github.com/Behnam-RK/maktab'
GIT_URL = 'git+https://github.com/Behnam-RK/maktab'

# A tag names the plugin it releases: `<plugin>--vX.Y.Z`. tahrir ships inside the
# maktab plugin, so `tahrir init` emits maktab pins for pre-commit and uvx.
PLUGIN = 'maktab'


def tag(version: str = __version__) -> str:
    return f'{PLUGIN}--v{version}'


# Tracked files, because that is what the gate will measure: it reaches
# `src/pkg/mod.py` at any depth, and it does not see `node_modules` or a
# virtualenv, which a recursive `rglob` would walk into and be fooled by.
def _has_tracked(root: Path, pattern: str) -> bool:
    try:
        listing = git(root, 'ls-files', '-z', '--', pattern)
    except GitUnavailable:
        # `tahrir init` is the one command that must work without git: scaffolding
        # a repository is a reasonable thing to do before creating one.
        listing = None
    if listing is not None:
        return any(listing.split('\0'))
    # No index to ask, so probe the root and one level down rather than walking
    # a whole tree that may contain `node_modules` or a virtualenv.
    return any(next(root.glob(p), None) for p in (pattern, f'*/{pattern}'))


def detect_languages(root: Path) -> list[str]:
    found: list[str] = []
    for marker, lang in MARKERS.items():
        if (root / marker).exists() and lang not in found:
            found.append(lang)
    for lang, pattern in GLOB_MARKERS.items():
        if lang not in found and _has_tracked(root, pattern):
            found.append(lang)
    # A TypeScript repo always has a package.json too; the narrower answer wins.
    if 'typescript' in found and 'javascript' in found:
        found.remove('javascript')
    return found or ['python']


def _code_globs(root: Path, lang: str | None) -> list[str]:
    langs = [name.strip() for name in lang.split(',') if name.strip()] if lang else []
    langs = langs or detect_languages(root)
    out: list[str] = []
    for name in langs:
        if name not in LANG_GLOBS:
            raise ValueError(
                f'unknown --lang {name!r} — choose from {", ".join(sorted(LANG_GLOBS))}'
            )
        out += [g for g in LANG_GLOBS[name] if g not in out]
    return out


def _adr_override(adr_dir: str) -> dict:
    # The shipped `docs/adr/**` caps, moved: an ADR elsewhere is still a record
    # of a past decision, and trimming one to fit a budget rewrites history.
    shipped = next(o for o in BUILTIN_OVERRIDES if o['pattern'] == f'{DEFAULT_ADR_DIR}/**')
    return {**shipped, 'pattern': f'{adr_dir}/**'}


def _toml(value) -> str:
    # JSON's string, number and array syntax is valid TOML; its objects are not.
    if isinstance(value, dict):
        return '{ ' + ', '.join(f'{_toml(k)} = {_toml(v)}' for k, v in value.items()) + ' }'
    return json.dumps(value, ensure_ascii=False)


# Named, and the caps interpolated, so the generated file cannot restate a
# threshold or a rule id that the engine has since changed.
EXAMPLE_RULE = 'docstring'


def _config_text(
    profile: str,
    globs: list[str],
    exclude: list[str] | None = None,
    doc_gate: bool | None = None,
    routing_doc: str | None = None,
    adr_dir: str = DEFAULT_ADR_DIR,
    adr_index: str | None = None,
) -> str:
    # What the caller chose is written live; the rest stays a commented example.
    parts = [
        f'# Written by `tahrir init` v{__version__}. Every key is optional.\n'
        f'# `tahrir --explain <rule>` prints the reasoning and knobs for one rule.\n'
        f'profile = {_toml(profile)}\n'
        f'\n[corpus]\ncode_globs = [{", ".join(_toml(g) for g in globs)}]\n'
        f'\n# [defaults]\n# soft = {DEFAULT_SOFT}\n# hard = {DEFAULT_HARD}\n'
        f'\n# First match wins; the shipped README and {DEFAULT_ADR_DIR}/ overrides are consulted last.\n'
    ]
    if adr_dir != DEFAULT_ADR_DIR:
        override = _adr_override(adr_dir)
        parts.append(
            '[[overrides]]\n'
            + ''.join(f'{key} = {_toml(value)}\n' for key, value in override.items())
        )
    else:
        parts.append('# [[overrides]]\n# pattern = "docs/legacy/**"\n# rules = "off"\n')

    if exclude:
        parts.append(f'\n[exclude]\npaths = [{", ".join(_toml(p) for p in exclude)}]\n')
    else:
        parts.append('\n# [exclude]\n# paths = ["vendor/**"]\n')

    if adr_dir != DEFAULT_ADR_DIR or adr_index is not None:
        index = f'{adr_dir}/README.md' if adr_index is None else adr_index
        parts.append(
            f'\n[rules.{ADR_RULE}]\n'
            f'adr_glob = {_toml(f"{adr_dir}/{ADR_NAME_GLOB}")}\n'
            f'index = {_toml(index)}\n'
        )
    parts.append(f'\n# [rules.{EXAMPLE_RULE}]\n# severity = "fail"\n')
    parts.append(
        '\n# [python]\n'
        '# runtime_surfaced_decorators = ["strawberry", "strawberry_django", "*.tool"]\n'
    )

    if doc_gate is not None or routing_doc:
        gate = '\n[doc-gate]\n'
        if doc_gate is not None:
            gate += f'enabled = {"true" if doc_gate else "false"}\n'
        if routing_doc:
            gate += f'routing_doc = {_toml(routing_doc)}\n'
        parts.append(gate)
    return ''.join(parts)


# What the guide's link to the decision log can point at: its index, the bare
# directory when it has none, or nothing when there is no log yet.
INDEX, DIRECTORY = 'index', 'directory'


def _log_link(root: Path, adr_dir: str, indexed: bool) -> str | None:
    if indexed:
        return INDEX
    return DIRECTORY if (root / adr_dir).is_dir() else None


def _template(name: str, adr_dir: str, link_to: str | None = INDEX) -> str:
    text = (TEMPLATES / name).read_text(encoding='utf-8')
    if name != GUIDE or (adr_dir == DEFAULT_ADR_DIR and link_to == INDEX):
        return text
    # Path and link follow the chosen dir, never to a missing README or dir.
    # Path first: replaced after the link, `docs/adrs` became `docs/adrss`.
    text = text.replace(DEFAULT_ADR_DIR, adr_dir)
    here = PurePosixPath(GUIDE_TARGET).parent
    shipped = f'[`{adr_dir}/`]({os.path.relpath(f"{DEFAULT_ADR_DIR}/README.md", here)})'
    if link_to == INDEX:
        linked = f'[`{adr_dir}/`]({os.path.relpath(f"{adr_dir}/README.md", here)})'
    elif link_to == DIRECTORY:
        linked = f'[`{adr_dir}/`]({os.path.relpath(adr_dir, here)}/)'
    else:
        linked = f'`{adr_dir}/`'
    return text.replace(shipped, linked)


def _targets(adr_dir: str, guide: bool = True, adr: bool = True) -> dict[str, str]:
    out = {GUIDE: GUIDE_TARGET} if guide else {}
    if adr:
        out.update({name: f'{adr_dir}/{landed}' for name, landed in ADR_FILES.items()})
    return out


GLOB_CHARS = '*?['


def _repo_adr(root: Path) -> tuple[str, bool]:
    # The drift check has no flags to say where the log went or whether it has
    # an index, but the config the same init wrote does; a broken or absent one
    # means the shipped place.
    try:
        opts = load_config(root).rule(ADR_RULE).opts
    except (ConfigError, OSError):
        return DEFAULT_ADR_DIR, True
    # The literal directory above the first wildcard: the rule also accepts a
    # recursive `docs/adr/**/[0-9]*.md`, whose parent is no path.
    parts = PurePosixPath(opts['adr_glob']).parent.parts
    fixed = str(PurePosixPath(*takewhile(lambda part: not set(part) & set(GLOB_CHARS), parts)))
    return (DEFAULT_ADR_DIR if fixed == '.' else fixed), opts['index'] != ''


def _write(
    path: Path, text: str, force: bool, written: list[str], skipped: list[str],
    note: str = '(exists; --force to overwrite)',
):
    if path.exists() and not force:
        skipped.append(f'{path}  {note}')
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')
    written.append(str(path))


def _drift(root: Path, adr_dir: str | None, guide: bool, adr: bool) -> int:
    kept_dir, indexed = _repo_adr(root)
    adr_dir = adr_dir or kept_dir
    link_to = _log_link(root, adr_dir, indexed)
    drifted = []
    missing = []
    for name, target in _targets(adr_dir, guide, adr).items():
        landed = root / target
        if not landed.exists():
            missing.append(target)
        elif name in SEEDED_ONLY:
            continue
        elif landed.read_text(encoding='utf-8') != _template(name, adr_dir, link_to):
            drifted.append(target)
    for target in missing:
        print(f'missing  {target}')
    for target in drifted:
        print(f'drift    {target}  differs from the copy shipped in v{__version__}')
    if not drifted and not missing:
        print(f'all templates match the copies shipped in v{__version__}')
        return 0
    return 1


def _relative_dir(value: str) -> str | None:
    path = PurePosixPath(value.strip().rstrip('/'))
    # The root itself is no log directory: `./**` and `./0001-*.md` match nothing.
    # A wildcard would be read back as a glob by `_repo_adr` and the rule alike.
    if (not value.strip() or path.is_absolute() or '..' in path.parts or str(path) == '.'
            or set(value) & set(GLOB_CHARS)):
        return None
    return str(path)


def _warn_kept_config(root: Path, chosen: str, force: bool):
    # A kept config keeps its own `adr_glob`: the flag then only moves the
    # templates, and the gate would police a directory that has none.
    if force or not (root / CONFIG_NAME).exists():
        return
    kept = _repo_adr(root)[0]
    if kept != chosen:
        print(
            f'tahrir init: --adr-dir {chosen!r} differs from the kept {CONFIG_NAME} '
            f'(its ADR log is {kept!r}); --force rewrites the config',
            file=sys.stderr,
        )


def init_repo(
    root: Path,
    profile: str = 'default',
    lang: str | None = None,
    force: bool = False,
    write_guide: bool = True,
    write_adr: bool = True,
    drift_check: bool = False,
    exclude: list[str] | None = None,
    doc_gate: bool | None = None,
    routing_doc: str | None = None,
    adr_dir: str | None = None,
) -> int:
    if not root.is_dir():
        print(f'tahrir init: --root {str(root)!r} is not a directory', file=sys.stderr)
        return 2
    # Not given: the decision log the repo's own config names, else the shipped one.
    chosen = None
    if adr_dir is not None:
        chosen = _relative_dir(adr_dir)
        if chosen is None:
            print(f'tahrir init: --adr-dir {adr_dir!r} must be a path inside the repo, '
                  f'without wildcards', file=sys.stderr)
            return 2
    if drift_check:
        if chosen is not None:
            _warn_kept_config(root, chosen, force)
        return _drift(root, chosen, write_guide, write_adr)
    if profile not in PROFILES:
        print(
            f'tahrir init: unknown profile {profile!r} — choose from '
            f'{", ".join(sorted(PROFILES))}',
            file=sys.stderr,
        )
        return 2
    if chosen is None:
        chosen = _repo_adr(root)[0] if (root / CONFIG_NAME).exists() else DEFAULT_ADR_DIR
    else:
        _warn_kept_config(root, chosen, force)

    # A decision log the repo already keeps elsewhere may have no index; pointing
    # the rule at a missing README would report every ADR as unindexed.
    adr_index = None
    if not write_adr and not (root / chosen / 'README.md').exists():
        adr_index = ''
    try:
        globs = _code_globs(root, lang)
    except ValueError as exc:
        print(f'tahrir init: {exc}', file=sys.stderr)
        return 2
    text = _config_text(profile, globs, exclude, doc_gate, routing_doc, chosen, adr_index)
    # Checked against the engine before anything lands: a flag value the
    # validator rejects would otherwise leave a config every later run refuses.
    try:
        Config(tomllib.loads(text))
    except (ConfigError, tomllib.TOMLDecodeError) as exc:
        print(f'tahrir init: the generated config is invalid — {exc}', file=sys.stderr)
        return 2

    # Judged before anything lands: the ADR templates written below are the
    # index this link points at.
    link_to = INDEX if write_adr else _log_link(root, chosen, adr_index != '')
    written: list[str] = []
    skipped: list[str] = []
    try:
        _write(root / CONFIG_NAME, text, force, written, skipped)
        for name, target in _targets(chosen, write_guide, write_adr).items():
            # `--force` refreshes the templates, but a seeded file is the repo's
            # own content after the first ADR lands; overwriting it deleted the
            # index that `SEEDED_ONLY` exists to protect from the drift check.
            seeded = name in SEEDED_ONLY
            note = (
                '(seeded once; never overwritten)' if seeded
                else '(exists; --force to overwrite)'
            )
            _write(root / target, _template(name, chosen, link_to),
                   force and not seeded, written, skipped, note)
    except OSError as exc:
        print(f'tahrir init: cannot write {exc.filename or root}: {exc.strerror}',
              file=sys.stderr)
        return 2

    for path in written:
        print(f'wrote    {path}')
    for path in skipped:
        print(f'kept     {path}')

    print(f'\nadd to .pre-commit-config.yaml (prefer the tag\'s sha: '
          f'rev: <sha>  # frozen: {tag()}):\n'
          f'  - repo: {REPO}\n'
          f'    rev: {tag()}\n'
          f'    hooks: [{{id: tahrir}}]\n')
    print(f'add to CI:\n'
          f"  uvx --from 'tahrir[exact] @ {GIT_URL}@{tag()}' "
          f'tahrir check --require-exact')
    return 0
