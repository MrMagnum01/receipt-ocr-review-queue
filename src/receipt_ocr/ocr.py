"""pytesseract wrapper: turns an image into lines of words with per-word
confidence.

Tesseract's own block/paragraph/line numbering treats a left name column
and a far-right price column (typical receipt layout) as separate text
blocks read in block order, not top-to-bottom -- which would silently
scramble every item line. Lines here are instead reconstructed directly
from each word's vertical position (top + height), clustering words whose
vertical bands overlap into one visual row and ordering them left to
right. This is the layout reconstruction step, independent of whatever
column/block grouping Tesseract's page-segmentation happened to pick.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytesseract
from PIL import Image


@dataclass
class OcrLine:
    text: str
    words: list[tuple[str, int]] = field(default_factory=list)  # (word, conf 0-100)

    @property
    def mean_conf(self) -> float:
        confs = [c for _, c in self.words if c >= 0]
        return (sum(confs) / len(confs)) if confs else 0.0


@dataclass
class OcrResult:
    lines: list[OcrLine]
    full_text: str
    mean_word_conf: float  # 0-100, across every recognised word


def run_ocr(img: Image.Image) -> OcrResult:
    data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)

    words = []  # (top, bottom, left, text, conf)
    all_confs: list[int] = []
    n = len(data["text"])
    for i in range(n):
        text = data["text"][i].strip()
        if not text:
            continue
        try:
            conf = int(float(data["conf"][i]))
        except (ValueError, TypeError):
            conf = -1
        top = data["top"][i]
        height = max(1, data["height"][i])
        left = data["left"][i]
        words.append((top, top + height, left, text, conf))
        if conf >= 0:
            all_confs.append(conf)

    # cluster into visual rows by vertical overlap, top to bottom
    words.sort(key=lambda w: (w[0], w[2]))
    rows: list[list[tuple[int, int, int, str, int]]] = []
    for w in words:
        top, bottom, _left, _text, _conf = w
        placed = False
        for row in rows:
            row_top = min(r[0] for r in row)
            row_bottom = max(r[1] for r in row)
            overlap = min(bottom, row_bottom) - max(top, row_top)
            band = min(bottom - top, row_bottom - row_top)
            if band > 0 and overlap > 0.5 * band:
                row.append(w)
                placed = True
                break
        if not placed:
            rows.append([w])

    # rows were appended in first-word-seen order (already ~top-to-bottom
    # since `words` was sorted by top); sort each row left-to-right.
    lines: list[OcrLine] = []
    for row in rows:
        row.sort(key=lambda r: r[2])
        line = OcrLine(text=" ".join(r[3] for r in row), words=[(r[3], r[4]) for r in row])
        lines.append(line)

    full_text = "\n".join(line.text for line in lines)
    mean_word_conf = (sum(all_confs) / len(all_confs)) if all_confs else 0.0
    return OcrResult(lines=lines, full_text=full_text, mean_word_conf=mean_word_conf)
