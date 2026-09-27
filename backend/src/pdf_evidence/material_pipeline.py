from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
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
from runtime.semantic_service import (
    SemanticServiceError,
    material_request_fits,
    request_semantics,
    semantic_client,
)

from .ocr_page_evidence import (
    build_native_page_evidence,
    canonical_sha256,
    extract_page,
    route_page,
)
from .source_set import collect_source_set


Progress = Callable[[str, int, int], None]


class MaterialAnalysisError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def validate_runtime_lock(lock: Any, *, assessment: bool = True) -> dict[str, Any]:
    """依實際用途驗證目前 v1 的元件契約。"""

    try:
        if not isinstance(lock, dict) or set(lock) - {'material_review'} != {
            "schema", "python", "ingestion", "semantic_service",
            "material_semantics", "assessment",
        }:
            raise ValueError
        if 'material_review' in lock:
            review = lock['material_review']
            if (set(review) != {'policy', 'prompt', 'max_tokens', 'generation'}
                or review['policy'] != 'material-review/v1' or not isinstance(review['prompt'], str)
                or not review['prompt'].strip() or type(review['max_tokens']) is not int
                or not 1 <= review['max_tokens'] < lock['semantic_service']['max_model_len']
                or review['generation'] != lock['material_semantics']['generation']):
                raise ValueError
        semantic = lock["semantic_service"]
        material = lock["material_semantics"]
        assessment_settings = lock["assessment"]
        ingestion = lock["ingestion"]
        if (
            lock["schema"] != "studydy-runtime-lock/v1"
            or lock["python"] != "3.12"
            or set(ingestion) != {
                "page_schema", "native_schema", "processing_policy", "normalizer_policy", "render",
            }
            or ingestion["render"] != {"dpi": 200, "colorspace": "RGB", "format": "PNG"}
            or set(semantic) != {
                "model_id", "revision", "api_protocol", "base_url", "max_model_len",
                "max_num_seqs", "server", "authentication",
            }
            or not isinstance(semantic["model_id"], str) or not semantic["model_id"].strip()
            or not isinstance(semantic["revision"], str) or not semantic["revision"].strip()
            or semantic["api_protocol"] != "openai-chat-completions/v1"
            or semantic["base_url"] != "http://127.0.0.1:18000"
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
            or material["request_schema"] != "material-semantics-request/v1"
            or material["response_schema"] != "material-semantics-response/v1"
            or material["bundle_policy"] != "contiguous-evidence-new-input/v1"
            or material["max_new_input_tokens"] != 1536
            or material["max_tokens"] != 8192
            or material["generation"] != {
                "temperature": 1.0, "top_p": 0.95, "top_k": 64,
                "chat_template_kwargs": {"enable_thinking": True},
            }
            or not isinstance(material["prompt"], str)
            or not material["prompt"]
            or (assessment and (set(assessment_settings) != {
                "request_schema", "response_schema", "public_schema", "private_schema",
                "provenance_schema", "policy", "candidate_count", "option_count",
                "max_tokens", "generation", "prompt", "check_max_tokens", "check_generation", "check_prompt",
            }
            or assessment_settings["request_schema"] != "assessment-semantics-request/v1"
            or assessment_settings["response_schema"] != "assessment-semantics-response/v1"
            or assessment_settings["public_schema"] != "single-choice-assessment/v1"
            or assessment_settings["private_schema"] != "single-choice-answer/v1"
            or assessment_settings["provenance_schema"] != "assessment-generation-provenance/v1"
            or assessment_settings["policy"] != "source-span-single-choice/v1"
            or assessment_settings["candidate_count"] != 3
            or assessment_settings["option_count"] != 4
            or assessment_settings["max_tokens"] != 4096
            or assessment_settings["generation"] != {
                "temperature": 1.0, "top_p": 0.95, "top_k": 64,
                "chat_template_kwargs": {"enable_thinking": True},
            }
            or not isinstance(assessment_settings["prompt"], str)
            or not assessment_settings["prompt"]
            or assessment_settings["check_max_tokens"] != 1536
            or assessment_settings["check_generation"] != {
                "temperature": 1.0, "top_p": 0.95, "top_k": 64,
                "chat_template_kwargs": {"enable_thinking": True},
            }
            or not isinstance(assessment_settings["check_prompt"], str)
            or not assessment_settings["check_prompt"]))
            or ingestion["page_schema"] != "page-evidence/v1"
            or ingestion["native_schema"] != "page-native/v1"
            or ingestion["processing_policy"] != "native-text-only/v1"
            or ingestion["normalizer_policy"] != "ocr-text-nfc-line-preserving/v1"
            or material["retry_attempts"] != 2
        ):
            raise ValueError
        return lock
    except (KeyError, TypeError, ValueError):
        raise MaterialAnalysisError("RUNTIME_LOCK_INVALID") from None


