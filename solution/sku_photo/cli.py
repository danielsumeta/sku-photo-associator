from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

from . import __version__
from .ocr import extract_text
from .table import load_table, validate_sku
from .sort import sort_associations

ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def _is_ocr_sidecar(txt_name: str, image_names: set[str]) -> bool:
    if not txt_name.lower().endswith(".txt"):
        return False
    base = txt_name[:-4]
    if base in image_names:
        return True
    txt_stem = Path(txt_name).stem
    for img in image_names:
        if Path(img).stem == txt_stem:
            return True
    return False


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_photos_fs(photos_arg: str | Path) -> tuple[list[Path], list[str], Path | None]:
    """Return (photo_files_sorted_by_name, skipped_basenames, extract_root_for_cleanup).

    For zip, extracts to out/_zip_extract (caller controls cleanup). For dir, no temp.
    """
    p = Path(photos_arg)
    if p.is_file() and p.suffix.lower() == ".zip":
        return [], [], None
    if p.is_dir():
        photos: list[Path] = []
        skipped: list[str] = []
        for q in sorted(p.iterdir(), key=lambda x: x.name):
            if q.is_file():
                if q.suffix.lower() in ALLOWED_EXTS:
                    photos.append(q)
                elif q.suffix.lower() != ".txt":
                    skipped.append(q.name)
        skipped.sort()
        return photos, skipped, None
    if p.is_file() and p.suffix.lower() in ALLOWED_EXTS:
        return [p], [], None
    return [], [], None


def _token_match(text: str, sku: str) -> bool:
    return bool(re.search(r"\b" + re.escape(sku) + r"\b", text, flags=re.IGNORECASE))


def cmd_init(args):
    table_path = Path(args.table)
    photos_path = Path(args.photos)
    out = Path(args.out)
    if not table_path.exists():
        print(f"table not found: {table_path}", file=sys.stderr)
        sys.exit(1)
    if not photos_path.exists():
        print(f"photos not found: {photos_path}", file=sys.stderr)
        sys.exit(1)
    try:
        rows, fieldnames, sku_col = load_table(table_path, sku_column=args.sku_column)
    except Exception as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    if sku_col is None:
        print("sku column not found", file=sys.stderr)
        sys.exit(1)

    # Build invalid_rows
    invalid_rows = []
    for idx, row in enumerate(rows):
        sku_val = (row.get(sku_col) or "").strip()
        if not sku_val or not validate_sku(sku_val):
            invalid_rows.append({"row_index": idx, "sku": sku_val, "reason": "invalid_sku_format"})

    # Count photos + skipped (for manifest stats)
    # For zip, count entries without extracting yet
    all_names = []
    if photos_path.is_file() and photos_path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(photos_path, "r") as z:
                for info in z.infolist():
                    if info.is_dir():
                        continue
                    all_names.append(Path(info.filename).name)
        except Exception as e:
            print(f"invalid zip: {e}", file=sys.stderr)
            sys.exit(1)
    elif photos_path.is_dir():
        all_names = [q.name for q in photos_path.iterdir() if q.is_file()]
    image_names = {n for n in all_names if Path(n).suffix.lower() in ALLOWED_EXTS}
    total_photos = len(image_names)
    skipped_files: list[str] = []
    for name in all_names:
        ext = Path(name).suffix.lower()
        if ext in ALLOWED_EXTS:
            continue
        if _is_ocr_sidecar(name, image_names):
            continue
        if name:
            skipped_files.append(name)
    if photos_path.is_file() and photos_path.suffix.lower() in ALLOWED_EXTS:
        total_photos = 1
        skipped_files = []

    skipped_files.sort()
    out.mkdir(parents=True, exist_ok=True)
    manifest = {
        "table": str(table_path.resolve()),
        "photos": str(photos_path.resolve()),
        "out": str(out.resolve()),
        "sku_column": sku_col,
        "total_rows": len(rows),
        "total_photos": total_photos,
        "invalid_rows": sorted(invalid_rows, key=lambda x: x["row_index"]),
        "skipped_files": sorted(skipped_files),
        "fieldnames": fieldnames,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"manifest": str(out / "manifest.json"), **{k: manifest[k] for k in ("total_rows", "total_photos")}}, indent=2))


