from django.core.management.base import BaseCommand
from django.utils import timezone

from shortener.models import Link
from shortener.services import purge_expired_links


class Command(BaseCommand):
    help = "Delete short links whose expiry time has passed (links with no expiry are kept)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='List what would be deleted without deleting anything.',
        )

    def handle(self, *args, **options):
        if options['dry_run']:
            expired = Link.objects.filter(expires_at__isnull=False, expires_at__lte=timezone.now())
            for link in expired:
                self.stdout.write(f"would delete: {link.short_code} (expired {link.expires_at})")
            self.stdout.write(self.style.WARNING(f"[dry-run] {expired.count()} expired link(s)"))
            return

        count = purge_expired_links()
        self.stdout.write(self.style.SUCCESS(f"Deleted {count} expired link(s)."))
