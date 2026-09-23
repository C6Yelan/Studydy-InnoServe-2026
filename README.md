# Studydy InnoServe

Studydy 將教材轉成可回查原頁的 Knowledge Map、Learning Path 與 Assessment。
多份來源先在本機轉為 PDF、確認順序，再以 PyMuPDF 原生文字建立 Canonical Evidence，交給 Gemma Semantic。
功能與主專題 main 對齊：來源追加與複核、知識地圖、觀念題組、整組交卷、錯題補強與學習接續。
競賽版主要支援具有可靠文字層的 PDF。圖片與圖表保留在原始教材供回查，不自動轉成知識 Evidence。

正式模型為 `google/gemma-4-31B-it-qat-w4a16-ct`。
Backend、frontend、持久化 PostgreSQL 與 PDF store 在本機；Pod 提供常駐 Gemma。

先完成[本地環境設定](docs/local-environment.md)，從 repository root 執行：

```bash
git status --short --branch
python3 ops/local/manage.py status
python3 ops/local/manage.py start
```

瀏覽器入口：<http://127.0.0.1:4176>。`status` 不呼叫模型 API。
AI 離線時相關操作明確失敗；本機教材與帳號資料仍保留。

- [系統架構](docs/architecture.md)
- [教材擷取與來源](docs/document-ingestion.md)
- [帳號與登入](docs/accounts.md)
- [多來源與轉檔](docs/document-normalization.md)
- [觀念題組](docs/assessment-sets.md)
- [錯題補強](docs/assessment-remediation.md)
- [測試](docs/testing.md)
