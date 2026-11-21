"""Online buying, a page per piece, and the Google product feed.

Called from process_stock.py after stock numbers and photos are sorted:

  stripe_sync(entries)   Creates a Stripe payment link for each available piece (one payment only),
                         turns links off for reserved/sold/removed pieces, and marks pieces Sold
                         when a payment link has been paid. Needs the STRIPE_KEY secret; without it
                         this step is skipped and the site carries on with Reserve only.
  piece_pages(entries)   Writes stock/jrc-025.html etc. with photos, details, Buy now and Google
                         product data (schema.org Product).
  google_feed(entries)   Writes google-products.xml for Google Merchant Center (scheduled fetch).

Links between pieces and Stripe are kept in .stripe-links.json:
  {"JRC-025": {"id": "plink_...", "url": "https://buy.stripe.com/...", "amount": 17000, "band": "medium", "active": true}}
"""
import html
import json
import os
import re
import time
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

import requests

ROOT = Path(__file__).resolve().parent.parent
LINKS = ROOT / ".stripe-links.json"
PAGES = ROOT / "stock"
FEED = ROOT / "google-products.xml"
SHOP = ROOT / "shop.html"
API = "https://api.stripe.com/v1"
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


# ---------- Stripe ----------

def stripe(method, path, data=None):
    key = os.environ.get("STRIPE_KEY", "").strip()
    r = requests.request(method, API + path, auth=(key, ""), data=data if method == "POST" else None,
                         params=data if method == "GET" else None, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"Stripe {method} {path}: {r.status_code} {r.text[:300]}")
    return r.json()


def shipping_rates(links):
    """Create the three postage options once and remember their ids."""
    meta = links.setdefault("_rates", {})
    wanted = {
        "small": ("Tracked delivery (UK mainland)", 500),
        "medium": ("Tracked delivery (UK mainland)", 1000),
        "collection": ("Collect from our yard in Great Wigborough, Colchester (free)", 0),
    }
    for name, (label, amount) in wanted.items():
        if name not in meta:
            rate = stripe("POST", "/shipping_rates", {
                "display_name": label, "type": "fixed_amount",
                "fixed_amount[amount]": amount, "fixed_amount[currency]": "gbp",
                "metadata[jrc]": name,
            })
            meta[name] = rate["id"]
            print(f"Stripe: created postage option {name}")
    return meta


def create_link(d, b, rates, s):
    base = s["site_url"].rstrip("/")
    amount = int(round(num(d["price"]) * 100))
    product = {"name": f"{d['ref']} {d['name']}", "metadata[ref]": d["ref"],
               "description": ", ".join([d.get("wood", "")] + dims(d)).strip(", ") or d["name"],
               "url": f"{base}/{page_path(d['ref'])}"}
    for i, u in enumerate(photo_urls(d, base)[:8]):
        product[f"images[{i}]"] = u
    prod = stripe("POST", "/products", product)
    price = stripe("POST", "/prices", {"product": prod["id"], "unit_amount": amount, "currency": "gbp"})
    data = {
        "line_items[0][price]": price["id"], "line_items[0][quantity]": 1,
        "restrictions[completed_sessions][limit]": 1,
        "inactive_message": f"Sorry, {d['ref']} has sold or is reserved. Call or WhatsApp 07596 836838 for similar pieces.",
        "phone_number_collection[enabled]": "true",
        "metadata[ref]": d["ref"],
        "after_completion[type]": "hosted_confirmation",
        "after_completion[hosted_confirmation][custom_message]":
            f"Thank you! {d['ref']} is yours. We'll be in touch within a day to arrange delivery or collection. "
            "Questions? Call or WhatsApp 07596 836838.",
    }
    options = ([b] if b != "collection" else []) + ["collection"]
    for i, o in enumerate(options):
        data[f"shipping_options[{i}][shipping_rate]"] = rates[o]
    if b != "collection":
        data["shipping_address_collection[allowed_countries][0]"] = "GB"
    link = stripe("POST", "/payment_links", data)
    print(f"Stripe: payment link for {d['ref']} ({BAND_LABEL[b]}, £{fmt(amount / 100)})")
    return {"id": link["id"], "url": link["url"], "amount": amount, "band": b, "active": True}


