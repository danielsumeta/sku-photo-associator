from __future__ import annotations

import csv
import json
import re
from pathlib import Path

SKU_RE = re.compile(r"^[A-Z]{2,4}-\d{4,6}(-[A-Z0-9]{1,4})?$")
SKU_TOKEN_RE = re.compile(r"^[A-Z]{2,4}-\d{4,6}(-[A-Z0-9]{1,4})?$", re.IGNORECASE)


def validate_sku(sku: str) -> bool:
    return bool(SKU_RE.match(sku.strip()))


def _find_sku_column(fieldnames: list[str], override: str | None) -> str | None:
    if override:
        for fn in fieldnames:
            if fn.lower() == override.lower():
                return fn
        return None
    for fn in fieldnames:
        if fn.lower() == "sku":
            return fn
    return None


def load_table(path: str | Path, sku_column: str | None = None):
    p = Path(path)
    if p.suffix.lower() == ".json":
        data = json.loads(p.read_text())
        if isinstance(data, dict) and "rows" in data:
            rows = data["rows"]
            fieldnames = data.get("columns") or (list(rows[0].keys()) if rows else [])
        elif isinstance(data, list):
            rows = data
            fieldnames = list(rows[0].keys()) if rows else []
        else:
            raise ValueError("JSON table must be a list of rows or {columns, rows}")
        sku_col = _find_sku_column(fieldnames, sku_column)
        return rows, fieldnames, sku_col
    # CSV
    with p.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("CSV missing header")
        fieldnames = list(reader.fieldnames)
        rows = list(reader)
    sku_col = _find_sku_column(fieldnames, sku_column)
    return rows, fieldnames, sku_col
