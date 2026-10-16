# QuoteRoom — Content & Ads Plan

Everything about our Instagram/Facebook content and Meta ads in one place: what's done, what's scheduled,
every caption, the ideas still to make, how to (re)generate the files, and what we learned from the ads.
For product facts, prices and sales scripts see `docs/PRODUCT_GUIDE.md` (the source of truth).

---

## 1. Status at a glance (as of 15–16 Oct 2026)

| Piece | Format | Status | Files (in `ad-videos/`, git-ignored) | Generator |
|---|---|---|---|---|
| "5 reasons interior jobs are lost" | Carousel, 7 slides 4:5 | **Posted** on Instagram (15 Oct) | `carousel-lost-jobs-1…7.png` | `tools/ad_video/carousel_lost_jobs.py` |
| "Same job. Same price. Very different impression." | Single image 4:5 | **Scheduled** (one per day from 16 Oct, 11 AM IST) | `post-before-after.png` | `tools/ad_video/profile_posts.py` |
| "What your customer receives" | Carousel, 6 slides 4:5 | **Scheduled** | `carousel-customer-sees-1…6.png` | `tools/ad_video/profile_posts.py` |
| "One price. Your whole team." | Single image 4:5 | **Scheduled** | `post-one-price.png` | `tools/ad_video/profile_posts.py` |
| "From tape measure to GST invoice" | Reel 28 s, 9:16 + 4:5, music | **Ready to post** | `reel-tape-to-invoice-9x16.mp4`, `-4x5.mp4`, `-frames.png` | `tools/ad_video/reel_tape_to_invoice.py` (opener: `tape_opener.py`) |
| "Excel vs QuoteRoom" (same quote, two ways) | Reel 21 s, 9:16 + 4:5, music | **Ready to post** | `reel-excel-vs-9x16.mp4`, `-4x5.mp4`, `-frames.png` | `tools/ad_video/reel_excel_vs.py` |
| "Stop chasing payments" | Reel 21 s, 9:16 only, music | **Ready to post** | `reel-payments-9x16.mp4`, `-frames.png` | `tools/ad_video/reel_payments.py` |
| "Do you know your profit?" | Reel 22 s, 9:16, music | **Ready to post** | `reel-profit-9x16.mp4`, `-frames.png` | `tools/ad_video/reel_profit.py` |
| "Does your quotation have all 6?" | Single image 4:5 | **Ready to post** | `post-checklist.png` | `tools/ad_video/profile_posts.py` |
| Earlier video ads (measure → quote) | 9:16 / 4:5 / 16:9 with owner's voice | Running in ads | `quoteroom-ad-*-your-voice.mp4` | `tools/ad_video/render_ad.py` |
| Earlier static ads | 4:5 + 9:16 | Running in ads | `static-measure-*.png`, `static-customer-*.png` | `tools/ad_video/static_ads.py` |

Scheduled posts were set up by the owner in Instagram (not by these tools).

---

