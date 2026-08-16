from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Association:
    sku: str
    row_index: int
    photo: str
    photo_sha256: str
    extracted_text: str


@dataclass
class Unassociated:
    photo: str
    reason: str


@dataclass
class InvalidRow:
    row_index: int
    sku: str
    reason: str


@dataclass
class Manifest:
    table_path: str
    photos_path: str
    out_dir: str
    sku_column: str | None
    total_rows: int
    invalid_rows: list[dict] = field(default_factory=list)
    skipped_files: list[str] = field(default_factory=list)
