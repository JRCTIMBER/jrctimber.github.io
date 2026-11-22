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

- **Add a piece:** tap **Add an entry**, type the number from the piece's tag (e.g. `25`), take or choose photos,
  fill in the name, wood, measurements and price, and **Save**. About a minute later it's in the shop as JRC-025.
  Leave the number blank and it gets the next free number automatically.
- **Number used twice?** The newer piece is hidden from the shop and eBay, shows a **Problem** message in the stock manager,
  and is listed under "Needs checking" on jrctimber.github.io/ebay.html until the number is corrected.
- **Sold or reserved:** tap **Sold or reserved a piece** (in the menu or at the top of the Stock screen), type the stock number,
  choose Sold, Reserved, Available again or Remove from the site, and confirm.
- **Edit a piece:** search by stock number, name or wood, open it, change it and **Save**.

Behind the scenes (`.github/workflows/site.yml` and `scripts/process_stock.py`) every change:
gives new pieces a stock number, shrinks photos to 1600px with a 640px thumbnail and removes their location data,
writes `stock.json` for the shop page, and republishes the site.

Each piece is a small file in `_stock/`. The highest number used is kept in `.stock-counter` and `.stock-index.json` records which file owns each number.

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

## Buying online (Square) and Google Shopping

Each piece has its own page at `stock/jrc-025.html` (made automatically) with photos, details, **Buy now**,
Reserve on WhatsApp, and Google product data (schema.org Product).

**Buy now** appears for available pieces that have a photo, a length and a width, once a Square token is added:
- Each piece gets its own Square payment link. Square's links take **one payment** only, so a piece can't be sold twice online.
- The price includes postage for the size band (£5 or £10) and asks for the delivery address.
  Collection-only pieces are paid for online and collected. Buyers who'd rather collect a piece that can be posted
  reserve it on WhatsApp and pay at the yard.
- Links are removed automatically when a piece is reserved, sold, removed, or its price or size changes
  (a new link is made when it's available again or at the new price).
- Every 15 minutes the automation checks Square for paid links and marks those pieces **Sold**.
  The sale shows in your Square Dashboard and app (Orders) with the buyer's address. Buyers land on `thanks.html`.
- Links are recorded in `.square-links.json`.

To turn it on: at developer.squareup.com sign in with your Square account, create an application, open
**Credentials**, switch to **Production** and copy the **Production access token**. Add it in GitHub under
Settings → Secrets and variables → Actions as `SQUARE_TOKEN`. Payments go to your main Square location; to use
another one add its ID as `SQUARE_LOCATION_ID`. To try it with Square's test cards first, use the Sandbox token
and add a secret `SQUARE_ENV` set to `sandbox` (delete it and swap in the production token when done).

**Google Shopping:** `google-products.xml` lists available pieces with Buy now, a photo and £5/£10 delivery.
Add `https://jrctimber.co.uk/google-products.xml` in Google Merchant Center as a scheduled-fetch product source.
Collection-only pieces aren't in the feed (Google needs a delivery price) but still get their own page.

**Delivery & returns** (`delivery.html`) is made from the eBay settings so the sizes and prices always match.

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
