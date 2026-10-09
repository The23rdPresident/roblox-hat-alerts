#!/usr/bin/env python3
"""Continuous worker: checks every 30 seconds by default, without third-party packages."""

import signal
import sys
import threading
import time

import price_alert


def main():
    import os

    try:
        interval = int(os.environ.get("CHECK_EVERY", "30"))
    except ValueError:
        raise SystemExit("CHECK_EVERY must be a whole number of seconds.")
    if interval < 10:
        raise SystemExit("CHECK_EVERY must be at least 10 seconds.")
    price_alert.validate_settings()
    stopping = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stopping.set())

    price_alert.log(f"Watching {len(price_alert.WATCHLIST)} hats; starting a check about every {interval} seconds.")
    if price_alert.TEST_ALERT:
        if not price_alert.send_test_alert():
            raise SystemExit(1)
        price_alert.TEST_ALERT = False  # Never repeat the test on every polling round.
    price_alert.MANUAL_RUN = False

    while not stopping.is_set():
        started = time.monotonic()
        backoff = price_alert.main()
        elapsed = time.monotonic() - started
        stopping.wait(max(1, interval - elapsed, backoff))
    price_alert.log("Price watcher stopped.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
