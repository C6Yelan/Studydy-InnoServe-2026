"""Native text is the only production Evidence source; original images remain in the PDF."""
import hashlib
from pathlib import Path

import pymupdf
import pytest

import pdf_evidence.material_pipeline as pipeline
from pdf_evidence.ocr_page_evidence import extract_page, build_native_page_evidence, _native_text_blocks, _native_region
from test_material_pipeline_v1 import Client, _settings, _request, _semantic, _pdf


def mixed_document(rotation=0, *, native=True):
    with pymupdf.open() as source:
        p = source.new_page(width=240, height=100)
        p.insert_text((12, 35), 'IMAGE ONLY: char str[10];', fontsize=9)
        png = p.get_pixmap().tobytes('png')
    doc = pymupdf.open(); page = doc.new_page(width=480, height=360)
    if native: page.insert_text((20, 30), 'Reliable native paragraph explains the buffer.', fontsize=12)
    page.insert_image(pymupdf.Rect(30, 100, 400, 260), stream=png)
    page.set_rotation(rotation)
    return doc


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_mixed_page_preserves_native_text_and_pdf_coordinates(rotation):
    with mixed_document(rotation) as doc:
        sha = hashlib.sha256(doc.tobytes()).hexdigest()
        page = extract_page(doc, sha, 1)
        artifact = build_native_page_evidence(page, input_binding={}, produced_at='test')
        assert [b['text'] for b in artifact['evidence_blocks']] == [b['text'] for b in _native_text_blocks(page)]
        assert len(artifact['images']) == 1
        assert all(b['source']=='native_text' for b in artifact['evidence_blocks'])
        for b in artifact['evidence_blocks']:
            assert b['locator']['page']==1
            assert b['locator']['region']==pytest.approx(_native_text_blocks(page)[b['reading_order']]['bbox'])
        assert 'IMAGE ONLY' not in str(artifact['evidence_blocks'])


def test_mixed_document_sends_only_native_text_to_semantics(tmp_path):
    source=tmp_path/'mixed.pdf'
    with mixed_document() as doc: doc.save(source)
    calls=[]
    result=pipeline.analyze_material(_request(source),_settings(tmp_path),client=Client(),semantic_call=_semantic(calls))
    assert result['metrics']['ocr_calls']==0
    assert {e['source'] for e in result['evidence']}=={'native_text'}
    assert 'IMAGE ONLY' not in str(calls)
    assert result['concepts'] and result['initial_learning_path']


def test_pure_scan_is_unsupported_without_any_semantic_request(tmp_path):
    source=tmp_path/'scan.pdf'
    with mixed_document(native=False) as doc: doc.save(source)
    calls=[]
    with pytest.raises(pipeline.MaterialAnalysisError,match='NO_USABLE_EVIDENCE'):
        pipeline.analyze_material(_request(source),_settings(tmp_path),client=Client(),semantic_call=_semantic(calls))
    assert calls==[]


def test_excluded_last_page_is_recorded_and_processing_can_finish(tmp_path):
    source=tmp_path/'partial.pdf';_pdf(source,2)
    with pymupdf.open(source) as doc:
        doc.new_page(); raw=doc.tobytes()
    source.write_bytes(raw)
    calls=[];progress=[]
    result=pipeline.analyze_material(_request(source),_settings(tmp_path),client=Client(),semantic_call=_semantic(calls),progress_callback=lambda *a:progress.append(a))
    assert [p['page'] for p in result['excluded_pages']]==[3]
    assert result['excluded_pages'][0]['page_ref']
    assert all(e['page']!=3 for e in result['evidence'])
    assert 'PAGES_EXCLUDED' in result['status']['reason_codes']
    assert result['status']['processing']=='partial'
    assert progress[-1]==('semantics',3,3)
    assert result['metrics']['ocr_calls']==0


def test_native_identity_and_invalid_coordinates_remain_guarded(tmp_path):
    source=tmp_path/'native.pdf';_pdf(source,1)
    with pymupdf.open(source) as doc: page=extract_page(doc,hashlib.sha256(source.read_bytes()).hexdigest(),1)
    with pytest.raises(ValueError,match='OCR_LOCATOR_INVALID'): _native_region([1000,1000,1100,1100],page)
    page['page_number']=2
    with pytest.raises(ValueError,match='OCR_LOCATOR_INVALID'): build_native_page_evidence(page,input_binding={},produced_at='test')


def test_invalid_image_metadata_does_not_invent_or_remove_native_text(tmp_path):
    source=tmp_path/'native.pdf';_pdf(source,1)
    with pymupdf.open(source) as doc: page=extract_page(doc,hashlib.sha256(source.read_bytes()).hexdigest(),1)
    page['images']=[{'bbox':'invalid'}]
    artifact=build_native_page_evidence(page,input_binding={},produced_at='test')
    assert artifact['images']==[]
    assert artifact['processing']=='partial'
    assert artifact['quality']=='needs_review'
    assert 'OCR_OUTPUT_INVALID' in artifact['reason_codes']
    assert [b['text'] for b in artifact['evidence_blocks']]==[b['text'] for b in _native_text_blocks(page)]


def test_runtime_rejects_removed_image_inference_settings(tmp_path):
    settings = _settings(tmp_path)
    assert pipeline.validate_runtime_lock(settings['runtime_lock'])
    settings['runtime_lock']['ingestion']['vision'] = {'max_tokens': 8192}
    with pytest.raises(pipeline.MaterialAnalysisError, match='RUNTIME_LOCK_INVALID'):
        pipeline.validate_runtime_lock(settings['runtime_lock'])


def test_scan_with_only_native_copyright_footer_is_unsupported(tmp_path, monkeypatch):
    source=tmp_path/'footer-scan.pdf'
    with mixed_document(native=False) as doc:
        doc[0].insert_text((20,350),'Copyright 2026 All rights reserved',fontsize=8)
        doc.save(source)
    monkeypatch.setattr(pipeline,'semantic_client',lambda: pytest.fail('no semantic client for metadata-only text'))
    with pytest.raises(pipeline.MaterialAnalysisError,match='NO_USABLE_EVIDENCE'):
        pipeline.analyze_material(_request(source),_settings(tmp_path))
