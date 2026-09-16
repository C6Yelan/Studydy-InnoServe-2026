# Studydy InnoServe

Studydy 將教材轉成可回查原頁的 Knowledge Map、Learning Path 與 Assessment。
PDF 以 PyMuPDF 原生文字為主；圖片與掃描頁由 Gemma Vision 輔助轉錄。
Canonical Evidence 交給獨立的 Gemma Semantic 階段。Vision 內容保留來源並要求核對原頁。

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
- [測試](docs/testing.md)
