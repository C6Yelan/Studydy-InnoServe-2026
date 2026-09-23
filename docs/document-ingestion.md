# 教材擷取

Studydy InnoServe 支援多來源教材；可用的 PDF、TXT、Markdown、Word 與 PowerPoint 格式由本機轉檔環境宣告。
所有来源先個別轉為 PDF 並確認順序，再以可靠文字層建立 Evidence。詳見[來源轉檔](document-normalization.md)。

```text
來源集合 → 本機個別轉為 PDF → PyMuPDF native text → Canonical Evidence → Gemma Semantic
    → Concept / Claim / Relation → Knowledge Map / Learning Path / Assessment
```

PyMuPDF 讀取原生文字、段落順序、文件雜湊、頁碼與原始 PDF 座標。
符合既有字元品質檢查的頁面建立 `source=native_text` Evidence。
文字 normalization 保持 Unicode NFC、換行與行內內容；程式碼、變數與標點不由擷取階段改寫。

圖片與圖表保留在原始 PDF，使用者可從 Evidence locator 回到同一頁查看。
系統不自動轉錄圖片、不把圖片內容當成 Semantic Evidence，也不推測圖片中的程式碼或關係。
原始 PDF 是完整教材；知識地圖只反映可擷取文字所支持的內容。

沒有可靠文字的頁面會記入 `excluded_pages`，包含頁碼、page reference 與原因。
其餘頁面仍有足夠 Evidence 時，沿用 partial／needs_review 與原頁回查契約。
整份文件沒有可用 native Evidence 時回報 `NO_USABLE_EVIDENCE`，提示目前不支援此教材，
不呼叫語意模型假裝成功。純掃描 PDF 不在目前支援範圍。

Gemma Semantic 使用 `google/gemma-4-31B-it-qat-w4a16-ct`，只接收文字 Evidence。
批次維持 1536 new input tokens 與 8192 output tokens；模型不可用或回應不完整時明確失敗。
`ocr_calls` 保留為現有 artifact 統計欄位，新處理結果固定為 0。

多來源的 Evidence 保留來源檔案、集合閱讀順序與來源內頁碼；normalized PDF 不合併。
現行 KnowledgeStructure v4 與公開 view v3 使用來源集合契約，DB 升級套用 0007–0014。
依本次需求不提供舊版單 PDF／單題相容讀取；舊資料保持原狀，需重新上傳與分析。
