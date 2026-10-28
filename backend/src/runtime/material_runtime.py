"""比對教材接續所需的分析設定，評量設定不影響教材接續。"""

from copy import deepcopy
import os
from pathlib import Path
from typing import Any

from content_identity import canonical_sha256
from .semantic_service import SemanticServiceError, preflight_semantic_service


_CONFIG_KEYS = {"private_runtime_root", "runtime_lock"}
_RUNTIME_COMPONENTS = {"layout", "runtime_lock", "semantic_service"}
_RUNTIME_REASONS = {
    "LOCAL_RUNTIME_MISSING",
    "LOCAL_RUNTIME_UNSAFE_TARGET",
    "LOCAL_RUNTIME_NOT_EXECUTABLE",
    "LOCAL_RUNTIME_VERSION_MISMATCH",
    "LOCAL_RUNTIME_SMOKE_FAILED",
    "LOCAL_RUNTIME_SETTINGS_MISMATCH",
    "LOCAL_RUNTIME_LOCK_MISMATCH",
    "LOCAL_RUNTIME_WRITE_FAILED",
}


class MaterialAnalysisError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        super().__init__(reason_code)
        self.reason_code = reason_code


def _validate_versions_contract(lock):
    if lock["schema"] != "studydy-runtime-lock/v1" or lock["python"] != "3.12":
        raise ValueError


def _validate_ingestion_contract(ingestion):
    if ingestion != {
        "page_schema": "page-evidence/v1", "native_schema": "page-native/v1",
        "processing_policy": "native-text-only/v1",
        "normalizer_policy": "text-nfc-line-preserving/v1",
        "render": {"dpi": 200, "colorspace": "RGB", "format": "PNG"},
    }:
        raise ValueError


def _validate_semantic_contract(semantic):
    if (set(semantic) != {"model_id", "revision", "api_protocol", "base_url", "max_model_len", "max_num_seqs", "server", "authentication"}
        or not isinstance(semantic["model_id"], str) or not semantic["model_id"].strip()
        or not isinstance(semantic["revision"], str) or not semantic["revision"].strip()
        or semantic["api_protocol"] != "openai-chat-completions/v1"
        or semantic["base_url"] != "http://127.0.0.1:18000"
        or semantic["max_model_len"] not in (32768, 65536)
        or semantic["max_num_seqs"] != 1
        or semantic["server"] != {"package": "vllm", "version": "0.28.0", "python": "3.12", "torch": "2.13.0+cu130", "cuda": "13.0", "transformers": "5.15.1"}
        or semantic["authentication"] != "environment-bearer:VLLM_API_KEY"):
        raise ValueError


def _validate_material_contract(material, semantic):
    independent = material.get("bundle_policy") == "independent-evidence-blocks/v1"
    spoken = material.get("spoken_policy") == "source-excerpts/v1"
    if (
        set(material)
        != {
            "request_schema",
            "response_schema",
            "bundle_policy",
            "max_tokens",
            "prompt",
            "retry_attempts",
            "generation",
            "max_new_input_tokens",
        }
        | ({"max_concurrency"} if independent else set())
        | ({"localization_policy"} if "localization_policy" in material else set())
        | ({"spoken_policy"} if spoken and independent else set())
        or (
            "localization_policy" in material
            and (
                not independent
                or material["localization_policy"] != "traditional-chinese-literals/v1"
            )
        )
        or material["request_schema"]
        != (
            ("material-block-request/v2" if spoken else "material-block-request/v1")
            if independent
            else "material-semantics-request/v1"
        )
        or (
            material["response_schema"]
            != (
                ("material-block-response/v2" if spoken else "material-block-response/v1")
                if independent
                else "material-semantics-response/v1"
            )
        )
        or (
            material["bundle_policy"]
            != (
                "independent-evidence-blocks/v1"
                if independent
                else "contiguous-evidence-new-input/v1"
            )
        )
        or (material["max_new_input_tokens"] != (4096 if independent else 1536))
        or (
            independent
            and (
                type(material["max_concurrency"]) is not int
                or not 1 <= material["max_concurrency"] <= 8
            )
        )
        or (type(material["max_tokens"]) is not int)
        or (not 1 <= material["max_tokens"] <= semantic["max_model_len"])
        or (
            material["generation"]
            != {
                "temperature": 1.0,
                "top_p": 0.95,
                "top_k": 64,
                "chat_template_kwargs": {"enable_thinking": True},
            }
        )
        or (not isinstance(material["prompt"], str))
        or (not material["prompt"])
        or (material["retry_attempts"] != 2)
    ):
        raise ValueError


