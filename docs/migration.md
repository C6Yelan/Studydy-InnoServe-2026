# Compose 切換與還原

[文件入口](../README.md) · [安裝](getting-started.md) · [測試](testing.md)

## 目前狀態

競賽版已依使用者授權切換至 Docker Compose，入口為 **http://127.0.0.1:4176**。前後端與資料庫使用正式版 `bf678484` 基線；migration SQL、版本 0001–0005 與 runner 均與正式版完全相同，不再維護競賽版 0001–0015 分支。後續兩版同步新增 0005，讓失敗來源可退出教材清單，保留歷史來源與 artifact；原 0001–0004 checksum 未變。

主要產品差異是 native-text-only：不包含 Unlimited-OCR loader、套件、權重或 GPU 裝置。Python、Node、依賴 lock、Nginx、LibreOffice、字型與 Bubblewrap 層對齊正式版。共用 `backend/.venv` symlink 未變動。

切換時模型連線保持停用；後續已依使用者提供的臨時 Pod 更新競賽版 `.env`，啟用 SSH profile，金鑰與 known_hosts 沿用既有檔案唯讀掛載。中文三份 demo 已完成真實分析、初篩、錯題補強、追加來源、進度承接與歷史恢復；候選生成與檢核額度均已提高至 16384 tokens。失敗來源移除修正亦完成線上補測。這些結果限於已測中文展示流程，不代表任意教材、全數內容品質與跨帳號隔離都已完整驗收。

## 獨立部署

| 項目 | 競賽版 | 正式版 |
| --- | --- | --- |
| Compose project | `studydy-competition` | `studydy` |
| 前端 | `127.0.0.1:4176` | `127.0.0.1:4173` |
| API | 同一入口 `/v1`，Nginx 轉送 | 相同 |
| 容器內 API | `backend:8001`，不發布主機 port | 相同 |
| PostgreSQL | `studydy-competition-postgres-1` | `studydy-postgres-1` |
| 設定 | 競賽 checkout `.env` | 正式 checkout `.env` |
| 持久資料 | `.studydy-product/compose/{artifacts,postgres}` | `data/{artifacts,postgres}` |
| 現行 migration | 正式版 0001–0005 | 0001–0005 |

日常在本 checkout 執行 `docker compose ps`、`up -d --wait`、`down`。不使用舊 host 啟動器；不停止或刪除保留資料的 `studydy-product-postgres`。

## 舊資料與 migration 帳本

切換前實際 DB 只有 0001–0006：2 個帳號、15 筆登入 session、6 份教材與原檔、7 筆分析、5 份知識結構、5 題與 4 筆作答，沒有未完成工作或其他 DB 連線。checksum 均已核對。

先備份並還原產品資料，驗證 11 張原資料表的完整 row 摘要一致，再演練並套用 0007–0015；原有欄位、來源、artifact hash、模型身分與 checksum 均未改寫。依使用者後續要求，最終改為正式版相同的 migration 基線：

1. 在停止競賽寫入後追加備份。
2. 將這份已還原資料庫的 16 張歷史表、保護函式及完整 ledger 移入 `competition_before_main_baseline` schema。這個 schema 只供保留／回復，不是產品 reader。
3. 由**未修改的正式版 migration runner** 在新的 public schema 實際執行 0001–0004，再執行一次確認不變。沒有把舊 ledger 的版本或 checksum 改成新值。
4. 將原帳號及登入 session 複製到現行 public schema，逐筆核對內容一致；歷史 schema 的 rows／checksum 也再次核對不變。

依使用者決定，舊教材、地圖、題目、作答與 checkpoint **不提供相容讀取**。新版教材庫由新上傳內容開始；舊內容仍在歷史 schema、原 DB、原 artifact root 與備份中，沒有刪除或清空。退役的 Pod／DB JSON 已從產品根目錄移除，只在原切換備份保留；目前部署連線設定統一由 `.env` 提供。舊 PDF 不會被重標為 OCR，也不會以新轉檔 policy 回填其歷史身分。

## 備份

本次私人備份位於：

`.studydy-product/backups/competition-compose-20260927-064740/`

備份目錄 0700，檔案 0600。包含：

- `database.dump`：切換前原產品 PostgreSQL 18 dump，原帳本至 0006。
- `artifacts.tar`、`artifacts-manifest.json`：6 份原檔，共 23,078,352 bytes；內容 SHA-256 與原本 0400 mode 均核對。
- `database-before.json`、`database-restored.json`：還原前後每表筆數與完整內容摘要。
- `before-canonical-baseline.dump`：採用正式版 public schema 前的追加還原點。
- 原私密設定、切換當時的 `compose.env`、舊／新 source archive、映像識別及完整性記錄。備份中的 Pod 設定是歷史還原資料，不代表目前臨時 Pod。
- `superseded-migrations/`：已退役競賽 SQL 的原始 bytes，保留供核對舊帳本，不屬現行產品 migration。
- `baseline-adoption.py`、對應合成演練及驗證摘要：說明這次 namespace 切換，不加入產品相容路徑。

解開 artifact archive 時，安全的 tar data filter 會增加 owner write；本次先核對 bytes，再依原 manifest 恢復 0400。原始教材與舊 store 完全不改動。

## 還原

1. 先停止競賽 Compose 寫入並備份切換後的新 DB／檔案；不操作正式版 project，不刪除任何產品資料目錄。
2. 需要回到切換前狀態時，原競賽 DB 仍在 `studydy-product-postgres`，原私密設定副本在上述備份目錄，原 artifact root 仍保留。先保存現行未提交修改，再於同一競賽 checkout 還原對應 source／設定；不建立第三份應用 checkout、不重寫 Git 歷史、不從備份目錄啟動產品。
3. 需要由 dump 還原時，建立明確命名的空白**產品還原目標**，使用 PostgreSQL 18 `pg_restore --no-owner --no-acl --exit-on-error --single-transaction`，artifact 解到新的私人目錄，再核對原帳本與完整摘要。不得使用 `--clean` 或覆蓋既有產品 DB。
4. 舊帳本不能拿給現行 runner 冒充同一 lineage；回復 source／schema／設定必須相符。不得刪除 public ledger 或修改 checksum 來迫使啟動。
5. 新版啟用後的教材／作答要另外保留；舊格式不相容，恢復前由操作者決定恢復點，不能默默丟掉新資料。模型／SSH 排除不因還原而解除。

## 驗證

- 原資料 restore、全部原欄位／row／artifact hash、原 SQL checksum：通過。
- 新基線 adoption、checksum 拒絕、交易回滾、主版本 migration 與 artifact store：18 項合成測試通過。
- 現行四份 SQL 及 runner 與正式版逐 byte 比對；歷史 ledger 保留於封存 schema。
- 切換前無網路容器單元／沙箱 161 passed，mock browser 248 passed；Node 6 份測試檔、TypeScript、production build 通過。
- 容器真 DOC／DOCX／PPT／PPTX／TXT／Markdown 轉檔、owner 隔離及重啟恢復已通過隔離測試。
- 產品容器另以暫存合成 DOCX 驗證真 LibreOffice／Bubblewrap 轉檔及 native 擷取，OCR 呼叫數 0，不新增測試教材至產品 DB。

新的 0001–0004 baseline 完整 runtime／真 API／隔離 DB browser 回歸為 **208 passed**（291.94 秒，無 skip），沒有未解決失敗。4176 的桌機／手機登入頁、現行 OpenAPI 與未登入資源保護亦通過；正式版與保留的舊 DB 持續運作。以上本機驗證不代表 Pod 或真實模型品質已驗收。
