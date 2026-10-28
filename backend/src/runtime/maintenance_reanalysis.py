"""指定教材重分析、章節與摘要的持久共同額度；不修改分析輸入 hash。"""

from functools import partial
from sqlalchemy import select, text

from .semantic_service import SemanticServiceError, request_semantics
from .storage.database import database_session
from .storage.tables import KnowledgeStructure, MaterialProcessingRun


def reserve_call(run_id, *, dsn=None):
    # 先持久保留才外送；無法確定是否已受理的失敗請求也不退額。
    with database_session(dsn) as session:
        used = session.execute(text("""
            UPDATE material_processing_runs
            SET maintenance = jsonb_set(maintenance, '{reserved_calls}',
                to_jsonb((maintenance->>'reserved_calls')::integer + 1))
            WHERE run_id = :run AND maintenance->>'mode' = 'demo-full-reanalysis/v1'
                AND (maintenance->>'reserved_calls')::integer < (maintenance->>'limit')::integer
            RETURNING (maintenance->>'reserved_calls')::integer
        """), {"run": run_id}).scalar_one_or_none()
        if used is None:
            raise SemanticServiceError("MATERIAL_MODEL_BUDGET_EXHAUSTED")


def semantic_call_for_run(run_id, *, dsn=None):
    with database_session(dsn) as session:
        maintenance = session.scalar(select(MaterialProcessingRun.maintenance).where(
            MaterialProcessingRun.run_id == run_id))
    if maintenance is None:
        return None
    return partial(request_semantics, before_request=partial(reserve_call, run_id, dsn=dsn))


def semantic_call_for_revision(owner, material_id, revision, *, dsn=None):
    with database_session(dsn) as session:
        run_id = session.scalar(select(KnowledgeStructure.run_id).where(
            KnowledgeStructure.learner_id == owner,
            KnowledgeStructure.material_id == material_id,
            KnowledgeStructure.structure_revision == revision))
    return semantic_call_for_run(run_id, dsn=dsn)
