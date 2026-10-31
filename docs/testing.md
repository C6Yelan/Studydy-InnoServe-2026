# 測試

[文件入口](../README.md) · [安裝與啟動](getting-started.md) · [限制](limitations.md)

## 選擇範圍

| 變更 | 驗證入口 |
| --- | --- |
| Evidence、知識結構、題目與純邏輯 | backend/tests 對應單元測試 |
| API、資料庫、worker、來源與交易 | backend/tests/runtime 對應領域 |
| 前端 API、路由與資料投影 | Node tests、TypeScript |
| 介面與互動 | production build、對應 Playwright spec |
| 文件與註解 | 連結、命令與語法／行為不變核對 |

測試通過後，只有新變更、失敗或未解疑慮才擴大或重跑。

## 無網路容器測試

~~~bash
docker compose -p studydy-unit-tests -f compose.test.yaml run --build --rm unit
~~~

容器不掛載產品資料，不需要 GPU 或模型。前端映像建置包含 Node tests、TypeScript 與 production build。

後端使用 CPython 3.12.15；LibreOffice／Bubblewrap 保留原驗證快照，CA、XML／網路／文件解析相關系統庫由獨立安全快照定版安裝，版本見 `ops/docker/backend.Dockerfile`。lxml 依鎖定版本自建 wheel 並連結系統 XML 函式庫；後端信任庫依官方修補範圍確認 emSign G3 已移除。前端採官方 nginx 1.30.6 映像，Alpine 3.24.3 等官方重建後再更新 digest，不自行 apk upgrade。

## 身分與檔案權限驗證

Backend／test 映像預設使用20002:1000；Compose由 `STUDYDY_BACKEND_UID` 選擇後端 UID，與資料管理／bridge／cloudflared的 `STUDYDY_UID` 分開。隔離驗證使用獨立 Compose project、暫存資料根及假金鑰，不掛載產品資料或真金鑰；確認init只處理允許的目錄、後端能寫入／正規化artifact、管理者只能透過API或服務UID受控命令讀取私有產物。

保留0700／0400等現有斷言。Runtime需要模型替身及專用測試DB；使用新非root UID不代表可提高NPROC／pids、放寬seccomp或取消隔離。SSH bridge仍以1000:1000驗證假金鑰可讀，其他服務身分不可因此取得私鑰。

完整重建後端映像後，以 `python3 -B ops/tests/backend_identity.py <映像>` 核對執行 UID 有 passwd 身分、HOME 為 /tmp，且清空環境時 `getpass.getuser()` 與 `~` 仍可用。腳本以唯讀 rootfs、無網路執行，不 build／pull、不掛產品資料；UID 依 `STUDYDY_BACKEND_UID`（預設20002）。

## 原始碼測試

需先準備獨立臨時 Python 環境與 frontend/node_modules；真轉檔還需要部署相同的 LibreOffice、字型及 Bubblewrap。依賴版本以 lock files 為準，不重建其他 checkout 共用的環境。

~~~bash
test_root=$(mktemp -d)
UV_CACHE_DIR="$test_root/cache" UV_PROJECT_ENVIRONMENT="$test_root/venv" uv sync --project backend --extra test
PYTHONPATH=backend/src:backend/tests:backend/tests/runtime/materials:backend/tests/runtime/study:backend/tests/runtime/sources \
  "$test_root/venv/bin/python" -m pytest -q backend/tests/test_*.py
npm --prefix frontend test
npm --prefix frontend run typecheck
~~~

Node runner 的摘要可能按測試檔計數；需要個別案例時可直接執行對應 test.mjs。

## Runtime 與瀏覽器

Runtime 按 accounts、assessments、infrastructure、materials、sources、study 分類。fixture 預設建立固定映像的 disposable PostgreSQL 18.6，每個案例使用獨立 DB 與 artifact root；禁止接產品 DB。

如需指定資料庫，STUDYDY_TEST_POSTGRES_DSN 只接受本機、名稱以 studydy_test 開頭的專用 control database，並核對版本及 superuser 權限。

完整 runtime 測試需要獨立前端 build 與 ports：

