import os

import click
from flask.cli import AppGroup

from .seed import SeedError, bootstrap, seed_demo
from . import branding
from . import plan as plan_mod


def register_cli(app):

    @app.cli.command('bootstrap')
    def bootstrap_command():
        """Create the first admin (from ADMIN_USERNAME/ADMIN_PASSWORD) and seed reference data."""
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
        if os.environ.get('FLASK_ENV') == 'production' and not force:
            raise click.ClickException('Refusing to seed demo data in production. Use --force if you really mean it.')
        if reset:
            click.confirm('This will DELETE ALL data in the database. Continue?', abort=True)
        try:
            for line in seed_demo(reset=reset, password=password):
                click.echo(line)
        except SeedError as exc:
            raise click.ClickException(str(exc))

    @app.cli.command('company-status')
    def company_status_command():
        """Show the company identity fields and which are locked."""
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
    def company_unlock_command(fields, all_fields):
        """Let the client change a locked field once: name, gstin and/or logo. It re-locks when they save."""
        from . import db
        chosen = set(branding.LOCKABLE) if all_fields else set(fields)
        bad = chosen - set(branding.LOCKABLE)
        if not chosen or bad:
            raise click.ClickException('Choose one or more of: name, gstin, logo (or --all).')
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
        _show(plan_mod.load_status(on=plan_mod.today()))

    @plan_group.command('set')
    @click.option('--plan', 'plan_name', type=click.Choice(['trial', '6m', '1y', 'custom']), required=True)
    @click.option('--start', default=None, help='Start date YYYY-MM-DD (default: today).')
    @click.option('--until', default=None, help='End date YYYY-MM-DD (default: start + plan length).')
    def plan_set(plan_name, start, until):
        """Set the plan, e.g.  flask plan set --plan 1y   or  --plan custom --until 2027-03-31"""
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
        from . import db
        plan_mod.save_plan('', None, None)
        db.session.commit()
        click.echo('Plan limits removed.')

    # ── Shared trials app ─────────────────────────────────────────────────────
    trial_group = AppGroup('trial', help='Manage trials in the shared trials database (Postgres).')
    app.cli.add_command(trial_group)

    def _need_postgres():
        from . import db
        if db.engine.dialect.name != 'postgresql':
            raise click.ClickException('Trials need a PostgreSQL DATABASE_URL.')

    def _migrate_schema(schema):
        from flask_migrate import upgrade
        upgrade(x_arg=[f'tenant_schema={schema}'])

    @trial_group.command('create')
    @click.argument('slug')
    @click.option('--admin-username', default='admin', show_default=True)
    @click.option('--admin-password', prompt=True, hide_input=True, confirmation_prompt=True,
                  help='Password for the trial\'s admin (asked if not given).')
    @click.option('--days', default=7, show_default=True, help='Trial length in days.')
    def trial_create(slug, admin_username, admin_password, days):
        """Create a trial: its schema, tables, admin login, default data and a 7-day trial plan."""
        from datetime import timedelta
        from sqlalchemy import text
        from . import db, tenancy
        from .seed import bootstrap, SeedError
        _need_postgres()
        try:
            slug = tenancy.validate_slug(slug)
        except tenancy.TenantError as exc:
            raise click.ClickException(str(exc))
        if len(admin_password or '') < 8:
            raise click.ClickException('The admin password must be at least 8 characters.')
        schema = tenancy.schema_for(slug)
        tenancy.ensure_registry()
        with db.engine.begin() as conn:
            if conn.execute(text('SELECT 1 FROM public.tenants WHERE slug = :s'), {'s': slug}).first():
                raise click.ClickException(f'A trial named "{slug}" already exists.')
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text("INSERT INTO public.tenants (slug, schema_name, status) VALUES (:s, :sc, 'creating')"),
                         {'s': slug, 'sc': schema})
        click.echo(f'Creating tables in schema {schema}…')
        _migrate_schema(schema)
        with tenancy.tenant_context(slug, schema):
            try:
                for line in bootstrap(username=admin_username, password=admin_password):
                    click.echo(line)
            except SeedError as exc:
                raise click.ClickException(str(exc))
            start = plan_mod.today()
            plan_mod.save_plan('trial', start, start + timedelta(days=days))
            db.session.commit()
        with db.engine.begin() as conn:
            conn.execute(text("UPDATE public.tenants SET status = 'active' WHERE slug = :s"), {'s': slug})
        base = tenancy.base_domain() or '<TENANT_BASE_DOMAIN>'
        click.echo(f'\nTrial "{slug}" is ready. {days}-day trial ends {(start + timedelta(days=days)).strftime("%d %b %Y")}.')
        click.echo(f'Next: add {slug}.{base} to the trials Vercel project and a CNAME "{slug}" in GoDaddy.')
        click.echo(f'Login: https://{slug}.{base}  ·  username: {admin_username}')

    @trial_group.command('list')
    def trial_list():
        """List trials with their plan status."""
        from . import tenancy
        _need_postgres()
        tenancy.ensure_registry()
        rows = tenancy.registry_rows()
        if not rows:
            click.echo('No trials yet.')
            return
        click.echo(f'{"SLUG":20} {"STATUS":10} {"PLAN":12} {"ENDS":12} {"STATE":10} DELETE ON')
        for r in rows:
            plan_txt = ends = state = delete_on = '—'
            if r['status'] == 'active':
                with tenancy.tenant_context(r['slug'], r['schema_name']):
                    st = plan_mod.load_status(on=plan_mod.today())
                if st.has_limit:
                    plan_txt, ends, state = st.plan, st.ends_on.strftime('%d %b %Y'), st.state
                    delete_on = st.delete_on.strftime('%d %b %Y')
            click.echo(f'{r["slug"]:20} {r["status"]:10} {plan_txt:12} {ends:12} {state:10} {delete_on}')

    @trial_group.command('extend')
    @click.argument('slug')
    @click.argument('length')
    def trial_extend(slug, length):
        """Give a trial more time, e.g.  flask trial extend acme 7d"""
        from datetime import timedelta
        from sqlalchemy import text
        from . import db, tenancy
        _need_postgres()
        try:
            plan_mod.parse_length(length)
        except ValueError as exc:
            raise click.ClickException(str(exc))
        with db.engine.connect() as conn:
            row = conn.execute(text("SELECT schema_name FROM public.tenants WHERE slug = :s AND status = 'active'"),
                               {'s': slug}).first()
        if not row:
            raise click.ClickException(f'No active trial named "{slug}".')
        with tenancy.tenant_context(slug, row[0]):
            st = plan_mod.load_status(on=plan_mod.today())
            base = max(st.ends_on, plan_mod.today()) if st.has_limit else plan_mod.today()
            plan_mod.save_plan('trial', st.started_on or plan_mod.today(), plan_mod.add_length(base, length))
            db.session.commit()
            st = plan_mod.load_status(on=plan_mod.today())
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
        from sqlalchemy import text
        from . import db, tenancy
        _need_postgres()
        tenancy.ensure_registry()
        with db.engine.connect() as conn:
            row = conn.execute(text('SELECT schema_name FROM public.tenants WHERE slug = :s'), {'s': slug}).first()
        if not row:
            raise click.ClickException(f'No trial named "{slug}".')
        if not yes:
            click.confirm(f'Permanently delete trial "{slug}" and ALL its data?', abort=True)
        with db.engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{row[0]}" CASCADE'))
            conn.execute(text('DELETE FROM public.tenants WHERE slug = :s'), {'s': slug})
        tenancy.clear_cache()
        click.echo(f'Deleted trial "{slug}". Remember to remove its domain from Vercel and its CNAME from GoDaddy.')

    @trial_group.command('convert')
    @click.argument('slug')
    @click.option('--to', 'target_url', required=True, help='The customer\'s NEW database URL (direct, not -pooler).')
    @click.option('--plan', 'plan_name', type=click.Choice(['6m', '1y']), required=True)
    def trial_convert(slug, target_url, plan_name):
        """Copy a trial into the customer's own (new, migrated, empty) database and start their paid plan."""
        from sqlalchemy import create_engine, inspect, text
        from . import db, tenancy
        _need_postgres()
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
                    rows = [dict(r) for r in src.execute(table.select()).mappings()]
                    if rows:
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
