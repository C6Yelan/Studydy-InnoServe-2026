"""驗證 native 優先、區域來源、Gemma request 與明確失敗行為。"""
import hashlib
import json
from pathlib import Path

import httpx
import pymupdf
import pytest

from pdf_evidence.ocr_page_evidence import (
    extract_page, route_page, vision_regions, render_vision_region,
    build_page_evidence, build_native_page_evidence,
)
from runtime.semantic_service import request_vision, SemanticServiceError
from pdf_evidence.material_pipeline import validate_runtime_lock, MaterialAnalysisError


def lock():
    return json.loads((Path(__file__).parents[2] / 'local_ai/runtime-lock.json').read_text())


def mixed_page(rotation=0):
    image_doc = pymupdf.open()
    ip = image_doc.new_page(width=240, height=100)
    ip.insert_text((12, 35), 'char str[10]; if (str[0] == 0) return;', fontsize=9)
    png = ip.get_pixmap().tobytes('png')
    doc = pymupdf.open(); p = doc.new_page(width=480, height=360)
    p.insert_text((20, 30), 'Reliable native title and paragraph.', fontsize=12)
    p.insert_image(pymupdf.Rect(30, 100, 400, 260), stream=png)
    p.set_rotation(rotation)
    return doc


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_region_locator_and_native_text_survive_vision(rotation):
    with mixed_page(rotation) as doc:
        page = extract_page(doc, hashlib.sha256(doc.tobytes()).hexdigest(), 1)
        assert route_page(page) == 'OCR_needed'
        regions = vision_regions(page); assert len(regions) == 1
        png, bbox = render_vision_region(page, regions[0])
        assert png.startswith(b'\x89PNG')
        artifact = build_page_evidence(page, [{'type':'text', 'text':'char str[10];', 'bbox':bbox}], input_binding={'runtime_lock_sha256':'test'}, produced_at='test')
        native = [x for x in artifact['evidence_blocks'] if x['source']=='native_text']
        vision = [x for x in artifact['evidence_blocks'] if x['source']=='vision']
        assert len(native)==len(vision)==1
        assert native[0]['text']=='Reliable native title and paragraph.'
        assert vision[0]['locator']['page']==1
        assert vision[0]['locator']['region']==pytest.approx(regions[0], abs=0.5)
        assert artifact['quality']=='needs_review'


def test_scan_uses_full_page_but_native_page_needs_no_vision():
    with pymupdf.open() as doc:
        p=doc.new_page(); p.insert_text((20,30),'Reliable source content about arrays and strings.')
        page=extract_page(doc,'a'*64,1)
        assert route_page(page)=='native_sufficient'
        assert vision_regions(page)==[]
        a=build_native_page_evidence(page,input_binding={},produced_at='test')
        assert {x['source'] for x in a['evidence_blocks']}=={'native_text'}
        p=doc.new_page();page=extract_page(doc,'a'*64,2)
        assert vision_regions(page)==[page['geometry']['unrotated_points']]
        a=build_page_evidence(page,[{'type':'text','text':'Scanned source text','bbox':[0,0,1000,1000]}],input_binding={},produced_at='test')
        assert {x['source'] for x in a['evidence_blocks']}=={'vision'}
        assert a['evidence_blocks'][0]['locator']['page']==2


@pytest.mark.parametrize('finish', ['stop','length'])
def test_vision_wire_settings_and_truncation(finish):
    calls=[]
    def server(req):
        body=json.loads(req.content);calls.append(body)
        assert body['messages'][0]['content'][0]['type']=='image_url'
        assert body['messages'][0]['content'][1]['type']=='text'
        assert body['chat_template_kwargs']=={'enable_thinking':False}
        assert body['mm_processor_kwargs']=={'max_soft_tokens':1120}
        if req.url.path=='/tokenize':return httpx.Response(200,json={'count':1253,'max_model_len':32768})
        assert {k:body[k] for k in ['temperature','top_p','top_k','max_tokens']}=={'temperature':1.0,'top_p':.95,'top_k':64,'max_tokens':8192}
        assert 'response_format' not in body
        return httpx.Response(200,json={'choices':[{'finish_reason':finish,'message':{'content':r"if (str1[i] == '\0') break;"}}]})
    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        if finish=='length':
            with pytest.raises(SemanticServiceError,match='VISION_OUTPUT_TRUNCATED'):request_vision(client,runtime_lock=lock(),png_bytes=b'png')
        else: assert '\\0' in request_vision(client,runtime_lock=lock(),png_bytes=b'png')
    assert len(calls)==2


