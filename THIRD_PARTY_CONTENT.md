# 素材與第三方內容

## 介面素材

角色與插圖為 AI 生成素材，位於 [角色素材](frontend/public/assets/Studydy_角色素材/) 與 [介面素材](frontend/public/assets/studydy/)。生成工具、適用條款及對外使用授權仍待維護者確認。

## 介面音效

答題、升級、取得徽章、完成關卡與按鈕點擊的提示音，由瀏覽器 Web Audio API 即時合成（[feedback-sound.ts](frontend/src/ui/feedback-sound.ts)）；音效為程式合成，無第三方素材，也沒有音檔。

## 測試文件

[合成文件](backend/tests/fixtures/README.md) 由專案自行建立，用於轉檔、內容保留與來源定位測試。

## 沙箱設定

[Bubblewrap seccomp 設定](ops/docker/bubblewrap-seccomp.json) 改自 [Moby profiles](https://github.com/moby/profiles/blob/65adc7e022c97f55e45c054ff012988027733b87/seccomp/default.json)，增加沙箱所需的 namespace 操作。原作採 Apache License 2.0，授權文字保留於 [MOBY-LICENSE](ops/docker/MOBY-LICENSE)。

## 套件、模型與專案授權

依賴版本見 [Python lock](backend/uv.lock)、[npm lock](frontend/package-lock.json)；模型設定見 [runtime lock](local_ai/runtime-lock.json)。各套件與模型適用其發行者條款。

Studydy 原創程式碼除另有標示外採 [MIT License](LICENSE) 授權。第三方元件、模型與介面素材仍依各自適用條款，不因專案採 MIT License 而改變其原授權狀態。

## 概念卡圖示與詞彙

[Tabler Icons 3.49.0](https://github.com/tabler/tabler-icons) 幾何資料採 MIT，完整文字在 [Tabler 授權](frontend/public/licenses/tabler-icons.txt)。
[CC-CEDICT / MDBG](https://www.mdbg.net/chinese/dictionary?page=cc-cedict) 衍生的中文詞表及別名採 CC BY-SA 4.0；不將其改稱 MIT。[署名與修改說明](frontend/public/licenses/concept-icons.txt) 隨網站發佈，SVG 下載也保留署名連結。

圖庫在概念卡開啟時載入，全程本機詞彙與語境比對，不增加模型推論。版本、來源 hash 及生成方式見 [圖庫維護](ops/icons/README.md)。

競賽版的 [圖示目錄](frontend/src/features/concept-cards/icons/catalog.json) 與 [幾何資料](frontend/src/features/concept-cards/icons/shapes.json) 獨立保留，語音測試採用下列 LibriSpeech 素材；介面更新不替換這些來源與授權紀錄。

## 瀏覽器人聲辨識

語音模式使用 [vad-web 0.0.31](https://github.com/ricky0123/vad)（ISC）、[Silero VAD v6](https://github.com/snakers4/silero-vad)（MIT）與 [ONNX Runtime Web 1.30.0](https://github.com/microsoft/onnxruntime)（MIT）。模型、worklet 與 WASM 從鎖定 npm 套件建置，隨本站發布；[完整授權文字](frontend/public/voice-assets/LICENSES.txt) 同時提供給網站使用者。人聲分類在瀏覽器執行，通過判定的錄音才交給既有 Studydy 語音問答服務。

## 語音測試素材

瀏覽器人聲分類測試使用 [LibriSpeech](https://www.openslr.org/12) 的 `test-other/1688-142285-0007`。資料集由 Vassil Panayotov 製作、Daniel Povey 協助，採 CC BY 4.0；使用範圍、來源與轉檔方式見[素材說明](frontend/e2e/fixtures/voice/README.md)。

## 模型與語音執行套件

| 項目 | 版本／來源 | 授權 |
| --- | --- | --- |
| Google DeepMind Gemma 4 | [`google/gemma-4-31B-it-qat-w4a16-ct`](https://huggingface.co/google/gemma-4-31B-it-qat-w4a16-ct/blob/52f3f65bc7a02d555763bc923bd1d9094898219d/README.md)，revision `52f3f65bc7a02d555763bc923bd1d9094898219d`，與 runtime lock 一致 | [Apache License 2.0](https://ai.google.dev/gemma/apache_2) |
| OpenAI Whisper | [`large-v3-turbo`](https://huggingface.co/openai/whisper-large-v3-turbo)，語音辨識模型 | [MIT](https://github.com/openai/whisper#license) |
| SYSTRAN faster-whisper | [`v1.2.1`](https://github.com/SYSTRAN/faster-whisper/tree/v1.2.1)，以 CTranslate2 執行 Whisper | [MIT](https://raw.githubusercontent.com/SYSTRAN/faster-whisper/v1.2.1/LICENSE) |

語音服務由 `STUDYDY_STT_MODEL_DIR` 載入本機轉換後權重。套件的 `large-v3-turbo` 別名對應 [`mobiuslabsgmbh/faster-whisper-large-v3-turbo`](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo)；實際部署須記錄本機目錄的來源與 revision，不能由套件版本推定權重身分。

## Tesseract OCR

圖片文字辨識使用 Tesseract（Apache-2.0），繁體中文 chi_tra 與英文 eng 語言資料隨 Ubuntu 套件安裝。來源：https://github.com/tesseract-ocr/tesseract 、https://github.com/tesseract-ocr/tessdata 。系統套件版本由 Docker 的 Ubuntu snapshot 固定。
