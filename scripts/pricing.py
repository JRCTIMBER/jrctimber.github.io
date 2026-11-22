"""Works out each piece's price from the price list in _data/prices.yml.

price = length (m) × width (m) × thickness (m) × price per m³, × 1.5 for special timber, rounded to £1.

Which price per m³:
  Finish "Rough sawn" (or blank finish) and Drying "Fresh sawn"  -> green timber, rough sawn
  Finish "Rough sawn"                                            -> unplaned, by width
  Finish Flattened / Planed / Sanded / Finished                  -> planed, by edges and width

The result is saved on the piece as list_price, with the working in price_working, so it shows in the
stock manager. A price typed into "Your price" on the piece is used instead (see price_of).
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PRICES = ROOT / "_data" / "prices.yml"

DEFAULTS = {
    "green_rough_sawn": 1500,
    "unplaned_narrow": 2300, "unplaned_wide": 4300, "unplaned_wide_from_mm": 700,
    "live_one_side": 3500, "live_one_side_max_mm": 700,
    "live_both_narrow": 3000, "live_both_narrow_max_mm": 700,
    "live_both_mid": 5750, "live_both_mid_max_mm": 1000,
    "live_both_wide": 7000,
    "straight_narrow": 4000, "straight_narrow_max_mm": 300, "straight_wide": 4500,
    "special_woods": ["Walnut"], "special_multiplier": 1.5,
}
PLANED = {"flattened", "planed", "sanded", "finished"}


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def money(v):
    return f"£{v:,.0f}" if float(v).is_integer() else f"£{v:,.2f}"


def fmt(v):
    return f"{v:g}"


def load_prices():
    p = dict(DEFAULTS)
    if PRICES.exists():
        p.update({k: v for k, v in (yaml.safe_load(PRICES.read_text(encoding="utf-8")) or {}).items() if v not in (None, "")})
    return p


def rate_for(d, p):
    """(price per m³, description, warning or '')"""
    width = num(d.get("width"))
    finish = str(d.get("finish") or "").strip().lower()
    dried = str(d.get("dried") or "").strip().lower()
    edges = str(d.get("edges") or "Live edge both sides").strip().lower()
    if finish not in PLANED:
        if dried == "fresh sawn":
            return p["green_rough_sawn"], "green, rough sawn", ""
        if not finish:
            return None, "", "Choose the finish to work out the price."
        if width < float(p["unplaned_wide_from_mm"]):
            return p["unplaned_narrow"], f"unplaned, under {fmt(float(p['unplaned_wide_from_mm']))}mm", ""
        return p["unplaned_wide"], f"unplaned, {fmt(float(p['unplaned_wide_from_mm']))}mm and over", ""
    if edges.startswith("straight"):
        if width <= float(p["straight_narrow_max_mm"]):
            return p["straight_narrow"], f"planed, straight edges, up to {fmt(float(p['straight_narrow_max_mm']))}mm", ""
        return p["straight_wide"], f"planed, straight edges, over {fmt(float(p['straight_narrow_max_mm']))}mm", ""
    if "one side" in edges and width <= float(p["live_one_side_max_mm"]):
        return p["live_one_side"], f"planed, live edge one side, up to {fmt(float(p['live_one_side_max_mm']))}mm", ""
    # live edge both sides (and one side over 700mm, which the list doesn't cover)
    side = "live edge one side" if "one side" in edges else "live edge both sides"
    if width <= float(p["live_both_narrow_max_mm"]):
        return p["live_both_narrow"], f"planed, {side}, up to {fmt(float(p['live_both_narrow_max_mm']))}mm", ""
    if width <= float(p["live_both_mid_max_mm"]):
        return p["live_both_mid"], (f"planed, {side}, {fmt(float(p['live_both_narrow_max_mm']))}–"
                                    f"{fmt(float(p['live_both_mid_max_mm']))}mm"), ""
    return p["live_both_wide"], f"planed, {side}, over {fmt(float(p['live_both_mid_max_mm']))}mm", \
        "Over 1m wide is 'from' this price: check it and type your own price if needed."


def work_out(d, p):
    """(price or None, working text)"""
    length, width, thick = num(d.get("length")), num(d.get("width")), num(d.get("thickness"))
    missing = [n for n, v in (("length", length), ("width", width), ("thickness", thick)) if not v]
    if missing:
        return None, f"Add the {' and '.join(missing)} to work out the price."
    rate, what, warn = rate_for(d, p)
    if rate is None:
        return None, warn
    m3 = length * width / 1000 * thick / 1000
    base = m3 * float(rate)
    working = f"{fmt(length)} × {fmt(width / 1000)} × {fmt(thick / 1000)} = {f'{m3:.5f}'.rstrip('0')} m³ × {money(float(rate))} ({what})"
    special = d.get("wood") in (p.get("special_woods") or []) or bool(d.get("special"))
    if special:
        mult = float(p["special_multiplier"])
        price = max(1, round(base * mult))
        working += f" = {money(round(base, 2))}, × {fmt(mult)} special timber = £{price:,}"
    else:
        price = max(1, round(base))
        working += f" = £{price:,}"
    if warn:
        working += ". " + warn
    return price, working


def apply(entries, write_entry):
    """Save list_price and price_working on every piece that needs them changed."""
    p = load_prices()
    for path, d, body in entries:
        if not d.get("name"):
            continue
        price, working = work_out(d, p)
        new = {"list_price": price, "price_working": working}
        if any(d.get(k) != v for k, v in new.items()):
            for k, v in new.items():
                if v is None:
                    d.pop(k, None)
                else:
                    d[k] = v
            write_entry(path, d, body)
            print(f"Price for {d.get('ref')}: {working}")


def price_of(d):
    """The price shown and charged: your own price if typed in, otherwise the price list price."""
    own = num(d.get("price"))
    if own and own > 0:
        return own
    lp = num(d.get("list_price"))
    return lp if lp and lp > 0 else None
