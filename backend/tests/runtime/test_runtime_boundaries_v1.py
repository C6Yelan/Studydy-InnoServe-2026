from copy import deepcopy
from contextlib import nullcontext
from pathlib import Path

import pytest

import runtime.api.app as api_app
import runtime.local_app as local_app
import runtime.local_runtime as local_runtime
import runtime.workers as workers_module
from runtime.material_processing import MaterialProcessingError, runtime_binding


def _environment(tmp_path: Path) -> dict[str, str]:
    return {
        "STUDYDY_PROFILE": "local",
        "STUDYDY_PUBLIC_ORIGIN": "http://127.0.0.1:4175",
        "STUDYDY_SECURE_COOKIE": "false",
        "STUDYDY_LOCAL_RUNTIME_ROOT": str(tmp_path / "installed"),
    }


def test_local_config_pins_runtime_and_rejects_unknown_assessment_fields(tmp_path):
    config = local_app.read_local_ai_config_from_environment(_environment(tmp_path))
    assert set(config) == {
        "private_runtime_root", "runtime_lock",
    }
    assert config["runtime_lock"]["python"] == "3.12"
    assert config["runtime_lock"]["semantic_service"]["model_id"] == "google/gemma-4-31B-it-qat-w4a16-ct"
    tampered = deepcopy(config)
    tampered["runtime_lock"]["assessment"]["unknown_setting"] = True
    from pdf_evidence.material_pipeline import MaterialAnalysisError, validate_runtime_lock
    with pytest.raises(MaterialAnalysisError):
        validate_runtime_lock(tampered["runtime_lock"])
    runtime_binding(tampered)


@pytest.mark.parametrize("field,value", [("model_id", "example/other-model"), ("model_revision", "a" * 40)])
def test_stored_runtime_binding_rejects_wrong_identity_even_with_valid_hash(tmp_path, field, value):
    """重算 binding hash 不能讓未批准的模型或 revision 通過。"""
    from pdf_evidence.ocr_page_evidence import canonical_sha256
    from runtime.storage.knowledge_structures import runtime_binding_is_valid
    binding = runtime_binding(local_app.read_local_ai_config_from_environment(_environment(tmp_path)))
    assert runtime_binding_is_valid(binding)
    binding[field] = value
    binding["runtime_binding_sha256"] = canonical_sha256({
        key: item for key, item in binding.items() if key != "runtime_binding_sha256"
    })
    assert not runtime_binding_is_valid(binding)


def test_local_app_composition_validates_settings_without_ai_then_starts_uvicorn(tmp_path, monkeypatch):
    observed = []
    import runtime.material_processing as processing
    monkeypatch.setattr(processing, "preflight_semantic_service", lambda _: pytest.fail("startup must not contact AI"))
    app = local_app.create_local_app(
        profile="local", public_origin="http://127.0.0.1:4175", secure_cookie=False,
        local_config=local_app.read_local_ai_config_from_environment(_environment(tmp_path)), dsn=None,
    )
    assert app.version == "3.0.0"
    assert observed == []

    monkeypatch.setattr(local_app, "create_local_app", lambda **arguments: observed.append(("create", arguments)) or app)
    monkeypatch.setattr(local_app.uvicorn, "run", lambda created, **arguments: observed.append(("run", created, arguments)))
    local_app.run_local_app(environment=_environment(tmp_path), port=8183)
    assert observed[-1][0] == "run"


def test_runtime_verify_checks_existing_gemma_without_child_process(tmp_path, monkeypatch):
    observed = []
    monkeypatch.setattr(local_runtime, "runtime_preflight", lambda _: observed.append("gemma-preflight"))
    assert local_runtime.verify_local_runtime({"private_runtime_root": str(tmp_path)}) == {"status": "succeeded", "command": "verify"}
    assert observed == ["gemma-preflight"]


def test_worker_recovers_once_and_does_not_own_model_lifecycle(monkeypatch):
    events = []
    for name in ("run_next_set", "normalize_next", "reconcile_new_artifacts", "reconcile_removed_material_analysis", "reconcile_published_checkpoints"):
        monkeypatch.setattr(workers_module, name, lambda **_: False)
    monkeypatch.setattr(workers_module, "recover_interrupted_material_runs", lambda **_: events.append("recover") or 0)
    monkeypatch.setattr(workers_module, "finish_material_discards", lambda **_: None)
    monkeypatch.setattr(workers_module, "claim_next_material_processing_run", lambda **_: None)
    worker = workers_module.RuntimeWorkers(None, {})
    worker.start()
    worker.stop()
    assert events == ["recover"]
    assert not hasattr(workers_module, "start_assessment_process")
    assert not hasattr(workers_module, "material_analysis_lock")


def test_backend_does_not_spawn_model_processes():
    root = Path(__file__).parents[3]
    production = "\n".join(path.read_text(encoding="utf-8") for path in (root / "backend/src").rglob("*.py"))
    production = production.replace((root / "backend/src/document_normalization/converter.py").read_text(), "")
    assert "subprocess.Popen" not in production
    assert not (root / "backend/src/runtime/command_semantics.py").exists()


def test_native_binding_and_saved_binding_remain_readable(tmp_path):
    from pdf_evidence.ocr_page_evidence import canonical_sha256
    from runtime.storage.knowledge_structures import runtime_binding_is_valid
    current = runtime_binding(local_app.read_local_ai_config_from_environment(_environment(tmp_path)))
    assert current['ingestion'] == {'policy': 'native-text-only/v1'}
    assert runtime_binding_is_valid(current)
    saved = deepcopy(current)
    saved['ingestion'] = {'policy': 'text-first-image-assisted/v1', 'vision_model_id': current['model_id']}
    saved['runtime_binding_sha256'] = canonical_sha256({k: v for k, v in saved.items() if k != 'runtime_binding_sha256'})
    assert runtime_binding_is_valid(saved)
