"""Fixed-window rate limiting stored in PostgreSQL.

Each key (for example "login:<ip>:<email>") has a counter for the current one-minute window.
One atomic INSERT ... ON CONFLICT statement both creates and increments the counter, so two
requests at the same moment cannot both read the old count. Because the counter is in the
database it also works when several API processes run side by side.
"""
import hashlib

from sqlalchemy import text

from app import metrics
from app.errors import ApiError


def check_rate_limit(engine, key, max_requests, window_seconds=60):
    # The key can contain an email address, so only its hash is stored.
    bucket_key = hashlib.sha256(key.encode()).hexdigest()

    with engine.begin() as db:
        hits = db.execute(
            text("""
                INSERT INTO rate_limits (bucket_key, hits, window_ends_at)
                VALUES (:key, 1, now() + make_interval(secs => :seconds))
                ON CONFLICT (bucket_key) DO UPDATE SET
                    hits = CASE WHEN rate_limits.window_ends_at <= now() THEN 1
                                ELSE rate_limits.hits + 1 END,
                    window_ends_at = CASE WHEN rate_limits.window_ends_at <= now() THEN EXCLUDED.window_ends_at
                                          ELSE rate_limits.window_ends_at END
                RETURNING hits
            """),
            {"key": bucket_key, "seconds": window_seconds},
        ).scalar_one()

    if hits > max_requests:
        metrics.increment("rate_limited_total")
        raise ApiError(429, "RATE_LIMITED", "Too many requests. Please wait and try again.",
                       headers={"Retry-After": str(window_seconds)})
