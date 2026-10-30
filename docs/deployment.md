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
- `STUDYDY_MATERIAL_WORKERS`、`STUDYDY_CARD_WORKERS`、`STUDYDY_PODCAST_WORKERS`、`STUDYDY_RESEARCH_WORKERS` 設定教材、卡組、
  Podcast、主題研究的背景執行緒數，預設 1；依模型服務的並行能力調整（如 A100 可調高、本機維持 1）。
  Podcast 配音在語音服務端共用 GPU 鎖，多條 worker 只會讓講稿生成並行，配音仍逐份進行。
- `STUDYDY_NOTES_CHAPTER_CONCURRENCY` 設定一份完整筆記同時生成的一級章數，預設 1（逐批依序）。
  大於 1 時各章並行、章內依序；前文只看當下已完成且位置在前的批次，跨章重述的攔截較少。
  速覽不受影響。同時請求數約為教材 worker 數乘以此值，須小於模型服務的 `--max-num-seqs`。
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

語音辨識與合成由本機獨立 `ops/podcast/provider.py` 提供 `/audio`、`/transcribe`、`/media-transcribe`、`/align`。
以獨立 Python 環境安裝 `ops/podcast/stt-requirements.txt`，設定 `STUDYDY_STT_PYTHON`、`STUDYDY_STT_MODEL_DIR`、`STUDYDY_PODCAST_PROVIDER_TOKEN`；模型由本機目錄載入，不在請求時下載。
語音合成另建 Python 3.12 環境：先由 PyTorch cu128 index 安裝 torch／torchaudio 2.8.0，再安裝 `ops/podcast/xtts-requirements.txt`（不裝 Coqui 中文 extras、jieba、pypinyin）。設定 `STUDYDY_PODCAST_TTS_PYTHON`（該環境的 python）、`STUDYDY_XTTS_MODEL_DIR`（[coqui/XTTS-v2@6c2b0d75](https://huggingface.co/coqui/XTTS-v2/tree/6c2b0d75eae4b7047358e3b6bd9325f857d43f77) 的 config.json、vocab.json、model.pth、speakers_xtts.pth）、`STUDYDY_XTTS_CKIP_MODEL_DIR`（[ckiplab/bert-base-chinese-ws@60c22ced](https://huggingface.co/ckiplab/bert-base-chinese-ws)）、`STUDYDY_XTTS_CKIP_TOKENIZER_DIR`（[google-bert/bert-base-chinese@8f23c25b](https://huggingface.co/google-bert/bert-base-chinese) 的 tokenizer 檔）、`STUDYDY_XTTS_CEDICT`（[CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cc-cedict) 的 `cedict_1_0_ts_utf-8_mdbg.txt.gz`）、`STUDYDY_XTTS_UNIHAN`（[Unicode Unihan.zip](https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip)），並設 `HF_HUB_OFFLINE=1`。
XTTS-v2 權重採 Coqui Public Model License，不得商用，只用於競賽展示。`/audio` 與 `/media-transcribe` 共用 GPU 鎖；每次請求啟動子程序載入模型，結束釋放 GPU。
服務預設 `127.0.0.1:18091`。容器使用主機服務時，須由部署者設定可達的監聽位址與存取邊界。
短錄音與對齊使用 CPU；影音轉寫與語音合成使用 GPU，部署前須與同機其他工作安排資源使用時段。
SearXNG 由競賽 project 的 `research-search` 提供，不使用正式站的 provider 或搜尋服務。

文字模型執行參數需符合 runtime lock，包含 `--max-model-len 65536`。
Podcast 完成結果是講稿與音訊（可選影片）；語音問答接受錄音，回答以文字與引用呈現並逐句配音。影片分鏡由設定的文字模型生成。

不需 AI 的驗證包含 auth、ownership、上傳、normalization／download、private no-store
與公開 HTTPS。真 AI generation／retry／map generation 標記 DEFERRED_AI_VALIDATION。

## 後端專用身分

Backend 與其轉檔子程序使用 `STUDYDY_BACKEND_UID`（預設20002），GID維持1000。容器 runtime tmpfs 使用同一身分；完整建置時 Compose 以同名建置參數在 backend 階段建立 `studydy-backend` passwd 項目（HOME=/tmp tmpfs），讓 `getpass`、`~` 等依 passwd 查身分的程式可用；改 UID 須完整重建 backend 映像。`nproc=1024`、容器 pids512、read_only、cap_drop、no-new-privileges、seccomp及bwrap參數均不變。

`STUDYDY_UID/GID` 仍供主機資料管理、model-bridge與cloudflared使用（預設1000:1000）。這兩個低執行緒代理不執行轉檔或推論，保留原身分可避免更改私鑰／token的owner與私有權限。Init仍以0:0執行，僅初始化缺少的受管理目錄；既有資料根目錄與PostgreSQL權限保留，artifact根及其子樹的身分遷移須在部署時分開處理。

Artifact仍採私有目錄／不可變發布檔契約，不能靠群組開權限繞過。具體遷移範圍、檔案數、擁有者切換及回滾命令應依本次部署狀態檔執行，不把整個資料根目錄一起變更，也不改主機共用 `.venv`。

## PostgreSQL 18.6 安全更新

PostgreSQL 映像與隔離測試 fixture 固定同一個 18.6-bookworm digest；psycopg／psycopg-binary 3.3.5 的正式 wheel 內含 libpq 18.6，更新 server 不會替換這份 client library。

[18.6 release notes](https://www.postgresql.org/docs/release/18.6/) 說明 18.5 未發布；同一 18 系列不需 dump／restore，但有針對既有索引的人工處置條件：GIN 統計需檢查是否應 ANALYZE，btree_gist 的浮點 NaN／bit 與 ltree 超長 label 等特定索引可能需 REINDEX。競賽版 `backend/migrations` 只建立一般 B-tree／unique 索引，沒有 GIN、btree_gist、ltree 或 extension 宣告，因此未找到適用這些特定重建要求的 repository 索引。此結論不涵蓋產品 DB 中手動建立而未記入 migrations 的物件；本輪沒有查詢或操作產品 DB。

繁中提示更新：新題組使用 `source-span-single-choice/v3`，筆記契約為 `material-notes/v17`，localization 與 Podcast 核對提示各升為 v2。Gemma 講稿提示位於 `backend/src/runtime/podcast_script_generation.py`（`source-script/v17`），不在 ASR provider。封存 v1／v2 題組仍依原 lock 生成及驗證，已存資料與 hash 不重寫，無 migration；開 Pod 後另做真模型驗收。

筆記生成契約為 `material-notes/v17`：新稿依原教材章節，模型核對一次後刪除不符內容，完整筆記每批對未涵蓋概念補寫並核對一次；複習速覽每章挑 3～5 條核心，缺漏概念明列。舊發布稿、Evidence 與已保存 lock／hash 不改寫，契約變更重試只清除未發布暫存。v16 新增 `0032_note_source_sections.sql` 的 `material_notes.published_metadata`，需與理解 `sections`／`unorganized_concepts` 的前端一起部署；舊稿兩欄回空陣列。

`0033_maintenance_budget_range.sql` 把 0021 的 DB 約束 `demo_reanalysis_budget` 改為每個維護 run 自訂上限（`limit` 1～2000，`reserved_calls` 不超過該 run 的 `limit`）；`create_revision(..., full_reanalysis=True)` 建立的工作仍是 300，已存在的 run 不變。經使用者授權的一次性維護重分析可設定較高上限，仍在外送前原子保留、不得超支；這類 run 可封存替換過來源的新 source set，發布時只核對新結構與該 run 自己的來源綁定，不要求與舊版相同。一般新增來源流程不變。