### Customer tutorials (for trial customers, phone size, captions + lo-fi music)
Files in `ad-videos/tutorials/`, recorded from the real app (fictional "Sharma Interiors", fresh database):
`quoteroom-tutorial-1-company.mp4` (61 s) · `-2-rates.mp4` (33 s) · `-3-first-quotation.mp4` (94 s) ·
`-4-send-and-accept.mp4` (31 s) · `-5-get-paid.mp4` (38 s) · `quoteroom-tutorial-full.mp4` (4 min, all five).
Re-record after UI changes: start the "tutorial" preview server on a fresh database, then run
`tools/tutorials/part1_company.py`, `parts2to5.py` and `make_videos.py` (see each file's docstring).

### Tutorial series: everything the app does (plan, 16 Oct 2026)
Same style as parts 1–5 (phone size, captions, ≤ 90 s each). ✅ = on the website. Record in this order.

| # | Title | What it shows | Screens | Length |
|---|---|---|---|---|
| ✅ | Full walkthrough | Parts 1–5 in one video | – | 4 min |
| ✅ 1 | Your company details | Login, company name, GSTIN, logo, colours | Settings → Company, Appearance | 1 min |
| ✅ 2 | Your rates & materials | Rates per sqft, own materials, fittings price list | Admin → Rates | 33 s |
| ✅ 3 | Your first quotation | Customer, rooms, items in ft/in, fittings, discount | New quotation | 1.5 min |
| ✅ 4 | Send it & get it accepted | Initial / Full PDF, approval link, customer accepts | Quotation page, `/q/` link | 31 s |
| ✅ 5 | Get paid | Payments, GST invoice, reminders, Balances | Quotation page, Balances | 38 s |
| 6 | **Know your profit** | Enter what each material/fitting costs you → profit & margin on every quotation (before GST), "costs missing" hint → Reports: this year, past years, projected | Admin → Costs, quotation page, Admin → Reports | ~1.5 min |
| 7 | Change a quotation | Edit after the customer asks, Rev 2 with what changed, send the new link, customer accepts the new version | Edit, Revisions card | ~1 min |
| 8 | Track every job | Stages (Pending → Confirmed → Ongoing → Completed, On hold, Cancelled), search, filter by stage, notifications | Quotations list, stage menu, bell | ~45 s |
| 9 | Your team | Add staff logins, reset a password, give a staff member access to a quotation; one price for the whole team | Admin → Users, Access on a quotation | ~1 min |
| 10 | Send by email | Set up Gmail (app password), send a test, email a quotation or invoice with the PDF attached | Settings → Email, Email buttons | ~1 min |
| 11 | Online payments (Razorpay) | Test mode keys, webhook, send a payment link, payment records itself | Admin → Payment settings, Payment link | ~1.5 min |
| 12 | Your PDFs & invoice settings | Terms & conditions and notes on quotations; invoice prefix/numbering, GST or not, HSN, room-by-room or summary | Settings → Quotation PDFs, Invoices | ~1 min |
| 13 | QuoteRoom on your home screen | Add to home screen on Android & iPhone for one-tap access | Browser menu | ~20 s |

Later: a second "full walkthrough" for 6–9 ("Run your business"), and short Reels cut from 6, 7 and 11.

## 2. Captions & ad copy (ready to paste)

Use **"Link in bio"** for organic posts. If a post is later used as an ad, swap that line for
**"Try it free: quote-room.co.in"** (the caption becomes the ad's main text).

**5 reasons interior jobs are lost** (carousel)
> Interior designers: most jobs aren't lost on price. They're lost to a late quote, a wrong total, or no follow-up. Swipe to see all 5 👉
>
> QuoteRoom lets you measure on site, send a branded quotation in minutes, and get customers to accept online. One price for your whole team.
>
> Try it free for 7 days: quote-room.co.in
>
> #interiordesigner #interiordesign #modularkitchen #wardrobe #interiordesignbusiness #quotation

As an ad: Headline "Stop losing interior jobs" · Description "Free 7-day trial · No payment to start" · CTA Sign Up ·
link `https://www.quote-room.co.in/free-trial?utm_source=facebook&utm_campaign=carousel-lost-jobs`
(Instagram post as ad: `utm_source=instagram`). Turn off "show best-performing cards first".

**Before / after**
> Your customer judges your work by your quotation before they ever see your work. Same job, same price. Which one would you trust? 👇
> QuoteRoom turns your measurements into a branded quotation in minutes. Link in bio.
> #interiordesign #interiordesigner #quotation #wardrobedesign

**What your customer receives** (carousel)
> From the first quote to the final GST invoice, everything your customer receives carries your logo. Swipe to see all four steps 👉
> Free 7-day trial, link in bio.
> #interiordesigner #modularfurniture #gstinvoice #interiordesignindia

**One price. Your whole team.**
> One price for your whole team. No per-user fees, no setup fee, your own brand. ₹8,999 a year, about ₹750 a month, with unlimited staff and quotations.
> Try QuoteRoom free for 7 days. Link in bio.
> #interiordesigner #interiordesignbusiness #modularkitchen #smallbusinessindia

**From tape measure to GST invoice** (reel)
> From tape measure to GST invoice, in one app. 📏 → 📄 → ✅ → 🧾
> Measure on site, send a branded quote on WhatsApp, let your customer accept online, then invoice and get paid.
> One price for your whole team. Free 7-day trial, link in bio.
> #interiordesigner #interiordesign #modularkitchen #wardrobe #interiordesignbusiness #smallbusinessindia

**Excel vs QuoteRoom** (reel)
> Same quote. Two ways. ⏱ 40 minutes of formulas, #VALUE! errors and 8.6 instead of 8 ft 6 in… or 3 minutes and it's sent.
> QuoteRoom works out the sqft and totals, makes a branded PDF and sends it on WhatsApp. Your customer accepts online.
> Free 7-day trial, link in bio.
> #interiordesigner #interiordesign #excel #modularkitchen #interiordesignbusiness #smallbusinessindia

**Stop chasing payments** (reel)
> Who still owes you money? If the answer is in a notebook, bank SMS and old WhatsApp chats… 📒
> QuoteRoom keeps every payment against its job and shows every balance due in one list. One tap sends the customer the amount, your UPI and a payment link, and online payments update the balance by themselves.
> Stop chasing. Start collecting. Free 7-day trial, link in bio.
> #interiordesigner #interiordesignbusiness #smallbusinessindia #payments #modularkitchen

**Do you know your profit?** (reel)
> You know the quote. Do you know what you actually make on it? 🤔
> Enter what your materials and fittings cost you, once. Every quotation then shows its profit and margin, and Reports show the whole year. Only you see it, never your staff or customers.
> Free 7-day trial, link in bio.
> #interiordesigner #interiordesignbusiness #smallbusinessindia #profit #modularkitchen

**Does your quotation have all 6?** (post)
> Save this and check your next quotation 🔖 Logo, room-by-room sizes, your rates, payment details, a GST invoice and a link to accept online.
> QuoteRoom gives you all 6 on every quote. Free 7-day trial, link in bio.
> #interiordesigner #interiordesign #quotation #modularkitchen #interiordesignbusiness

**Suggested posting order (from 16 Oct):** 16 Oct before/after (11 AM, scheduled) · 17 Oct customer-receives carousel (11 AM, scheduled)
+ tape-to-invoice reel (7 PM) · 18 Oct one-price (11 AM, scheduled) · 19 Oct Excel reel · 21 Oct payments reel ·
22 Oct checklist post · 23 Oct profit reel.

Reel tips: cover frame ≈ 4 s (the "51 sqft" chip); keep the built-in music (timed to scene changes); post on a day
without a scheduled image post.

---

## 3. Instagram profile setup

- **Bio:** "Quotation app for interior designers & furniture firms · Measure on site → branded quote on WhatsApp in minutes · 7-day free trial 👇"
- **Bio link:** `quote-room.co.in/free-trial`
- **Highlights:** "How it works" and "Pricing" (use slides from the posts).
- **Cadence:** a post every 1–2 days; reels get the most reach on a new profile.
- **Engagement:** reply to every comment in the first hour; share each post to Stories with a **Link sticker** to the free-trial page (posts have no clickable link).
- The Instagram account is a professional account connected to the **Quote-Room** business portfolio (needed to use posts as ads).

---

## 4. Ideas backlog (not made yet)

Every idea speaks to the **business owner** (interior designer / modular furniture firm), not homeowners.
★ features (invoices, approval, reminders, revisions, profit, reports, email) are live since 15 Oct.

### Reels
| # | Idea | Hook / content | Needs from owner |
|---|---|---|---|
| 1 | Quote before you leave the site | "Your competitor sends the quote tomorrow. You send it before you leave." Measure → total → WhatsApp → sent | Best with a 5-sec real clip of measuring at a site (or reuse the animated tape opener) |
| 2 | ~~Excel vs QuoteRoom~~ | **Done** (see section 1) | — |
| 3 | "The customer accepted while I was driving" ★ | Approval link → customer taps Accept → "Quotation accepted" notification → Confirmed | Nothing, or record 2–3 voice lines |
| 4 | ~~Stop chasing payments~~ | **Done** (see section 1) | — |
| 5 | ~~Do you know your profit?~~ | **Done** (see section 1) | — |
| 6 | Your brand, not ours | Same app switching logos/colours → branded PDF → `yourname.quote-room.co.in` | Nothing |
| 7 | ~~Tape measure to GST invoice~~ | **Done** (see section 1) | — |
| 8 | Founder talking-head (20 s) | "I built QuoteRoom because interior quotes are still made in Excel and notebooks…" | Owner films it on a phone; we add captions, screens, music |

### Posts / carousels
| # | Idea | Notes |
|---|---|---|
| 1 | ~~5 reasons jobs are lost~~ | **Done** |
| 2 | ~~What your customer sees~~ | **Done** ("What your customer receives") |
| 3 | ~~Price comparison~~ | **Done** ("One price. Your whole team.") — names no competitors |
| 4 | Big number: "₹750/month · unlimited staff · your own brand · GST invoices" | Simple, bold |
| 5 | ~~Before/after (paper vs PDF)~~ | **Done** |
| 6 | ~~Checklist "Does your quotation have all 6?"~~ | **Done** |
| 7 | Testimonial | Only with a real customer's permission — never invent one |
| 8 | Tip carousel: "How to price a wardrobe per sqft" | Educational (box vs frame work, laminate vs acrylic, hardware); last slide "Do this automatically in QuoteRoom" |

**Suggested next:** reel 3 or 4 (music only, or with the owner's voice), then post 6 (checklist).

---

## 5. How the files are made (for regenerating or editing)

- **Reels: 9:16 only** from now on (owner's preference). Older reels also have a 4:5 version.
- **Scratch environment:** the temp folder is cleaned periodically; if imports fail, recreate a venv with
  `pip install pillow numpy imageio-ffmpeg pymupdf` (plus the app's requirements for screenshots).
- **Run any generator** from the repo with the scratch venv that has Pillow/numpy/imageio-ffmpeg, e.g.
  `python tools/ad_video/reel_tape_to_invoice.py` (add `stills` to get a frame sheet first). Outputs go to `ad-videos/` (git-ignored).
- **Style:** pine-green gradient background, tape-yellow accents, Avenir Next; helpers in `static_ads.py`
  (background, phone mockup, cards, pills, footer CTA "Start your free 7-day trial").
- **Missing glyphs:** Avenir has no ₹, → or ✓. `carousel_lost_jobs.py` (`rich_text`, `rich_pill`) draws those from
  SF (₹) and Arial Unicode (→, ✓). Use these helpers for any text containing them.
- **Music:** `tools/ad_video/music.py` composes tracks in code (free to use), in five styles so reels don't all sound
  the same: `pop` (tape-to-invoice), `funk` (Excel vs QuoteRoom), `tropical` (payments), `cinematic` (profit), and
  `lofi` (unused, for the next reel). Pick a style no recent reel used. Reels mix it with loudnorm −16 LUFS.
- **Screens:** real app screenshots of a fictional business, **Nest & Grain Interiors** (Hyderabad, fictional Telangana GSTIN),
  stored in `static/ads/` (01–08: list, add item, stage, room totals, initial PDF, full PDF, approval accepted, GST invoice).
  New screenshots come from a local app started with the "ad-shots" preview config (demo data renamed to Nest & Grain).
  Never use real customer data.
- **Voice:** best results come from the owner's own recording (phone voice memo), cut to the scenes in `render_ad.py`.
  Synthetic voices sounded flat.
- **Can't do:** film real people or real sites, or invent testimonials. Real clips are filmed by the owner and composited in.

---

## 6. Meta ads — setup and lessons

- **Account:** ad account 27345396725076969 (Quote-Room business), campaign **"QuoteRoom Campaign"**, ₹500/day
  campaign budget. Ad sets: **Feeds** and **Reels & Stories** (active), "AdSet 1" (Warangal, paused).
- **Problem found (15 Oct):** 34 of the first 35 leads came from **Audience Network** (in-app/game placements,
  ~17% "click" rate = accidental/rewarded taps) → random people filling the form.
- **Fixed (15 Oct):** both active ad sets now
  - show only on **Facebook + Instagram** (feeds; stories/reels), no Audience Network
  - **Advantage+ audience off**; age **24–55**; India
  - targeting by **job title/employer** only (Interior Designer, Interior Designer/Owner, Interior Design Consultant,
    Furniture Designer, Kitchen Designer, Architect, …); removed design-student "education majors" and "Modern furniture"
  - Meta keeps "detailed targeting expansion" on for lead campaigns (can't be switched off)
- **Website tracking:** the Meta **Lead** event fires only for trial requests with business type *Interior designer*
  or *Furniture works* (value ₹1,000, INR); "Others" send **LeadOther**, so the ads learn from real businesses.
- **Expect:** fewer leads at ₹200–400 each instead of ₹46–74, but real businesses. Don't edit ad sets for 3–5 days after a change (learning phase).
- **Budget questions:** a ₹500 daily budget can spend up to ₹875 on a given day but never more than 7× in a week; Meta's
  charges add **18% GST** on top of ad spend.
- **Adding new ads:** prefer adding to the existing ad sets. Adding an ad can restart learning, so batch new creatives.
- **Using an Instagram post as an ad:** Ads Manager → ad set → Create ad → *Use existing post* (not the Boost button,
  which ignores our targeting and Lead tracking).
- Review results ~5 days after each change: check trial requests in the console (business type, company name).

---

## 7. YouTube: tutorial titles & descriptions

Playlist: **QuoteRoom tutorials**. Audience: not made for kids. Tags (all): `interior design quotation, quotation app,
interior designer software, modular kitchen quotation, wardrobe quotation, GST invoice, QuoteRoom`.
Upload order: full, 1, 2, 3, 4, 5. Then add each link in the ops console → **Tutorials**
(first time: press **Add the first six tutorials**, paste each YouTube link, Save). New videos later: **Add a tutorial**
on the same page; they appear on www.quote-room.co.in/tutorials within a minute, no deploy needed.

**Full walkthrough** — *QuoteRoom full walkthrough: from setup to getting paid (4 min)*
> Everything you need to start using QuoteRoom, the quotation app for interior designers and modular furniture firms, on your phone.
>
> 0:00 Your company details & logo
> 0:59 Your rates & materials
> 1:29 Your first quotation
> 3:01 Send it & get it accepted online
> 3:29 Get paid: payments, GST invoice & reminders
>
> Measure on site, send a branded quotation on WhatsApp in minutes, let your customer accept online, then invoice and get paid. One price for your whole team.
> 👉 Free 7-day trial: https://www.quote-room.co.in
> Questions? Message us on WhatsApp from the website.

**Part 1** — *QuoteRoom tutorial 1: add your company details & logo*
> Set up QuoteRoom in about a minute: log in, add your company name, phone, address and GSTIN, then upload your logo and pick your colours. They appear on your app and on every quotation PDF.
> Tip: check your company name and GSTIN carefully, they lock once saved (message us if you need a change).
> 👉 Free 7-day trial: https://www.quote-room.co.in

**Part 2** — *QuoteRoom tutorial 2: set your rates & materials*
> Set your own rate per sqft for each material and work type, add any material you use (wallpaper, PU, glass…) and keep a price list of fittings like Magic Corners and tandem drawers. Every new quotation uses your rates.
> 👉 Free 7-day trial: https://www.quote-room.co.in

**Part 3** — *QuoteRoom tutorial 3: make your first quotation*
> Make a complete interior quotation on your phone: add the customer, add rooms, enter each item's length and width in feet and inches, pick the material, add fittings from your price list and give a discount. QuoteRoom works out the sqft and the totals for you.
> 👉 Free 7-day trial: https://www.quote-room.co.in

**Part 4** — *QuoteRoom tutorial 4: send it & get it accepted online*
> Share the Initial Quotation (amounts by material) or the Full Quotation (every room and size) as a PDF, or send a link on WhatsApp. Your customer opens it with no app or login, taps Accept, and the job moves to Confirmed.
> 👉 Free 7-day trial: https://www.quote-room.co.in

**Part 5** — *QuoteRoom tutorial 5: payments, GST invoice & reminders*
> Record advances and part payments, turn the confirmed quotation into a GST invoice in one step (CGST + SGST or IGST worked out), send a polite WhatsApp reminder and see everyone who still owes you on the Balances page.
> 👉 Free 7-day trial: https://www.quote-room.co.in
