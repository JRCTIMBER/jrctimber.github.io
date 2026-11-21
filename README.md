# JRC Timber website

A simple static website for jrctimber.co.uk, hosted free on GitHub Pages.

## What's in here

- `index.html` – the home page (services, recent work, about, contact form)
- `shop.html` – the shop page, which reads `stock.json`
- `_stock/` – one file per piece of stock (managed in Pages CMS)
- `stock.json` – made automatically from `_stock/`; don't edit by hand
- `style.css` – the look of both pages
- `site.js` – the phone menu
- `img/` – photos and logo, already resized for the web
- `404.html` – sends old Wix links (e.g. /shop, /product-page/...) to the right section
- Custom domain: set jrctimber.co.uk under Settings → Pages when switching over (GitHub creates a CNAME file)

## Updating the shop (stock manager)

Stock is managed at **https://app.pagescms.org** (sign in with GitHub). Open this repository and tap **Stock**.

- **Add a piece:** tap **Add an entry**, take or choose photos, fill in the name, wood, measurements and price, and **Save**.
  About a minute later it's on the shop with the next stock number (JRC-025, JRC-026, …). Open the piece again to see its number.
- **Sold or reserved:** tap **Sold or reserved a piece** (in the menu or at the top of the Stock screen), type the stock number,
  choose Sold, Reserved, Available again or Remove from the site, and confirm.
- **Edit a piece:** search by stock number, name or wood, open it, change it and **Save**.

Behind the scenes (`.github/workflows/site.yml` and `scripts/process_stock.py`) every change:
gives new pieces a stock number, shrinks photos to 1600px with a 640px thumbnail and removes their location data,
writes `stock.json` for the shop page, and republishes the site.

Each piece is a small file in `_stock/`. The last number used is kept in `.stock-counter`, so numbers are never reused.

## eBay

Every save also updates **jrctimber.github.io/ebay.html**, which has a download button for `ebay.csv`:
an eBay upload file (eBay's Timber category template, category 180970) with every piece that is

- Available and not ticked **Listed on eBay**
- has a length, a width and at least one photo.

Postage is chosen by size, using postage policies saved in the eBay account (names in `_data/ebay.yml`,
editable in Pages CMS under **eBay settings**):

| Size | eBay postage policy |
|---|---|
| up to 80cm long and 40cm wide | `JRC £5 postage` |
| up to 1.2m long and 50cm wide | `JRC £10 postage` |
| anything longer or wider | `JRC collection only` |

Upload the file in eBay **Seller Hub → Reports → Uploads**, then tick **Listed on eBay** on those pieces.
Photo links use `site_url` in the eBay settings: change it to `https://jrctimber.co.uk` once the domain is switched.

## Common edits

- **Services:** in `index.html`, find `const services = [` and edit the name or description. The optional fifth item is the max size, e.g. `"Slabs up to 1.2m wide × 3m long"`.
- **FAQ:** in `index.html`, find `id="faq"`. Each question is a `<details>` block.
- **Recent work photos:** add `img/work-13.jpg` (large) and `img/work-13-t.jpg` (small), then add a line to `const work = [`.
- **Phone / email:** search for `07596` and `info@jrctimber.co.uk`.

## Connecting the enquiry form

1. Create a free form at formspree.io, using info@jrctimber.co.uk.
2. Copy the form's URL (looks like `https://formspree.io/f/abcdwxyz`).
3. In `index.html`, paste it into `const FORM_ENDPOINT = "";`.

Enquiries will then arrive by email.

## Google reviews

1. Create a free account at featurable.com and make a widget for your Google Business Profile.
2. Click "Embed" and copy the code. It contains an id like `featurable-Wd8c0xk...`.
3. In `index.html`, paste that id into `const FEATURABLE_ID = "";`.

The reviews then appear in the Reviews section and update automatically.
