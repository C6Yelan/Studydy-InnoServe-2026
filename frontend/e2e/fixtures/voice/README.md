# 人聲分類回歸音訊

`speech.wav` 使用 LibriSpeech `test-other` 樣本 `1688-142285-0007`，由 [PyTorch TorchAudio 教學](https://docs.pytorch.org/audio/2.5.0/tutorials/asr_inference_with_ctc_decoder_tutorial.html)提供。[原始 WAV](https://download.pytorch.org/torchaudio/tutorial-assets/ctc-decoding/1688-142285-0007.wav)取前 4 秒，重取樣為 24 kHz、單聲道 PCM16。

[LibriSpeech](https://www.openslr.org/12) 由 Vassil Panayotov 製作、Daniel Povey 協助，來源為 LibriVox 有聲書，採 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 授權。此音訊仍適用該授權。

瀏覽器測試以此音訊產生小聲與混合噪音樣本，實際執行本站提供的 Silero VAD／ONNX Runtime。此回歸只驗證固定公開樣本，不代表實體麥克風、所有口音與環境的辨識率。
