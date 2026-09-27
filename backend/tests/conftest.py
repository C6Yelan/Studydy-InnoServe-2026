"""回歸只使用受控模型回應，禁止 HTTP transport 連到真實模型服務。"""
import httpx
import pytest


@pytest.fixture(autouse=True)
def forbid_live_model_http(monkeypatch):
    # TestClient／ASGITransport／MockTransport 不經這個入口；模型 HTTP 一律禁止。
    def reject(*args, **kwargs):
        raise AssertionError("LIVE_MODEL_HTTP_FORBIDDEN_IN_TESTS")

    async def reject_async(*args, **kwargs):
        raise AssertionError("LIVE_MODEL_HTTP_FORBIDDEN_IN_TESTS")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", reject)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", reject_async)
