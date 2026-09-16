import hashlib
import json
from pathlib import Path

import pymupdf
import httpx

import pdf_evidence.material_pipeline as pipeline


class Client:
    def post(self, url, **kwargs):
        assert url.endswith("/tokenize")
        return httpx.Response(200, json={"count": 100, "max_model_len": 32768}, request=httpx.Request("POST", url))


def _settings(tmp_path: Path) -> dict:
    lock = json.loads((Path(__file__).parents[2] / "local_ai/runtime-lock.json").read_text())
    return {
        "private_runtime_root": str(tmp_path / "runtime"),
        "runtime_lock": lock,
    }


def _pdf(path: Path, pages: int, *, blank_first: bool = False) -> None:
    document = pymupdf.open()
    for page_number in range(1, pages + 1):
        page = document.new_page(width=612, height=792)
        if not (blank_first and page_number == 1):
            if page_number == 1:
                page.insert_text((72, 72), "Public Algorithms", fontsize=20)
            page.insert_text((72, 120), f"Public lesson {page_number} explains a deterministic learning concept with evidence.", fontsize=12)
    document.save(path)
    document.close()


def _request(path: Path) -> dict:
    return {
        "media_type": "application/pdf",
        "source_path": str(path),
        "expected_source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def _semantic(calls: list[dict]):
    def call(_client, **arguments):
        request = arguments["request"]
        calls.append(request)
        allowed = arguments["response_schema"]["properties"]["concepts"]["items"]["properties"]["c"]["items"]["properties"]["s"]["items"]["enum"]
        assert allowed == [row[0] for section in request["sections"] for row in section["evidence"]]
        first = next(item for section in request["sections"] for item in section["evidence"] if item[2] != "heading")
        return {
            "concepts": [{
                "k": "algorithm", "l": "Algorithm", "a": [],
                "c": [{"m": None, "s": [first[0]]}],
            }],
            "relations": [],
        }
    return call


def test_eight_native_pages_use_one_unified_semantic_call_without_ocr(tmp_path, monkeypatch):
    source = tmp_path / "eight.pdf"
    _pdf(source, 8)
    monkeypatch.setattr(pipeline, "request_vision", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("native PDF must not load OCR")))
    calls: list[dict] = []
    structure = pipeline.analyze_material(
        _request(source), _settings(tmp_path), client=Client(), semantic_call=_semantic(calls)
    )
    assert structure["metrics"]["semantic_calls"] == 1
    assert structure["metrics"]["ocr_calls"] == 0
    assert len(calls) == 1
    assert len({item[1] for section in calls[0]["sections"] for item in section["evidence"]}) == 8
    assert structure["initial_learning_path"][0]["concept_id"] == structure["concepts"][0]["concept_id"]


def test_multiple_bundles_report_incremental_semantic_progress(tmp_path):
    """後面頁面尚未處理時，不能先把語意進度回報為整份完成。"""
    source = tmp_path / "three.pdf"
    _pdf(source, 3)
    class BudgetClient:
        def post(self, url, **kwargs):
            request = json.loads(kwargs["json"]["messages"][-1]["content"].split("\nINPUT:\n", 1)[1])
            count = 700 * sum(len(section["evidence"]) for section in request["sections"])
            return httpx.Response(200, json={"count": count, "max_model_len": 32768}, request=httpx.Request("POST", url))
    calls = []
    progress = []
    pipeline.analyze_material(_request(source), _settings(tmp_path), client=BudgetClient(),
                              semantic_call=_semantic(calls), progress_callback=lambda stage, done, total: progress.append((stage, done, total)))
    assert len(calls) > 1
    assert {row[1] for call in calls for section in call["sections"] for row in section["evidence"]} == {1, 2, 3}
    completed = [done for stage, done, _total in progress if stage == "semantics"]
    assert completed == sorted(completed)
    assert completed[0] < 3 and completed[-1] == 3


