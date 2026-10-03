import os

import click

from .seed import SeedError, bootstrap, seed_demo


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
