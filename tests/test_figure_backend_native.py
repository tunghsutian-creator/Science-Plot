"""Actual generic Veusz compilation with measured pre-clipping text bounds."""
from pathlib import Path
import shutil

import pytest

from sciplot_core.plot_backends.managed import ManagedVeuszCompiler
from test_figure_grammar import example, resolve


@pytest.mark.comprehensive
def test_native_figure_rebuild_and_qa(tmp_path):
    spec, datasets = example()
    ir = resolve(spec, datasets)
    compiler = ManagedVeuszCompiler()
    try:
        result = compiler.compile_ir(ir, tmp_path / "artifacts")
        assert result["publication_qa"]["status"] == "passed"
        assert result["publication_qa"]["native_text_checked"]
        exported = compiler.export_ir(ir, Path(result["document"]), tmp_path / "artifacts/exports")
        assert exported["ready_to_use"]
        pixels = Path(result["preview"]["path"]).read_bytes()
        shutil.rmtree(tmp_path / "artifacts")
        rebuilt = compiler.compile_ir(ir, tmp_path / "artifacts")
        assert rebuilt["scientific_audit"] == result["scientific_audit"]
        assert rebuilt["native_state_hash"] == result["native_state_hash"]
        assert Path(rebuilt["preview"]["path"]).read_bytes() == pixels
    finally:
        compiler.close()


@pytest.mark.comprehensive
def test_all_seven_marks_and_native_clipped_text_rejection(tmp_path):
    from copy import deepcopy
    import subprocess
    from sciplot_core.plot_document import DocumentError

    spec, datasets = example()
    data = datasets['raw:A']['columns']
    data['column:0']['values'] = [1., 5., 9.]
    data['column:2'] = {'label': 'Low', 'unit': 'Pa', 'values': [.5, 4., 14.]}
    data['column:3'] = {'label': 'High', 'unit': 'Pa', 'values': [2., 6., 16.]}
    layer = spec['views'][0]['layers'][0]
    layer['mappings'].update(y_low='column:2', y_high='column:3')
    for kind in ['bar', 'errorbar', 'band', 'rule', 'text']:
        mark = {'id': 'mark:' + kind, 'type': kind, 'style': {}}
        if kind == 'bar':
            mark.update(baseline=0, width_data=.5)
        if kind == 'rule':
            mark.update(orientation='vertical')
        if kind == 'text':
            mark.update(text='X', style={'font_size_pt': 5})
        layer['marks'].append(mark)
    compiler = ManagedVeuszCompiler()
    try:
        ir = resolve(spec, datasets)
        result = compiler.compile_ir(ir, tmp_path / 'all')
        assert result['publication_qa']['native_text_checked']
        assert {mark['type'] for mark in result['scientific_audit']['layers'][0]['marks']} == {
            'line', 'point', 'bar', 'errorbar', 'band', 'rule', 'text'}
        assert compiler.export_ir(ir, Path(result['document']), tmp_path / 'exports')['ready_to_use']
        # Actual native text measurement must fail even though its anchor fits.
        bad = deepcopy(spec)
        bad['annotations'] = [{'id': 'annotation:long', 'space': 'view', 'view_id': 'view:A',
            'x': .5, 'y': .5, 'text': 'W' * 100, 'visible': True, 'style': {}}]
        invalid = resolve(bad, datasets)
        with pytest.raises((ValueError, subprocess.CalledProcessError)):
            compiler.compile_ir(invalid, tmp_path / 'clipped')
        with pytest.raises(DocumentError, match='publication'):
            compiler.export_ir(invalid, tmp_path / 'clipped/document.vsz', tmp_path / 'must-not-export')
        assert not (tmp_path / 'must-not-export').exists()
    finally:
        compiler.close()


@pytest.mark.comprehensive
@pytest.mark.parametrize('horizontal',[False,True], ids=['weighted-vconcat','weighted-hconcat'])
def test_native_shared_scales_weighted_concat_and_figure_legend(tmp_path, horizontal):
    from copy import deepcopy

    spec,data=example()
    second=deepcopy(spec['views'][0])
    second.update(id='view:B',panel_label='B')
    for axis in second['axes']:
        axis['id']+='-B'
    for layer in second['layers']:
        layer['id']+='-B'
        for mark in layer['marks']:
            mark['id']+='-B'
    spec['views'].append(second)
    spec['layout']['width_mm']=240 if horizontal else 100
    spec['composition'].update(kind='hconcat' if horizontal else 'vconcat',rows=1 if horizontal else 2,
        columns=2 if horizontal else 1,row_weights=[1] if horizontal else [1,1.5],
        column_weights=[1,1.5] if horizontal else [1],
        resolve=[{'id':'resolve:AB','views':['view:A','view:B'],'x':'shared','y':'shared','legend':'shared'}])
    spec['composition']['cells'].append({'view_id':'view:B','row':0 if horizontal else 1,
        'column':1 if horizontal else 0,'row_span':1,'column_span':1})
    guide=spec['guides'][0]
    guide.pop('view_id')
    guide.update(scope='figure',location='top',layer_ids=[],order=[],columns=2)
    ir=resolve(spec,data)
    compiler=ManagedVeuszCompiler()
    try:
        result=compiler.compile_ir(ir,tmp_path/'panels')
        assert result['publication_qa']['status']=='passed'
        assert compiler.export_ir(ir,Path(result['document']),tmp_path/'exports')['ready_to_use']
    finally:
        compiler.close()