def test_vision_failure_fails_closed_before_semantics(tmp_path, monkeypatch):
    import pytest
    from runtime.semantic_service import SemanticServiceError
    source = tmp_path / "mixed.pdf"
    _pdf(source, 2, blank_first=True)
    def fail(*args, **kwargs):
        raise SemanticServiceError("SEMANTIC_SERVICE_UNAVAILABLE")
    monkeypatch.setattr(pipeline, "request_vision", fail)
    calls = []
    with pytest.raises(pipeline.MaterialAnalysisError, match="SEMANTIC_SERVICE_UNAVAILABLE"):
        pipeline.analyze_material(_request(source), _settings(tmp_path), client=Client(), semantic_call=_semantic(calls))
    assert calls == []


def test_cancellation_before_semantics_never_opens_a_model_request(tmp_path, monkeypatch):
    import pytest
    source = tmp_path / "cancel.pdf"; _pdf(source, 2)
    class Cancelled(RuntimeError): pass
    requested = False
    def report(stage, done, total):
        nonlocal requested
        if stage == "evidence" and done == total: requested = True
    def check():
        if requested: raise Cancelled()
    monkeypatch.setattr(pipeline, "semantic_client", lambda: (_ for _ in ()).throw(AssertionError("no model client after cancellation")))
    with pytest.raises(Cancelled):
        pipeline.analyze_material(_request(source), _settings(tmp_path), progress_callback=report, cancellation_check=check)


def test_cancellation_stops_semantic_retries_and_next_bundles(tmp_path, monkeypatch):
    import pytest
    source = tmp_path / "cancel.pdf"; _pdf(source, 3)
    class Cancelled(RuntimeError): pass
    for fail_first in (True, False):
        requested = False; calls = []
        def check():
            if requested: raise Cancelled()
        def semantic(client, **arguments):
            nonlocal requested
            requested = True
            if fail_first:
                calls.append(arguments)
                raise ValueError("synthetic invalid model response")
            return _semantic(calls)(client, **arguments)
        original_bundles = pipeline.build_semantic_bundles
        def two_bundles(*args, **kwargs):
            first = next(iter(original_bundles(*args, **kwargs)))
            yield first
            yield first
        with monkeypatch.context() as patch:
            patch.setattr(pipeline, "build_semantic_bundles", two_bundles)
            with pytest.raises(Cancelled):
                pipeline.analyze_material(_request(source), _settings(tmp_path), client=Client(), semantic_call=semantic, cancellation_check=check)
        assert len(calls) == 1


def test_cancellation_at_evidence_checkpoint_does_not_start_the_next_page(tmp_path, monkeypatch):
    import pytest
    source = tmp_path / "cancel.pdf"; _pdf(source, 3)
    class Cancelled(RuntimeError): pass
    pages = []
    original = pipeline.extract_page
    def extract(*args):
        pages.append(args[-1]); return original(*args)
    monkeypatch.setattr(pipeline, "extract_page", extract)
    def report(*_args): raise Cancelled()
    with pytest.raises(Cancelled):
        pipeline.analyze_material(_request(source), _settings(tmp_path), client=Client(), progress_callback=report)
    assert pages == [1]


def _rows(request):
    return [row for section in request['sections'] for row in section['evidence']]


def _all_claims(request):
    return {'concepts': [{'k': 'lesson', 'l': 'Lesson', 'a': [],
                         'c': [{'m': None, 's': [row[0]]} for row in _rows(request)]}],
            'relations': []}


def test_truncated_bundle_splits_in_order_and_accumulates_only_successful_children(tmp_path, monkeypatch):
    from runtime.semantic_service import SemanticServiceError
    source = tmp_path / 'split.pdf'; _pdf(source, 4)
    calls = []; extractions = []
    original = pipeline._page_evidence
    def extract(*args, **kwargs):
        extractions.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(pipeline, '_page_evidence', extract)
    def semantic(_client, **kwargs):
        request = kwargs['request']; calls.append(request)
        if len(calls) == 1:
            raise SemanticServiceError('SEMANTIC_OUTPUT_TRUNCATED')
        return _all_claims(request)
    result = pipeline.analyze_material(_request(source), _settings(tmp_path), client=Client(), semantic_call=semantic)
    assert len(calls) == 3
    parent = _rows(calls[0]); midpoint = len(parent) // 2
    assert _rows(calls[1]) == parent[:midpoint]
    assert _rows(calls[2]) == parent[midpoint:]
    assert calls[1]['existing_concepts'] == []
    assert calls[2]['existing_concepts']
    assert len(extractions) == 1
    assert result['metrics']['semantic_calls'] == 3
    assert result['metrics']['ocr_calls'] == 0
    assert result['initial_learning_path']
    assert len(result['evidence']) == len(parent)
    assert len(result['concepts'][0]['claims']) == len(parent)


