"""Online buying, a page per piece, and the Google product feed.

Called from process_stock.py after stock numbers and photos are sorted:

  square_sync(entries)   Creates a Square payment link for each available piece (Square's links take
                         one payment only), removes links for reserved/sold/removed pieces, and marks
                         pieces Sold once their link has been paid. Needs the SQUARE_TOKEN secret;
                         without it this step is skipped and the site carries on with Reserve only.
  piece_pages(entries)   Writes stock/jrc-025.html etc. with photos, details, Buy now and Google
                         product data (schema.org Product).
  google_feed(entries)   Writes google-products.xml for Google Merchant Center (scheduled fetch).

Links between pieces and Square are kept in .square-links.json:
  {"_location": "L...", "JRC-025": {"id": "...", "url": "https://square.link/u/...", "order_id": "...", "amount": 17000, "band": "medium"}}
"""
import html
import json
import os
import re
import uuid
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import requests

ROOT = Path(__file__).resolve().parent.parent
LINKS = ROOT / ".square-links.json"
PAGES = ROOT / "stock"
FEED = ROOT / "google-products.xml"
SHOP = ROOT / "shop.html"
RETURN_DAYS = 14


# ---------- helpers ----------

def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fmt(n):
    return f"{n:g}"


def slug(ref):
    return str(ref).lower()


def page_path(ref):
    return f"stock/{slug(ref)}.html"


def is_live(d):
    """On the website at all (has a name, number and no problem)."""
    return bool(d.get("name") and d.get("ref") and not d.get("problem"))


def status(d):
    return str(d.get("status") or "Available").lower()


def band(d, s):
    """Postage band from the eBay settings: small (£5), medium (£10) or collection."""
    length, width = num(d.get("length")), num(d.get("width"))
    if length is None or width is None:
        return "collection"
    if length <= float(s["small_max_length_m"]) and width <= float(s["small_max_width_mm"]):
        return "small"
    if length <= float(s["medium_max_length_m"]) and width <= float(s["medium_max_width_mm"]):
        return "medium"
    return "collection"


BAND_PRICE = {"small": 500, "medium": 1000, "collection": None}  # pence
BAND_LABEL = {"small": "£5 tracked delivery", "medium": "£10 tracked delivery", "collection": "Collection only"}


def dims(d):
    length, width, wmin, thick = (num(d.get(k)) for k in ("length", "width", "width_min", "thickness"))
    out = []
    if length:
        out.append(f"{fmt(length)}m long")
    if width:
        out.append(f"{fmt(wmin)}–{fmt(width)}mm wide" if wmin else f"{fmt(width)}mm wide")
    if thick:
        out.append(f"{fmt(thick)}mm thick")
    return out


def long_title(d):
    bits = [f"Live edge {d.get('wood', '').lower()} {('board' if re.search(r'board|plank', d['name'], re.I) else 'slab')}"]
    bits += dims(d)
    if d.get("dried"):
        bits.append(d["dried"].lower())
    return f"{d['name']} – " + ", ".join(bits) + f" ({d['ref']})"


def thumb_of(p):
    """img/stock/abc.jpg -> img/stock/thumbs/abc.jpg"""
    head, _, name = str(p).lstrip("/").rpartition("/")
    return f"{head}/thumbs/{name.rsplit('.', 1)[0]}.jpg"


def photo_urls(d, base):
    return [base + "/" + str(p).lstrip("/") for p in (d.get("photos") or [])]


def load_links():
    return json.loads(LINKS.read_text()) if LINKS.exists() else {}


def save_links(links):
    LINKS.write_text(json.dumps(links, indent=1, sort_keys=True) + "\n")


# ---------- Square ----------

