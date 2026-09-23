# 題目品質與可用性（B5-Q）

依 2026-09-20 使用者要求，品質改良採「安全候選排序」，不設教學品質最低分。目前由 B05 題組使用三個候選、一次 blind solve、後端評分與學習政策；舊單題 API 已移除；本文記錄 B5-Q；已完成的 B5-D 題組見 [assessment-sets.md](assessment-sets.md)，B5-R 補強見 [assessment-remediation.md](assessment-remediation.md)。下列各輪驗證與切換依當時狀態記錄。

## 正確性與品質分開

正解仍須是指定 Evidence 的原文 span，四個選項正規化後不同；另一個未取得私有答案的模型呼叫確認唯一可答，結果必須與私有正解一致。錯誤答案、多解、無解、來源不符與已知同事實重複仍拒絕。Structured Output 只驗格式，不能代替內容正確性。

同一次 checker 呼叫另外回報五種品質提示：無意義的題材、答案線索、措辭不清、選項型態不一致、干擾項偏弱。後端只在安全候選中比較：先避開無意義題材，再避開答案線索，最後比較提示數量；平手保留原順序。所有安全候選都有提示時，仍發布其中相對較好的題目，不追加模型呼叫追求完美，也不因品質提示降低該題既有的作答資格。重複列出的同一品質提示只算一次。

基礎定義、API 名稱、規則與直接回憶題皆可採用。干擾選項出現在教材其他位置不代表它能回答本題；相同答案詞也不代表兩題測的是同一件事。三個候選是擇一發布的替代題，不要求教材必須包含三個不同事實。

前置 `partial`、`needs_review` 或 `source_review_required` 不直接阻擋出題；依各題實際引用的原文判斷。Claim 只提供目標脈絡，不能提供原文不存在的條件。來源缺損與前置理解錯誤仍可能讓題目不可用，本改動不宣稱修復那些內容。無安全新題不產生 AnswerEvent、不代表學生不會；前端明示未出題不算答錯。

## 重複檢查與歷史

從同一 session／exact KS 的歷史題目挑選有限比較集合：同 Claim、Evidence 重疊、同 Concept、其餘近期題目依序優先。最多讀取 32 筆候選，完整納入最多 8 題及 12,000 UTF-8 bytes 的比較內容；超出時略過整題，不截斷題幹或來源。這是模型比較上下文的安排，不是教材容量或使用者初篩題數上限。

generator 與 checker 使用相同集合，checker 只接收歷史題目及選項，不接收任何私有正解。發布紀錄保存實際比較過的 Assessment revisions，不宣稱全歷史語意去重。同 session 的 exact normalized identity 另查完整已保存集合，即使該題未放入 prompt 也不重複發布。

## 版本與資料保存

競賽版同步 main 的 assessment 契約與 prompt：generator request v2、checker request／response v2、policy `source-span-single-choice/v6`、provenance v8。model、OCR、material semantics、context 與 generation budgets 保持原設定。競賽版仍只使用原有 Gemma HTTP 服務。

新 provenance 私存選中候選、檢查／安全候選數、品質提示、比較範圍及兩個 prompt hashes；模型身分與 runtime hash 保留於私有 provenance。公開題目、resume、history 不加入這些欄位或私有答案。

歷史紀錄不補欄位、不改 hash 或 mastery eligibility；現行 reader 僅接受 provenance v8，不再提供 v5–v7 相容分支。出題功能本身沿用既有資料模型；收尾的教材接續修正以 migration 0010 保存工作開始時的非機密設定。後續 B5-D 已將題組模型呼叫移至短交易之外，沿用本頁候選準備與檢查流程。

教材與出題設定已解耦：所有教材工作使用同一條執行流程，比對實際影響教材分析的 Python、原生文字擷取、semantic service 與 material semantics；不以 assessment 或整份設定的版號決定能否接續。工作保存開始時的設定並核對其原 runtime binding，執行與發布仍使用該份設定，因此不改寫舊 run、KS 或 checkpoint 的 hash。新重試可以重用分析設定相同的已保存進度；設定缺失、損毀或教材依賴改變時停止並明示，不能暗中重新分析。沒有新增 legacy 執行分支或按歷史版本切換的 fallback。

2026-09-20 後續已修正 [checkpoint 生命週期](source-revisions.md#分批保存與失敗重試)：地圖發布成功即清理，不受 `needs_review` 影響。已完成教材不需要 checkpoint 接續，也不因品質提示阻擋服務切換。

## 驗證範圍

`test_assessment_safety_v1.py` 驗證安全優先、品質排序、所有候選皆有品質提示仍可發布，以及合法基礎題與相同答案不同問題。`runtime/test_assessment_quality.py` 用真 PostgreSQL 與受控語意 fixture 驗證部分來源仍可出題、跨 Claim 重複不產生錯答、比較範圍及拒絕將舊題 provenance 當成現行契約；評分、重播與恢復由題組回歸涵蓋。

這些測試證明程式行為，不證明真實模型品質。替代模型舊新比較與正式 Gemma 品質需分別記錄；未執行的檢查不算通過。