def test_vision_bad_response_and_offline_never_fallback():
    for response in [httpx.Response(503,json={'detail':'unavailable'}),httpx.Response(200,json={'count':1,'max_model_len':32768})]:
        with httpx.Client(transport=httpx.MockTransport(lambda _:response)) as client:
            with pytest.raises(SemanticServiceError):request_vision(client,runtime_lock=lock(),png_bytes=b'png')


def test_runtime_rejects_unqualified_vision_parameters():
    settings=lock();settings['ingestion']['vision']['generation']['temperature']=0
    with pytest.raises(MaterialAnalysisError):validate_runtime_lock(settings)


def test_reliable_native_overlay_is_removed_from_vision_pixels():
    """送給 Vision 的裁圖不能要求它重新抄寫已有的可靠文字層。"""
    with mixed_page() as doc:
        doc[0].insert_text((55, 150), 'Native overlay', fontsize=12)
        bounds=doc[0].search_for('Native overlay')[0]
        page=extract_page(doc,'b'*64,1)
        png,bbox=render_vision_region(page,vision_regions(page)[0])
        rendered=pymupdf.Pixmap(page['png_bytes']);cropped=pymupdf.Pixmap(png)
        scale=page['render']['width']/doc[0].rect.width
        area=(bounds * scale).irect
        x0=round(bbox[0]*rendered.width/1000);y0=round(bbox[1]*rendered.height/1000)
        original=[];masked=[]
        for y in range(area.y0+1,area.y1-1):
            for x in range(area.x0+1,area.x1-1):
                original.extend(rendered.pixel(x,y));masked.extend(cropped.pixel(x-x0,y-y0))
        assert min(original)<100
        assert min(masked)==255


def test_scan_pipeline_publishes_reviewable_vision_provenance(tmp_path, monkeypatch):
    import pdf_evidence.material_pipeline as pipeline
    from knowledge_map.structure import validate_knowledge_structure
    source=tmp_path/'scan.pdf'
    with pymupdf.open() as doc:
        doc.new_page();doc.save(source)
    calls=[]
    def vision(*args,**kwargs):
        calls.append(kwargs['png_bytes'])
        return 'A stack removes the most recently added item first.'
    monkeypatch.setattr(pipeline,'request_vision',vision)
    def semantic(_client,**kwargs):
        request=kwargs['request'];row=request['sections'][0]['evidence'][0]
        assert request['evidence_sources'][str(row[0])]=='vision'
        return {'concepts':[{'k':'stack','l':'Stack','a':[],'c':[{'m':None,'s':[row[0]]}]}],'relations':[]}
    def server(req):return httpx.Response(200,json={'count':100,'max_model_len':32768})
    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        document=pipeline.analyze_material({'media_type':'application/pdf','source_path':str(source),'expected_source_sha256':hashlib.sha256(source.read_bytes()).hexdigest()},
            {'private_runtime_root':str(tmp_path/'runtime'),'runtime_lock':lock()},client=client,semantic_call=semantic)
    assert len(calls)==1 and document['metrics']['ocr_calls']==1
    assert {x['source'] for x in document['evidence']}=={'vision'}
    assert document['status']['quality']=='needs_review'
    assert 'VISION_DERIVED_EVIDENCE' in document['status']['reason_codes']
    assert validate_knowledge_structure(document)
