from __future__ import annotations

from helpers import counter, doc, repo

from docsteward import corpus
from docsteward.markdown import (
    CODE,
    FRONT,
    HEADING,
    PROSE,
    analyze,
    doc_status,
    exempt_reason,
    unfenced_lines,
)


def kinds(text):
    return [seg.kind for seg in doc(text).segments]


# --- fences -------------------------------------------------------------------


def test_a_closing_fence_indented_up_to_three_spaces_closes():
    assert kinds('```py\nx\n   ```\nafter\n') == [CODE, CODE, CODE, PROSE]


def test_a_closer_with_an_info_string_does_not_close():
    d = doc('```py\nx\n```js\ny\n```\nafter\n')
    assert [seg.kind for seg in d.segments] == [CODE] * 5 + [PROSE]
    assert [(start, end) for start, end, *_ in d.fences] == [(1, 5)]


def test_a_backtick_fence_with_a_backtick_in_its_info_is_inline_code():
    text = '```a``` is a span\nnot code\n'
    assert kinds(text) == [PROSE, PROSE]
    assert doc(text).fences == []


def test_a_tilde_fence_may_carry_a_backtick_in_its_info():
    assert kinds('~~~py `x`\ny\n~~~\n') == [CODE, CODE, CODE]


def test_unfenced_lines_follow_the_same_fence_rules():
    text = '```py\nx\n```js\ny\n   ```\nz\n'
    assert list(unfenced_lines(text)) == [(6, 'z')]


def test_a_fence_left_open_runs_to_the_end_of_the_file():
    assert doc('intro\n```py\nx = 1\ny = 2\n').fences == [(2, 4, 'py', 3)]


def test_a_fence_opened_on_the_last_line_is_not_a_block():
    assert doc('intro\n```py\n').fences == []


def test_a_closed_fence_reports_its_language_and_length():
    assert doc('```py\nx\n```\n\n~~~\ny\n~~~\n').fences == [(1, 3, 'py', 3)]


# --- front matter -------------------------------------------------------------


def test_front_matter_is_its_own_unpriced_segment():
    d = doc('---\nstatus: Draft\ntitle: T\n---\n# T\n')
    assert [seg.kind for seg in d.segments] == [FRONT] * 4 + [HEADING]
    assert d.tokens == doc('# T\n').tokens


def test_a_dashed_line_without_a_closer_is_not_front_matter():
    assert kinds('---\nstatus: Draft\n') == [PROSE, PROSE]


def test_a_second_dashed_line_ends_front_matter():
    assert kinds('---\n---\nafter\n') == [FRONT, FRONT, PROSE]


# --- headings -----------------------------------------------------------------


def test_a_heading_keeps_a_trailing_hash_that_is_part_of_its_title():
    titles = [s.title for s in doc('## Learning C#\n\n## Closed ##\n\n## F# ###\n').sections]
    assert titles == ['Learning C#', 'Closed', 'F#']


# --- line breaks --------------------------------------------------------------


def test_only_newlines_break_a_line():
    text = '# T\n\none two\x0cthree\x85four\n\nlast\n'
    d = analyze('docs/x.md', text, counter())
    assert d.lines == 5
    assert [seg.lineno for seg in d.segments][-1] == 5


def test_every_newline_spelling_counts_once():
    assert analyze('x.md', 'a\r\nb\rc\nd', counter()).lines == 4
    assert analyze('x.md', 'a\n', counter()).lines == 1
    assert analyze('x.md', '', counter()).lines == 0


# --- byte order mark ----------------------------------------------------------


def test_a_leading_bom_does_not_hide_front_matter_a_heading_or_a_marker(tmp_path):
    root = repo(tmp_path, {
        'front.md': '﻿---\nstatus: Accepted\n---\n# T\n',
        'head.md': '﻿# Title\n',
        'gen.md': '﻿<!-- docs: exempt - generated -->\n',
    })
    read = lambda name: corpus.read_tracked(root / name)  # noqa: E731
    assert doc_status(read('front.md')) == 'Accepted'
    assert [s.title for s in doc(read('head.md')).sections] == ['Title']
    assert exempt_reason(read('gen.md')) == 'generated'


# --- exempt marker ------------------------------------------------------------


def test_the_exempt_marker_may_follow_blank_lines():
    assert exempt_reason('\n\n<!-- docs: exempt - generated -->\n') == 'generated'


def test_an_exempt_marker_without_a_terminator_still_gives_its_reason():
    assert exempt_reason('<!-- docs: exempt - generated\n') == 'generated'
    assert exempt_reason('<!-- doc-budget: exempt — old spelling -->') == 'old spelling'


def test_a_marker_below_the_first_line_of_content_is_not_one():
    assert exempt_reason('# T\n\n<!-- docs: exempt - late -->\n') is None
    assert exempt_reason('') is None
    assert exempt_reason('\n\n') is None


# --- status -------------------------------------------------------------------


def test_front_matter_status_skips_other_keys_and_unquotes():
    text = '---\ntitle: T\nstatus: "Superseded by 0007"\n---\n# T\n'
    assert doc_status(text) == 'Superseded by 0007'


def test_an_empty_front_matter_status_is_no_status():
    assert doc_status('---\ntitle: T\nstatus: ""\n---\n') is None
    assert doc_status('---\ntitle: T\n---\n') is None


def test_front_matter_status_wins_over_a_body_line():
    assert doc_status('---\nstatus: Accepted\n---\n**Status:** Draft\n') == 'Accepted'


def test_a_body_status_line_is_read_in_either_bold_spelling():
    assert doc_status('# ADR\n\n**Status:** Accepted\n') == 'Accepted'
    assert doc_status('# ADR\n\n**Status**: Proposed\n') == 'Proposed'


def test_an_empty_body_status_is_no_status():
    assert doc_status('# ADR\n\n**Status:**\n') is None


def test_a_status_line_inside_a_fence_is_sample_content():
    assert doc_status('```md\n**Status:** Accepted\n```\n') is None
