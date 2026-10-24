# Operations Guide (operator only)

How to run QuoteRoom as a business: set up the platform, start trials, onboard paying customers,
ship updates and handle support. Customers never need this document.

> **Never put real secrets in this file, in the repo, or in chats.** Database URLs (they contain the
> password), `SECRET_KEY`s, `DATA_ENCRYPTION_KEY`s and API keys belong only in Vercel's environment
> variables and your password manager. Keep your customer list (name, subdomain, Vercel project, Neon URLs, admin
> username) in your password manager.
>
> **Placeholders in this guide are in CAPITALS**, e.g. `PASTE_DIRECT_URL_HERE`. Always replace them
> with the real value; never run a command that still contains a placeholder.

---

## 1. How it all fits together

| What | Where | Notes |
|---|---|---|
| Code | GitHub `QuotationsTemplate`, branch `main` | One repo for everything |
| Marketing site + public demo | Vercel project `quotations-template` → `www.quote-room.co.in` | `MARKETING_SITE=1`, `DEMO_MODE=1`, own Neon DB (wiped nightly) |
| Free trials | ONE Vercel project `trials` + ONE Neon database, one schema per trial → `NAME.quote-room.co.in` | `TENANT_MODE=1` |
| Each paying customer | Their own Vercel project + their own Neon database → `NAME.quote-room.co.in` | Same repo, own env vars |
| DNS | GoDaddy → `quote-room.co.in` | One CNAME per trial/customer |

```
 Your Mac (terminal)            Neon (cloud databases)              Vercel (websites)
 python -m flask …  ──direct──▶  trials DB / customer DB  ◀──pooled──  app at NAME.quote-room.co.in
```

- Commands you run on your Mac connect **over the internet to the Neon database** named in
  `DATABASE_URL`. Creating a trial, extending a plan or running migrations changes data **in Neon**.
- Vercel runs the same code from GitHub against the same database, so the website sees those changes
  on the next page load. **No Vercel deploy is needed for data changes.**
- Only `git push` changes the website's code. **Every Vercel project builds from `main`**, so a push
  redeploys the demo, the trials app and every customer.

### Two database URLs per Neon project

| URL | How to recognise it | Where it goes |
|---|---|---|
| **Pooled** | host contains `-pooler` | Vercel → `DATABASE_URL` |
| **Direct** | same host **without** `-pooler` | your Mac, for `python -m flask …` commands |

Where to find them: Neon → project → **Connect** → copy the string. **Connection pooling ON** = pooled,
**OFF** = direct. (Or take the pooled string and delete `-pooler` from the host.) The password is the
same in both.

---

## 2. One-time setup on your Mac

In Terminal:

```bash
cd ~/Documents/Harshith/QuotationTemplate
python3 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
```

The last line must end with **"Successfully installed …"**.

**Every new Terminal window:** go to the folder and activate the venv before any command:

```bash
cd ~/Documents/Harshith/QuotationTemplate
source venv/bin/activate
```

You'll see `(venv)` at the start of the prompt. Always run commands as **`python -m flask …`**
(not just `flask …`): your Mac also has a Homebrew Flask, and `python -m flask` guarantees the
project's own one is used.

### Pointing a command at a database

```bash
export DATABASE_URL="PASTE_DIRECT_URL_HERE"
```

- **Keep the double quotes.** The URL contains `&`, which the terminal otherwise treats as
  "run in background", and the variable silently isn't set.
- Paste the **whole** string copied from Neon (Connect → pooling OFF).
- Check it before running anything (should print `0`):
  ```bash
  echo "$DATABASE_URL" | grep -c "PASTE_"
  ```
- See where it points, with the password hidden (safe to share):
  ```bash
  echo "$DATABASE_URL" | sed -E 's#://([^:]+):[^@]+@#://\1:****@#'
  ```
- When finished: `unset DATABASE_URL`

**Most commands also need that project's encryption key** (the same `DATA_ENCRYPTION_KEY` as in its
Vercel project), so they can read and write the encrypted data:

```bash
export DATA_ENCRYPTION_KEY="PASTE_THAT_PROJECTS_KEY_HERE"
```

Always set both together, for the **same** project, and clear both when finished:
`unset DATABASE_URL DATA_ENCRYPTION_KEY`. (Plan and company-lock commands work without the key.)

Optional, so trial commands print real addresses: `export TENANT_BASE_DOMAIN=quote-room.co.in`

### Generating a SECRET_KEY
A new one for **every** Vercel project; never reuse one:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### Generating a DATA_ENCRYPTION_KEY
Also a new one for **every** Vercel project (demo, trials, each customer). Run inside the venv:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Save it in your password manager **next to that customer's entry** before adding it to Vercel.
**If this key is lost, that customer's data can't be recovered by anyone.** Never change it in Vercel
without following "Rotating an encryption key" (section 3e).

---

## 3. Platform setup (already done; for reference or rebuilding)

### 3a. Domain `quote-room.co.in` → marketing site
1. Vercel → `quotations-template` → **Settings → Domains → Add** → enter only `quote-room.co.in`,
   keep **"Redirect apex domains to www"** ticked (don't also type the www version, as it's added for you).
2. Vercel shows the records. In **GoDaddy → quote-room.co.in → DNS**:
   - **Edit** the existing A record for `@` (often "Parked") → value `216.198.79.1` (or whatever Vercel
     shows). There must be only one A record for `@`; delete extras.
   - **Edit** the existing CNAME `www` → the value Vercel shows (e.g. `xxxx.vercel-dns-017.com`, without the final dot).
   - Make sure **Forwarding** is off for the domain.
3. Vercel → **Refresh** until both show **Valid Configuration**. HTTPS is automatic.

### 3b. Marketing + demo project env vars (`quotations-template`)

