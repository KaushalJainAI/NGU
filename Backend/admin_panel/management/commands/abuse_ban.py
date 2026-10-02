"""Manually ban / unban / inspect client IPs flagged for abuse.

    python manage.py abuse_ban --ip 1.2.3.4            # ban (until unbanned)
    python manage.py abuse_ban --ip 1.2.3.4 --ttl 3600 # ban for 1 hour
    python manage.py abuse_ban --ip 1.2.3.4 --unban     # lift the ban
    python manage.py abuse_ban --ip 1.2.3.4 --status    # is it banned + strikes
"""
from django.core.management.base import BaseCommand, CommandError
from django.core.cache import cache

from spices_backend.abuse import block_ip, unblock_ip, is_blocked
from spices_backend.limits import ABUSE_STRIKE_WINDOW


class Command(BaseCommand):
    help = "Ban/unban an IP flagged for abusive (out-of-bound / extreme) requests."

    def add_arguments(self, parser):
        parser.add_argument("--ip", required=True, help="Client IP address")
        parser.add_argument("--unban", action="store_true", help="Lift the ban")
        parser.add_argument("--status", action="store_true", help="Show ban + strike count")
        parser.add_argument("--ttl", type=int, default=None, help="Ban duration in seconds (default: permanent)")

    def handle(self, *args, **opts):
        ip = opts["ip"].strip()
        if not ip:
            raise CommandError("--ip is required")

        if opts["status"]:
            strikes = cache.get(f"abuse:strikes:{ip}", 0)
            self.stdout.write(
                f"{ip}: blocked={is_blocked(ip)} "
                f"strikes={strikes} (window {ABUSE_STRIKE_WINDOW}s)"
            )
            return

        if opts["unban"]:
            unblock_ip(ip)
            self.stdout.write(self.style.SUCCESS(f"Unbanned {ip}"))
            return

        block_ip(ip, ttl=opts["ttl"])
        self.stdout.write(self.style.SUCCESS(
            f"Banned {ip}" + (f" for {opts['ttl']}s" if opts["ttl"] else " (permanent)")
        ))
