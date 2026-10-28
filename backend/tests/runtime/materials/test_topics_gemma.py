"""主題提案的 Gemma HTTP 與持久工作；模型輸出為受控候選。"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json

import httpx
import pytest

from product_fixtures import closed_loop
from runtime import semantic_service, topics
from runtime.local_ai_config import configured_lock
from test_inference_controlled_exit import blocked_http


PLAN = {"title": "佇列入門", "goals": ["理解 FIFO"], "topics": ["佇列：資料移除順序"]}


@pytest.fixture
def gemma_http(monkeypatch):
    calls = []
    response = {"result": deepcopy(PLAN), "finish_reason": "stop", "status": 200}
    lock = configured_lock()

    def respond(request):
        body = json.loads(request.content)
        assert body["model"] == lock["semantic_service"]["model_id"]
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100, "max_model_len": 65536})
        assert request.url.path == "/v1/chat/completions"
        assert body["response_format"]["type"] == "json_schema"
        assert body["max_tokens"] == lock["material_review"]["max_tokens"]
        prompt, payload = body["messages"][0]["content"].split("\nINPUT:\n", 1)
        calls.append({"prompt": prompt, "request": json.loads(payload),
                      "schema": body["response_format"]["json_schema"]["schema"]})
        return httpx.Response(response["status"], json={"choices": [{
            "finish_reason": response["finish_reason"],
            "message": {"content": response.get("raw", json.dumps(response["result"]))},
        }]})

    monkeypatch.setattr(semantic_service, "semantic_client", lambda: httpx.Client(
        transport=httpx.MockTransport(respond), trust_env=False,
    ))
    return calls, response


@pytest.mark.parametrize("supplement", [False, True])
def test_gemma_proposal_preserves_request_context_and_waits_for_approval(
    closed_loop, gemma_http, supplement,
):
    learner, material, _, _, dsn, _ = closed_loop
    calls, _ = gemma_http
    scope = topics.create(learner.learner_id, "我想了解佇列", "gemma-scope",
                          material_id=material.material_id if supplement else None, dsn=dsn)
    assert topics.step(dsn=dsn)
    saved = topics.read(learner.learner_id, scope["topic_id"], dsn=dsn)
    assert saved["status"] == "ready" and saved["proposal"] == PLAN
    assert saved["research_id"] is None
    assert saved["generation_provider"] == (
        f"vllm:{configured_lock()['semantic_service']['model_id']};scope/v6"
    )
    assert calls[0]["prompt"] == topics.SCOPE_PROMPT
    assert calls[0]["request"]["request"] == "我想了解佇列"
    assert calls[0]["schema"]["properties"]["title"]["maxLength"] == (180 if supplement else 40)
    if supplement:
        assert calls[0]["request"]["material_title"]
        assert isinstance(calls[0]["request"]["existing_concepts"], list)
    assert topics.approve(learner.learner_id, scope["topic_id"], saved["version"],
                          saved["proposal"], "gemma-approve", dsn=dsn)["research_id"]


@pytest.mark.parametrize("failure", [
    {"status": 503},
    {"raw": "{invalid"},
    {"finish_reason": "length"},
    {"result": {**PLAN, "title": "字" * 41}},
    {"result": {**PLAN, "topics": []}},
])
def test_gemma_failure_does_not_publish_and_can_retry(closed_loop, gemma_http, failure):
    learner, _, _, _, dsn, _ = closed_loop
    _, response = gemma_http
    response.update(failure)
    scope = topics.create(learner.learner_id, "佇列", "failed-gemma", dsn=dsn)
    assert topics.step(dsn=dsn)
    saved = topics.read(learner.learner_id, scope["topic_id"], dsn=dsn)
    assert saved["status"] == "failed" and saved["error_code"] == "TOPIC_PROVIDER_FAILED"
    assert saved["proposal"] is None and saved["generation_provider"] is None
    response.update(result=deepcopy(PLAN), finish_reason="stop", status=200)
    response.pop("raw", None)
    topics.action(learner.learner_id, scope["topic_id"], "retry", saved["version"], dsn=dsn)
    assert topics.step(dsn=dsn)
    assert topics.read(learner.learner_id, scope["topic_id"], dsn=dsn)["status"] == "ready"


def test_cancelling_gemma_wait_keeps_topic_cancelled(closed_loop, monkeypatch):
    learner, _, _, _, dsn, _ = closed_loop
    scope = topics.create(learner.learner_id, "佇列", "cancel-gemma", dsn=dsn)
    with blocked_http(monkeypatch) as server, ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(topics.step, dsn=dsn)
        try:
            assert server.entered.wait(5)
            topics.action(learner.learner_id, scope["topic_id"], "cancel", scope["version"], dsn=dsn)
            assert running.result(timeout=3)
            saved = topics.read(learner.learner_id, scope["topic_id"], dsn=dsn)
            assert saved["status"] == "cancelled" and saved["proposal"] is None
        finally:
            server.release.set()
