"""逐集產生與核對講稿，不佔用教材／題組 worker。"""

import logging

from . import model_calls, podcast_titles, podcasts
from .generation_jobs import cancellable_job
from .podcast_script_generation import script
from .provider_http import _cancellation
from .storage.tables import Podcast


def step(*, dsn=None):
    claim = podcasts.claim_step(dsn=dsn)
    if claim is None:
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
