from __future__ import annotations

import json
from pathlib import Path


def _exif_date(path: Path):
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
        img = Image.open(str(path))
        exif = img.getexif()
        if not exif:
            return None
        # 306 = DateTime, 36867 = DateTimeOriginal, 36868 = DateTimeDigitized
        for tag_id in (36867, 36868, 306):
            v = exif.get(tag_id)
            if v:
                s = str(v)
                # "YYYY:MM:DD HH:MM:SS"
                try:
                    import datetime
                    dt = datetime.datetime.strptime(s, "%Y:%m:%d %H:%M:%S")
                    return dt
                except Exception:
                    continue
        return None
    except Exception:
        return None


def sort_associations(associations: list[dict], by: str, order: str, photos_root: Path | None = None) -> list[dict]:
    reverse = (order == "desc")
    if by == "sku":
        return sorted(associations, key=lambda x: (x.get("sku", ""), x.get("photo", ""), x.get("row_index", 0)), reverse=reverse)
    if by == "filename":
        return sorted(associations, key=lambda x: (x.get("photo", ""), x.get("sku", ""), x.get("row_index", 0)), reverse=reverse)
    if by == "date":
        def key_fn(item):
            if photos_root is not None:
                cand = photos_root / item.get("photo", "")
                if cand.exists():
                    dt = _exif_date(cand)
                    if dt is not None:
                        return (dt, item.get("photo", ""))
                    try:
                        return (cand.stat().st_mtime, item.get("photo", ""))
                    except Exception:
                        pass
            return (0, item.get("photo", ""))
        # date key is not directly sortable mixed types, so normalize
        def norm(item):
            k = key_fn(item)
            # if first element is datetime, convert to timestamp
            import datetime
            v = k[0]
            if isinstance(v, datetime.datetime):
                v = v.timestamp()
            return (v, k[1])
        return sorted(associations, key=norm, reverse=reverse)
    return associations
