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
    assert card['data-kind'] == 'candidate'
    assert not any('data-edit-request' in attrs for _, attrs in page.elements)


def saved_group(root):
    project = root / 'project'
    figure = {'figure_id': 'ftir-main', 'title': 'Spectrum', 'scope': 'saved',
              'document': str(project / 'studio' / 'document.vsz'), 'document_sha256': 'b' * 64,
              'preview': {'path': str(root / 'preview.png'), 'sha256': 'c' * 64}}
    return {'title': 'Spectra', 'queried_at': '2026-09-09', 'previews': [figure['preview']], 'items': [{
        'id': 'ftir', 'label': 'FTIR', 'status': 'complete', 'figures': [figure],
        'project': str(project), 'current_evidence': evidence(True), 'source_current': True,
    }]}


def test_saved_native_edit_handoff_binds_identity_without_writing_or_requiring_current_exports(tmp_path):
    result = saved_group(tmp_path)
    item = result['items'][0]
    item['current_evidence']['qa']['current'] = False
    item['current_evidence']['delivery']['current'] = None
    page = Page(Path(write_group_gallery(tmp_path, result)).read_text())
    assert sum('data-edit-request' in attrs for _, attrs in page.elements) == 1
    template = next(word for word in page.words if '预期文档 SHA-256：' in word)
    assert item['project'] in template and item['figures'][0]['document'] in template
    assert '图形 ID：ftir-main' in template and 'b' * 64 in template
    assert '请先重新查询' in template and '不代表修改已应用或保存' in template
    assert not any(tag == 'form' for tag, _ in page.elements)
    button = next(attrs for _, attrs in page.elements if 'data-copy-edit' in attrs)
    assert 'disabled' in button
    # The presentation trusts owner-returned snapshots; it must not inspect or create native files.
    assert not Path(item['project']).exists()


@pytest.mark.parametrize('change', [
    'candidate', 'unknown_scope', 'missing_figure', 'missing_hash', 'invalid_hash',
    'missing_project', 'relative_project', 'outside_document', 'parent_path', 'not_native',
    'missing_preview', 'stale_preview', 'source_changed', 'source_evidence_changed',
    'blocked', 'task_blocked',
])
def test_unbound_or_stale_group_figures_offer_no_edit_handoff(tmp_path, change):
    result = saved_group(tmp_path)
    item = result['items'][0]
    figure = item['figures'][0]
    if change == 'candidate':
        figure['scope'] = 'candidate'
    elif change == 'unknown_scope':
        figure.pop('scope')
    elif change == 'missing_figure':
        figure.pop('figure_id')
    elif change == 'missing_hash':
        figure.pop('document_sha256')
    elif change == 'invalid_hash':
        figure['document_sha256'] = 'old'
    elif change == 'missing_project':
        item.pop('project')
    elif change == 'relative_project':
        item['project'] = 'project'
    elif change == 'outside_document':
        figure['document'] = str(tmp_path / 'other.vsz')
    elif change == 'parent_path':
        figure['document'] = str(Path(item['project']) / '..' / 'other.vsz')
    elif change == 'not_native':
        figure['document'] = str(Path(item['project']) / 'figure.png')
    elif change == 'missing_preview':
        figure.pop('preview')
    elif change == 'stale_preview':
        figure['preview_error'] = '待审预览与当前文档不一致，请重新查询。'
    elif change == 'source_changed':
        item['source_current'] = False
    elif change == 'source_evidence_changed':
        item['current_evidence']['source']['current'] = False
    elif change == 'blocked':
        item['status'] = 'blocked'
    elif change == 'task_blocked':
        item['task'] = {'blocker': {'message': '当前任务受阻'}}
    page = Page(Path(write_group_gallery(tmp_path, result)).read_text())
    assert not any('data-edit-request' in attrs or 'data-copy-edit' in attrs for _, attrs in page.elements)
    assert not any('预期文档 SHA-256：' in word for word in page.words)


def test_group_edit_template_and_workspace_labels_escape_original_identity(tmp_path):
    result = saved_group(tmp_path)
    attack = '</textarea><img src=x onerror=alert(1)><script>alert(1)</script>'
    item = result['items'][0]
    item['label'] = attack
    figure = item['figures'][0]
    figure.update(title=attack, figure_id=attack,
                  document=str(Path(item['project']) / (attack + '.vsz')))
    page = Page(Path(write_group_gallery(tmp_path, result)).read_text())
    card = next(attrs for tag, attrs in page.elements if tag == 'article')
    assert card['data-title'] == attack and card['data-subtitle'] == attack
    assert card['data-kind'] == 'saved'
    assert not any('onerror' in attrs or attrs.get('src') == 'x' for _, attrs in page.elements)
    assert [attrs for tag, attrs in page.elements if tag == 'script'] == [{'type': 'module'}]
    assert any('图形 ID：' + attack in word for word in page.words)


def test_group_workspace_ids_follow_native_identity_across_reordering(tmp_path):
    result = saved_group(tmp_path)
    figures = result['items'][0]['figures']
    figures.append({**figures[0], 'figure_id': 'ftir-second', 'title': 'Second'})

    def identities():
        page = Page(Path(write_group_gallery(tmp_path, result)).read_text())
        return {attrs['data-title']: attrs['id'] for tag, attrs in page.elements if tag == 'article'}

    before = identities()
    figures.reverse()
    assert identities() == before
    assert len(set(before.values())) == 2


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
    # Entry-level flags must not override an unavailable or historical result.
    page = Page(Path(write_comparison_gallery(tmp_path, result)).read_text())
    assert not any(attrs.get('data-copy', '').startswith('select-') for _, attrs in page.elements)
    assert not any('预期比较标识：' in word for word in page.words)
    if selected:
        assert '当时采用' in page.words


