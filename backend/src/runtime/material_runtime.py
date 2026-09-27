"""教材接續共用一套設定比對；完整 lock 留作原工作稽核，assessment 不參與相容性。"""
from copy import deepcopy
import os
from pathlib import Path
from typing import Any

from pdf_evidence.ocr_page_evidence import canonical_sha256
from pdf_evidence.material_pipeline import MaterialAnalysisError, validate_runtime_lock
from .semantic_service import SemanticServiceError, preflight_semantic_service


_CONFIG_KEYS = {"private_runtime_root", "runtime_lock"}
_RUNTIME_COMPONENTS = {"layout", "runtime_lock", "semantic_service"}
_RUNTIME_REASONS = {
    "LOCAL_RUNTIME_MISSING", "LOCAL_RUNTIME_UNSAFE_TARGET", "LOCAL_RUNTIME_NOT_EXECUTABLE",
    "LOCAL_RUNTIME_VERSION_MISMATCH", "LOCAL_RUNTIME_SMOKE_FAILED",
    "LOCAL_RUNTIME_SETTINGS_MISMATCH", "LOCAL_RUNTIME_LOCK_MISMATCH", "LOCAL_RUNTIME_WRITE_FAILED",
}


class MaterialRuntimeError(RuntimeError):
    """設定／環境錯誤只攜帶固定公開原因碼，不依賴工作執行模組。"""

    def __init__(self, component: str, reason: str) -> None:
        super().__init__("MATERIAL_CONFIGURATION_INVALID")
        self.component = component if component in _RUNTIME_COMPONENTS else None
        self.reason = reason if reason in _RUNTIME_REASONS else None


def runtime_binding(local_config: Any) -> dict[str, Any]:
    if not isinstance(local_config, dict) or set(local_config) != _CONFIG_KEYS:
        raise MaterialRuntimeError("layout", "LOCAL_RUNTIME_SETTINGS_MISMATCH")
    try:
        root = Path(local_config["private_runtime_root"])
        if not root.is_absolute() or root.is_symlink():
            raise ValueError
        lock = validate_runtime_lock(local_config["runtime_lock"], assessment=False)
    except (IndexError, KeyError, MaterialAnalysisError, TypeError, ValueError):
        raise MaterialRuntimeError("runtime_lock", "LOCAL_RUNTIME_LOCK_MISMATCH") from None
    binding = {
        "schema": "material-runtime-binding/v1",
        "python": lock["python"],
        "runtime_lock_sha256": canonical_sha256(lock),
        "model_id": lock["semantic_service"]["model_id"],
        "model_revision": lock["semantic_service"]["revision"],
        "semantic_service": {
            "base_url": lock["semantic_service"]["base_url"],
            "max_model_len": lock["semantic_service"]["max_model_len"],
            "server": deepcopy(lock["semantic_service"]["server"]),
        },
        "ingestion": {"policy": lock["ingestion"]["processing_policy"]},
        "policy": "native-text-semantics-product/v1",
    }
    binding["runtime_binding_sha256"] = canonical_sha256(binding)
    return binding


def _prepare_runtime_root(value: str) -> None:
    path = Path(value)
    if not path.is_absolute() or path.is_symlink():
        raise MaterialRuntimeError("layout", "LOCAL_RUNTIME_UNSAFE_TARGET")
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            raise OSError
    except OSError:
        raise MaterialRuntimeError("layout", "LOCAL_RUNTIME_WRITE_FAILED") from None


def runtime_preflight(local_config: Any) -> dict[str, Any]:
    binding = runtime_binding(local_config)
    assert isinstance(local_config, dict)
    try:
        preflight_semantic_service(local_config["runtime_lock"])
    except SemanticServiceError as error:
        reason = "LOCAL_RUNTIME_SETTINGS_MISMATCH" if error.reason_code.endswith(("CONFIG_INVALID", "IDENTITY_MISMATCH")) else "LOCAL_RUNTIME_MISSING"
        raise MaterialRuntimeError("semantic_service", reason) from None
    _prepare_runtime_root(local_config["private_runtime_root"])
    return binding


def runtime_binding_is_valid(value: Any) -> bool:
    """驗證目前 HTTP runtime binding 的形狀與內容雜湊。"""
    def digest(value):
        return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)

    try:
        if not isinstance(value, dict) or set(value) != {
            "schema", "python", "runtime_lock_sha256", "model_id", "model_revision",
            "semantic_service", "ingestion", "policy", "runtime_binding_sha256",
        }:
            return False
        identity = {key: item for key, item in value.items() if key != "runtime_binding_sha256"}
        if (value["schema"] != "material-runtime-binding/v1" or value["python"] != "3.12"
            or value["runtime_binding_sha256"] != canonical_sha256(identity)
            or not digest(value["runtime_lock_sha256"])
            or value["policy"] != "native-text-semantics-product/v1"
            or value["ingestion"] != {"policy": "native-text-only/v1"}):
            return False
        service = value["semantic_service"]
        if not isinstance(service, dict):
            return False
        return (all(isinstance(value[k], str) and value[k].strip() for k in ("model_id", "model_revision"))
                and service == {
                    "base_url": "http://127.0.0.1:18000", "max_model_len": 32768,
                    "server": {"package": "vllm", "version": "0.28.0", "python": "3.12",
                               "torch": "2.13.0+cu130", "cuda": "13.0", "transformers": "5.15.1"},
                })
    except (KeyError, TypeError, ValueError):
        return False


def lock_matches_binding(lock, binding):
    if not isinstance(lock, dict) or not runtime_binding_is_valid(binding):
        return False
    try:
        if binding['python'] != lock['python'] or binding['ingestion'] != {'policy': lock['ingestion']['processing_policy']}:
            return False
        service = binding['semantic_service']
        saved_service = lock['semantic_service']
        return (lock.get('schema') == 'studydy-runtime-lock/v1'
                and service == {k: saved_service[k] for k in ('base_url', 'max_model_len', 'server')}
                and binding['model_id'] == saved_service['model_id']
                and binding['model_revision'] == saved_service['revision']
                and binding['runtime_lock_sha256'] == canonical_sha256(lock))
    except (KeyError, TypeError, ValueError):
        return False


def same_material_runtime(first_lock, first_binding, second_lock, second_binding):
    if not lock_matches_binding(first_lock, first_binding) or not lock_matches_binding(second_lock, second_binding):
        return False
    fields = ('python', 'ingestion', 'semantic_service', 'material_semantics')
    if any(key not in first_lock or key not in second_lock or first_lock[key] != second_lock[key] for key in fields):
        return False
    if first_lock.get('material_review') != second_lock.get('material_review'):
        return False
    return True