| Name | Value |
|---|---|
| `FLASK_ENV` | `production` |
| `SECRET_KEY` | new random value |
| `DATA_ENCRYPTION_KEY` | new key (section 2) |
| `DATABASE_URL` | demo DB **pooled** URL |
| `MARKETING_SITE` | `1` |
| `MARKETING_WHATSAPP` | your number, digits only, e.g. `917675801918` |
| `MARKETING_PRODUCT_NAME` | `QuoteRoom` |
| `MARKETING_LEGAL_NAME`, `MARKETING_CONTACT_EMAIL`, `MARKETING_ADDRESS`, `MARKETING_JURISDICTION` | shown on /privacy and /terms |
| `DEMO_MODE` | `1` |
| `DEMO_PASSWORD` | random value (visitors use the one-click demo, not a password) |
| `CRON_SECRET` | random value (lets the nightly cron reset the demo) |
| `META_PIXEL_ID`, `GOOGLE_ADS_ID`, `GOOGLE_ADS_CONVERSION` | when you start ads (they only load after a visitor accepts the cookie notice) |
| `LEADS_PASSWORD` | a long random password (section 2 "SECRET_KEY" command works); opens `/leads` |

Region: **Settings → Functions → Function Region → Singapore (sin1)**.
Demo database first-time setup (direct URL **and** the demo key exported): `python -m flask db upgrade` then
`python -m flask seed-demo`.

**The demo database is wiped and reloaded every night (~02:00 IST).** Never use it for anything
else, and never set `DEMO_MODE` on a customer project. Manual reset: Vercel → `quotations-template`
→ **Settings → Cron Jobs → Run**.

### 3c. Trials project (`trials`)
1. **Neon:** new project `trials`, region **AWS Asia Pacific (Singapore)**. Save pooled + direct URLs.
2. **Vercel → Add New → Project** → import `QuotationsTemplate`, name it `trials`. Env vars:

   | Name | Value |
   |---|---|
   | `FLASK_ENV` | `production` |
   | `SECRET_KEY` | new random value |
   | `DATA_ENCRYPTION_KEY` | new key (section 2) |
   | `DATABASE_URL` | trials **pooled** URL |
   | `TENANT_MODE` | `1` |
   | `TENANT_BASE_DOMAIN` | `quote-room.co.in` |
   | `SUPPORT_WHATSAPP` | your number, digits only |

   Don't set `MARKETING_SITE`, `DEMO_MODE`, `CRON_SECRET`, `ADMIN_*` or `COMPANY_*` here.
3. Region **Singapore (sin1)**, then deploy.
4. Expected: the project's own `….vercel.app` address shows **"Not found"**; that's correct,
   because it isn't a trial address.
5. **Don't run `python -m flask db upgrade` on the trials database.** Trial tables are created per
   trial by `trial create`.

### 3d. Rotating a database password (do this if a URL ever leaks, e.g. pasted in a chat)
1. Neon → project → **Roles** → `neondb_owner` → **Reset password**.
2. Neon → **Connect** → copy the new **pooled** string → Vercel project → **Settings → Environment
   Variables** → edit `DATABASE_URL` → save → **Deployments → ⋯ → Redeploy**.
3. Save the new direct + pooled strings in your password manager; delete the old ones.

### 3e. Encryption keys

Every project has its own `DATA_ENCRYPTION_KEY` (in its Vercel env vars and your password manager).
It encrypts customer details, amounts, rates and payment secrets in that project's database.
**A database must only ever be used with its own project's key.** Using another project's key
makes that data unreadable until the right key is used.

#### Turning encryption on for projects created before October 2026 (one time)

Do these in order. The app refuses to start without its key, so the key must be in Vercel
**before** the new code is deployed.

**Step 1: install the new library (once, on your Mac).**
```bash
cd ~/Documents/Harshith/QuotationTemplate
source venv/bin/activate
git pull
python -m pip install -r requirements.txt
```

**Step 2: create one key per project.** Run this once for each project (demo, trials, each existing
customer). Each run prints a different key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Save each key in your password manager **next to that project's entry** (e.g. "QuoteRoom demo –
DATA_ENCRYPTION_KEY") before doing anything else.

**Step 3: add each key to its Vercel project.** Vercel → project → **Settings → Environment
Variables** → Key `DATA_ENCRYPTION_KEY`, Value = that project's key, Environment **Production** → Save.
Demo key → `quotations-template`. Trials key → `trials`. Each customer's key → their project.

**Step 4: deploy.** Push the code to `main` (or ask Claude to). Check the sites still open.
They keep working with the old, unencrypted values until step 5.

**Step 5: encrypt the existing data, one database at a time.** Each block sets that project's
direct URL and key, runs the command, then clears both. Paste the real values in place of the
CAPITALS (keep the double quotes).

Demo database:
```bash
export DATABASE_URL="PASTE_DEMO_DIRECT_URL_HERE"
export DATA_ENCRYPTION_KEY="PASTE_DEMO_KEY_HERE"
python -m flask db upgrade && python -m flask bootstrap
unset DATABASE_URL DATA_ENCRYPTION_KEY
```
Expected last lines: `Admin user already exists — skipped.`, `Reference data already present — skipped.`,
`Encryption: encrypted rows in projects (…), payments (…), …`

Trials database (all trials at once):
```bash
export DATABASE_URL="PASTE_TRIALS_DIRECT_URL_HERE"
export DATA_ENCRYPTION_KEY="PASTE_TRIALS_KEY_HERE"
python -m flask trial migrate-all
unset DATABASE_URL DATA_ENCRYPTION_KEY
```
Expected: for each trial a line `→ test (t_test)` followed by `Encryption: encrypted rows in …`
(or `all data already encrypted`), and finally `All trial schemas are up to date.`

Each paying customer (repeat per customer, with **their** URL and key):
```bash
export DATABASE_URL="PASTE_CUSTOMER_DIRECT_URL_HERE"
export DATA_ENCRYPTION_KEY="PASTE_CUSTOMER_KEY_HERE"
python -m flask db upgrade && python -m flask bootstrap
unset DATABASE_URL DATA_ENCRYPTION_KEY
```

**Step 6: check.** Open each site, log in, and open a quotation and the dashboard: everything
should look exactly as before. Running a step 5 block again is safe; it then prints
`Encryption: all data already encrypted.`

