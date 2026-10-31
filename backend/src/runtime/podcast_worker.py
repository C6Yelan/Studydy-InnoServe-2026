"""逐集產生與核對講稿，再交本機語音 provider 配音；不佔用教材／題組 worker。"""

from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from threading import BoundedSemaphore
import json
import logging
from urllib.error import HTTPError

from . import model_calls, podcast_titles, podcasts
from .errors import PodcastError
from .generation_jobs import cancellable_job
from .podcast_script_generation import script
from .provider_http import _cancellation, generation_response, provider_error_code, provider_request
from .storage.tables import Podcast


def step(*, dsn=None, workers=1):
    claims = podcasts.claim_step(dsn=dsn, parallel=True)
    if claims is None:
        return
    claim = claims[0]
    from .semantic_service import _request_slots
    token = _request_slots.set(BoundedSemaphore(workers))
    try:
        with cancellable_job(Podcast, claim["podcast_id"], claim["token"], dsn=dsn):
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(copy_context().run, _episode, item, dsn=dsn) for item in claims]
                for future in futures:
                    future.result()
            podcasts.finish_batch(claim, dsn=dsn)
    finally:
        _request_slots.reset(token)


def _episode(claim, *, dsn):
    if claim["episode"]["script"]:
        _audio(claim, dsn=dsn)
        return
    trace = model_calls.start(
        "podcast_script", (claim["podcast_id"], claim["index"]), claim["token"],
        claim["material_id"], claim["owner"],
    )
    try:
        with cancellable_job(Podcast, claim["podcast_id"], claim["token"], dsn=dsn):
            episode = claim["episode"]
            result = script({
                "claims": episode["claims"], "delivery": episode["delivery"],
                "hosts": episode["hosts"], "series": claim["series"],
                "source_context": claim["source_context"],
            })
            state = _cancellation.get()
            if state is not None:
                state.check()
            title = podcast_titles.generate({**episode, "script": result}, claim=claim)
            podcasts.finish_step(claim, script=result, title=title, dsn=dsn)
    except Exception as error:
        model_calls.rejected(str(error))
        code = str(error) if str(error) in {
            "PODCAST_SCRIPT_INVALID", "PODCAST_SCRIPT_NEEDS_REVIEW", "PODCAST_CANCELLED",
            "SEMANTIC_SERVICE_UNAVAILABLE", "SEMANTIC_SERVICE_TIMEOUT", "SEMANTIC_GENERATION_FAILED",
        } else "PODCAST_PROVIDER_FAILED"
        logging.getLogger(__name__).warning("podcast_step_failed error_code=%s", code)
        podcasts.finish_step(claim, error=code, dsn=dsn)
    finally:
        model_calls.close(trace)


def _audio(claim, *, dsn):
    saving = False
    try:
        with cancellable_job(Podcast, claim["podcast_id"], claim["token"], dsn=dsn) as job:
            request = provider_request(
                "/audio",
                {"script": claim["episode"]["script"], "purpose": "podcast",
                 "episode_index": claim["index"], **job},
                unavailable=PodcastError("PODCAST_PROVIDER_UNAVAILABLE"),
            )
            try:
                with generation_response(request) as response:
                    data = response.read(100 * 1024 * 1024 + 1)
                    audio_provider = response.headers.get("X-Studydy-Audio-Provider")
                    raw_metadata = response.headers.get("X-Studydy-Audio-Mastering", "")
                    if len(raw_metadata) > 2048:
                        raise PodcastError("PODCAST_AUDIO_INVALID")
                    audio_mastering = json.loads(raw_metadata) if raw_metadata else None
            except HTTPError as failure:
                code = provider_error_code(failure)
                if code in {"PODCAST_AUDIO_INVALID", "PODCAST_CANCELLED"}:
                    raise PodcastError(code) from None
                raise PodcastError("PODCAST_PROVIDER_FAILED") from None
            if len(data) > 100 * 1024 * 1024:
                raise PodcastError("PODCAST_AUDIO_INVALID")
            saving = True
            podcasts.finish_step(
                claim, audio=data, audio_provider=audio_provider,
                audio_mastering=audio_mastering, dsn=dsn,
            )
    except Exception as error:
        code = (
            str(error) if isinstance(error, PodcastError)
            else "PODCAST_STORAGE_FAILED" if saving else "PODCAST_PROVIDER_FAILED"
        )
        logging.getLogger(__name__).warning("podcast_step_failed error_code=%s", code)
        try:
            podcasts.finish_step(claim, error=code, dsn=dsn)
        except Exception:
            logging.getLogger(__name__).warning("PODCAST_RESULT_SAVE_FAILED")
