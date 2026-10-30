# 教材處理

[文件入口](../README.md) · [使用指南](usage.md) · [系統架構](architecture.md)

## 來源與轉檔

教材是具名的來源集合。單檔與轉換後 PDF 上限皆為 100 MiB，格式能力由/v1/source-capabilities 宣告。

| 格式 | 處理與定位 |
| --- | --- |
| PDF | 驗證原檔、建立預覽與 mapping，使用原頁碼 |
| DOCX | LibreOffice Writer 轉 PDF；使用轉換後頁碼，段落對照可能有歧義 |
| PPTX | LibreOffice Impress 轉 PDF；排除 hidden slides／notes，保留原投影片編號 |
| DOC／PPT | 檢查二進位 Office 格式再轉 PDF；僅提供轉換後頁碼 |
| UTF-8 TXT | 有界換行排版；保存原行號及 PDF 頁碼 |
| Markdown | 限制 HTML 排版；raw HTML 顯示為文字、不載入圖片，保存 block 及 PDF 頁碼 |

文字轉檔政策為第 4 版；72 欄軟換行保留 LaTeX 指令、英文單字與數字，避免回讀 PDF 時拆成不同字面值。已完成的來源快照不重寫；失敗來源重試依既有流程採用現行政策。

原檔、PDF 與 mapping 各自保存 hash。下載使用原 MIME 與 attachment，PDF 預覽使用獨立入口。解析在無網路 Bubblewrap 子程序內執行，唯讀掛載 runtime 及輸入，僅輸出／暫存可寫。資源限制、版本檢查與禁止的主動內容見 [converter.py](../backend/src/document_normalization/converter.py) 及 [renderer.py](../backend/src/document_normalization/renderer.py)。

## 草稿與來源快照

建立草稿後，各檔案以獨立 Idempotency-Key 上傳並排入轉換。使用者確認就緒來源與順序，後端同交易封存 SourceSet、bundle manifest 與 processing run；之後上傳的檔案不混入已建立工作。

相同意圖重播不重複建立；輸入、順序或 base revision 不同則拒絕衝突。未被使用的來源可移除；只被 failed／cancelled 工作引用的來源可退出清單，內部保留原檔與封存關係。正在處理或已發布結果使用的來源受保護。重新上傳使用新的意圖，已移除 normalization 不能用於新分析。

## Evidence 與分析

PDF 有可讀文字層時直接建立原生 Evidence；其餘頁面以 Tesseract chi_tra+eng 取得文字與區塊位置。純文字頁建立 Tesseract Evidence；公式或表格頁標示「需對照原圖」，暫不納入概念與練習。混合來源保留可用頁；整個來源集合沒有可用 Evidence 時顯示原因，不發布空地圖。

Evidence 保留教材、1-based 頁碼、區塊、定位及技術字面值。換行合併依幾何與段落結構，不跨欄猜讀序。

語意請求按章節與 Evidence 分批，以實際 tokenizer 核對 prompt、概念目錄與輸出預算。模型引用完整 Evidence handle；程式還原來源關係並驗證 Claim、Relation 及 Path。設定以 runtime lock 為準。

## 檢核與發布

初次分析與追加結果都經教材檢核。模型提出整合、案例歸屬、別名、文字及關係修正；程式核對覆蓋、來源、先備關係與字面值。覆蓋／歸屬錯誤可有界補正，無來源支持的修改保留原文或拒絕發布。

有可用新增內容的 partial／needs_review 結果可發布；無可用新增內容、取消或失敗時保留目前 head。已發布教材可由/v1/materials/{material_id}/review 建立只檢核的新版本，尚無獨立 UI 入口。

## 追加與接續

補充研究依使用者確認的範圍執行規劃、篩選、來源類型核對、定位、閱讀與補查，各模型階段共用 Gemma HTTP。研究邊界先核對回應欄位、型別、列舉與索引範圍，再進行原文引用及涵蓋檢查；非法候選記為失敗，可重試或取消。

搜尋保留 SearXNG 的 Wikipedia 管道與學術論文來源。來源身分及授權由取得流程核對；模型不能自行授權匯入。已核對正文保存為快照，使用者選取後沿用同一份內容交接教材處理。Wikipedia 數學元素以 MathML 的完整 alttext 保存原始 LaTeX，正文擷取後才還原，避免截斷的 annotation、外溢殘文或 Markdown 轉義損壞公式；每個公式只保留一次。一般圖片仍不納入正文，原始位元組與授權快照 hash 不變。

