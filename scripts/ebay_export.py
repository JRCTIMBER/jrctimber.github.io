"""Build the eBay upload file (ebay.csv) and a simple page that explains it (ebay.html).

A piece goes in the file when it is:
  - Available (not reserved or sold),
  - not ticked "Listed on eBay" in Pages CMS,
  - has a length, a width and at least one photo.

Postage is set by size, using postage policies saved in the eBay account:
  - up to 80cm long and 40cm wide   -> small_policy  (£5)
  - up to 1.2m long and 50cm wide   -> medium_policy (£10)
  - anything longer or wider        -> collection_policy (collection only)
Settings live in _data/ebay.yml (editable in Pages CMS).
"""
import csv
import html
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path(__file__).resolve().parent / "ebay_template.csv"
SETTINGS = ROOT / "_data" / "ebay.yml"
OUT_CSV = ROOT / "ebay.csv"
OUT_PAGE = ROOT / "ebay.html"

CATEGORY = "180970"  # Home, Furniture & DIY > DIY Materials > Timber & Composites > Timber
SOFTWOODS = {"Redwood", "Cedar", "Yew", "Pine", "Fir", "Spruce", "Larch", "Douglas fir"}
PALE = {"Maple", "Ash", "Sycamore", "Hornbeam", "Poplar", "Beech", "Birch"}
EXTRA_COLUMNS = ["ShippingProfileName", "PostalCode"]


DEFAULTS = {
    "site_url": "https://jrctimber.co.uk", "location": "Great Wigborough, Colchester", "postcode": "CO5 7RP",
    "dispatch_days": 3, "small_max_length_m": 0.8, "small_max_width_mm": 400, "small_policy": "JRC £5 postage",
    "medium_max_length_m": 1.2, "medium_max_width_mm": 500, "medium_policy": "JRC £10 postage",
    "collection_policy": "JRC collection only",
}


def load_settings():
    s = yaml.safe_load(SETTINGS.read_text(encoding="utf-8")) or {}
    return {**DEFAULTS, **{k: v for k, v in s.items() if v not in (None, "")}}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt(n):
    """2.0 -> '2', 2.45 -> '2.45'"""
    return f"{n:g}"


def why_not(d, s):
    """Reason a piece can't go on eBay yet, or None if it can."""
    length, width = num(d.get("length")), num(d.get("width"))
    if str(d.get("status") or "Available").lower() != "available":
        return None  # not shown at all
    if d.get("ebay"):
        return None  # already listed
    if length is None:
        return "needs a length"
    if width is None:
        return "needs a width"
    if not d.get("photos"):
        return "needs at least one photo"
    return ""


def postage(d, s):
    length, width = num(d["length"]), num(d["width"])
    if length <= float(s["small_max_length_m"]) and width <= float(s["small_max_width_mm"]):
        return s["small_policy"], "£5 postage"
    if length <= float(s["medium_max_length_m"]) and width <= float(s["medium_max_width_mm"]):
        return s["medium_policy"], "£10 postage"
    return s["collection_policy"], "Collection only"


def describe(d, policy_label, s):
    length, width, wmin, thick = (num(d.get(k)) for k in ("length", "width", "width_min", "thickness"))
    rows = [("Stock number", d["ref"]), ("Wood", d["wood"]), ("Length", f"{fmt(length * 100)}cm ({fmt(length)}m)")]
    rows.append(("Width", f"{fmt(wmin / 10)}–{fmt(width / 10)}cm" if wmin else f"{fmt(width / 10)}cm"))
    if thick:
        rows.append(("Thickness", f"{fmt(thick)}mm"))
    if d.get("dried"):
        rows.append(("Drying", d["dried"]))
    if d.get("finish"):
        rows.append(("Finish", d["finish"]))
    rows.append(("Delivery", policy_label + (" from Great Wigborough, Colchester" if policy_label == "Collection only" else "")))
    table = "".join(f"<tr><td><b>{html.escape(k)}</b></td><td>{html.escape(str(v))}</td></tr>" for k, v in rows)
    note = f"<p>{html.escape(d['note'])}</p>" if d.get("note") else ""
    return (
        f"<h2>{html.escape(d['name'])}</h2>{note}<table>{table}</table>"
        "<p>Cut from a local Essex tree and milled by JRC Timber near Colchester. Every piece is one of a kind, "
        "and the photos show the actual piece you'll receive.</p>"
        "<p>We can also flatten, plane or cut pieces to size. Collection is welcome by appointment. "
        f"Please quote stock number {html.escape(d['ref'])} if you message us.</p>"
    )