If a command prints an error, see the encryption rows in section 10 (Troubleshooting).

#### New projects from now on
Nothing extra beyond the normal setup: section 2 shows how to create the key, and sections 3b,
3c and 6 list `DATA_ENCRYPTION_KEY` with the other env vars.

#### Rotating an encryption key (only if a key may have leaked)
1. Create a new key (step 2 above) and save it in your password manager **without deleting the old one**.
2. In Vercel set `DATA_ENCRYPTION_KEY` to `NEW_KEY,OLD_KEY` (new first, a comma, no spaces) and redeploy.
New data uses the new key, and old data still reads. Keep the old key in the list: existing rows
aren't re-encrypted with the new key automatically yet.

### 3f. Operator console (`ops.quote-room.co.in`)

A private web page to manage trials with buttons: see new trial requests, create a trial from a
request (address, admin login and a ready-to-send WhatsApp message; the company name, city and email from the
request, editable before you press Create, and their phone are filled in as their company details, so their
quotations carry their name from the start, and they can correct the name once in Settings), extend, reset the admin
password, unlock company details and delete. It runs as its **own** Vercel project. Sign-in needs your
password **and** a 6-digit code from an authenticator app. Every action is logged under **Activity**.

**Step 1: move the domain's DNS to Vercel (once).** This lets every new trial address work
automatically. The domain stays registered (and renewed) at GoDaddy; only its DNS moves.
1. In GoDaddy → `quote-room.co.in` → **DNS**, write down any records **you** added (for example a
   Meta verification **TXT** record, or email **MX** records). The A / CNAME records for the website
   don't need copying: Vercel creates those itself.
2. Vercel → **Domains** (top menu, not inside a project) → `quote-room.co.in` → **DNS Records** →
   add the records from step 1 again exactly.
3. On the same Vercel page, note the nameservers it asks for (`ns1.vercel-dns.com`, `ns2.vercel-dns.com`).
4. GoDaddy → `quote-room.co.in` → **DNS → Nameservers → Change Nameservers** → **I'll use my own
   nameservers** → enter both → Save. GoDaddy may warn that its DNS records stop being used: that's expected.
5. Wait until Vercel's Domains page shows the domain using Vercel nameservers (usually under an hour,
   up to 48 h). The sites keep working during the switch.
6. Vercel → `trials` → **Settings → Domains → Add** → `*.quote-room.co.in` → Connect to Production.
   From now on new trials need **no** domain or GoDaddy step. (`www`, the apex domain and `ops` stay on
   their own projects, because a specific address always wins over the wildcard.)

**Step 2: create the console's password and 2FA key (on your Mac, in the venv).**
```bash
python -m flask console-setup
```
Choose a strong password (12+ characters). It prints a **setup key**: in your authenticator app
(Google Authenticator, Microsoft Authenticator, 1Password, …) tap **+ → Enter a setup key**, account
"QuoteRoom console", type the key, time-based. Then type the 6-digit code the app shows to confirm.
It prints two values, `CONSOLE_PASSWORD_HASH` and `CONSOLE_TOTP_SECRET`. Save the setup key and your
password in your password manager (you need the key to set up a new phone).

**Step 3: create the console project.** Vercel → **Add New → Project** → import
`QuotationsTemplate`, name it `console`. Env vars (Production):

| Name | Value |
|---|---|
| `FLASK_ENV` | `production` |
| `CONSOLE_MODE` | `1` |
| `SECRET_KEY` | new random value (section 2) |
| `DATABASE_URL` | **trials** pooled URL (same as the `trials` project) |
| `DATA_ENCRYPTION_KEY` | **trials** key (same as the `trials` project) |
| `TENANT_BASE_DOMAIN` | `quote-room.co.in` |
| `CONSOLE_PASSWORD_HASH`, `CONSOLE_TOTP_SECRET` | from step 2 |
| `LEADS_DATABASE_URL` | **demo** pooled URL (same as `quotations-template`), so trial requests show up |
| `LEADS_DATA_ENCRYPTION_KEY` | **demo** key (same as `quotations-template`) |
| `MARKETING_PRODUCT_NAME` | `QuoteRoom` (used in the welcome message) |
| `CONSOLE_SENDER_NAME` | optional: your first name in follow-up messages (default `Harshith`) |

Don't set `TENANT_MODE`, `MARKETING_SITE` or `DEMO_MODE` here. Region **Singapore (sin1)**. In
**Settings → Functions**, make sure **Max Duration** is at least **30 seconds** (creating a trial
builds its tables). Deploy.

