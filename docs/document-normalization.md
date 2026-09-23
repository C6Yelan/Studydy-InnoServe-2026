# 單檔文件轉換（B2-I）

PDF 是主要教材格式。其他已開放格式上傳後自動轉成 PDF，轉換品質不保證；保留原檔、轉換後預覽及來源回查。首次多檔建立與既有教材追加見 [B3-A／B3-B](source-revisions.md)。以下逐檔轉檔政策沿用 B02。

## 環境與啟用

若 `.studydy-runtime/normalizer-venv` 已連到共用環境，請直接沿用，不重新建立或安裝套件。

PDF、DOC／DOCX、PPT／PPTX、UTF-8 TXT／Markdown 的單檔上限統一為 100 MiB（104,857,600 bytes），包含原 PDF v1 與新來源端點；轉換後 PDF 也使用相同單檔上限。不另設頁數、段落數、ZIP 項目數、解壓總量或壓縮比使用門檻。需要 LibreOffice **26.2.5.2** Writer/Impress、bubblewrap、fontconfig、Noto CJK 與一個獨立的 Python 3.12 converter 環境。不要修改正式版與競賽版共用的 backend/.venv。

```bash
uv venv --python backend/.venv/bin/python .studydy-runtime/normalizer-venv
uv pip install --python .studydy-runtime/normalizer-venv/bin/python -r backend/normalizer-requirements.txt
export STUDYDY_NORMALIZER_PYTHON="$PWD/.studydy-runtime/normalizer-venv/bin/python"
```

可將 normalizer Python 絕對路徑存入本 checkout 的 `.studydy-product/private-config.json` 的 `normalizer_python`。既有 launcher 只注入轉檔環境，不切換 AI；私人設定不提交 Git。

未設定 converter 時初次上傳只宣告 PDF 來源格式。來源轉檔／追加須有本節的 normalizer 設定。B02 使用 migration 0007／0008，當前 B3-A worker 另需 0009；不要在舊 schema 啟動新 worker。正式 DB 升級須依工作區資料政策，先有明確授權、可驗證備份與回復計畫。這裡的指令不是自動套用正式資料的授權。

Normalization policy 的 `version` 已升為 3（加入 olefile 0.47 的舊 Office 辨識），包含統一檔案大小設定；已完成的舊 normalization／SourceSet 不改寫，新操作採新 policy。執行期記憶體與逾時防護繼續保留，無法完成時回報失敗。

## 資料生命週期

1. `POST /v2/materials`：建立草稿，body 為 `material-draft-create/v1` + `display_name`，使用 Idempotency-Key。
2. `POST /v2/materials/{id}/sources`：raw bytes、實際 MIME、URL-encoded `X-Material-Name` 與獨立 Idempotency-Key。保存原檔 receipt 和 pending normalization，HTTP request 不執行轉檔。
3. worker 領取 source normalization，轉檔在 DB transaction 外；120 秒 lease、最大 60 秒子程序 wall time。意外中斷後 expired lease 可重領，最多 3 次；使用者可明確 POST retry。
4. ready 原子發布 normalized PDF／mapping。失敗保留原檔與固定錯誤代碼。改變 renderer policy 後重試會建立新 normalization record，不改寫舊 ready record。
5. `POST /v2/materials/{id}/revisions`：初次使用 `material-revision-create/v1`、`base_revision: null`、一份或多份 ready `normalization_ids`、獨立 Idempotency-Key。短交易內封存有序 SourceSet 與 run。B3-A 起沿用各來源 normalized PDF，以集合閱讀序號映射來源頁碼，不另存合併 PDF。
6. UI 用既有 run 頁顯示分析；開始分析是明確操作，GET／reload 不生成、不轉檔。新 run 回應 `material-processing-run/v6` 並帶 `input_source_set_id`；不再提供 v5 run reader。

單來源頁碼映射為 identity；bundle manifest 保存在 run JSON + hash，mapping bytes 在 private artifact store。所有原檔／normalized／mapping 使用既有 owner-scoped store。B3-A 的多來源資料契約見其專頁。

## 來源與資料保存

Migration 0008 只擴充原檔 MIME，新增 application/msword／application/vnd.ms-powerpoint，不改既有資料。

Migration 0007 增加來源、normalization、SourceSet／items、run bundle binding 與 nullable draft/head 欄位；不改 0001–0006 SQL。歷史 migration 的 PDF backfill 保持原樣；現行建立入口只有來源集合，不再提供 v1 PDF upload 或舊 PDF reader。

