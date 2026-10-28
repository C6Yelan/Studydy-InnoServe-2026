"""Gemma HTTP 契約、真 DB 檢索與問答保存；模型回應為受控候選。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

import httpx
import pytest

from product_fixtures import closed_loop
from qa_fixtures import grounded_answer, qa_model
from runtime import material_qa, semantic_service, voice
from runtime.local_ai_config import configured_lock
from runtime.storage.database import database_session
from runtime.storage.tables import VoiceConversation
from test_inference_controlled_exit import blocked_http
from test_podcast_process import provider_server, provider as speech_provider
from test_voice import setup


@pytest.fixture
def gemma_http(monkeypatch):
    calls, replacements = [], []
    model = configured_lock()["semantic_service"]

    def respond(request):
        body = json.loads(request.content)
        assert body["model"] == model["model_id"]
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100, "max_model_len": model["max_model_len"]})
        assert request.url.path == "/v1/chat/completions"
        assert body["response_format"]["type"] == "json_schema"
        prompt, payload = body["messages"][0]["content"].split("\nINPUT:\n", 1)
        schema = body["response_format"]["json_schema"]["schema"]
        call = {"prompt": prompt, "request": json.loads(payload), "schema": schema}
        calls.append(call)
        if schema["required"] == ["summary"]:
            result = {"summary": "使用者曾詢問條件 0 至 6，討論堆疊的後進先出規則。"}
        elif replacements and "sources" in call["request"] and "segments" not in call["request"]:
            result = replacements.pop(0)
        else:
            result = qa_model(call, "堆疊採用後進先出。")
        if "speech_terms" in schema["properties"]:
            result.setdefault("speech_terms", ["堆疊", "後進先出"])
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(result, ensure_ascii=False)}}]})

    monkeypatch.setattr(semantic_service, "semantic_client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(respond)))
    return calls, replacements


@pytest.mark.parametrize("input_kind", ["text", "typed_voice", "recording"])
def test_gemma_answers_keep_verified_sources_for_each_input(closed_loop, gemma_http, monkeypatch, request, input_kind):
    owner, _, conversation, dsn = setup(closed_loop)
    question = "Stack LIFO"
    if input_kind == "recording":
        request.getfixturevalue("provider_server")
        monkeypatch.setattr(speech_provider, "transcribe", lambda body, **kwargs: {
            "text": question, "provider": "synthetic-asr", "hints": body["hints"],
            "segments": [{"text": question, "start": 0, "end": 1, "avg_logprob": -.2, "no_speech_prob": .01}],
        })
        turn = voice.add_turn(owner, conversation, input_kind, recording=b"synthetic recording", dsn=dsn)
        assert voice.step(dsn=dsn)
        assert voice.read(owner, conversation, dsn=dsn)["turns"][0]["status"] == "pending"
    else:
        turn = voice.add_turn(owner, conversation, input_kind, question, mode="voice" if input_kind == "typed_voice" else "text", dsn=dsn)
    assert voice.step(dsn=dsn)
    view = voice.read(owner, conversation, dsn=dsn)
    saved = view["turns"][0]
    assert saved["turn_id"] == turn["turn_id"] and saved["status"] == "ready"
    assert saved["answer"]["text"] == "堆疊採用後進先出。" and saved["answer"]["supported"]
    assert saved["answer"]["provider"] == "vllm:" + configured_lock()["semantic_service"]["model_id"]
    assert all(reference["page"] >= 1 and reference["evidence_id"] for citation in saved["answer"]["citations"] for reference in citation["evidence"])
    calls, _ = gemma_http
    answer_call = next(call for call in calls if "sources" in call["request"] and "segments" not in call["request"])
    review_call = next(call for call in calls if "segments" in call["request"])
    assert answer_call["prompt"] == material_qa.ANSWER_PROMPT
    assert review_call["prompt"] == material_qa.REVIEW_PROMPT
    if input_kind == "recording":
        plan = next(call for call in calls if "interpreted_question" in call["schema"]["properties"])
        assert plan["request"]["recognition"]["hints"]
        assert saved["question"] == question


def test_gemma_compresses_and_reuses_persisted_conversation_memory(closed_loop, gemma_http):
    owner, _, conversation, dsn = setup(closed_loop)
    for index in range(7):
        voice.add_turn(owner, conversation, f"history-{index}", f"條件 {index}", dsn=dsn)
        state = voice.claim(dsn=dsn)
        voice.finish(state, grounded_answer(state, dsn, "舊的完整教材說明。" * 70), dsn=dsn)
    voice.add_turn(owner, conversation, "summarize", "沿用早期條件", dsn=dsn)
    assert voice.step(dsn=dsn)
    with database_session(dsn) as db:
        memory = deepcopy(db.get(VoiceConversation, conversation).memory)
    calls, _ = gemma_http
    assert memory and any(call["schema"]["required"] == ["summary"] for call in calls)
    calls.clear()
    voice.add_turn(owner, conversation, "followup", "繼續說明堆疊", dsn=dsn)
    assert voice.step(dsn=dsn)
    assert calls[0]["request"]["history"]["summary"] == memory["summary"]
    assert voice.read(owner, conversation, dsn=dsn)["turns"][-1]["status"] == "ready"


def test_gemma_candidate_with_foreign_citation_is_not_published(closed_loop, gemma_http):
    owner, _, conversation, dsn = setup(closed_loop)
    _, replacements = gemma_http
    replacements.append({"segments": [{"text": "無法回查的候選。", "citations": [999]}], "queries": [], "missing": ""})
    voice.add_turn(owner, conversation, "bad-citation", "Stack LIFO", dsn=dsn)
    assert voice.step(dsn=dsn)
    saved = voice.read(owner, conversation, dsn=dsn)["turns"][0]
    assert saved["status"] == "failed" and saved["error_code"] == "VOICE_ANSWER_INVALID"
    assert saved["answer"] is None


def test_cancelling_gemma_http_wait_keeps_turn_cancelled(closed_loop, monkeypatch):
    owner, _, conversation, dsn = setup(closed_loop)
    turn = voice.add_turn(owner, conversation, "cancel-http", "Stack LIFO", dsn=dsn)
    with blocked_http(monkeypatch) as server, ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(voice.step, dsn=dsn)
        try:
            assert server.entered.wait(5)
            voice.action(owner, conversation, turn["turn_id"], "cancel", dsn=dsn)
            assert running.result(timeout=3)
            saved = voice.read(owner, conversation, dsn=dsn)["turns"][0]
            assert saved["status"] == "cancelled" and saved["answer"] is None
            next_turn = voice.add_turn(owner, conversation, "next-http", "Stack LIFO", dsn=dsn)
            assert voice.claim(dsn=dsn)["turn_id"] == next_turn["turn_id"]
        finally:
            server.release.set()
