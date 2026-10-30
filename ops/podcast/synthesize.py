"""Podcast 與問答語音：XTTS-v2 官方雙聲線、中文讀音前處理及正式版音訊修正。

XTTS-v2 權重為 Coqui Public Model License（非商用），只供競賽展示。
"""

import json
import logging
import os
from pathlib import Path
import re
import sys
import types

# host 名字庫為女聲、guest 為男聲（見 backend podcasts.HOST_PAIRS）；皆為官方 speakers_xtts.pth 內建聲線。
SPEAKERS = {"host": "Ana Florence", "guest": "Andrew Chipper"}
RATE = 24000
_ENGLISH = re.compile(r"[A-Za-z]+(?:[\s,\-]+[A-Za-z]+)*")
# 單獨出現的公式字母改用中文近似名稱，整句維持中文模式，不在字母前後切換語言。
_LETTERS = {"Q": "丘", "K": "開", "V": "維", "eps": "伊普西龍", "w": "達布溜", "x": "艾克斯", "y": "歪", "L": "艾爾"}
_LETTER = re.compile(r"(?<![A-Za-z0-9_])(" + "|".join(_LETTERS) + r")(?![A-Za-z0-9_])")


def prepare(text):
    """講稿文字 → 句子與語言片段；原講稿不改，只產生朗讀輸入。"""
    from unicode_rbnf import RbnfEngine
    from spoken_input import mixed_sentences

    zh_numbers = RbnfEngine.for_language("zh_Hant")
    en_numbers = RbnfEngine.for_language("en")

    def zh(part):
        part = re.sub(r"(\d+(?:\.\d+)?)\s*[%％]", r"百分之\1", part)
        return re.sub(
            r"[-−]?\d+(?:\.\d+)?",
            lambda m: zh_numbers.format_number(m[0].replace("−", "-")).text,
            part,
        )

    text = re.sub(r"(?<![A-Za-z0-9_])(?:y_hat|ŷ)(?![A-Za-z0-9_])", "歪的預測值", text)
    text = re.sub(r"(?<![A-Za-z0-9_])d([A-Za-z])/d([A-Za-z])(?![A-Za-z0-9_])", r"\1 對 \2 的導數", text)
    text = _LETTER.sub(lambda m: _LETTERS[m[1]], text)
    spoken = "".join(
        item["text"] for item in mixed_sentences(text, zh, lambda s: en_numbers.format_number(s).text)
    )
    sentences = []
    # 合併列舉／逗號片語，只在完整句界或超過 70 個漢字的長句逗號切開，減少接縫。
    for sentence in re.findall(r"[^。！？!?]+[。！？!?]?", spoken):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(re.findall(r"[㐀-鿿]", sentence)) <= 70:
            sentences.append(sentence)
            continue
        buffer = ""
        for clause in re.findall(r"[^，]+，?", sentence):
            if buffer and len(re.findall(r"[㐀-鿿]", buffer + clause)) > 70:
                sentences.append(buffer)
                buffer = ""
            buffer += clause
        if buffer:
            sentences.append(buffer)
    result = []
    for sentence in sentences:
        parts, start = [], 0
        for match in _ENGLISH.finditer(sentence):
            parts.append(("zh", start, match.start()))
            parts.append(("en", match.start(), match.end()))
            start = match.end()
        parts.append(("zh", start, len(sentence)))
        kept = []
        for language, begin, end in parts:
            if re.search(r"[A-Za-z㐀-鿿]", sentence[begin:end]):
                kept.append({"language": language, "start": begin, "end": end})
            elif kept:
                # 純標點併入前一片段，不單獨合成。
                kept[-1]["end"] = end
        if kept:
            kept[0]["start"] = 0
            result.append({"text": sentence, "parts": kept})
    return result


