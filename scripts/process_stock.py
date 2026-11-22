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
import shop_extras  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STOCK = ROOT / "_stock"
PHOTOS = ROOT / "img" / "stock"
THUMBS = PHOTOS / "thumbs"
COUNTER = ROOT / ".stock-counter"
FEED = ROOT / "stock.json"
INDEX = ROOT / ".stock-index.json"  # which file owns each stock number
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


def put_first(data, key):
    return {key: data[key], **{k: v for k, v in data.items() if k != key}}


def assign_numbers(entries):
    """Tidy typed-in tag numbers, catch numbers used twice, and number pieces left blank."""
    index = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    # 1. "25", "jrc25", "JRC-25" -> "JRC-025"
    for entry in entries:
        path, data, body = entry
        n = ref_number(data.get("ref"))
        if data.get("ref") not in (None, "") and n is None:
            data["problem"] = f"Couldn't read the stock number {data.get('ref')!r}. Type just the number from the tag, e.g. 25."
            write_entry(path, data, body)
            continue
        if n is not None and data.get("ref") != f"JRC-{n:03d}":
            data["ref"] = f"JRC-{n:03d}"
            entry[1] = data = put_first(data, "ref")
            write_entry(path, data, body)
    # 2. Same number on two pieces: the one that already had it keeps it, the other is flagged
    groups = {}
    for entry in entries:
        n = ref_number(entry[1].get("ref"))
        if n is not None:
            groups.setdefault(n, []).append(entry)
    flagged = set()
    for n, group in groups.items():
        if len(group) < 2:
            continue
        owner = next((e for e in group if index.get(e[1]["ref"]) == e[0].name), group[0])
        for e in group:
            if e is not owner:
                flagged.add(id(e))
                e[1]["problem"] = (f"Stock number {e[1]['ref']} is already used by \"{owner[1].get('name')}\". "
                                   "Check the tag and type the right number, then save.")
                write_entry(*e)
                print(f"Problem: {e[1]['ref']} used twice ({e[1].get('name')})")
    # 3. Clear old problems that are now fixed
    for entry in entries:
        path, data, body = entry
        bad_ref = data.get("ref") not in (None, "") and ref_number(data.get("ref")) is None
        if data.get("problem") and id(entry) not in flagged and not bad_ref:
            data.pop("problem")
            write_entry(path, data, body)
    # 4. Blank numbers get the next one after the highest number ever used
    used = [ref_number(d.get("ref")) for _, d, _ in entries]
    last = max([n for n in used if n is not None] + [int(COUNTER.read_text().strip() or 0) if COUNTER.exists() else 0])
    for entry in entries:  # sorted by filename, which starts with the date and time it was added
        path, data, body = entry
        if data.get("ref") in (None, ""):
            last += 1
            data["ref"] = f"JRC-{last:03d}"
            data.setdefault("status", "Available")
            entry[1] = data = put_first(data, "ref")
            write_entry(path, data, body)
            print(f"New piece {data['ref']}: {data.get('name')}")
        elif not data.get("problem"):
            data.setdefault("status", "Available")
    COUNTER.write_text(f"{last}\n")
    INDEX.write_text(json.dumps({d["ref"]: p.name for p, d, _ in entries if d.get("ref") and not d.get("problem")},
                                indent=1, sort_keys=True) + "\n")


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


def write_feed(entries, links=None):
    links = links or {}
    items = []
    for _, data, _ in entries:
        if not data.get("name") or data.get("problem"):
            continue
        item = {k: data.get(k) for k in FEED_FIELDS}
        item["photos"] = [str(x) for x in (item["photos"] or [])]
        item["url"] = shop_extras.page_path(data["ref"])
        item["buy"] = shop_extras.buy_url(data, links)
        items.append(item)
    items.sort(key=lambda d: ref_number(d["ref"]) or 0)
    FEED.write_text(json.dumps(items, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"stock.json: {len(items)} pieces")


def main():
    entries = load_all()
    apply_cms_button(entries)
    assign_numbers(entries)
    process_photos(entries)
    settings = ebay_export.load_settings()
    links = shop_extras.square_sync(entries, settings, write_entry)
    write_feed(entries, links)
    shop_extras.piece_pages(entries, links, settings)
    shop_extras.google_feed(entries, links, settings)
    shop_extras.delivery_page(settings)
    ebay_export.build(entries)


if __name__ == "__main__":
    main()
