import subprocess
import tomllib
from pathlib import Path

import pytest

from docsteward import config, scaffold
from docsteward.cli import main


def _init(root, *flags):
    return main(['init', '--root', str(root), *flags])


def _toml(root):
    return tomllib.loads((root / '.docs.toml').read_text(encoding='utf-8'))


@pytest.fixture
def repo(tmp_path):
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    return tmp_path


def test_default_init_writes_config_guide_and_adr(repo):
    assert _init(repo) == 0
    assert (repo / 'docs/workflows/documentation-guide.md').is_file()
    assert (repo / 'docs/adr/template.md').is_file()
    assert (repo / 'docs/adr/README.md').is_file()
    data = _toml(repo)
    assert data['profile'] == 'default'
    # Nothing chosen, so nothing optional is live.
    assert 'exclude' not in data and 'doc-gate' not in data and 'overrides' not in data
    config.load(repo)


def test_every_flag_lands_and_loads(repo):
    assert _init(
        repo, '--profile', 'strict', '--lang', 'python,shell',
        '--exclude', 'vendor/**', '--exclude', 'gen/**',
        '--no-doc-gate', '--routing-doc', 'CLAUDE.md', '--adr-dir', 'decisions/',
    ) == 0
    data = _toml(repo)
    assert data['profile'] == 'strict'
    assert data['corpus']['code_globs'] == ['*.py', '*.sh']
    assert data['exclude']['paths'] == ['vendor/**', 'gen/**']
    assert data['doc-gate'] == {'enabled': False, 'routing_doc': 'CLAUDE.md'}
    assert data['rules']['adr-number-collision'] == {
        'adr_glob': 'decisions/[0-9][0-9][0-9][0-9]-*.md',
        'index': 'decisions/README.md',
    }
    assert data['overrides'] == [
        {'pattern': 'decisions/**', 'soft': 1200, 'hard': 2000, 'structure_rules': False,
         'rules': {'stale-file-ref': 'off'}}
    ]
    loaded = config.load(repo)
    assert loaded.caps_for('decisions/0001-x.md') == (1200, 2000)
    assert (repo / 'decisions/README.md').is_file()
    assert not (repo / 'docs/adr').exists()


def test_doc_gate_on_writes_enabled_true(repo):
    assert _init(repo, '--doc-gate') == 0
    assert _toml(repo)['doc-gate'] == {'enabled': True}


def test_custom_adr_dir_rewrites_guide_paths_and_link(repo):
    assert _init(repo, '--adr-dir', 'decisions') == 0
    guide = (repo / 'docs/workflows/documentation-guide.md').read_text(encoding='utf-8')
    assert 'docs/adr' not in guide
    assert '](../../decisions/README.md)' in guide


def test_drift_check_follows_custom_adr_dir(repo, capsys):
    _init(repo, '--adr-dir', 'decisions')
    capsys.readouterr()
    assert _init(repo, '--check') == 0
    assert 'all templates match' in capsys.readouterr().out


def test_drift_reports_edited_template_and_missing(repo, capsys):
    _init(repo)
    (repo / 'docs/adr/template.md').write_text('mine\n', encoding='utf-8')
    (repo / 'docs/workflows/documentation-guide.md').unlink()
    capsys.readouterr()
    assert _init(repo, '--check') == 1
    out = capsys.readouterr().out
    assert 'drift    docs/adr/template.md' in out
    assert 'missing  docs/workflows/documentation-guide.md' in out


def test_drift_ignores_seeded_index(repo):
    _init(repo)
    (repo / 'docs/adr/README.md').write_text('| ADR-0001 | x |\n', encoding='utf-8')
    assert _init(repo, '--check') == 0


def test_force_never_overwrites_seeded_index(repo):
    _init(repo)
    index = repo / 'docs/adr/README.md'
    index.write_text('ours\n', encoding='utf-8')
    (repo / 'docs/adr/template.md').write_text('stale\n', encoding='utf-8')
    assert _init(repo, '--force') == 0
    assert index.read_text(encoding='utf-8') == 'ours\n'
    assert (repo / 'docs/adr/template.md').read_text(encoding='utf-8') != 'stale\n'


def test_existing_config_is_kept_without_force(repo, capsys):
    (repo / '.docs.toml').write_text('profile = "strict"\n', encoding='utf-8')
    assert _init(repo) == 0
    assert (repo / '.docs.toml').read_text(encoding='utf-8') == 'profile = "strict"\n'
    assert 'kept' in capsys.readouterr().out


def test_no_adr_reusing_a_log_without_index_turns_index_off(repo):
    (repo / 'adr').mkdir()
    (repo / 'adr/0001-x.md').write_text('# x\n', encoding='utf-8')
    assert _init(repo, '--no-adr', '--adr-dir', 'adr') == 0
    assert _toml(repo)['rules']['adr-number-collision']['index'] == ''
    assert not (repo / 'adr/template.md').exists()
    assert (repo / 'docs/workflows/documentation-guide.md').is_file()


