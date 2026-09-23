# 多來源教材建立與增量更新（B3-A／B3-B）

教材可由一份或多份來源初次建立，也能在建立後追加來源，沿用目前版面與 B02 轉檔。每份原檔、每份轉換後 PDF 各自上限 100 MiB；不新增檔數上限，不保存合併 PDF。

## 初次多檔建立（B3-B）

上傳頁接受多選／拖放與混合已支援格式，逐檔顯示驗證及上傳狀態；全部使用既有 draft→sources→revisions 流程。即使只有 PDF，也先進入來源確認頁。上傳、GET 與 reload 不啟動語意分析。

每份檔案保留獨立 Idempotency-Key；部分上傳失敗只重試尚未收到成功回應的檔案，已確認上傳者不重送。確認頁可逐檔預覽、重試轉換、明確移除未封存來源，並調整這次初始來源的順序。顯示份數、全部 ready 後的總頁數與原檔總容量。有 pending／failed 檔或尚未完成的上傳時不自動開始，也不默默略過來源。

使用者確認後提交 `base_revision=null` 與有序 ready normalization 清單，沿用同一 SourceSet、worker、KS v4、發布及來源回查流程。開始後輸入集合固定，後來上傳者不混入。初次多檔建立後可直接使用 B3-A 追加；既有來源不開放重排。B3-B 沒有新增資料庫 migration 或更動模型 prompt／runtime lock。

## API 與輸入

- `POST /v2/materials/{id}/sources` 保存原檔與轉換工作，不自動開始分析。同一 Material 的相同原檔 SHA 明確拒絕；同名不同 bytes 可分別保存。
- 使用者預覽、勾選後，以 `POST /v2/materials/{id}/revisions` 提交 `material-revision-create/v1`、目前 `base_revision`、有序 `normalization_ids` 和 Idempotency-Key。後端從 base 取得原有成員，再附加選定且 ready 的來源。
- SourceSet、run 與 fingerprint 同交易封存；後來上傳的檔案不混入。每 Material 最多一個 active operation。同意圖重播回同 run，包括 head 已切換後；改順序、錯 base、競爭更新回 409。`base_revision=null` 接受一份或多份 ready normalization。
- `POST /v2/material-processing-runs/{run_id}/cancel` 的 closed body 為 `{schema:"material-revision-cancel/v1",base_revision:...}`，僅取消該次追加。重播回已保存狀態；已完成的 run 保留結果。
- `DELETE /v2/materials/{id}/sources/{source_id}` 只清理未被 SourceSet／run 引用且沒有運行中轉檔工作的 staged source。已分析來源可取消勾選，不可刪改已發布集合。

沿用 owner、Origin、artifact 權限邊界。GET、預覽與登入不啟動模型或建立學習紀錄。

## 來源與增量語意

`bundle-manifest/v2` 將集合內的閱讀序號映射到來源與 normalized page；該序號不代表合併 PDF 頁碼。`knowledge-structure/v4` 使用 `source_set_sha256`，不把集合 digest 偽稱為某份 PDF 的 SHA。原檔／normalized／mapping hash、policy、順序與 bundle hash 皆綁定 run／KS，處理與讀取時驗證。

現行追加只接受已有來源集合綁定的 v4 KS；單 PDF identity 補建與未綁定 v2／v3 reader 已移除。既有資料不改寫、不重算。

舊 Evidence／Claims 由已驗證基準重用，以原始與 normalized hash、頁碼、原文、區塊順序及 region 對應到新集合。只對新增來源執行 原生文字擷取／semantic calls。請求包含新 Evidence、既有概念 catalog 及各 Claim 的來源 scope，不反覆送入整份舊頁面 metadata。

沿用 Claim grounding、字面值保護及 Relation validators。模型的 `review_required=true` 只是來源 scope／概念分組的複核提示，不能據此認定教材互相矛盾，也不停止整次更新。可回查的新增 Claims 照常納入，既有 Claims 不改寫；提示以 `source_review_required=true` 與 `SOURCE_REVIEW_SUGGESTED` 保存，品質為 `needs_review`。此版本沒有任意語意修訂或自動衝突裁決引擎。