def square(method, path, data=None):
    token = os.environ.get("SQUARE_TOKEN", "").strip()
    host = "https://connect.squareupsandbox.com" if os.environ.get("SQUARE_ENV", "").strip().lower() == "sandbox" \
        else "https://connect.squareup.com"
    r = requests.request(method, host + "/v2" + path, json=data,
                         headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Square {method} {path}: {r.status_code} {r.text[:300]}")
    return r.json() if r.text else {}


def location_id(links):
    """The Square location payments go to: SQUARE_LOCATION_ID if set, otherwise the main location."""
    loc = os.environ.get("SQUARE_LOCATION_ID", "").strip() or links.get("_location")
    if not loc:
        loc = square("GET", "/locations/main")["location"]["id"]
        print("Square: using the main location")
    links["_location"] = loc
    return loc


def create_link(d, b, loc, s):
    base = s["site_url"].rstrip("/")
    amount = int(round(num(d["price"]) * 100))
    desc = ", ".join([d.get("wood", "")] + dims(d)).strip(", ")
    options = {
        "redirect_url": f"{base}/thanks.html",
        "merchant_support_email": "info@jrctimber.co.uk",
        "ask_for_shipping_address": b != "collection",
    }
    if BAND_PRICE[b] is not None:
        options["shipping_fee"] = {"name": "Tracked delivery (UK mainland)",
                                   "charge": {"amount": BAND_PRICE[b], "currency": "GBP"}}
    body = {
        "idempotency_key": str(uuid.uuid4()),
        "description": f"{d['ref']} {d['name']}",
        "order": {
            "location_id": loc,
            "reference_id": d["ref"],
            "line_items": [{
                "name": f"{d['ref']} {d['name']}"[:500],
                "quantity": "1",
                "base_price_money": {"amount": amount, "currency": "GBP"},
                "note": (desc + (" – collection from Great Wigborough, Colchester" if b == "collection" else ""))[:2000],
            }],
            "metadata": {"ref": d["ref"]},
        },
        "checkout_options": options,
        "payment_note": d["ref"],
    }
    link = square("POST", "/online-checkout/payment-links", body)["payment_link"]
    print(f"Square: payment link for {d['ref']} ({BAND_LABEL[b]}, £{fmt(amount / 100)})")
    return {"id": link["id"], "url": link["url"], "order_id": link["order_id"], "amount": amount, "band": b}


def remove_link(links, ref):
    """Delete a piece's payment link (Square can't switch one off and on again; a new one is made if needed)."""
    rec = links.get(ref)
    if not rec:
        return
    try:
        square("DELETE", f"/online-checkout/payment-links/{rec['id']}")
        print(f"Square: link for {ref} removed")
    except RuntimeError as e:
        if " 404 " not in str(e):
            print(f"Square: couldn't remove link for {ref}, will retry: {e}")
            return
    links.pop(ref, None)


def paid_orders(links):
    """Order ids that have been paid. Square links are single-use, so a paid link can't be paid again."""
    ids = [rec["order_id"] for ref, rec in links.items() if not ref.startswith("_") and rec.get("order_id")]
    paid = set()
    for i in range(0, len(ids), 100):
        res = square("POST", "/orders/batch-retrieve", {"location_id": links["_location"], "order_ids": ids[i:i + 100]})
        for o in res.get("orders", []):
            if o.get("state") in ("OPEN", "COMPLETED"):
                paid.add(o["id"])
    return paid


def square_sync(entries, s, write_entry):
    links = load_links()
    if not os.environ.get("SQUARE_TOKEN", "").strip():
        print("Square: no SQUARE_TOKEN set, skipping online payments")
        save_links(links)
        return links
    try:
        loc = location_id(links)
        # 1. Paid links: mark the piece Sold and forget the link
        paid = paid_orders(links)
        for ref, rec in list(links.items()):
            if ref.startswith("_") or rec.get("order_id") not in paid:
                continue
            links.pop(ref)
            for path, d, body in entries:
                if d.get("ref") == ref and status(d) != "sold":
                    d["status"] = "Sold"
                    write_entry(path, d, body)
                    print(f"Sold online: {ref} ({d.get('name')})")
        # 2. Links follow each piece's status, price and postage band
        live_refs = set()
        for path, d, body in entries:
            if not is_live(d):
                continue
            ref = d["ref"]
            live_refs.add(ref)
            rec = links.get(ref)
            price = num(d.get("price"))
            # Buy now only for pieces people can see and measure: a photo, a length and a width
            want = (status(d) == "available" and price and price > 0 and d.get("photos")
                    and num(d.get("length")) and num(d.get("width")))
            if not want:
                remove_link(links, ref)
                continue
            b = band(d, s)
            amount = int(round(price * 100))
            if rec and rec["amount"] == amount and rec["band"] == b:
                continue
            if rec:
                remove_link(links, ref)
                if ref in links:
                    continue  # couldn't remove the old link; try again next run
            links[ref] = create_link(d, b, loc, s)
        # 3. Pieces removed from the site
        for ref in [r for r in links if not r.startswith("_") and r not in live_refs]:
            remove_link(links, ref)
    except (RuntimeError, requests.RequestException, KeyError) as e:
        print(f"Square: stopped early, will retry next run: {e}")
    save_links(links)
    return links


def buy_url(d, links):
    rec = links.get(d.get("ref") or "")
    if rec and status(d) == "available":
        return rec["url"]
    return ""


# ---------- pages ----------

def shell():
    """Header and footer from shop.html, so piece pages always match the site."""
    src = SHOP.read_text(encoding="utf-8")
    head = src[src.index("<body>") + 6:src.index("<main>")]
    foot = src[src.index("</main>") + 7:src.index("<script>\n{")]
    return head, foot


def piece_pages(entries, links, s):
    PAGES.mkdir(exist_ok=True)
    head, foot = shell()
    base = s["site_url"].rstrip("/")
    keep = set()
    for _, d, _ in entries:
        if not is_live(d):
            continue
        name = PAGES / f"{slug(d['ref'])}.html"
        keep.add(name.name)
        name.write_text(piece_html(d, links, s, base, head, foot), encoding="utf-8")
    for f in PAGES.glob("*.html"):
        if f.name not in keep:
            f.unlink()
    print(f"Piece pages: {len(keep)}")


def piece_html(d, links, s, base, head, foot):
    e = html.escape
    ref, st = d["ref"], status(d)
    price = num(d.get("price")) or 0
    was = num(d.get("was"))
    b = band(d, s)
    url = buy_url(d, links)
    photos = d.get("photos") or []
    full = [str(p).lstrip("/") for p in photos]
    abs_photos = photo_urls(d, base)
    page_url = f"{base}/{page_path(ref)}"
    rows = [("Stock number", ref), ("Wood", d.get("wood", ""))]
    length, width, wmin, thick = (num(d.get(k)) for k in ("length", "width", "width_min", "thickness"))
    if length:
        rows.append(("Length", f"{fmt(length)}m"))
    if width:
        rows.append(("Width", f"{fmt(wmin)}–{fmt(width)}mm" if wmin else f"{fmt(width)}mm"))
    if thick:
        rows.append(("Thickness", f"{fmt(thick)}mm"))
    if d.get("dried"):
        rows.append(("Drying", d["dried"]))
    if d.get("finish"):
        rows.append(("Finish", d["finish"]))
    rows.append(("Delivery", BAND_LABEL[b] + (", or free collection" if b != "collection" else " from Great Wigborough, Colchester")))
    table = "".join(f"<tr><th>{e(k)}</th><td>{e(str(v))}</td></tr>" for k, v in rows)
    msg = f"Hi JRC Timber, is piece {ref}, the {d['name']}, £{fmt(price)}, still available?"
    wa = "https://wa.me/447596836838?text=" + requests.utils.quote(msg)
    if st == "sold":
        actions = "<p class='pp-sold'>This piece has sold. Call or WhatsApp us for similar pieces.</p>"
    elif st == "reserved":
        actions = f"<p class='pp-sold'>This piece is reserved.</p><a class='btn btn-outline' href='{e(wa)}' target='_blank' rel='noopener'>Ask about similar pieces</a>"
    else:
        extra = f" + £{fmt(BAND_PRICE[b] / 100)} delivery" if BAND_PRICE[b] is not None else " – collect from our yard"
        actions = (f"<a class='btn btn-wood pp-buy' href='{e(url)}'>Buy now – £{fmt(price)}{extra}</a>" if url else "") + \
                  f"<a class='btn {'btn-outline' if url else 'btn-dark'}' href='{e(wa)}' target='_blank' rel='noopener'><svg><use href='#i-chat'/></svg>Reserve on WhatsApp</a>"
        if url and BAND_PRICE[b] is not None:
            actions += "<p class='pp-small'>Collecting from the yard instead? Reserve on WhatsApp and pay by card or cash when you collect.</p>"
    gallery = ""
    if full:
        thumbs = "".join(f"<button type='button' data-src='{e(p)}' aria-label='Photo {i + 1}'><img src='{e(thumb_of(p))}' alt=''></button>"
                         for i, p in enumerate(full)) if len(full) > 1 else ""
        gallery = f"<div class='pp-pics'><img id='pp-main' src='{e(full[0])}' alt='{e(d['name'])}'><div class='pp-thumbs'>{thumbs}</div></div>"
    else:
        gallery = "<div class='pp-pics pp-none'><p>Photos coming soon. Ask us on WhatsApp and we'll send some.</p></div>"
    availability = {"available": "InStock", "reserved": "OutOfStock", "sold": "SoldOut"}.get(st, "InStock")
    offer = {
        "@type": "Offer", "url": page_url, "price": f"{price:.2f}", "priceCurrency": "GBP",
        "availability": f"https://schema.org/{availability}", "itemCondition": "https://schema.org/NewCondition",
        "seller": {"@type": "Organization", "name": "JRC Timber"},
        "hasMerchantReturnPolicy": {
            "@type": "MerchantReturnPolicy", "applicableCountry": "GB",
            "returnPolicyCategory": "https://schema.org/MerchantReturnFiniteReturnWindow",
            "merchantReturnDays": RETURN_DAYS, "returnMethod": "https://schema.org/ReturnByMail",
            "returnFees": "https://schema.org/ReturnShippingFees"},
    }
    if BAND_PRICE[b] is not None:
        offer["shippingDetails"] = {
            "@type": "OfferShippingDetails",
            "shippingRate": {"@type": "MonetaryAmount", "value": f"{BAND_PRICE[b] / 100:.2f}", "currency": "GBP"},
            "shippingDestination": {"@type": "DefinedRegion", "addressCountry": "GB"},
            "deliveryTime": {"@type": "ShippingDeliveryTime",
                             "handlingTime": {"@type": "QuantitativeValue", "minValue": 0, "maxValue": int(s.get("dispatch_days", 3)), "unitCode": "DAY"},
                             "transitTime": {"@type": "QuantitativeValue", "minValue": 1, "maxValue": 3, "unitCode": "DAY"}}}
    product = {"@context": "https://schema.org/", "@type": "Product", "name": f"{d['name']} ({ref})", "sku": ref,
               "description": long_title(d) + (f". {d['note']}" if d.get("note") else ""),
               "brand": {"@type": "Brand", "name": "JRC Timber"}, "material": d.get("wood", ""), "offers": offer}
    if abs_photos:
        product["image"] = abs_photos
    ld = json.dumps(product, ensure_ascii=False).replace("</", "<\\/")
    price_html = f"£{fmt(price)}" + (f" <s>£{fmt(was)}</s>" if was else "")
    note = f"<p class='pp-note'>{e(d['note'])}</p>" if d.get("note") else ""
    rough = "<p class='pp-note'>Can be flattened or planed for you before collection or delivery.</p>" if re.search(r"rough|sawn", str(d.get("finish") or ""), re.I) else ""
    return f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<base href="../">
<title>{e(d['name'])} {e(ref)} | JRC Timber</title>
<meta name="description" content="{e(long_title(d))}. £{fmt(price)}. Local Essex timber from JRC Timber, Colchester.">
<link rel="canonical" href="{e(page_url)}">
<link rel="icon" href="favicon.png">
<meta property="og:title" content="{e(d['name'])} ({e(ref)}) – £{fmt(price)}">
{f'<meta property="og:image" content="{e(abs_photos[0])}">' if abs_photos else ''}
<meta name="theme-color" content="#365347">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Questrial&display=swap" rel="stylesheet">
<link rel="stylesheet" href="style.css">
<script type="application/ld+json">{ld}</script>
</head>
<body>{head}<main>
<section class="band pp">
  <div class="wrap">
    <p class="pp-crumb"><a href="shop.html">Shop</a> › {e(d.get('wood', ''))} › {e(ref)}</p>
    <div class="pp-grid">
      {gallery}
      <div class="pp-info">
        <p class="pp-ref">{e(d.get('wood', ''))} · {e(ref)}</p>
        <h1>{e(d['name'])}</h1>
        <p class="pp-price">{price_html}</p>
        {note}{rough}
        <div class="pp-acts">{actions}</div>
        <table class="pp-table">{table}</table>
        <p class="pp-small">Every piece is one of a kind and the photos show this exact piece. Card payments are handled securely by Square. See <a href="delivery.html">delivery &amp; returns</a>.</p>
      </div>
    </div>
  </div>
</section>
</main>{foot}<script>
{{
  const main = document.getElementById("pp-main");
  document.querySelectorAll(".pp-thumbs button").forEach(b => b.addEventListener("click", () => {{ main.src = b.dataset.src; }}));
}}
</script>
<script src="site.js"></script>
</body>
</html>
"""


# ---------- Google feed ----------

def google_feed(entries, links, s):
    base = s["site_url"].rstrip("/")
    items = []
    for _, d, _ in entries:
        if not is_live(d) or status(d) != "available":
            continue
        url = buy_url(d, links)
        b = band(d, s)
        photos = photo_urls(d, base)
        if not url or not photos or BAND_PRICE[b] is None:
            continue
        price = num(d["price"])
        x = lambda t: xml_escape(str(t))
        extra = "".join(f"<g:additional_image_link>{x(p)}</g:additional_image_link>" for p in photos[1:10])
        sale = ""
        was = num(d.get("was"))
        if was and was > price:
            sale = f"<g:sale_price>{price:.2f} GBP</g:sale_price>"
            price = was
        items.append(f"""<item>
<g:id>{x(d['ref'])}</g:id>
<g:title>{x(long_title(d)[:150])}</g:title>
<g:description>{x(long_title(d) + '. Cut from a local Essex tree and milled by JRC Timber near Colchester. ' + (d.get('note') or ''))}</g:description>
<g:link>{x(base + '/' + page_path(d['ref']))}</g:link>
<g:image_link>{x(photos[0])}</g:image_link>{extra}
<g:availability>in_stock</g:availability>
<g:price>{price:.2f} GBP</g:price>{sale}
<g:condition>new</g:condition>
<g:brand>JRC Timber</g:brand>
<g:identifier_exists>no</g:identifier_exists>
<g:product_type>Timber &gt; Live edge slabs &gt; {x(d.get('wood', ''))}</g:product_type>
<g:material>{x(d.get('wood', ''))}</g:material>
<g:shipping><g:country>GB</g:country><g:price>{BAND_PRICE[b] / 100:.2f} GBP</g:price></g:shipping>
</item>""")
    FEED.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:g="http://base.google.com/ns/1.0" version="2.0">
<channel>
<title>JRC Timber stock</title>
<link>{xml_escape(base)}/shop.html</link>
<description>Live edge slabs and boards from local Essex trees</description>
{chr(10).join(items)}
</channel>
</rss>
""", encoding="utf-8")
    print(f"google-products.xml: {len(items)} pieces")


