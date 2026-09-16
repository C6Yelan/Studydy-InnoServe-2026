# InnoServe 本地持久化環境

Backend、frontend、PostgreSQL 與原始 PDF 在本機，Gemma 在外部常駐 Pod。
所有私密設定與持久化檔案放在本 checkout 的 `.studydy-product/`，不加入 Git。

## 準備

需要 Python 3.12、Node.js/npm、Docker、OpenSSH 與可連線的 Gemma vLLM 服務。
使用 backend 虛擬環境與 frontend dependencies：

```bash
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -e './backend[test]'
npm --prefix frontend ci
npm --prefix frontend run build
```

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

既有資料升級前先停止寫入並備份 DB 與 PDF store，不修改已套用 SQL 的 checksum。

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
Pod loopback 18000。服務須支援 image input、tokenizer，以及
`mm_processor_kwargs.max_soft_tokens=1120`。Vision 設定見[教材擷取](document-ingestion.md)。
Backend 不啟停或替換模型；每次產品 AI 操作驗證既有服務，失敗不轉交其他 runtime。

換 Pod 時僅更新私有連線設定，確認 runtime lock 相符後重啟本機通道服務。
不要修改持久化資料或把實際連線值寫入公開文件。