**Step 4: its address.** `console` → **Settings → Domains → Add** → `ops.quote-room.co.in`.
(With Vercel DNS from step 1 there's nothing to do in GoDaddy.) Open https://ops.quote-room.co.in and
sign in. Bookmark it on your phone.

**Security notes**
- 5 wrong sign-ins within 15 minutes lock sign-in for 15 minutes (for everyone, including you).
- Each 6-digit code works once. Sessions last 12 hours.
- Changing `CONSOLE_PASSWORD_HASH` or `CONSOLE_TOTP_SECRET` in Vercel (and redeploying) signs out every
  session: do this if you lose your phone. Run `console-setup` again for new values.
- Check **Activity** now and then: unknown sign-ins or failed attempts from strange IPs mean someone found
  the address. Change the password and 2FA key if so.

### 3g. Paying customers in the console (one-time setup)

Each paying customer gets **their own database and login** inside one shared Neon project called
`customers` (their login can open only their own database), **their own Vercel project** (`qr-NAME`) with
their own keys, and their address `NAME.quote-room.co.in`. The console's **Customers** page creates all of
that with one button, and its **Updates** page updates every database before you ship.

1. **Neon project for customers.** Neon → **New project** → name `customers`, region **AWS Asia Pacific
   (Singapore)**. Open **Connect**, turn **Connection pooling OFF**, and copy the connection string
   (it uses the `neondb_owner` login). Save it in your password manager as "Neon customers admin".
2. **Vercel token.** Vercel → your avatar → **Account Settings → Tokens → Create Token**: name
   `QuoteRoom console`, scope = your team (the one your projects are in), expiration **No expiration**
   (or 1 year, with a calendar reminder). Copy it once; save it in your password manager.
3. **Team ID.** Vercel → the team switcher (top left) → **Settings → General** → copy **Team ID**
   (starts with `team_`).
4. **Vault key** (the console encrypts each customer's database link and keys with it). Create a new key
   with the DATA_ENCRYPTION_KEY command in section 2 and save it in your password manager as
   "QuoteRoom console vault key". Without it the console can't open its customer records (the customers'
   apps keep working).
5. Vercel → the **console** project → **Settings → Environment Variables** (Production) → add:

   | Name | Value |
   |---|---|
   | `CUSTOMERS_ADMIN_DATABASE_URL` | from step 1 (direct, pooling OFF) |
   | `VERCEL_TOKEN` | from step 2 |
   | `VERCEL_TEAM_ID` | from step 3 |
   | `VERCEL_TRIALS_PROJECT` | the trials project's Vercel name, e.g. `quotations-template-sg2v` (lets the console move a trial address that was added to it by hand) |
   | `CONSOLE_VAULT_KEY` | from step 4 |
   | `SUPPORT_WHATSAPP` | your number, digits only (passed on to every customer app) |
   | `VERCEL_GIT_REPO` | `harshith2608/QuotationsTemplate` (optional; this is the default) |

   Also set **Settings → Functions → Max Duration** to **60** seconds. Then **Deployments → ⋯ → Redeploy**.
6. Open the console's **Customers** page: when the yellow "Not set up yet" box is gone, it's ready.

**Only for real paying customers:** upgrade Vercel to **Pro** first (section 6, step 0). Testing with a
made-up customer on Hobby is fine; delete it afterwards.

### 3h. Automatic: self-serve trials, payment in the app, moving to their own database (one-time setup)

How it works once set up:
1. An interior designer or furniture works asks for a trial on the website → **"Set up my app now"** → on the
   console's public page `/start` they confirm their firm name (the address comes from it) and choose a password → their app opens straight away (a
   ready-made trial is renamed for them). "Others" still come to you. You see every new trial on the dashboard,
   linked to the request, with the WhatsApp follow-ups.
