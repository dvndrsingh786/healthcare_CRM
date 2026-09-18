"""One small ASGI middleware that wraps every request. It:

1. gives the request an ID (or keeps a safe X-Request-ID sent by the client),
2. adds standard security headers to every response,
3. writes one redacted access-log line per request (path only, never the query string),
4. turns any unexpected crash into a clean 500 error without internal details.
"""
import logging
import re
import secrets
import time

from app import metrics
from app.context import client_ip_var, request_id_var, user_agent_var
from app.errors import error_response

logger = logging.getLogger("hcrm.access")

SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    # API responses can contain health data, so browsers and proxies must not cache them.
    (b"cache-control", b"no-store"),
]
# The Swagger page loads its scripts from a CDN, so it cannot use the strict policy.
STRICT_CSP = (b"content-security-policy", b"default-src 'none'; frame-ancestors 'none'")
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class RequestContextMiddleware:
    def __init__(self, app, hsts=False):
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if SAFE_REQUEST_ID.match(incoming) else secrets.token_hex(8)
        token = request_id_var.set(request_id)
        client = scope.get("client")
        ip_token = client_ip_var.set(client[0] if client else None)
        agent = dict(scope["headers"]).get(b"user-agent", b"").decode("latin-1")[:255]
        agent_token = user_agent_var.set(agent or None)
        scope.setdefault("state", {})["request_id"] = request_id

        path = scope["path"]
        started = time.perf_counter()
        status_holder = {"status": 500, "started": False}

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                status_holder["status"] = message["status"]
                status_holder["started"] = True
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                headers.extend(SECURITY_HEADERS)
                if not path.startswith(DOCS_PATHS):
                    headers.append(STRICT_CSP)
                if self.hsts:
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception:
            logger.exception("unhandled_error", extra={"method": scope["method"], "path": path})
            if not status_holder["started"]:
                response = error_response(500, "INTERNAL_ERROR", "Internal server error.")
                await response(scope, receive, send_with_headers)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 1)
            metrics.record_request(scope["method"], status_holder["status"], duration_ms)
            logger.info("request", extra={
                "method": scope["method"],
                "path": path,  # redacted by the formatter for signed storage links
                "status": status_holder["status"],
                "duration_ms": duration_ms,
            })
            request_id_var.reset(token)
            client_ip_var.reset(ip_token)
            user_agent_var.reset(agent_token)
