"""The path rules in lenses.md are the spec; these golden paths pin what each one picks."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

LENSES = Path(__file__).resolve().parents[1] / 'skills' / 'momayezi' / 'references' / 'lenses.md'


def rules() -> dict[str, str]:
    text = LENSES.read_text(encoding='utf-8')
    block = text.split('## Picking', 1)[1].split('```', 2)[1]
    return dict(line.split(None, 1) for line in block.strip().splitlines())


RULES = rules()
GOLDEN = {
    'prose': (['README.md', 'docs/a.mdx', 'notes.txt', 'skills/x/SKILL.md'],
              ['a.py', 'README.md.j2', 'docs/conf.py']),
    'security': (['src/auth/login.py', 'app/secrets.ts', 'db/migrations/0001.sql', 'scripts/sync.sh',
                  '.github/workflows/ci.yaml', 'infra/main.tf', 'Dockerfile', 'compose.yml',
                  'lib/parser.rs', 'run_exec.go', 'token_store.py', 'crypto/aes.c'],
                 ['src/stats.py', 'README.md', 'docs/guide.md', 'web/button.tsx', 'tests/test_math.py']),
    'test': (['tests/test_x.py', 'src/__tests__/a.ts', 'spec/models/user_spec.rb', 'pkg/foo_test.go',
              'web/a.test.tsx', 'web/b.spec.js', 'test_top.py', 'conftest.py'],
             ['src/testing.py', 'src/contest.py', 'latest/a.py', 'docs/test-plan.md']),
    'source': (['a.py', 'b.tsx', 'c.go', 'd.rs', 'e.sh', 'f.kt', 'g.exs'],
               ['README.md', 'config.toml', 'image.png', 'Makefile']),
    'docs': (['README.md', 'docs/x.py', 'src/cli.py', 'bin/tool', 'app/config.py', 'pyproject.toml',
              '.github/workflows/ci.yaml', 'src/api/routes.py', 'pkg/__init__.py', 'web/index.ts', 'package.json'],
             ['src/stats.py', 'web/button.tsx', 'notes.txt']),
}


def test_every_rule_has_golden_cases():
    assert set(RULES) == set(GOLDEN)


@pytest.mark.parametrize('name', sorted(GOLDEN))
def test_rule_matches_its_golden_paths(name):
    pattern = re.compile(RULES[name], re.IGNORECASE)
    hits, misses = GOLDEN[name]
    assert [p for p in hits if not pattern.search(p)] == []
    assert [p for p in misses if pattern.search(p)] == []


@pytest.mark.parametrize('name', sorted(GOLDEN))
def test_patterns_stay_in_the_syntax_rg_and_python_share(name):
    assert not re.search(r'\(\?[=!<]|\\[1-9]|\\[dswb]', RULES[name])


@pytest.mark.skipif(shutil.which('rg') is None, reason='rg not installed')
@pytest.mark.parametrize('name', sorted(GOLDEN))
def test_rg_agrees_with_python(name):
    hits, misses = GOLDEN[name]
    done = subprocess.run(['rg', '-i', RULES[name]], input='\n'.join(hits + misses) + '\n',
                          capture_output=True, text=True, check=False)
    assert done.stdout.splitlines() == hits
