#!/usr/bin/env python
"""
Full test pyramid + security audit orchestrator for NGU.

Runs, in order, capturing one combined transcript:

  1. UNIT + INTEGRATION  - the in-process Django suite (Backend/, SQLite test DB)
  2. E2E + SECURITY       - spins up a local live server (file SQLite, seeded)
                            and runs the black-box HTTP suite (testing/) at it

The transcript is written to testing/reports/session_transcript.txt and is the
input to tools/make_video.py.

Razorpay/payment capture flows are intentionally out of scope (no live gateway).

Usage (from anywhere):
    python testing/tools/run_full_audit.py
Options:
    --skip-unit     skip phase 1
    --skip-e2e      skip phase 2
    --port 8011     port for the local e2e server
"""
import argparse
import datetime as dt
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TESTING_DIR = HERE.parent
REPO = TESTING_DIR.parent
BACKEND = REPO / "Backend"
REPORTS = TESTING_DIR / "reports"
REPORTS.mkdir(exist_ok=True)
TRANSCRIPT = REPORTS / "session_transcript.txt"

PY = sys.executable
VENV_PY = BACKEND / "venv" / "Scripts" / "python.exe"
if VENV_PY.exists():
    PY = str(VENV_PY)


class Tee:
    def __init__(self, path):
        self.fh = open(path, "w", encoding="utf-8")

    def write(self, text):
        sys.stdout.write(text)
        sys.stdout.flush()
        self.fh.write(text)
        self.fh.flush()

    def banner(self, title):
        bar = "=" * 78
        self.write(f"\n{bar}\n=== {title}\n{bar}\n")

    def close(self):
        self.fh.close()


def run(cmd, tee, cwd=None, env=None, timeout=1800):
    import threading

    tee.write(f"\n$ {' '.join(str(c) for c in cmd)}\n")
    proc = subprocess.Popen(
        cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1,
    )
    # Watchdog: if the child hangs producing no EOF, the stdout read loop below
    # would block forever — so a timer kills the process, which closes stdout and
    # lets the loop (and this function) return.
    timed_out = {"v": False}

    def _kill():
        timed_out["v"] = True
        try:
            proc.kill()
        except Exception:
            pass

    timer = threading.Timer(timeout, _kill)
    timer.start()
    try:
        for line in proc.stdout:
            tee.write(line)
        proc.wait()
    finally:
        timer.cancel()
    if timed_out["v"]:
        tee.write(f"\n[orchestrator] TIMEOUT after {timeout}s — process killed\n")
        return 124
    return proc.returncode


def wait_for_health(url, tee, attempts=40):
    import urllib.request
    for i in range(attempts):
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                if r.status == 200:
                    tee.write(f"[orchestrator] server healthy after {i+1} tries\n")
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def free_port(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


# Previously assistant/test_chat_and_tools.py was quarantined (Product.save() infinite
# slug-retry loop deadlocked under load). Fixed in products/models.py
# (_generate_unique_slug) + offline test storage, so the full suite now runs.
QUARANTINE = []


def phase_unit(tee):
    tee.banner("PHASE 1 — UNIT + INTEGRATION  (Django suite, Postgres test DB)")
    # The full suite hits SQLite ":memory:" lock failures under load (see
    # test_settings docstring), so we run against the local docker Postgres.
    env = dict(
        os.environ,
        TEST_DB="postgres",
        DB_ENGINE=os.environ.get("DB_ENGINE", "django.db.backends.postgresql"),
        DB_NAME=os.environ.get("DB_NAME", "ngu_local"),
        DB_USER=os.environ.get("DB_USER", "ngu"),
        DB_PASSWORD=os.environ.get("DB_PASSWORD", "ngu_local_pw"),
        DB_HOST=os.environ.get("DB_HOST", "127.0.0.1"),
        DB_PORT=os.environ.get("DB_PORT", "5432"),
        PYTHONUNBUFFERED="1",
    )
    return run([PY, "-u", "-m", "pytest", "-p", "no:cacheprovider", "-q",
                "--no-header", "-o", "addopts=", "--timeout=120", *QUARANTINE],
               tee, cwd=str(BACKEND), env=env, timeout=2400)


def phase_e2e(tee, port):
    tee.banner("PHASE 2 — E2E + SECURITY  (black-box HTTP against local server)")
    base_url = f"http://127.0.0.1:{port}"
    settings = "spices_backend.e2e_settings"
    env = dict(
        os.environ,
        DJANGO_SETTINGS_MODULE=settings,
        USE_CLOUDINARY="False",
        USE_S3="False",
        SECRET_KEY="e2e-insecure-do-not-use-in-prod",
        PYTHONUNBUFFERED="1",
    )

    # Fresh DB each run for determinism.
    db = BACKEND / "e2e_db.sqlite3"
    if db.exists():
        db.unlink()

    tee.write("[orchestrator] migrating e2e database...\n")
    rc = run([PY, "manage.py", "migrate", "--noinput", f"--settings={settings}"],
             tee, cwd=str(BACKEND), env=env, timeout=600)
    if rc != 0:
        tee.write("[orchestrator] migrate failed — aborting phase 2\n")
        return rc

    tee.write("[orchestrator] seeding catalog...\n")
    run([PY, str(HERE / "seed_e2e.py")], tee, cwd=str(BACKEND), env=env, timeout=300)

    if not free_port(port):
        tee.write(f"[orchestrator] port {port} busy — aborting\n")
        return 1

    tee.write(f"[orchestrator] launching server on {base_url} ...\n")
    server = subprocess.Popen(
        [PY, "manage.py", "runserver", f"127.0.0.1:{port}", "--noreload",
         f"--settings={settings}"],
        cwd=str(BACKEND), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_for_health(f"{base_url}/api/health/", tee):
            tee.write("[orchestrator] server did not become healthy — aborting\n")
            return 1
        test_env = dict(os.environ, NGU_BASE_URL=base_url, NGU_IS_PROD="0",
                        NGU_TIMEOUT="20", PYTHONUNBUFFERED="1")
        return run([PY, "-u", "-m", "pytest", "-q", "-o", "addopts=-v --tb=short",
                    "e2e", "security"], tee, cwd=str(TESTING_DIR), env=test_env,
                   timeout=900)
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
        tee.write("[orchestrator] server stopped\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-unit", action="store_true")
    ap.add_argument("--skip-e2e", action="store_true")
    ap.add_argument("--port", type=int, default=8011)
    args = ap.parse_args()

    tee = Tee(TRANSCRIPT)
    start = dt.datetime.now()
    tee.write(f"NGU automated test & security audit\n")
    tee.write(f"started: {start:%Y-%m-%d %H:%M:%S}\n")
    tee.write(f"python : {PY}\n")

    results = {}
    if not args.skip_unit:
        results["unit+integration"] = phase_unit(tee)
    if not args.skip_e2e:
        results["e2e+security"] = phase_e2e(tee, args.port)

    tee.banner("SUMMARY")
    overall = 0
    for name, rc in results.items():
        status = "PASS" if rc == 0 else f"FAIL (rc={rc})"
        overall = overall or rc
        tee.write(f"  {name:<20} {status}\n")
    elapsed = (dt.datetime.now() - start).total_seconds()
    tee.write(f"\nelapsed: {elapsed:.0f}s\n")
    tee.write(f"transcript: {TRANSCRIPT}\n")
    tee.close()
    sys.exit(overall)


if __name__ == "__main__":
    main()