def render(body, output):
    segments = body.get("script", {}).get("segments")
    if not isinstance(segments, list) or not 1 <= len(segments) <= 12:
        raise ValueError("REQUEST_INVALID")
    turns = []
    for segment_index, segment in enumerate(segments):
        group = segment.get("turns")
        if not isinstance(group, list) or not 1 <= len(group) <= 12:
            raise ValueError("REQUEST_INVALID")
        for turn in group:
            if (
                not isinstance(turn, dict)
                or turn.get("speaker") not in SPEAKERS
                or not isinstance(turn.get("text"), str)
                or not 1 <= len(turn["text"].strip()) <= 1600
            ):
                raise ValueError("REQUEST_INVALID")
            turns.append({**turn, "segment_index": segment_index})

    # 模型的逐句 log 可能含教材，語音程序不輸出內容。
    logging.disable(logging.CRITICAL)
    # 原廠 tokenizer 匯入的中文數字正規化來自中國來源專案；中文改由 zh_readings 提供拼音，不載入該模組。
    sys.modules["TTS.tts.layers.xtts.zh_num2words"] = types.SimpleNamespace(TextNorm=None)
    import numpy as np
    import soundfile as sf
    import torch
    from ckip_transformers.nlp import CkipWordSegmenter
    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.tts.layers.xtts.tokenizer import VoiceBpeTokenizer
    from TTS.tts.models.xtts import Xtts
    from audio_mastering import master, trim_edges
    from dialogue_audio_repair import assemble, spoken_units
    from zh_readings import readings, to_model_text

    planned = [(turn, sentence) for turn in turns for sentence in prepare(turn["text"])]
    if not planned:
        raise RuntimeError("PODCAST_AUDIO_INVALID")
    torch.set_num_threads(4)
    segmenter = CkipWordSegmenter(
        model_name=os.environ["STUDYDY_XTTS_CKIP_MODEL_DIR"],
        tokenizer_name=os.environ["STUDYDY_XTTS_CKIP_TOKENIZER_DIR"],
        device=0,
    )
    words = segmenter([s["text"] for _, s in planned], use_delim=True, batch_size=8, show_progress=False)
    del segmenter
    original = VoiceBpeTokenizer.preprocess_text
    # 中文片段已是數字聲調拼音；其他語言沿用原廠前處理。
    VoiceBpeTokenizer.preprocess_text = lambda self, text, lang: (
        text if lang == "zh" else original(self, text, lang)
    )
    model_dir = Path(os.environ["STUDYDY_XTTS_MODEL_DIR"])
    config = XttsConfig()
    config.load_json(str(model_dir / "config.json"))
    model = Xtts.init_from_config(config)
    model.load_checkpoint(config, checkpoint_dir=str(model_dir), eval=True)
    model.cuda()
    items, total = [], 0
    for (turn, sentence), sentence_words in zip(planned, words):
        phones = readings(sentence["text"], sentence_words)
        for index, part in enumerate(sentence["parts"]):
            text = sentence["text"][part["start"] : part["end"]].strip()
            model_text = (
                to_model_text(sentence["text"][part["start"] : part["end"]], phones[part["start"] : part["end"]]).strip()
                if part["language"] == "zh"
                # 英文模式看不懂全形標點，句尾殘留時可能多念一段無關內容。
                else text.translate(str.maketrans("。，！？；：", ".,!?;:"))
            )
            torch.manual_seed(1030)
            with torch.inference_mode():
                result = model.synthesize(
                    model_text,
                    language="zh-cn" if part["language"] == "zh" else "en",
                    speaker=SPEAKERS[turn["speaker"]],
                    speed=1.0,
                    enable_text_splitting=False,
                )
            data = np.asarray(result["wav"], dtype=np.float32)
            total += data.size
            if data.size < 2400 or not np.isfinite(data).all() or total > RATE * 1800:
                raise RuntimeError("PODCAST_AUDIO_INVALID")
            if part["language"] == "en":
                # 短英文片段常在結尾多生成無關語音；以 CMU 音節估計上限，在上限前最安靜處截斷。
                units, unknown = spoken_units(text)
                limit = round(RATE * (0.5 + 0.4 * (units + 2 * len(unknown))))
                trimmed = trim_edges(data)
                if len(trimmed) > limit:
                    frame = RATE // 50
                    start = int(limit * 0.6) // frame * frame
                    energy = [float(np.mean(trimmed[i : i + frame] ** 2)) for i in range(start, limit - frame + 1, frame)]
                    data = trimmed[: start + frame * int(np.argmin(energy)) + frame // 2]
            last = index == len(sentence["parts"]) - 1
            items.append({
                "audio": trim_edges(data),
                "text": text,
                "source_text": sentence["text"],
                "ending": sentence["text"][-1] if last else None,
                "language_join": not last,
                "speaker": turn["speaker"],
                "beat": turn["segment_index"],
            })
    combined = assemble(items, RATE)
    if combined.size > RATE * 1800:
        raise RuntimeError("PODCAST_AUDIO_INVALID")
    raw = Path(output).with_suffix(".float.wav")
    sf.write(raw, combined, RATE, format="WAV", subtype="FLOAT")
    metadata = master(raw, output)
    Path(output).with_suffix(".json").write_text(json.dumps(metadata))
    raw.unlink()


if __name__ == "__main__":
    render(json.load(sys.stdin), sys.argv[1])
