"""In-process job scheduler — the single long-running process that fires the
platform's periodic background jobs.

Historically these jobs (`reconcile_payments`, `rollup_analytics`) were only ever
run by hand via `docker-compose exec`, so on a real deploy they simply never ran:
payments couldn't self-heal a missed webhook, abandoned checkouts held their
stock forever, and the admin Insights dashboard froze. This command closes that
gap by running them on a fixed cadence.

Run it as its OWN dedicated container (see the `scheduler` service in
docker-compose*.yml) — one process, so jobs never double-fire the way an
in-gunicorn-worker scheduler would (N workers → N duplicate runs).

    python manage.py run_scheduler

Schedule (all intervals overridable via env):
  * reconcile_payments   every RECONCILE_INTERVAL_MINUTES   (default 5)
        L3 self-healing. For each ONLINE order unpaid past PAYMENT_STUCK_TTL_MINUTES
        (15) it asks Razorpay for the truth: captured → mark paid (recovers a
        missed webhook); otherwise → cancel + restore stock + payment_status
        'rejected'.
  * rollup_analytics     every ROLLUP_INTERVAL_MINUTES      (default 5)
        Recomputes today's sales/behavioral rollups and drains the anonymous
        Redis counters into the DB, so the Insights dashboard stays live.
  * rollup_analytics --days 3   nightly at 00:20
        A wider catch-up pass so a few missed ticks self-heal.
  * send_daily_digest    daily at 08:00
        Plain-language store-owner email (yesterday's sales + what needs
        attention) to ADMIN_ALERT_EMAIL.
  * send_weekly_summary  Mondays at 08:30
        Weekly business summary (revenue vs last week, best sellers, zero-result
        searches, low stock) to ADMIN_ALERT_EMAIL.

Each job is wrapped so one failure is logged and never kills the scheduler.
"""
import logging

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


def _run(label, *args, **kwargs):
    """Invoke a management command, swallowing (but logging) any error so the
    scheduler process itself never dies on a single bad run."""
    try:
        logger.info("scheduler: running %s", label)
        call_command(*args, **kwargs)
    except Exception:  # noqa: BLE001 — a failed job must not stop the scheduler
        logger.exception("scheduler: job %s failed", label)


class Command(BaseCommand):
    help = "Run the periodic background jobs (payment reconciliation, analytics rollups)."

    def handle(self, *args, **options):
        try:
            from apscheduler.schedulers.blocking import BlockingScheduler
            from apscheduler.triggers.cron import CronTrigger
        except ImportError:
            raise SystemExit(
                "APScheduler is not installed. Add 'apscheduler' to requirements.txt "
                "and rebuild the image.")

        reconcile_every = int(getattr(settings, 'RECONCILE_INTERVAL_MINUTES', 5) or 5)
        rollup_every = int(getattr(settings, 'ROLLUP_INTERVAL_MINUTES', 5) or 5)

        scheduler = BlockingScheduler(timezone=str(getattr(settings, 'TIME_ZONE', 'UTC')))

        # coalesce=True: if the process was busy/asleep, collapse the missed runs
        # into a single catch-up rather than firing a backlog. max_instances=1:
        # never overlap a job with itself. (No next_run_time override — that would
        # add the job *paused*; the trigger schedules the first run one interval
        # out, and we fire an immediate run manually below.)
        scheduler.add_job(
            _run, 'interval', minutes=reconcile_every,
            args=['reconcile_payments', 'reconcile_payments'],
            id='reconcile_payments', coalesce=True, max_instances=1)
        scheduler.add_job(
            _run, 'interval', minutes=rollup_every,
            args=['rollup_analytics', 'rollup_analytics'],
            id='rollup_analytics', coalesce=True, max_instances=1)
        scheduler.add_job(
            _run, CronTrigger(hour=0, minute=20),
            kwargs={'days': 3}, args=['rollup_analytics_nightly', 'rollup_analytics'],
            id='rollup_analytics_nightly', coalesce=True, max_instances=1)
        # Store-owner emails: daily digest every morning, weekly summary Mondays.
        scheduler.add_job(
            _run, CronTrigger(hour=8, minute=0),
            args=['send_daily_digest', 'send_daily_digest'],
            id='send_daily_digest', coalesce=True, max_instances=1)
        scheduler.add_job(
            _run, CronTrigger(day_of_week='mon', hour=8, minute=30),
            args=['send_weekly_summary', 'send_weekly_summary'],
            id='send_weekly_summary', coalesce=True, max_instances=1)

        # Fire both interval jobs once at startup so a fresh deploy reconciles and
        # refreshes insights immediately instead of waiting a full interval.
        _run('reconcile_payments', 'reconcile_payments')
        _run('rollup_analytics', 'rollup_analytics')

        self.stdout.write(self.style.SUCCESS(
            f"Scheduler started: reconcile every {reconcile_every}m, "
            f"rollup every {rollup_every}m, nightly rollup at 00:20."))
        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            self.stdout.write("Scheduler stopped.")
