# 教材擷取

Studydy InnoServe 使用文字優先、圖片輔助的單一 Evidence 流程。

1. PyMuPDF 建立文件雜湊、頁碼、原生文字、圖片範圍與 200 DPI RGB 渲染。
2. 可靠原生文字直接成為 `source=native_text` Evidence。小型裝飾圖片不觸發 Vision。
3. 缺漏的實質圖片區域交給 Gemma Vision 純轉錄。沒有可靠文字層時轉錄整頁。
   裁切圖上覆蓋到的可靠 native 文字會遮除，避免模型重新產生並取代它。
4. 轉錄成為 `source=vision` Evidence。locator 使用實際 PDF 裁切範圍，不是模型猜測的字元座標。
5. Canonical Evidence 交給另一個 Gemma Semantic request 建立 Concept／Claim／Relation，再由程式檢查與建立 Map／Path。
   語意階段會收到 Evidence 的來源，native_text 優先；Vision 階段不生成 Concept／Claim／Relation。

Vision 與 Semantic 共用 `google/gemma-4-31B-it-qat-w4a16-ct`，但 prompt 與 request 各自分開。
Vision 使用 temperature 1.0、top_p 0.95、top_k 64、8192 output tokens、關閉 thinking、image-first，
逐請求指定 `mm_processor_kwargs.max_soft_tokens=1120`。實際 image token 數依裁切比例取整。

Vision 是 best-effort transcription，不是逐字無損 OCR。包含 Vision Evidence 的地圖保持
`needs_review`，並帶有 `VISION_DERIVED_EVIDENCE`。每份 Evidence 保留原頁與區域，可開啟原 PDF 回查。
圖解的箭頭／空間關係不因文字轉錄成功就視為已被理解；無法辨識的文字不得合理化補寫。

Vision 服務不可用、輸出截斷或回應格式錯誤會明確失敗；沒有其他 OCR/model fallback。
Semantic 輸出截斷時，只拆分該批 Evidence 後依序重試，不重新辨識圖片；單筆 Evidence
仍截斷則整份處理失敗，不發布未完成地圖。詳見[語意批次處理](architecture.md)。
`ocr_calls` 是沿用的公開統計欄位，代表本次圖片區域轉錄請求次數，一頁可以有多次請求。

現有 JSON 儲存欄位保存來源與 runtime binding，無須新增資料表或 migration。
