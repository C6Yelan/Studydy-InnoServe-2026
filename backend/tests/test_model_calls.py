"""後端標籤、跨步候選及終態私人紀錄；只有合成輸入。"""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import json
import os
import stat

import pytest

from runtime import model_calls, provider_http
from runtime.local_ai_config import _runtime_lock
from runtime.semantic_service import SemanticServiceError, request_semantics


@pytest.fixture(autouse=True)
def private_state(monkeypatch, tmp_path):
    (tmp_path / "artifacts").mkdir()
    monkeypatch.setenv("STUDYDY_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    model_calls._pending.clear()
    yield
    model_calls._pending.clear()


def start(feature="research", **kwargs):
    return model_calls.start(feature, "work", "attempt", "material", "learner", **kwargs)


def test_cross_step_candidates_survive_until_failed_terminal(tmp_path, monkeypatch, caplog):
    first = start()
    model_calls.capture({"private": "私密候選"})
    model_calls.rejected("私密退回理由")
    model_calls.close(first)
    assert not list((tmp_path / "artifacts/failures").glob("*.json"))
    second = start()
    assert second.candidates == first.candidates
    model_calls.completed("failed", "RESEARCH_SEARCH_FAILED")
    model_calls.close(second)
    path, = (tmp_path / "artifacts/failures").glob("*.json")
    value = json.loads(path.read_text())
    assert value["candidates"][0]["candidate"] == {"private": "私密候選"}
    assert value["rejections"] == ["私密退回理由"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert "私密" not in caplog.text
    assert not model_calls._pending


@pytest.mark.parametrize("outcome", ["succeeded", "cancelled"])
@pytest.mark.parametrize("archive", [None, "analysis/synthetic"])
def test_intermediate_rejection_does_not_become_failure(outcome, archive, tmp_path):
    work = start(archive=archive)
    saved = []
    model_calls.set_archive_writer(saved.extend)
    model_calls.capture("私密退稿")
    model_calls.rejected("未通過", candidate="私密退稿")
    model_calls.completed(outcome)
    model_calls.close(work)
    assert not list((tmp_path / "artifacts/failures").glob("*.json"))
    assert not model_calls._pending
    assert saved == [] and work.candidates == []


def test_cancel_discards_pending_attempt_and_retry_uses_new_identity(tmp_path):
    work = start()
    model_calls.capture("舊候選")
    model_calls.close(work)
    model_calls.discard("research", "work", "learner")
    retried = model_calls.start("research", "work", "new-attempt", "material", "learner")
    assert retried.tags["attempt_id"] != work.tags["attempt_id"]
    assert retried.candidates == []
    model_calls.completed("succeeded")
    model_calls.close(retried)
    assert not list((tmp_path / "artifacts/failures").glob("*.json"))


def test_failure_retention_cleans_without_new_model_call(tmp_path):
    directory = tmp_path / "artifacts/failures"
    directory.mkdir(parents=True)
    old, recent = directory / "old.json", directory / "recent.json"
    old.write_text("{}")
    recent.write_text("{}")
    timestamp = (datetime.now(UTC) - timedelta(days=31)).timestamp()
    os.utime(old, (timestamp, timestamp))
    model_calls.cleanup()
    assert not old.exists() and recent.exists()


def test_failed_title_waits_for_parent_transaction(tmp_path):
    parent = start("podcast_script")
    title = start("podcast_title", defer_to_parent=True)
    model_calls.capture("無效集名")
    model_calls.completed("failed", "PODCAST_TITLE_INVALID")
    model_calls.close(title)
    assert not list((tmp_path / "artifacts/failures").glob("*.json"))
    model_calls.completed("succeeded")
    model_calls.close(parent)
    path, = (tmp_path / "artifacts/failures").glob("*.json")
    assert json.loads(path.read_text())["tags"]["feature"] == "podcast_title"