def test_no_adr_reusing_a_log_with_index_keeps_it(repo):
    (repo / 'adr').mkdir()
    (repo / 'adr/README.md').write_text('# index\n', encoding='utf-8')
    assert _init(repo, '--no-adr', '--adr-dir', 'adr') == 0
    assert _toml(repo)['rules']['adr-number-collision']['index'] == 'adr/README.md'


def test_no_docs_writes_only_config(repo):
    assert _init(repo, '--no-docs') == 0
    assert sorted(p.name for p in repo.iterdir() if p.name != '.git') == ['.docs.toml']


@pytest.mark.parametrize('bad', ['../elsewhere', '/abs', '', '.', './'])
def test_adr_dir_outside_repo_is_refused(repo, bad):
    assert _init(repo, '--adr-dir', bad) == 2
    assert not (repo / '.docs.toml').exists()


def test_unknown_profile_writes_nothing(repo):
    assert _init(repo, '--profile', 'nope') == 2
    assert not (repo / '.docs.toml').exists()


def test_config_the_engine_rejects_writes_nothing(repo, monkeypatch):
    monkeypatch.setattr(scaffold, '_config_text', lambda *a: '[nonsense]\n')
    assert _init(repo) == 2
    assert not (repo / '.docs.toml').exists()
    assert not (repo / 'docs').exists()


def test_unknown_lang_is_refused_with_exit_2(repo, capsys):
    assert _init(repo, '--lang', 'cobol') == 2
    assert 'unknown --lang' in capsys.readouterr().err
    assert not (repo / '.docs.toml').exists()


def test_missing_root_is_a_clean_error(tmp_path, capsys):
    gone = tmp_path / 'zzz'
    assert _init(gone) == 2
    assert 'not a directory' in capsys.readouterr().err
    assert _init(gone, '--check') == 2
    assert not gone.exists()


def test_unwritable_target_is_a_clean_error(repo, capsys):
    (repo / 'docs').write_text('a file where the dir goes\n', encoding='utf-8')
    assert _init(repo) == 2
    assert 'cannot write' in capsys.readouterr().err


@pytest.mark.parametrize('bad', ['dir[1]', 'a*b', 'what?'])
def test_adr_dir_with_glob_characters_is_refused(repo, bad):
    assert _init(repo, '--adr-dir', bad) == 2
    assert _init(repo, '--adr-dir', bad, '--check') == 2
    assert not (repo / '.docs.toml').exists()


def test_plain_init_follows_the_kept_configs_adr_dir(repo):
    _init(repo, '--adr-dir', 'docs/decisions')
    assert _init(repo) == 0
    assert not (repo / 'docs/adr').exists()
    assert _init(repo, '--check') == 0


def test_adr_dir_against_a_kept_config_warns(repo, capsys):
    _init(repo, '--adr-dir', 'docs/decisions')
    capsys.readouterr()
    assert _init(repo, '--adr-dir', 'other') == 0
    err = capsys.readouterr().err
    assert "'other'" in err and "'docs/decisions'" in err
    assert _init(repo, '--adr-dir', 'docs/decisions') == 0
    assert capsys.readouterr().err == ''


def test_check_honours_the_flags_init_ran_with(repo, capsys):
    assert _init(repo, '--no-docs') == 0
    capsys.readouterr()
    assert _init(repo, '--check') == 1
    assert 'missing' in capsys.readouterr().out
    assert _init(repo, '--check', '--no-docs') == 0
    assert 'all templates match' in capsys.readouterr().out


def test_check_with_no_adr_demands_only_the_guide(repo, capsys):
    (repo / 'adr').mkdir()
    (repo / 'adr/0001-x.md').write_text('# x\n', encoding='utf-8')
    _init(repo, '--no-adr', '--adr-dir', 'adr')
    capsys.readouterr()
    assert _init(repo, '--check', '--no-adr') == 0
    (repo / 'docs/workflows/documentation-guide.md').unlink()
    assert _init(repo, '--check', '--no-adr') == 1
    assert 'missing  docs/workflows/documentation-guide.md' in capsys.readouterr().out