~~~bash
export STUDYDY_E2E_FRONTEND_DIST="$PWD/.studydy-runtime/test-frontend"
export STUDYDY_E2E_FRONTEND_PORT=4183 STUDYDY_E2E_API_PORT=8002
npm --prefix frontend run build -- --outDir "$STUDYDY_E2E_FRONTEND_DIST" --emptyOutDir

env -u STUDYDY_TEST_POSTGRES_DSN -u STUDYDY_DATABASE_DSN \
  PYTHONPATH=backend/src:backend/tests:backend/tests/runtime/materials:backend/tests/runtime/study:backend/tests/runtime/sources \
  "$test_root/venv/bin/python" -m pytest -q backend/tests --durations=10
~~~

- frontend/e2e/mock 攔截 API，驗證公開契約、互動及代表性桌機／手機版面。
- frontend/e2e/api 由 Python fixture 啟動真 API、隔離 DB 及必要 worker；模型回應受控。故障注入案例會明確攔截個別請求。
- fixture 負責設定啟用旗標；不要手動設旗標或把 skip 當通過。

執行 mock browser，沿用上述 build 與 ports：

~~~bash
PYTHONPATH=backend/tests/runtime "$test_root/venv/bin/python" - <<'PYTEST'
from browser_e2e_runner import main
raise SystemExit(main("e2e/mock/", timeout_seconds=600))
PYTEST
~~~

可將 spec 改為檔名或 regex，限制驗證範圍。真 API 案例應執行其 backend/tests/runtime fixture，例如 sources/test_source_revisions_browser.py。

## 必須保護的行為

- owner／session 隔離、私密答案及來源綁定。
- 整組交卷的原子性、冪等、版本衝突與回應遺失恢復。
- 刪除、quarantine、checkpoint 清理與晚到 worker 的隔離。
- migration checksum、序列、併發安裝、升級與失敗回滾。
- 真轉檔、頁碼／區塊定位，以及瀏覽器恢復。

記錄實際命令、範圍、結果與限制。合成測試提供程式回歸證據；模型品質須另以指定素材及標準，透過產品流程生成並人工核對。

`test_research_workflow.py` 驗證完整涵蓋請求預算、長標題／線索／警告只在超額時截取、原文分批及來源索引保留；無法容納的原文不得宣稱支持。Gemma 回應仍須通過現有欄位與型別檢查。

`test_note_sections.py` 驗證原章節／小節最多三層、原順序、多檔一檔一章、無標題地圖退路、跨章 claim 歸屬與每章程式大綱。`test_material_notes.py` 驗證每章必選的複習速覽、合法引用、公式語法與數字、一次逐段核對後只刪不符位置，以及格式與 provider 失敗不可假成功；完整筆記只對未涵蓋概念補寫一次並保留原有效段落，章節並行時章內順序、依批次組裝、失敗停止與補缺續接。`runtime/study/test_note_v16_queue.py` 用一次性 PostgreSQL 與受控模型驗證章節 metadata 同正文發布、更新途中仍讀舊稿、全空時保留既有稿與明確錯誤、首次空稿保存全部缺漏，以及速覽缺漏只顯示與完整筆記的交集；`test_note_queue.py` 核對重試契約與排程，以及並行章節依位置保存與續接。`test_assessment_safety_v1.py` 保護 v1／v2 封存題與 v3 新題讀取。這些受控測試不代替 Gemma 真實內容驗收。

Podcast 回歸以合成資料驗證省略 29／31 重點後的存檔一致性、各集並行與 lease 恢復、前段變動後重核、共用請求上限、標題 512 tokens 與失敗候選／診斷保存，以及疊字重試仍污染時拒收。候選與診斷只保存在測試私人目錄，不呼叫真模型；不以此宣稱模型品質通過。

`frontend/e2e/mock/notes.spec.ts` 另驗證批次進度、進度頁重新整理／返回，以及從知識地圖開啟對應筆記段落；沒有對應段落時不顯示入口，閱讀不觸發生成。

`runtime/study/test_note_highlights.py` 驗證標記 CRUD、owner／Origin、選取範圍、Unicode code point、唯一／重複／缺失原句對應、舊註記、各類區塊與整條公式、章節標記重對應及三種匯出格式。`test_notes_browser.py` 走隔離 DB 的真 API；notes mock 驗證選取工具列、旁註、BOT 預填但不送出、手機與鍵盤操作。
