import json
import os
import subprocess
from pathlib import Path

import pytest


HOOK = Path(__file__).resolve().parents[1] / 'scripts' / 'doc-gate.sh'
DIRECTIVE = 'implement the export endpoint'


def _run(root, prompt=DIRECTIVE, option=None, payload=None, cwd=None):
    env = {k: v for k, v in os.environ.items() if k != 'CLAUDE_PLUGIN_OPTION_TAHRIR_PROACTIVITY'}
    env['CLAUDE_PROJECT_DIR'] = str(root)
    if option is not None:
        env['CLAUDE_PLUGIN_OPTION_TAHRIR_PROACTIVITY'] = option
    data = payload if payload is not None else json.dumps({'prompt': prompt})
    done = subprocess.run(['bash', str(HOOK)], input=data, env=env,
                          capture_output=True, text=True, timeout=30, cwd=cwd)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture
def adopted(tmp_path):
    (tmp_path / 'AGENTS.md').write_text('# conventions\n', encoding='utf-8')
    return tmp_path


def test_silent_in_a_repo_without_conventions(tmp_path):
    assert _run(tmp_path) == ''


def test_names_the_routing_doc_when_it_exists(adopted):
    assert 'read AGENTS.md → ' in _run(adopted)


def test_config_alone_never_names_a_missing_routing_doc(tmp_path):
    (tmp_path / '.docs.toml').write_text('profile = "default"\n', encoding='utf-8')
    out = _run(tmp_path)
    assert out.startswith('[doc-gate] Before non-trivial code: read this layer')
    assert 'AGENTS.md' not in out


def test_claude_md_counts_when_unconfigured(tmp_path):
    (tmp_path / 'CLAUDE.md').write_text('x\n', encoding='utf-8')
    assert 'read CLAUDE.md → ' in _run(tmp_path)


def test_agents_md_is_named_when_both_exist(adopted):
    (adopted / 'CLAUDE.md').write_text('x\n', encoding='utf-8')
    assert 'read AGENTS.md → ' in _run(adopted)


def test_configured_routing_doc_missing_falls_back_to_generic(tmp_path):
    (tmp_path / 'AGENTS.md').write_text('x\n', encoding='utf-8')
    (tmp_path / '.docs.toml').write_text('[doc-gate]\nrouting_doc = "docs/GUIDE.md"\n',
                                         encoding='utf-8')
    out = _run(tmp_path)
    assert 'read this layer' in out and 'GUIDE' not in out


def test_custom_routing_doc(tmp_path):
    (tmp_path / 'CLAUDE.md').write_text('x\n', encoding='utf-8')
    (tmp_path / '.docs.toml').write_text('[doc-gate]\nrouting_doc = "CLAUDE.md"\n',
                                         encoding='utf-8')
    assert 'read CLAUDE.md → ' in _run(tmp_path)


@pytest.mark.parametrize('value', ['off', 'OFF', ' Off '])
def test_proactivity_off_silences(adopted, value):
    assert _run(adopted, option=value) == ''


@pytest.mark.parametrize('value', ['eager', 'suggest', 'on-request', ''])
def test_proactivity_other_or_blank_fires(adopted, value):
    assert _run(adopted, option=value) != ''


def test_repo_switch_off_silences(adopted):
    (adopted / '.docs.toml').write_text('[doc-gate]\nenabled = false\n', encoding='utf-8')
    assert _run(adopted) == ''


def test_both_switches_must_be_on(adopted):
    (adopted / '.docs.toml').write_text('[doc-gate]\nenabled = true\n', encoding='utf-8')
    assert _run(adopted, option='off') == ''
    assert _run(adopted, option='suggest') != ''


@pytest.mark.parametrize('prompt', [
    'how do I implement X?', 'should I refactor this?', 'explain the gate',
])
def test_questions_do_not_trip_it(adopted, prompt):
    assert _run(adopted, prompt) == ''


@pytest.mark.parametrize('prompt', [
    'implement X', 'please refactor the loader', "let's add a new field",
    'context first\nbuild the importer',
])
def test_directives_trip_it(adopted, prompt):
    assert _run(adopted, prompt) != ''


def test_custom_trigger(adopted):
    (adopted / '.docs.toml').write_text('[doc-gate]\ntrigger = "^ship "\n', encoding='utf-8')
    assert _run(adopted, 'ship it now') != ''
    assert _run(adopted, 'implement X') == ''


def test_broken_config_falls_back_to_defaults(adopted):
    (adopted / '.docs.toml').write_text('this is = = not toml\n', encoding='utf-8')
    assert _run(adopted) != ''


def test_non_table_section_falls_back(adopted):
    (adopted / '.docs.toml').write_text('doc-gate = "yes"\n', encoding='utf-8')
    assert _run(adopted) != ''


def test_payload_past_the_pipe_buffer(adopted):
    assert _run(adopted, DIRECTIVE + '\n' + 'x' * 300_000) != ''


@pytest.mark.parametrize('payload', ['', 'not json', '[]'])
def test_bad_payload_is_silent(adopted, payload):
    assert _run(adopted, payload=payload) == ''


@pytest.mark.parametrize('prompt', ["let's implement it", 'let\u2019s implement it'])
def test_default_trigger_takes_either_apostrophe(adopted, prompt):
    assert 'read AGENTS.md' in _run(adopted, prompt)


def test_a_trigger_starting_with_a_dash_is_a_pattern_not_an_option(adopted):
    (adopted / '.docs.toml').write_text('[doc-gate]\ntrigger = "-ship"\n', encoding='utf-8')
    assert 'read AGENTS.md' in _run(adopted, '-ship it')


def test_repo_files_cannot_shadow_the_hook_interpreter(adopted):
    # The hook runs with the repo as cwd; `python -c` would import its json.py.
    (adopted / 'json.py').write_text('raise SystemExit(7)\n', encoding='utf-8')
    (adopted / 'tomllib.py').write_text('raise SystemExit(7)\n', encoding='utf-8')
    assert 'read AGENTS.md' in _run(adopted, cwd=adopted)
