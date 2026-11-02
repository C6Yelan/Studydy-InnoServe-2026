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
- `STUDYDY_MATERIAL_WORKERS`、`STUDYDY_CARD_WORKERS`、`STUDYDY_RESEARCH_WORKERS` 設定教材、卡組、主題研究的背景執行緒數；
  `STUDYDY_PODCAST_WORKERS` 設定同份 Podcast 的製作並行數。全部預設 1；依模型服務的並行能力調整（如 A100 可調高、本機維持 1）。
  Podcast 配音在語音服務端共用 GPU 鎖，多集製作只會讓講稿生成並行，配音仍逐份進行。
  `STUDYDY_VIDEO_WORKERS`（預設 1）設定同時渲染的 Podcast 影片集數；影片在後端容器以 CPU 編碼，字幕對齊仍在語音服務逐份進行。
- `STUDYDY_NOTES_CHAPTER_CONCURRENCY` 設定一份完整筆記同時生成的一級章數，預設 1（逐批依序）。
  大於 1 時各章並行、章內依序；前文只看當下已完成且位置在前的批次，跨章重述的攔截較少。
  速覽不受影響。同時請求數約為教材 worker 數乘以此值，須小於模型服務的 `--max-num-seqs`。
- `STUDYDY_MATERIAL_REVIEW_CONCURRENCY` 設定一份教材同時送出的複核批次數，預設 1。各批只讀自己的輸入，
  跨批套用順序固定依原地圖概念順序，續跑以批次內容快取接續，不受完成順序影響；整併（去重）維持逐次。
- 教材分析每批最多分到內容區塊總數的 1/`max_concurrency`：小教材整份放得進一兩批時也會切成約
  `max_concurrency` 批並行，大教材仍以 `max_new_input_tokens` 為上限。批次邊界因此和舊後端不同，
  部署前須清空分析中的工作，舊 checkpoint 的已完成範圍對不上會以 ANALYSIS_CHECKPOINT_INVALID 結束。
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

此 DB 只能從空資料庫依 0001 起的 migration 初始化，不能直接升級舊競賽資料庫。回復時使用舊 images、設定與經驗證的 DB dump，搭配原地保留的 artifact 目錄；不把新 SQL 套到舊資料，也不清除 volume。

語音辨識與合成由本機獨立 `ops/podcast/provider.py` 提供 `/audio`、`/transcribe`、`/media-transcribe`、`/align`。
以獨立 Python 環境安裝 `ops/podcast/stt-requirements.txt`，設定 `STUDYDY_STT_PYTHON`、`STUDYDY_STT_MODEL_DIR`、`STUDYDY_PODCAST_PROVIDER_TOKEN`；模型由本機目錄載入，不在請求時下載。
語音合成另建 Python 3.12 環境：先由 PyTorch cu128 index 安裝 torch／torchaudio 2.8.0，再安裝 `ops/podcast/xtts-requirements.txt`（不裝 Coqui 中文 extras、jieba、pypinyin）。設定 `STUDYDY_PODCAST_TTS_PYTHON`（該環境的 python）、`STUDYDY_XTTS_MODEL_DIR`（[coqui/XTTS-v2@6c2b0d75](https://huggingface.co/coqui/XTTS-v2/tree/6c2b0d75eae4b7047358e3b6bd9325f857d43f77) 的 config.json、vocab.json、model.pth、speakers_xtts.pth）、`STUDYDY_XTTS_CKIP_MODEL_DIR`（[ckiplab/bert-base-chinese-ws@60c22ced](https://huggingface.co/ckiplab/bert-base-chinese-ws)）、`STUDYDY_XTTS_CKIP_TOKENIZER_DIR`（[google-bert/bert-base-chinese@8f23c25b](https://huggingface.co/google-bert/bert-base-chinese) 的 tokenizer 檔）、`STUDYDY_XTTS_CEDICT`（[CC-CEDICT](https://www.mdbg.net/chinese/dictionary?page=cc-cedict) 的 `cedict_1_0_ts_utf-8_mdbg.txt.gz`）、`STUDYDY_XTTS_UNIHAN`（[Unicode Unihan.zip](https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip)），並設 `HF_HUB_OFFLINE=1`。
XTTS-v2 權重採 Coqui Public Model License，不得商用，只用於競賽展示。`/audio` 與 `/media-transcribe` 共用 GPU 鎖；每次請求啟動子程序載入模型，結束釋放 GPU。
服務預設 `127.0.0.1:18091`。容器使用主機服務時，須由部署者設定可達的監聽位址與存取邊界。

競賽 provider 啟動前，將暫存目錄放在 WSL 硬碟上的競賽資料目錄，避免音訊、轉寫及字幕對齊暫存占用 `/tmp` 的記憶體檔案系統：

```bash
mkdir -p /home/jerry/project/Studydy/main-competition/.studydy-product/podcast/tmp
export TMPDIR=/home/jerry/project/Studydy/main-competition/.studydy-product/podcast/tmp
```

部署者須把此 `TMPDIR` 值加入競賽 provider 既有啟動設定，並確保服務帳號可寫入該目錄；provider 及其子程序沿用同一設定。只更新這份文件不會改變執行中的服務，實際套用與重啟由部署流程處理。

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

## 其他部署注意

Podcast 講稿提示位於 `backend/src/runtime/podcast_script_generation.py`（`source-script/v17`），不在 ASR provider。

`0033_maintenance_budget_range.sql` 讓每個一次性維護重分析 run 自訂模型請求上限（`limit` 1～2000；`create_revision(..., full_reanalysis=True)` 建立的工作預設 300），仍在外送前原子保留、不得超支；這類 run 可封存替換過來源的新 source set，發布時只核對新結構與該 run 自己的來源綁定。執行前須取得使用者對教材與額度的授權；一般新增來源流程不變。