2. In their app, the admin taps **Choose a plan** (or **Renew**) → pays ₹4,999 / ₹8,999 by Razorpay → the plan is
   active at once (a trial's paid plan starts when the trial ends) → receipt (not a GST invoice).
3. Razorpay tells the console (webhook) → the console moves the paid trial into **its own database** (with its own
   encryption key) in a few seconds. Same address, same login, the same shared app ("shared hosting"). You see it
   under **Payments** and **Customers**. A daily task (03:00 UTC) catches anything left over.

Setup (do it with Razorpay **test** keys first, then switch to live keys):

1. **Customer databases in the trials Neon project.** Neon → the trials project → **Connect**, connection pooling
   **OFF**, copy the direct URL (`neondb_owner`). Console project → set `CUSTOMERS_ADMIN_DATABASE_URL` to it (this
   replaces the separate `customers` project of section 3g; each customer still gets its own database and login).
2. **Vault key on both apps.** `CONSOLE_VAULT_KEY` (section 3g step 4) must be set on the **console** and on the
   **trials** project too (the same value): the trials app uses it to open each paying customer's database.
   Then set `SHARED_HOSTING=1` on the console: only then does it offer (and use) the shared app for new customers
   and paid trials. Until then "own app" stays the default, as before.
3. **Razorpay keys** (Razorpay Dashboard → **Account & Settings → API Keys**). On the **trials** project **and the
   console** set `PLATFORM_RAZORPAY_KEY_ID` and `PLATFORM_RAZORPAY_KEY_SECRET` (the console uses them for payment links),
   plus on both what the receipt shows:
   `PLATFORM_LEGAL_NAME` (e.g. "QuoteRoom (Harshith Pola)"), `PLATFORM_ADDRESS`, `PLATFORM_EMAIL`, `PLATFORM_PHONE`.
   Prices default to ₹4,999 / ₹8,999 (`PLAN_PRICE_6M`, `PLAN_PRICE_1Y` to change). Without the keys, the plan buttons
   keep opening WhatsApp to you, as before.
4. **Razorpay webhook** (Razorpay → **Account & Settings → Webhooks → Add new webhook**): URL
   `https://ops.quote-room.co.in/billing/razorpay-webhook`, a secret you generate (`python -c "import secrets;
   print(secrets.token_hex(24))"`), events **order.paid** and **payment_link.paid**. Console project → `PLATFORM_RAZORPAY_WEBHOOK_SECRET` = that secret.
   (`AUTO_MOVE_PAID_TRIALS=0` if you'd rather press **Move now** on Payments yourself.)
5. **Self-serve trials.** Generate another secret the same way. Set `SIGNUP_SECRET` to it on the **console** and on the
   **website** project (`quotations-template`). On the website also set `AUTO_TRIALS=1` and
   `SIGNUP_URL=https://ops.quote-room.co.in`. Optional bot check: Cloudflare → **Turnstile → Add site**
   (`ops.quote-room.co.in`, Managed) → console `TURNSTILE_SITE_KEY` and `TURNSTILE_SECRET_KEY`.
   `SPARE_TRIALS` (default 3) = how many ready-made trials to keep.
6. **Daily task.** Console project → `CRON_SECRET` = a third generated secret (Vercel sends it to the daily task).
6b. **Emails from hello@quote-room.co.in** (GoDaddy email; DNS: MX/SPF/DKIM on `secureserver.net`): on the **website**,
   **trials** and **console** projects set `PLATFORM_SMTP_HOST=smtpout.secureserver.net` (or the outgoing server shown in
   the GoDaddy email dashboard), `PLATFORM_SMTP_PORT=465`, `PLATFORM_SMTP_USER=hello@quote-room.co.in`,
   `PLATFORM_SMTP_PASSWORD` (the mailbox password; type it in Vercel only). Optional `OPERATOR_EMAIL` (who gets the
   "Payment:" notes; default hello@). With email set up:
   - the website **emails** the set-up link instead of showing it (proves the email is theirs);
   - every payment sends "Payment received" with the receipt to the business, and a note to you;
   - the daily task emails "trial ends in 2 days / has ended" and "plan ends in 15 / 3 days / has ended", once each,
     with the link to Choose a plan.
   DNS (checked 24 Oct 2026): SPF `include:secureserver.net -all`, DKIM `secureserver1/2._domainkey`, DMARC `p=reject`,
   all in place. Keep DKIM switched on in the email admin. Because DMARC rejects anything not sent through GoDaddy, any
   other service that should send as @quote-room.co.in must be added to SPF first.
7. **Time limits.** On the console **and** the trials project: **Settings → Functions → Max Duration → 60**.
8. Redeploy the console, trials and website projects. Console → dashboard → **Self-serve trials → Make more** once.
9. **Test end to end (test keys):** request a trial on the website as an interior designer → set up the app →
   Choose a plan → pay with Razorpay's test card (`4111 1111 1111 1111`, any future date, any CVV) or test UPI
   (`success@razorpay`) → thank-you page and receipt → within a minute the console's **Payments** shows it and
   **Customers** shows the business on the shared app. Then switch steps 3–4 to **live** keys (and a live-mode webhook).

Vercel **Pro** is needed before the first real payment (section 6, step 0).

---

## 4. Plans: 7-day free trial → 6 or 12 months

Prices: **6 months ₹4,999 · 12 months ₹8,999**, with no GST added (not GST-registered for now; check
with your CA as revenue grows). No auto-renewal, no refunds (the trial is free).

What the app does by itself:
- Trial: "Free trial ends in N days" banner for admins all week.
- Paid: reminder banner for admins in the last 15 days.
- After the end: paid plans get 7 days' grace (full access, red banner for everyone); trials go
  read-only immediately.
- Read-only: sign-in, viewing and PDFs work; nothing can be created or changed. The banner shows the
  **deletion date = end date + 30 days** and that they'll lose access to the website.
- Every banner has a Renew / Subscribe button that opens WhatsApp to you with the customer's
  company, app address and plan filled in.

**Your job:** when a paying customer renews, extend their plan; when a deletion date passes, delete.

Paying customer (their own database, direct URL):
```bash
export DATABASE_URL="PASTE_CUSTOMER_DIRECT_URL_HERE"
python -m flask plan status
python -m flask plan extend 1y        # or 6m. On time → adds to the current end date; late → starts today
unset DATABASE_URL
```
`python -m flask plan set --plan 6m --start 2026-10-05` sets dates explicitly if ever needed.
Trials use `trial extend` instead (section 5).

---

## 5. Free trials

> **Use the operator console** (https://ops.quote-room.co.in, section 3f) for everything in this
> section: new requests, creating, extending and deleting trials are buttons there. The terminal
> commands below still work and are kept for reference.

### Tutorial videos on the website
The website's **Tutorials** page (and its header link) shows the videos listed in the console under
**Tutorials**. They're stored in the demo database, so the console needs `LEADS_DATABASE_URL` (already set).
1. Upload the video to YouTube (Public or Unlisted).
2. Console → **Tutorials** → **Add a tutorial**: title, length, one line on what it shows, the YouTube link.
   Or edit an existing one and paste its link. Tick **Show on the site** → Save.
3. It's on www.quote-room.co.in/tutorials within a minute (no deploy). Use ↑ Up / ↓ Down to change the order:
   the first video is the big one at the top. **Remove** only takes it off the site; it stays on YouTube.
- A video without a link, or with **Show** unticked, isn't shown. No shown videos → no Tutorials page or link.
- The list is marketing-only: it isn't copied into customers' databases.
- While at least one video is on the site, the console's welcome messages (new trial, new customer) include
  "New here? Short setup videos …: www.quote-room.co.in/tutorials".

### New trial requests (check daily)
Every "Start free trial" button on the website opens a short form (name, mobile, business type).
To see who asked:
1. Open **https://www.quote-room.co.in/leads** (bookmark it). Your browser asks to sign in:
   any username, password = `LEADS_PASSWORD` from the `quotations-template` Vercel project.
2. Each request shows when it came in (IST), the name, number, business and which ad or page it
   came from. Tap **WhatsApp** to message them, then start their trial as below.
   **Download CSV** gives you the whole list.
- Serious people may also tap "Skip the wait" and message you on WhatsApp straight away, with
  their name and business already in the message.
- Requests are encrypted, survive the nightly demo reset, and are deleted automatically after 12 months.
- For ads, link to **https://www.quote-room.co.in/free-trial?utm_source=facebook&utm_campaign=CAMPAIGN_NAME**
  so the "Source" column shows which campaign each request came from.

### Start a trial (≈5 minutes)
Pick their name: lowercase letters, numbers, single hyphens, e.g. `acme`.

1. Create it (trials **direct** URL):
   ```bash
   export DATABASE_URL="PASTE_TRIALS_DIRECT_URL_HERE"
   export DATA_ENCRYPTION_KEY="PASTE_TRIALS_KEY_HERE"
   python -m flask trial create acme
   unset DATABASE_URL DATA_ENCRYPTION_KEY
   ```
   It asks you to **choose a password for the trial's `admin` login** (not the database password;
   at least 8 characters). **Nothing shows on screen while typing**; type it, Enter, then again to
   confirm. Success ends with `Trial "acme" is ready. 7-day trial ends …`.
2. **Vercel** → `trials` → **Settings → Domains → Add** → `acme.quote-room.co.in` → Connect to
   Production. To see the CNAME value: if the domain is open in edit mode click **Cancel**, then
   click **"Show DNS configuration"** next to *Invalid Configuration*.
3. **GoDaddy** → `quote-room.co.in` → **DNS → Add New Record** → Type **CNAME**, Name `acme`,
   Value = what Vercel shows (without the final dot). Save.
   (`cname.vercel-dns.com` also works if Vercel shows none.)
4. Vercel → **Refresh** → *Generating SSL Certificate* → **Valid Configuration** (usually 1–10 minutes).
5. Send the customer: `https://acme.quote-room.co.in`, username `admin`, the password. Save all three
   in your password manager.

### See trials, give more time
```bash
export DATABASE_URL="PASTE_TRIALS_DIRECT_URL_HERE"
python -m flask trial list                # every trial: plan, end date, state, deletion date
python -m flask trial extend acme 7d      # e.g. while negotiating
unset DATABASE_URL
```

### Follow up on WhatsApp
Each trial's page in the console (or **WhatsApp** on the dashboard) has a **Message on WhatsApp** card: the
business's name and number from their trial request, a draft picked for where they are (not signed in yet, help with
rates, make a real quotation, quiet for a while, trial ending with the plan prices, trial ended), or your own text.
**Open in WhatsApp** opens your own WhatsApp with the message ready; check it and press send. Nothing is sent by the
console. Suggested rhythm: day 1, day 3, two days before the end, the day it ends.

### Setting up a firm: how they price, and their own starting quotations
Every business makes one choice, **how they price** (Settings → Pricing, also a setup guide step; or on their console
page → Features):
- **By material**: a rate per sqft for each material and work type, sizes on each item, fittings from a price list
  (modular / carpentry firms).
  One-off work (accent wall, pooja civil works, debris removal) is a **Lump sum**: Add item → Lump sum, one amount
  with a description, saved for next time and listed in Admin → Rates → Lump sums.
- **By item**: each item with its own rate, description and unit (wardrobe per sqft, side table per piece, 3D design
  lump sum), printed as a BOQ (turnkey firms). They only see items and rates, not materials or plywood.
  **Finishes** (optional, Admin → Rates → Finishes): when the same item costs more in another finish (laminate base,
  acrylic / veneer / membrane +25%). The ticked items get a Finish choice on the quotation; the rate changes by itself
  and prints as "Wardrobe (Acrylic finish)". The firm can change the % or add finishes there any time.

**Photos on items** (console → their page → Features → **Turn photos on**; off by default): a small "Photo" button
under every item on the quotation form, for a reference image (a sofa, a chair, a wardrobe design). It prints in a
Photo column of the PDF and shows on the quotation page and the customer's link. Needs "Update all" once after the
update that added it.

When a firm shares its old quotations, have them written into a `.json` price list (format at the top of
`app/price_list.py`): how they price, their items and rates (or materials, rates and fittings), one or more starting
quotations (e.g. "2 BHK turnkey") and their notes and payment terms. Upload it with **Load price list** on that firm's
page: it goes into that business only. New Quotation then offers their starting quotations first: every room and item
filled in, they type the sizes and remove what that home doesn't need. Keep the file out of the repository: it is the
firm's business data. Firms can also save any quotation as a starting quotation themselves (Save as template).
The same file (or one with only `"quotations"`) can also bring in quotations they already sent, as real quotations
with every line, unit and rate (the total is checked against their sheet). Loading it again doesn't add them twice. Their
sheets often have no customer mobile number: they add it when they next edit the quotation.

### Trial → paying customer
**Automatic (section 3h):** the admin pays in their app; the console moves them to their own database by itself. Nothing to do but send a thank-you.

**Payment link (section 3h):** on the trial's console page → **Payment link** → plan → **Make payment link** → **Send on
WhatsApp** (opens your WhatsApp with the message) and/or **Send by email**. When they pay, the same happens as above.
If they ask for an invoice before paying: on the payment link's page → **Proforma invoice** → their business name (and
address) → **Download proforma invoice (PDF)**, and send it with the link. It shows the plan, the amount and the link,
and says in plain words that it is not a GST invoice (you're not registered under GST: no GST charged, no GST credit).
Their payment receipt is emailed automatically once they pay.
Renewals: the same card on a paying customer's page. A **new customer without a trial**: Customers → New paying customer
→ **Send a payment link first**: nothing is made until they pay; then their app is made, the receipt is emailed, and the
customer page shows their login once with the WhatsApp welcome message to send.

**With the console (section 3g):** after the payment arrives, **Customers → New paying customer → Convert a
trial** → choose the trial, type the business name (and WhatsApp number), choose the plan → **Create
customer**. It creates their database and app, copies everything from the trial (logins, settings, logo,
quotations), starts the paid plan, and once the first build is ready (about a minute; the page refreshes
itself) moves the address to their new app. Then send them the ready-made WhatsApp message. Delete the
old trial copy a few days later from **Trials → Manage**. If a step fails, the page shows why: fix it and
press **Retry** (it continues where it stopped).

**Without the console** (manual fallback):
1. **Vercel Pro first** (section 6, step 0) if not done yet.
2. Create their **Neon project** and **Vercel project** exactly as in section 6, steps 1–2.
   Skip section 6 step 3: their data comes from the trial.
3. Create the tables in the new database, then copy the trial into it:
   ```bash
   export DATABASE_URL="PASTE_NEW_CUSTOMER_DIRECT_URL_HERE"
   python -m flask db upgrade
   export DATABASE_URL="PASTE_TRIALS_DIRECT_URL_HERE"
   export DATA_ENCRYPTION_KEY="PASTE_TRIALS_KEY_HERE"
   python -m flask trial convert acme --to "PASTE_NEW_CUSTOMER_DIRECT_URL_HERE" --plan 1y   # or 6m
   unset DATABASE_URL DATA_ENCRYPTION_KEY
   ```
   It asks for the **customer project's** `DATA_ENCRYPTION_KEY` (the new one you put in their Vercel
   project; nothing shows while typing). It copies everything (logins, settings, logo, quotations),
   re-encrypting it with the customer's own key, and starts their paid plan from today.
   The trial address immediately stops being served by the trials app.