material request 為 v3、response 為 v5，記錄來源 scope 與 review flag。bundle policy 為 `contiguous-evidence-new-input/v4`，Gemma 以相同 tokenizer 與輸出預算逐批安排新增 Evidence，不裁切單一來源區塊。

## 學習進度

新版 session 仍由明確操作 ensure。新舊 Claim 只有文字、來源及區塊定位完全相同且一對一時才承接；有歧義、變更、拆分或合併者不自動承接。

舊 AnswerEvents 僅在記憶體中投影為新版 Claim 的學習證據，交給同一 learning-state reducer。原事件、題目、答案、評分、revision 和時間不改寫，不複製假事件。新增 Claim 沒有作答證據；Concept 仍須全部 Claims 符合既有規則才可 mastered。

舊分頁後續提交仍屬原題，新版重新讀取時可反映到未變 Claim。作答、引導與 head 切換採 Material 範圍鎖；resume 的一致性檢查包含承接後的 progress revision。學習位置只在基準 current Concept 可唯一對應時承接。

## 發布、取消及清理

KS insert、run terminal binding 與 head 更新在同一交易，以 Material→run 鎖序重查 base/head、取消／刪除意圖及 worker token／lease。通過結構與來源驗證、且至少有一筆 Claim 引用新增教材 Evidence 的結果會切換 head，包括 `partial / needs_review`。關係被拒絕、字面值修復及其他品質提示如實保留，作為複核提醒，不要求完美關係，也不阻擋後續追加。

若新增教材完全沒有產生可用 Claim，回報 `NO_USABLE_ADDED_CONTENT` 並保留原圖，不把重用舊內容當成更新完成。來源／結構錯誤、處理或儲存失敗、取消及 base 衝突同樣不發布。

Worker lease 為 10 分鐘，由 checkpoints 及處理期間每 30 秒的存活檢查延展；等待模型期間也會續租，lease 不作為模型執行時間上限。既有 worker 週期檢查過期工作。已保存取消可收斂為 cancelled，晚到結果不得發布。取消意圖不保證立即終止在途模型計算。

## 分批保存與失敗重試

分析完成每一批後，先將 Evidence context、累積語意狀態、精確 Evidence 游標與工作量原子保存，才更新頁數進度。保存位於 private artifact root 的 `analysis/{learner}/{material}/{run}/`；目錄 0700、checkpoint 0600。checkpoint 用於進行中或失敗工作的接續，地圖發布交易 commit 後即清理；`partial`、`needs_review` 或 `source_review_required` 品質提示不延長其保留時間。模型呼叫的輸入、schema、原始回應及 stdout／stderr 仍保留作私人查核資料，不寫一般 log／Git；本次清理不刪原檔、正式地圖或作答紀錄。

明確重試會建立新 run，僅從同 owner／Material、相同來源 artifact／SourceSet／base revision 與教材分析設定的失敗作業接續。migration 0010 的 `runtime_lock_document` 保存工作開始時的非機密設定，先核對原始 runtime binding，再比較 Python、原生文字擷取、教材語意設定及實際模型執行身分；assessment 與整份 lock 版號不參與相容性判定。所有工作使用同一套流程，沒有 legacy 分支。

來源 bytes 仍先經原有 hash 驗證，checkpoint 的 digest 與 signature 仍對應其原 run，不改寫成新 hash。進度損毀回 `ANALYSIS_CHECKPOINT_INVALID`；原設定缺失或教材分析依賴不一致回 `ANALYSIS_RUNTIME_CHANGED`，不暗中改成全量重跑。已建立的 pending／running 工作使用其封存設定執行及發布，只改出題設定不會讓最後發布因版本不同而失敗。游標是區塊位置，所以最後一頁有多批時，也不會把 `90 / 90` 誤當全部分析完成。

