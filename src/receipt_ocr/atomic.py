"""Atomic file publish: readers never observe a half-written file.

Every output file this project writes (ground truth, accepted.csv,
review_queue.csv, manifest.json, the evaluation report) is written to a
temp file in the same directory and then moved into place with
`os.replace`, which is atomic on the same filesystem. A crash or a
concurrent read during generation either sees the old complete file or the
new complete file, never a partial one.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable


def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise


def atomic_write_bytes_via(path: str | Path, writer: Callable[[str], None]) -> None:
    """For libraries (e.g. Pillow's Image.save) that only write to a path
    themselves: call `writer(tmp_path)` and atomically publish the result."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    os.close(fd)
    try:
        writer(tmp_name)
        os.replace(tmp_name, path)
    except BaseException:
        if os.path.exists(tmp_name):
            os.remove(tmp_name)
        raise