def _validate_assessment_contract(assessment_settings, semantic):
    if (
        set(assessment_settings)
        != {
            "request_schema",
            "response_schema",
            "public_schema",
            "private_schema",
            "provenance_schema",
            "policy",
            "candidate_count",
            "option_count",
            "max_tokens",
            "generation",
            "prompt",
            "check_max_tokens",
            "check_generation",
            "check_prompt",
        }
        or assessment_settings["request_schema"] != "assessment-semantics-request/v1"
        or assessment_settings["response_schema"] != "assessment-semantics-response/v1"
        or (assessment_settings["public_schema"] != "single-choice-assessment/v1")
        or (assessment_settings["private_schema"] != "single-choice-answer/v1")
        or (
            assessment_settings["provenance_schema"]
            != "assessment-generation-provenance/v1"
        )
        or (assessment_settings["policy"] != "source-span-single-choice/v1")
        or (assessment_settings["candidate_count"] != 3)
        or (assessment_settings["option_count"] != 4)
        or (type(assessment_settings["max_tokens"]) is not int)
        or (not 1 <= assessment_settings["max_tokens"] <= semantic["max_model_len"])
        or (
            assessment_settings["generation"]
            != {
                "temperature": 1.0,
                "top_p": 0.95,
                "top_k": 64,
                "chat_template_kwargs": {"enable_thinking": True},
            }
        )
        or (not isinstance(assessment_settings["prompt"], str))
        or (not assessment_settings["prompt"])
        or (type(assessment_settings["check_max_tokens"]) is not int)
        or (
            not 1
            <= assessment_settings["check_max_tokens"]
            <= semantic["max_model_len"]
        )
        or (
            assessment_settings["check_generation"]
            != {
                "temperature": 1.0,
                "top_p": 0.95,
                "top_k": 64,
                "chat_template_kwargs": {"enable_thinking": True},
            }
        )
        or (not isinstance(assessment_settings["check_prompt"], str))
        or (not assessment_settings["check_prompt"])
    ):
        raise ValueError


def _validate_review_contract(lock):
    review = lock["material_review"]
    if (
        set(review) - {"consolidation_policy"}
        != {"policy", "prompt", "max_tokens", "generation"}
        or (
            "consolidation_policy" in review
            and review["consolidation_policy"] != "source-preserving-consolidation/v1"
        )
        or review["policy"] != "material-review/v1"
        or (not isinstance(review["prompt"], str))
        or (not review["prompt"].strip())
        or (type(review["max_tokens"]) is not int)
        or (not 1 <= review["max_tokens"] <= lock["semantic_service"]["max_model_len"])
        or (review["generation"] != lock["material_semantics"]["generation"])
    ):
        raise ValueError


