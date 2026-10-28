# Studydy 一點就通

將個人教材整理成可回查來源的知識地圖，搭配觀念題組、錯題補強與持久學習紀錄。

**上傳教材 → 確認來源 → 分析與檢核 → 知識地圖 → 題組練習 → 錯題補強**

支援 PDF、DOC／DOCX、PPT／PPTX、UTF-8 TXT、Markdown，以及影音與 YouTube 語音來源。可追加來源，建立知識地圖、題組、概念卡、筆記與 Podcast 講稿，並使用有引用的文字／語音輸入問答。可用格式與大小以介面讀取的來源能力為準。

介面提供教材、概念、卡組與 Podcast 的分類搜尋，並保留學習目標、測驗紀錄及來源回查。知識地圖匯出概念大綱 Markdown；筆記與概念卡匯出依教材命名。

Podcast 目前生成講稿，完成後可閱讀分集內容及匯出 Markdown；不產生新音訊或教學影片。已保存的音訊／影片仍可讀取及播放，只有實際存在的媒體才提供相應匯出。

## 部署與使用

以 Docker Compose 提供 React 前端、FastAPI、PostgreSQL 與隔離轉檔。教材擷取使用 PyMuPDF 原生文字與 Tesseract 圖片文字；分析與出題呼叫已部署的 Gemma HTTP／HTTPS 服務。文字層直接採用，純文字圖片頁以 chi_tra+eng 辨識；公式／表格頁標示需對照原圖。

- [安裝與啟動](docs/getting-started.md)：主機需求、設定、服務管理與備份。預設入口 http://127.0.0.1:4176。
- [使用指南](docs/usage.md)：教材、地圖、練習與進度恢復。
- [測試](docs/testing.md)：不需模型的容器測試及隔離 API／瀏覽器回歸。

## 開發文件

| 主題 | 文件 |
| --- | --- |
| 模組、資料流與信任邊界 | [系統架構](docs/architecture.md) |
| 轉檔、Evidence、來源與版本 | [教材處理](docs/materials.md) |
| 題組、評分、補強與學習狀態 | [學習與評量](docs/learning.md) |
| 格式、模型品質與覆蓋範圍 | [限制](docs/limitations.md) |

原檔與持久資料保存在部署主機；AI 操作會傳送必要內容至設定的模型服務。模型結果須對照教材確認，程式測試不代表內容品質已全面驗收。

除另有標示外，Studydy 專案原創程式碼採 [MIT License](LICENSE) 授權。第三方元件、模型與介面素材可能適用不同條款，詳見 [第三方內容](THIRD_PARTY_CONTENT.md)。
