from __future__ import annotations

import pytest

from docsteward.config import (
    DEFAULT_HARD,
    DEFAULT_SOFT,
    FAIL,
    OFF,
    WARN,
    Config,
    ConfigError,
    decorator_matches,
    glob_match,
    load,
)


def write_config(tmp_path, text):
    (tmp_path / '.docs.toml').write_text(text, encoding='utf-8')


# --- load -------------------------------------------------------------------


def test_load_without_a_config_gives_defaults(tmp_path):
    config = load(tmp_path)
    assert config.source is None
    assert (config.soft, config.hard) == (DEFAULT_SOFT, DEFAULT_HARD)
    assert config.profile == 'default'


def test_load_reads_docs_toml(tmp_path):
    write_config(tmp_path, '[defaults]\nsoft = 500\nhard = 900\n')
    config = load(tmp_path)
    assert config.source == tmp_path / '.docs.toml'
    assert (config.soft, config.hard) == (500, 900)


def test_load_explicit_path_that_does_not_exist(tmp_path):
    with pytest.raises(ConfigError, match='no config at'):
        load(tmp_path, tmp_path / 'missing.toml')


def test_load_bad_toml_is_a_config_error(tmp_path):
    write_config(tmp_path, '[defaults\n')
    with pytest.raises(ConfigError):
        load(tmp_path)


def test_load_profile_argument_beats_the_file(tmp_path):
    write_config(tmp_path, 'profile = "default"\n')
    assert load(tmp_path, profile='strict').profile == 'strict'


# --- unknown sections and keys -----------------------------------------------


def test_unknown_section():
    with pytest.raises(ConfigError, match='unknown section'):
        Config({'defualts': {}})


def test_unknown_doc_gate_key():
    with pytest.raises(ConfigError, match=r'\[doc-gate\]: unknown key'):
        Config({'doc-gate': {'enable': True}})


def test_doc_gate_values_are_not_typed_by_the_engine():
    # The UserPromptSubmit hook (scripts/doc-gate.sh) reads these and accepts
    # `enabled = "no"` as off on purpose; the engine checks the keys only.
    Config({'doc-gate': {'enabled': 'no', 'routing_doc': 'AGENTS.md'}})


def test_unknown_rule():
    with pytest.raises(ConfigError, match='unknown rule'):
        Config({'rules': {'no-such-rule': {'severity': WARN}}})


def test_unknown_rule_knob():
    with pytest.raises(ConfigError, match='unknown key'):
        Config({'rules': {'wall-of-text': {'tokens_per_head': 10}}})


def test_help_is_not_a_knob():
    with pytest.raises(ConfigError, match='unknown key'):
        Config({'rules': {'wall-of-text': {'help': 'mine'}}})


def test_rule_with_no_knobs_says_so():
    with pytest.raises(ConfigError, match='it has no knobs'):
        Config({'rules': {'docstring': {'max': 1}}})


def test_unknown_override_key():
    with pytest.raises(ConfigError, match='unknown key'):
        Config({'overrides': [{'pattern': 'a/**', 'cap': 5}]})


def test_override_needs_a_pattern():
    with pytest.raises(ConfigError, match='needs a `pattern`'):
        Config({'overrides': [{'soft': 5}]})


def test_override_unknown_rule():
    with pytest.raises(ConfigError, match='unknown rule'):
        Config({'overrides': [{'pattern': 'a/**', 'rules': {'nope': WARN}}]})


# --- bad types ----------------------------------------------------------------


@pytest.mark.parametrize('data', [{'exclude': 'vendor'}, {'defaults': 5}])
def test_section_must_be_a_table(data):
    with pytest.raises(ConfigError, match='must be a table'):
        Config(data)


@pytest.mark.parametrize('section, value', [('python', 'no'), ('comments', 1)])
def test_enabled_must_be_a_boolean(section, value):
    with pytest.raises(ConfigError, match='enabled must be true or false'):
        Config({section: {'enabled': value}})


def test_exclude_paths_must_be_a_list_not_a_string():
    with pytest.raises(ConfigError, match='paths must be a list of strings'):
        Config({'exclude': {'paths': 'vendor/**'}})


