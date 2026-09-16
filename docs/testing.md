# 測試

從 repository root 執行。Python 使用 3.12；先完成[本地環境](local-environment.md)的依賴安裝。

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend/src:backend/tests backend/.venv/bin/pytest -q backend/tests
npm --prefix frontend test
npm --prefix frontend run typecheck
npm --prefix frontend run build
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend/src backend/.venv/bin/python backend/tests/runtime/browser_e2e_runner.py
```

Backend integration tests 使用隔離 PostgreSQL 18 container。可透過私有
`STUDYDY_TEST_POSTGRES_DSN` 指向專用 `studydy_test*` control database；不可指向產品 DB。
測試涵蓋 schema installation、ownership、immutable Knowledge Structure、source-bound
Assessment、答案保密、scoring、idempotency、learning resume 與教材刪除競態。

`test_vision_ingestion.py` 驗證 native-only 不送 Vision、scan／region 擷取、裁切與旋轉座標、
原生文字遮罩、來源保存、generation settings、truncation 及 unavailable fail closed。
Runtime tests 驗證 lock／binding identity、獨立 Vision／Semantic request 與來源契約。

三組 API/DB browser tests 使用 backend 8003、frontend 4175；保持這些測試 port 可用。
其 saved fixtures 驗證帳號隔離、教材庫與學習復原，不呼叫真實模型。
Playwright suite 使用 mocked API 驗證 Map、Relations、PDF locator、Assessment、feedback
以及 desktop/mobile 的 Vision 來源提示。

若 `/tmp` 是空間不足的 tmpfs，為 Chromium 設定有足夠磁碟空間的私有 temp 目錄：

```bash
mkdir -p .studydy-product/browser-tmp
export TMPDIR="$PWD/.studydy-product/browser-tmp"
```

## 真實產品驗證

自動測試不代替真實 Gemma 與教材驗證。透過正式 UI/API 上傳操作者授權的 PDF，確認：

1. 文字型 PDF 保留 PyMuPDF native Evidence，無需圖片輔助時 Vision calls 為零。
2. 圖片／掃描 Evidence 標示 `vision`，可回查原 PDF page／region，且不覆蓋 native text。
3. Knowledge Map／Learning Path 可讀，Assessment 可建立、作答、取得 feedback 與重新開啟。
4. 服務錯誤與 review 狀態如實呈現；Vision 不宣稱逐字無損。

真實教材、回應、畫面與檢查紀錄放在 `/tmp` 或私有 ignored 目錄，不加入公開 repository。
不要把測試 artifact 當作產品 fixture 或把未執行的檢查標記成功。
