# JRC Timber website

A simple static website for jrctimber.co.uk, hosted free on GitHub Pages.

## What's in here

- `index.html` – the home page (services, recent work, about, contact form)
- `shop.html` – the shop page, which reads its list from `stock.csv`
- `stock.csv` – the stock list (open in Excel or Google Sheets)
- `style.css` – the look of both pages
- `site.js` – the phone menu
- `img/` – photos and logo, already resized for the web
- `404.html` – sends old Wix links (e.g. /shop, /product-page/...) to the right section
- Custom domain: set jrctimber.co.uk under Settings → Pages when switching over (GitHub creates a CNAME file)

## Updating the shop

Open `stock.csv` in Excel or Google Sheets. One row per piece:

- **ref** – the piece number, e.g. `JRC-025`. Customers quote it when they reserve.
- **name, wood, price** – e.g. `Oak slab, Oak, 170`
- **length** – in metres, e.g. `2.45m`
- **width** – widest point in mm, e.g. `520`. **width_min** – narrowest point in mm (optional)
- **thickness** – in mm, e.g. `55`
- **dried** – `Air dried` or `Kiln dried`
- **finish** – e.g. `Rough sawn`, `Flattened`, `Planed`. Rough sawn pieces show "Can be flattened or planed for you".
- **was** – the old price, if it's reduced (shows a "Reduced" tag)
- **status** – `available`, `reserved` or `sold`
- **note** – optional short line, e.g. `Ideal for resin projects`
- **photo** – a file name in `img/`, e.g. `stock-oak-slab.jpg`. Leave blank to show a drawn placeholder.

Save it as CSV and upload it to replace the old one.

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