@pytest.mark.parametrize('history', ['complete', 'selection', 'stale'])
def test_historical_comparison_rejects_contradictory_selectable_flags(tmp_path, history):
    result = comparison(tmp_path)
    if history == 'complete':
        result['status'] = 'complete'
    elif history == 'selection':
        result['selection'] = {'candidate_id': 'a'}
    else:
        result['baseline_current'] = False
    page = Page(Path(write_comparison_gallery(tmp_path, result)).read_text())
    assert not any(attrs.get('data-copy', '').startswith('select-') for _, attrs in page.elements)
    assert not any('预期比较标识：' in word for word in page.words)
    assert all(attrs['data-kind'] == 'history' for tag, attrs in page.elements if tag == 'article')


def test_comparison_workspace_preserves_entry_scope_errors_and_selection_eligibility(tmp_path):
    result = comparison(tmp_path)
    result['candidates'][0].update(status='blocked', selectable=False, error='当前候选审计失败')
    page = Page(Path(write_comparison_gallery(tmp_path, result)).read_text())
    cards = [attrs for tag, attrs in page.elements if tag == 'article']
    assert cards[0]['data-kind'] == 'baseline' and cards[0]['data-attention'] == 'false'
    assert cards[1]['data-kind'] == 'candidate' and cards[1]['data-attention'] == 'true'
    assert all('data-review-card' in card and card['data-title'] in card['data-search'] for card in cards)
    assert len({card['id'] for card in cards}) == 2
    assert '当前候选审计失败' in page.words
    assert not any('data-edit-request' in attrs for _, attrs in page.elements)
    notes = [word for word in page.words if '预期比较标识：' in word]
    assert len(notes) == 1 and '候选 ID：baseline' in notes[0]


def test_stale_comparison_exposes_one_shared_current_state_despite_passed_candidate_audit(tmp_path):
    result = comparison(tmp_path)
    result.update(baseline_current=False, can_select=False, status='blocked', project='/current/project',
                  current_error='当前文件无法读取', blocker={'message': '比较基线已经变化'},
                  current_figure={'figure_id': 'spectrum-now', 'document': '/current/project/document.vsz',
                                  'document_sha256': 'd' * 64}, current_evidence=evidence(False))
    result['current_evidence']['delivery']['path'] = '/current/delivery'
    result['candidates'][0].update(change_count=2, changes=[], scientific_audit_status='passed',
                                  review_path=str(tmp_path / 'review.json'))
    html = Path(write_comparison_gallery(tmp_path, result)).read_text()
    page = Page(html)
    sections = [attrs for _, attrs in page.elements if 'data-comparison-state' in attrs]
    assert len(sections) == 1 and sections[0]['aria-label'] == '当前项目与比较状态'
    # Shared state remains outside individual historical cards and can be cloned intact.
    section_start = html.index('data-comparison-state')
    section_end = html.index('</section>', section_start)
    assert section_end < html.index('<article')
    shared = Page(html[section_start:section_end])
    assert '当前文件无法读取' in shared.words and '比较基线已经变化' in shared.words
    assert any('当前项目与比较时的基线已不同' in word and '不能据此应用候选' in word for word in shared.words)
    assert any('数值审计描述比较时的快照' in word for word in shared.words)
    for identity in ('/current/project', 'spectrum-now', '/current/project/document.vsz', 'd' * 64, '/current/delivery'):
        assert identity in shared.words and page.words.count(identity) == 1
    assert '已变化 / 需核查' in shared.words and '需更新 / 核查' in shared.words
    assert any('数值审计通过' in word for word in page.words)
    assert not any(attrs.get('data-copy', '').startswith('select-') for _, attrs in page.elements)


@pytest.mark.parametrize('baseline,expected', [
    (True, '比较基线与当前项目匹配（查询时）。'),
    (None, '尚未确认比较基线是否仍匹配当前项目，请重新查询。'),
])
def test_comparison_shared_state_distinguishes_current_and_unknown_baseline(tmp_path, baseline, expected):
    result = comparison(tmp_path)
    result['baseline_current'] = baseline
    page = Page(Path(write_comparison_gallery(tmp_path, result)).read_text())
    assert expected in page.words
    assert not any('当前项目与比较时的基线已不同' in word for word in page.words)


def test_comparison_shared_error_and_current_identity_are_escaped(tmp_path):
    result = comparison(tmp_path)
    attack = '</textarea><img src=x onerror=alert(1)><script>alert(1)</script>'
    result.update(current_error=attack, project='/project/' + attack,
                  current_figure={'figure_id': attack, 'document': '/project/' + attack + '.vsz',
                                  'document_sha256': attack})
    page = Page(Path(write_comparison_gallery(tmp_path, result)).read_text())
    assert not any('onerror' in attrs or attrs.get('src') == 'x' for _, attrs in page.elements)
    assert [attrs for tag, attrs in page.elements if tag == 'script'] == [{'type': 'module'}]
    assert attack in page.words and '/project/' + attack + '.vsz' in page.words


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
