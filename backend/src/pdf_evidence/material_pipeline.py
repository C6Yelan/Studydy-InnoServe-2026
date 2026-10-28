from __future__ import annotations

from runtime.material_runtime import MaterialAnalysisError, validate_runtime_lock

from functools import partial
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
import fcntl
import os
from pathlib import Path
import tempfile
import time
from typing import Any, Callable
from uuid import uuid4

import httpx
import pymupdf

from knowledge_map.structure import (
    SemanticState,
    apply_semantic_response,
    build_document_context,
    build_structure_draft,
    build_semantic_bundles,
    semantic_request,
    semantic_response_schema,
)
from runtime import model_calls
from runtime.semantic_service import (
    SemanticServiceError,
    material_request_fits,
    request_semantics,
    semantic_client,
)

from .page_evidence import (
    _build_page_evidence,
    build_native_page_evidence,
    extract_page,
    route_page,
)
from .image_text import image_blocks
from content_identity import canonical_sha256
from .source_set import collect_source_set


Progress = Callable[[str, int, int], None]


@contextmanager
def material_analysis_lock(
    runtime_root: Path,
    *,
    wait_seconds: float | None = None,
    cancellation_check: Callable[[], None] | None = None,
):
    """序列化共用的教材分析工作；模型服務生命週期不在此鎖內。"""

    if (
        not runtime_root.is_absolute()
        or runtime_root.is_symlink()
        or (wait_seconds is not None and wait_seconds < 0)
    ):
        raise MaterialAnalysisError("RUNTIME_LAYOUT_INVALID")
    runtime_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = runtime_root / "material-analysis.lock"
    if lock_path.is_symlink():
        raise MaterialAnalysisError("RUNTIME_LAYOUT_INVALID")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        deadline = None if wait_seconds is None else time.monotonic() + wait_seconds
        while True:
            if cancellation_check is not None:
                cancellation_check()
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if deadline is not None and time.monotonic() >= deadline:
                    raise MaterialAnalysisError("RUNTIME_BUSY") from None
                time.sleep(0.05)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _reason(error: Exception) -> str:
    reason = getattr(error, "reason_code", None) or str(error)
    allowed = {
        "OCR_VISUAL_REVIEW_REQUIRED",
        "OCR_UNAVAILABLE",
        "OCR_TIMEOUT",
        "CHILD_EXITED",
        "CHILD_TIMEOUT",
        "CHILD_RESPONSE_INVALID",
        "OCR_OUTPUT_INVALID",
        "OCR_LOCATOR_INVALID",
        "NO_USABLE_EVIDENCE",
        "PROTOCOL_LIMIT_EXCEEDED",
        "SEMANTIC_SERVICE_TIMEOUT",
        "SEMANTIC_SERVICE_UNAVAILABLE",
        "SEMANTIC_GENERATION_FAILED",
        "MATERIAL_MODEL_BUDGET_EXHAUSTED",
        "SEMANTIC_RESPONSE_INVALID",
        "SEMANTIC_OUTPUT_INVALID",
        "SEMANTIC_OUTPUT_TRUNCATED",
        "SEMANTIC_OUTPUT_TOO_LARGE",
        "SEMANTIC_INPUT_TOO_LARGE",
        "SEMANTIC_BUDGET_EXHAUSTED",
        "KNOWLEDGE_STRUCTURE_INVALID",
        "MATERIAL_IDENTITY_INVALID",
        "ANALYSIS_CHECKPOINT_INVALID",
    }
    return reason if reason in allowed else "MATERIAL_ANALYSIS_FAILED"


def _excluded(page: dict[str, Any], reason: str) -> dict[str, Any]:
    return {
        "page_ref": page["page_ref"],
        "page": page["page_number"],
        "stage": "evidence",
        "reason_code": reason,
    }


