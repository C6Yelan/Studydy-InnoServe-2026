from __future__ import annotations

from contextlib import contextmanager, ExitStack
from copy import deepcopy
from datetime import UTC, datetime
import fcntl
import logging
import os
from pathlib import Path
import re
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
    build_knowledge_structure,
    build_semantic_bundles,
    semantic_request,
    semantic_response_schema,
)
from runtime.semantic_service import (
    SemanticServiceError,
    material_request_fits,
    request_semantics,
    semantic_client,
    request_vision,
)

from .ocr_page_evidence import (
    build_native_page_evidence,
    build_page_evidence,
    canonical_sha256,
    extract_page,
    route_page,
    vision_regions,
    render_vision_region,
)
from .source_pdf import snapshot_whole_document_request


Progress = Callable[[str, int, int], None]


class MaterialAnalysisError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def validate_runtime_lock(lock: Any) -> dict[str, Any]:
    """驗證競賽版的單一 Gemma 與文字優先擷取設定。"""

    try:
        if not isinstance(lock, dict) or set(lock) != {
            "schema", "python", "ingestion", "semantic_service",
            "material_semantics", "assessment",
        }:
            raise ValueError
        semantic = lock["semantic_service"]
        material = lock["material_semantics"]
        assessment = lock["assessment"]
        ingestion = lock["ingestion"]
        if (
            lock["schema"] != "studydy-runtime-lock/innoserve-v1"
            or lock["python"] != "3.12"
            or set(ingestion) != {"page_schema", "native_schema", "normalizer_policy", "processing_policy", "render", "vision"}
            or ingestion["render"] != {"dpi": 200, "colorspace": "RGB", "format": "PNG"}
            or set(ingestion["vision"]) != {"generation", "max_tokens", "mm_processor_kwargs", "prompt"}
            or ingestion["vision"]["generation"] != {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "chat_template_kwargs": {"enable_thinking": False}}
            or ingestion["vision"]["max_tokens"] != 8192
            or ingestion["vision"]["mm_processor_kwargs"] != {"max_soft_tokens": 1120}
            or not isinstance(ingestion["vision"]["prompt"], str)
            or not ingestion["vision"]["prompt"].strip()
            or set(semantic) != {
                "model_id", "revision", "api_protocol", "base_url", "max_model_len",
                "max_num_seqs", "server", "authentication",
            }
            or semantic["model_id"] != "google/gemma-4-31B-it-qat-w4a16-ct"
            or semantic["revision"] != "52f3f65bc7a02d555763bc923bd1d9094898219d"
            or semantic["api_protocol"] != "openai-chat-completions/v1"
            or semantic["base_url"] != "http://127.0.0.1:18001"
            or semantic["max_model_len"] != 32768
            or semantic["max_num_seqs"] != 1
            or semantic["server"] != {
                "package": "vllm",
                "version": "0.28.0",
                "python": "3.12",
                "torch": "2.13.0+cu130",
                "cuda": "13.0",
                "transformers": "5.15.1",
            }
            or semantic["authentication"] != "environment-bearer:VLLM_API_KEY"
            or set(material) != {
                "request_schema", "response_schema", "bundle_policy",
                "max_tokens", "prompt", "retry_attempts", "generation", "max_new_input_tokens",
            }
            or material["request_schema"] != "material-semantics-request/v2"
            or material["response_schema"] != "material-semantics-response/v4"
            or material["bundle_policy"] != "tokenized-contiguous-evidence/v3"
            or material["max_new_input_tokens"] != 1536
            or material["max_tokens"] != 8192
            or material["generation"] != {
                "temperature": 1.0, "top_p": 0.95, "top_k": 64,
                "chat_template_kwargs": {"enable_thinking": True},
            }
            or not isinstance(material["prompt"], str)
            or not material["prompt"]
            or set(assessment) != {
                "request_schema", "response_schema", "public_schema", "private_schema",
                "provenance_schema", "policy", "candidate_count", "option_count",
                "max_tokens", "generation", "prompt", "check_max_tokens", "check_generation", "check_prompt",
            }
            or assessment["request_schema"] != "assessment-semantics-request/v1"
            or assessment["response_schema"] != "assessment-semantics-response/v2"
            or assessment["public_schema"] != "single-choice-assessment/v2"
            or assessment["private_schema"] != "single-choice-answer/v2"
            or assessment["provenance_schema"] != "assessment-generation-provenance/v6"
            or assessment["policy"] != "source-span-single-choice/v5"
            or assessment["candidate_count"] != 3
            or assessment["option_count"] != 4
            or assessment["max_tokens"] != 4096
            or assessment["generation"] != {
                "temperature": 1.0, "top_p": 0.95, "top_k": 64,
                "chat_template_kwargs": {"enable_thinking": True},
            }
            or not isinstance(assessment["prompt"], str)
            or not assessment["prompt"]
            or assessment["check_max_tokens"] != 1536
            or assessment["check_generation"] != {
                "temperature": 1.0, "top_p": 0.95, "top_k": 64,
                "chat_template_kwargs": {"enable_thinking": True},
            }
            or not isinstance(assessment["check_prompt"], str)
            or not assessment["check_prompt"]
            or ingestion["page_schema"] != "page-evidence/v4"
            or ingestion["native_schema"] != "page-native/v3"
            or ingestion["processing_policy"] != "text-first-image-assisted/v1"
            or ingestion["normalizer_policy"] != "ocr-text-nfc-line-preserving/v1"
            or material["retry_attempts"] != 2
        ):
            raise ValueError
        return lock
    except (KeyError, TypeError, ValueError):
        raise MaterialAnalysisError("RUNTIME_LOCK_INVALID") from None


