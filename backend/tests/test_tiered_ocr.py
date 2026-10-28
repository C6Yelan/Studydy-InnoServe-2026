import hashlib
import json
from pathlib import Path

import pymupdf
import pytest

from pdf_evidence import image_text, material_pipeline
from pdf_evidence.page_evidence import extract_page, _build_page_evidence
from pdf_evidence.source_set import collect_source_set
from runtime.material_runtime import MaterialAnalysisError


def document(path, text="", grid=False, rotation=0):
    with pymupdf.open() as pdf:
        page = pdf.new_page(width=300, height=400)
        if text:
            page.insert_text((30, 60), text)
        if grid:
            for x in (30, 150, 270):
                page.draw_line((x, 50), (x, 350))
            for y in (50, 150, 250, 350):
                page.draw_line((30, y), (270, y))
        page.set_rotation(rotation)
        pdf.save(path)


def words(text="Readable image text"):
    raw = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
    raw += "5\t1\t1\t1\t1\t1\t60\t90\t180\t30\t95\t" + text + "\n"
    return image_text.parse_words(raw, 1000, 1200)


def settings(tmp_path):
    return {"private_runtime_root": str(tmp_path / "runtime"), "runtime_lock": json.loads(
        (Path(__file__).parents[2] / "local_ai/runtime-lock.json").read_text())}