def cmd_associate(args):
    out = Path(args.out)
    manifest_path = out / "manifest.json"
    if not manifest_path.exists():
        print("manifest not found; run init first", file=sys.stderr)
        sys.exit(1)
    manifest = json.loads(manifest_path.read_text())
    table_path = Path(manifest["table"])
    photos_arg = Path(manifest["photos"])
    sku_col = manifest["sku_column"]

    rows, _, _ = load_table(table_path, sku_column=sku_col)
    # Map sku -> list of row_index for valid rows only
    from collections import defaultdict
    sku_to_rows: dict[str, list[int]] = defaultdict(list)
    valid_row_indices: set[int] = set()
    for idx, row in enumerate(rows):
        sku_val = (row.get(sku_col) or "").strip()
        if sku_val and validate_sku(sku_val):
            # normalized key upper-case for matching, but preserve original row value
            sku_to_rows[sku_val.upper()].append(idx)
            valid_row_indices.add(idx)

    # Collect photo files (handle zip extraction to out/_zip_extract)
    zip_extract: Path | None = None
    photo_files: list[Path] = []
    skipped: list[str] = list(manifest.get("skipped_files", []))
    if photos_arg.is_file() and photos_arg.suffix.lower() == ".zip":
        zip_extract = out / "_zip_extract"
        if zip_extract.exists():
            shutil.rmtree(zip_extract)
        zip_extract.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(photos_arg, "r") as z:
            z.extractall(zip_extract)
        for q in sorted(zip_extract.rglob("*"), key=lambda x: x.name):
            if q.is_file() and q.suffix.lower() in ALLOWED_EXTS:
                photo_files.append(q)
            elif q.is_file() and q.suffix.lower() != ".txt" and q.parent == zip_extract:
                pass  # top-level skipped already from manifest; nested handled via rglob name
        photo_files.sort(key=lambda x: x.name)
    elif photos_arg.is_dir():
        for q in sorted(photos_arg.iterdir(), key=lambda x: x.name):
            if q.is_file() and q.suffix.lower() in ALLOWED_EXTS:
                photo_files.append(q)
    elif photos_arg.is_file():
        photo_files = [photos_arg]

    # Dedup by sha256 — keep first occurrence
    seen_sha: dict[str, Path] = {}
    duplicate_photos: list[dict] = []
    unique_files: list[Path] = []
    for pf in photo_files:
        try:
            sha = _sha256(pf)
        except Exception:
            continue
        if sha in seen_sha:
            duplicate_photos.append({"photo": pf.name, "duplicate_of": seen_sha[sha].name, "photo_sha256": sha})
        else:
            seen_sha[sha] = pf
            unique_files.append(pf)

    # For each unique file, OCR and match
    associations: list[dict] = []
    unassociated: list[dict] = []
    invalid_rows = manifest.get("invalid_rows", [])

    # Build list of distinct SKU strings (original case from first row)
    sku_display: dict[str, str] = {}
    for idx, row in enumerate(rows):
        if idx in valid_row_indices:
            sku_val = (row.get(sku_col) or "").strip()
            key = sku_val.upper()
            if key not in sku_display:
                sku_display[key] = sku_val

    for pf in unique_files:
        sha = _sha256(pf)
        text = extract_text(pf)
        # distinct SKU keys matched in this image
        matched_keys: list[str] = []
        for key in sku_display:
            if _token_match(text, key):
                matched_keys.append(key)
        # --strict: reject if 0 or >1 distinct SKU matched
        if args.strict and len(matched_keys) != 1:
            reason = "no_sku_in_image" if len(matched_keys) == 0 else "multiple_skus_in_image"
            unassociated.append({"photo": pf.name, "reason": reason})
            continue
        if len(matched_keys) == 0:
            unassociated.append({"photo": pf.name, "reason": "no_sku_in_image"})
            continue
        # Associate to ALL rows for each matched distinct SKU
        for key in sorted(matched_keys):
            display_sku = sku_display[key]
            for row_idx in sorted(sku_to_rows[key]):
                associations.append({
                    "sku": display_sku,
                    "row_index": row_idx,
                    "photo": pf.name,
                    "photo_sha256": sha,
                    "extracted_text": text.strip()[:2000],
                })

    # Stable sort by sku, photo, row_index for determinism
    associations.sort(key=lambda x: (x["sku"], x["photo"], x["row_index"]))
    unassociated.sort(key=lambda x: x["photo"])
    duplicate_photos.sort(key=lambda x: x["photo"])
    invalid_rows_sorted = sorted(invalid_rows, key=lambda x: x["row_index"])

    out.mkdir(parents=True, exist_ok=True)
    assoc_path = out / "associations.json"
    assoc_path.write_text(json.dumps({
        "associations": associations,
        "unassociated": unassociated,
        "invalid_rows": invalid_rows_sorted,
        "duplicate_photos": duplicate_photos,
        "skipped_files": sorted(skipped),
    }, indent=2, sort_keys=True) + "\n")

    # CSV: sku,row_index,photo,photo_sha256
    csv_path = out / "associations.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["sku", "row_index", "photo", "photo_sha256"])
        w.writeheader()
        for a in associations:
            w.writerow({k: a[k] for k in ["sku", "row_index", "photo", "photo_sha256"]})

    print(json.dumps({"associations": len(associations), "unassociated": len(unassociated), "duplicate_photos": len(duplicate_photos)}, indent=2))

    # Cleanup zip extract — tests assert no leftover cwd extraction; we keep _zip_extract for export
    # Do not delete here; export needs it. But ensure no cwd pollution.
    # Nothing to do.