4. **Vercel:** remove `acme.quote-room.co.in` from `trials` → add it to the customer's project.
   **GoDaddy:** edit the `acme` CNAME to the value the customer's project shows. Same address,
   logins and data for the customer.
5. After you've checked their app works:
   ```bash
   export DATABASE_URL="PASTE_TRIALS_DIRECT_URL_HERE"
   python -m flask trial delete acme
   unset DATABASE_URL
   ```

### Trial didn't convert
After the deletion date shown by `trial list`: run `python -m flask trial delete acme` (trials direct
URL), then remove the domain in Vercel and the CNAME in GoDaddy.

---

## 6. Onboard a paying customer directly (no trial, ≈15 minutes)

> **With the console (section 3g):** **Customers → New paying customer → New (no trial)** → address name,
> business name, WhatsApp number, plan → **Create customer**. The admin password is shown once with a
> ready-to-send WhatsApp message. Step 0 (Vercel Pro) still applies. The manual steps below are the fallback.

### 0. Before the first paying customer: upgrade Vercel to Pro
If the account is still on Hobby, upgrade **before** creating the customer's project
(Vercel → Settings → Billing). Hobby is non-commercial only; one Pro seat covers every project.

### 1. Database (Neon)
New project named after them (e.g. `acme`), region **Singapore**. Save pooled + direct URLs.

