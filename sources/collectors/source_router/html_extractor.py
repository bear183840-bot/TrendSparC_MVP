"""Firecrawl — HTML source → Clean Markdown. doc1 §10.

Reuses the shared FIRECRAWL_API_KEY (already sector-agnostic, see
sources/collectors/kofic_pdf.py and every sector's Firecrawl-based
collector) rather than minting a new dedicated env var for this package.

*** Rate-limit pacing — added 2026-08-11 ***
This is the only Firecrawl call site in the source_router package, so it is
also the only place that can pace it. A live run lost two sources outright
to `Rate Limit Exceeded ... Consumed (req/min): 20, Remaining (req/min): 0`
after router.py's eager direct-batch inspection fired its scrapes back to
back with nothing in between. Note the limit that actually applied there was
20/min, not the ~10-11/min CLAUDE.md documents — that figure predates this
plan, so the window below is set from the observed number with headroom
rather than from the doc.

Two independent guards, because they cover different failures:
  - a sliding-window gate that *avoids* the limit (costs nothing until a
    burst would actually exceed it — a run that scrapes five URLs never
    sleeps), and
  - a bounded retry that *recovers* from it when the gate's accounting is
    wrong anyway, which it can be: this process shares one FIRECRAWL_API_KEY
    with every sector collector, and the counter here only sees its own
    calls.
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
from collections import deque

_API_KEY_ENV_VAR = "FIRECRAWL_API_KEY"

# Set below the 20/min the API actually reported so a sector collector
# scraping on the same key at the same time doesn't push the shared account
# over on its own.
_MAX_SCRAPES_PER_WINDOW = 15
_WINDOW_SECONDS = 60.0
# Never block a single call for longer than this, whatever the arithmetic
# says — a stuck pacer silently stalling a run is worse than one scrape
# racing the limit and getting the retry path below.
_MAX_PACING_SLEEP_SECONDS = 30.0

_RATE_LIMIT_RETRY_ATTEMPTS = 2
_DEFAULT_RATE_LIMIT_BACKOFF_SECONDS = 5.0
_MAX_RATE_LIMIT_BACKOFF_SECONDS = 30.0

_recent_scrape_starts: deque[float] = deque()
_pacing_lock = threading.Lock()


def _reset_pacing_state() -> None:
    """Test seam — clears the sliding window between cases so one test's
    recorded calls can't pace another's."""
    with _pacing_lock:
        _recent_scrape_starts.clear()


def _seconds_until_scrape_slot(now: float) -> float:
    """Reserves a slot, returning how long the caller must sleep first (0.0
    when the window has room). Prunes entries that have aged out."""
    with _pacing_lock:
        while _recent_scrape_starts and now - _recent_scrape_starts[0] >= _WINDOW_SECONDS:
            _recent_scrape_starts.popleft()
        if len(_recent_scrape_starts) < _MAX_SCRAPES_PER_WINDOW:
            _recent_scrape_starts.append(now)
            return 0.0
        wait = _WINDOW_SECONDS - (now - _recent_scrape_starts[0])
        # Record the slot at the time it will actually be used, so the next
        # caller's arithmetic accounts for this one instead of double-booking.
        _recent_scrape_starts.append(now + wait)
        return min(max(wait, 0.0), _MAX_PACING_SLEEP_SECONDS)


def _wait_for_scrape_slot() -> None:
    wait = _seconds_until_scrape_slot(time.monotonic())
    if wait <= 0:
        return
    print(
        f"[source_router.html_extractor] pacing: {_MAX_SCRAPES_PER_WINDOW} scrapes already "
        f"started within {int(_WINDOW_SECONDS)}s, waiting {wait:.1f}s for a slot",
        file=sys.stderr,
    )
    time.sleep(wait)


def _is_rate_limit_error(message: str) -> bool:
    return "rate limit" in message.casefold()


def _retry_after_seconds(message: str) -> float:
    """Firecrawl states its own backoff in the error text ("please retry
    after 3s") — honor that number when present rather than guessing."""
    match = re.search(r"retry after (\d+(?:\.\d+)?)\s*s", message, flags=re.IGNORECASE)
    if not match:
        return _DEFAULT_RATE_LIMIT_BACKOFF_SECONDS
    return min(float(match.group(1)), _MAX_RATE_LIMIT_BACKOFF_SECONDS)


def extract_html(url: str, *, timeout_seconds: int = 120) -> str | None:
    """Return clean markdown for a URL, or None on any failure (missing key,
    network error, empty content). A miss means "still needs full text" to
    the caller, never a crash."""
    api_key = os.environ.get(_API_KEY_ENV_VAR, "").strip()
    if not api_key:
        print("[source_router.html_extractor] FIRECRAWL_API_KEY not set", file=sys.stderr)
        return None

    document = None
    for attempt in range(_RATE_LIMIT_RETRY_ATTEMPTS + 1):
        _wait_for_scrape_slot()
        try:
            from firecrawl import Firecrawl  # imported lazily — unit tests don't need network/API setup

            client = Firecrawl(api_key=api_key, timeout=timeout_seconds, max_retries=1)
            document = client.scrape(url, formats=["markdown"])
            break
        except Exception as exc:  # noqa: BLE001
            message = str(exc)
            if attempt < _RATE_LIMIT_RETRY_ATTEMPTS and _is_rate_limit_error(message):
                backoff = _retry_after_seconds(message)
                print(
                    f"[source_router.html_extractor] rate limited on {url}, retrying in "
                    f"{backoff:.1f}s (attempt {attempt + 1}/{_RATE_LIMIT_RETRY_ATTEMPTS})",
                    file=sys.stderr,
                )
                time.sleep(backoff)
                continue
            print(f"[source_router.html_extractor] scrape failed for {url}: {exc}", file=sys.stderr)
            return None

    markdown = getattr(document, "markdown", None)
    if not markdown and isinstance(document, dict):
        markdown = document.get("markdown")
    return markdown or None
