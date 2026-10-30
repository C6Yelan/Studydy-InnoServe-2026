"""受控模型走一次維護全量重分析；正式教材與真實模型不在測試範圍。"""

from runtime.storage.database import database_session
from runtime.storage.knowledge_structures import read_knowledge_structure
from runtime.storage.tables import Material, MaterialProcessingRun
from product_fixtures import closed_loop
from test_source_revisions import revisions


def test_maintenance_run_may_publish_a_replaced_source_set(revisions, monkeypatch):
    # 一次性維護腳本可替換來源後全量重分析；來源綁定仍由該 run 自己的 source set 驗證。
    from pdf_evidence.material_pipeline import analyze_material
    owner, material, settings, dsn, add, start, execute, first, original, requests = revisions
    monkeypatch.setattr("runtime.material_processing.analyze_material", analyze_material)
    sent = []

    def provider(_client, *, request, before_request, **_kwargs):
        before_request()
        sent.append(request)
        rows = [row for section in request["sections"] for row in section["evidence"] if row[2] != "heading"]
        assert rows  # 維護重分析須送完整原文，不可落入增量零頁或 review-only。
        result = {"concepts": [{"k": f"new_{row[0]}", "l": f"Concept {row[0]}", "a": [],
            "c": [{"m": None, "s": [row[0]]}]} for row in rows], "relations": []}
        if "update_policy" in request:
            result["review_required"] = False
        return result

    monkeypatch.setattr("runtime.maintenance_reanalysis.request_semantics", provider)
    replacement = add("B.pdf", "A queue removes the earliest inserted element first.")
    run_id = start([replacement], "replaced-sources", original["revision"]).run_id
    with database_session(dsn) as session:
        session.get(MaterialProcessingRun, run_id).maintenance = {
            "mode": "demo-full-reanalysis/v1", "limit": 2000, "reserved_calls": 0}
    completed = execute()
    assert completed.status == "succeeded", completed.error_code
    document = read_knowledge_structure(owner.learner_id, material, run_id=run_id, dsn=dsn).document
    assert document["source_set_sha256"] != original["source_set_sha256"]
    with database_session(dsn) as session:
        assert session.get(Material, material).head_revision == document["revision"]
        assert session.get(MaterialProcessingRun, run_id).maintenance["reserved_calls"] == len(sent) > 0