def test_exclude_paths_elements_must_be_strings():
    with pytest.raises(ConfigError, match='a list of strings'):
        Config({'exclude': {'paths': ['vendor/**', 3]}})


def test_comment_prefixes_must_be_strings():
    with pytest.raises(ConfigError, match='a table of strings'):
        Config({'comments': {'prefixes': {'.x': 1}}})


@pytest.mark.parametrize('value', ['1000', 0.5])
def test_default_cap_must_be_a_whole_number(value):
    with pytest.raises(ConfigError, match='soft must be a whole number'):
        Config({'defaults': {'soft': value}})


def test_integral_float_cap_is_accepted():
    config = Config({'defaults': {'soft': 1000.0}})
    assert config.soft == 1000
    assert isinstance(config.soft, int)


def test_profile_must_be_a_string():
    with pytest.raises(ConfigError, match='profile must be a string'):
        Config({'profile': 5})


def test_overrides_must_be_a_list():
    with pytest.raises(ConfigError, match='must be a list of tables'):
        Config({'overrides': {'pattern': 'x'}})


def test_override_entry_must_be_a_table():
    with pytest.raises(ConfigError, match='must be a table'):
        Config({'overrides': ['docs/**']})


def test_override_pattern_must_be_a_string():
    with pytest.raises(ConfigError, match='`pattern` must be a string'):
        Config({'overrides': [{'pattern': 5, 'soft': 10}]})


@pytest.mark.parametrize('cap, value', [('soft', 'big'), ('hard', 1.5)])
def test_override_caps_must_be_numeric(cap, value):
    with pytest.raises(ConfigError, match=f'{cap} must be a whole number'):
        Config({'overrides': [{'pattern': 'docs/**', cap: value}]})


def test_override_structure_rules_must_be_a_boolean():
    with pytest.raises(ConfigError, match='structure_rules must be true or false'):
        Config({'overrides': [{'pattern': 'docs/**', 'structure_rules': 'false'}]})


def test_override_rules_string_other_than_off():
    with pytest.raises(ConfigError, match='rules must be a table'):
        Config({'overrides': [{'pattern': 'docs/**', 'rules': 'warn'}]})


def test_override_rule_severity_is_validated_at_load():
    with pytest.raises(ConfigError, match='severity must be one of'):
        Config({'overrides': [{'pattern': 'docs/**', 'rules': {'docstring': 'loud'}}]})


def test_rule_entry_must_be_a_table():
    with pytest.raises(ConfigError, match=r'\[rules.docstring\] must be a table'):
        Config({'rules': {'docstring': 'fail'}})


def test_rule_severity_is_validated():
    with pytest.raises(ConfigError, match='severity must be one of'):
        Config({'rules': {'docstring': {'severity': 'error'}}})


@pytest.mark.parametrize('value', ['long', True])
def test_rule_knob_shape(value):
    with pytest.raises(ConfigError, match='max_chars must be int'):
        Config({'rules': {'prose-line-long': {'max_chars': value}}})


def test_list_knob_elements_must_be_strings():
    with pytest.raises(ConfigError, match='a list of strings'):
        Config({'rules': {'todo-marker': {'markers': [1]}}})


@pytest.mark.parametrize('template', ['{{version}}', 'v{version}-{x}', 'plain'])
def test_tag_template_must_use_version_only(template):
    with pytest.raises(ConfigError, match='tag template'):
        Config({'rules': {'changelog-unreleased-tagged': {'default_tag': template}}})


def test_status_override_needs_a_cap():
    with pytest.raises(ConfigError, match='does nothing'):
        Config({'overrides': [{'pattern': 'docs/adr/**', 'status': ['Superseded*']}]})


def test_status_override_cannot_set_rules():
    with pytest.raises(ConfigError, match='sets caps only'):
        Config({'overrides': [
            {'pattern': 'docs/adr/**', 'status': ['Superseded*'], 'soft': 1, 'rules': 'off'},
        ]})


# --- profiles and severities -------------------------------------------------


def test_default_profile_severities():
    config = Config()
    assert config.rule('over-hard-cap').severity == FAIL
    assert config.rule('over-soft-cap').severity == WARN
    assert config.rule('docstring').severity == OFF
    assert config.rule('doc-code-ratio').severity == OFF


