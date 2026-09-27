"""Renders synthetic receipt images from fictional shop layouts, with a
deterministic seed and realistic scan degradation, and records ground
truth alongside each image.

All shops, products, addresses and receipts here are invented for this
demo. No real business, client or employer data is used.
"""

from __future__ import annotations

import json
import random
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .atomic import atomic_write_bytes_via, atomic_write_text
from .models import LineItem, ReceiptGroundTruth
from .shops import SHOP_LAYOUTS, ShopLayout

VARIANTS: tuple[str, ...] = (
    "clean",
    "rotated",
    "blurred",
    "noisy",
    "low_contrast",
    "crumpled",
)

_SHOP_DATE_FORMAT = {
    "corner_grocery": "%Y-%m-%d",
    "riverside_cafe": "%d/%m/%Y",
    "brightmart": "%d-%m-%Y",
    "luna_bookshop": "%d %b %Y",
}

_FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")
_FONTS = {
    "mono": _FONT_DIR / "DejaVuSansMono.ttf",
    "mono_bold": _FONT_DIR / "DejaVuSansMono-Bold.ttf",
    "sans": _FONT_DIR / "DejaVuSans.ttf",
    "sans_bold": _FONT_DIR / "DejaVuSans-Bold.ttf",
}


def _font(style: str, bold: bool, size: int) -> ImageFont.FreeTypeFont:
    key = f"{style}_bold" if bold else style
    path = _FONTS.get(key, _FONTS["sans"])
    return ImageFont.truetype(str(path), size)


def _base_date(rng: random.Random) -> date:
    start = date(2025, 1, 1)
    return start + timedelta(days=rng.randrange(0, 700))


def _pick_items(shop: ShopLayout, rng: random.Random) -> tuple[LineItem, ...]:
    n = rng.randint(2, 6)
    chosen = rng.sample(shop.catalog, k=min(n, len(shop.catalog)))
    items = []
    for name, price in chosen:
        qty = rng.randint(1, 3)
        items.append(LineItem(name=name, qty=qty, unit_price=price))
    return tuple(items)


def _render_clean(shop: ShopLayout, gt: ReceiptGroundTruth, date_display: str, rng: random.Random) -> Image.Image:
    line_h = 26
    header_h = 130
    footer_h = 90
    height = header_h + len(gt.items) * line_h + 70 + footer_h
    img = Image.new("RGB", (shop.width_px, height), "white")
    draw = ImageDraw.Draw(img)

    title_font = _font(shop.font_style, True, 20)
    body_font = _font(shop.font_style, False, 15)
    small_font = _font(shop.font_style, False, 13)

    y = 14
    if shop.align == "center":
        w = draw.textlength(shop.name, font=title_font)
        draw.text(((shop.width_px - w) / 2, y), shop.name, font=title_font, fill="black")
    else:
        draw.text((16, y), shop.name, font=title_font, fill="black")
    y += 28
    draw.text((16, y), shop.address, font=small_font, fill="black")
    y += 20
    draw.text((16, y), f"Date: {date_display}", font=small_font, fill="black")
    y += 18
    draw.text((16, y), f"Receipt #{gt.receipt_id}", font=small_font, fill="black")
    y += 24
    draw.line((16, y, shop.width_px - 16, y), fill="black", width=1)
    y += 10

    for item in gt.items:
        left = f"{item.name} x{item.qty}"
        right = f"{item.amount:.2f}"
        draw.text((16, y), left, font=body_font, fill="black")
        rw = draw.textlength(right, font=body_font)
        draw.text((shop.width_px - 16 - rw, y), right, font=body_font, fill="black")
        y += line_h

    y += 8
    draw.line((16, y, shop.width_px - 16, y), fill="black", width=1)
    y += 12
    total_label = f"TOTAL {gt.currency}"
    total_val = f"{shop.symbol} {gt.total:.2f}"
    draw.text((16, y), total_label, font=_font(shop.font_style, True, 16), fill="black")
    rw = draw.textlength(total_val, font=_font(shop.font_style, True, 16))
    draw.text((shop.width_px - 16 - rw, y), total_val, font=_font(shop.font_style, True, 16), fill="black")
    y += 34

    draw.text((16, y), shop.footer, font=small_font, fill="black")

    return img