中途失敗重用已完成批次與 Evidence，僅對未完成批次呼叫模型；若只剩 deterministic construction／publication，就重做該步，不需要 OCR、模型連線或新推論。保存的 metrics 包含沿用的分析工作量；新呼叫應以該 run 的呼叫產物核對，不能將沿用結果冒稱新的模型執行。發布後用小型 `completion.json` 記錄可核對的 `reused_from_run` 與發布 revision，不保留完整恢復狀態；同一封存輸入與 runtime、已被此次成功工作涵蓋的舊失敗 checkpoint 一併清理，原失敗 run 狀態及錯誤紀錄不改寫。

模型完成、頁數到 100% 或 checkpoint 的 `complete=true` 都不能取代 DB 發布完成。未發布的失敗工作，以及不同輸入或 runtime 的失敗 checkpoint 繼續保留；來源損毀也不自動改成從頭重跑。發布成功後若檔案清理失敗，記錄 `ANALYSIS_CHECKPOINT_CLEANUP_FAILED`，由 worker 啟動與既有恢復週期補做，不把已發布結果改回 failed。成功工作的 checkpoint 即使損毀也不再需要恢復，可在記錄接續來源資訊不可用後清理。晚到 worker 不得向已結束 run 寫回 checkpoint。

使用者明確刪除整份教材時，才連同其餘私人分析查核資料清除；刪除已提交但檔案清理中斷時，啟動會核對 Material 已不存在後補完。取消、worker token 與整份刪除意圖仍阻止晚到 worker 發布或重建已刪除資料。

`material-processing-run` 回應帶 `analysis_saved`，失敗頁據此顯示「接續已保存的分析」。沒有保存資料的舊失敗作業不宣稱可恢復。

失敗頁直接呼叫 `POST /v2/material-processing-runs/{run_id}/retry`（空 body、Origin 與 Idempotency-Key）。後端從該次 frozen SourceSet／base run receipts 取回原追加清單與順序，再建立重試 run；不重新讀取 staged 清單來猜使用者意圖，也不納入後來上傳的檔案。回應遺失沿用同 key，即使 head 已切換、舊完整 KS 已清理也可重播。修改來源是另一個明確操作。

若先前失敗原因是完全沒有可用概念／新增知識，重試仍重用 Evidence，但會重試語意步驟，不會卡在反覆組裝同一個空結果。原模型回應仍保留以供查核。

舊流程若僅因 `SOURCE_UPDATE_NEEDS_REVIEW` 停止，重試會比對並沿用該批已保存回應，再繼續尚未完成的批次。比對仍要求同來源與 runtime、完整請求內容相同；catalog 以概念 key 對齊，避免 checkpoint JSON 的字典排序讓等價 catalog 被誤當不同輸入。這是修正後端對既有旗標的解讀，沒有改模型、分批目標或來源綁定，也不回寫舊 KS。

產品提供目前地圖，舊一般 Map 連結在確認有效 run binding 後導向 head。partial 更新顯示「教材更新完成」並附複核提醒；學習紀錄仍以 exact revision 讀回原題。

發布後清理無 StudySession／active run 引用的舊完整 KS，保留 head。被學習紀錄引用的舊 KS 仍是必要資料。小型 run receipts／SourceSet metadata 留作重播和稽核；原檔及轉換 PDF 跨更新重用，不累積每次合併檔。取消勾選本身不會刪除來源。

## 升級與驗證

新增 `0009_material_source_revisions.sql`，0001–0008 不改寫。競賽版沿用 0007–0014 migration，不保留舊單 PDF／單題 reader。產品 DB 升級、服務切換仍需獨立授權；寫入 v4 後採 forward repair 或經授權備份恢復，不直接切回不支援 v4 的 binary。

`test_source_revisions.py` 覆蓋增量輸入、重播／競爭、late upload、取消發布、fencing、進度承接與 staged cleanup。`test_source_identity.py` 驗證來源穩定與歧義拒絕。`test_source_revisions_browser.py` 使用真 API／DB／轉檔／worker 與受控語意 fixture，驗證 desktop／390px、reload、來源與已保存作答；`source-revisions.spec.ts` 驗證佇列和取消不發整份教材 DELETE。

合成測試只證明功能契約。真實替代模型須另外記錄狀態、來源、coverage、呼叫量與限制；`needs_review` 不算 accepted。尚未宣告大型教材容量、任意來源衝突或正式模型品質通過。
