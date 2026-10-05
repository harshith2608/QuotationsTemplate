# Interior Quotation App — White-Label Template

A Flask application for interior design businesses to create wood-work quotations, track payments, generate branded PDF quotations and share them with customers on WhatsApp.

This repository is a **template**: each client gets their own deployment with their own branding (set by environment variables) and their own Postgres database (`DATABASE_URL`). Nothing business-specific is hardcoded.

---

## Features

### Quotation Management
- Create quotations with customer details, rooms, and items (length × width → sqft)
- Material types: **Acrylic**, **Laminates**, **Veneer** · Work types: **Box Work**, **Frame Work** (defined once in `app/catalog.py`)
- **Fixed-price items** (fittings & accessories such as a Magic Corner or tandem drawers): quantity × unit price, no dimensions. Picked from an admin-managed price list (Admin → Rates), itemised per room in the Full Quotation and shown as one "Fittings & Accessories" line in the Initial Quotation
- Auto-calculates area and cost per item using admin-configured rates
- Discount support — percentage or fixed amount
- Live cost summary and plywood board estimate (8×4 ft boards) as rooms/items are added
- Auto-save draft while editing; search, paginate, and filter quotations

### PDF Generation
Two PDF formats via **ReportLab Platypus**:

| PDF Type | Contents |
|---|---|
| **Internal PDF** | Full room-by-room breakdown with rates, cost summary, total area, plywood used, material specs, T&C, signature section, payment details |
| **Customer PDF** | Simplified view without per-item rates: final total, plywood used, material specs, T&C, signature section |

Both PDFs carry the client's logo, company name, address, phone, email, GSTIN, brand colours and signatory.

### Payments, Sharing, Admin
- Manual payments, **Razorpay Payment Links** and a signed **Razorpay webhook** that auto-records payments
- Email notifications (SMTP) to admin and customer on auto-payment
- One-click WhatsApp share with a formatted quotation summary
- Admin dashboard, user management, rates, payment/company settings, per-quotation employee access, notifications
- Role-based access: `admin` and `employee`

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12 · Flask 3.0 (application factory + blueprints) |
| ORM / migrations | Flask-SQLAlchemy · Flask-Migrate (Alembic) |
| Database | PostgreSQL per deployment (Neon / Supabase / Render) · SQLite for local dev |
| Auth | Flask-Login · PBKDF2-SHA256 · Flask-WTF CSRF |
| PDF | ReportLab Platypus |
| Payments | Razorpay Payment Links API + webhook |
| Frontend | Bootstrap 5 · Bootstrap Icons · vanilla JS |
| Hosting | Vercel, Render or any Procfile host (Gunicorn + WhiteNoise) |

---

## Configuration

All configuration is via environment variables. Copy `.env.example` to `.env` for local development (it is loaded automatically); set them in your host's dashboard in production.

### Core

| Variable | Required | Description |
|---|---|---|
| `SECRET_KEY` | production | Long random string. `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | production | This deployment's Postgres URL. Unset locally → SQLite `app.db` |
| `FLASK_ENV` | | `production` when deployed (default `development`) |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | first deploy | First admin, created by `flask bootstrap` if no admin exists (password ≥ 8 chars) |

The app refuses to start with `FLASK_ENV=production` unless `SECRET_KEY` and `DATABASE_URL` are set.

### Branding & theme

Clients customise their portal themselves in **Admin → Settings**; the env vars below only set the starting values for a new deployment. Every value resolves as: *saved in Settings* → *env var* → *built-in default*. Clearing a field in Settings falls back to the env var (shown as the placeholder).

| Variable | Default | Settings tab | Used in |
|---|---|---|---|
| `COMPANY_NAME` | `Your Company Name` | Company | Navbar, titles, login, PDFs, emails, WhatsApp, Razorpay links |
| `COMPANY_ADDRESS` / `COMPANY_PHONE` / `COMPANY_EMAIL` | — | Company | PDF header |
| `COMPANY_GSTIN` | — | Company | PDF header (only when set) |
| `COMPANY_TAGLINE` | `Interior Design & Furnishing Solutions` | Company | Footer; PDF subtitle when no contact details are set |
| `SIGNATORY_NAME` / `SIGNATORY_TITLE` | company name / `Proprietor` | Company | PDF signature block |
| `BRAND_PRIMARY` | `#1a237e` | Appearance | Header, buttons, links, headings, form focus, PDF tables, favicon |
| `BRAND_SECONDARY` | `#283593` | Appearance | Gradients, room headers |
| `BRAND_ACCENT` | `#f57f17` | Appearance | Active menu, light-header underline, PDF divider rules |
| `BRAND_BACKGROUND` | `#f5f6fa` | Appearance | Page background (must be light) |
| `BRAND_HEADER` | `gradient` | Appearance | `gradient` \| `solid` \| `light` — top bar and section headers |
| `BRAND_CORNERS` | `rounded` | Appearance | `sharp` \| `rounded` \| `soft` — cards, inputs, badges |
| `BRAND_BUTTONS` | `standard` | Appearance | `standard` (match corners) \| `pill` |
| `BRAND_FONT` | `system` | Appearance | `system`, `inter`, `poppins`, `montserrat`, `lato`, `nunito`, `dm-sans`, `lora` (Google Fonts) |
| `LOGO_FILE` | — | Appearance (upload) | PNG/JPG under `static/`; an uploaded logo takes precedence |

