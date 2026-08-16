from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _safe_sku_dir(sku: str) -> str:
    # SKU chars are A-Z, 0-9, '-'; safe for dir name but sanitize just in case
    return sku.strip().replace("/", "_").replace("\\", "_")
