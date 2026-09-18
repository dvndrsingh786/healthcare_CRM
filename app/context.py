"""The request ID of the request being handled right now.

It is set by the middleware and read by the logger and the error handlers,
so every log line and every error response can be matched to one request.
"""
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def current_request_id():
    return request_id_var.get()
