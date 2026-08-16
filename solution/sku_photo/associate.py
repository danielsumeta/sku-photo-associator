from __future__ import annotations

import hashlib
import re
from pathlib import Path

from .ocr import extract_text
from .table import validate_sku

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _token_match(text: str, sku: str) -> bool:
    # whole-token, case-insensitive, \b on both sides
    # sku itself may contain '-' so \b still works at hyphens? Use a stricter:
    # require sku not preceded/followed by [A-Za-z0-9-] — but instruction says \bSKU\b.
    # So we follow that literally: \b<escaped sku>\b case-insensitive.
    return bool(re.search(r"\b" + re.escape(sku) + r"\b", text, flags=re.IGNORECASE))


def _collect_photos(photos_path: str | Path, out_dir: Path) -> tuple[list[Path], list[str]]:
    p = Path(photos_path)
    files: list[Path] = []
    skipped: list[str] = []
    if p.is_file() and p.suffix.lower() == ".zip":
        import tempfile
        import zipfile
        tmp = out_dir / "_zip_extract"
        # re-extract idempotently
        if tmp.exists():
            import shutil
            shutil.rmtree(tmp)
        tmp.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(p, "r") as z:
            z.extractall(tmp)
        for q in tmp.rglob("*"):
            if q.is_file():
                if q.suffix.lower() in ALLOWED_EXTS:
                    files.append(q)
                else:
                    # ignore sidecar .txt
                    if q.suffix.lower() != ".txt":
                        skipped.append(q.name)
        files.sort(key=lambda x: x.name)
        skipped.sort()
        return files, skipped
    # directory
    if p.is_dir():
        for q in sorted(p.iterdir(), key=lambda x: x.name):
            if q.is_file():
                if q.suffix.lower() in ALLOWED_EXTS:
                    files.append(q)
                else:
                    if q.suffix.lower() != ".txt":
                        skipped.append(q.name)
        return files, skipped
    # single file image
    if p.is_file() and p.suffix.lower() in ALLOWED_EXTS:
        return [p], []
    return [], []


def _load_rows(table_path: str | Path, sku_column: str | None):
    from .table import load_table
    rows, fieldnames, sku_col = load_table(table_path, sku_column=sku_column)
    return rows, fieldnames, sku_col
