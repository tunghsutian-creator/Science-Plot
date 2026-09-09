from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

import pytest

from sciplot_core.task_comparison_gallery import write_comparison_gallery
from sciplot_core.task_group_gallery import write_group_gallery


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.words = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def handle_data(self, value):
        self.words.append(value)


def evidence(current):
    return {key: {'current': current} for key in ('source', 'qa', 'delivery')}


@pytest.mark.parametrize('current,attention,expected', [
    (True, 'false', '匹配当前保存图'),
    (False, 'true', '需更新 / 核查'),
    (None, 'true', '暂无当前证据'),
])
def test_completed_task_does_not_override_current_export_evidence(tmp_path, current, attention, expected):
    result = {'title': 'Spectra', 'queried_at': '2026-09-09', 'previews': [], 'items': [{
        'id': 'ftir', 'label': 'FTIR', 'status': 'complete', 'figures': [],
        'current_evidence': evidence(current),
    }]}
    page = Page(Path(write_group_gallery(tmp_path, result)).read_text())
    card = next(attrs for tag, attrs in page.elements if tag == 'article')
    assert card['data-attention'] == attention
    assert expected in page.words
    if current is not True:
        assert '与当前版本一致' not in page.words
        assert '未变化' not in page.words


def test_pending_candidate_remains_unsaved_even_when_saved_delivery_is_current(tmp_path):
    figure = {'title': 'Spectrum', 'scope': 'candidate', 'samples': [{'sample': 'E0'}, {'sample': 'E2'}]}
    result = {'title': 'Spectra', 'queried_at': '2026-09-09', 'previews': [], 'items': [{
        'id': 'ftir', 'label': 'FTIR', 'status': 'needs_review', 'figures': [figure],
        'current_evidence': evidence(True), 'source_current': False,
    }]}
    page = Page(Path(write_group_gallery(tmp_path, result)).read_text())
    assert '待审候选 · 未保存' in page.words and '当前已保存项目 · 查询时状态' in page.words
    assert '已变化 / 需核查' in page.words and '未变化' not in page.words
    card = next(attrs for tag, attrs in page.elements if tag == 'article')
    assert 'E0 E2' in card['data-search'] and card['data-attention'] == 'true'


def test_project_snapshot_path_is_not_presented_as_original_input(tmp_path):
    current = evidence(True)
    current['source']['input'] = {'path': '/project/source'}
    result = {'title': 'Saved edit', 'queried_at': '2026-09-09', 'previews': [], 'items': [{
        'id': 'edit', 'label': 'Edit', 'status': 'needs_review', 'figures': [], 'current_evidence': current,
    }]}
    page = Page(Path(write_group_gallery(tmp_path, result)).read_text())
    assert '项目数据路径' in page.words and '原始数据路径' not in page.words


def comparison(root):
    return {'title': 'Alternatives', 'queried_at': '2026-09-09', 'status': 'needs_selection',
            'comparison_dir': str(root), 'comparison_id': 'a' * 64, 'can_select': True,
            'current_evidence': evidence(None),
            'baseline': {'id': 'baseline', 'label': 'Original', 'status': 'ready', 'selectable': True},
            'candidates': [{'id': 'a', 'label': 'A', 'status': 'ready', 'selectable': True}]}


def test_choice_handoff_contains_exact_identity_and_requires_reinspection(tmp_path):
    result = comparison(tmp_path)
    page = Page(Path(write_comparison_gallery(tmp_path, result)).read_text())
    notes = [word for word in page.words if '预期比较标识：' in word]
    assert len(notes) == 2
    assert all(str(tmp_path) in note and 'a' * 64 in note and '请重新检查' in note for note in notes)
    assert '候选 ID：baseline' in notes[0] and '候选 ID：a' in notes[1]
    assert not any(tag == 'form' for tag, _ in page.elements)


@pytest.mark.parametrize('selected', [False, True])
def test_unavailable_and_historical_comparisons_offer_no_actionable_choice(tmp_path, selected):
    result = comparison(tmp_path)
    result.update(can_select=False, status='complete' if selected else 'blocked')
    if selected:
        result['selection'] = {'candidate_id': 'a'}
    else:
        result['blocker'] = {'message': '项目已变化'}
    for entry in [result['baseline'], *result['candidates']]:
        entry['selectable'] = False
    page = Page(Path(write_comparison_gallery(tmp_path, result)).read_text())
    assert not any(attrs.get('data-copy', '').startswith('select-') for _, attrs in page.elements)
    assert not any('预期比较标识：' in word for word in page.words)
    if selected:
        assert '当时采用' in page.words


def test_labels_paths_and_choice_notes_cannot_inject_markup(tmp_path):
    result = comparison(tmp_path)
    attack = '</textarea><img src=x onerror=alert(1)><script>alert(1)</script>'
    result['title'] = attack
    result['candidates'][0]['label'] = attack
    result['current_evidence']['delivery']['path'] = '/data/' + attack
    page = Page(Path(write_comparison_gallery(tmp_path, result)).read_text())
    assert not any('onerror' in attrs for _, attrs in page.elements)
    assert not any(attrs.get('src') == 'x' for _, attrs in page.elements)
    scripts = [attrs for tag, attrs in page.elements if tag == 'script']
    assert scripts == [{'type': 'module'}]
    assert any('候选 ID：a' in word and attack in word for word in page.words)


def test_failed_audit_is_never_displayed_as_passed(tmp_path):
    result = comparison(tmp_path)
    result['candidates'][0].update(change_count=1, changes=[], scientific_audit_status='failed',
                                  review_path=str(tmp_path / 'review.json'))
    page = Page(Path(write_comparison_gallery(tmp_path, result)).read_text())
    assert any('数值审计未确认' in word for word in page.words)
    assert not any('数值审计通过' in word for word in page.words)


def test_preview_cannot_link_outside_review_root(tmp_path):
    result = comparison(tmp_path)
    result['baseline']['preview'] = {'path': str(tmp_path.parent / 'private.png')}
    with pytest.raises(ValueError):
        write_comparison_gallery(tmp_path, result)
    assert not (tmp_path / 'overview.html').exists()
