# InnoServe 本地持久化環境

Backend、frontend、PostgreSQL 與原始 PDF 在本機，Gemma 在外部常駐 Pod。
所有私密設定與持久化檔案放在本 checkout 的 `.studydy-product/`，不加入 Git。

## 準備

需要 Python 3.12、Node.js/npm、Docker、OpenSSH 與可連線的 Gemma vLLM 服務。
使用 backend 虛擬環境與 frontend dependencies：

```bash
backend/.venv/bin/python --version
# backend/.venv 與正式版共用；不要重建或刪除此環境。
npm --prefix frontend ci
npm --prefix frontend run build
```

多來源轉檔使用共用的 `backend/.venv`，套件安裝與系統需求見[來源轉檔](document-normalization.md)。
競賽版仍執行自己的 renderer，不需要另設 Python 路徑，也不會啟動 Unlimited-OCR。

由操作者準備獨立、持久化 PostgreSQL 18 資料庫與 volume，以及私有 PDF artifact root。
不得用 disposable test DB 取代產品資料庫；不得刪除既有 volume 或 PDF store。
`.studydy-product/private-config.json` 必須有以下欄位，值由本機操作者填寫：

```json
{
  "container": "<persistent-postgres-container>",
  "volume": "<persistent-postgres-volume>",
  "database_dsn": "<private-database-dsn>",
  "artifact_root": "<absolute-private-artifact-directory>"
}
```

`.studydy-product/pod-connection.json` 格式：

```json
{"ssh_host": "<user>@<ssh-host>"}
```

Private JSON 權限 0600，artifact root 0700。SSH 使用 `~/.ssh/id_ed25519`，要求已驗證的
known-host key。Pod 端設定 `VLLM_API_KEY`；通道只在 Pod 讀取，不複製金鑰到本機。
不得輸出或提交 DSN、教材、帳密、SSH 入口與 logs。

新資料庫須在開始產品寫入前套用 repository 現有 schema migrations。
在私有環境設定好 `STUDYDY_DATABASE_DSN` 後執行：

```bash
PYTHONPATH=backend/src backend/.venv/bin/python -c 'from runtime.storage.migrations import run_migrations; print(run_migrations())'
```

啟用新版前須先套用 0007–0014；本次程式同步與測試沒有套用產品 DB migration 或重啟服務。
依使用者決定不保留舊 API／資料 reader；舊單 PDF 地圖與單題紀錄可能失效，之後重新上傳分析。
migration 不清空 DB、改寫歷史 artifact 或刪除原始教材。既有資料升級前先停止寫入並備份 DB 與 PDF store，不修改已套用 SQL 的 checksum。

## 啟停

```bash
python3 ops/local/manage.py status
python3 ops/local/manage.py start
python3 ops/local/manage.py stop
```

| 服務 | 本機位置 |
|---|---|
| Frontend | `http://127.0.0.1:4176` |
| Backend | `127.0.0.1:8002` |
| 模型通道 | `127.0.0.1:18001` |
| Logs / PID | `.studydy-product/logs/`、`.studydy-product/run/` |

`status` 只檢查程序、socket 與 Docker，不送模型請求。`start` 沿用本 checkout 擁有的程序，
未知程序占用 port 時拒絕啟動；只啟動既有持久 DB、通道、backend 與 frontend。
`stop` 不刪資料、不停止 PostgreSQL 或 Pod。關閉本機 HTTP/SSH 不代表遠端推論已取消。

## Gemma 服務

模型、revision、vLLM 版本與 request 設定以 `local_ai/runtime-lock.json` 為準。
模型為 `google/gemma-4-31B-it-qat-w4a16-ct`，vLLM 0.28.0、32768 context，
Pod loopback 18000。服務須支援文字 chat completions、JSON schema 與 tokenizer。
支援的 PDF 格式見[教材擷取](document-ingestion.md)。
Backend 不啟停或替換模型；每次產品 AI 操作驗證既有服務，失敗不轉交其他 runtime。

換 Pod 時僅更新私有連線設定，確認 runtime lock 相符後重啟本機通道服務。
不要修改持久化資料或把實際連線值寫入公開文件。
