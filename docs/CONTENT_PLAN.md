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
| "Excel vs QuoteRoom" carousel (10-slide framework: hook, example, diagrams, comparisons, CTA) | Carousel, 10 slides 4:5 | **Ready to post** | `carousel-excel-vs-1…10.png` | `tools/ad_video/carousel_excel_vs.py` |
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
`-4-send-and-accept.mp4` (31 s) · `-5-get-paid.mp4` (38 s) · `-6-profit.mp4` (49 s, pop music) · `-7-change-a-quotation.mp4` (72 s, funk) · `-8-track-every-job.mp4` (61 s, tropical) · `-9-your-team.mp4` (63 s, cinematic) · `-10-send-by-email.mp4` (65 s, lo-fi) · `quoteroom-tutorial-full.mp4` (4 min, all five).
Re-record after UI changes: start the "tutorial" preview server on a fresh database, then run
`tools/tutorials/part1_company.py`, `parts2to5.py`, `part6_profit.py`, `part7_revisions.py`, `part8_track_jobs.py`, `part9_team.py`, `part10_email.py` and `make_videos.py` (see each file's docstring).

### Tutorial series: everything the app does (plan, 16 Oct 2026)
Same style as parts 1–5 (phone size, captions, ≤ 90 s each). ✅ = on the website. Record in this order. 🎬 = recorded, not uploaded yet.

| # | Title | What it shows | Screens | Length |
|---|---|---|---|---|
| ✅ | Full walkthrough | Parts 1–5 in one video | – | 4 min |
| ✅ 1 | Your company details | Login, company name, GSTIN, logo, colours | Settings → Company, Appearance | 1 min |
| ✅ 2 | Your rates & materials | Rates per sqft, own materials, fittings price list | Admin → Rates | 33 s |
| ✅ 3 | Your first quotation | Customer, rooms, items in ft/in, fittings, discount | New quotation | 1.5 min |
| ✅ 4 | Send it & get it accepted | Initial / Full PDF, approval link, customer accepts | Quotation page, `/q/` link | 31 s |
| ✅ 5 | Get paid | Payments, GST invoice, reminders, Balances | Quotation page, Balances | 38 s |
| ✅ 6 | **Know your profit** | Enter what each material/fitting costs you → profit & margin on every quotation (before GST), "costs missing" hint → Reports: this year, past years, projected | Admin → Costs, quotation page, Admin → Reports | ~1.5 min |
| ✅ 7 | Change a quotation | Customer asks for a change → edit → Rev 2 with what changed → they change their mind → restore Rev 1 → they accept | Edit, Revisions card | ~1 min |
| 🎬 8 | Track every job | Stages (Pending → Confirmed → Ongoing → Completed, On hold, Cancelled), search, filter by stage, notifications | Quotations list, stage menu, bell | ~45 s |
| 🎬 9 | Your team | Add staff logins, reset a password, give a staff member access to a quotation; one price for the whole team | Admin → Users, Access on a quotation | ~1 min |
| 🎬 10 | Send by email | Set up Gmail (app password), send a test, email a quotation or invoice with the PDF attached | Settings → Email, Email buttons | ~1 min |
| 🎬 11 | Online payments (Razorpay) | Setup guide, API keys, webhook address & secret, Test connection → payment link for an advance → customer pays → recorded automatically with a notification and the new balance | Admin → Payment settings, Payment link | 63 s |
| 🎬 12 | Your quotation PDF | By room or by material; room descriptions (ticked per room); Material Specifications with Insert buttons ({plywood_details} etc.); Payment/Delivery Terms; T&C; Units (ft & in / mm / cm / in, sqft / sq m); the room-wise Initial Quotation that results | Settings → Quotation PDFs, Units, Edit quotation | 81 s |
| 🎬 13 | QuoteRoom on your home screen | Android (⋮ → Add to Home screen) and iPhone (Share → Add to Home Screen); the business's own logo and name on the home screen; opens full screen | Browser menu (drawn mock-ups) | 26 s |

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
**Re-recorded 18 Oct 2026 (re-uploaded and console links updated the same day)** for the new app (plywood, No's, room-by-room Initial Quotation, view/edit access, no signatures):
re-upload Full (4.5 min), 1 (58 s), 2 (45 s), 3 (1 min 51 s), 4 (31 s), 5 (38 s) and 9 (65 s), then update their links and
lengths in the console. Parts 6–8 and 10 were re-rendered only for consistency; their content didn't change.

Upload order: full, 1, 2, 3, 4, 5. Then add each link in the ops console → **Tutorials**
(first time: press **Add the first six tutorials**, paste each YouTube link, Save). New videos later: **Add a tutorial**
on the same page; they appear on www.quote-room.co.in/tutorials within a minute, no deploy needed.

**Demo: quote to accepted** (landscape, laptop; 1 min 17 s) — *QuoteRoom in 1 minute: a full home quotation, accepted online by the customer*
> See QuoteRoom, the quotation app for interior designers and modular furniture firms, in action. A quotation for a whole home (kitchen, master bedroom, guest bedroom and living room) made in minutes on a laptop, with sizes in feet and inches and your own rates. Then a branded PDF, an approval link sent on WhatsApp, and the customer opening it on her phone (no app, no login) and accepting. Back on your side, the quotation is Confirmed with a notification.
>
> 0:00 A new quotation
> 0:10 Kitchen: items with sizes
> 0:28 Master Bedroom, Guest Bedroom, Living Room
> 0:44 Save and the PDF
> 0:51 Send the approval link on WhatsApp
> 0:56 The customer views it and accepts
> 1:08 Confirmed, with a notification
>
> 👉 Free 7-day trial: https://www.quote-room.co.in

Console → Tutorials → **Add a tutorial**: title `QuoteRoom in 1 minute`, length `1 min`, "A full home quotation made on a
laptop, then the customer views it on her phone and accepts it online." Then press **↑ Up** until it is first: the first
video is the big one at the top of the Tutorials page. Its link also goes in the first message to a lead (PRODUCT_GUIDE §7).
Made by `tools/tutorials/demo_quote_to_accepted.py` (landscape layout: `tools/tutorials/landscape.py`).

**Full walkthrough** — *QuoteRoom full walkthrough: from setup to getting paid (4.5 min)*
> Everything you need to start using QuoteRoom, the quotation app for interior designers and modular furniture firms, on your phone.
>
> 0:00 Your company details & logo
> 0:54 Your rates, materials & plywood
> 1:37 Your first quotation
> 3:25 Send it & get it accepted online
> 3:53 Get paid: payments, GST invoice & reminders
>
> Measure on site, send a branded quotation on WhatsApp in minutes, let your customer accept online, then invoice and get paid. One price for your whole team.
> 👉 Free 7-day trial: https://www.quote-room.co.in
> Questions? Message us on WhatsApp from the website.

**Part 1** — *QuoteRoom tutorial 1: add your company details & logo*
> Set up QuoteRoom in about a minute: log in, add your company name, phone, address and GSTIN, then upload your logo and pick your colours. They appear on your app and on every quotation PDF.
> Tip: check your company name and GSTIN carefully, they lock once saved (message us if you need a change).
> 👉 Free 7-day trial: https://www.quote-room.co.in

Instagram Reel caption (cover text: "Set up your quotation app in 1 minute"):
> Your quotations, in your brand ✨ In about a minute: add your company name, phone, address and GSTIN, upload your logo and pick your colours. They show on your app and on every quotation PDF your customer gets.
>
> Part 1 of our QuoteRoom setup series. Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #quoteroom #interiordesignindia #quotation

**Part 2** — *QuoteRoom tutorial 2: set your rates, materials & plywood*
> Set your own rate per sqft for each material and work type, add any material you use (wallpaper, PU, glass…), keep a price list of fittings like Magic Corners and tandem drawers, and add the plywood you offer with its price difference per sqft (e.g. 18mm BWP +₹150) and details. Every new quotation uses your rates.
> 👉 Free 7-day trial: https://www.quote-room.co.in

**Part 3** — *QuoteRoom tutorial 3: make your first quotation*
> Make a complete interior quotation on your phone: add the customer, add rooms, enter each item's length and width, set No's for identical pieces, pick the material and plywood, add fittings from your price list and give a discount. QuoteRoom works out the sqft and the totals for you.
> 👉 Free 7-day trial: https://www.quote-room.co.in

**Part 4** — *QuoteRoom tutorial 4: send it & get it accepted online*
> Share the Initial Quotation (room by room: items with sizes and one amount per room) or the Full Quotation (every rate and amount) as a PDF, or send a link on WhatsApp. Your customer opens it with no app or login, taps Accept, and the job moves to Confirmed.
> 👉 Free 7-day trial: https://www.quote-room.co.in

**Part 5** — *QuoteRoom tutorial 5: payments, GST invoice & reminders*
> Record advances and part payments, turn the confirmed quotation into a GST invoice in one step (CGST + SGST or IGST worked out), send a polite WhatsApp reminder and see everyone who still owes you on the Balances page.
> 👉 Free 7-day trial: https://www.quote-room.co.in

**Part 6** — *QuoteRoom tutorial 6: know your profit on every job*
> Enter what each material and fitting costs you, once. Every quotation then shows your profit and margin (before GST: price before GST minus your costs), and Reports shows work won, collected, invoiced and profit for this financial year, month by month, past years and a projection to 31 March. Only admins see costs and profit: never on PDFs, WhatsApp or the customer's link.
> 👉 Free 7-day trial: https://www.quote-room.co.in

Console → Tutorials → Add a tutorial: title `6 · Know your profit`, length `49 sec`,
"Add your costs once: profit on every job, plus yearly reports." Instagram Reel caption:
> Do you know your profit on every job? 💰 Add what your materials cost you once, and QuoteRoom shows the profit on every quotation, plus your profit for the year. Only you see it. Link in bio for a free 7-day trial.
> #interiordesign #interiordesigner #modularkitchen #interiorbusiness #quoteroom

**Part 7** — *QuoteRoom tutorial 7: change a quotation (revisions & restore)*
> Your customer asks for a change on the approval link, you edit the quotation and it's saved as Rev 2 with exactly what changed. They change their mind? Open Rev 1 and tap Restore: it's back, saved as Rev 3, and nothing is lost. Their link always shows the latest version, ready to accept.
> 👉 Free 7-day trial: https://www.quote-room.co.in

Console → Tutorials → Add a tutorial: title `7 · Change a quotation`, length `1 min`,
"Edit after the customer asks, every version kept, restore an older one." Instagram Reel caption:
> Customer wants the loft removed… then wants it back? 🙃 With QuoteRoom every version of your quotation is kept. Restore an older one in one tap, no re-typing, and they accept it online. Link in bio for a free 7-day trial.
> #interiordesign #interiordesigner #modularkitchen #wardrobedesign #quoteroom

**Part 8** — *QuoteRoom tutorial 8: track every job (stages, search & notifications)*
> See every quotation with its stage: Awaiting confirmation, Confirmed, Ongoing, On hold, Completed or Cancelled. Tap a stage to filter, search by customer name or mobile, move a job along with a note for your team, and see the whole history of each job. The bell shows accepted quotations and change requests as they happen.
> 👉 Free 7-day trial: https://www.quote-room.co.in

Console → Tutorials → Add a tutorial: title `8 · Track every job`, length `1 min`,
"Stages, filters, search and notifications." Instagram Reel caption:
> Which jobs are confirmed, which are on site, which are waiting? 📋 QuoteRoom keeps every job's stage and history in one list, with a note for your team at each step. Link in bio for a free 7-day trial.
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #quoteroom

As a standalone YouTube Short (upload separately; under 3 min, vertical): title *Track every interior job in one place:
confirmed, on site, on hold #Shorts*
> Which jobs are confirmed, which are on site, which are still waiting for the customer's answer? QuoteRoom keeps every quotation's stage in one list: Awaiting confirmation, Confirmed, Ongoing, On hold, Completed or Cancelled.
>
> Tap a stage to filter, search by customer name or mobile, move a job along with a note for your team, and see each job's full history. The bell tells you the moment a customer accepts a quotation or asks for changes.
>
> QuoteRoom is a quotation app for interior designers and furniture makers: measure rooms on your phone, send branded quotations on WhatsApp, and track every job to payment.
>
> 👉 Free 7-day trial: https://www.quote-room.co.in
>
> #interiordesign #interiordesigner #modularkitchen #interiorbusiness #quoteroom #Shorts

Instagram (standalone, cover text "Every job, one list"):
> Which jobs are confirmed? Which are on site? Which customer still hasn't replied? 🤔
>
> QuoteRoom keeps every job's stage in one list: awaiting confirmation, confirmed, ongoing, on hold, completed. Tap a stage to filter, add a note for your team at each step, and get a notification the moment a customer accepts your quotation.
>
> No more scrolling WhatsApp chats to remember where each job stands. Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #smallbusinessindia

**Part 9** — *QuoteRoom tutorial 9: your team (staff logins & sharing jobs)*
> Give everyone in your team their own login: one price, however many people. Add a staff login, set a new password if they forget it, and share a job with them using Access, as Can view or Can edit (only admins can delete). Staff see only the jobs shared with them and the ones they make; your costs, profit, reports and settings stay admin-only.
> 👉 Free 7-day trial: https://www.quote-room.co.in

Console → Tutorials → Add a tutorial: title `9 · Your team`, length `1 min`,
"Staff logins, passwords and sharing a job." Instagram Reel caption:
> Your whole team on QuoteRoom, one price 👷‍♂️ Give your site supervisor his own login, share only the jobs he needs, and keep your costs and profit to yourself. Link in bio for a free 7-day trial.
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #quoteroom

**Part 10** — *QuoteRoom tutorial 10: email quotations & invoices from your own email*
> Set up your email once (Gmail: turn on 2-Step Verification, create an App Password, tap "Use Gmail settings"), send a test, then email quotations and GST invoices straight from QuoteRoom, with the PDF attached and a link your customer can open and accept. Sent from your own address, in your brand. Zoho and Outlook work too.
> 👉 Free 7-day trial: https://www.quote-room.co.in

Console → Tutorials → Add a tutorial: title `10 · Send by email`, length `1 min`,
"Set up Gmail once, then email quotations and invoices." Instagram Reel caption:
> Send your quotation by email, from your own address, PDF attached, with a link to accept online ✉️ Set it up once in QuoteRoom. Link in bio for a free 7-day trial.
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #quoteroom

(Recorded with a practice mail server on the Mac: `tools/tutorials/part10_email.py` docstring. Fictional .example addresses.)

**Part 11** — *QuoteRoom tutorial 11: online payments with Razorpay (payment links that record themselves)*
> Let customers pay you online by UPI, card or net banking. Follow the step-by-step guide in Payment Settings: create a Razorpay account, start in Test mode, paste your API keys, add the webhook address and secret in Razorpay, and tap Test connection. Then type any amount on a quotation (an advance, a stage payment or the full balance) and tap Payment Link. When your customer pays, QuoteRoom records the payment on the quotation by itself, with a notification and the new balance. Switch Razorpay to Live mode when your KYC is approved.
> 👉 Free 7-day trial: https://www.quote-room.co.in

Chapters: 0:00 Online payments · 0:05 Payment Settings & guide · 0:15 API keys & webhook · 0:24 Test connection · 0:27 Payment link for an advance · 0:38 Customer pays · 0:43 Recorded automatically · 0:57 Go live

Console → Tutorials → Add a tutorial: title `11 · Online payments`, length `1 min`,
"Razorpay keys, a payment link, and the payment records itself." Instagram Reel caption:
> Send a payment link, get paid by UPI, and see it recorded on the quotation by itself 💸 No typing payments in, no checking your bank app. QuoteRoom works with Razorpay. Link in bio for a free 7-day trial.
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #quoteroom

(Recorded with Razorpay TEST keys on the local tutorial app; the owner made the test payment; the "paid" webhook was delivered locally by `tools/tutorials/replay_razorpay_webhook.py` because Razorpay can't reach a local app. The app ran with a recording-only sitecustomize that turns off Razorpay's SMS/email for test links. Run the recorder with `RAZORPAY_ACCOUNT_NAME` set so the Razorpay account's name is shown as the fictional business.)

**Part 12** — *QuoteRoom tutorial 12: make the quotation PDF your own (room descriptions, specs, terms & units)*
> Choose what your customer gets: room by room (items with sizes and No's, one amount per room, no rates) or by material. Add your room descriptions once and tick them on each room. Write your Material Specifications, Payment Terms, Delivery Terms and Terms & Conditions, and tap Insert to add details that change per quotation, like the plywood: "Plywood: {plywood_details} for all carcass and shutters" prints the plywood chosen on that quotation. Measure in feet & inches, mm, cm or inches, with rates per sqft or per sq m.
> 👉 Free 7-day trial: https://www.quote-room.co.in

Chapters: 0:00 Quotation PDFs · 0:16 Room descriptions · 0:21 Material Specifications & Insert · 0:34 Payment & Delivery Terms · 0:44 Units · 0:51 Edit a quotation · 1:05 The Initial Quotation

Console → Tutorials → Add a tutorial: title `12 · Your quotation PDF`, length `1 min`,
"Room descriptions, material specs, payment terms and units." Instagram Reel caption:
> Your quotation, your words 📄 Room-by-room amounts, your material specs with the plywood filled in automatically, your payment terms. Set it once in QuoteRoom and every quotation comes out your way. Link in bio for a free 7-day trial.
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #quoteroom


**Part 13** — *QuoteRoom tutorial 13: put QuoteRoom on your home screen (Android & iPhone)*
> Open QuoteRoom in one tap, like an app, with your own logo and name. Android (Chrome): tap the three-dot menu → Add to Home screen (or Install app) → Add. iPhone (Safari): tap Share → Add to Home Screen → Add. It opens full screen, straight to your quotations. No app store, and each person in your team can do it on their own phone.
> 👉 Free 7-day trial: https://www.quote-room.co.in

Console → Tutorials → Add a tutorial: title `13 · On your home screen`, length `30 s`,
"Add QuoteRoom to your home screen on Android and iPhone." Instagram Reel caption:
> Your quotation app, one tap away 📱 Add QuoteRoom to your home screen with your own logo: no app store, works on Android and iPhone. Link in bio for a free 7-day trial.
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #quoteroom

(The browser menus are plain drawn mock-ups, since a web page can't capture the browser's own menus; the icon and name are the app's real ones.)
## 8. Instagram captions for every tutorial (standalone)

Each works on its own (no "part N", no "previous video"). Paste the caption, set the cover text, post as a Reel.
Links in captions aren't clickable on Instagram, so each one says "link in bio". Same hashtags on all, plus one per topic.

**1-minute demo** (laptop + phone) · cover: "Quote to yes in 1 minute"
> A whole home quoted in minutes ⏱️ Kitchen, master bedroom, guest bedroom, living room: every item with its size, your own rates, and the total worked out as you go. Send the link on WhatsApp, and your customer opens it on her phone and taps Accept. No app, no login, no chasing.
>
> See QuoteRoom for yourself: free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #homeinteriors

**Full walkthrough** · cover: "Set up to paid, in 4 minutes"
> Everything in one video 🎬 Add your company and logo, set your rates, make a room-by-room quotation, send it on WhatsApp, get it accepted online, then record payments and issue a GST invoice. That's QuoteRoom, start to finish.
>
> Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #gstinvoice

**1 · Company details & logo** · cover: "Set up your quotation app in 1 minute"
> Your quotations, in your brand ✨ In about a minute: add your company name, phone, address and GSTIN, upload your logo and pick your colours. They show on your app and on every quotation PDF your customer gets.
>
> Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #branding

**2 · Rates, materials & plywood** · cover: "Your rates, set once"
> Every quotation priced your way 💰 Set your rate per sqft for acrylic, laminates, veneer, glass or anything you use. Add the plywood you offer (18mm BWP? +₹150/sqft), and keep a price list of fittings like Magic Corners and tandem drawers. Every new quotation uses them, for everyone in your team.
>
> Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #modularfurniture

**3 · Your first quotation** · cover: "A quotation on your phone"
> Still adding up sqft on a calculator? 📱 Add rooms and items, type the length and width in feet and inches (or mm), pick the material and plywood, add fittings and a discount. QuoteRoom works out every area and the total as you type.
>
> Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #wardrobedesign

**4 · Send it & get it accepted** · cover: "Accepted online. No chasing."
> "Did you see the quotation?" Stop asking ✅ Send a clean PDF in your brand, or a link on WhatsApp. Your customer opens it on their phone, sees every room and the total, and taps Accept. The job turns Confirmed and you get a notification.
>
> Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #customerexperience

**5 · Get paid** · cover: "From quote to paid"
> Who still owes you money? 🧾 Record advances and payments as they come in, issue a proper GST invoice in one tap, and send a polite payment reminder on WhatsApp with your UPI details. Balances shows everyone who owes you, biggest first.
>
> Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #gstinvoice

**6 · Know your profit** · cover: "What do you make on each job?"
> Do you know your margin on every job? 📊 Enter what each material and fitting costs you, once. Every quotation then shows its profit (only to you, never to the customer), and Reports shows your sales, collections and profit for the year.
>
> Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #businessgrowth

**7 · Change a quotation** · cover: "Every version kept"
> "Can we drop the loft?" … "Actually, keep it." 🔄 Edit the quotation, and QuoteRoom keeps every version with exactly what changed. Customer changes their mind again? Restore the earlier one in one tap. No re-typing, no mix-ups.
>
> Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #wardrobedesign

**8 · Track every job** · cover: "Every job, one list"
> Which jobs are confirmed? Which are on site? Which customer still hasn't replied? 🤔 QuoteRoom keeps every job's stage in one list: awaiting confirmation, confirmed, ongoing, on hold, completed. Tap a stage to filter, add a note for your team at each step, and get a notification the moment a customer accepts.
>
> No more scrolling WhatsApp chats to remember where each job stands. Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #smallbusinessindia

**9 · Your team** · cover: "Your whole team, one price"
> One login per person, one price for the whole team 👷 Give your site supervisor his own login, share only the jobs he needs (view or edit), and keep your costs and profit to yourself. Forgot a password? Set a new one in seconds.
>
> Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #teamwork

**10 · Send by email** · cover: "From your own email"
> Some customers want it by email ✉️ Connect your Gmail once, then send quotations and GST invoices from your own address: PDF attached, plus a link they can open and accept.
>
> Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #smallbusiness

**11 · Online payments** · cover: "Paid online. Recorded for you."
> Collect the advance online 💸 Send a payment link, your customer pays by UPI or card, and the payment shows up on the quotation by itself, with a notification and the new balance. No typing payments in, no checking your bank app.
>
> Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #upi

**12 · Your quotation PDF** · cover: "Every quotation, your way"
> Your quotation, your words 📄 Room-by-room amounts with what each room is made of, your material specifications with the plywood filled in automatically, your payment and delivery terms. Measure in feet, mm or cm. Set it once, and every quotation comes out your way.
>
> Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #quotation

**13 · On your home screen** · cover: "Your app, one tap away"
> Your quotation app, with your logo, right on your phone's home screen 📱 Two taps on Android or iPhone, no app store. It opens full screen, straight to your quotations, for everyone in your team.
>
> Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #smallbusinessindia


## 9. Excel vs QuoteRoom carousel (feed, 10 slides)

Slides: 1 hook ("Still making quotations in Excel?", the #VALUE! sheet, 40 min vs 3 min) · 2 the Excel way · 3 the
QuoteRoom way · 4 where the 40 minutes go (bar chart) · 5 after you send it (two flows) · 6 sqft maths · 7 changes &
versions · 8 getting the yes and getting paid · 9 side-by-side ✗/✓ table · 10 "Stop fixing formulas. Start sending
quotes." Files `ad-videos/carousel-excel-vs-1…10.png`, made by `tools/ad_video/carousel_excel_vs.py`.

Caption:
> Still making quotations in Excel? 📊 Same kitchen, same customer: 40 minutes and a #VALUE! error, or 3 minutes and sent on WhatsApp.
>
> Swipe to see where the 40 minutes go, what happens after you send it, and the side-by-side comparison 👉
>
> Save this for your next quote. Free 7-day trial, link in bio 👆
>
> #interiordesign #interiordesigner #interiorbusiness #modularkitchen #interiordesignindia #quoteroom #excel
