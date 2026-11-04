from __future__ import annotations

import errno
from pathlib import Path

import pytest
from helpers import commit, config, counter, doc, git, prose, repo, rules, write

from docsteward import corpus, scanner
from docsteward.config import FAIL, WARN, Config
from docsteward.rules import findings_for


SMALL_CAPS = config(defaults={'soft': 10, 'hard': 20})


def ids(found):
    return [f.rule for f in found]


def sections(count, tokens_each):
    return ''.join(f'## Section {i}\n\n{prose(tokens_each)}\n\n' for i in range(count))


# --- caps ---------------------------------------------------------------------


def test_under_the_soft_cap_is_clean():
    assert findings_for(doc(prose(5)), SMALL_CAPS) == []


def test_over_soft_cap():
    [finding] = findings_for(doc(prose(15)), SMALL_CAPS)
    assert finding.rule == 'over-soft-cap'
    assert finding.severity == WARN
    assert 'soft cap 10' in finding.message


def test_over_hard_cap_fails_with_a_hint():
    [finding] = findings_for(doc(prose(40)), SMALL_CAPS)
    assert finding.rule == 'over-hard-cap'
    assert finding.severity == FAIL
    assert finding.line == 1
    assert 'hard cap 20' in finding.message
    assert finding.hint


def test_over_hard_cap_does_not_also_report_soft():
    assert ids(findings_for(doc(prose(40)), SMALL_CAPS)) == ['over-hard-cap']


def test_counter_grace_relaxes_both_caps():
    assert ids(findings_for(doc(prose(30)), SMALL_CAPS, counter_grace=2.0)) == ['over-soft-cap']


def test_pre_existing_oversize_is_demoted_to_warn():
    big = doc(prose(40))
    [finding] = findings_for(big, SMALL_CAPS, baseline_tokens=big.tokens)
    assert finding.severity == WARN
    assert 'pre-existing' in finding.message


def test_growing_an_oversized_doc_still_fails():
    big = doc(prose(40))
    [finding] = findings_for(big, SMALL_CAPS, baseline_tokens=big.tokens - 5)
    assert finding.severity == FAIL


def test_hard_cap_rule_off():
    cfg = Config({'defaults': {'soft': 10, 'hard': 20},
                  'rules': {'over-hard-cap': {'severity': 'off'}}})
    assert findings_for(doc(prose(40)), cfg) == []


def test_readme_gets_the_readme_cap():
    text = sections(4, 375)
    assert ids(findings_for(doc(text, 'README.md'), Config())) == []
    assert ids(findings_for(doc(text, 'docs/x.md'), Config())) == ['over-hard-cap']


def test_code_fences_are_discounted():
    code = '```python\n' + ('x = 1\n' * 10) + '```\n'
    bare = '```\n' + ('x = 1\n' * 10) + '```\n'
    assert doc(code).tokens < doc(bare).tokens


def test_exempt_marker_skips_every_rule():
    text = '<!-- docs: exempt — generated -->\n' + prose(40)
    assert findings_for(doc(text), SMALL_CAPS) == []


def test_muted_subtree_skips_every_rule():
    cfg = Config({'defaults': {'soft': 10, 'hard': 20},
                  'overrides': [{'pattern': 'docs/**', 'rules': 'off'}]})
    assert findings_for(doc(prose(40)), cfg) == []


# --- hard-cap hints -----------------------------------------------------------


def hard_cap_hint(text, cfg=SMALL_CAPS, **kwargs):
    [finding] = [f for f in findings_for(doc(text), cfg, **kwargs) if f.rule == 'over-hard-cap']
    return finding.hint


def test_hint_moves_a_labelled_fence_that_is_the_overage():
    text = '# T\n\n```python\n' + 'x = 1\n' * 60 + '```\n'
    assert hard_cap_hint(text) == (
        'move the python block at L3-64 (62 lines) out to docs/examples/python and link to it'
    )


def test_hint_leaves_a_fence_alone_when_prose_is_the_overage():
    text = '# T\n\n```python\n' + 'x = 1\n' * 25 + '```\n\n' + prose(100)
    assert hard_cap_hint(text).startswith('no single fix stands out')


