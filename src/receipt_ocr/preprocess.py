"""Deterministic image preprocessing before OCR.

No randomness here: the same input image always produces the same
preprocessed image, so pipeline runs are reproducible.
"""

from __future__ import annotations

from PIL import Image, ImageFilter, ImageOps


def preprocess(img: Image.Image) -> Image.Image:
    gray = ImageOps.grayscale(img)
    gray = ImageOps.autocontrast(gray, cutoff=1)
    if max(gray.size) < 900:
        scale = 900 / max(gray.size)
        gray = gray.resize(
            (max(1, int(gray.width * scale)), max(1, int(gray.height * scale))),
            resample=Image.LANCZOS,
        )
    gray = gray.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=2))
    return gray.convert("RGB")
