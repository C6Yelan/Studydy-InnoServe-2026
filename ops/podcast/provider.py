"""獨立語音合成、辨識與對齊服務。"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from hmac import compare_digest
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Lock
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend/src"))
from runtime import podcast_process
ASR_LOCK = Lock()
# 語音合成與教材辨識都使用顯示卡，共用同一把 GPU 鎖。
GPU_LOCK = Lock()
AUDIO_PROVIDER = "XTTS-v2@6c2b0d75;official-speakers;ckip-cc-cedict-pinyin/v1;spoken-input/v15;dynamic-pauses/v2;podcast-mastering/v1"


def audio(body, *, cancelled=None):
    # Podcast 由使用者取消或程序結果結束，不用固定秒數終止長音訊。
    with tempfile.TemporaryDirectory(prefix="studydy-podcast-audio-") as directory:
        output = Path(directory) / "audio.wav"
        result = podcast_process.run(
            [
                os.environ["STUDYDY_PODCAST_TTS_PYTHON"],
                str(Path(__file__).with_name("synthesize.py")),
                str(output),
            ],
            input=json.dumps(body, ensure_ascii=False),
            timeout=None,
            cancelled=cancelled,
            env={
                k: v
                for k, v in os.environ.items()
                if k != "STUDYDY_PODCAST_PROVIDER_TOKEN"
            },
        )
        if result.returncode != 0 or not output.is_file():
            raise RuntimeError("PODCAST_AUDIO_INVALID")
        data = output.read_bytes()
        if len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            raise RuntimeError("PODCAST_AUDIO_INVALID")
        metadata = None
        if body.get("purpose") == "podcast":
            metadata = json.loads(output.with_suffix(".json").read_text())
        return data, metadata


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
        routes = {"/audio": audio, "/transcribe": transcribe, "/media-transcribe": media_transcribe, "/align": align_audio}
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
                lock = GPU_LOCK if self.path in {"/audio", "/media-transcribe"} else ASR_LOCK
                with podcast_process.job(body) as cancelled:
                    queued = time.monotonic()
                    with podcast_process.tracked_lock(lock, cancelled, body, self.path):
                        started = time.monotonic()
                        result = routes[self.path](body, cancelled=cancelled)
                    podcast_process.check(cancelled)
                if self.path == "/audio":
                    data, metadata = result
                    headers = {
                        "X-Studydy-Audio-Timings": json.dumps({
                            "tts_queue_ms": (started - queued) * 1000,
                            "tts_synthesis_ms": (time.monotonic() - started) * 1000,
                        }),
                        "X-Studydy-Audio-Provider": AUDIO_PROVIDER,
                    }
                    if metadata:
                        headers["X-Studydy-Audio-Mastering"] = json.dumps(metadata, separators=(",", ":"))
                    self.respond(data, media="audio/wav", headers=headers)
                    return
            self.respond(result)
        except Exception as error:
            code = str(error)
            if code not in {"REQUEST_INVALID", "VOICE_TRANSCRIPT_INVALID", "PODCAST_AUDIO_INVALID", "MEDIA_TRANSCRIPT_FAILED", "SCENE_ALIGNMENT_FAILED", "PODCAST_CANCELLED"}:
                code = "VOICE_PROVIDER_FAILED"
            self.respond({"error_code": code}, 502)

    def respond(self, result, status=200, *, media="application/json", headers=None):
        data = result if media != "application/json" else json.dumps(result, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", media)
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)


def main():
    if not os.environ.get("STUDYDY_PODCAST_PROVIDER_TOKEN"):
        raise SystemExit("VOICE_PROVIDER_TOKEN_REQUIRED")
    ThreadingHTTPServer((os.environ.get("STUDYDY_PROVIDER_HOST", "127.0.0.1"), int(os.environ.get("STUDYDY_PROVIDER_PORT", "18091"))), Handler).serve_forever()


if __name__ == "__main__":
    main()
