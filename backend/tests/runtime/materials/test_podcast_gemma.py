"""講稿 worker 走完整 Gemma HTTP 契約，再保存已核對來源的講稿。"""

from copy import deepcopy
import json

import httpx
import pytest

from product_fixtures import closed_loop
from runtime import podcasts, podcast_worker, semantic_service
from runtime.local_ai_config import configured_lock
from runtime.storage.database import database_session
from runtime.storage.tables import Podcast
from test_podcast_provider import verdict


@pytest.mark.parametrize('failure', [None, 'script', 'review', 'title', 'foreign_source'])
def test_gemma_script_review_title_and_persistence(closed_loop, monkeypatch, failure):
    # 本例驗證等待耗盡後的發布／失敗流程；退避與等待上限由 semantic_service 單元測試驗證。
    monkeypatch.setattr(semantic_service, 'SERVICE_WAIT_SECONDS', 0)
    owner, material, _, document, dsn, _ = closed_loop
    saved = podcasts.create_podcast(owner.learner_id, material.material_id, document['revision'],
        '合成講稿', [document['concepts'][0]['concept_id']], 'gemma-script', delivery='solo', dsn=dsn)
    with database_session(dsn) as db:
        claim = deepcopy(db.get(Podcast, saved['podcast_id']).episodes[0]['claims'][0])
    lock = configured_lock()
    stages = []

    def respond(request):
        body = json.loads(request.content)
        assert body['model'] == lock['semantic_service']['model_id']
        if request.url.path == '/tokenize':
            return httpx.Response(200, json={'count': 256, 'max_model_len': lock['semantic_service']['max_model_len']})
        assert request.url.path == '/v1/chat/completions'
        schema = body['response_format']['json_schema']['schema']
        prompt, _ = body['messages'][0]['content'].rsplit('\nINPUT:\n', 1)
        if 'checks' in schema['properties']:
            stage = 'review'
            result = verdict(json.loads(prompt.split('\nINPUT:\n', 1)[1]))
        elif set(schema['properties']) == {'title'}:
            stage, result = 'title', {'title': '堆疊的規則'}
        else:
            stage = 'script'
            assert set(schema['properties']) == {'segments'}
            result = {'segments': [{'title': claim['label'], 'turns': [{'speaker': 'host',
                'text': claim['text'], 'source_indices': [999 if failure == 'foreign_source' else 0]}]}]}
        stages.append(stage)
        if failure == stage:
            return httpx.Response(503, json={'error': 'synthetic unavailable'})
        return httpx.Response(200, json={'choices': [{'finish_reason': 'stop',
            'message': {'content': json.dumps(result, ensure_ascii=False)}}]})

    monkeypatch.setattr(semantic_service, 'semantic_client', lambda **kwargs: httpx.Client(transport=httpx.MockTransport(respond)))
    podcast_worker.step(dsn=dsn)
    view = podcasts.read_podcast(owner.learner_id, saved['podcast_id'], dsn=dsn)
    episode = view['episodes'][0]
    if failure in {'script', 'review', 'foreign_source'}:
        assert view['status'] == 'failed' and episode['script'] is None
        assert view['error_code'] == ('PODCAST_SCRIPT_INVALID' if failure == 'foreign_source' else 'SEMANTIC_SERVICE_UNAVAILABLE')
        return
    # 講稿完成後等待配音，音訊完成才算完成一集。
    assert view['status'] == 'pending' and view['completed_episodes'] == 0
    assert stages == ['script', 'review', 'title']
    script = episode['script']
    assert script['provider'] == f"vllm:{lock['semantic_service']['model_id']};source-script/v17"
    turn = script['segments'][0]['turns'][0]
    assert turn['text'] == claim['text']
    assert turn['parts'][0]['source_refs'] == [{'source_index': 0,
        'evidence_ids': [e['evidence_id'] for e in claim['evidence']]}]
    if failure is None:
        assert episode['title'] == '堆疊的規則'
    else:
        assert episode.get('title') is None
    assert podcasts.claim_step(dsn=dsn)['episode']['script'] == script
