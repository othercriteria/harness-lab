"""Whole-stage deadlines and cooperative cancellation for trusted owners."""

import contextlib
import signal


class DeadlineExceeded(Exception):
    pass


class RunCancelled(BaseException):
    pass


class UnsafeCleanup(BaseException):
    """Abort the campaign; unverified isolation cleanup is not a task failure."""


@contextlib.contextmanager
def deadline(seconds):
    def expired(signum, frame):
        raise DeadlineExceeded("Whole-stage wall deadline expired")

    if seconds <= 0:
        raise DeadlineExceeded("No wall budget remaining")
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


@contextlib.contextmanager
def cancellation():
    def cancelled(signum, frame):
        raise RunCancelled(f"Cancelled by signal {signum}")

    previous = {
        sig: signal.signal(sig, cancelled)
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
    }
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
