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
