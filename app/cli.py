import os

import click

from .seed import SeedError, bootstrap, seed_demo
from . import branding


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
