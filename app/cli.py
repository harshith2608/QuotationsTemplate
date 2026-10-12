import os

import click
from flask.cli import AppGroup

from .seed import SeedError, bootstrap, seed_demo
from . import branding
from . import plan as plan_mod


TRIALS_DB_MESSAGE = ('This is the shared trials database, which holds many trials. Say which trial with '
                     '--trial NAME, e.g.  python -m flask company-status --trial acme   '
                     '(list them with: python -m flask trial list). For plan dates use: flask trial extend NAME LENGTH.')


def _refuse_on_trials_db():
    """Commands for a single business must not run against the shared trials database without --trial."""
    from sqlalchemy import text
    from . import db, tenancy
    if tenancy.current_schema() or db.engine.dialect.name != 'postgresql':
        return
    with db.engine.connect() as conn:
        if conn.execute(text("SELECT to_regclass('public.tenants')")).scalar():
            raise click.ClickException(TRIALS_DB_MESSAGE)


def register_cli(app):

    @app.cli.command('bootstrap')
    def bootstrap_command():
        """Create the first admin (from ADMIN_USERNAME/ADMIN_PASSWORD) and seed reference data."""
        _refuse_on_trials_db()
        try:
            for line in bootstrap():
                click.echo(line)
        except SeedError as exc:
            raise click.ClickException(str(exc))

    @app.cli.command('seed-demo')
    @click.option('--reset', is_flag=True, help='Delete ALL existing data before seeding.')
    @click.option('--force', is_flag=True, help='Allow running when FLASK_ENV=production.')
    @click.option('--password', default=None,
                  help='Password for the demo users (default: $DEMO_PASSWORD or demo1234).')
    def seed_demo_command(reset, force, password):
        """Load fictional "Demo Interiors" data (users, quotations, payments)."""
        _refuse_on_trials_db()
        if os.environ.get('FLASK_ENV') == 'production' and not force:
            raise click.ClickException('Refusing to seed demo data in production. Use --force if you really mean it.')
        if reset:
            click.confirm('This will DELETE ALL data in the database. Continue?', abort=True)
        try:
            for line in seed_demo(reset=reset, password=password):
                click.echo(line)
        except SeedError as exc:
            raise click.ClickException(str(exc))

    def _maybe_trial(slug):
        """Context manager: run inside a trial's schema when --trial is given, else a no-op."""
        from contextlib import nullcontext
        if not slug:
            _refuse_on_trials_db()
            return nullcontext()
        from sqlalchemy import text
        from . import db, tenancy
        with db.engine.connect() as conn:
            row = conn.execute(text("SELECT schema_name FROM public.tenants WHERE slug = :s AND status = 'active'"),
                               {'s': slug}).first()
        if not row:
            raise click.ClickException(f'No active trial named "{slug}".')
        return tenancy.tenant_context(slug, row[0])

    @app.cli.command('console-setup')
    def console_setup_command():
        """Create the operator console's password hash and authenticator (2FA) secret."""
        from urllib.parse import quote
        from werkzeug.security import generate_password_hash
        from .console import new_totp_secret, totp_match
        password = click.prompt('Choose a console password (min 12 characters)', hide_input=True,
                                confirmation_prompt=True)
        if len(password) < 12:
            raise click.ClickException('Use at least 12 characters.')
        secret = new_totp_secret()
        grouped = ' '.join(secret[i:i + 4] for i in range(0, len(secret), 4))
        click.echo('\n1) In your authenticator app (Google Authenticator, Microsoft Authenticator, 1Password, …)')
        click.echo('   tap + → "Enter a setup key". Account: QuoteRoom console. Key (time-based):\n')
        click.echo(f'   {grouped}\n')
        click.echo(f'   (or open: otpauth://totp/{quote("QuoteRoom console")}?secret={secret}&issuer=QuoteRoom)\n')
        for attempt in range(3):
            code = click.prompt('2) Type the 6-digit code the app shows now')
            if totp_match(secret, code) is not None:
                break
            click.echo('   That code doesn\'t match. Check the key was typed exactly, then try the next code.')
        else:
            raise click.ClickException('Codes didn\'t match. Run this again and re-enter the key.')
        click.echo('\n3) Add these two env vars to the console Vercel project (Production), then redeploy:\n')
        click.echo(f'   CONSOLE_PASSWORD_HASH = {generate_password_hash(password, method="pbkdf2:sha256:600000")}')
        click.echo(f'   CONSOLE_TOTP_SECRET   = {secret}\n')
        click.echo('Keep the setup key in your password manager too: you need it to set up a new phone.')

    @app.cli.command('encrypt-data')
    @click.option('--trial', 'trial_slug', default=None, help='Run inside this trial (trials database).')
    def encrypt_data_command(trial_slug):
        """Encrypt any data still stored in plain text (also done by `flask bootstrap`)."""
        from . import crypto
        from .seed import encrypt_existing_data
        if not crypto.enabled():
            raise click.ClickException(f'Set {crypto.ENV} first (the same key as the Vercel project).')
        with _maybe_trial(trial_slug):
            click.echo(encrypt_existing_data())

    @app.cli.command('export-data')
    @click.argument('out_dir', type=click.Path(file_okay=False))
    @click.option('--trial', 'trial_slug', default=None, help='Export this trial (trials database).')
    def export_data_command(out_dir, trial_slug):
        """Write the customer's data, decrypted, as one CSV file per table (for their export request)."""
        import csv
        from . import crypto, db
        from .models import AppSetting
        os.makedirs(out_dir, exist_ok=True)
        skip_cols = {'password_hash'}
        skip_settings = {'logo_png'} | AppSetting.ENCRYPTED_KEYS - {'account_number', 'ifsc_code'}
        with _maybe_trial(trial_slug):
            for table in db.metadata.sorted_tables:
                cols = [c for c in table.columns if c.name not in skip_cols]
                rows = db.session.execute(table.select().with_only_columns(*cols)).mappings().all()
                path = os.path.join(out_dir, f'{table.name}.csv')
                with open(path, 'w', newline='', encoding='utf-8') as f:
                    w = csv.writer(f)
                    w.writerow([c.name for c in cols])
                    for r in rows:
                        if table.name == 'app_settings':
                            if r['key'] in skip_settings:
                                continue
                            r = dict(r, value=crypto.decrypt(r['value']) if r['value'] else r['value'])
                        w.writerow([r[c.name] for c in cols])
                click.echo(f'{path}: {len(rows)} rows')
        click.echo('Done. These files contain the customer\'s data in plain text: send them securely, then delete them.')

    @app.cli.command('company-status')
    @click.option('--trial', 'trial_slug', default=None, help='Run inside this trial (trials database).')
    def company_status_command(trial_slug):
        """Show the company identity fields and which are locked."""
        with _maybe_trial(trial_slug):
            _company_status()

    def _company_status():
        from .models import AppSetting
        locked = branding.locked_fields()
        rows = [('name', AppSetting.get('company_name', '')), ('gstin', AppSetting.get('company_gstin', '')),
                ('logo', 'uploaded' if AppSetting.get(branding.LOGO_VERSION_KEY, '') else '')]
        if not branding.lock_enabled():
            click.echo('Locking is disabled on this deployment (LOCK_COMPANY_DETAILS=0).')
        for field, value in rows:
            state = 'LOCKED' if field in locked else ('unlocked' if value else 'not set')
            click.echo(f'{field:6s} {state:9s} {value or "—"}')

    @app.cli.command('company-unlock')
    @click.argument('fields', nargs=-1)
    @click.option('--all', 'all_fields', is_flag=True, help='Unlock name, GSTIN and logo.')
    @click.option('--trial', 'trial_slug', default=None, help='Run inside this trial (trials database).')
    def company_unlock_command(fields, all_fields, trial_slug):
        """Let the client change a locked field once: name, gstin and/or logo. It re-locks when they save."""
        from . import db
        chosen = set(branding.LOCKABLE) if all_fields else set(fields)
        bad = chosen - set(branding.LOCKABLE)
        if not chosen or bad:
            raise click.ClickException('Choose one or more of: name, gstin, logo (or --all).')
        with _maybe_trial(trial_slug):
            branding.unlock(chosen)
            db.session.commit()
        click.echo(f'Unlocked: {", ".join(sorted(chosen))}. The client can change it once in Admin → Settings; '
                   'it locks again when they save.')

    # AppGroup (not click.Group) so every subcommand runs inside the app context
    plan_group = AppGroup('plan', help='Show or change this deployment\'s subscription plan.')
    app.cli.add_command(plan_group)

    def _show(status):
        if not status.has_limit:
            click.echo('No plan limits set (unlimited).')
            return
        fmt = lambda d: d.strftime('%d %b %Y') if d else '—'
        click.echo(f'Plan:        {status.label} ({status.plan})')
        click.echo(f'Started:     {fmt(status.started_on)}')
        click.echo(f'Ends:        {fmt(status.ends_on)}  ({status.days_left} days left)' if status.days_left >= 0
                   else f'Ends:        {fmt(status.ends_on)}  (ended {-status.days_left} days ago)')
        if not status.is_trial:
            click.echo(f'Grace until: {fmt(status.grace_until)}')
        click.echo(f'Read-only:   {"YES" if status.read_only else "no"}')
        click.echo(f'Delete on:   {fmt(status.delete_on)}')
        click.echo(f'State:       {status.state}')

    @plan_group.command('status')
    def plan_status():
        """Show the current plan and its dates."""
        _refuse_on_trials_db()
        _show(plan_mod.load_status(on=plan_mod.today()))

    @plan_group.command('set')
    @click.option('--plan', 'plan_name', type=click.Choice(['trial', '6m', '1y', 'custom']), required=True)
    @click.option('--start', default=None, help='Start date YYYY-MM-DD (default: today).')
    @click.option('--until', default=None, help='End date YYYY-MM-DD (default: start + plan length).')
    def plan_set(plan_name, start, until):
        """Set the plan, e.g.  flask plan set --plan 1y   or  --plan custom --until 2027-03-31"""
        _refuse_on_trials_db()
        from . import db
        from datetime import date
        try:
            start_d = date.fromisoformat(start) if start else plan_mod.today()
            if until:
                end_d = date.fromisoformat(until)
            elif plan_name in plan_mod.DEFAULT_LENGTH:
                end_d = plan_mod.add_length(start_d, plan_mod.DEFAULT_LENGTH[plan_name])
            else:
                raise click.ClickException('A custom plan needs --until YYYY-MM-DD.')
        except ValueError as exc:
            raise click.ClickException(str(exc))
        if end_d <= start_d:
            raise click.ClickException('The end date must be after the start date.')
        plan_mod.save_plan(plan_name, start_d, end_d)
        db.session.commit()
        _show(plan_mod.load_status(on=plan_mod.today()))

    @plan_group.command('extend')
    @click.argument('length')
    @click.option('--plan', 'plan_name', type=click.Choice(['6m', '1y', 'custom']), default=None,
                  help='Plan after renewing (default: 6m for 6m, 1y for 1y, else unchanged).')
    def plan_extend(length, plan_name):
        """Renew: add 6m, 1y, 7d… Extends from the current end date if still within grace, else from today."""
        _refuse_on_trials_db()
        from . import db
        status = plan_mod.load_status(on=plan_mod.today())
        try:
            plan_mod.parse_length(length)
        except ValueError as exc:
            raise click.ClickException(str(exc))
        today = plan_mod.today()
        if status.has_limit and today <= status.grace_until:
            base = status.ends_on          # renewing on time: no days lost
        else:
            base = today                   # late renewal (or no plan yet): start fresh
        key = length.strip().lower()
        # 6m / 1y renewals become that plan (incl. converting a trial); other lengths keep the current plan
        new_plan = plan_name or {'6m': '6m', '1y': '1y', '12m': '1y'}.get(key) or status.plan or 'custom'
        plan_mod.save_plan(new_plan, base, plan_mod.add_length(base, length))
        db.session.commit()
        _show(plan_mod.load_status(on=today))

    @plan_group.command('clear')
    def plan_clear():
        """Remove all plan limits (unlimited)."""
        _refuse_on_trials_db()
        from . import db
        plan_mod.save_plan('', None, None)
        db.session.commit()
        click.echo('Plan limits removed.')

    # ── Shared trials app ─────────────────────────────────────────────────────
    trial_group = AppGroup('trial', help='Manage trials in the shared trials database (Postgres).')
    app.cli.add_command(trial_group)

    from . import ops

    def _need_postgres():
        try:
            ops.need_postgres()
        except ops.OpsError as exc:
            raise click.ClickException(str(exc))

    _migrate_schema = ops.migrate_schema

    @trial_group.command('create')
    @click.argument('slug')
    @click.option('--admin-username', default='admin', show_default=True)
    @click.option('--admin-password', prompt=True, hide_input=True, confirmation_prompt=True,
                  help='Password for the trial\'s admin (asked if not given).')
    @click.option('--days', default=7, show_default=True, help='Trial length in days.')
    def trial_create(slug, admin_username, admin_password, days):
        """Create a trial: its schema, tables, admin login, default data and a 7-day trial plan."""
        try:
            t = ops.create_trial(slug, admin_username, admin_password, days, log=click.echo)
        except ops.OpsError as exc:
            raise click.ClickException(str(exc))
        click.echo(f'\nTrial "{t["slug"]}" is ready. {days}-day trial ends {t["ends_on"].strftime("%d %b %Y")}.')
        click.echo(f'Login: {t["url"]}  ·  username: {t["username"]}')

    @trial_group.command('list')
    def trial_list():
        """List trials with their plan status."""
        _need_postgres()
        rows = ops.list_trials()
        if not rows:
            click.echo('No trials yet.')
            return
        click.echo(f'{"SLUG":20} {"STATUS":10} {"PLAN":12} {"ENDS":12} {"STATE":10} DELETE ON')
        for r in rows:
            plan_txt = ends = state = delete_on = '—'
            st = r['status_obj']
            if st is not None and st.has_limit:
                plan_txt, ends, state = st.plan, st.ends_on.strftime('%d %b %Y'), st.state
                delete_on = st.delete_on.strftime('%d %b %Y')
            click.echo(f'{r["slug"]:20} {r["status"]:10} {plan_txt:12} {ends:12} {state:10} {delete_on}')

    @trial_group.command('extend')
    @click.argument('slug')
    @click.argument('length')
    def trial_extend(slug, length):
        """Give a trial more time, e.g.  flask trial extend acme 7d"""
        try:
            st = ops.extend_trial(slug, length)
        except ops.OpsError as exc:
            raise click.ClickException(str(exc))
        click.echo(f'Trial "{slug}" now ends {st.ends_on.strftime("%d %b %Y")} ({st.days_left} days left).')

    @trial_group.command('migrate-all')
    def trial_migrate_all():
        """Apply database updates to every active trial schema."""
        from . import tenancy
        _need_postgres()
        tenancy.ensure_registry()
        failed = []
        for r in tenancy.registry_rows():
            if r['status'] != 'active':
                continue
            click.echo(f'→ {r["slug"]} ({r["schema_name"]})')
            try:
                _migrate_schema(r['schema_name'])
                from .seed import encrypt_existing_data
                with tenancy.tenant_context(r['slug'], r['schema_name']):
                    click.echo('  ' + encrypt_existing_data())
            except Exception as exc:              # keep going; report at the end
                failed.append(r['slug'])
                click.echo(f'  FAILED: {exc}')
        if failed:
            raise click.ClickException(f'Migration failed for: {", ".join(failed)}')
        click.echo('All trial schemas are up to date.')

    @trial_group.command('delete')
    @click.argument('slug')
    @click.option('--yes', is_flag=True, help='Skip the confirmation prompt.')
    def trial_delete(slug, yes):
        """Permanently delete a trial's schema and all its data."""
        _need_postgres()
        try:
            ops.schema_of(slug, active_only=False)
            if not yes:
                click.confirm(f'Permanently delete trial "{slug}" and ALL its data?', abort=True)
            ops.delete_trial(slug)
        except ops.OpsError as exc:
            raise click.ClickException(str(exc))
        click.echo(f'Deleted trial "{slug}".')

    @trial_group.command('convert')
    @click.argument('slug')
    @click.option('--to', 'target_url', required=True, help='The customer\'s NEW database URL (direct, not -pooler).')
    @click.option('--plan', 'plan_name', type=click.Choice(['6m', '1y']), required=True)
    @click.option('--to-key', 'to_key', envvar='TARGET_DATA_ENCRYPTION_KEY', prompt='New project\'s DATA_ENCRYPTION_KEY',
                  hide_input=True, help='The customer project\'s own DATA_ENCRYPTION_KEY (asked if not given).')
    def trial_convert(slug, target_url, plan_name, to_key):
        """Copy a trial into the customer's own (new, migrated, empty) database and start their paid plan."""
        from sqlalchemy import create_engine, inspect, text
        from . import crypto, db, tenancy
        from .models import AppSetting
        _need_postgres()
        try:
            crypto.validate_key(to_key)
        except crypto.EncryptionError as exc:
            raise click.ClickException(f'--to-key: {exc}')
        if not crypto.enabled():
            raise click.ClickException(f'Set {crypto.ENV} to the trials project\'s key so the trial data can be read.')
        tenancy.ensure_registry()
        with db.engine.connect() as conn:
            row = conn.execute(text('SELECT schema_name, status FROM public.tenants WHERE slug = :s'), {'s': slug}).first()
        if not row:
            raise click.ClickException(f'No trial named "{slug}".')
        schema = row[0]

        url = target_url.strip()
        if url.startswith('postgres://'):
            url = url.replace('postgres://', 'postgresql+psycopg2://', 1)
        elif url.startswith('postgresql://'):
            url = url.replace('postgresql://', 'postgresql+psycopg2://', 1)
        target = create_engine(url)
        tables = db.metadata.sorted_tables
        with target.connect() as tc:
            names = set(inspect(tc).get_table_names())
            missing = [t.name for t in tables if t.name not in names]
            if missing or 'alembic_version' not in names:
                raise click.ClickException('The new database isn\'t set up yet. Run first:\n'
                                           f'  DATABASE_URL="<new-direct-url>" flask db upgrade')
            if tc.execute(text('SELECT COUNT(*) FROM users')).scalar():
                raise click.ClickException('The new database already has users. Use an empty database.')

        copied = {}
        with tenancy.tenant_context(slug, schema):
            src = db.session.connection()                 # schema-mapped to the trial
            with target.begin() as tc:
                for table in tables:
                    # Read decrypts with the trials key; insert re-encrypts with the customer's own key
                    rows = [dict(r) for r in src.execute(table.select()).mappings()]
                    if table.name == 'app_settings':
                        for r in rows:
                            if r['key'] in AppSetting.ENCRYPTED_KEYS and r['value']:
                                plain = crypto.decrypt(r['value'])
                                with crypto.using_key(to_key):
                                    r['value'] = crypto.encrypt(plain)
                    if rows:
                        with crypto.using_key(to_key):
                            tc.execute(table.insert(), rows)
                    copied[table.name] = len(rows)
                # Continue id sequences after the copied rows
                for table in tables:
                    if 'id' in table.c and table.c.id.primary_key:
                        tc.execute(text(
                            f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', 'id'), "
                            f"COALESCE((SELECT MAX(id) FROM \"{table.name}\"), 1), "
                            f"(SELECT MAX(id) FROM \"{table.name}\") IS NOT NULL)"))
                # Start the paid plan in the new database
                start = plan_mod.today()
                end = plan_mod.add_length(start, plan_name)
                for key, value in ((plan_mod.PLAN_KEY, plan_name), (plan_mod.STARTED_KEY, start.isoformat()),
                                   (plan_mod.ENDS_KEY, end.isoformat())):
                    tc.execute(text('DELETE FROM app_settings WHERE key = :k'), {'k': key})
                    tc.execute(text('INSERT INTO app_settings (key, value) VALUES (:k, :v)'), {'k': key, 'v': value})
            db.session.rollback()
        with db.engine.begin() as conn:
            conn.execute(text("UPDATE public.tenants SET status = 'converted', converted_at = (now() AT TIME ZONE 'utc') "
                              "WHERE slug = :s"), {'s': slug})
        tenancy.clear_cache()
        click.echo('Copied: ' + ', '.join(f'{k} {v}' for k, v in copied.items() if v))
        click.echo(f'Paid plan {plan_name} runs {start.strftime("%d %b %Y")} – {end.strftime("%d %b %Y")}.')
        click.echo(f'Next: move {slug}.{tenancy.base_domain() or "<domain>"} from the trials project to the customer\'s '
                   'own Vercel project. Then delete the trial copy with: flask trial delete ' + slug)
