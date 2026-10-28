"""獨立語音辨識與對齊服務。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from hmac import compare_digest
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Lock
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend/src"))
from runtime import podcast_process
ASR_LOCK = Lock()


def transcribe(body, *, cancelled=None):
    import base64

    data = base64.b64decode(body["audio"], validate=True)
    if not 0 < len(data) <= 12 * 1024 * 1024:
        raise ValueError("REQUEST_INVALID")
    hints = body.get("hints", "")
    if (
        not isinstance(hints, str)
        or len(hints) > 320
        or any(ord(c) < 32 for c in hints)
    ):
        raise ValueError("REQUEST_INVALID")
    with tempfile.TemporaryDirectory(prefix="studydy-stt-") as temporary:
        output = Path(temporary) / "transcript.json"
        result = podcast_process.run(
            [
                os.environ["STUDYDY_STT_PYTHON"],
                str(Path(__file__).with_name("transcribe.py")),
                str(output),
            ],
            input=data,
            timeout=None,
            cancelled=cancelled,
            env={
                **{
                    k: v
                    for k, v in os.environ.items()
                    if k != "STUDYDY_PODCAST_PROVIDER_TOKEN"
                },
                "STUDYDY_STT_HINTS": hints,
            },
        )
        if result.returncode != 0 or not output.is_file():
            raise RuntimeError("VOICE_TRANSCRIPT_INVALID")
        return json.loads(output.read_text())


def media_transcribe(body, *, cancelled=None):
    """教材音訊、影片音軌與無字幕 YouTube 的逐字稿；音訊只在暫存目錄，完成即刪除。"""
    import base64

    data = base64.b64decode(body["audio"], validate=True)
    if not 0 < len(data) <= 48 * 1024 * 1024:
        raise ValueError("REQUEST_INVALID")
    with tempfile.TemporaryDirectory(prefix="studydy-media-stt-") as temporary:
        audio = Path(temporary) / "speech.ogg"
        output = Path(temporary) / "transcript.json"
        audio.write_bytes(data)
        del data
        result = podcast_process.run(
            [
                os.environ["STUDYDY_STT_PYTHON"],
                str(Path(__file__).with_name("transcribe_media.py")),
                str(audio),
                str(output),
            ],
            timeout=None,
            cancelled=cancelled,
            env={
                k: v
                for k, v in os.environ.items()
                if k != "STUDYDY_PODCAST_PROVIDER_TOKEN"
            },
        )
        if result.returncode != 0 or not output.is_file():
            raise RuntimeError("MEDIA_TRANSCRIPT_FAILED")
        return json.loads(output.read_text())


def align_audio(body, *, cancelled=None, max_texts=12):
    import base64

    data = base64.b64decode(body["audio"], validate=True)
    texts = body.get("texts")
    if (
        not 0 < len(data) <= 100 * 1024 * 1024
        or not isinstance(texts, list)
        or not 1 <= len(texts) <= max_texts
    ):
        raise ValueError("REQUEST_INVALID")
    with tempfile.TemporaryDirectory(prefix="studydy-align-") as temporary:
        wav = Path(temporary) / "audio.wav"
        output = Path(temporary) / "alignment.json"
        wav.write_bytes(data)
        result = podcast_process.run(
            [
                os.environ["STUDYDY_STT_PYTHON"],
                str(Path(__file__).with_name("align.py")),
                str(wav),
                str(output),
            ],
            input=json.dumps(
                {
                    "texts": texts,
                    **{
                        k: body[k]
                        for k in ("turn_indices", "caption_turns")
                        if k in body
                    },
                },
                ensure_ascii=False,
            ),
            timeout=None,
            cancelled=cancelled,
            env={
                k: v
                for k, v in os.environ.items()
                if k != "STUDYDY_PODCAST_PROVIDER_TOKEN"
            },
        )
        if result.returncode != 0 or not output.is_file():
            raise RuntimeError("SCENE_ALIGNMENT_FAILED")
        return json.loads(output.read_text())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_POST(self):
        expected = "Bearer " + os.environ["STUDYDY_PODCAST_PROVIDER_TOKEN"]
        if not compare_digest(self.headers.get("Authorization", ""), expected):
            self.send_error(401)
            return
        routes = {"/transcribe": transcribe, "/media-transcribe": media_transcribe, "/align": align_audio}
        if self.path not in {*routes, "/jobs/cancel", "/jobs/progress"}:
            self.send_error(404)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            limit = 140 if self.path == "/align" else 66 if self.path == "/media-transcribe" else 18
            if not 0 < size <= limit * 1024 * 1024:
                raise ValueError("REQUEST_INVALID")
            body = json.loads(self.rfile.read(size))
            if self.path == "/jobs/cancel":
                result = podcast_process.cancel(body)
            elif self.path == "/jobs/progress":
                result = podcast_process.progress(body)
            else:
                with podcast_process.job(body) as cancelled:
                    with podcast_process.tracked_lock(ASR_LOCK, cancelled, body, self.path):
                        result = routes[self.path](body, cancelled=cancelled)
            self.respond(result)
        except Exception as error:
            code = str(error)
            if code not in {"REQUEST_INVALID", "VOICE_TRANSCRIPT_INVALID", "MEDIA_TRANSCRIPT_FAILED", "SCENE_ALIGNMENT_FAILED", "PODCAST_CANCELLED"}:
                code = "VOICE_PROVIDER_FAILED"
            self.respond({"error_code": code}, 502)

    def respond(self, result, status=200):
        data = json.dumps(result, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main():
    if not os.environ.get("STUDYDY_PODCAST_PROVIDER_TOKEN"):
        raise SystemExit("VOICE_PROVIDER_TOKEN_REQUIRED")
    ThreadingHTTPServer((os.environ.get("STUDYDY_PROVIDER_HOST", "127.0.0.1"), int(os.environ.get("STUDYDY_PROVIDER_PORT", "18091"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