def test_strict_profile_promotes_docstring_and_ratio():
    config = Config({'profile': 'strict'})
    assert config.rule('docstring').severity == FAIL
    assert config.rule('doc-code-ratio').severity == WARN
    assert config.rule('over-soft-cap').severity == WARN


def test_unknown_profile():
    with pytest.raises(ConfigError, match='unknown profile'):
        Config({'profile': 'paranoid'})


def test_configured_severity_beats_profile():
    config = Config({'profile': 'strict', 'rules': {'docstring': {'severity': WARN}}})
    assert config.rule('docstring').severity == WARN


def test_configured_knob_merges_with_defaults():
    config = Config({'rules': {'wall-of-text': {'floor': 10}}})
    rule = config.rule('wall-of-text')
    assert rule.opts == {'tokens_per_heading': 450, 'floor': 10}
    assert rule.on


def test_rule_opts_do_not_share_the_default_list():
    config = Config()
    config.rule('todo-marker').opts['markers'].append('NOTE')
    assert 'NOTE' not in Config().rule('todo-marker').opts['markers']


def test_override_severity_for_a_path():
    config = Config({'overrides': [{'pattern': 'legacy/**', 'rules': {'over-hard-cap': WARN}}]})
    assert config.rule('over-hard-cap', 'legacy/a.md').severity == WARN
    assert config.rule('over-hard-cap', 'docs/a.md').severity == FAIL
    assert config.rule('over-hard-cap').severity == FAIL


def test_override_severity_first_match_wins():
    config = Config({'overrides': [
        {'pattern': 'docs/api/**', 'rules': {'prose-line-long': OFF}},
        {'pattern': 'docs/**', 'rules': {'prose-line-long': FAIL}},
    ]})
    assert config.rule('prose-line-long', 'docs/api/x.md').severity == OFF
    assert config.rule('prose-line-long', 'docs/x.md').severity == FAIL


def test_override_without_that_rule_falls_through():
    config = Config({'overrides': [
        {'pattern': 'docs/**', 'rules': {'docstring': WARN}},
        {'pattern': 'docs/**', 'rules': {'prose-line-long': OFF}},
    ]})
    assert config.rule('prose-line-long', 'docs/x.md').severity == OFF


# --- caps ---------------------------------------------------------------------


def test_builtin_caps():
    config = Config()
    assert config.caps_for('notes.md') == (DEFAULT_SOFT, DEFAULT_HARD)
    assert config.caps_for('README.md') == (2000, 3000)
    assert config.caps_for('pkg/sub/README.md') == (2000, 3000)
    assert config.caps_for('docs/adr/0001-x.md') == (1200, 2000)


def test_user_override_is_consulted_before_builtins():
    config = Config({'overrides': [{'pattern': 'docs/adr/**', 'soft': 50, 'hard': 60}]})
    assert config.caps_for('docs/adr/0001-x.md') == (50, 60)


def test_caps_first_match_wins_among_user_overrides():
    config = Config({'overrides': [
        {'pattern': 'docs/a/**', 'soft': 1, 'hard': 2},
        {'pattern': 'docs/**', 'soft': 3, 'hard': 4},
    ]})
    assert config.caps_for('docs/a/x.md') == (1, 2)
    assert config.caps_for('docs/b/x.md') == (3, 4)


def test_adr_readme_takes_readme_cap_and_keeps_structure_exemption():
    config = Config()
    assert config.caps_for('docs/adr/README.md') == (2000, 3000)
    assert not config.structure_enabled('docs/adr/README.md')
    assert config.structure_enabled('docs/guide.md')


def test_status_override_outranks_a_path_override():
    config = Config({'overrides': [
        {'pattern': 'docs/adr/**', 'status': ['Superseded*'], 'soft': 10, 'hard': 20},
    ]})
    rel = 'docs/adr/0002-x.md'
    assert config.caps_for(rel, 'Superseded by docs/adr/0004.md') == (10, 20)
    assert config.caps_for(rel, 'Accepted') == (1200, 2000)
    assert config.caps_for(rel) == (1200, 2000)


def test_soft_only_override_keeps_hard_at_or_above_soft():
    config = Config({'overrides': [{'pattern': '**/README.md', 'soft': 2500}]})
    soft, hard = config.caps_for('README.md')
    assert soft == 2500
    assert hard >= soft