追加只分析新增來源，再整合檢核；發布同交易更新知識結構、run 與教材 head。教材庫開目前 head，學習依 exact revision 恢復。被學習或活動工作引用的結構保留，其餘完整結構可清理；來源檔跨版本重用。

Checkpoint 保存 Evidence、累積狀態、游標及執行快照。相同 owner、教材、輸入與分析設定的重試可重用已完成批次；只剩確定性建構／發布時不再推論。損毀或設定不符時停止，不靜默重跑。

私人 analysis archive 保存請求與回應；重用和新增呼叫分開計數。Checkpoint 只在 DB 確認發布後清理，失敗由 worker 補做，過期 worker 不能重建已結束工作的狀態。

## 取消與刪除

取消更新保留已發布地圖與學習；刪除整份教材則先保存意圖、阻止新工作及過期發布，再清理來源、分析與學習資料。檔案先進 quarantine，DB 回滾時還原、提交後刪除，清理可重試且不影響其他教材。

取消不保證外部服務立即停止已送出的計算。教材改名只更新顯示名稱，不改 hash 或學習紀錄。

影音與 YouTube 來源以本機語音辨識產生逐字稿，再依原有來源工作建立可回查的教材內容。上傳能力與大小依 `/v1/source-capabilities` 回傳的實際清單顯示；圖片組沿用 PNG／JPG／JPEG／WebP、最多 50 張、合計 100 MiB 與單張 4000 萬像素限制，依既有順序轉成 PDF 後走相同三級處理。

### 圖片頁分級與視覺接點

分類先採可讀文字層；無文字層時以 Tesseract TSV 的字詞及位置檢查公式符號、格線或跨列欄位空白。來源、1-based 頁碼、原圖 hash 與區塊座標都保留。這些規則不保證找出所有公式／表格，未自動驗收辨識品質。

`pdf_evidence.image_text.image_blocks` 的 `visual_reader` 接點只供已驗收的影像辨識器使用，接收原頁、公式／表格原因與取消檢查，回傳未旋轉 PDF 座標的 type/text/bbox 區塊。預設沒有接入器，產品不送出視覺模型請求；R0 候選結果不會自動發布。接入後以 gemma_visual 保留來源身分，仍通過共用區塊與座標驗證。

新生成的題目、筆記、概念卡與 Podcast 講稿以繁體中文呈現，英文技術術語可保留原文；Evidence 不翻譯。概念名稱兩輪翻譯失敗時仍保留原文退路。新擷取補充網頁移除編輯連結、上標引註與 Markdown 粗體格式；數學上標、公式與程式碼字面值維持原文，既有來源不回頭修改。

教材的「筆記」提供「複習速覽」與「完整筆記」，新生成契約為 `material-notes/v17`。章節依已保存原教材標題與原文順序，最多三層；多檔教材一檔一章，單檔沒有可用標題時以知識地圖分區作章節。每個重點按最早直接 Evidence 歸屬章節，每章開頭的大綱由程式列出小節。章節與缺漏清單保存於 `material_notes.published_metadata`（0032），隨正文在同一交易發布；已發布舊契約稿在更新前保持原樣。

複習速覽每章挑 3～5 條核心重點與必要公式，只呈現有正文的小節及其祖先；完整筆記盡力整理全部重點。內容核對每段一次：程式保留格式、引用、表格與公式檢查，模型判不符的句子／條列／表格列直接移除，段落沒有內容才刪段，不因涵蓋不足擋住整份發布。完整筆記每批核對後，對仍無已核對解說的概念補寫一次並走相同核對；補寫仍未通過就保留缺漏。刪除後未實際解說的概念放在 `unorganized_concepts`，筆記末尾列「以下概念暫未整理」並可在地圖查看；速覽只列同版本已發布完整筆記也未涵蓋的概念。正文全空且已有發布稿時保留舊稿，以 NOTE_NO_SUPPORTED_CONTENT 結束；首次全空則發布缺漏清單。格式、引用、公式或核對回應格式不合法時單批最多三次嘗試，provider、契約與容量錯誤不重試。前文只供去重與辨認情境，不作新證據。