def test_hint_points_at_a_duplicate_that_covers_the_overage():
    text = prose(40)
    hint = hard_cap_hint(text, duplicate_tokens=30, duplicate_with='docs/other.md')
    assert hint.startswith('~30 tok of this also appears in docs/other.md')
    assert 'link' in hint
    assert 'also appears' not in hard_cap_hint(text, duplicate_tokens=5, duplicate_with='x.md')
    assert 'also appears' not in hard_cap_hint(text, duplicate_tokens=30)


def test_hint_splits_at_the_most_balanced_h2_and_keeps_the_first_of_a_tie():
    cfg = config(defaults={'soft': 100, 'hard': 250})
    hint = hard_cap_hint(sections(3, 100), cfg)
    assert hint.startswith('split at "## Section 1": docs/guide.md keeps ~')
    assert 'docs/section-1.md takes ~' in hint


def test_hint_names_the_section_holding_most_of_the_doc():
    cfg = config(defaults={'soft': 50, 'hard': 100})
    text = '# Big\n\n' + prose(150) + '\n# Small\n\n' + prose(100)
    hint = hard_cap_hint(text, cfg)
    assert hint.startswith('cut ~')
    assert '"# Big"' in hint
    assert '60% of the doc' in hint


def test_hint_does_not_name_a_section_that_is_the_whole_doc():
    cfg = config(defaults={'soft': 50, 'hard': 100})
    text = '# Big\n\n' + prose(400) + '\n# Tiny\n\nx\n'
    assert hard_cap_hint(text, cfg).startswith('no single fix stands out')


# --- structure ----------------------------------------------------------------


def test_wall_of_text_without_headings():
    [finding] = findings_for(doc(prose(500)), Config())
    assert finding.rule == 'wall-of-text'
    assert 'no headings' in finding.message


def test_wall_of_text_below_the_floor_is_quiet():
    assert findings_for(doc(prose(300)), Config()) == []


def test_wall_of_text_tokens_per_heading():
    [finding] = findings_for(doc(sections(1, 500)), Config())
    assert finding.rule == 'wall-of-text'
    assert 'per heading' in finding.message


def test_enough_headings_clears_wall_of_text():
    assert findings_for(doc(sections(2, 250)), Config()) == []


def test_over_fragmented():
    [finding] = findings_for(doc(sections(10, 42)), Config())
    assert finding.rule == 'over-fragmented'
    assert finding.message.startswith('10 headings')


def test_over_fragmented_respects_min_headings():
    cfg = Config({'rules': {'over-fragmented': {'min_headings': 20}}})
    assert findings_for(doc(sections(10, 42)), cfg) == []


def test_adr_folder_has_no_structure_rules():
    assert findings_for(doc(prose(500), 'docs/adr/0001-x.md'), Config()) == []


# --- formatting ---------------------------------------------------------------


def test_prose_line_long():
    text = '# T\n\n' + 'word ' * 30 + '\n'
    [finding] = findings_for(doc(text), Config())
    assert finding.rule == 'prose-line-long'
    assert finding.line == 3


def test_prose_line_long_ignores_urls_and_code_spans():
    text = 'see https://example.com/' + 'a' * 100 + ' and `' + 'b' * 40 + '`\n'
    assert findings_for(doc(text), Config()) == []


def test_prose_line_long_ignores_headings_and_labelled_fences():
    text = '# ' + 'h' * 150 + '\n\n```text\n' + 'c' * 150 + '\n```\n'
    assert findings_for(doc(text), Config()) == []


def test_prose_line_long_knob():
    cfg = Config({'rules': {'prose-line-long': {'max_chars': 20}}})
    assert ids(findings_for(doc('word ' * 5 + '\n'), cfg)) == ['prose-line-long']


def test_table_cell_crammed():
    text = '| a | b |\n|---|---|\n| x | ' + 'y' * 130 + ' |\n'
    [finding] = findings_for(doc(text), Config())
    assert finding.rule == 'table-cell-crammed'
    assert finding.line == 3


