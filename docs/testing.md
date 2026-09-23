# 測試

從 repository root 執行。Python 使用 3.12；先完成[本地環境](local-environment.md)的依賴安裝。

```bash
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build -- --outDir ../.studydy-runtime/main-ui-parity-frontend --emptyOutDir
PYTHONDONTWRITEBYTECODE=1 \
STUDYDY_E2E_FRONTEND_DIST="$PWD/.studydy-runtime/main-ui-parity-frontend" \
STUDYDY_E2E_FRONTEND_PORT=4175 STUDYDY_E2E_API_PORT=8003 \
PYTHONPATH=backend/src:backend/tests backend/.venv/bin/pytest -q backend/tests
STUDYDY_E2E_FRONTEND_DIST="$PWD/.studydy-runtime/main-ui-parity-frontend" \
PYTHONPATH=backend/src:backend/tests/runtime backend/.venv/bin/python -c \
  'from browser_e2e_runner import main; raise SystemExit(main(production=True, timeout_seconds=600))'
```

Backend integration tests 使用隔離 PostgreSQL 18 container。可透過私有
`STUDYDY_TEST_POSTGRES_DSN` 指向專用 `studydy_test*` control database；不可指向產品 DB。
測試涵蓋 schema installation、ownership、immutable Knowledge Structure、source-bound
Assessment、答案保密、scoring、idempotency、learning resume 與教材刪除競態。

`test_native_ingestion.py` 驗證純文字與混合頁只產生 native Evidence、原生文字與旋轉座標、
純掃描文件拒絕、excluded 尾頁可正常收尾，以及無效圖片 metadata 不會虛構文字。
Runtime tests 驗證 lock／binding identity、來源契約與已保存教材的讀取相容性。

API/DB browser tests 使用 backend 8003、frontend 4175；保持這些測試 port 可用。
其 saved fixtures 驗證帳號隔離、教材庫與多來源轉檔、題組交卷／補強與學習復原，不呼叫真實模型。
Playwright suite 使用 mocked API 驗證 Map、Relations、PDF locator、Assessment、feedback
以及 desktop/mobile 的文字來源與 PDF locator。

若 `/tmp` 是空間不足的 tmpfs，為 Chromium 設定有足夠磁碟空間的私有 temp 目錄：

```bash
mkdir -p .studydy-product/browser-tmp
export TMPDIR="$PWD/.studydy-product/browser-tmp"
```

## 本次同步範圍與隔離

產品功能、API 與 UI 以主專題 main `b0b34273` 為基準；競賽版只保留自己的
原生文字擷取與 Gemma HTTP 邊界。`backend/tests/conftest.py` 阻擋真實 HTTP 模型連線；
`MockTransport`、合成模型回應與本機測試 API 仍可使用。沒有執行 Pod preflight 或真實推論。

多來源測試需要[本機轉檔環境](document-normalization.md)。此工作區的
`.studydy-runtime/normalizer-venv` 唯讀共用主專題同名環境，不更動套件或 product DB。

`test_assessment_sets.py`、`test_assessment_set_submission.py`、`test_assessment_remediation.py`
驗證題組、原子交卷、重播、部分失敗、錯題補強與獨立掌握邊界。
`test_source_revisions.py` 驗證來源順序、追加、取消、復原、保存與 owner 隔離。
對應 browser tests 驗證真 API／隔離 DB；frontend specs 覆蓋桌機／手機版面、來源確認、
學習導覽與答案回顧。這些測試不等於 Gemma 內容品質驗收。

舊單 PDF／單題契約依使用者要求退役，不提供 legacy reader。0001–0006 migration checksum
保持不變；0007–0014 只在隔離 DB 驗證，本次沒有升級或啟動產品服務。

## 2026-09-23 同步驗證

- 完整 backend 回歸先為 359 passed／2 failed；兩個測試的正式版 lock 版號假設改為競賽版設定後，包含它們的 32 個接續／原生文字／複核案例通過。
- 20 個受控 HTTP 契約案例通過，包含 material semantics、material review 與 assessment 共用競賽版固定服務的檢查。
- 390 個前端 mocked browser 案例通過；真 API／DB browser 另包含在 backend 回歸中。
- Node tests、TypeScript 與獨立 production build 通過。Playwright MCP 另核對 1536px／390px 多檔選取、六題交卷、答案回顧與来源對話框，未發現橫向溢出。
- 全部使用合成教材、本機轉檔與隔離 DB；沒有 Pod、真實模型呼叫或產品 DB migration。不得以此宣稱 Gemma 內容品質已驗收。

## 真實產品驗證

自動測試不代替真實 Gemma 與教材驗證。透過正式 UI/API 上傳操作者授權的 PDF，確認：

1. 文字型 PDF 保留 PyMuPDF native Evidence，圖片推論呼叫為零。
2. 混合頁保留文字，圖片只在原 PDF 查看；無可讀文字的頁面明確列為 excluded。
3. 純掃描文件明確不支援，不建立虛構 Evidence 或呼叫 Semantic。
4. Knowledge Map／Learning Path 可讀，Assessment 可建立、作答、取得 feedback 與重新開啟。
5. Source PDF locator、review 狀態與已保存的學習紀錄正確，錯誤如實呈現。

真實教材、回應、畫面與檢查紀錄放在 `/tmp` 或私有 ignored 目錄，不加入公開 repository。
不要把測試 artifact 當作產品 fixture 或把未執行的檢查標記成功。
