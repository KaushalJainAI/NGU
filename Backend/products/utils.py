import threading
import asyncio
import logging
from django.conf import settings
from django.db import close_old_connections

logger = logging.getLogger(__name__)

def run_in_background(target, *args, **kwargs):
    """
    Run a function in a background thread. This is useful for moving long-running
    I/O bound operations (like calling external APIs) off the main request thread
    so the web application does not hang.

    If the target function is asynchronous, this utility will wrap it in an asyncio loop.
    Crucially, it safely closes database connections when the thread completes to prevent pool exhaustion.

    Skipped under TESTING: the thread runs on its own DB connection that cannot
    see a test's rolled-back transaction (causing FK errors), and would make
    real LLM calls. Code that needs the work in tests should call the target
    (e.g. ensure_search_kb) directly.
    """
    if getattr(settings, 'TESTING', False):
        return None

    def wrapper():
        try:
            if asyncio.iscoroutinefunction(target):
                # Setup a new event loop for this thread if strictly necessary
                # or just use asyncio.run to execute the coroutine
                asyncio.run(target(*args, **kwargs))
            else:
                target(*args, **kwargs)
        except Exception as e:
            logger.error(f"Background task {target.__name__} failed: {e}", exc_info=True)
        finally:
            # IMPORTANT: Clean up database connections for this thread
            # so we don't leak connection objects and deplete the Postgres/SQLite pool.
            close_old_connections()
            
    thread = threading.Thread(target=wrapper, daemon=True)
    thread.start()
    return thread
