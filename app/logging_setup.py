"""Structured (JSON) logs with the request ID on every line, and redaction of sensitive values.

Rule of thumb: log WHAT happened and WHICH record (ids), never the personal or health data itself.
The redaction below is a safety net in case someone logs a dict by mistake.
"""
import json
import logging
import re
from datetime import UTC, datetime

from app.context import current_request_id

# Any extra field with one of these words in its name is replaced by "[REDACTED]".
SENSITIVE_KEY_PARTS = (
    "password", "token", "secret", "authorization", "api_key", "cookie",
    "date_of_birth", "dob", "address", "postcode", "body", "content", "phone", "email",
    "first_name", "last_name", "preferred_name", "mrn", "payload",
)

# Bearer tokens and signed storage links inside free text are also hidden.
TEXT_PATTERNS = [
    (re.compile(r"(?i)bearer\s+[a-z0-9._~+/=-]+"), "Bearer [REDACTED]"),
    (re.compile(r"/storage/(upload|download)/[A-Za-z0-9._~-]+"), r"/storage/\1/[REDACTED]"),
]

# Attributes every LogRecord has. Anything else was passed with extra={...}.
STANDARD_ATTRIBUTES = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


def is_sensitive_key(key):
    key = key.lower()
    return any(part in key for part in SENSITIVE_KEY_PARTS)


def redact(value, key=""):
    if key and is_sensitive_key(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        for pattern, replacement in TEXT_PATTERNS:
            value = pattern.sub(replacement, value)
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "time": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
            "request_id": current_request_id(),
        }
        for key, value in vars(record).items():
            if key not in STANDARD_ATTRIBUTES and not key.startswith("_"):
                entry[key] = redact(value, key)
        if record.exc_info:
            # The stack trace goes to our logs only, never to the client.
            entry["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(entry, default=str)


def setup_logging(level="INFO"):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # Uvicorn's own access log prints full URLs; ours (in middleware.py) is redacted instead.
    logging.getLogger("uvicorn.access").disabled = True
