"""只使用本機 HTTP stub／小型 child，驗證推論等待可取消且不設總時限。"""

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
from threading import Event, Thread, enumerate as threads
from types import SimpleNamespace

import pytest

from runtime.semantic_service import request_semantics, semantic_client


class Cancelled(RuntimeError):
    pass


def check(event):
    if event.is_set():
        raise Cancelled()


@contextmanager
def blocked_http(monkeypatch, *, path='/v1/chat/completions', body=False):
    state = SimpleNamespace(entered=Event(), release=Event(), requests=[])

    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *_):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            state.requests.append(self.path)
            payload = json.dumps({'count': 50, 'max_model_len': json.loads((Path(__file__).parents[2] / 'local_ai/runtime-lock.json').read_text())['semantic_service']['max_model_len']} if self.path == '/tokenize'
                                 else {'choices': [{'finish_reason': 'stop', 'message': {'content': '{"ok":true}'}}]}).encode()
            blocking = self.path == path
            if blocking and not body:
                state.entered.set()
                state.release.wait()
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                if blocking and body:
                    self.wfile.write(payload[:1])
                    self.wfile.flush()
                    state.entered.set()
                    state.release.wait()
                    payload = payload[1:]
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.delenv('VLLM_API_KEY', raising=False)
    monkeypatch.setenv('STUDYDY_SEMANTIC_BASE_URL', f'http://127.0.0.1:{server.server_port}')
    try:
        yield state
    finally:
        state.release.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


def semantic_request(cancel, task='assessment'):
    lock = json.loads((Path(__file__).parents[2] / 'local_ai/runtime-lock.json').read_text())
    with semantic_client(environment={}) as client:
        assert client.timeout.read is None
        assert client.timeout.connect == 5
        return request_semantics(client, runtime_lock=lock, task=task, request={},
                                 response_schema={}, cancellation_check=lambda: check(cancel))


@pytest.mark.parametrize('task', ['material_semantics', 'material_review', 'assessment', 'assessment_check'])
@pytest.mark.parametrize('path,body', [('/tokenize', False), ('/v1/chat/completions', False), ('/v1/chat/completions', True)])
def test_semantic_cancellation_interrupts_headers_and_body_without_waiting_for_remote(monkeypatch, task, path, body):
    cancel = Event()
    results = []
    def run():
        try:
            results.append(semantic_request(cancel, task))
        except Cancelled:
            results.append('cancelled')
    with blocked_http(monkeypatch, path=path, body=body) as server:
        thread = Thread(target=run, daemon=True)
        thread.start()
        try:
            assert server.entered.wait(3)
            cancel.set()
            thread.join(2)
            assert not thread.is_alive()
            assert results == ['cancelled']
            assert not server.release.is_set()  # 遠端 stub 尚未完成，本地已退出。
            assert not any(t.name == 'studydy-semantic-cancellation' for t in threads())
        finally:
            server.release.set()
            thread.join(3)
    assert results == ['cancelled']


def test_normal_semantic_wait_survives_many_cancellation_checks(monkeypatch):
    cancel = Event()
    results = []
    with blocked_http(monkeypatch) as server:
        thread = Thread(target=lambda: results.append(semantic_request(cancel)), daemon=True)
        thread.start()
        try:
            assert server.entered.wait(3)
            thread.join(.4)
            assert thread.is_alive() and results == []
            server.release.set()
            thread.join(3)
            assert results == [{'ok': True}]
        finally:
            server.release.set()
            thread.join(3)
