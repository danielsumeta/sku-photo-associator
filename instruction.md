# SKU Photo Associator — Whole Repo Generation Task

## Overview
Build a CLI tool `sku-photo` that ingests a tabular inventory and a directory/zip of photos, validates that each photo visibly contains its claimed SKU code, associates photos to the correct table rows, sorts the associations, and exports an organized result. Graded binary (pass/fail): the hidden suite must fully pass.

## Data Model

### Table
- Input table is CSV (or JSON) with header row. Must contain at least `sku` column (case-insensitive). `sku` format: `^[A-Z]{2,4}-\d{4,6}(-[A-Z0-9]{1,4})?$` (e.g., `AB-1234`, `SKU-001234-X1`).
- Other columns are opaque (preserve through to output). Rows without a valid `sku` must be reported as `invalid_rows` with reason `invalid_sku_format`.
- Duplicate SKUs in table: allowed; photos matching a duplicate SKU must associate to **all** matching rows.

### Photos
- Input is a directory or `.zip` containing `*.jpg, *.jpeg, *.png, *.webp` (case-insensitive). Ignore other files but report them in `skipped_files` (count of non-image files, excluding any image sidecars).
- SKU presence is determined by **OCR text extraction** from the image. Implement `extract_text(image_path) -> str` by calling `pytesseract.image_to_string` on the image (the environment provides `tesseract-ocr` with `eng` and DejaVu fonts). Hidden tests provide synthetic images with the SKU rendered as plain horizontal 24pt+ sans-serif black text on white background; your OCR must read these via real tesseract OCR (no sidecar `.txt` fallback). Matching is case-insensitive.
- A photo matches a row iff `sku` (case-insensitive) appears as a **whole token** in extracted text (`\bSKU\b`). SKU-like substrings that are part of longer tokens do NOT match.

## CLI Interface (required — tests invoke CLI only)

All commands exit `0` on success, `1` on user error (bad args, missing files), `2` on validation failure (no valid associations when at least one valid association was expected, or `verify` violations). Errors print to stderr; stdout is JSON or human table per `--json`.

```
sku-photo init --table <path.csv|json> --photos <dir|zip> --out <dir> [--sku-column NAME]
  # Validates inputs, creates <out>/manifest.json with stats. Idempotent (re-running with same inputs overwrites manifest).

sku-photo associate [--out <dir>] [--strict]
  # Reads <out>/manifest.json, runs OCR, creates associations.
  # --strict counts distinct SKU strings: reject (move to unassociated with reason `multiple_skus_in_image`) any photo whose OCR text contains >1 distinct valid SKU from the table, and reject with `no_sku_in_image` when it contains 0 distinct SKUs. A photo that contains one distinct SKU but matches multiple duplicate rows still associates (one distinct SKU, not >1). Default (no --strict): associate to all matching rows even if multiple distinct SKUs.
  # Writes <out>/associations.json and <out>/associations.csv

sku-photo sort [--by sku|filename|date] [--order asc|desc] [--out <dir>]
  # Stable sort of associations. Default --by sku --order asc. Date = EXIF DateTimeOriginal else mtime.

sku-photo verify [--out <dir>] [--json]
  # Verifies invariant: every associated photo contains its SKU token. Prints report; exit 2 if violations.

sku-photo export [--out <dir>] [--organized-dir <dir>]
  # Copies photos into <organized-dir>/<SKU>/filename (duplicate-SKU rows share same folder, dedup by content hash — same SHA256 → single file via hardlink/copy).
  # Generates <out>/report.json {total_rows, total_photos, associated, unassociated, invalid_rows, skipped_files, duplicate_photos}
```

Flags `--help` and `--version` required.

## Rules & Edge Cases (graded)

1. **SKU-in-image mandatory:** `associate` must reject (move to `unassociated` with reason `no_sku_in_image`) any photo where OCR text does not contain its target SKU. Do not rely on filename.
2. **Multi-match:** If a photo contains `AB-1234` and `CD-5678`, associate to both rows (or reject all with `multiple_skus_in_image` if `--strict`).
3. **Dedup:** Photos with identical SHA256 are duplicates — count once in `associated` but list all source paths in `duplicate_photos` (inside `associations.json` and counted in `report.json`). `export` must not duplicate bytes.
4. **Orphans & invalid:** Photos with no SKU match → `unassociated` (`no_sku_in_image`). Rows with no matching photo → listed but not an error. Rows with invalid SKU → `invalid_rows` (`invalid_sku_format`) and never matched.
5. **Idempotency:** Re-running `associate`/`sort`/`export` with same inputs produces byte-identical `associations.*` and `report.json` (stable sort, sorted keys, deterministic JSON with 2-space indent).
6. **Zip input:** Must handle zip without extracting to cwd (stream or tempdir cleanup — no leftover temp files).
7. **EXIF:** Use EXIF `DateTimeOriginal` when present for `--by date`; fallback to `mtime`. Missing EXIF must not crash.
8. **Large batch:** Must handle 100 photos / 50 rows within 30s on 2-core (hidden test perf gate; cache OCR by hash if needed).

## File Layout (expected)

```
sku-photo/
  pyproject.toml | setup.py  # console entry `sku-photo`
  sku_photo/
    __init__.py  # exposes __version__
    cli.py       # argparse / click entry
    ocr.py       # extract_text() via pytesseract
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
  "invalid_rows": [{"row_index": 3, "sku": "bad!", "reason": "invalid_sku_format"}],
  "duplicate_photos": [{"photo": "dup.jpg", "duplicate_of": "orig.jpg", "photo_sha256": "..."}],
  "skipped_files": ["readme.txt"]
}
```
Reasons are exactly `no_sku_in_image`, `multiple_skus_in_image` (only with --strict), `invalid_sku_format`. Additional keys `duplicate_photos` and `skipped_files` are required in `associations.json` (empty list when none).

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
Hidden suite tests CLI via subprocess: init → associate → sort → verify → export, including invalid SKU, duplicate photo, zip input, strict mode, idempotency, and perf smoke. All tests must pass (binary scoring).
