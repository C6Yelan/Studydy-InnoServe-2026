"""外送前拒絕預算耗盡，不得把固定原因碼轉成可重試的連線錯誤。"""

import pytest

from runtime.local_ai_config import read_local_ai_config_from_environment
from runtime.semantic_service import SemanticServiceError, request_semantics


def test_exhausted_budget_never_reaches_provider(monkeypatch):
    import runtime.semantic_service as service
    lock = read_local_ai_config_from_environment(
        {})["runtime_lock"]
    sent = []
    monkeypatch.setattr(service, "_token_count", lambda *args: 100)
    monkeypatch.setattr(service, "_post", lambda *args, **kwargs: sent.append(args))

    def exhausted():
        raise SemanticServiceError("MATERIAL_MODEL_BUDGET_EXHAUSTED")

    with pytest.raises(SemanticServiceError, match="MATERIAL_MODEL_BUDGET_EXHAUSTED"):
        request_semantics(None, runtime_lock=lock, task="material_review",
            request={}, response_schema={}, before_request=exhausted)
    assert sent == []
