from __future__ import annotations

import pytest

from momayezi import config
from momayezi.config import ConfigError, K8s, Settings

K8S_FILE = 'backend = "k8s-job"\n[k8s]\ntemplate = "ops/momayezi-job.yaml"\nnamespace = "momayezi"\n'


def load(tmp_path, text=None, **env):
    if text is not None:
        (tmp_path / '.momayezi.toml').write_text(text, encoding='utf-8')
    return config.load({'CLAUDE_PROJECT_DIR': str(tmp_path), **env})


def test_no_settings_and_no_file_is_todays_label_with_pr_comments(tmp_path):
    assert load(tmp_path) == Settings('gh-label', 'all')


def test_the_default_root_is_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / '.momayezi.toml').write_text('backend = "gh-dispatch"\n', encoding='utf-8')
    assert config.load({}).backend == 'gh-dispatch'


def test_env_beats_user_beats_repo(tmp_path):
    text = 'backend = "gh-dispatch"\n'
    assert load(tmp_path, text).backend == 'gh-dispatch'
    assert load(tmp_path, text, MOMAYEZI_USER_REVIEWER_BACKEND='repo').backend == 'gh-dispatch'
    assert load(tmp_path, text, MOMAYEZI_USER_REVIEWER_BACKEND='gh-label').backend == 'gh-label'
    assert load(tmp_path, text, MOMAYEZI_USER_REVIEWER_BACKEND='gh-label',
                MOMAYEZI_REVIEWER_BACKEND='gh-dispatch').backend == 'gh-dispatch'


def test_an_unsubstituted_or_empty_setting_is_unset(tmp_path):
    got = load(tmp_path, MOMAYEZI_USER_REVIEWER_BACKEND='${user_config.momayezi_reviewer_backend}',
               MOMAYEZI_USER_PR_COMMENTS=' ', MOMAYEZI_REVIEWER_BACKEND='')
    assert got == Settings('gh-label', 'all')


def test_auto_pr_comments_follow_the_backend(tmp_path):
    assert load(tmp_path, MOMAYEZI_REVIEWER_BACKEND='gh-dispatch').pr_comments == 'all'
    got = load(tmp_path, K8S_FILE)
    assert got == Settings('k8s-job', 'none', K8s(tmp_path / 'ops/momayezi-job.yaml', 'momayezi'))
    assert load(tmp_path, K8S_FILE, MOMAYEZI_USER_PR_COMMENTS='all').pr_comments == 'all'
    got = load(tmp_path, MOMAYEZI_REVIEWER_BACKEND='gh-dispatch', MOMAYEZI_USER_PR_COMMENTS='none')
    assert got.pr_comments == 'none'


def test_the_pre_rename_repo_file_is_refused_not_ignored(tmp_path):
    (tmp_path / '.momayez.toml').write_text(K8S_FILE, encoding='utf-8')
    with pytest.raises(ConfigError, match='renamed .momayezi.toml'):
        load(tmp_path)


def test_a_chosen_gh_label_leaves_the_repo_file_unread(tmp_path):
    broken = 'backend = \n'
    assert load(tmp_path, broken, MOMAYEZI_USER_REVIEWER_BACKEND='gh-label').backend == 'gh-label'
    for backend in ('k8s-job', 'gh-dispatch'):
        with pytest.raises(ConfigError):
            load(tmp_path, broken, MOMAYEZI_REVIEWER_BACKEND=backend)


def test_dispatch_ref_is_gh_dispatchs_and_defaults_to_none(tmp_path):
    assert load(tmp_path, 'backend = "gh-dispatch"\n').dispatch_ref is None
    text = 'backend = "gh-dispatch"\ndispatch_ref = "main"\n'
    assert load(tmp_path, text).dispatch_ref == 'main'
    assert load(tmp_path, text, MOMAYEZI_REVIEWER_BACKEND='gh-dispatch').dispatch_ref == 'main'
    assert load(tmp_path, 'dispatch_ref = "main"\n').dispatch_ref is None  # gh-label's branch dispatch ignores it


def test_k8s_context_is_optional(tmp_path):
    got = load(tmp_path, K8S_FILE + 'context = "staging"\n')
    assert got.k8s.context == 'staging'


@pytest.mark.parametrize('text, env, message', [
    (None, {'MOMAYEZI_REVIEWER_BACKEND': 'lambda'}, "unknown reviewer backend 'lambda'"),
    (None, {'MOMAYEZI_USER_PR_COMMENTS': 'some'}, "unknown pr_comments 'some'"),
    (None, {'MOMAYEZI_USER_PR_COMMENTS': 'none'}, 'gh-label needs PR comments'),
    ('backend = "k8s-job"\n', {}, 'k8s-job needs [k8s] template and namespace'),
    ('backend = "k8s-job"\nk8s = 3\n', {}, 'k8s-job needs [k8s]'),
    ('backend = \n', {}, '.momayezi.toml:'),
])
def test_bad_settings_are_errors(tmp_path, text, env, message):
    with pytest.raises(ConfigError, match=None) as raised:
        load(tmp_path, text, **env)
    assert message in str(raised.value)