def test_list_item_long_reports_the_item_not_its_lines():
    text = '- ' + 'word ' * 130 + '\n'
    [finding] = findings_for(doc(text), Config())
    assert finding.rule == 'list-item-long'


def test_list_item_long_joins_wrapped_lines():
    item = '- start\n' + ''.join('  ' + 'word ' * 20 + '\n' for _ in range(7))
    [finding] = findings_for(doc(item), Config())
    assert finding.rule == 'list-item-long'
    assert finding.line == 1


def test_short_list_items_are_clean():
    assert findings_for(doc('- one\n- two\n  continued\n'), Config()) == []


# --- duplicates ---------------------------------------------------------------


def test_cross_doc_duplicate():
    shared = prose(60).replace('\n', ' ')
    docs = [doc(f'# A\n\n{shared}\n', 'a.md'), doc(f'# B\n\n{shared}\n', 'b.md')]
    found, worst = corpus.duplicate_findings(docs, counter(), Config())
    assert sorted(f.rel for f in found) == ['a.md', 'b.md']
    assert {f.rule for f in found} == {'cross-doc-duplicate'}
    assert worst['a.md'][1] == 'b.md'


def test_short_shared_block_is_not_a_duplicate():
    docs = [doc('# A\n\nsee the docs\n', 'a.md'), doc('# B\n\nsee the docs\n', 'b.md')]
    assert corpus.duplicate_findings(docs, counter(), Config()) == ([], {})


# --- stale-file-ref -----------------------------------------------------------


def stale(root, text, cfg=None, rel='docs/guide.md', suffixes=None):
    return scanner.stale_file_refs(root, rel, text, cfg or Config(), suffixes)


def test_stale_link(tmp_path):
    [finding] = stale(tmp_path, 'see [x](missing.md)\n')
    assert finding.rule == 'stale-file-ref'
    assert 'missing.md' in finding.message


def test_live_links_resolve_doc_relative_and_root_relative(tmp_path):
    write(tmp_path, {'docs/near.md': '', 'src/app.py': ''})
    text = '[a](near.md) and `src/app.py` and [b](/src/app.py#L3)\n'
    assert stale(tmp_path, text) == []


def test_backticked_path_without_a_slash_is_not_a_reference(tmp_path):
    assert stale(tmp_path, 'run `setup.py`\n') == []


def test_urls_anchors_and_fences_are_not_references(tmp_path):
    text = '[u](https://x.io/a.md) [h](#top)\n\n```md\n[x](gone.md)\n```\n'
    assert stale(tmp_path, text) == []


def test_allow_marker_on_the_line_or_above(tmp_path):
    text = (
        '<!-- docs: allow stale-file-ref -->\n[a](gone.md)\n\n'
        '[b](gone2.md) <!-- docs: allow stale-file-ref -->\n'
    )
    assert stale(tmp_path, text) == []


def test_ignore_patterns(tmp_path):
    assert stale(tmp_path, '[spec](api/v2.json)\n') == []
    cfg = Config({'rules': {'stale-file-ref': {'ignore_patterns': ['old/*']}}})
    assert stale(tmp_path, '[x](old/a.md)\n', cfg) == []


def test_package_roots_resolve_package_shorthand(tmp_path):
    write(tmp_path, {'services/shop/apps/x.py': ''})
    rel = 'services/shop/docs/guide.md'
    text = 'see `apps/x.py`\n'
    assert len(stale(tmp_path, text, rel=rel)) == 1
    cfg = Config({'corpus': {'package_roots': ['services/']}})
    assert stale(tmp_path, text, cfg, rel=rel) == []


def test_suffix_index_accepts_a_tracked_suffix(tmp_path):
    text = 'see `pkg/mod.py`\n'
    assert stale(tmp_path, text, suffixes=frozenset({'pkg/mod.py'})) == []
    assert len(stale(tmp_path, '[x](../pkg/mod.py)\n', suffixes=frozenset({'pkg/mod.py'}))) == 1


