# Operations Guide (operator only)

How to run QuoteRoom as a business: onboard customers, ship updates, handle support requests.
Customers never need this document.

> **Never put real secrets in this file or anywhere in the repo.** Database URLs, passwords,
> `SECRET_KEY`s and API keys belong in Vercel's environment variables and your password manager.
> Keep your customer list (name, subdomain, Neon URL, admin username) in your password manager.

---

## How it's set up

| What | Where | Notes |
|---|---|---|
| Code | GitHub `QuotationsTemplate`, branch `main` | One repo for everyone |
| Marketing site + public demo | Vercel project `quotations-template` → `www.quote-room.co.in` | `MARKETING_SITE=1`, `DEMO_MODE=1` |
| Each customer | Their own Vercel project + their own Neon database → `<name>.quote-room.co.in` | Same repo, separate env vars |
| DNS | GoDaddy → `quote-room.co.in` | One CNAME per customer |

**Every Vercel project builds from `main`.** Pushing to `main` redeploys the demo and every customer.

---

## One-time setup on your Mac

```bash
cd QuotationsTemplate
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

Run every `flask …` command below from this folder with the venv active.

---

## Onboard a new customer (≈15 minutes)

Pick a short subdomain name for them, e.g. `acme`.

### 0. Before the first paying customer: upgrade Vercel to Pro
If the account is still on the Hobby plan, upgrade it **before** creating the customer's project
(Vercel → Settings → Billing). Hobby is non-commercial only, and a paying customer's app must not
depend on it. One Pro seat covers every project in the account. Only needed once.

### 1. Database (Neon)
1. Neon → **New Project** → name `acme`, region **AWS Asia Pacific (Singapore)**.
2. Copy two connection strings:
   - **Pooled** (host contains `-pooler`): for Vercel's `DATABASE_URL`
   - **Direct** (same host without `-pooler`): for running migrations from your Mac
3. Save both in your password manager under the customer's name.

### 2. App (Vercel)
1. Vercel → **Add New → Project** → import `QuotationsTemplate`. Name it `acme`.
2. **Environment Variables** before the first deploy:

   | Name | Value |
   |---|---|
   | `FLASK_ENV` | `production` |
   | `SECRET_KEY` | new random value (see below) |
   | `DATABASE_URL` | the **pooled** Neon string |
   | `SUPPORT_WHATSAPP` | your number, e.g. `919876543210` |

   Optional starting branding (the customer can change these later): `COMPANY_NAME`, `BRAND_PRIMARY`, `BRAND_ACCENT`.
   Do **not** set `MARKETING_SITE` or `DEMO_MODE` on customer projects.

   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
3. **Settings → Functions → Function Region → Singapore (sin1)**.
4. Deploy.

### 3. Create their tables and admin login (from your Mac, using the **direct** URL)

```bash
export DATABASE_URL="<their-direct-neon-url>"
flask db upgrade
ADMIN_USERNAME=admin ADMIN_PASSWORD="<strong-password-for-them>" flask bootstrap
unset DATABASE_URL
```

### 4. Subdomain
1. Vercel project `acme` → **Settings → Domains** → add `acme.quote-room.co.in`.
2. GoDaddy → `quote-room.co.in` → **DNS** → add a **CNAME**: Name `acme`, Value = what Vercel shows.
3. Wait for **Valid Configuration** in Vercel.

### 5. Hand over
Send the customer: `https://acme.quote-room.co.in`, username `admin`, the password. Ask them to:
- fill **Admin → Settings → Company** (name, GSTIN, logo lock after saving)
- set **Admin → Rates** and the fittings price list
- follow the guides in **Payment Settings** (Razorpay) and **Settings → Email**
- create staff logins under **Admin → Users**

Record the customer in your password manager: name, subdomain, Vercel project, both Neon URLs, admin username.

---

## Shipping an update

### Safe workflow
1. Work on a `dev` branch; test locally.
2. Merge to `main` only when ready: this redeploys **everyone**.
3. If the update includes a **new migration** (a new file in `migrations/versions/`), do step 4 **before** merging.

### 4. Run migrations on every database (only when there's a new migration)
Migrations only add things, so run them first; the currently deployed code keeps working.
Use each database's **direct** URL. Start with the demo, then each customer:

```bash
export DATABASE_URL="<direct-neon-url>"
flask db upgrade
flask bootstrap          # fills any new reference tables; never changes existing data
flask db current         # should end with "(head)"
unset DATABASE_URL
```

Tick each database off as you go. When all show `(head)`, merge to `main`.

How to tell whether an update needs migrations:
```bash
git diff --stat main..dev -- migrations/versions/
```
No output = no migrations, just merge.

---

## Support requests

### "Change my company name / GSTIN / logo"
The WhatsApp message tells you the company and the app URL (e.g. `acme.quote-room.co.in`). Check it's genuine, then:

```bash
export DATABASE_URL="<their-direct-neon-url>"
flask company-status
flask company-unlock gstin        # or: name, logo, --all
unset DATABASE_URL
```

Tell the customer to make the change in **Admin → Settings**. It locks again when they save.

### "I forgot the admin password"
Have another admin reset it under **Admin → Users**. If there's no other admin:

```bash
export DATABASE_URL="<their-direct-neon-url>"
flask shell
```
```python
from werkzeug.security import generate_password_hash
from app import db
from app.models import User
u = User.query.filter_by(username='admin').first()
u.password_hash = generate_password_hash('<new-password>', method='pbkdf2:sha256')
db.session.commit()
```

### Razorpay payments not being recorded
In their app, **Admin → Payment Settings** should show all three ticks. Usually the webhook secret in Razorpay doesn't match the one saved in the app, or the webhook URL/event (`payment_link.paid`) is wrong.

---

## Cancelling a customer
1. Offer an export within 30 days (see Privacy Policy): Neon → their project → backup/download, or `pg_dump "<direct-url>" > acme.sql`.
2. After 30 days: delete the Vercel project, the Neon project, and the GoDaddy CNAME.
3. Remove them from your password manager list.

---

## Marketing site and demo (`www.quote-room.co.in`)

| Variable | Purpose |
|---|---|
| `MARKETING_SITE=1` | Landing page at `/`, plus `/privacy` and `/terms` |
| `MARKETING_WHATSAPP`, `MARKETING_PRODUCT_NAME` | Buttons and branding on the landing page |
| `MARKETING_LEGAL_NAME`, `MARKETING_CONTACT_EMAIL`, `MARKETING_ADDRESS`, `MARKETING_JURISDICTION` | Shown on privacy/terms |
| `META_PIXEL_ID`, `GOOGLE_ADS_ID`, `GOOGLE_ADS_CONVERSION` | Ad tracking (WhatsApp clicks count as leads) |
| `DEMO_MODE=1` | One-click `/demo`, blocked admin saves, watermarked PDFs |
| `DEMO_PASSWORD`, `CRON_SECRET` | Random values; the cron resets demo data nightly at ~02:00 IST |

**The nightly reset wipes the demo database.** Never point a customer's `DATABASE_URL` at it, and never set `DEMO_MODE` on a customer project.

Manual reset (e.g. after testing): Vercel → `quotations-template` → **Settings → Cron Jobs → Run**.

---

## Costs and limits to watch
- **Vercel**: commercial use needs the **Pro** plan. One team can hold all customer projects.
- **Neon**: the free plan limits the number of projects; upgrade before you run out.
- Check both sites' current pricing; plans change.

---

## Environment variable reference
See `.env.example` in the repo root for every variable with comments.