### 2. App (Vercel)
**Add New → Project** → import `QuotationsTemplate`, name it `acme`. Env vars:

| Name | Value |
|---|---|
| `FLASK_ENV` | `production` |
| `SECRET_KEY` | new random value |
| `DATA_ENCRYPTION_KEY` | new key (section 2) |
| `DATABASE_URL` | their **pooled** URL |
| `SUPPORT_WHATSAPP` | your number, digits only |

Don't set `MARKETING_SITE`, `DEMO_MODE` or `TENANT_MODE`. Region **Singapore (sin1)**. Deploy.

### 3. Tables, admin login and plan (their direct URL)
```bash
export DATABASE_URL="PASTE_CUSTOMER_DIRECT_URL_HERE"
export DATA_ENCRYPTION_KEY="PASTE_CUSTOMER_KEY_HERE"
python -m flask db upgrade
ADMIN_USERNAME=admin ADMIN_PASSWORD="CHOOSE_A_STRONG_PASSWORD" python -m flask bootstrap
python -m flask plan set --plan 1y        # or 6m
unset DATABASE_URL DATA_ENCRYPTION_KEY
```

### 4. Subdomain
Same as section 5 steps 2–4, but in the customer's own Vercel project.

### 5. Hand over
Send `https://acme.quote-room.co.in`, username `admin`, password. Ask them to fill
**Admin → Settings → Company** (name, GSTIN and logo lock after saving), **Admin → Rates** and the
fittings price list, follow the guides in **Payment Settings** (Razorpay) and **Settings → Email**,
and create staff logins in **Admin → Users**.

---

## 7. Shipping an update

> **With the console:** step 3 below is one button: **Updates → Update all** (demo, every trial and every
> customer). It's safe to run any time. The console uses its own deployed code, so it only knows about a
> database change **after** that change has been merged and deployed. Updates built to cope with that
> (the release notes / commit say "safe to update after deploy", e.g. custom materials) go:
> **merge → push → wait for the deploys → Updates → Update all**. For any other database change, update from
> your Mac on the branch **before** merging (steps below).

1. Work on a `dev` branch and run the tests (in the venv; first time: `pip install -r requirements-dev.txt`):
   ```bash
   python -m pytest tests -q
   ```
   Everything should pass (one skipped trials test is normal). Don't ship with a failure.
2. Check whether the update changes the database:
   ```bash
   git diff --stat main..dev -- migrations/versions/
   ```
   **No output** → just merge `dev` into `main` and push. Done.
3. **If it lists files**, migrate every database **before** merging (migrations only add things, so
   the live code keeps working). Direct URLs, in this order:
   - Demo:
     ```bash
     export DATABASE_URL="PASTE_DEMO_DIRECT_URL_HERE"
     export DATA_ENCRYPTION_KEY="PASTE_DEMO_KEY_HERE"
     python -m flask db upgrade && python -m flask bootstrap && python -m flask db current
     ```
   - Trials (all at once):
     ```bash
     export DATABASE_URL="PASTE_TRIALS_DIRECT_URL_HERE"
     export DATA_ENCRYPTION_KEY="PASTE_TRIALS_KEY_HERE"
     python -m flask trial migrate-all
     ```
   - Each paying customer: same commands as the demo, with their URL and key.
   **Check it worked:** the last command, `flask db current`, prints the database's version, e.g.
   `a7c41e0d9b21 (head)`. **`(head)` at the end means "fully up to date with the code".** If you see
   a code without `(head)`, or nothing at all, the update didn't finish: run `python -m flask db upgrade`
   again and read the error it prints. (The code changes with every database update, so don't
   compare it with this example; only look for `(head)`.) For trials, `migrate-all` does this check
   itself and ends with `All trial schemas are up to date.`

   `bootstrap` only fills empty reference tables and encrypts any leftover plain values; it never
   changes your data. Then `unset DATABASE_URL DATA_ENCRYPTION_KEY`, merge to `main` and push.

**Quote to cash (invoices, reminders, online approval, revisions, costs)** adds six new tables in one
database update (`a9d3e7f1c5b2`) and is *safe to update after deploy*: until **Update all** runs, those
cards and pages stay hidden and everything else works as before. Notes for support:
- Invoices are numbered `PREFIX/2026-27/001` per financial year (April–March); a cancelled invoice keeps its
  number. A quotation with invoices can't be deleted. GST is CGST+SGST when the place of supply is the
  business's state (from its GSTIN), IGST otherwise; no GSTIN on the business means plain invoices without GST.
- Once invoiced, the balance due uses the invoice total (which may include GST).
- Approval links (`/q/<token>`) work without a login, even when the business's plan is read-only.
- Costs & profit are admin-only and never printed or shown to customers.

