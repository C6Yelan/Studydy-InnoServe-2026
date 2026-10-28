"""圖片頁的文字抽取與公式／表格分流；視覺候選未驗收前保留原圖。"""
import csv
import io
import os
from pathlib import Path
import re
import statistics
import subprocess
import tempfile

import pymupdf


def tesseract_words(page, cancellation_check):
    with tempfile.TemporaryDirectory(prefix="studydy-image-text-") as directory:
        directory = Path(directory)
        image = directory / "page.png"
        image.write_bytes(page["png_bytes"])
        target = directory / "words"
        try:
            with subprocess.Popen(
                ["tesseract", str(image), str(target), "-l", "chi_tra+eng", "--psm", "3", "tsv"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env={**os.environ, "OMP_THREAD_LIMIT": "1"},
            ) as process:
                try:
                    for _ in range(1200):
                        cancellation_check()
                        try:
                            code = process.wait(timeout=0.1)
                            break
                        except subprocess.TimeoutExpired:
                            continue
                    else:
                        raise ValueError("OCR_TIMEOUT")
                except BaseException:
                    process.terminate()
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
                    raise
            if code != 0:
                raise ValueError("OCR_UNAVAILABLE")
            raw = target.with_suffix(".tsv").read_text(encoding="utf-8")
        except OSError:
            raise ValueError("OCR_UNAVAILABLE") from None
    return parse_words(raw, page["render"]["width"], page["render"]["height"])


def parse_words(raw, width, height):
    words = []
    try:
        for row in csv.DictReader(io.StringIO(raw), delimiter="\t", quoting=csv.QUOTE_NONE):
            if row["level"] != "5" or not row["text"].strip():
                continue
            left, top, w, h = (int(row[key]) for key in ("left", "top", "width", "height"))
            if not (0 <= left < left + w <= width and 0 <= top < top + h <= height):
                raise ValueError
            words.append({"text": row["text"], "bbox": [left, top, left + w, top + h],
                "line": tuple(int(row[key]) for key in ("block_num", "par_num", "line_num"))})
    except (KeyError, TypeError, ValueError):
        raise ValueError("OCR_OUTPUT_INVALID") from None
    return words


def visual_reason(page, words):
    text = " ".join(word["text"] for word in words)
    if re.search(r"[=<>≤≥≠≈±×÷∑∫√∞∂∇^_]|[α-ωΑ-Ω]|\\(?:frac|sqrt|sum)|\d\s*[+*/−-]\s*\d", text):
        return "formula"
    # 表格線在二值圖中形成長水平／垂直線；文字的短筆畫不算格線。
    pixmap = pymupdf.Pixmap(pymupdf.csGRAY, pymupdf.Pixmap(page["png_bytes"]))
    dark = pixmap.samples.translate(bytes(int(value < 100) for value in range(256)))
    horizontal = [y for y in range(pixmap.height)
                  if dark[y * pixmap.width:(y + 1) * pixmap.width].count(b"\1") > pixmap.width * 0.35]
    vertical = [x for x in range(pixmap.width)
                if dark[x::pixmap.width].count(b"\1") > pixmap.height * 0.15]
    def groups(values):
        return sum(i == 0 or value - values[i - 1] > 3 for i, value in enumerate(values))
    if groups(horizontal) >= 2 and groups(vertical) >= 2:
        return "table"
    # 無框線表格：至少兩列在相同欄位間留有明顯空白。
    lines = {}
    for word in words:
        lines.setdefault(word["line"], []).append(word)
    gaps = []
    for line in lines.values():
        line.sort(key=lambda word: word["bbox"][0])
        size = statistics.median(word["bbox"][3] - word["bbox"][1] for word in line)
        for left, right in zip(line, line[1:]):
            if right["bbox"][0] - left["bbox"][2] > size * 2:
                gaps.append((left["bbox"][2], right["bbox"][0], line[0]["line"]))
    if any(a[2] != b[2] and min(a[1], b[1]) - max(a[0], b[0]) > 10
           for i, a in enumerate(gaps) for b in gaps[i + 1:]):
        return "table"
    return None


def image_blocks(page, cancellation_check, *, visual_reader=None):
    """visual_reader 接已驗收的區塊辨識器；預設不送出視覺模型請求。"""
    words = tesseract_words(page, cancellation_check)
    reason = visual_reason(page, words)
    if reason:
        if visual_reader is None:
            raise ValueError("OCR_VISUAL_REVIEW_REQUIRED")
        # 接入器收到原圖及原來源定位，回傳 PDF 未旋轉座標的 type/text/bbox 區塊。
        return visual_reader(page, reason, cancellation_check), "visual_ocr", "gemma_visual"
    if not words:
        raise ValueError("NO_USABLE_EVIDENCE")
    lines = {}
    for word in words:
        lines.setdefault(word["line"], []).append(word)
    visible = page["geometry"]["visible_points"]
    matrix = pymupdf.Matrix(*page["geometry"]["derotation_matrix"])
    blocks = []
    for line in lines.values():
        box = [min(word["bbox"][0] for word in line), min(word["bbox"][1] for word in line),
               max(word["bbox"][2] for word in line), max(word["bbox"][3] for word in line)]
        region = pymupdf.Rect(box[0] * (visible[2] - visible[0]) / page["render"]["width"],
            box[1] * (visible[3] - visible[1]) / page["render"]["height"],
            box[2] * (visible[2] - visible[0]) / page["render"]["width"],
            box[3] * (visible[3] - visible[1]) / page["render"]["height"]) * matrix
        text = re.sub(r"(?<=[\u3400-\u9fff]) (?=[\u3400-\u9fff])", "", " ".join(word["text"] for word in line))
        blocks.append({"type": "text", "text": text, "bbox": list(region)})
    return blocks, "tesseract_text", "tesseract"