@pytest.mark.parametrize('target', [
    'ftp://h/a.md', 'ssh://git@h/a.md', 'HTTPS://x.io/a.md', 'git+ssh://h/a.md', 'Mailto:a@b.io',
])
def test_any_url_scheme_is_external_in_any_case(tmp_path, target):
    assert stale(tmp_path, f'[x]({target})\n') == []


def test_a_link_shown_in_inline_code_is_an_example(tmp_path):
    assert stale(tmp_path, 'write `[x](missing.md)` to link\n') == []
    assert len(stale(tmp_path, 'write [x](missing.md) to link\n')) == 1


def test_a_percent_encoded_target_names_the_decoded_file(tmp_path):
    write(tmp_path, {'docs/my notes.md': ''})
    assert stale(tmp_path, '[x](my%20notes.md)\n') == []


def test_a_target_with_parentheses_and_a_single_quoted_title(tmp_path):
    write(tmp_path, {'docs/foo_(bar).md': '', 'docs/baz.md': ''})
    assert stale(tmp_path, "[x](foo_(bar).md) and [y](baz.md 'the title')\n") == []
    [finding] = stale(tmp_path, '[x](gone_(bar).md)\n')
    assert 'gone_(bar).md' in finding.message


def test_a_target_too_long_for_the_filesystem_is_just_missing(tmp_path, monkeypatch):
    # Python 3.12 and 3.13 raise from `Path.exists` here; 3.14 answers False.
    def too_long(self):
        raise OSError(errno.ENAMETOOLONG, 'File name too long')

    monkeypatch.setattr(Path, 'exists', too_long)
    [finding] = stale(tmp_path, f'[x]({"a" * 300}.md)\n')
    assert finding.rule == 'stale-file-ref'


# --- todo / checkbox / citation ----------------------------------------------


def test_todo_marker_is_off_by_default():
    assert scanner.todo_markers('a.md', 'TODO: later\n', Config()) == []


def test_todo_marker():
    found = scanner.todo_markers('a.md', 'x\nTODO: later\nTODOS are fine\nFIXME\n',
                                 rules(todo_marker='warn'))
    assert [(f.line, f.message) for f in found] == [
        (2, 'TODO marker left in place'),
        (4, 'FIXME marker left in place'),
    ]


def test_todo_marker_with_punctuation_in_the_marker():
    cfg = Config({'rules': {'todo-marker': {'severity': 'warn', 'markers': ['TODO:', '@todo']}}})
    found = scanner.todo_markers('a.md', 'a TODO: x\n// @todo y\nTODOS: no\nmy@todo\n', cfg)
    assert [f.line for f in found] == [1, 2]


def test_todo_marker_skips_a_fenced_example_in_a_doc_only():
    text = 'real TODO\n```\nsample TODO\n```\n'
    cfg = rules(todo_marker='warn')
    assert [f.line for f in scanner.todo_markers('a.md', text, cfg)] == [1]
    assert [f.line for f in scanner.todo_markers('a.py', text, cfg, prose=False)] == [1, 3]


def test_todo_marker_line_numbers_ignore_exotic_line_breaks():
    found = scanner.todo_markers('a.md', 'a\u2028b\x0cc\nTODO\n', rules(todo_marker='warn'))
    assert [f.line for f in found] == [2]


def test_todo_marker_custom_and_empty_lists():
    custom = Config({'rules': {'todo-marker': {'severity': 'warn', 'markers': ['NOTE']}}})
    assert [f.line for f in scanner.todo_markers('a.md', 'TODO\nNOTE\n', custom)] == [2]
    empty = Config({'rules': {'todo-marker': {'severity': 'warn', 'markers': []}}})
    assert scanner.todo_markers('a.md', 'TODO and words\n', empty) == []


def test_open_checkbox():
    text = '- [ ] open\n- [x] done\n* [ ] another\n'
    found = scanner.open_checkboxes('a.md', text, rules(open_checkbox='fail'))
    assert [(f.line, f.severity) for f in found] == [(1, FAIL), (3, FAIL)]