def test_rules_off_mutes_a_subtree():
    config = Config({'overrides': [{'pattern': 'vendor/**', 'rules': 'off'}]})
    assert config.rules_muted('vendor/x.md')
    assert not config.rules_muted('docs/x.md')


def test_exclusions():
    config = Config({'exclude': {'paths': ['vendor/**']}})
    assert config.is_excluded('vendor/a/b.md')
    assert config.is_excluded('pkg/foo_pb2.py')
    assert not config.is_excluded('docs/a.md')


def test_always_exempt_matches_by_name_too():
    config = Config()
    assert config.is_pattern_exempt('CHANGELOG.md')
    assert config.is_pattern_exempt('pkg/CHANGELOG.md')
    assert config.is_pattern_exempt('prompts/review.prompt.md')
    assert not config.is_pattern_exempt('changelog.md')


def test_comment_prefix_overrides():
    config = Config({'comments': {'prefixes': {'.ts': '#', '.foo': '%'}}})
    assert config.comment_prefix('.ts') == '#'
    assert config.comment_prefix('.foo') == '%'
    assert config.comment_prefix('.go') == '//'
    assert config.comment_prefix('.md') is None


# --- for_scan ----------------------------------------------------------------


def test_for_scan_promotes_inherited_off_to_warn():
    scan = Config().for_scan()
    assert scan.rule('docstring').severity == WARN
    assert scan.rule('changed-without-docs').severity == WARN


def test_for_scan_demotes_fail_to_warn():
    assert Config().for_scan().rule('over-hard-cap').severity == WARN


def test_for_scan_keeps_a_stated_off():
    scan = Config({'rules': {'docstring': {'severity': OFF}}}).for_scan()
    assert scan.rule('docstring').severity == OFF


def test_for_scan_promotes_a_profile_off():
    # The strict profile has nothing to say about todo-marker: still inherited.
    scan = Config({'profile': 'strict'}).for_scan()
    assert scan.rule('todo-marker').severity == WARN


def test_for_scan_keeps_an_override_off_but_demotes_an_override_fail():
    config = Config({'overrides': [
        {'pattern': 'legacy/**', 'rules': {'prose-line-long': OFF, 'docstring': FAIL}},
    ]}).for_scan()
    assert config.rule('prose-line-long', 'legacy/x.md').severity == OFF
    assert config.rule('docstring', 'legacy/x.py').severity == WARN
    assert config.rule('prose-line-long', 'docs/x.md').severity == WARN


def test_for_scan_does_not_touch_the_original():
    config = Config()
    config.for_scan()
    assert config.rule('over-hard-cap').severity == FAIL
    assert config.rule('docstring').severity == OFF


# --- glob_match ---------------------------------------------------------------


@pytest.mark.parametrize('rel, pattern, expected', [
    ('README.md', '**/README.md', True),
    ('a/b/README.md', '**/README.md', True),
    ('docs/adr/sub/0001-x.md', 'docs/adr/**', True),
    ('docs/a/x.md', 'docs/*.md', False),
    ('docs/a/.md', 'docs/a?.md', False),
    ('api/v2', '*/v[0-9]*', True),
    ('a/b', 'a[!x]b', False),
    ('a]b', 'a[]]b', True),
    ('a[b', 'a[b', True),
    ('a[z-a]b', 'a[z-a]b', True),
    ('axb', 'a.b', False),
    ('DOCS/x.md', 'docs/*.md', False),
])
def test_glob_match(rel, pattern, expected):
    assert glob_match(rel, pattern) is expected


# --- decorator_matches --------------------------------------------------------


@pytest.mark.parametrize('dotted, pattern, expected', [
    ('strawberry.type', 'strawberry', True),
    ('strawberryx', 'strawberry', False),
    ('tool', '*.tool', True),
    ('app.mcp.tool', '*.tool', True),
    ('toolkit', '*.tool', False),
    ('app', 'app.*', False),
])
def test_decorator_matches(dotted, pattern, expected):
    assert decorator_matches(dotted, pattern) is expected


# --- stricter validation ------------------------------------------------------