def _reason(error: Exception) -> str:
    reason = getattr(error, "reason_code", None) or str(error)
    allowed = {
        "CHILD_EXITED", "CHILD_TIMEOUT", "CHILD_RESPONSE_INVALID",
        "OCR_OUTPUT_INVALID", "OCR_LOCATOR_INVALID", "NO_USABLE_EVIDENCE",
        "PROTOCOL_LIMIT_EXCEEDED", "SEMANTIC_SERVICE_TIMEOUT",
        "SEMANTIC_SERVICE_UNAVAILABLE", "SEMANTIC_RESPONSE_INVALID",
        "SEMANTIC_OUTPUT_INVALID", "SEMANTIC_OUTPUT_TRUNCATED",
        "SEMANTIC_INPUT_TOO_LARGE", "SEMANTIC_BUDGET_EXHAUSTED",
        "KNOWLEDGE_STRUCTURE_INVALID", "MATERIAL_IDENTITY_INVALID",
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
    with pymupdf.open(source_path) as document:
        for completed, page_number in enumerate(page_numbers, start=1):
            cancellation_check()
            page = extract_page(document, source_sha256, page_number)
            try:
                binding = {
                    "source_sha256": source_sha256, "page": page_number,
                    "render_sha256": page["render"]["sha256"], "route": route_page(page),
                    "runtime_lock_sha256": canonical_sha256(settings["runtime_lock"]),
                }
                pages.append(build_native_page_evidence(page, input_binding=binding, produced_at=produced_at))
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
    source_inputs: list[dict[str, Any]],
    input_binding: dict[str, Any],
    settings: dict[str, Any],
    *,
    run_id: str | None = None,
    produced_at: str | None = None,
    progress_callback: Progress | None = None,
    cancellation_check: Callable[[], None] | None = None,
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
    source_digest = input_binding["source_set_digest"]
    restored = analysis_archive.load_checkpoint() if analysis_archive is not None else None
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
        if cursor and not restored.get("restart_semantics"):
            report("semantics", context["evidence"][cursor - 1]["page"], len(page_numbers))
    else:
        evidence_started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="studydy-source-") as directory:
            page_numbers = list(range(1, len(input_binding["bundle"]["pages"]) + 1))
            pages, excluded, ocr_calls = collect_source_set(
                source_inputs, input_binding, base_structure, Path(directory),
                settings, resolved_time, report, check_cancel, _page_evidence,
            )
        evidence_duration_ms = round((time.monotonic() - evidence_started) * 1000)
        check_cancel()
        context = build_document_context(
            pages, page_count=len(page_numbers), excluded_pages=excluded,
            source_pages=input_binding["bundle"]["pages"],
        )
        # 掃描頁上的版權／頁尾文字不能使純影像教材被當成可分析來源。
        if not any(
            item["evidence_id"] not in context["non_content_evidence_ids"]
            for item in context["evidence"]
        ):
            raise MaterialAnalysisError("NO_USABLE_EVIDENCE")
        if base_structure is not None:
            from knowledge_map.source_identity import seed_incremental_state
            state = seed_incremental_state(base_structure, context, input_binding)
            context["incremental"] = True
            state.rejected_claims = base_structure["metrics"]["rejected_claims"]
            state.rejected_relations = base_structure["metrics"]["rejected_relations"]
            state.literal_repairs = base_structure["metrics"]["literal_repairs"]
        else:
            state = SemanticState()
        cursor = semantic_calls = previous_semantic_ms = 0
    if restored is not None and restored.get("restart_semantics"):
        if base_structure is not None:
            from knowledge_map.source_identity import seed_incremental_state
            state = seed_incremental_state(base_structure, context, input_binding)
            state.rejected_claims = base_structure["metrics"]["rejected_claims"]
            state.rejected_relations = base_structure["metrics"]["rejected_relations"]
            state.literal_repairs = base_structure["metrics"]["literal_repairs"]
        else:
            state = SemanticState()
        cursor = 0
    semantic_started = time.monotonic()
    complete = bool(restored and restored.get("complete"))
    evidence_indices = {
        item["evidence_id"]: index
        for index, item in enumerate(context["evidence"])
    }

    def save_checkpoint():
        if analysis_archive is not None:
            analysis_archive.save_checkpoint({
                "context": context,
                "state": asdict(state),
                "cursor": cursor,
                "complete": complete,
                "source_sha256": source_digest,
                "semantic_calls": semantic_calls,
                "ocr_calls": ocr_calls,
                "evidence_duration_ms": evidence_duration_ms,
                "semantic_duration_ms": previous_semantic_ms + round(
                    (time.monotonic() - semantic_started) * 1000
                ),
            })
    save_checkpoint()
    owned_client = client is None and not complete
    http = semantic_client() if owned_client else client
    try:
        bundles = iter(build_semantic_bundles(
            context, state=state,
            fits=lambda request: material_request_fits(http, lock, request),
            minimum_page=base_structure["page_count"] + 1 if base_structure else 1,
            minimum_evidence_index=cursor,
        ))
        while True:
            check_cancel()
            try:
                bundle = next(bundles)
            except StopIteration:
                complete = True
                # 尾頁列為 excluded 時，完成進度仍包含整份文件。
                report("semantics", len(page_numbers), len(page_numbers))
                break
            except ValueError as error:
                # 分批器也可能在呼叫模型前拒絕輸入，保留可公開的原因碼。
                raise MaterialAnalysisError(_reason(error)) from None
            request_document = semantic_request(context, bundle, state)
            last_error: Exception | None = None
            for _attempt in range(lock["material_semantics"]["retry_attempts"]):
                check_cancel()
                candidate_state = deepcopy(state)
                try:
                    response = (
                        analysis_archive.reuse_review_response(request_document)
                        if analysis_archive is not None else None
                    )
                    if response is None:
                        semantic_calls += 1
                        if analysis_archive is not None:
                            analysis_archive.prepare_call(semantic_calls, request_document)
                        response = semantic_call(
                            http,
                            runtime_lock=lock,
                            task="material_semantics",
                            request=request_document,
                            response_schema=semantic_response_schema([
                                row[0]
                                for section in request_document["sections"]
                                for row in section["evidence"]
                            ], incremental=base_structure is not None),
                        )
                    if analysis_archive is not None:
                        analysis_archive.save_response(semantic_calls, request_document, response)
                    if base_structure is not None:
                        if (
                            not isinstance(response, dict)
                            or type(response.get("review_required")) is not bool
                        ):
                            raise ValueError("SEMANTIC_OUTPUT_INVALID")
                        candidate_state.source_review_required |= response["review_required"]
                        response = {
                            key: value for key, value in response.items()
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
                    state.source_review_required = candidate_state.source_review_required
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
            report("semantics", bundle["evidence"][-1]["page"], len(page_numbers))
    finally:
        if owned_client:
            http.close()
        save_checkpoint()
    semantic_duration_ms = previous_semantic_ms + round((time.monotonic() - semantic_started) * 1000)
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