def title(d):
    length, width, wmin, thick = (num(d.get(k)) for k in ("length", "width", "width_min", "thickness"))
    form = "Board" if re.search(r"board|plank", d["name"], re.I) else "Slab"
    size = f"{fmt(length * 100)} x {fmt(wmin / 10)}-{fmt(width / 10)}cm" if wmin else f"{fmt(length * 100)} x {fmt(width / 10)}cm"
    if thick:
        size += f" x {fmt(thick)}mm"
    bits = ["Live Edge", d["wood"], form, size]
    if d.get("dried") in ("Air dried", "Kiln dried"):
        bits.append(d["dried"].title())
    t = " ".join(bits) + f" {d['ref']}"
    return t if len(t) <= 80 else (" ".join(bits[:4]) + f" {d['ref']}")[:80]


def row(d, header, s):
    length, width, thick = num(d["length"]), num(d["width"]), num(d.get("thickness"))
    policy, policy_label = postage(d, s)
    features = ["Waney Edge"] + (["Planed"] if d.get("finish") in ("Planed", "Flattened", "Sanded", "Finished") else [])
    moisture = {"Air dried": "Air Dried (AD)", "Kiln dried": "Kiln Dried (KD)", "Fresh sawn": "Surface Green (S-GRN)"}.get(d.get("dried"), "")
    base = s["site_url"].rstrip("/")
    pics = "|".join(base + "/" + str(p).lstrip("/") for p in d["photos"][:12])
    values = {
        header[0]: "Add",
        "CustomLabel": d["ref"],
        "*Category": CATEGORY,
        "*Title": title(d),
        "*ConditionID": "1000",
        "C:Wood Species": d["wood"],
        "C:Material": "Wood",
        "C:Form": "Plank" if re.search(r"board|plank", d["name"], re.I) else "Slab",
        "C:Type": "Board" if re.search(r"board|plank", d["name"], re.I) else "Slab",
        "C:Features": "|".join(features),
        "C:Hardwood/Softwood": "Softwood" if d["wood"] in SOFTWOODS else "Hardwood",
        "C:Finish": "Untreated",
        "C:Colour": "Beige" if d["wood"] in PALE else ("Red" if d["wood"] == "Redwood" else "Brown"),
        "C:Item Length": f"{fmt(length * 100)} cm",
        "C:Item Width": f"{fmt(width / 10)} cm",
        "C:Size": f"{fmt(length * 100)} x {fmt(width / 10)} cm",
        "C:Item Thickness": f"{fmt(thick / 10)} cm" if thick else "",
        "C:Number in Pack": "1",
        "C:Brand": "Unbranded",
        "C:Country of Origin": "United Kingdom",
        "C:Moisture Content": moisture,
        "C:Suitable For": "Furniture & Cabinets|Shelving|Woodworking Project",
        "C:Texture": "Smooth" if "Planed" in features else "",
        "PicURL": pics,
        "*Description": describe(d, policy_label, s),
        "*Format": "FixedPrice",
        "*Duration": "GTC",
        "*StartPrice": fmt(num(d["price"])),
        "*Quantity": "1",
        "*Location": s["location"],
        "*DispatchTimeMax": str(s.get("dispatch_days", 3)),
        "*ReturnsAcceptedOption": "ReturnsAccepted",
        "ReturnsWithinOption": "Days_30",
        "RefundOption": "MoneyBack",
        "ShippingCostPaidByOption": "Buyer",
        "ShippingProfileName": policy,
        "PostalCode": s.get("postcode", ""),
    }
    return [values.get(h, "") for h in header], policy_label