def test_open_checkbox_at_the_end_of_a_line_and_not_in_a_fence():
    text = '- [ ]\n```\n- [ ] sample\n```\n- [ ] real\n'
    found = scanner.open_checkboxes('a.md', text, rules(open_checkbox='fail'))
    assert [f.line for f in found] == [1, 5]


def test_section_citation_keeps_a_trailing_hash_and_ignores_fenced_headings(tmp_path):
    write(tmp_path, {'docs/other.md': '# Other\n\n## Learning C#\n\n```md\n## Sample\n```\n'})
    text = (
        '`docs/other.md`\'s "Learning C#" is there\n'
        '`docs/other.md`\'s "Sample" is only in a fence\n'
    )
    found = scanner.section_citations(tmp_path, 'README.md', text, rules(section_citation='warn'))
    assert [f.line for f in found] == [2]


def test_section_citation(tmp_path):
    write(tmp_path, {'docs/other.md': '# Other\n\n## Setup **steps**\n'})
    cfg = rules(section_citation='warn')
    text = (
        '`docs/other.md`\'s "Setup steps" is fine\n'
        'the "Teardown" section of `docs/other.md`\n'
        '`docs/gone.md`\'s "Setup"\n'
    )
    found = scanner.section_citations(tmp_path, 'README.md', text, cfg)
    assert [(f.line, f.message.split(' — ')[1]) for f in found] == [
        (2, 'no such section'),
        (3, 'no such file'),
    ]


# --- ADRs and changelogs (git) ------------------------------------------------


def adr_repo(tmp_path, index):
    return repo(tmp_path, {
        'docs/adr/0001-first.md': '# 1\n',
        'docs/adr/0001-clash.md': '# 1 again\n',
        'docs/adr/0002-second.md': '# 2\n',
        'docs/adr/README.md': index,
    })


def test_adr_number_collision(tmp_path):
    index = '[1](0001-first.md)\n[1b](./0001-clash.md)\n[2](0002-second.md)\n'
    [finding] = corpus.adr_findings(adr_repo(tmp_path, index), Config())
    assert finding.rule == 'adr-number-collision'
    assert 'ADR number 0001 is held by 2 files' in finding.message


def test_date_named_adrs_are_not_numbered(tmp_path):
    repo(tmp_path, {
        'docs/adr/2024-01-15-a.md': '# a\n', 'docs/adr/2024-03-01-b.md': '# b\n',
        'docs/adr/README.md': '[a](2024-01-15-a.md)\n[b](2024-03-01-b.md)\n',
    })
    cfg = Config({'rules': {'adr-number-collision': {'adr_glob': 'docs/adr/*.md'}}})
    assert corpus.adr_findings(tmp_path, cfg) == []


def test_a_short_number_ahead_of_a_slug_still_collides(tmp_path):
    repo(tmp_path, {
        'docs/adr/0001-a.md': '# a\n', 'docs/adr/0001-b.md': '# b\n', 'docs/adr/7-c.md': '# c\n',
        'docs/adr/7-d.md': '# d\n',
    })
    cfg = Config({'rules': {'adr-number-collision': {'adr_glob': 'docs/adr/*.md', 'index': ''}}})
    found = corpus.adr_findings(tmp_path, cfg)
    assert [f.message.split(' is ')[0] for f in found] == ['ADR number 0001', 'ADR number 7']


def test_adr_index_rows(tmp_path):
    index = '[1](0001-first.md)\n[1b](0001-clash.md)\n[3](0003-missing.md)\n[web](https://x.io)\n'
    found = corpus.adr_findings(adr_repo(tmp_path, index), Config())
    messages = sorted(f'{f.rel}: {f.message}' for f in found)
    assert any('index row links docs/adr/0003-missing.md' in m for m in messages)
    assert any(m.startswith('docs/adr/0002-second.md: no row') for m in messages)
    assert len(found) == 3


def test_adr_empty_index_skips_index_checks(tmp_path):
    cfg = Config({'rules': {'adr-number-collision': {'index': ''}}})
    found = corpus.adr_findings(adr_repo(tmp_path, ''), cfg)
    assert [f.message.split(' is ')[0] for f in found] == ['ADR number 0001']


