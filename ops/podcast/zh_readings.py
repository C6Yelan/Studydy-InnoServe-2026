"""XTTS 中文讀音：CKIP 斷詞＋CC-CEDICT 詞彙讀音，不使用 pypinyin／jieba。

多音字依序取：詞典唯一讀音 → 第二輪人工核對的語境讀音 → CC-CEDICT 標示的台灣讀音
→ Unihan kMandarin 的台灣慣用讀音。這是自動規則，不是逐稿人工核對；個別語境仍可能念錯。
"""

import gzip
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import unicodedata
import zipfile

HAN = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_HAN_RUN = re.compile(r"[㐀-䶿一-鿿豈-﫿]+")
_TONE_MARKS = {"̄": "1", "́": "2", "̌": "3", "̀": "4"}


def _numbered(syllable):
    """Unihan 的聲調符號拼音轉成 CC-CEDICT 的數字聲調（ü 寫成 u:）。"""
    decomposed = unicodedata.normalize("NFD", syllable.lower())
    tone = next((_TONE_MARKS[c] for c in decomposed if c in _TONE_MARKS), "5")
    base = "".join(c for c in decomposed if c not in _TONE_MARKS)
    return unicodedata.normalize("NFC", base).replace("ü", "u:").replace("ü", "u:") + tone


@lru_cache(maxsize=1)
def dictionary():
    entries = {}
    with gzip.open(os.environ["STUDYDY_XTTS_CEDICT"], "rt", encoding="utf-8") as source:
        for line in source:
            found = re.fullmatch(r"(\S+) \S+ \[([^]]+)\] /(.*)/\n?", line)
            if not found:
                continue
            word, pinyin, gloss = found.groups()
            readings = entries.setdefault(word, {"all": [], "taiwan": []})
            readings["all"].append(pinyin.lower())
            for alternate in re.finditer(r"Taiwan pr\.\s*\[([^]]+)\]", gloss):
                syllables = re.findall(r"[a-zA-Zü:]+[1-5]", alternate[1])
                if len(syllables) == len(word):
                    readings["taiwan"].append(" ".join(syllables).lower())
    return entries


@lru_cache(maxsize=1)
def unihan():
    readings = {}
    with zipfile.ZipFile(os.environ["STUDYDY_XTTS_UNIHAN"]) as archive:
        for line in archive.read("Unihan_Readings.txt").decode().splitlines():
            if "\tkMandarin\t" in line:
                code, _, values = line.split("\t")
                # 兩個值時第二個是台灣慣用讀音。
                readings[chr(int(code[2:], 16))] = _numbered(values.split()[-1])
    return readings


@lru_cache(maxsize=1)
def reviewed():
    return json.loads(Path(__file__).with_name("zh-reviewed-readings.json").read_text())["readings"]


def _default(char):
    if char in reviewed():
        return reviewed()[char]
    candidates = dictionary().get(char, {}).get("all", [])
    preferred = unihan().get(char)
    if preferred in candidates or (preferred and not candidates):
        return preferred
    if candidates:
        return candidates[0]
    raise ValueError("PODCAST_AUDIO_INVALID")


def _word(word):
    if word in reviewed():
        return reviewed()[word].split()
    entry = dictionary()[word]
    candidates = list(dict.fromkeys(entry["all"]))
    if len(candidates) == 1:
        return candidates[0].split()
    if len(word) == 1:
        return [_default(word)]
    if entry["taiwan"]:
        return entry["taiwan"][0].split()
    defaults = [_default(c) for c in word]
    return max(candidates, key=lambda r: sum(a == b for a, b in zip(r.split(), defaults))).split()


def readings(text, words):
    """依斷詞結果回傳每個漢字的讀音；非漢字為 None。"""
    if "".join(words) != text:
        raise ValueError("PODCAST_AUDIO_INVALID")
    result = []
    for word in words:
        cursor = 0
        for run in _HAN_RUN.finditer(word):
            result.extend([None] * (run.start() - cursor))
            remaining = run[0]
            while remaining:
                size = next(
                    (n for n in range(len(remaining), 0, -1) if remaining[:n] in dictionary() or remaining[:n] in reviewed()),
                    1,
                )
                piece = remaining[:size]
                spoken = _word(piece) if piece in dictionary() or piece in reviewed() else [_default(piece)]
                if len(spoken) != len(piece):
                    spoken = [_default(c) for c in piece]
                result.extend(spoken)
                remaining = remaining[size:]
            cursor = run.end()
        result.extend([None] * (len(word) - cursor))
    return result


def to_model_text(text, phones):
    """XTTS 中文模式的輸入：漢字換成數字聲調拼音，其他字元原樣保留。"""
    return "".join(
        p.replace("u:", "v").replace("ü", "v") if p else c for c, p in zip(text, phones)
    )