def cmd_sort(args):
    out = Path(args.out)
    assoc_path = out / "associations.json"
    if not assoc_path.exists():
        print("associations.json not found; run associate first", file=sys.stderr)
        sys.exit(1)
    data = json.loads(assoc_path.read_text())
    assocs = data.get("associations", [])

    # Determine photos root for date sort
    manifest = {}
    try:
        manifest = json.loads((out / "manifest.json").read_text())
    except Exception:
        pass
    photos_root: Path | None = None
    if args.by == "date":
        photos_arg = manifest.get("photos")
        if photos_arg:
            p = Path(photos_arg)
            if p.is_dir():
                photos_root = p
            elif (out / "_zip_extract").exists():
                photos_root = out / "_zip_extract"
            else:
                photos_root = out

    sorted_assocs = sort_associations(assocs, by=args.by, order=args.order, photos_root=photos_root)
    data["associations"] = sorted_assocs
    # Deterministic write: already sorted, sort_keys=True
    assoc_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")
    csv_path = out / "associations.csv"
    import csv as _csv
    with csv_path.open("w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=["sku", "row_index", "photo", "photo_sha256"])
        w.writeheader()
        for a in sorted_assocs:
            w.writerow({k: a[k] for k in ["sku", "row_index", "photo", "photo_sha256"]})
    print(json.dumps({"sorted_by": args.by, "order": args.order, "count": len(sorted_assocs)}, indent=2))


def cmd_verify(args):
    out = Path(args.out)
    assoc_path = out / "associations.json"
    if not assoc_path.exists():
        print("associations.json not found", file=sys.stderr)
        sys.exit(1)
    data = json.loads(assoc_path.read_text())
    violations = []
    for a in data.get("associations", []):
        sku = a.get("sku", "")
        text = a.get("extracted_text", "")
        if not re.search(r"\b" + re.escape(sku) + r"\b", text or "", flags=re.IGNORECASE):
            violations.append({"sku": sku, "photo": a.get("photo"), "reason": "sku_not_in_extracted_text"})
    report = {"violations": violations, "violation_count": len(violations)}
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        if violations:
            print(f"FAIL: {len(violations)} violation(s)", file=sys.stderr)
            for v in violations:
                print(f"  {v['photo']}: sku {v['sku']} not in text", file=sys.stderr)
        else:
            print("OK: all associations valid")
    if violations:
        sys.exit(2)


def cmd_export(args):
    out = Path(args.out)
    assoc_path = out / "associations.json"
    manifest_path = out / "manifest.json"
    if not assoc_path.exists() or not manifest_path.exists():
        print("manifest or associations missing; run init+associate first", file=sys.stderr)
        sys.exit(1)
    data = json.loads(assoc_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    assocs = data.get("associations", [])
    unassociated = data.get("unassociated", [])
    invalid_rows = data.get("invalid_rows", manifest.get("invalid_rows", []))
    skipped_files = data.get("skipped_files", manifest.get("skipped_files", []))
    duplicate_photos = data.get("duplicate_photos", [])

    organized = Path(args.organized_dir) if args.organized_dir else out / "organized"
    # Clean and recreate organized (idempotent)
    if organized.exists():
        shutil.rmtree(organized)
    organized.mkdir(parents=True, exist_ok=True)

    # Resolve source photo location
    photos_arg = Path(manifest["photos"])
    zip_extract = out / "_zip_extract"
    # Map photo basename -> source path (unique files only)
    source_map: dict[str, Path] = {}
    if photos_arg.is_file() and photos_arg.suffix.lower() == ".zip" and zip_extract.exists():
        for q in zip_extract.rglob("*"):
            if q.is_file() and q.suffix.lower() in ALLOWED_EXTS:
                # keep first path for duplicate basenames (should be unique basenames in tests)
                if q.name not in source_map:
                    source_map[q.name] = q
    elif photos_arg.is_dir():
        for q in photos_arg.iterdir():
            if q.is_file() and q.suffix.lower() in ALLOWED_EXTS:
                source_map[q.name] = q
    elif photos_arg.is_file():
        source_map[photos_arg.name] = photos_arg

    # Deduplicate bytes: track sha already copied
    copied_sha: dict[str, Path] = {}
    for a in assocs:
        sku = a["sku"]
        photo = a["photo"]
        src = source_map.get(photo)
        if src is None or not src.exists():
            continue
        sha = a.get("photo_sha256") or _sha256(src)
        sku_dir = organized / sku
        sku_dir.mkdir(parents=True, exist_ok=True)
        dest = sku_dir / photo
        if sha in copied_sha:
            # dedup: hardlink or copy with -2 suffix already handled by unique_files, so this is duplicate-SKU rows sharing same file
            # For export we still want one file per SKU folder deduped: if same sha already copied to this SKU dir, skip
            if dest.exists():
                continue
            # Same content already copied somewhere else — hardlink if possible, else copy
            try:
                dest.hardlink_to(copied_sha[sha])
            except Exception:
                shutil.copy2(copied_sha[sha], dest)
        else:
            if not dest.exists():
                shutil.copy2(src, dest)
            copied_sha[sha] = dest

    # Also dedup within report counts: associated counts unique files, not row-expanded assocs
    # For report, per instruction: {total_rows, total_photos, associated, unassociated, invalid_rows, skipped_files, duplicate_photos}
    # associated = number of unique photos that were associated (not number of assoc rows)
    unique_associated_photos = len(set(a["photo"] for a in assocs))
    report = {
        "total_rows": manifest.get("total_rows", 0),
        "total_photos": manifest.get("total_photos", 0),
        "associated": unique_associated_photos,
        "unassociated": len(unassociated),
        "invalid_rows": len(invalid_rows),
        "skipped_files": len(skipped_files),
        "duplicate_photos": len(duplicate_photos),
    }
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))


def build_parser():
    p = argparse.ArgumentParser(prog="sku-photo")
    p.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("--table", required=True)
    s.add_argument("--photos", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--sku-column", default=None)

    s = sub.add_parser("associate")
    s.add_argument("--out", default="out")
    s.add_argument("--strict", action="store_true")

    s = sub.add_parser("sort")
    s.add_argument("--by", choices=["sku", "filename", "date"], default="sku")
    s.add_argument("--order", choices=["asc", "desc"], default="asc")
    s.add_argument("--out", default="out")

    s = sub.add_parser("verify")
    s.add_argument("--out", default="out")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("export")
    s.add_argument("--out", default="out")
    s.add_argument("--organized-dir", default=None)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd == "init":
        cmd_init(args)
    elif args.cmd == "associate":
        cmd_associate(args)
    elif args.cmd == "sort":
        cmd_sort(args)
    elif args.cmd == "verify":
        cmd_verify(args)
    elif args.cmd == "export":
        cmd_export(args)


if __name__ == "__main__":
    main()