B02 保存的 KS 為 `knowledge-structure/v3`；B3-A 新來源集合使用 v4，詳見其文件。content revision 包含 input binding；已保存版本保留原嚴格驗證。read 再核對 SourceSet membership、三種 artifact SHA、bundle page map 與 runtime 身分；不接受 client 任意 URL 或路徑。草稿／失敗轉檔也能找回及刪除。

`GET /v2/materials/{id}/knowledge-structures/{revision}/evidence/{id}/source` 以 exact KS/Evidence 回查 normalized page 與相交的來源 block：

- PDF：原頁碼。
- PPTX：原投影片編號；hidden slides 和 notes 不匯出，原编号不重編。
- DOC／PPT：先確認舊二進位 Office 容器與類型，轉成 PDF；原生 locator 標示 unavailable，提供轉換後頁碼與原檔下載，不偽造原頁碼／投影片編號。
- DOCX：轉換後頁碼；paragraph anchors 可 exact／ambiguous／unavailable，不冒充作者 Word 分頁。
- TXT／MD：原始行／block 範圍，視覺換行不改 source line。

Map、Relation、Study、Assessment 共用來源按鈕，分開「開啟 PDF 來源頁」和「下載原檔」。非 PDF 原檔以 attachment、正確 MIME、nosniff 下載；不直接渲染任意 HTML。原生定位缺失時仍回查轉換後 PDF，不偽造位置。

完整刪除先等待／取消活動工作，再移除所有 owned artifacts、SourceSet 與學習資料。新 artifact 發布留下 pending marker；commit 結果未知時依 DB reference 決定保留或清理。quarantine rollback 使用原 reconciliation，不刪其他使用者資料。

## 隔離與限制

所有格式的解析（含 Story）在無網路 bubblewrap 中執行；只掛必要唯讀系統／Python／renderer／input 路徑，output 可寫，profile/temp 在獨立 tmpfs。子程序 CPU 45 秒、address space 2 GiB、單檔 100 MiB、128 descriptors、wall time 60 秒；NPROC 1024 為每 UID 限制，不是 cgroup 的每 job aggregate memory/process quota。

舊 DOC／PPT 使用 olefile 0.47 辨識 OLE 容器和 Word／PowerPoint stream，拒絕可辨識的巨集、主動物件及加密容器；不支援或受密碼保護的內容會如實失敗。LibreOffice 使用最高巨集安全層級的獨立 profile。

OOXML 保留檔案類型與 ZIP 路徑檢查，拒絕加密、宏與外部 relationships；不按頁數、ZIP 項目數、解壓總量或壓縮比拒絕檔案。Markdown raw HTML 不執行、圖片不載入、連結以文字呈現。TXT 長行按 72 顯示欄位有界換行；Markdown 複雜排版與長 code 仍屬盡力轉換。100 MiB 是產品大小上限，不保證所有上限內文件都能轉換成功。不能以此宣稱解析所有 Office 文件，或以 exit 0 代替有效 PDF／hash 檢查。

## 競賽版擷取與模型

競賽版在來源轉為 PDF 後只擷取可靠的原生文字，不啟動 Unlimited-OCR 或圖片模型。
Semantic、教材複核與題組都使用競賽版 runtime lock 的同一 Gemma HTTP 服務。
不載入 `STUDYDY_SEMANTIC_COMMAND_CONFIG`，也不執行 `codex exec`。

## 驗證與部署邊界

- 後端標準測試使用 disposable PostgreSQL。converter 測試需上方獨立環境。
- `test_source_normalization.py` 覆蓋實際轉檔、owner／origin、replay、lease recovery、policy version、snapshot、來源回查、legacy／完整刪除保存。
- 瀏覽器 fixture 可用 `STUDYDY_E2E_FRONTEND_PORT=4175`、`STUDYDY_E2E_API_PORT=8003`，不必停止使用者 4176／8002 服務。production preview 驗證真實建置；fixture transport 不啟動模型。
- migration rollback 不刪新資料；寫入 sources-v2 後要保留新 reader，採 forward repair 或經授權的 DB backup restore。不要直接切回舊 binary 期待它能讀所有新格式。

本頁說明 B02 轉檔基礎；B3-A 追加見獨立文件，B4 地圖改版與 B5 題組仍不在本批範圍。
