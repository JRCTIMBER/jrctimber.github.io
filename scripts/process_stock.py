"""Tidy up stock after every change made in Pages CMS.

Runs in GitHub Actions (.github/workflows/site.yml):
  1. Applies the "Sold or reserved a piece" button from Pages CMS, if that's what started the run.
  2. Gives every new piece the next stock number (JRC-025, JRC-026, ...).
  3. Shrinks new photos, removes their location data and makes a small thumbnail for the shop.
  4. Writes stock.json, which the shop page reads.
  5. Writes ebay.csv and ebay.html for pieces that can go on eBay (see ebay_export.py).
"""
import json
import os
import re
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ebay_export  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STOCK = ROOT / "_stock"
PHOTOS = ROOT / "img" / "stock"
THUMBS = PHOTOS / "thumbs"
COUNTER = ROOT / ".stock-counter"
FEED = ROOT / "stock.json"
FEED_FIELDS = ["ref", "name", "wood", "length", "width", "width_min", "thickness",
               "dried", "finish", "price", "was", "status", "note", "photos"]
FULL_SIZE = 1600
THUMB_SIZE = 640


def read_entry(path):
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def write_entry(path, data, body):
    front = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    path.write_text(f"---\n{front}\n---\n{body}", encoding="utf-8")


def ref_number(ref):
    m = re.search(r"(\d+)", str(ref or ""))
    return int(m.group(1)) if m else None


def photo_file(p):
    """'/img/stock/x.jpg' or 'img/stock/x.jpg' -> path in the repo."""
    return ROOT / str(p).lstrip("/")


def load_all():
    entries = []
    for path in sorted(STOCK.glob("*.md")):
        data, body = read_entry(path)
        entries.append([path, data, body])
    return entries


def apply_cms_button(entries):
    raw = os.environ.get("PAYLOAD", "").strip()
    if not raw:
        return
    payload = json.loads(raw)
    inputs = payload.get("inputs") or {}
    wanted = ref_number(inputs.get("stock"))
    what = str(inputs.get("what") or "Sold")
    if wanted is None:
        sys.exit(f"Couldn't read a stock number from {inputs.get('stock')!r}")
    for entry in entries:
        path, data, body = entry
        if ref_number(data.get("ref")) == wanted:
            if what.lower().startswith("remove"):
                for p in data.get("photos") or []:
                    f = photo_file(p)
                    for x in (f, THUMBS / (f.stem + ".jpg")):
                        if x.exists():
                            x.unlink()
                path.unlink()
                entries.remove(entry)
                print(f"Removed {data.get('ref')} ({data.get('name')}) from the site")
            else:
                status = "Available" if "available" in what.lower() else what
                data["status"] = status
                write_entry(path, data, body)
                print(f"Marked {data.get('ref')} ({data.get('name')}) as {status}")
            return
    sys.exit(f"No piece with stock number JRC-{wanted:03d} was found")


def assign_numbers(entries):
    used = [ref_number(d.get("ref")) for _, d, _ in entries]
    last = max([n for n in used if n] + [int(COUNTER.read_text().strip() or 0) if COUNTER.exists() else 0])
    for entry in entries:  # sorted by filename, which starts with the date and time it was added
        path, data, body = entry
        if not data.get("ref"):
            last += 1
            data["ref"] = f"JRC-{last:03d}"
            data.setdefault("status", "Available")
            # keep the stock number near the top of the file
            data = {"ref": data["ref"], **{k: v for k, v in data.items() if k != "ref"}}
            entry[1] = data
            write_entry(path, data, body)
            print(f"New piece {data['ref']}: {data.get('name')}")
    COUNTER.write_text(f"{last}\n")


def process_photos(entries):
    THUMBS.mkdir(parents=True, exist_ok=True)
    for path, data, body in entries:
        photos = data.get("photos") or []
        changed = False
        for i, p in enumerate(photos):
            src = photo_file(p)
            if not src.exists():
                continue
            thumb = THUMBS / (src.stem + ".jpg")
            if thumb.exists() and src.suffix.lower() == ".jpg":
                continue
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                full = im.copy()
                full.thumbnail((FULL_SIZE, FULL_SIZE), Image.LANCZOS)
                out = src.with_suffix(".jpg")
                # saved without EXIF, so phone location data is removed
                full.save(out, "JPEG", quality=80, optimize=True, progressive=True)
                small = im.copy()
                small.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.LANCZOS)
                small.save(thumb, "JPEG", quality=75, optimize=True, progressive=True)
            if out != src:
                src.unlink()
                photos[i] = "/" + str(out.relative_to(ROOT)).replace(os.sep, "/")
                changed = True
            print(f"Photo ready: {out.name}")
        if changed:
            data["photos"] = photos
            write_entry(path, data, body)


def write_feed(entries):
    items = []
    for _, data, _ in entries:
        if not data.get("name"):
            continue
        item = {k: data.get(k) for k in FEED_FIELDS}
        item["photos"] = [str(x) for x in (item["photos"] or [])]
        items.append(item)
    items.sort(key=lambda d: ref_number(d["ref"]) or 0)
    FEED.write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"stock.json: {len(items)} pieces")


def main():
    entries = load_all()
    apply_cms_button(entries)
    assign_numbers(entries)
    process_photos(entries)
    write_feed(entries)
    ebay_export.build(entries)


if __name__ == "__main__":
    main()
