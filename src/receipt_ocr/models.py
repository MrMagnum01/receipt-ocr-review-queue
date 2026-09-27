"""Shared dataclasses for ground truth, extraction results and review reasons."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class LineItem:
    name: str
    qty: int
    unit_price: float

    @property
    def amount(self) -> float:
        return round(self.qty * self.unit_price, 2)


@dataclass(frozen=True)
class ReceiptGroundTruth:
    """The true content of one synthetic receipt, recorded at generation time."""

    receipt_id: str
    shop: str
    date: str  # ISO YYYY-MM-DD
    items: tuple[LineItem, ...]
    total: float
    currency: str
    variant: str  # degradation applied: clean / rotated / blurred / noisy / low_contrast / crumpled

    @property
    def items_sum(self) -> float:
        return round(sum(i.amount for i in self.items), 2)


@dataclass
class FieldExtraction:
    """One extracted field with its confidence and, if rejected, why."""

    value: str | None
    confidence: float  # 0.0-1.0
    ok: bool
    reason: str | None = None  # populated when ok is False


@dataclass
class ExtractionResult:
    """Everything the pipeline produced for one receipt image."""

    receipt_id: str
    image_path: str
    shop: FieldExtraction
    date: FieldExtraction
    total: FieldExtraction
    currency: FieldExtraction
    items: list[LineItem] = field(default_factory=list)
    items_sum: float | None = None
    ocr_mean_word_conf: float = 0.0
    review_reasons: list[str] = field(default_factory=list)
    error: str | None = None  # set when OCR/preprocessing itself failed

    @property
    def needs_review(self) -> bool:
        return bool(self.review_reasons) or self.error is not None
