# Roadmap: ideas on hold

Ideas agreed as worth doing but not started. Each has what it is, how it would work, what it costs and what to check
first. Move an idea out of here when work starts.

## Quotation from a photo of site notes

*Proposed 23 Oct 2026. On hold.*

**The idea.** Designers write measurements in a notebook on site and type the quotation later at the office. Instead,
they photograph the notebook page(s) and the app turns them into a **draft quotation** they then finish as usual.

**How it would work**
1. New Quotation → **From site notes** → take or pick 1–3 photos (shrunk on the phone before upload).
2. An AI model that reads images (Claude, Anthropic API) returns rooms, items, sizes and counts as structured data
   (e.g. "Kitchen: base 10'6 x 2'9, loft 10 x 2, W/R 7x8").
3. Each item is matched to the firm's **own** items (BOQ lines, materials, fittings). Descriptions and rates always
   come from the firm's saved rates, **never from the AI**.
4. A draft quotation is saved and opened, with the photo alongside for checking. Anything unread or unmatched stays
   highlighted ("type the size"), and the usual checks (no line saved without its price) still apply.

**What to expect.** Neat notes read well. Rushed notes with private abbreviations, crossings-out and sketches will
sometimes be misread. It saves typing; the designer still checks every line.

**Cost (estimate; check current API prices before deciding).** Pay per photo to Anthropic: roughly ₹2–4 per page with
a mid-sized model (about ₹1 with a small one, which reads handwriting less reliably). That's about ₹80–160 a month for
a firm doing 20 quotations of 2 pages, or ₹8,000–16,000 a month at 100 firms. Against ~₹833/month per firm, heavy use
could take 10–20% of revenue, so cap it: a **monthly page limit per plan** (e.g. 40) or a paid add-on. Photos are
read and discarded, not stored.

**Before building**
- Test on 3–4 **real** notebook photos from a firm (e.g. Dizine Interiors) to see if accuracy is good enough.
- Anthropic API account with billing; the key in the hosting environment settings (never in the code).
- Hosting: the AI call takes 10–30 seconds; check the hosting plan allows functions that long.
- Privacy policy: add that photos of site notes are sent to Anthropic to be read (API data isn't used for training
  by default).
- Only for signed-in firms, with the monthly limit, so a trial can't run up the bill.

## Laser measure straight into the quotation (research)

*Proposed 25 Oct 2026. Research only.*

**The idea.** Designers measure rooms with a laser distance meter. Instead of reading the screen and typing, the
reading goes straight into the size box on the quotation: tap Length, press measure, done. A strong marketing line too.

**What we found (Bosch GLM 50-27 CG, ₹10,499 on Bosch India).** 50 m range, ±1.5 mm, metres or ft/in, Bluetooth Low
Energy, but only for Bosch's own MeasureOn app: no "keyboard mode" (HID) that would type readings into any app, and
Bosch doesn't publish its Bluetooth protocol (hobbyists have decoded the older GLM 50 C / 100 C; the 50-27 CG may be
similar, untested).

**Three kinds of meter, three ways in.**
1. **Keyboard mode (HID)** meters (some Leica DISTO, Hilti and other models): they type into the selected box already,
   no change to the app. Only gap: our size boxes are feet + inches, meters send decimals.
2. **Bluetooth, brand app only** (Bosch GLM, most others): a "Connect laser" button using Web Bluetooth. Works in Chrome
   on Android and laptops, **not on iPhone/iPad** (Safari has no Web Bluetooth). Per brand, unofficial for Bosch (a
   firmware update could break it); Leica's protocol is better documented.
3. **USB only**: not practical on site.

**Cheap first step (any meter).** Let size boxes accept a decimal in metres or feet (2.438 m → 8 ft 0 in), so a reading
copied from any meter or its app is quick to enter.

**Before starting.**
- Ask customers whether they own a laser meter, and which brand/model.
- Buy the most common one and test: keyboard mode, or decode its Bluetooth messages with a BLE scanner (nRF Connect).
- Decide whether Android-only is acceptable (check how many customers quote on iPhone).