def test_recursive_truncation_is_a_finite_deterministic_contiguous_partition(tmp_path, caplog):
    from runtime.semantic_service import SemanticServiceError
    source = tmp_path / 'recursive.pdf'; _pdf(source, 4)
    calls = []; successful = []
    def semantic(_client, **kwargs):
        request = kwargs['request']; rows = _rows(request); calls.append([row[0] for row in rows])
        if len(rows) > 1: raise SemanticServiceError('SEMANTIC_OUTPUT_TRUNCATED')
        successful.extend(rows)
        return _all_claims(request)
    result = pipeline.analyze_material(_request(source), _settings(tmp_path), client=Client(), semantic_call=semantic)
    def visits(ids):
        if len(ids) == 1: return [ids]
        middle = len(ids) // 2
        return [ids] + visits(ids[:middle]) + visits(ids[middle:])
    assert calls == visits(calls[0])
    assert [row[0] for row in successful] == calls[0]
    assert result['metrics']['semantic_calls'] == 2 * len(calls[0]) - 1
    assert 'split_depth=' in caplog.text
    assert 'Public lesson' not in caplog.text


def test_single_evidence_truncation_fails_without_retry_or_partial_structure(tmp_path, monkeypatch):
    import pytest
    from runtime.semantic_service import SemanticServiceError
    source = tmp_path / 'minimum.pdf'; _pdf(source, 4)
    calls = []; successful = []
    def semantic(_client, **kwargs):
        request = kwargs['request']; rows = _rows(request); calls.append(rows)
        # Successful left half, but rightmost leaf always truncates.
        if any(row[1] == 4 for row in rows):
            raise SemanticServiceError('SEMANTIC_OUTPUT_TRUNCATED')
        successful.extend(rows)
        return _all_claims(request)
    monkeypatch.setattr(pipeline, 'build_knowledge_structure', lambda *_a, **_k: pytest.fail('cannot publish incomplete semantics'))
    with pytest.raises(pipeline.MaterialAnalysisError, match='^SEMANTIC_OUTPUT_TRUNCATED$'):
        pipeline.analyze_material(_request(source), _settings(tmp_path), client=Client(), semantic_call=semantic)
    assert successful
    assert len(calls[-1]) == 1
    assert sum(rows == calls[-1] for rows in calls) == 1
    assert len(calls) <= 2 * len(calls[0]) - 1


def test_other_semantic_errors_keep_identical_request_retries_without_split(tmp_path):
    import pytest
    from runtime.semantic_service import SemanticServiceError
    source = tmp_path / 'retry.pdf'; _pdf(source, 3)
    for reason in ['SEMANTIC_SERVICE_TIMEOUT', 'SEMANTIC_SERVICE_UNAVAILABLE', 'SEMANTIC_RESPONSE_INVALID']:
        for recover in [True, False]:
            calls = []
            def semantic(_client, **kwargs):
                calls.append(kwargs['request'])
                if len(calls) == 1 or not recover: raise SemanticServiceError(reason)
                return _all_claims(kwargs['request'])
            if recover:
                result = pipeline.analyze_material(_request(source), _settings(tmp_path), client=Client(), semantic_call=semantic)
                assert result['metrics']['semantic_calls'] == 2
            else:
                with pytest.raises(pipeline.MaterialAnalysisError, match=reason):
                    pipeline.analyze_material(_request(source), _settings(tmp_path), client=Client(), semantic_call=semantic)
            assert len(calls) == 2
            assert calls[0] == calls[1]
            assert calls[1]['existing_concepts'] == []