def test_slug_named_adrs_need_a_row_but_the_index_and_template_do_not(tmp_path):
    repo(tmp_path, {
        'docs/adr/README.md': '[stripe](use-stripe.md)\n',
        'docs/adr/template.md': '# T\n',
        'docs/adr/use-stripe.md': '# a\n',
        'docs/adr/use-kafka.md': '# b\n',
    })
    cfg = Config({'rules': {'adr-number-collision': {'adr_glob': 'docs/adr/*.md'}}})
    [finding] = corpus.adr_findings(tmp_path, cfg)
    assert finding.rel == 'docs/adr/use-kafka.md'
    assert 'no row' in finding.message


def test_changelog_unreleased_but_tagged(tmp_path):
    repo(tmp_path, {'CHANGELOG.md': '# Changelog\n\n## [1.0.0] - Unreleased\n\n## [0.9.0] - Unreleased\n'})
    git(tmp_path, 'tag', 'v1.0.0')
    [finding] = corpus.changelog_findings(tmp_path, Config())
    assert finding.rule == 'changelog-unreleased-tagged'
    assert finding.line == 3
    assert 'tag v1.0.0 exists' in finding.message


def test_changelog_heading_spellings(tmp_path):
    repo(tmp_path, {'CHANGELOG.md': (
        '## [v1.0.0] - Unreleased\n## [2.0.0-rc.1] - Unreleased\n## 3.0.0 - Unreleased\n'
    )})
    for tag in ('v1.0.0', 'v2.0.0-rc.1', 'v3.0.0'):
        git(tmp_path, 'tag', tag)
    found = corpus.changelog_findings(tmp_path, Config())
    assert [f.line for f in found] == [1, 2, 3]
    assert [f.message.split(' is ')[0] for f in found] == ['1.0.0', '2.0.0-rc.1', '3.0.0']


def test_package_of_matches_a_whole_root_directory():
    assert corpus.package_of('apps/shop/docs/a.md', ['apps']) == 'apps/shop'
    assert corpus.package_of('apps2/shop/docs/a.md', ['apps']) is None
    assert corpus.package_of('apps/shop/docs/a.md', ['apps/']) == 'apps/shop'


def test_changelog_without_tags_is_quiet(tmp_path, capsys):
    repo(tmp_path, {'CHANGELOG.md': '## [1.0.0] - Unreleased\n'})
    assert corpus.changelog_findings(tmp_path, Config()) == []
    assert 'no git tags' in capsys.readouterr().err


def test_changelog_tag_patterns(tmp_path):
    repo(tmp_path, {'pkg/CHANGELOG.md': '## [2.0.0] - Unreleased\n'})
    commit(tmp_path, {'x.md': 'x\n'})
    git(tmp_path, 'tag', 'pkg-2.0.0')
    cfg = Config({'rules': {'changelog-unreleased-tagged': {
        'tag_patterns': {'pkg/**': 'pkg-{version}'},
    }}})
    assert len(corpus.changelog_findings(tmp_path, cfg)) == 1
    assert corpus.changelog_findings(tmp_path, Config()) == []


# --- rules switched off -------------------------------------------------------


def test_list_item_long_off_reports_nothing_for_a_wrapped_item():
    item = '- start\n' + ''.join('  ' + 'word ' * 20 + '\n' for _ in range(7))
    assert ids(findings_for(doc(item), Config())) == ['list-item-long']
    assert findings_for(doc(item), rules(list_item_long='off')) == []


def test_wall_of_text_off_ignores_a_doc_with_no_headings():
    assert ids(findings_for(doc(prose(500)), Config())) == ['wall-of-text']
    assert findings_for(doc(prose(500)), rules(wall_of_text='off')) == []


def test_wall_of_text_off_still_reports_over_fragmented():
    found = findings_for(doc(sections(10, 42)), rules(wall_of_text='off'))
    assert ids(found) == ['over-fragmented']
