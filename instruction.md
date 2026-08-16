# SKU Photo Associator — Whole Repo Generation Task

## Overview
Build a CLI tool `sku-photo` that ingests a tabular inventory and a directory/zip of photos, validates that each photo visibly contains its claimed SKU code, associates photos to the correct table rows, sorts the associations, and exports an organized result. Graded on hidden test pass rate (not binary).

## Data Model

### Table
- Input table is CSV (or JSON) with header row. Must contain at least `sku` column (case-insensitive). `sku` format: `^[A-Z]{2,4}-\d{4,6}(-[A-Z0-9]{1,4})?$` (e.g., `AB-1234`, `SKU-001234-X1`).
- Other columns are opaque (preserve through to output). Rows without a valid `sku` must be reported as `invalid_rows`.
- Duplicate SKUs in table: allowed; photos matching a duplicate SKU must associate to **all** matching rows.

### Photos
- Input is a directory or `.zip` containing `*.jpg, *.jpeg, *.png, *.webp` (case-insensitive). Ignore other files but report them in `skipped_files`.
- SKU presence is determined by **OCR text extraction** from the image. For this task, implement `extract_text(image_path) -> str` (wrap `pytesseract` or equivalent; hidden tests provide synthetic images with SKU rendered as plain text — your OCR need only handle clear, horizontal, 24pt+ sans-serif text on white background, but must be case-insensitive).
- A photo matches a row iff `sku` (case-insensitive) appears as a **whole token** in extracted text (`\bSKU\b`). SKU-like substrings that are part of longer tokens do NOT match.

## CLI Interface (required — tests invoke CLI only)

All commands exit `0` on success, `1` on user error (bad args, missing files), `2` on validation failure (no valid associations). Errors print to stderr; stdout is JSON or human table per `--json`.

```
sku-photo init --table <path.csv|json> --photos <dir|zip> --out <dir> [--sku-column NAME]
  # Validates inputs, creates <out>/manifest.json with stats. Idempotent (re-running with same inputs overwrites manifest).

sku-photo associate [--out <dir>] [--strict]
  # Reads <out>/manifest.json, runs OCR, creates associations.
  # --strict: reject (not just warn) photos with 0 or >1 SKU matches. Default: warn, associate to all matches.
  # Writes <out>/associations.json and <out>/associations.csv

sku-photo sort [--by sku|filename|date] [--order asc|desc] [--out <dir>]
  # Stable sort of associations. Default --by sku --order asc. Date = EXIF DateTimeOriginal else mtime.

sku-photo verify [--out <dir>] [--json]
  # Verifies invariant: every associated photo contains its SKU token. Prints report; exit 2 if violations.

sku-photo export [--out <dir>] [--organized-dir <dir>]
  # Copies photos into <organized-dir>/<SKU>/filename (duplicate-SKU rows share same folder, dedup by content hash — same SHA256 → single file + symlink/hardlink or duplicate with -2 suffix).
  # Generates <out>/report.json {total_rows, total_photos, associated, unassociated, invalid_rows, skipped_files, duplicate_photos}
```

Flags `--help` and `--version` required.

## Rules & Edge Cases (graded)

1. **SKU-in-image mandatory:** `associate` must reject (move to `unassociated`) any photo where OCR text does not contain its target SKU. Do not rely on filename.
2. **Multi-match:** If a photo contains `AB-1234` and `CD-5678`, associate to both rows (or reject if `--strict`).
3. **Dedup:** Photos with identical SHA256 are duplicates — count once in `associated` but list all source paths in `duplicate_photos`. `export` must not duplicate bytes.
4. **Orphans & invalid:** Photos with no SKU match → `unassociated`. Rows with no matching photo → listed but not an error. Rows with invalid SKU → `invalid_rows` and never matched.
5. **Idempotency:** Re-running `associate`/`sort`/`export` with same inputs produces byte-identical `associations.*` and `report.json` (stable sort, sorted keys, deterministic JSON with 2-space indent).
6. **Zip input:** Must handle zip without extracting to cwd (stream or tempdir cleanup — no leftover temp files).
7. **EXIF:** Use EXIF `DateTimeOriginal` when present for `--by date`; fallback to `mtime`. Missing EXIF must not crash.
8. **Large batch:** Must handle 1000 photos / 500 rows within 30s on 2-core (hidden test perf gate — avoid O(n*m) naive OCR re-reads; cache).

## File Layout (expected)

```
sku-photo/
  pyproject.toml | setup.py  # console entry `sku-photo`
  sku_photo/
    __init__.py  # exposes __version__
    cli.py       # argparse / click entry
    ocr.py       # extract_text()
    table.py     # load_table(), validate_sku()
    associate.py # association logic
    sort.py
    export.py
    models.py    # dataclasses
  tests/         # your own tests (not graded)
  README.md
```

Do not require network at runtime; `pytesseract` + `Pillow` + system `tesseract` is allowed (declare in Dockerfile/requirements).

## Output Schemas (exact — hidden tests parse these)

`associations.json`:
```json
{
  "associations": [{"sku": "AB-1234", "row_index": 0, "photo": "IMG_001.jpg", "photo_sha256": "...", "extracted_text": "..."}],
  "unassociated": [{"photo": "no_sku.jpg", "reason": "no_sku_in_image"}],
  "invalid_rows": [{"row_index": 3, "sku": "bad!", "reason": "invalid_sku_format"}]
}
```

`associations.csv`: header `sku,row_index,photo,photo_sha256`

`report.json`: see `export` above; all counts are ints.

Example `report.json`:
```json
{
  "total_rows": 10,
  "total_photos": 12,
  "associated": 8,
  "unassociated": 2,
  "invalid_rows": 1,
  "skipped_files": 2,
  "duplicate_photos": 1
}
```

## Examples

```bash
sku-photo init --table inventory.csv --photos ./uploads --out ./out
sku-photo associate --out ./out
sku-photo sort --by sku --order asc --out ./out
sku-photo verify --out ./out --json
sku-photo export --out ./out --organized-dir ./out/organized
```

`inventory.csv`:
```
sku,name,qty
AB-1234,Widget A,10
CD-5678,Gadget B,5
```

Uploads: `widget_a.jpg` (contains "AB-1234"), `random.jpg` (contains no SKU) → `report.json` has `associated=1, unassociated=1`.

## Non-Goals
No GUI, no server, no cloud OCR, no auth. Single-node CLI only.

## Evaluation
Hidden suite tests CLI via subprocess: init → associate → sort → verify → export, including invalid SKU, duplicate photo, zip input, strict mode, idempotency, and 1k-photo perf. Each test counts equally toward pass rate.
