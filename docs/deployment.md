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
- native-text-only、branding、worker、runtime lock、migrations 與資料身分保持不變。

公開部署已獲使用者批准，Access 非必要。啟動 connector 前必須完成本機 smoke，
使用 `docker compose -f compose.yaml -f compose.tunnel.yaml --profile tunnel up -d --no-deps cloudflared`。
日後管理前後端也須保留兩個 Compose 檔；不要用 base-only 設定意外撤掉 HTTPS／edge。

驗證入口為 `ops/tests/compose_boundary.py`、`ops/tests/nginx_boundary.py` 與
`backend/tests/runtime/infrastructure/test_https_deployment.py`。Compose test 指定
`STUDYDY_TEST_ENV_FILE`；Nginx test 指定兩個測試 image，僅使用測試 port 4183。
資料測試使用 disposable DB；不得掛載產品資料或呼叫模型。

切換前保存舊 image identity／私有設定，確認無 pending migration 與進行中工作，
停止寫入後備份 DB 與 artifacts。只替換 frontend/backend；失敗先停止本版 connector，
再以舊 images/config 恢復 localhost，不清 volume、不回寫 migration、不改主站。

不需 AI 的驗證包含 auth、ownership、上傳、normalization／download、private no-store
與公開 HTTPS。真 AI generation／retry／map generation 標記 DEFERRED_AI_VALIDATION。

## PostgreSQL 18.6 安全更新

PostgreSQL 映像與隔離測試 fixture 固定同一個 18.6-bookworm digest；psycopg／psycopg-binary 3.3.5 的正式 wheel 內含 libpq 18.6，更新 server 不會替換這份 client library。

[18.6 release notes](https://www.postgresql.org/docs/release/18.6/) 說明 18.5 未發布；同一 18 系列不需 dump／restore，但有針對既有索引的人工處置條件：GIN 統計需檢查是否應 ANALYZE，btree_gist 的浮點 NaN／bit 與 ltree 超長 label 等特定索引可能需 REINDEX。競賽版 `backend/migrations` 只建立一般 B-tree／unique 索引，沒有 GIN、btree_gist、ltree 或 extension 宣告，因此未找到適用這些特定重建要求的 repository 索引。此結論不涵蓋產品 DB 中手動建立而未記入 migrations 的物件；本輪沒有查詢或操作產品 DB。
