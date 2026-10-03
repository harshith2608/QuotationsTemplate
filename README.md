# Interior Quotation App — White-Label Template

A Flask application for interior design businesses to create wood-work quotations, track payments, generate branded PDF quotations and share them with customers on WhatsApp.

This repository is a **template**: each client gets their own deployment with their own branding (set by environment variables) and their own Postgres database (`DATABASE_URL`). Nothing business-specific is hardcoded.

---

## Features

### Quotation Management
- Create quotations with customer details, rooms, and items (length × width → sqft)
- Material types: **Acrylic**, **Laminates**, **Veneer** · Work types: **Box Work**, **Frame Work** (defined once in `app/catalog.py`)
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

### Branding

| Variable | Default | Used in |
|---|---|---|
| `COMPANY_NAME` | `Your Company Name` | Navbar, page titles, login, PDFs, emails, WhatsApp, Razorpay link description |
| `COMPANY_ADDRESS` | — | PDF header |
| `COMPANY_PHONE` | — | PDF header |
| `COMPANY_EMAIL` | — | PDF header |
| `COMPANY_GSTIN` | — | PDF header (shown only when set) |
| `COMPANY_TAGLINE` | `Interior Design & Furnishing Solutions` | Footer; PDF subtitle when no contact details are set |
| `SIGNATORY_NAME` | `COMPANY_NAME` | PDF signature block |
| `SIGNATORY_TITLE` | `Proprietor` | PDF signature block |
| `BRAND_PRIMARY` | `#1a237e` | Navbar, buttons, headings, PDF tables, favicon |
| `BRAND_SECONDARY` | `#283593` | Gradients, room headers |
| `BRAND_ACCENT` | `#f57f17` | PDF accent rules |
| `LOGO_FILE` | — | Path under `static/`, e.g. `brand/logo.png`. PNG/JPG for PDF support |

**Company details can also be edited by an admin** in *Admin → Payment Settings*. A value saved there overrides the env var; clearing the field falls back to the env var (shown as the placeholder). Colours, logo, tagline and signatory are env-only.

Razorpay keys, UPI/bank details, SMTP, material specifications and T&C are entered by the admin in *Admin → Payment Settings* and stored in the database.

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
5. **Log in as the admin** and fill in *Payment Settings* (UPI/bank, Razorpay, SMTP, T&C) and *Rates*.

---

## Database Migrations

The schema is managed by Flask-Migrate (Alembic) in `migrations/`. When you change `app/models.py`:

```bash
flask db migrate -m "describe the change"   # generates migrations/versions/xxxx.py — review it
flask db upgrade                            # apply locally
```

Commit the new migration file. Every deployment picks it up on its next `flask db upgrade`. No manual `ALTER TABLE` needed.

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
- Brand colours are validated as `#rrggbb` before being injected into CSS

Note: Razorpay secrets and the SMTP password entered in Payment Settings are stored unencrypted in the `app_settings` table — restrict database access accordingly.

---

## License

Add your license here.