# ---------- delivery & returns page ----------

def delivery_page(s):
    head, foot = shell()
    head = head.replace(' aria-current="page"', "")
    sl, sw = fmt(float(s["small_max_length_m"]) * 100), fmt(float(s["small_max_width_mm"]) / 10)
    ml, mw = fmt(float(s["medium_max_length_m"]) * 100), fmt(float(s["medium_max_width_mm"]) / 10)
    days = int(s.get("dispatch_days", 3))
    (ROOT / "delivery.html").write_text(f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Delivery &amp; Returns | JRC Timber</title>
<meta name="description" content="Delivery, collection, returns and payment information for JRC Timber, Great Wigborough, Colchester.">
<link rel="icon" href="favicon.png">
<meta name="theme-color" content="#365347">
<link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Questrial&display=swap" rel="stylesheet">
<link rel="stylesheet" href="style.css">
</head>
<body>{head}<main>
<section class="band">
  <div class="wrap doc">
    <h1>Delivery &amp; returns</h1>

    <h2>Delivery</h2>
    <table>
      <tr><th>Piece size</th><th>Delivery</th></tr>
      <tr><td>Up to {sl}cm long and {sw}cm wide</td><td>£5 tracked delivery</td></tr>
      <tr><td>Up to {ml}cm long and {mw}cm wide</td><td>£10 tracked delivery</td></tr>
      <tr><td>Larger pieces</td><td>Collection, or ask us for a delivery quote</td></tr>
    </table>
    <p>We deliver to UK mainland addresses and aim to send pieces within {days} working days of payment. The delivery price for each piece is shown on its page and at checkout.</p>

    <h2>Collection</h2>
    <p>Collection from our yard is always free: Layer Road, Great Wigborough, Colchester CO5 7RP. Visits are by appointment, 7 days a week. Call or WhatsApp <a href="tel:+447596836838">07596 836838</a> to arrange a time.</p>

    <h2>Paying</h2>
    <p>Pieces with a Buy now button can be paid for online by card, Apple Pay or Google Pay. Buy now includes delivery where the piece can be sent. Payments are handled securely by Square and we never see your card details. To collect instead, reserve a piece on WhatsApp or by phone and pay by card or cash at the yard. Prices are in pounds sterling.</p>

    <h2>Returns</h2>
    <p>If you buy online and change your mind, tell us within {RETURN_DAYS} days of receiving your piece, then return it within a further {RETURN_DAYS} days in the condition you received it. We'll refund the price of the piece and the standard delivery charge within {RETURN_DAYS} days of getting it back. Return postage is paid by you unless the piece is faulty or not as described.</p>
    <p>Pieces you've seen and collected in person, and work made or altered to your order (cut to size, flattened, planed or made into furniture), can't be returned unless they're faulty. This doesn't affect your legal rights.</p>

    <h2>About natural timber</h2>
    <p>Every piece is one of a kind and the photos show the actual piece. Wood is a natural material: colour changes over time, and pieces can move or develop small checks as they adjust to a new environment. That's normal and not a fault.</p>

    <h2>Your details</h2>
    <p>We only use the details you give us (through the enquiry form, WhatsApp, phone or checkout) to answer you and arrange your order. We don't sell or share them for marketing.</p>

    <h2>Contact</h2>
    <p>JRC Timber, run by Josh Cook. Layer Road, Great Wigborough, Colchester CO5 7RP. <a href="tel:+447596836838">07596 836838</a> · <a href="mailto:info@jrctimber.co.uk">info@jrctimber.co.uk</a></p>
  </div>
</section>
</main>{foot}<script src="site.js"></script>
</body>
</html>
""", encoding="utf-8")
    (ROOT / "thanks.html").write_text(f"""<!DOCTYPE html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Thank you | JRC Timber</title>
<meta name="robots" content="noindex">
<link rel="icon" href="favicon.png">
<meta name="theme-color" content="#365347">
<link href="https://fonts.googleapis.com/css2?family=Libre+Baskerville:wght@400;700&family=Questrial&display=swap" rel="stylesheet">
<link rel="stylesheet" href="style.css">
</head>
<body>{head}<main>
<section class="band">
  <div class="wrap doc">
    <h1>Thank you, the piece is yours</h1>
    <p>Your payment has gone through and Square has emailed you a receipt. We'll be in touch within a day to arrange delivery or collection.</p>
    <p>Questions? Call or WhatsApp <a href="tel:+447596836838">07596 836838</a> or email <a href="mailto:info@jrctimber.co.uk">info@jrctimber.co.uk</a>.</p>
    <p><a class="btn btn-dark" href="shop.html">Back to the shop</a></p>
  </div>
</section>
</main>{foot}<script src="site.js"></script>
</body>
</html>
""", encoding="utf-8")
