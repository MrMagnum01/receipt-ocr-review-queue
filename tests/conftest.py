import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from receipt_ocr.generator import generate  # noqa: E402


@pytest.fixture(scope="session")
def corpus(tmp_path_factory):
    """A small deterministic corpus generated once and reused read-only by
    every test that needs real images."""
    out_dir = tmp_path_factory.mktemp("corpus")
    records = generate(out_dir, seed=42, count=16)
    return {"dir": out_dir, "records": records}
