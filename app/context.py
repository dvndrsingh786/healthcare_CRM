"""Facts about the request being handled right now.

They are set by the middleware and read by the logger, the error handlers and the audit log,
so every log line, error response and audit event can be matched to one request.
"""
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")
client_ip_var: ContextVar[str | None] = ContextVar("client_ip", default=None)
user_agent_var: ContextVar[str | None] = ContextVar("user_agent", default=None)


def current_request_id():
    return request_id_var.get()


def current_client():
    return {"ip_address": client_ip_var.get(), "user_agent": user_agent_var.get(),
            "request_id": request_id_var.get()}
