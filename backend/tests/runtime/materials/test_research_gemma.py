"""Gemma 各研究階段與持久工作；搜尋 HTTP、來源原頁及模型使用替身。"""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from urllib.parse import parse_qs

import httpx
import pytest

from product_fixtures import closed_loop
from research_fixtures import create_confirmed_research, review_provider
from runtime import research, research_web, semantic_service
from runtime.local_ai_config import configured_lock
from runtime.storage.database import database_session
from runtime.storage.tables import MaterialResearch, ResearchDocument
from test_inference_controlled_exit import blocked_http
from test_research_web import BODY


@pytest.fixture
def gemma_research(monkeypatch):
    control = {"channel": "wikipedia", "overrides": {}, "calls": [], "searches": [], "pages": []}
    original_client = httpx.Client
    lock = configured_lock()
    html = BODY.replace("</article>", "".join(
        f"<h2>Queue condition {i}</h2><p>A queue removes the first inserted item first. "
        f"In case {i}, the consumer must wait for the producer to insert an element before removal. "
        "This condition matters when interpreting the result of concurrent operations.</p>"
        for i in range(90)
    ) + "</article>").encode()

    def respond(request):
        if request.url.path == "/search":
            query = parse_qs(request.content.decode())
            control["searches"].append(query)
            return httpx.Response(200, json={"results": [{
                "url": "https://en.wikipedia.org/wiki/Queue", "title": "A learning example",
                "content": "A queue removes the first inserted item first.", "engines": ["fixture"],
            }]})
        body = json.loads(request.content)
        assert body["model"] == lock["semantic_service"]["model_id"]
        if request.url.path == "/tokenize":
            return httpx.Response(200, json={"count": 100, "max_model_len": 65536})
        assert request.url.path == "/v1/chat/completions"
        assert body["response_format"]["type"] == "json_schema"
        payload = json.loads(body["messages"][0]["content"].split("\nINPUT:\n", 1)[1])
        control["calls"].append(payload)
        result = review_provider("/semantics", {"request": payload})
        if payload["task"] == "plan":
            result["searches"][0]["channel"] = control["channel"]
        result.update(control["overrides"].get(payload["task"], {}))
        return httpx.Response(503 if control.get("fault") == "http" else 200, json={"choices": [{
            "finish_reason": "length" if control.get("fault") == "length" else "stop",
            "message": {"content": "{invalid" if control.get("fault") == "json" else json.dumps(result)},
        }]})

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(respond), **kwargs,
    ))
    monkeypatch.setenv("STUDYDY_SEARXNG_URL", "http://search.fixture")
    monkeypatch.delenv("STUDYDY_SEMANTIC_SCHOLAR_API_KEY", raising=False)
    monkeypatch.setattr(research_web, "_search_cache", OrderedDict())
    monkeypatch.setattr(research_web, "_next_search", 0)

    def page(url, **kwargs):
        control["pages"].append(url)
        return html, url, "text/html"

    monkeypatch.setattr(research.research_sources, "public_page", page)
    monkeypatch.setattr(research.research_sources, "openalex_search", lambda *args: ([{
        "id": "paper", "kind": "paper", "title": "A learning example", "authors": "Fixture",
        "url": "https://example.org/paper", "description": "A queue removes the first inserted item first.",
        "license": "unknown", "eligible": False, "state": "candidate", "reason": "Pending review",
    }], None))
    return control


def advance_until_terminal(owner, identity, dsn):
    for _ in range(100):
        view = research.read(owner, identity, dsn=dsn)
        if view["status"] != "searching":
            return view
        assert research.step(dsn=dsn)
    pytest.fail("research did not finish")