@contextmanager
def material_analysis_lock(runtime_root: Path, *, wait_seconds: float = 5):
    """教材處理串行執行；不管理常駐 Gemma 的生命週期。"""

    if not runtime_root.is_absolute() or runtime_root.is_symlink() or wait_seconds < 0:
        raise MaterialAnalysisError("RUNTIME_LAYOUT_INVALID")
    runtime_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = runtime_root / "material-analysis.lock"
    if lock_path.is_symlink():
        raise MaterialAnalysisError("RUNTIME_LAYOUT_INVALID")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise MaterialAnalysisError("RUNTIME_BUSY") from None
                time.sleep(0.05)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _reason(error: Exception) -> str:
    reason = getattr(error, "reason_code", None) or str(error)
    allowed = {
        "OCR_OUTPUT_INVALID", "OCR_LOCATOR_INVALID", "NO_USABLE_EVIDENCE",
        "PROTOCOL_LIMIT_EXCEEDED", "SEMANTIC_SERVICE_TIMEOUT",
        "SEMANTIC_SERVICE_UNAVAILABLE", "SEMANTIC_RESPONSE_INVALID",
        "SEMANTIC_OUTPUT_INVALID", "SEMANTIC_OUTPUT_TRUNCATED",
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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    pages: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    ocr_calls = 0
    with pymupdf.open(source_path) as document, ExitStack() as clients:
        http = None
        for completed, page_number in enumerate(page_numbers, start=1):
            cancellation_check()
            page = extract_page(document, source_sha256, page_number)
            try:
                route = route_page(page)
                binding = {
                    "source_sha256": source_sha256, "page": page_number,
                    "render_sha256": page["render"]["sha256"], "route": route,
                    "runtime_lock_sha256": canonical_sha256(settings["runtime_lock"]),
                }
                if route == "native_sufficient":
                    artifact = build_native_page_evidence(page, input_binding=binding, produced_at=produced_at)
                else:
                    if http is None:
                        http = clients.enter_context(semantic_client())
                    blocks = []
                    for region in vision_regions(page):
                        cancellation_check()
                        png, bbox = render_vision_region(page, region)
                        ocr_calls += 1
                        text = request_vision(http, runtime_lock=settings["runtime_lock"], png_bytes=png)
                        if text != "[no text]":
                            blocks.append({"type": "text", "text": text, "bbox": bbox})
                    artifact = build_page_evidence(page, blocks, input_binding=binding, produced_at=produced_at)
                pages.append(artifact)
            except SemanticServiceError as error:
                # 服務不可用或輸出不完整時不可假裝教材已正常處理。
                raise MaterialAnalysisError(error.reason_code) from None
            except ValueError as error:
                excluded.append(_excluded(page, _reason(error)))
            finally:
                page.pop("png_bytes", None)
                page.pop("native_evidence", None)
                report("evidence", completed, len(page_numbers))
    if not pages:
        raise MaterialAnalysisError("NO_USABLE_EVIDENCE")
    return pages, excluded, ocr_calls


def analyze_material(
    request: dict[str, Any],
    settings: dict[str, Any],
    *,
    run_id: str | None = None,
    produced_at: str | None = None,
    progress_callback: Progress | None = None,
    cancellation_check: Callable[[], None] | None = None,
    client: httpx.Client | None = None,
    semantic_call: Callable[..., dict[str, Any]] = request_semantics,
) -> dict[str, Any]:
    """Evidence → unified Gemma semantics → deterministic canonical structure。"""

    lock = validate_runtime_lock(settings.get("runtime_lock"))
    resolved_run = run_id or str(uuid4())
    resolved_time = produced_at or datetime.now(UTC).isoformat()
    report = progress_callback or (lambda _stage, _completed, _total: None)
    check_cancel = cancellation_check or (lambda: None)
    runtime_root = Path(settings["private_runtime_root"])
    with material_analysis_lock(runtime_root):
        check_cancel()
        evidence_started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="studydy-source-") as directory:
            snapshot = Path(directory) / "source.pdf"
            checked = snapshot_whole_document_request(request, snapshot)
            page_numbers = checked["page_numbers"]
            pages, excluded, ocr_calls = _page_evidence(
                snapshot,
                checked["expected_source_sha256"],
                page_numbers,
                settings,
                resolved_time,
                report,
                check_cancel,
            )
        evidence_duration_ms = round((time.monotonic() - evidence_started) * 1000)
        check_cancel()
        context = build_document_context(
            pages, page_count=len(page_numbers), excluded_pages=excluded
        )
        state = SemanticState()
        semantic_calls = 0
        semantic_started = time.monotonic()
        owned_client = client is None
        http = semantic_client() if client is None else client
        try:
            bundles = iter(build_semantic_bundles(
                context, state=state,
                fits=lambda request: material_request_fits(http, lock, request),
            ))
            def infer_bundle(bundle: dict[str, Any], depth: int = 0) -> None:
                nonlocal semantic_calls
                request_document = semantic_request(context, bundle, state)
                last_error: Exception | None = None
                for _attempt in range(lock["material_semantics"]["retry_attempts"]):
                    check_cancel()
                    candidate_state = deepcopy(state)
                    try:
                        semantic_calls += 1
                        response = semantic_call(
                            http,
                            runtime_lock=lock,
                            task="material_semantics",
                            request=request_document,
                            response_schema=semantic_response_schema([
                                row[0] for section in request_document["sections"] for row in section["evidence"]
                            ]),
                        )
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
                        logging.getLogger(__name__).info(
                            "Semantic bundle complete: evidence_count=%d page_start=%d page_end=%d "
                            "split_depth=%d attempt=%d semantic_calls=%d",
                            len(bundle["evidence"]), bundle["evidence"][0]["page"],
                            bundle["evidence"][-1]["page"], depth, _attempt + 1, semantic_calls,
                        )
                        last_error = None
                        break
                    except SemanticServiceError as error:
                        if error.reason_code == "SEMANTIC_OUTPUT_TRUNCATED":
                            evidence = bundle["evidence"]
                            logging.getLogger(__name__).warning(
                                "Semantic truncation: evidence_count=%d page_start=%d page_end=%d "
                                "split_depth=%d attempt=%d semantic_calls=%d max_tokens=%d",
                                len(evidence), evidence[0]["page"], evidence[-1]["page"],
                                depth, _attempt + 1, semantic_calls, lock["material_semantics"]["max_tokens"],
                            )
                            if len(evidence) == 1:
                                raise MaterialAnalysisError("SEMANTIC_OUTPUT_TRUNCATED") from None
                            middle = len(evidence) // 2
                            logging.getLogger(__name__).warning(
                                "Semantic split: split_depth=%d child_evidence_counts=%d,%d",
                                depth, middle, len(evidence) - middle,
                            )
                            # Strictly smaller contiguous children bound depth by ceil(log2(n)).
                            # Rebuild each request after the preceding child updates the catalog.
                            for items in (evidence[:middle], evidence[middle:]):
                                ids = {item["evidence_id"] for item in items}
                                child = {
                                    "evidence": items,
                                    "sections": [
                                        {**section, "evidence_ids": [ref for ref in section["evidence_ids"] if ref in ids]}
                                        for section in bundle["sections"]
                                        if any(ref in ids for ref in section["evidence_ids"])
                                    ],
                                }
                                infer_bundle(child, depth + 1)
                            return
                        last_error = error
                    except ValueError as error:
                        last_error = error
                if last_error is not None:
                    raise MaterialAnalysisError(_reason(last_error)) from None
            while True:
                check_cancel()
                try:
                    bundle = next(bundles)
                except StopIteration:
                    break
                infer_bundle(bundle)
                report("semantics", bundle["evidence"][-1]["page"], len(page_numbers))
        finally:
            if owned_client:
                http.close()
        semantic_duration_ms = round((time.monotonic() - semantic_started) * 1000)
    service = lock["semantic_service"]
    return build_knowledge_structure(
        context,
        state,
        source_sha256=checked["expected_source_sha256"],
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