**Admin → Settings → Appearance** offers 10 preset palettes, colour pickers, header/corner/button/font choices and a logo upload, with a live preview applied to the whole page before saving. Text on coloured headers and buttons automatically switches between white and dark for readability, and PDFs darken a too-light primary colour so printed text stays legible. Uploaded logos are validated, resized to ≤600 px and re-encoded as PNG, then stored in the database (Vercel's filesystem is read-only), so they survive redeploys.

**Admin → Payment Settings** holds Razorpay keys, the webhook secret, UPI and bank details. **Admin → Settings** also has *Quotation PDFs* (material specifications, T&C) and *Email* (SMTP for payment notifications).

### Company identity lock

One subscription covers one business. With `LOCK_COMPANY_DETAILS=1` (the default), the **company name, GSTIN and logo become read-only once the client saves them**. Each field locks on its own, so a GSTIN can still be added later. Before the first save the client must tick a confirmation box, and GSTINs are format-checked. Locked fields link to your `SUPPORT_WHATSAPP`.

To allow a genuine change, run against that client's database:

```bash
DATABASE_URL="postgresql://..." flask company-status
DATABASE_URL="postgresql://..." flask company-unlock gstin      # or: name, logo, --all
```

The client can then change that field once; it locks again when they save.

### Marketing page

The product's own sales page (pricing, features, a working sample quote) plus `/privacy` and `/terms`. Because every client deployment runs the same code, these are **off by default** and return 404. With `MARKETING_SITE=1`, `/` always shows the landing page (signed-in users get an "Open app" button; logging out returns there), so your domain root is the sales page; it's also at `/landingpage`. The legal pages read `MARKETING_LEGAL_NAME`, `MARKETING_CONTACT_EMAIL`, `MARKETING_ADDRESS` and `MARKETING_JURISDICTION`. Enable it only on your own demo/marketing deployment with `MARKETING_SITE=1`, and set `MARKETING_WHATSAPP` (all buttons open a WhatsApp chat), `MARKETING_PRODUCT_NAME`, and optionally `META_PIXEL_ID`, `GOOGLE_ADS_ID` / `GOOGLE_ADS_CONVERSION` (a WhatsApp-button click is tracked as a lead) and `MARKETING_PRIVACY_URL` / `MARKETING_TERMS_URL`. The "Try the live demo" button goes to that deployment's login page.

### Public demo mode

For your own demo deployment, set `DEMO_MODE=1`:

- **One-click entry:** `/demo` signs visitors into the `DEMO_USER` account (default `demo-admin`); the login page and landing page link to it. No password is shown, so set `DEMO_PASSWORD` to something random.
- **Can't be vandalised or used for fakes:** saving Settings/branding, Payment Settings, Rates and Users is blocked, as are deleting quotations or payments, Razorpay links and access changes. Creating and editing quotations, stages and recording payments still work.
- **Watermarked output:** every PDF is stamped "DEMO — NOT A VALID QUOTATION", and WhatsApp summaries are labelled as demo.
- **Nightly reset:** `vercel.json` schedules `/demo/reset` daily at 02:00 IST. It only runs when `DEMO_MODE=1` and the request carries `CRON_SECRET` (Vercel sends it automatically), and it **wipes and reloads the whole database** with demo data. On other hosts, run `flask seed-demo --reset --force` from a scheduler.

---

## Local Development

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env              # then edit; leave DATABASE_URL unset to use SQLite

flask db upgrade                  # create tables
flask seed-demo                   # load fictional "Demo Interiors" data
python run.py                     # http://localhost:5000
```

Log in as `demo-admin` or `demo-staff` with password `demo1234` (or `$DEMO_PASSWORD`).

To start with an empty database instead of demo data, run `flask bootstrap` (with `ADMIN_PASSWORD` set) instead of `flask seed-demo`.

### CLI commands

| Command | What it does |
|---|---|
| `flask db upgrade` | Apply database migrations (safe to run repeatedly) |
| `flask bootstrap` | Create the first admin from `ADMIN_USERNAME`/`ADMIN_PASSWORD` if none exists; seed default rates, room and item names into empty tables. Idempotent |
| `flask seed-demo` | Load Demo Interiors users, 5 quotations, payments and company settings. Refuses if the DB already has data |
| `flask seed-demo --reset` | Wipe **all** data, then load demo data (asks for confirmation) |
| `flask seed-demo --force` | Allow running with `FLASK_ENV=production` |

All demo names, phone numbers, addresses, GSTIN, UPI and bank details are fictional.

---

## Deploying for a New Client

> Running this as a business (onboarding customers, shipping updates, support)? See **[docs/OPERATIONS.md](docs/OPERATIONS.md)**.


1. **Create a Postgres database** for the client (Neon, Supabase or Render Postgres) and copy its connection URL.
2. **Add branding** — set the branding env vars; optionally commit the client's logo to `static/brand/` and set `LOGO_FILE`.
3. **Set core env vars** — `FLASK_ENV=production`, `SECRET_KEY`, `DATABASE_URL`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`.
4. **Initialise the database** — `flask db upgrade && flask bootstrap`.
   - **Render**: `render.yaml` runs both on every start. Rename the service and database first.
   - **Heroku-style hosts**: the `release:` line in `Procfile` runs both on each deploy.
   - **Vercel** (no release hook): run once from your machine against the client DB:
     ```bash
     DATABASE_URL="postgresql://..." ADMIN_PASSWORD="..." flask db upgrade
     DATABASE_URL="postgresql://..." ADMIN_PASSWORD="..." flask bootstrap
     ```
5. **Put the app next to its database.** Every page makes several database queries, so the app server and Postgres must be in the same region. On Vercel set *Project Settings → Functions → Function Region* to match the database (e.g. Neon `ap-southeast-1` → `sin1` Singapore), then redeploy. Vercel's default is Washington, D.C. (`iad1`).
6. **Log in as the admin** and fill in *Settings* (company details, appearance, PDFs, email), *Payment Settings* (UPI/bank, Razorpay) and *Rates*.

---

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest tests -q
```

Each script in `tests/checks/` runs against its own fresh SQLite database (migrated and seeded
automatically) and prints `PASS`/`FAIL` per check; you can also run one directly to see every
line. The multi-tenant (trials) checks need Postgres and are skipped unless `TEST_PG_URL` and
`TEST_PG_TARGET_URL` point at two **empty, throwaway** databases. Never point them at a real one.

---

## Database Migrations

The schema is managed by Flask-Migrate (Alembic) in `migrations/`. When you change `app/models.py`:

```bash
flask db migrate -m "describe the change"   # generates migrations/versions/xxxx.py — review it
flask db upgrade                            # apply locally
```

Commit the new migration file. Every deployment picks it up on its next `flask db upgrade`. No manual `ALTER TABLE` needed.

After upgrading an existing deployment, also run `flask bootstrap`: it only fills empty reference tables (for example the fittings price list added later) and never touches existing data.

**Adopting an existing database** that was created before migrations existed (tables already present): run `flask db stamp head` once against it to mark it as up to date, then use `flask db upgrade` from then on.

---

## Project Structure

```
├── app/
│   ├── __init__.py      # Application factory, extensions, template globals
│   ├── branding.py      # Env-driven branding + admin overrides (get_brand)
│   ├── catalog.py       # Materials, work types, plywood options, default reference data
│   ├── seed.py          # bootstrap() and seed_demo()
│   ├── cli.py           # flask bootstrap / flask seed-demo
│   ├── models.py        # SQLAlchemy models
│   ├── auth.py          # Login / logout
│   ├── main.py          # Root redirect, favicon, error handlers
│   ├── projects.py      # Quotation CRUD, PDFs, WhatsApp, payments, Razorpay webhook
│   ├── admin_bp.py      # Admin dashboard, users, rates, settings
│   ├── api.py           # Internal JSON API
│   ├── pdf_utils.py     # ReportLab PDF generation
│   ├── forms.py         # WTForms
│   └── decorators.py    # @admin_required
├── migrations/          # Alembic migration scripts
├── tests/               # python -m pytest tests -q (checks/ = one script per feature)
├── templates/           # Jinja templates (base, auth, projects, admin, errors)
├── static/
│   ├── brand/           # Put client logos here
│   ├── css/style.css
│   └── js/project_form.js
├── config.py            # Config classes, .env loading
├── run.py               # Entry point
├── .env.example         # All supported env vars
├── render.yaml · vercel.json · Procfile
└── requirements.txt
```

### Data model

`users`, `projects`, `rooms`, `items`, `item_rates` (rate per material × work type), `payments`, `payment_links`, `notifications`, `project_access`, `project_edit_logs`, `master_rooms` / `master_items` (autocomplete), `app_settings` (key-value store for admin settings), plus legacy `wood_rates` / `work_type_rates`. See `app/models.py`.

---

## API Endpoints (Internal)

| Method | Endpoint | Description |
|---|---|---|
| GET | `/api/master-rooms` | Room name suggestions |
| GET | `/api/master-items` | Item name suggestions |
| GET | `/api/wood-rates` | Map of `wood_type: rate` |
| POST | `/api/draft` | Auto-save project as draft |
| POST | `/webhook/razorpay` | Razorpay payment webhook |

---

## Security

- CSRF protection on all forms (Flask-WTF)
- PBKDF2-SHA256 password hashing; no default admin password — the first admin comes from `ADMIN_PASSWORD`
- HMAC-SHA256 verification of Razorpay webhooks
- Role-based access control; admin routes guarded by `@admin_required`
- Secure, HttpOnly, SameSite=Lax session cookies in production
- Theme values are validated (`#rrggbb` colours, whitelisted choices) before being injected into CSS; logo uploads are re-encoded through Pillow and SVG is rejected

Note: Razorpay secrets and the SMTP password entered in the admin settings are stored unencrypted in the `app_settings` table — restrict database access accordingly.

---

## License

Add your license here.
