"""回歸只使用受控模型回應，禁止 HTTP transport 連到真實模型服務。"""
import httpx
import pytest


@pytest.fixture(autouse=True)
def forbid_live_model_http(monkeypatch):
    original = httpx.HTTPTransport.handle_request

    def handle_request(self, request):
        if request.url.host not in {"127.0.0.1", "localhost", "::1"} or request.url.port in {18000, 18001}:
            raise AssertionError("LIVE_MODEL_HTTP_FORBIDDEN_IN_TESTS")
        return original(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle_request)
