# Operations Guide (operator only)

How to run QuoteRoom as a business: set up the platform, start trials, onboard paying customers,
ship updates and handle support. Customers never need this document.

> **Never put real secrets in this file, in the repo, or in chats.** Database URLs (they contain the
> password), `SECRET_KEY`s and API keys belong only in Vercel's environment variables and your
> password manager. Keep your customer list (name, subdomain, Vercel project, Neon URLs, admin
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

Optional, so trial commands print real addresses: `export TENANT_BASE_DOMAIN=quote-room.co.in`

### Generating a SECRET_KEY
A new one for **every** Vercel project; never reuse one:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

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
| `DATABASE_URL` | demo DB **pooled** URL |
| `MARKETING_SITE` | `1` |
| `MARKETING_WHATSAPP` | your number, digits only, e.g. `917675801918` |
| `MARKETING_PRODUCT_NAME` | `QuoteRoom` |
| `MARKETING_LEGAL_NAME`, `MARKETING_CONTACT_EMAIL`, `MARKETING_ADDRESS`, `MARKETING_JURISDICTION` | shown on /privacy and /terms |
| `DEMO_MODE` | `1` |
| `DEMO_PASSWORD` | random value (visitors use the one-click demo, not a password) |
| `CRON_SECRET` | random value (lets the nightly cron reset the demo) |
| `META_PIXEL_ID`, `GOOGLE_ADS_ID`, `GOOGLE_ADS_CONVERSION` | when you start ads |

Region: **Settings → Functions → Function Region → Singapore (sin1)**.
Demo database first-time setup (direct URL): `python -m flask db upgrade` then `python -m flask seed-demo`.

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

---

## 4. Plans: 7-day free trial → 6 or 12 months

Prices: **6 months ₹7,999 · 12 months ₹13,999**, with no GST added (not GST-registered for now; check
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

### Start a trial (≈5 minutes)
Pick their name: lowercase letters, numbers, single hyphens, e.g. `acme`.

1. Create it (trials **direct** URL):
   ```bash
   export DATABASE_URL="PASTE_TRIALS_DIRECT_URL_HERE"
   python -m flask trial create acme
   unset DATABASE_URL
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

### Trial → paying customer
1. **Vercel Pro first** (section 6, step 0) if not done yet.
2. Create their **Neon project** and **Vercel project** exactly as in section 6, steps 1–2.
   Skip section 6 step 3: their data comes from the trial.
3. Create the tables in the new database, then copy the trial into it:
   ```bash
   export DATABASE_URL="PASTE_NEW_CUSTOMER_DIRECT_URL_HERE"
   python -m flask db upgrade
   export DATABASE_URL="PASTE_TRIALS_DIRECT_URL_HERE"
   python -m flask trial convert acme --to "PASTE_NEW_CUSTOMER_DIRECT_URL_HERE" --plan 1y   # or 6m
   unset DATABASE_URL
   ```
   It copies everything (logins, settings, logo, quotations) and starts their paid plan from today.
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
| `DATABASE_URL` | their **pooled** URL |
| `SUPPORT_WHATSAPP` | your number, digits only |

Don't set `MARKETING_SITE`, `DEMO_MODE` or `TENANT_MODE`. Region **Singapore (sin1)**. Deploy.

### 3. Tables, admin login and plan (their direct URL)
```bash
export DATABASE_URL="PASTE_CUSTOMER_DIRECT_URL_HERE"
python -m flask db upgrade
ADMIN_USERNAME=admin ADMIN_PASSWORD="CHOOSE_A_STRONG_PASSWORD" python -m flask bootstrap
python -m flask plan set --plan 1y        # or 6m
unset DATABASE_URL
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

1. Work on a `dev` branch; test locally.
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
     python -m flask db upgrade && python -m flask bootstrap && python -m flask db current
     ```
   - Trials (all at once):
     ```bash
     export DATABASE_URL="PASTE_TRIALS_DIRECT_URL_HERE"
     python -m flask trial migrate-all
     ```
   - Each paying customer: same three commands as the demo, with their URL.
   `flask db current` should end with `(head)`. `bootstrap` only fills empty reference tables and
   never changes existing data. Then `unset DATABASE_URL`, merge to `main` and push.

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
1. Before the deletion date (end + 30 days) they can ask for an export: Neon → their project →
   backup/download, or `pg_dump "PASTE_DIRECT_URL_HERE" > acme.sql`.
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