def set_active(rec, active, ref):
    if rec.get("active") == active:
        return
    try:
        stripe("POST", f"/payment_links/{rec['id']}", {"active": "true" if active else "false"})
    except RuntimeError as e:
        print(f"Stripe: couldn't {'turn on' if active else 'turn off'} link for {ref}: {e}")
        if active:
            return
    rec["active"] = active
    print(f"Stripe: link for {ref} turned {'on' if active else 'off'}")


def stripe_sync(entries, s, write_entry):
    links = load_links()
    if not os.environ.get("STRIPE_KEY", "").strip():
        print("Stripe: no STRIPE_KEY set, skipping online payments")
        save_links(links)
        return links
    try:
        # 1. Anything paid for in the last 3 days becomes Sold
        by_link = {rec["id"]: ref for ref, rec in links.items() if not ref.startswith("_")}
        since = int(time.time()) - 3 * 86400
        page = stripe("GET", "/checkout/sessions", {"status": "complete", "limit": 100, "created[gte]": since})
        for sess in page.get("data", []):
            ref = by_link.get(sess.get("payment_link"))
            if not ref or sess.get("payment_status") not in ("paid", "no_payment_required"):
                continue
            for path, d, body in entries:
                if d.get("ref") == ref and status(d) != "sold":
                    d["status"] = "Sold"
                    write_entry(path, d, body)
                    links[ref]["active"] = False
                    print(f"Sold online: {ref} ({d.get('name')})")
        # 2. Links follow each piece's status, price and postage band
        rates = shipping_rates(links)
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
                if rec:
                    set_active(rec, False, ref)
                continue
            b = band(d, s)
            amount = int(round(price * 100))
            if rec and rec["amount"] == amount and rec["band"] == b:
                set_active(rec, True, ref)
                if rec.get("active"):
                    continue
            if rec:
                set_active(rec, False, ref)
            links[ref] = create_link(d, b, rates, s)
        # 3. Pieces removed from the site
        for ref, rec in links.items():
            if not ref.startswith("_") and ref not in live_refs:
                set_active(rec, False, ref)
    except (RuntimeError, requests.RequestException) as e:
        print(f"Stripe: stopped early, will retry next run: {e}")
    save_links(links)
    return links


def buy_url(d, links):
    rec = links.get(d.get("ref") or "")
    if rec and rec.get("active") and status(d) == "available":
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
        actions = (f"<a class='btn btn-wood pp-buy' href='{e(url)}'>Buy now – £{fmt(price)}</a>" if url else "") + \
                  f"<a class='btn {'btn-outline' if url else 'btn-dark'}' href='{e(wa)}' target='_blank' rel='noopener'><svg><use href='#i-chat'/></svg>Reserve on WhatsApp</a>"
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
        <p class="pp-small">Every piece is one of a kind and the photos show this exact piece. Card payments are handled securely by Stripe. See <a href="delivery.html">delivery &amp; returns</a>.</p>
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
    <p>We deliver to UK mainland addresses and aim to send pieces within {days} working days of payment. The delivery option for each piece is shown on its page and at checkout.</p>

    <h2>Collection</h2>
    <p>Collection from our yard is always free: Layer Road, Great Wigborough, Colchester CO5 7RP. Visits are by appointment, 7 days a week. Call or WhatsApp <a href="tel:+447596836838">07596 836838</a> to arrange a time.</p>

    <h2>Paying</h2>
    <p>Pieces with a Buy now button can be paid for online by card. Payments are handled securely by Stripe and we never see your card details. You can also reserve a piece on WhatsApp or by phone and pay on collection. Prices are in pounds sterling.</p>

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