def _page_evidence(
    source_path: Path,
    source_sha256: str,
    page_numbers: list[int],
    settings: dict[str, Any],
    produced_at: str,
    report: Progress,
    cancellation_check: Callable[[], None],
    *,
    wait_cancellation_check: Callable[[], None] | None = None,
    load_page: Callable[[int], dict | None] | None = None,
    save_page: Callable[[int, dict], None] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    pages: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    ocr_calls = 0
    document = pymupdf.open(source_path)
    try:
        for completed, page_number in enumerate(page_numbers, start=1):
            cancellation_check()
            cached = load_page(page_number) if load_page is not None else None
            if cached is not None:
                # 原來源頁碼、來源內容與完整 page artifact 都須一致，不能把另一頁的快照接上。
                cached_binding = (
                    cached.get("input_binding") if isinstance(cached, dict) else None
                )
                if (
                    not isinstance(cached_binding, dict)
                    or cached.get("schema") != "page-evidence/v1"
                    or cached.get("material_id") != "material:sha256:" + source_sha256
                    or cached.get("route") not in {"native_sufficient", "tesseract_text", "visual_ocr"}
                    or cached.get("page_number") != page_number
                    or cached_binding.get("source_sha256") != source_sha256
                    or cached_binding.get("page") != page_number
                    or cached_binding.get("route") != cached.get("route")
                    or cached_binding.get("runtime_lock_sha256") != canonical_sha256(settings["runtime_lock"])
                    or cached.get("page_evidence_id")
                    != "page-evidence:sha256:"
                    + canonical_sha256(
                        {k: v for k, v in cached.items() if k != "page_evidence_id"}
                    )
                ):
                    raise MaterialAnalysisError("ANALYSIS_CHECKPOINT_INVALID")
                if save_page is not None:
                    save_page(page_number, cached)
                pages.append(cached)
                report("evidence", completed, len(page_numbers))
                continue
            page = extract_page(document, source_sha256, page_number)
            artifact = None
            try:
                route = route_page(page)
                binding = {
                    "source_sha256": source_sha256,
                    "page": page_number,
                    "render_sha256": page["render"]["sha256"],
                    "route": route,
                    "runtime_lock_sha256": canonical_sha256(settings["runtime_lock"]),
                    "processing_policy": settings["runtime_lock"]["ingestion"]["processing_policy"],
                }
                if route == "native_sufficient":
                    artifact = build_native_page_evidence(
                        page,
                        input_binding=binding,
                        produced_at=produced_at,
                    )
                else:
                    if settings["runtime_lock"]["ingestion"]["processing_policy"] == "native-text-only/v1":
                        raise ValueError("NO_USABLE_EVIDENCE")
                    ocr_calls += 1
                    blocks, image_route, source = image_blocks(page, cancellation_check)
                    binding["route"] = image_route
                    artifact = _build_page_evidence(page, blocks, input_binding=binding,
                        produced_at=produced_at, route=image_route, source=source)
                pages.append(artifact)
            except ValueError as error:
                excluded.append(_excluded(page, _reason(error)))
            finally:
                page.pop("png_bytes", None)
                page.pop("native_evidence", None)
            # 儲存錯誤不可被當成單頁 OCR 失敗略過；成功落盤後才更新頁數。
            if artifact is not None and save_page is not None:
                save_page(page_number, artifact)
            report("evidence", completed, len(page_numbers))
    finally:
        document.close()
    return pages, excluded, ocr_calls


def _initial_semantic_state(base_structure, context, input_binding):
    if base_structure is None:
        return SemanticState()
    from knowledge_map.source_identity import seed_incremental_state

    state = seed_incremental_state(base_structure, context, input_binding)
    state.rejected_claims = base_structure["metrics"]["rejected_claims"]
    state.rejected_relations = base_structure["metrics"]["rejected_relations"]
    state.literal_repairs = base_structure["metrics"]["literal_repairs"]
    return state


def analyze_material(
    source_inputs: list[dict[str, Any]],
    input_binding: dict[str, Any],
    settings: dict[str, Any],
    *,
    run_id: str | None = None,
    produced_at: str | None = None,
    progress_callback: Progress | None = None,
    cancellation_check: Callable[[], None] | None = None,
    wait_cancellation_check: Callable[[], None] | None = None,
    client: httpx.Client | None = None,
    semantic_call: Callable[..., dict[str, Any]] = request_semantics,
    base_structure: dict[str, Any] | None = None,
    analysis_archive: Any | None = None,
) -> dict[str, Any]:
    """Evidence → 語意模型 → 未綁來源的內部草稿；發布前須完成正式來源綁定。"""

    lock = validate_runtime_lock(settings.get("runtime_lock"), assessment=False)
    resolved_run = run_id or str(uuid4())
    resolved_time = produced_at or datetime.now(UTC).isoformat()
    report = progress_callback or (lambda _stage, _completed, _total: None)
    check_cancel = cancellation_check or (lambda: None)
    check_wait = wait_cancellation_check or check_cancel
    source_digest = input_binding["source_set_digest"]
    restored = (
        analysis_archive.load_checkpoint() if analysis_archive is not None else None
    )
    check_cancel()
    if restored is not None:
        context = restored["context"]
        if restored["source_sha256"] != source_digest:
            raise MaterialAnalysisError("ANALYSIS_CHECKPOINT_INVALID")
        page_numbers = list(range(1, context["page_count"] + 1))
        state = SemanticState(**restored["state"])
        cursor = restored["cursor"]
        semantic_calls = restored["semantic_calls"]
        ocr_calls = restored["ocr_calls"]
        evidence_duration_ms = restored["evidence_duration_ms"]
        previous_semantic_ms = restored["semantic_duration_ms"]
        report("evidence", len(page_numbers), len(page_numbers))
    else:
        evidence_started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="studydy-source-") as directory:
            page_numbers = list(range(1, len(input_binding["bundle"]["pages"]) + 1))
            pages, excluded, ocr_calls = collect_source_set(
                source_inputs,
                input_binding,
                base_structure,
                Path(directory),
                settings,
                resolved_time,
                report,
                check_cancel,
                partial(_page_evidence, wait_cancellation_check=check_wait),
                analysis_archive=analysis_archive,
            )
        evidence_duration_ms = round((time.monotonic() - evidence_started) * 1000)
        check_cancel()
        try:
            context = build_document_context(
                pages,
                page_count=len(page_numbers),
                excluded_pages=excluded,
                source_pages=input_binding["bundle"]["pages"],
            )
            if input_binding["bundle"].get("learning_scopes"):
                context["learning_scopes"] = deepcopy(
                    input_binding["bundle"]["learning_scopes"]
                )
            if lock["material_semantics"].get("spoken_policy") == "source-excerpts/v1":
                context["spoken_sources"] = {
                    item["source_id"]: deepcopy(item["transcript"])
                    for item in input_binding["manifest"]["items"]
                    if "transcript" in item
                }
        except ValueError as error:
            raise MaterialAnalysisError("DOCUMENT_EVIDENCE_INVALID") from error
        state = _initial_semantic_state(base_structure, context, input_binding)
        if base_structure is not None:
            context["incremental"] = True
        cursor = semantic_calls = previous_semantic_ms = 0
    if restored is not None and restored.get("restart_semantics"):
        state = _initial_semantic_state(base_structure, context, input_binding)
        cursor = 0
    restored_ranges = deepcopy((restored or {}).get("completed_block_ranges", []))
    report(
        "semantics",
        cursor + sum(end - start for start, end in restored_ranges),
        len(context["evidence"]),
    )
    semantic_started = time.monotonic()
    complete = bool(restored and restored.get("complete"))
    evidence_indices = {
        item["evidence_id"]: index for index, item in enumerate(context["evidence"])
    }

    parallel_progress = {
        "cursor": cursor,
        "semantic_calls": semantic_calls,
        "ranges": restored_ranges,
    }

    def save_checkpoint():
        if analysis_archive is not None:
            analysis_archive.save_checkpoint(
                {
                    "context": context,
                    "state": asdict(state),
                    "cursor": cursor,
                    "completed_block_ranges": parallel_progress["ranges"],
                    "complete": complete,
                    "source_sha256": source_digest,
                    "semantic_calls": semantic_calls,
                    "ocr_calls": ocr_calls,
                    "evidence_duration_ms": evidence_duration_ms,
                    "semantic_duration_ms": previous_semantic_ms
                    + round((time.monotonic() - semantic_started) * 1000),
                }
            )

    save_checkpoint()

    owned_client = client is None and not complete
    http = semantic_client() if owned_client else client
    try:
        if (
            lock["material_semantics"]["bundle_policy"]
            == "independent-evidence-blocks/v1"
            and not complete
        ):
            from .semantic_blocks import analyze_blocks

            def checkpoint_blocks():
                nonlocal cursor, semantic_calls
                cursor = parallel_progress["cursor"]
                semantic_calls = parallel_progress["semantic_calls"]
                save_checkpoint()

            while True:
                try:
                    analyze_blocks(
                        context,
                        state,
                        parallel_progress,
                        lock=lock,
                        fits=lambda request: material_request_fits(
                            http, lock, request, cancellation_check=check_wait
                        ),
                        semantic_call=semantic_call,
                        archive=analysis_archive,
                        checkpoint=checkpoint_blocks,
                        report=report,
                        check_cancel=check_wait,
                        minimum_page=base_structure["page_count"] + 1
                        if base_structure
                        else 1,
                    )
                    cursor = parallel_progress["cursor"]
                    semantic_calls = parallel_progress["semantic_calls"]
                    complete = True
                    break
                except ValueError as error:
                    raise MaterialAnalysisError(_reason(error)) from None
        elif not complete:
            bundles = iter(
                build_semantic_bundles(
                    context,
                    state=state,
                    fits=lambda request: material_request_fits(
                        http, lock, request, cancellation_check=check_wait
                    ),
                    minimum_page=base_structure["page_count"] + 1
                    if base_structure
                    else 1,
                    minimum_evidence_index=cursor,
                )
            )
            while True:
                check_cancel()
                try:
                    bundle = next(bundles)
                except StopIteration:
                    complete = True
                    break
                except ValueError as error:
                    raise MaterialAnalysisError(_reason(error)) from None
                request_document = semantic_request(context, bundle, state)
                last_error: Exception | None = None
                for _attempt in range(lock["material_semantics"]["retry_attempts"]):
                    check_cancel()
                    candidate_state = deepcopy(state)
                    try:
                        response = (
                            analysis_archive.reuse_review_response(request_document)
                            if analysis_archive is not None
                            else None
                        )
                        if response is None:
                            semantic_calls += 1
                            if analysis_archive is not None:
                                analysis_archive.prepare_call(
                                    semantic_calls, request_document
                                )
                            response = semantic_call(
                                http,
                                runtime_lock=lock,
                                task="material_semantics",
                                tags=model_calls.tags(feature="material_analysis", stage="analysis"),
                                cancellation_check=check_wait,
                                request=request_document,
                                response_schema=semantic_response_schema(
                                    [
                                        row[0]
                                        for section in request_document["sections"]
                                        for row in section["evidence"]
                                    ],
                                    incremental=base_structure is not None,
                                ),
                            )
                        if analysis_archive is not None:
                            analysis_archive.save_response(
                                semantic_calls, request_document, response
                            )
                        if base_structure is not None:
                            if (
                                not isinstance(response, dict)
                                or type(response.get("review_required")) is not bool
                            ):
                                raise ValueError("SEMANTIC_OUTPUT_INVALID")
                            candidate_state.source_review_required |= response[
                                "review_required"
                            ]
                            response = {
                                key: value
                                for key, value in response.items()
                                if key != "review_required"
                            }
                        apply_semantic_response(
                            response,
                            context=context,
                            bundle=bundle,
                            state=candidate_state,
                        )
                        state.concepts = candidate_state.concepts
                        state.relations = candidate_state.relations
                        state.rejected_claims = candidate_state.rejected_claims
                        state.rejected_relations = candidate_state.rejected_relations
                        state.literal_repairs = candidate_state.literal_repairs
                        state.source_review_required = (
                            candidate_state.source_review_required
                        )
                        last_error = None
                        break
                    except SemanticServiceError as error:
                        last_error = error
                    except ValueError as error:
                        last_error = error
                if last_error is not None:
                    raise MaterialAnalysisError(_reason(last_error)) from None
                cursor = evidence_indices[bundle["evidence"][-1]["evidence_id"]] + 1
                save_checkpoint()
                report("semantics", cursor, len(context["evidence"]))
    finally:
        if (
            lock["material_semantics"]["bundle_policy"]
            == "independent-evidence-blocks/v1"
        ):
            cursor = parallel_progress["cursor"]
            semantic_calls = parallel_progress["semantic_calls"]
        if owned_client:
            http.close()
        save_checkpoint()
    report("semantics", len(context["evidence"]), len(context["evidence"]))
    semantic_duration_ms = previous_semantic_ms + round(
        (time.monotonic() - semantic_started) * 1000
    )
    service = lock["semantic_service"]
    try:
        return build_structure_draft(
            context,
            state,
            source_sha256=source_digest,
            run_id=resolved_run,
            produced_at=resolved_time,
            runtime_lock_sha256=canonical_sha256(lock),
            model_id=service["model_id"],
            model_revision=service["revision"],
            semantic_calls=semantic_calls,
            ocr_calls=ocr_calls,
            evidence_duration_ms=evidence_duration_ms,
            semantic_duration_ms=semantic_duration_ms,
        )
    except ValueError as error:
        raise MaterialAnalysisError(_reason(error)) from None