@pytest.mark.parametrize("channel", ["wikipedia", "papers"])
def test_gemma_research_preserves_sources_snapshots_and_selection(closed_loop, gemma_research, channel):
    learner, material, _, _, dsn, _ = closed_loop
    gemma_research["channel"] = channel
    work = create_confirmed_research(learner.learner_id, material.material_id, "佇列", "gemma", dsn=dsn)
    done = advance_until_terminal(learner.learner_id, work["research_id"], dsn)
    assert done["status"] == "selecting", done["error_code"]
    tasks = {call["task"] for call in gemma_research["calls"]}
    assert tasks >= {"plan", "screen", "locate", "read", "follow_up"}
    if channel == "papers":
        assert "source_type" in tasks
    else:
        assert gemma_research["searches"][0]["q"] == ["site:en.wikipedia.org queue tutorial"]
    with database_session(dsn) as db:
        row = db.get(MaterialResearch, work["research_id"])
        candidate = deepcopy(row.candidates[0])
        assert row.search_state["finish_reason"] == "covered"
        assert candidate["eligible"] and candidate["license"] == "CC-BY-SA-4.0"
        assert candidate["review"]["quotes"]
        receipt = candidate["_document_snapshot"]
        snapshot = db.get(ResearchDocument, (row.research_id, bytes.fromhex(receipt["sha256"])))
        assert all(q["quote"] in bytes(snapshot.content).decode() for q in candidate["review"]["quotes"])
    downloads = len(gemma_research["pages"])
    research.action(learner.learner_id, work["research_id"], "acquire", [candidate["id"]], dsn=dsn)
    assert research.step(dsn=dsn)
    with database_session(dsn) as db:
        acquired = db.get(MaterialResearch, work["research_id"]).candidates[0]
        assert acquired["source_id"]
    assert len(gemma_research["pages"]) == downloads


@pytest.mark.parametrize("task,invalid", [
    ("plan", {"summary": {"unexpected": "object"}}),
    ("plan", {"extra": "unrequested"}),
    ("screen", {"items": [{"index": 0, "relevance": "invented", "decision": "read", "topics": [0], "reason": "bad"}]}),
    ("source_type", {"type": "website"}),
    ("locate", {"sections": []}),
    ("read", {"supports": [{"topic": True, "passages": [0]}]}),
    ("read", {"supports": [{"topic": 0, "passages": [99999]}]}),
    ("follow_up", {"coverage": [{"topic": 0, "status": "invented", "reason": "bad", "sources": [0]}]}),
])
def test_invalid_gemma_stage_fails_without_saving_candidate(closed_loop, gemma_research, task, invalid):
    learner, material, _, _, dsn, _ = closed_loop
    gemma_research["channel"] = "papers"
    gemma_research["overrides"][task] = invalid
    work = create_confirmed_research(learner.learner_id, material.material_id, "佇列", "invalid", dsn=dsn)
    done = advance_until_terminal(learner.learner_id, work["research_id"], dsn)
    assert done["status"] == "failed" and done["error_code"] == "RESEARCH_REVIEW_FAILED"
    assert gemma_research["calls"][-1]["task"] == task
    assert done["run_id"] is None
    gemma_research["overrides"].clear()
    research.action(learner.learner_id, work["research_id"], "retry", dsn=dsn)
    assert advance_until_terminal(learner.learner_id, work["research_id"], dsn)["status"] == "selecting"


@pytest.mark.parametrize("fault", ["http", "json", "length"])
def test_gemma_transport_failure_is_saved_and_retryable(closed_loop, gemma_research, fault):
    learner, material, _, _, dsn, _ = closed_loop
    gemma_research["fault"] = fault
    work = create_confirmed_research(learner.learner_id, material.material_id, "佇列", "transport", dsn=dsn)
    assert research.step(dsn=dsn)
    saved = research.read(learner.learner_id, work["research_id"], dsn=dsn)
    assert saved["status"] == "failed" and saved["error_code"] == "RESEARCH_SEARCH_FAILED"
    assert saved["candidates"] == []
    del gemma_research["fault"]
    research.action(learner.learner_id, work["research_id"], "retry", dsn=dsn)
    assert research.step(dsn=dsn)
    with database_session(dsn) as db:
        assert db.get(MaterialResearch, work["research_id"]).search_state["stage"] == "searching"


def test_cancel_gemma_research_wait_keeps_saved_work_cancelled(closed_loop, monkeypatch):
    learner, material, _, _, dsn, _ = closed_loop
    work = create_confirmed_research(learner.learner_id, material.material_id, "佇列", "cancel", dsn=dsn)
    with blocked_http(monkeypatch) as server, ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(research.step, dsn=dsn)
        try:
            assert server.entered.wait(5)
            research.action(learner.learner_id, work["research_id"], "cancel", dsn=dsn)
            assert running.result(timeout=3)
            saved = research.read(learner.learner_id, work["research_id"], dsn=dsn)
            assert saved["status"] == "cancelled" and saved["candidates"] == []
        finally:
            server.release.set()
