# 中文 InnoServe 公開部署

此 checkout 的 canonical repository 為 Studydy-InnoServe-2026，分支 main。
部署使用本目錄的 `compose.yaml`＋`compose.tunnel.yaml`，project 保持
`studydy-competition`；不使用主站或英文版的 Compose、DB、artifact 或 token。

- 公開 origin：`https://innoserve.studydy.net`；Secure cookie=true。
- 主機維護入口：`127.0.0.1:4176`；HTTPS 設定下不放寬 localhost mutation Origin。
- cloudflared 僅在本 project 的 edge；frontend 在 edge 使用 `innoserve-frontend` alias，
  由 Dashboard 路由至 `http://innoserve-frontend:8080`。
- frontend 同時保留 application；backend／model bridge 的網路不變，database 保持 internal。
- token 是 repo 外 `/home/jerry/.config/studydy/cloudflared-innoserve-token`，0600、
  owner/group 與 STUDYDY_UID/GID 相容；父目錄 0700。`.env` 僅保存路徑，禁止保存 token 值。
- `STUDYDY_UPLOAD_MAX_BYTES=94371840` 同時約束 Nginx／API；UI 讀取 capabilities。
  內部 artifact 上限不變；capabilities 失敗時不以寫死上限繼續上傳。
- Nginx 限定正式與 localhost Host，清除未使用的 forwarded／Access 身分 headers，
  保留 exact Origin／Cookie；redirect 使用相對路徑。沒有新增 proxy trust chain。
- 使用新版持久工作、Gemma runtime lock 與 migration baseline；公開網域、UID、port 與資料位置保持競賽設定。

Access 非必要。每次切換須先完成本機驗收與部署核准；啟動 connector 前必須完成本機 smoke，
使用 `docker compose -f compose.yaml -f compose.tunnel.yaml --profile tunnel up -d --no-deps cloudflared`。
日後管理前後端也須保留兩個 Compose 檔；不要用 base-only 設定意外撤掉 HTTPS／edge。

驗證入口為 `ops/tests/compose_boundary.py`、`ops/tests/nginx_boundary.py` 與
`backend/tests/runtime/infrastructure/test_https_deployment.py`。Compose test 指定
`STUDYDY_TEST_ENV_FILE`；Nginx test 指定兩個測試 image，僅使用測試 port 4183。
資料測試使用 disposable DB；不得掛載產品資料或呼叫模型。

本版從 migration 0001 到最新序列使用獨立 baseline，只能套用到空的新資料庫，不能直接升級舊競賽資料庫。
核准切換後，先確認 DB 大小與剩餘空間，保存舊 image identity 與私有設定；停止寫入後執行 `pg_dump`，並以 `pg_restore --list` 驗證備份可讀。只重建 PostgreSQL DB，再從 0001 套用到最新 migration；artifact／原始 PDF 目錄原地保留，不改名、不搬移、不刪除。
舊帳號不自動轉入新 DB；以已授權帳密透過 `/v1/accounts` 重新註冊，再執行登入檢查。舊檔保留供回復使用。
回復時使用舊 images、設定與經驗證的 DB dump，搭配原地保留的 artifact 目錄；不把新 SQL 套到舊資料，也不清除 volume。

語音辨識由本機獨立 `ops/podcast/provider.py` 提供 `/transcribe`、`/media-transcribe`、`/align`。
以獨立 Python 環境安裝 `ops/podcast/stt-requirements.txt`，設定 `STUDYDY_STT_PYTHON`、`STUDYDY_STT_MODEL_DIR`、`STUDYDY_PODCAST_PROVIDER_TOKEN`；模型由本機目錄載入，不在請求時下載。
服務預設 `127.0.0.1:18091`。容器使用主機服務時，須由部署者設定可達的監聽位址與存取邊界。
短錄音與對齊使用 CPU；影音轉寫使用 GPU，部署前須與同機其他工作安排資源使用時段。
SearXNG 由競賽 project 的 `research-search` 提供，不使用正式站的 provider 或搜尋服務。

文字模型執行參數需符合 runtime lock，包含 `--max-model-len 65536`。
Podcast 完成結果是可閱讀講稿；語音問答接受錄音，回答以文字與引用呈現。

不需 AI 的驗證包含 auth、ownership、上傳、normalization／download、private no-store
與公開 HTTPS。真 AI generation／retry／map generation 標記 DEFERRED_AI_VALIDATION。

## 後端專用身分

Backend 與其轉檔子程序使用 `STUDYDY_BACKEND_UID`（預設20002），GID維持1000。容器 runtime tmpfs 使用同一身分；完整建置時 Compose 以同名建置參數在 backend 階段建立 `studydy-backend` passwd 項目（HOME=/tmp tmpfs），讓 `getpass`、`~` 等依 passwd 查身分的程式可用；改 UID 須完整重建 backend 映像。`nproc=1024`、容器 pids512、read_only、cap_drop、no-new-privileges、seccomp及bwrap參數均不變。

`STUDYDY_UID/GID` 仍供主機資料管理、model-bridge與cloudflared使用（預設1000:1000）。這兩個低執行緒代理不執行轉檔或推論，保留原身分可避免更改私鑰／token的owner與私有權限。Init仍以0:0執行，僅初始化缺少的受管理目錄；既有資料根目錄與PostgreSQL權限保留，artifact根及其子樹的身分遷移須在部署時分開處理。

Artifact仍採私有目錄／不可變發布檔契約，不能靠群組開權限繞過。具體遷移範圍、檔案數、擁有者切換及回滾命令應依本次部署狀態檔執行，不把整個資料根目錄一起變更，也不改主機共用 `.venv`。

## PostgreSQL 18.6 安全更新

PostgreSQL 映像與隔離測試 fixture 固定同一個 18.6-bookworm digest；psycopg／psycopg-binary 3.3.5 的正式 wheel 內含 libpq 18.6，更新 server 不會替換這份 client library。

[18.6 release notes](https://www.postgresql.org/docs/release/18.6/) 說明 18.5 未發布；同一 18 系列不需 dump／restore，但有針對既有索引的人工處置條件：GIN 統計需檢查是否應 ANALYZE，btree_gist 的浮點 NaN／bit 與 ltree 超長 label 等特定索引可能需 REINDEX。競賽版 `backend/migrations` 只建立一般 B-tree／unique 索引，沒有 GIN、btree_gist、ltree 或 extension 宣告，因此未找到適用這些特定重建要求的 repository 索引。此結論不涵蓋產品 DB 中手動建立而未記入 migrations 的物件；本輪沒有查詢或操作產品 DB。

繁中提示更新：新題組使用 `source-span-single-choice/v2`，筆記契約為 `material-notes/v13`，localization 與 Podcast 核對提示各升為 v2。Gemma 講稿提示位於 `backend/src/runtime/podcast_script_generation.py`（`source-script/v17`），不在 ASR provider。封存 v1 題組仍依原 lock 生成及驗證，已存資料與 hash 不重寫，無 migration；開 Pod 後另做真模型驗收。