def _degrade(img: Image.Image, variant: str, rng: random.Random) -> Image.Image:
    if variant == "clean":
        return img
    if variant == "rotated":
        angle = rng.uniform(-5, 5)
        return img.rotate(angle, expand=True, fillcolor="white", resample=Image.BICUBIC)
    if variant == "blurred":
        return img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(1.4, 2.4)))
    if variant == "noisy":
        noise = Image.effect_noise(img.size, rng.uniform(28, 42)).convert("RGB")
        return Image.blend(img, noise, alpha=0.18)
    if variant == "low_contrast":
        flattened = ImageEnhance.Contrast(img).enhance(0.35)
        return ImageEnhance.Brightness(flattened).enhance(1.12)
    if variant == "crumpled":
        w, h = img.size
        jitter = lambda mag: rng.randint(-mag, mag)  # noqa: E731
        mag = max(6, int(min(w, h) * 0.03))
        quad = (
            0 + jitter(mag), 0 + jitter(mag),
            0 + jitter(mag), h - jitter(mag),
            w - jitter(mag), h - jitter(mag),
            w - jitter(mag), 0 + jitter(mag),
        )
        warped = img.transform((w, h), Image.QUAD, quad, fillcolor="white", resample=Image.BICUBIC)
        noise = Image.effect_noise((w, h), rng.uniform(18, 26)).convert("RGB")
        warped = Image.blend(warped, noise, alpha=0.10)
        # partial: crop off a random slice of the bottom, hiding some content
        cut = rng.uniform(0.08, 0.22)
        keep_h = int(h * (1 - cut))
        cropped = Image.new("RGB", (w, h), "white")
        cropped.paste(warped.crop((0, 0, w, keep_h)), (0, 0))
        return cropped
    raise ValueError(f"unknown variant: {variant}")


def _date_display(iso_date: str, shop_key: str) -> str:
    d = date.fromisoformat(iso_date)
    return d.strftime(_SHOP_DATE_FORMAT[shop_key])


def generate(out_dir: str | Path, seed: int, count: int) -> list[ReceiptGroundTruth]:
    """Generate `count` synthetic receipts deterministically from `seed`.

    Writes images to <out_dir>/images/<receipt_id>.png and the full ground
    truth to <out_dir>/ground_truth.json (published atomically). Returns the
    list of ReceiptGroundTruth records generated, in receipt_id order.
    """
    out_dir = Path(out_dir)
    images_dir = out_dir / "images"
    rng = random.Random(seed)

    records: list[ReceiptGroundTruth] = []
    for i in range(count):
        shop = SHOP_LAYOUTS[i % len(SHOP_LAYOUTS)]
        variant = VARIANTS[i % len(VARIANTS)]
        d = _base_date(rng)
        items = _pick_items(shop, rng)
        total = round(sum(it.amount for it in items), 2)
        receipt_id = f"r{i + 1:04d}"

        gt = ReceiptGroundTruth(
            receipt_id=receipt_id,
            shop=shop.name,
            date=d.isoformat(),
            items=items,
            total=total,
            currency=shop.currency,
            variant=variant,
        )
        date_display = _date_display(gt.date, shop.key)

        clean_img = _render_clean(shop, gt, date_display, rng)
        final_img = _degrade(clean_img, variant, rng)

        image_path = images_dir / f"{receipt_id}.png"
        atomic_write_bytes_via(image_path, lambda tmp, im=final_img: im.save(tmp, format="PNG"))

        records.append(gt)

    payload = []
    for gt in records:
        d = asdict(gt)
        d["items"] = [asdict(it) for it in gt.items]
        d["items_sum"] = gt.items_sum
        d["image_path"] = str((images_dir / f"{gt.receipt_id}.png").relative_to(out_dir))
        payload.append(d)

    atomic_write_text(out_dir / "ground_truth.json", json.dumps(payload, indent=2, sort_keys=True))
    return records