@pytest.mark.parametrize('section, key', [
    ('defaults', 'sofft'), ('exclude', 'path'), ('python', 'enabeld'),
    ('comments', 'prefix'), ('corpus', 'doc_glob'),
])
def test_an_unknown_key_in_a_section_is_named(section, key):
    with pytest.raises(ConfigError, match=rf'\[{section}\]: unknown key\(s\) {key}'):
        Config({section: {key: 1}})


@pytest.mark.parametrize('data', [
    {'defaults': {'soft': -1}},
    {'defaults': {'hard': -5}},
    {'overrides': [{'pattern': 'a/**', 'soft': -1}]},
    {'python': {'docstring_cap': -1}},
    {'python': {'module_docstring_cap': -2}},
    {'rules': {'prose-line-long': {'max_chars': -1}}},
])
def test_a_negative_cap_is_rejected(data):
    with pytest.raises(ConfigError, match='negative'):
        Config(data)


@pytest.mark.parametrize('data', [
    {'defaults': {'soft': 2000, 'hard': 1000}},
    {'defaults': {'soft': 1500}},
    {'overrides': [{'pattern': 'a/**', 'soft': 50, 'hard': 10}]},
])
def test_a_soft_cap_above_the_hard_cap_is_rejected(data):
    with pytest.raises(ConfigError, match='soft cap .* above'):
        Config(data)


@pytest.mark.parametrize('value', [1.5, 'x', True])
def test_a_rule_knob_with_a_whole_number_default_must_be_one(value):
    with pytest.raises(ConfigError, match='max_chars must be int'):
        Config({'rules': {'prose-line-long': {'max_chars': value}}})


def test_a_config_that_is_not_utf8_is_a_config_error(tmp_path):
    (tmp_path / '.docs.toml').write_bytes(b'profile = "default"\n# \xff\xfe\n')
    with pytest.raises(ConfigError, match='not valid UTF-8'):
        load(tmp_path)


def test_the_shipped_defaults_pass_their_own_validation():
    assert Config({'defaults': {'soft': 1000, 'hard': 1400}}).soft == 1000
    assert Config({'defaults': {'soft': 0, 'hard': 0}}).hard == 0


def test_a_boolean_is_not_a_whole_number_for_a_cap():
    with pytest.raises(ConfigError, match=r'\[python\]: docstring_cap must be a whole number'):
        Config({'python': {'docstring_cap': True}})


def test_a_float_knob_takes_any_number_and_nothing_else():
    cfg = Config({'rules': {'doc-code-ratio': {'ratio': 1}}})
    assert cfg.rule('doc-code-ratio').opts['ratio'] == 1
    with pytest.raises(ConfigError, match=r"ratio must be float, got 'x'"):
        Config({'rules': {'doc-code-ratio': {'ratio': 'x'}}})
    with pytest.raises(ConfigError, match='ratio must not be negative'):
        Config({'rules': {'doc-code-ratio': {'ratio': -0.5}}})


def test_a_table_knob_must_hold_strings_only():
    with pytest.raises(ConfigError, match=r'tag_patterns must be a table of strings'):
        Config({'rules': {'changelog-unreleased-tagged': {'tag_patterns': {'a': 1}}}})


def test_a_tag_template_with_unbalanced_braces_is_rejected():
    with pytest.raises(ConfigError, match=r"default_tag: 'v\{version' must be a tag template"):
        Config({'rules': {'changelog-unreleased-tagged': {'default_tag': 'v{version'}}})


def test_a_tag_pattern_template_is_checked_under_its_glob():
    with pytest.raises(ConfigError, match=r"pkg/\*\*: 'pkg-\{name\}' must be a tag template"):
        Config({'rules': {'changelog-unreleased-tagged': {
            'tag_patterns': {'pkg/**': 'pkg-{name}'},
        }}})


@pytest.mark.parametrize('status', ['Accepted', ['ok', 1], 3])
def test_a_status_override_needs_a_list_of_strings(status):
    with pytest.raises(ConfigError, match=r'docs/\*\*: status must be a list of strings'):
        Config({'overrides': [{'pattern': 'docs/**', 'status': status, 'soft': 1}]})


def test_an_empty_status_list_could_never_match():
    with pytest.raises(ConfigError, match=r'docs/\*\*: status must not be empty'):
        Config({'overrides': [{'pattern': 'docs/**', 'status': [], 'soft': 1}]})