def build(entries):
    s = load_settings()
    with TEMPLATE.open(encoding="utf-8") as f:
        info, header = list(csv.reader(f))[:2]
    header = header + EXTRA_COLUMNS
    ready, waiting = [], []
    for _, d, _ in entries:
        if not d.get("name"):
            continue
        reason = why_not(d, s)
        if reason == "":
            ready.append(d)
        elif reason:
            waiting.append((d, reason))
    ready.sort(key=lambda d: d["ref"])
    lines = []
    with OUT_CSV.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(info)
        w.writerow(header)
        for d in ready:
            r, label = row(d, header, s)
            w.writerow(r)
            lines.append((d, label))
    write_page(lines, waiting)
    print(f"ebay.csv: {len(lines)} pieces ready, {len(waiting)} need details")


def write_page(lines, waiting):
    def li(d, extra):
        return f"<tr><td class='nw'>{html.escape(d['ref'])}</td><td>{html.escape(d['name'])}</td><td class='nw'>£{fmt(num(d['price']))}</td><td>{html.escape(extra)}</td></tr>"
    ready = "".join(li(d, label) for d, label in lines) or "<tr><td colspan='4'>Nothing new to list right now.</td></tr>"
    todo = "".join(li(d, why) for d, why in waiting)
    todo_block = f"<h2>Not in the file yet</h2><p>These can go on eBay once they have a bit more detail in the stock manager:</p><div class='scroll'><table class='eb'><tr><th>No.</th><th>Piece</th><th>Price</th><th>Needs</th></tr>{todo}</table></div>" if todo else ""
    OUT_PAGE.write_text(f"""<!DOCTYPE html>
<html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>eBay Upload</title><link rel="icon" href="favicon.png">
<link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@700&family=Questrial&display=swap" rel="stylesheet">
<link rel="stylesheet" href="style.css">
<style>.eb{{width:100%;border-collapse:collapse;font-size:15px}}.eb th,.eb td{{text-align:left;padding:10px 8px;border-bottom:1px solid var(--line);vertical-align:top}}.eb th{{font-size:14px;color:var(--muted)}}.steps{{padding-left:1.2em}}.steps li{{margin:6px 0}}main.band{{max-width:900px;margin:0 auto}}main h2{{margin:36px 0 10px;font-size:24px}}</style>
</head><body>
<main class="band">
<h1>eBay upload</h1>
<p style="margin:12px 0 20px;color:var(--muted)">Available pieces that aren't ticked "Listed on eBay". Up to 80 × 40cm: £5 postage. Up to 1.2m × 50cm: £10 postage. Anything bigger: collection only. This page updates every time you save in the stock manager.</p>
<a class="btn btn-dark" href="ebay.csv" download>Download eBay file ({len(lines)} piece{'s' if len(lines) != 1 else ''})</a>
<h2>In the file</h2>
<div class="scroll"><table class="eb"><tr><th>No.</th><th>Piece</th><th>Price</th><th>Postage</th></tr>{ready}</table></div>
{todo_block}
<h2>How to upload</h2>
<ol class="steps">
<li>Download the file above.</li>
<li>On eBay go to <b>Seller Hub → Reports → Uploads</b>, click <b>Upload template</b> and choose the file.</li>
<li>Check the results report eBay gives you for any errors.</li>
<li>In the stock manager, tick <b>Listed on eBay</b> on each piece that went up, so it isn't added again.</li>
</ol>
<p style="margin-top:20px;color:var(--muted)">Sold on eBay? Use "Sold or reserved a piece" in the stock manager. Sold elsewhere? End the listing in the eBay app.</p>
</main></body></html>
""", encoding="utf-8")
