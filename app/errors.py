"""Every error leaves the API in the same shape:

    {"error": {"code": "FORBIDDEN", "message": "...", "request_id": "...", "fields": [...]}}

`code` is stable and machine-readable, so the mobile/web app can tell validation,
authentication, forbidden, conflict and temporary failures apart without parsing text.
We never send stack traces, SQL or submitted values back to the client.
"""
import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.context import current_request_id

logger = logging.getLogger("hcrm.errors")


class ApiError(Exception):
    """Raise this anywhere in the code to return a clean error response."""

    def __init__(self, status_code, code, message, fields=None, headers=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.fields = fields
        self.headers = headers


# Short helpers for the errors we use most.

def not_found(what="Resource"):
    # Used for records that do not exist AND for records the caller may not see,
    # so nobody can find out that a record with a guessed id exists.
    return ApiError(404, "NOT_FOUND", f"{what} not found.")


def forbidden(message="You do not have access to this resource."):
    return ApiError(403, "FORBIDDEN", message)


def conflict(message, code="CONFLICT"):
    return ApiError(409, code, message)


def invalid(message, field=None, code="VALIDATION_ERROR"):
    fields = [{"field": field, "message": message}] if field else None
    return ApiError(422, code, message, fields=fields)


# ---------- What errors look like (used in the OpenAPI documentation) ----------

class FieldError(BaseModel):
    field: str
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    fields: list[FieldError] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


def _example(code, message):
    return {"application/json": {"example": {"error": {
        "code": code, "message": message, "request_id": "5f0c2a9e1b7d4c3a"}}}}


# Added to every router in main.py, so /docs lists the possible errors for each endpoint.
ERROR_RESPONSES = {
    400: {"model": ErrorResponse, "description": "Body is not valid JSON (INVALID_JSON)",
          "content": _example("INVALID_JSON", "The request body is not valid JSON.")},
    401: {"model": ErrorResponse, "description": "Missing, invalid, expired or revoked credentials (UNAUTHENTICATED)",
          "content": _example("UNAUTHENTICATED", "Your session is invalid or has expired.")},
    403: {"model": ErrorResponse, "description": "Authenticated but not allowed (FORBIDDEN)",
          "content": _example("FORBIDDEN", "You do not have access to this resource.")},
    404: {"model": ErrorResponse, "description": "Not found, or not visible to you (NOT_FOUND)",
          "content": _example("NOT_FOUND", "Patient not found.")},
    409: {"model": ErrorResponse, "description": "Conflict: duplicate, stale version or invalid state (CONFLICT, ...)",
          "content": _example("CONFLICT", "This conflicts with existing data.")},
    422: {"model": ErrorResponse, "description": "Invalid input, with one entry per field (VALIDATION_ERROR)",
          "content": _example("VALIDATION_ERROR", "Validation failed.")},
    429: {"model": ErrorResponse, "description": "Too many requests (RATE_LIMITED)",
          "content": _example("RATE_LIMITED", "Too many requests. Please wait and try again.")},
    503: {"model": ErrorResponse, "description": "Temporary failure, safe to retry later (TEMPORARY_FAILURE)",
          "content": _example("TEMPORARY_FAILURE", "The service is temporarily unavailable.")},
}

# Codes for plain HTTP errors raised by FastAPI/Starlette itself (for example 404 for an unknown URL).
STATUS_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    429: "RATE_LIMITED",
    503: "TEMPORARY_FAILURE",
}


def error_response(status_code, code, message, fields=None, headers=None):
    body = {"code": code, "message": message, "request_id": current_request_id()}
    if fields:
        body["fields"] = fields
    return JSONResponse(status_code=status_code, content={"error": body}, headers=headers)


def add_error_handlers(app):

    @app.exception_handler(ApiError)
    def api_error(request: Request, error: ApiError):
        return error_response(error.status_code, error.code, error.message, error.fields, error.headers)

    @app.exception_handler(StarletteHTTPException)
    def http_error(request: Request, error: StarletteHTTPException):
        code = STATUS_CODES.get(error.status_code, "ERROR")
        message = error.detail if isinstance(error.detail, str) else "Request failed."
        return error_response(error.status_code, code, message, headers=getattr(error, "headers", None))

    @app.exception_handler(RequestValidationError)
    def validation_error(request: Request, error: RequestValidationError):
        if any(item["type"] == "json_invalid" for item in error.errors()):
            return error_response(400, "INVALID_JSON", "The request body is not valid JSON.")

        fields = []
        for item in error.errors():
            # item["loc"] looks like ("body", "email") or ("query", "page_size").
            # We drop the first part so the client just sees "email" or "page_size".
            field = ".".join(str(part) for part in item["loc"][1:]) or str(item["loc"][0])
            fields.append({"field": field, "message": item["msg"]})
        # We do not echo back the submitted values, so passwords and health data never appear here.
        return error_response(422, "VALIDATION_ERROR", "Validation failed.", fields)

    @app.exception_handler(IntegrityError)
    def integrity_error(request: Request, error: IntegrityError):
        # Log only the constraint name, never the row values (they can contain patient data).
        constraint = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
        logger.warning("integrity_error", extra={"constraint": constraint})
        return error_response(409, "CONFLICT", "This conflicts with existing data.")

    @app.exception_handler(OperationalError)
    def database_unavailable(request: Request, error: OperationalError):
        logger.error("database_unavailable")
        return error_response(503, "TEMPORARY_FAILURE", "The service is temporarily unavailable. Please retry.")