def validate_runtime_lock(lock: Any, *, assessment: bool = True) -> dict[str, Any]:
    """各用途獨立核對既有契約；不改寫已封存的模型、政策或 hash。"""
    try:
        if not isinstance(lock, dict) or set(lock) - {
            "material_review",
            "material_notes",
            "podcast_script_review",
        } != {
            "schema",
            "python",
            "ingestion",
            "semantic_service",
            "material_semantics",
            "assessment",
        }:
            raise ValueError
        if "material_review" in lock:
            _validate_review_contract(lock)
        if "material_notes" in lock:
            notes = lock["material_notes"]
            # 歷史契約只供教材分析續接；筆記生成仍由 material_notes.step 限定現行版本。
            fields = {"version", "prompt", "selection_prompt", "review_prompt", "max_tokens"}
            if notes["version"] == "material-notes/v10":
                fields.add("summary_layout")
                if notes["summary_layout"] != "a4-12pt-18mm/v1":
                    raise ValueError
            if (set(notes) != fields
                or notes["version"] not in {"material-notes/v10", "material-notes/v11", "material-notes/v12"}
                or not isinstance(notes["prompt"], str) or not notes["prompt"].strip()
                or not isinstance(notes["selection_prompt"], str) or not notes["selection_prompt"].strip()
                or not isinstance(notes["review_prompt"], str) or not notes["review_prompt"].strip()
                or type(notes["max_tokens"]) is not int
                or not 1 <= notes["max_tokens"] <= lock["semantic_service"]["max_model_len"]):
                raise ValueError
        if "podcast_script_review" in lock:
            review = lock["podcast_script_review"]
            # 主機 Podcast provider 逐段核對講稿的提示；舊 lock 沒有此項仍有效。
            if (
                not isinstance(review, dict)
                or set(review) != {"version", "prompt"}
                or review["version"] != "podcast-script-review/v1"
                or not isinstance(review["prompt"], str)
                or not review["prompt"].strip()
            ):
                raise ValueError
        semantic = lock["semantic_service"]
        material = lock["material_semantics"]
        if not isinstance(material, dict):
            raise ValueError
        _validate_versions_contract(lock)
        _validate_ingestion_contract(lock["ingestion"])
        _validate_semantic_contract(semantic)
        _validate_material_contract(material, semantic)
        if assessment:
            _validate_assessment_contract(lock["assessment"], semantic)
        return lock
    except (KeyError, TypeError, ValueError):
        raise MaterialAnalysisError("RUNTIME_LOCK_INVALID") from None


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
    """驗證模型 runtime binding 的格式與內容雜湊。"""
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
        if not isinstance(service, dict) or service.get("max_model_len") not in (32768, 65536):
            return False
        return (all(isinstance(value[k], str) and value[k].strip() for k in ("model_id", "model_revision"))
                and service == {
                    "base_url": "http://127.0.0.1:18000", "max_model_len": service["max_model_len"],
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


# 僅放行本次已核准的 v1 → 獨立子圖升級；保留原工作 lock/hash，不能反向降級或換提示。
_LEGACY_SEMANTICS_HASH = (
    "31a72c95ff107def312071c697d2af5fb31c96f411f3b12bae4de0af766458d1"
)
_INDEPENDENT_SEMANTICS_HASH = (
    "e2b29d956a9f1a4b15f10840caea915fcf4aae96636d66b277fdfd4aa117fc5a"
)


def _semantics_policy_hash(value):
    return canonical_sha256(
        {k: v for k, v in value.items() if k not in ("max_tokens", "max_concurrency")}
    )


def same_material_runtime(first_lock, first_binding, second_lock, second_binding):
    if not lock_matches_binding(first_lock, first_binding) or not lock_matches_binding(
        second_lock, second_binding
    ):
        return False
    fields = ("python", "ingestion")
    if any(
        key not in first_lock
        or key not in second_lock
        or first_lock[key] != second_lock[key]
        for key in fields
    ):
        return False
    first_service, second_service = (
        first_lock["semantic_service"],
        second_lock["semantic_service"],
    )
    if first_service != second_service:
        # 同模型只擴大容量時可接續，舊 hash 保持原值。
        if not (
            first_service.get("api_protocol") == second_service.get("api_protocol") == "openai-chat-completions/v1"
            and first_service["max_model_len"] <= second_service["max_model_len"]
            and {k: v for k, v in first_service.items() if k != "max_model_len"}
            == {k: v for k, v in second_service.items() if k != "max_model_len"}
        ):
            return False
    # 額度調整不作廢已驗證的批次；各工作仍保留原始 lock 與 hash。
    for task in ("material_semantics", "material_review"):
        first, second = first_lock.get(task), second_lock.get(task)
        if first is None and second is None:
            continue
        if not isinstance(first, dict) or not isinstance(second, dict):
            return False
        ignored = (
            {"max_tokens", "max_concurrency"}
            if task == "material_semantics"
            else {"max_tokens"}
        )
        if {k: v for k, v in first.items() if k not in ignored} != {
            k: v for k, v in second.items() if k not in ignored
        }:
            if not (
                task == "material_semantics"
                and _semantics_policy_hash(first) == _LEGACY_SEMANTICS_HASH
                and _semantics_policy_hash(second) == _INDEPENDENT_SEMANTICS_HASH
            ):
                return False
    return True