**Pushes that don't need a build.** Every Vercel project built from this repo (demo, trials, console and
each customer) skips the build when a push only changes `docs/`, `tools/`, `tests/`, `static/ads/`,
`ad-videos/` or `.md` files (`tools/vercel_ignore_build.sh`, set as `ignoreCommand` in `vercel.json`).
Those deployments show as **Canceled** ("Ignored Build Step") in Vercel: that's expected, and the live
site stays on the last real deploy. A **Redeploy** of the same commit (e.g. after changing an
environment variable) always builds.

---

## 8. Support requests

### "Change my company name / GSTIN / logo"
The WhatsApp message includes the company and app address (e.g. `acme.quote-room.co.in`), which
tells you whose database to use. Check it's genuine, then (their direct URL):
```bash
python -m flask company-status
python -m flask company-unlock gstin      # or: name, logo, --all
```
They change it once in **Admin → Settings**; it locks again when they save.

For a **trial**, use the trials direct URL and add `--trial NAME`:
```bash
python -m flask company-status --trial acme
python -m flask company-unlock gstin --trial acme
```

### "I forgot the admin password"
Another admin can reset it in **Admin → Users**. If there's no other admin (their direct URL):
```bash
python -m flask shell
```
```python
from werkzeug.security import generate_password_hash
from app import db
from app.models import User
u = User.query.filter_by(username='admin').first()
u.password_hash = generate_password_hash('NEW_PASSWORD_HERE', method='pbkdf2:sha256')
db.session.commit()
```

### Razorpay payments not being recorded
In their app, **Admin → Payment Settings** should show all three ticks. Usually the webhook secret in
Razorpay doesn't match the one saved in the app, or the webhook URL / event (`payment_link.paid`) is wrong.

---

## 9. Ending a customer

> **With the console:** for an export, open the customer → **Show connection details** (gives the two values
> for step 1). After the deletion date: customer page → **Delete** (removes their app, database and login;
> type `delete NAME` to confirm). Then remove them from your password manager list.
1. Before the deletion date (end + 30 days) they can ask for an export. With their direct URL and
   key (section 2), write readable CSV files (one per table; a raw database dump would be encrypted):
   ```bash
   python -m flask export-data ~/Desktop/acme-export                # trial: add --trial acme
   ```
   Zip and send them securely, then delete the folder.
2. After the deletion date: delete their Vercel project, their Neon project and the GoDaddy CNAME.
3. Remove them from your password manager list.

---

## 10. Troubleshooting

| You see | Cause | Fix |
|---|---|---|
| `pg_config executable not found` during `pip install` | an old database-driver version without a build for your Python | Pull the latest code (`requirements.txt` pins `psycopg2-binary==2.9.13`) and reinstall |
| `ModuleNotFoundError: No module named 'flask_migrate'`, path shows `/opt/homebrew/…` | Homebrew's Flask ran, not the project's | Activate the venv, reinstall requirements, use `python -m flask …` |
| `Error: No such command 'trial'` | same as above, or not in the project folder | `cd ~/Documents/Harshith/QuotationTemplate && source venv/bin/activate` |
| `password authentication failed for user 'neondb_owner'` | wrong/placeholder password in `DATABASE_URL`, or the password was reset | Copy the string again from Neon → Connect; check with the `grep -c "PASTE_"` command |
| `DATABASE_URL` seems unchanged after `export` | missing double quotes (the `&` in the URL) | Wrap the URL in `"…"` |
| Command prints `<TENANT_BASE_DOMAIN>` | that variable isn't set on your Mac | Harmless; it means `quote-room.co.in`. Optional: `export TENANT_BASE_DOMAIN=quote-room.co.in` |
| Vercel domain: *Invalid Configuration* | DNS record missing or wrong | Click "Show DNS configuration", match GoDaddy exactly, Refresh |
| Vercel domain: *Generating SSL Certificate* | normal after DNS is valid | Wait a few minutes |
| Browser: "can't find server" right after adding a domain | your computer cached the old answer | Wait 10–15 minutes or try a private window / phone on mobile data |
| Trials project's `vercel.app` address shows "Not found" | expected: only trial addresses are served | Nothing to fix |
| Vercel log: `Missing required environment variable(s): DATA_ENCRYPTION_KEY` | key not added to that Vercel project | Add it (section 3e), redeploy |
| `DATA_ENCRYPTION_KEY is not a valid key` | typo, or a `SECRET_KEY` pasted instead | Copy the key again from your password manager |
| `This data was encrypted with a different key` | the key you exported belongs to another project | Export the key that matches the `DATABASE_URL` |
| `This data is encrypted but DATA_ENCRYPTION_KEY is not set` | key not exported on your Mac | `export DATA_ENCRYPTION_KEY="…"` for that project |
| `This is the shared trials database … --trial NAME` | a single-business command (company-status, plan, bootstrap, …) run on the trials database | Add `--trial NAME` (see `python -m flask trial list`); for trial dates use `trial extend` |
| `This is the shared trials database: don't run "flask db upgrade" on it` | `db upgrade` pointed at the trials database | Use `python -m flask trial migrate-all` instead |
| Site errors right after a push with a new migration | code deployed before the migration ran | Run the migrations (section 7) now; the site recovers on the next request |

---

## 11. Costs and limits (Vercel limits page, Sept 2026, so recheck occasionally)

| | Hobby (free) | Pro |
|---|---|---|
| Commercial use | **not allowed** | allowed |
| Projects connected to one Git repo | 25 | 150 |
| Domains per project (e.g. trials) | 50 | unlimited |
| Deployments per day (a push redeploys every project) | 100 | 6,000 |

- Plan: upgrade to **Pro on the first customer payment**. One seat covers all projects.
- **Neon** free plan limits the number of projects; upgrade before you run out.
- Past ~100 paying customers, consider moving paying customers into the shared multi-schema app
  as well (one project, one deploy, one migration run).

---

## 12. Environment variable reference
`.env.example` in the repo root lists every variable with comments.