def collect(tmp_path, paths, config):
    inputs = [{"media_type": "application/pdf", "source_path": str(path),
               "expected_source_sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]
    binding = {"source_set_digest": "a" * 64, "manifest": {"items": [
        {"normalized_sha256": item["expected_source_sha256"], "page_count": 1, "analysis_scope": None}
        for item in inputs]}, "bundle": {"pages": [{"page": i + 1} for i in range(len(paths))]}}
    directory = tmp_path / "snapshots"
    directory.mkdir()
    return collect_source_set(inputs, binding, None, directory, config, "test", lambda *_: None,
                              lambda: None, material_pipeline._page_evidence)


def test_native_page_never_invokes_tesseract(tmp_path, monkeypatch):
    path = tmp_path / "native.pdf"
    document(path, "Native source remains literal x=17.")
    monkeypatch.setattr(image_text, "tesseract_words", lambda *_: pytest.fail("native invoked OCR"))
    pages, excluded, count = collect(tmp_path, [path], settings(tmp_path))
    assert not excluded and count == 0
    assert pages[0]["evidence_blocks"][0]["source"] == "native_text"


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_image_text_keeps_original_page_and_rotated_locator(tmp_path, monkeypatch, rotation):
    path = tmp_path / "scan.pdf"
    document(path, rotation=rotation)
    monkeypatch.setattr(image_text, "tesseract_words", lambda *_: words())
    with pymupdf.open(path) as pdf:
        page = extract_page(pdf, hashlib.sha256(path.read_bytes()).hexdigest(), 1)
    blocks, route, source = image_text.image_blocks(page, lambda: None)
    result = _build_page_evidence(page, blocks, input_binding={}, produced_at="test", route=route, source=source)
    evidence = result["evidence_blocks"][0]
    assert evidence["text"] == "Readable image text" and evidence["source"] == "tesseract"
    assert evidence["locator"]["page"] == 1
    assert evidence["render_region"] == pytest.approx([60, 90, 240, 120])


@pytest.mark.parametrize("text,grid", [("x = 17", False), ("value", True)])
def test_visual_pages_preserve_good_sources_and_mark_original_image(tmp_path, monkeypatch, text, grid):
    native, visual = tmp_path / "native.pdf", tmp_path / "visual.pdf"
    document(native, "Native evidence can still be used.")
    document(visual, grid=grid)
    monkeypatch.setattr(image_text, "tesseract_words", lambda *_: words(text))
    pages, excluded, count = collect(tmp_path, [native, visual], settings(tmp_path))
    assert len(pages) == 1 and count == 1
    assert excluded[0]["page"] == 2
    assert excluded[0]["reason_code"] == "OCR_VISUAL_REVIEW_REQUIRED"


def test_all_visual_pages_report_review_instead_of_publishing_text(tmp_path, monkeypatch):
    path = tmp_path / "formula.pdf"
    document(path)
    monkeypatch.setattr(image_text, "tesseract_words", lambda *_: words("x = 17"))
    with pytest.raises(MaterialAnalysisError, match="OCR_VISUAL_REVIEW_REQUIRED"):
        collect(tmp_path, [path], settings(tmp_path))


def test_visual_reader_receives_source_image_and_preserves_provenance(tmp_path, monkeypatch):
    path = tmp_path / "formula.pdf"
    document(path)
    with pymupdf.open(path) as pdf:
        page = extract_page(pdf, hashlib.sha256(path.read_bytes()).hexdigest(), 1)
    monkeypatch.setattr(image_text, "tesseract_words", lambda *_: words("x = 17"))
    def approved_reader(source, reason, check):
        assert source is page and reason == "formula" and source["png_bytes"]
        check()
        return [{"type": "text", "text": "x = 17", "bbox": [10, 10, 100, 30]}]
    blocks, route, source = image_text.image_blocks(page, lambda: None, visual_reader=approved_reader)
    result = _build_page_evidence(page, blocks, input_binding={}, produced_at="test", route=route, source=source)
    assert result["evidence_blocks"][0]["source"] == "gemma_visual"
    assert result["evidence_blocks"][0]["locator"]["page"] == 1


def test_tsv_rejects_foreign_image_coordinates():
    with pytest.raises(ValueError, match="OCR_OUTPUT_INVALID"):
        image_text.parse_words("level\ttext\tleft\ttop\twidth\theight\n5\tbad\t-1\t0\t5\t5\n", 100, 100)


def test_text_image_cache_resumes_without_running_ocr_again(tmp_path, monkeypatch):
    path = tmp_path / "scan.pdf"
    document(path)
    monkeypatch.setattr(image_text, "tesseract_words", lambda *_: words())
    config = settings(tmp_path)
    cache = {}
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    args = (path, digest, [1], config, "test", lambda *_: None, lambda: None)
    first, _, count = material_pipeline._page_evidence(*args, save_page=lambda n, page: cache.update({n: page}))
    assert count == 1 and first[0]["route"] == "tesseract_text"
    monkeypatch.setattr(image_text, "tesseract_words", lambda *_: pytest.fail("cached OCR repeated"))
    resumed, _, count = material_pipeline._page_evidence(*args, load_page=cache.get)
    assert resumed == first and count == 0
    config["runtime_lock"]["ingestion"]["ocr"]["classification_policy"] = "changed"
    with pytest.raises(MaterialAnalysisError, match="ANALYSIS_CHECKPOINT_INVALID"):
        material_pipeline._page_evidence(*args, load_page=cache.get)


def test_saved_native_policy_stays_frozen_and_does_not_gain_ocr(tmp_path, monkeypatch):
    from copy import deepcopy
    from runtime.material_runtime import runtime_binding, runtime_binding_is_valid
    config = settings(tmp_path)
    config["runtime_lock"]["ingestion"].pop("ocr")
    config["runtime_lock"]["ingestion"]["processing_policy"] = "native-text-only/v1"
    before = deepcopy(config)
    binding = runtime_binding(config)
    assert runtime_binding_is_valid(binding) and binding["policy"] == "native-text-semantics-product/v1"
    path = tmp_path / "scan.pdf"
    document(path)
    monkeypatch.setattr(image_text, "tesseract_words", lambda *_: pytest.fail("frozen native run invoked OCR"))
    pages, excluded, count = material_pipeline._page_evidence(path, hashlib.sha256(path.read_bytes()).hexdigest(),
        [1], config, "test", lambda *_: None, lambda: None)
    assert not pages and excluded[0]["reason_code"] == "NO_USABLE_EVIDENCE" and count == 0
    assert config == before


def test_tesseract_process_is_cancelled_without_waiting_for_page_timeout(tmp_path, monkeypatch):
    import subprocess
    import sys
    actual = subprocess.Popen
    children = []
    def process(command, **kwargs):
        assert command[-5:] == ["-l", "chi_tra+eng", "--psm", "3", "tsv"]
        child = actual([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(image_text.subprocess, "Popen", process)
    def cancelled():
        raise RuntimeError("cancelled")
    with pytest.raises(RuntimeError, match="cancelled"):
        image_text.tesseract_words({"png_bytes": b"synthetic"}, cancelled)
    assert children[0].poll() is not None


def test_image_capabilities_and_zip_limit_match_existing_upload_contract(tmp_path, monkeypatch):
    from starlette.requests import Request
    from runtime.api import app as api
    from runtime.media_sources import upload_limit
    monkeypatch.setattr(api, "media_available", lambda: True)
    monkeypatch.setattr(api, "normalizer_available", lambda: True)
    monkeypatch.setattr(api.request_context, "trusted_learner", lambda *_: None)
    application = api.create_app(api.ApiSettings(profile="local", public_origin="http://127.0.0.1:8000",
        secure_cookie=False, local_config=settings(tmp_path)))
    endpoint = next(route.endpoint for route in application.routes if route.path == "/v1/source-capabilities")
    value = endpoint(Request({"type": "http", "query_string": b"", "headers": []})).model_dump()
    images = [entry for entry in value["formats"] if entry["kind"] == "image"]
    assert {entry["extension"] for entry in images} == {".png", ".jpg", ".jpeg", ".webp"}
    assert all(entry["max_bytes"] == 100 * 1024 * 1024 for entry in images)
    assert value["max_images"] == 50
    assert upload_limit("images.zip", "application/zip") == 100 * 1024 * 1024
