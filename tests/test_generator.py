import json

from receipt_ocr.generator import VARIANTS, generate


def test_generate_creates_one_image_per_receipt(corpus):
    records = corpus["records"]
    out_dir = corpus["dir"]
    assert len(records) == 16
    for rec in records:
        assert (out_dir / "images" / f"{rec.receipt_id}.png").exists()


def test_ground_truth_json_matches_records(corpus):
    out_dir = corpus["dir"]
    payload = json.loads((out_dir / "ground_truth.json").read_text())
    assert len(payload) == len(corpus["records"])
    by_id = {r["receipt_id"]: r for r in payload}
    for rec in corpus["records"]:
        entry = by_id[rec.receipt_id]
        assert entry["shop"] == rec.shop
        assert entry["date"] == rec.date
        assert entry["currency"] == rec.currency
        assert entry["total"] == rec.total
        assert abs(entry["items_sum"] - rec.total) < 1e-9  # total == sum of items, no tax modelled


def test_all_variants_are_exercised(corpus):
    seen = {rec.variant for rec in corpus["records"]}
    assert seen == set(VARIANTS)


def test_generation_is_deterministic(tmp_path):
    a = generate(tmp_path / "a", seed=99, count=6)
    b = generate(tmp_path / "b", seed=99, count=6)
    assert [r.receipt_id for r in a] == [r.receipt_id for r in b]
    assert [r.total for r in a] == [r.total for r in b]
    assert [r.items for r in a] == [r.items for r in b]
    img_a = (tmp_path / "a" / "images" / "r0001.png").read_bytes()
    img_b = (tmp_path / "b" / "images" / "r0001.png").read_bytes()
    assert img_a == img_b


def test_different_seed_changes_output(tmp_path):
    a = generate(tmp_path / "a", seed=1, count=6)
    c = generate(tmp_path / "c", seed=2, count=6)
    assert [r.total for r in a] != [r.total for r in c]
