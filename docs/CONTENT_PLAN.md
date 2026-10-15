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
| Earlier video ads (measure → quote) | 9:16 / 4:5 / 16:9 with owner's voice | Running in ads | `quoteroom-ad-*-your-voice.mp4` | `tools/ad_video/render_ad.py` |
| Earlier static ads | 4:5 + 9:16 | Running in ads | `static-measure-*.png`, `static-customer-*.png` | `tools/ad_video/static_ads.py` |

Scheduled posts were set up by the owner in Instagram (not by these tools).

---

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
| 5 | "Do you know your profit on this kitchen?" ★ | Quote ₹1.72L → profit card (before GST) → "Only you see this" | Nothing |
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
| 6 | Checklist: "Does your quotation have…?" ✔ logo ✔ room-wise sizes ✔ rates ✔ payment details ✔ GST invoice ✔ online accept | |
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
- **Music:** `tools/ad_video/music.py` composes an upbeat 112 bpm track in code (free to use); reels mix it with loudnorm −16 LUFS.
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