def test_detect_languages(repo):
    (repo / 'go.mod').write_text('module x\n', encoding='utf-8')
    (repo / 'run.sh').write_text('echo\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(repo), 'add', '-A'], check=True)
    assert scaffold.detect_languages(repo) == ['go', 'shell']


def test_detect_languages_defaults_to_python(tmp_path):
    assert scaffold.detect_languages(tmp_path) == ['python']


def test_pin_output_names_the_release_tag(repo, capsys):
    _init(repo)
    out = capsys.readouterr().out
    assert f'rev: {scaffold.tag()}' in out
    assert f'# frozen: {scaffold.tag()}' in out


def test_guide_links_an_unindexed_reused_log_as_a_directory(repo, capsys):
    # Found by a /tahrir setup dry run: the guide linked a README the reused
    # log never had, so tahrir's own scaffold failed its stale-file-ref rule.
    (repo / 'docs/decisions').mkdir(parents=True)
    (repo / 'docs/decisions/0001-x.md').write_text('# x\n', encoding='utf-8')
    assert _init(repo, '--no-adr', '--adr-dir', 'docs/decisions') == 0
    guide = (repo / 'docs/workflows/documentation-guide.md').read_text(encoding='utf-8')
    assert '](../decisions/)' in guide and 'decisions/README.md' not in guide
    subprocess.run(['git', '-C', str(repo), 'add', '-A'], check=True)
    capsys.readouterr()
    assert main(['scan', '--root', str(repo), '--json']) == 0
    assert 'stale-file-ref' not in capsys.readouterr().out
    assert _init(repo, '--check') == 1
    out = capsys.readouterr().out
    assert 'drift' not in out and 'missing  docs/decisions/template.md' in out


def test_no_adr_without_any_log_writes_no_link(repo, capsys):
    assert _init(repo, '--no-adr') == 0
    guide = (repo / 'docs/workflows/documentation-guide.md').read_text(encoding='utf-8')
    assert '](../adr/' not in guide and '`docs/adr/`' in guide
    subprocess.run(['git', '-C', str(repo), 'add', '-A'], check=True)
    capsys.readouterr()
    assert main(['scan', '--root', str(repo), '--json']) == 0
    assert 'stale-file-ref' not in capsys.readouterr().out
    _init(repo, '--check')
    assert 'drift' not in capsys.readouterr().out


def test_adr_dir_sharing_the_default_prefix_is_named_once(repo):
    assert _init(repo, '--adr-dir', 'docs/adrs') == 0
    guide = (repo / 'docs/workflows/documentation-guide.md').read_text(encoding='utf-8')
    assert '[`docs/adrs/`](../adrs/README.md)' in guide
    assert 'adrss' not in guide
    assert _init(repo, '--check') == 0


def test_drift_follows_a_recursive_adr_glob(repo, capsys):
    _init(repo)
    toml = repo / '.docs.toml'
    toml.write_text(toml.read_text(encoding='utf-8') + (
        '\n[rules.adr-number-collision]\nadr_glob = "docs/adr/**/[0-9]*.md"\n'
    ), encoding='utf-8')
    capsys.readouterr()
    assert _init(repo, '--check') == 0
    assert 'all templates match' in capsys.readouterr().out


def test_launcher_ignores_repo_files_shadowing_the_stdlib(repo):
    shim = Path(scaffold.__file__).resolve().parents[2] / 'bin' / 'tahrir'
    (repo / 'argparse.py').write_text('raise SystemExit("shadowed")\n', encoding='utf-8')
    done = subprocess.run(['bash', str(shim), '--version'], cwd=repo,
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == f'tahrir {scaffold.__version__}'


def test_a_routing_doc_alone_writes_no_enabled_key(repo):
    assert _init(repo, '--routing-doc', 'CLAUDE.md') == 0
    assert _toml(repo)['doc-gate'] == {'routing_doc': 'CLAUDE.md'}
    config.load(repo)


def test_typescript_supersedes_the_javascript_a_package_json_implies(tmp_path):
    (tmp_path / 'package.json').write_text('{}\n', encoding='utf-8')
    (tmp_path / 'tsconfig.json').write_text('{}\n', encoding='utf-8')
    assert scaffold.detect_languages(tmp_path) == ['typescript']


def test_detect_languages_probes_the_tree_when_git_is_missing(tmp_path, monkeypatch):
    (tmp_path / 'tools').mkdir()
    (tmp_path / 'tools/run.sh').write_text('echo\n', encoding='utf-8')
    (tmp_path / 'main.py').write_text('x = 1\n', encoding='utf-8')
    monkeypatch.setenv('PATH', '')
    assert scaffold.detect_languages(tmp_path) == ['python', 'shell']
    (tmp_path / 'main.py').unlink()
    assert scaffold.detect_languages(tmp_path) == ['shell']


def test_init_without_git_still_scaffolds_and_detects_by_files(tmp_path, monkeypatch):
    (tmp_path / 'run.sh').write_text('echo\n', encoding='utf-8')
    monkeypatch.setenv('PATH', '')
    assert _init(tmp_path) == 0
    assert _toml(tmp_path)['corpus']['code_globs'] == ['*.sh']


@pytest.mark.parametrize('broken', ['dir', 'toml'])
def test_check_falls_back_to_the_shipped_log_when_the_config_cannot_load(repo, capsys, broken):
    _init(repo, '--adr-dir', 'decisions')
    (repo / '.docs.toml').unlink()
    if broken == 'dir':
        (repo / '.docs.toml').mkdir()
    else:
        (repo / '.docs.toml').write_text('not = [valid\n', encoding='utf-8')
    capsys.readouterr()
    assert _init(repo, '--check') == 1
    out = capsys.readouterr().out
    assert 'missing  docs/adr/template.md' in out
    assert 'decisions' not in out


def test_check_with_adr_dir_against_a_kept_config_warns(repo, capsys):
    _init(repo, '--adr-dir', 'docs/decisions')
    capsys.readouterr()
    assert _init(repo, '--check', '--adr-dir', 'other') == 1
    captured = capsys.readouterr()
    assert "'other'" in captured.err and "'docs/decisions'" in captured.err
    assert 'missing  other/template.md' in captured.out
