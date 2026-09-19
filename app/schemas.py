"""Pieces shared by the request and response models of every module."""
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

from app.pagination import MAX_PAGE_SIZE, PageMeta, PageParams


class StrictModel(BaseModel):
    # extra="forbid" rejects any field we did not list (for example "organisation_id" or "role").
    # This allow-list is how we stop "mass assignment": clients can only send the fields we allow.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Out(BaseModel):
    """Base for responses. Only the fields declared on the model are ever returned."""
    model_config = ConfigDict(from_attributes=True)


Name = Annotated[str, StringConstraints(min_length=1, max_length=100)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=255)]
LongText = Annotated[str, StringConstraints(min_length=1, max_length=20000)]
Phone = Annotated[str, StringConstraints(pattern=r"^\+?[0-9 ()-]{7,20}$")]


def check_password_strength(password):
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        raise ValueError("Password must contain at least one letter and one number.")
    return password


# 10 to 128 characters, with at least one letter and one number.
Password = Annotated[str, Field(min_length=10, max_length=128), AfterValidator(check_password_strength)]


def require_timezone(value: datetime):
    # Appointment times must say which time zone they are in; "10:00" alone is ambiguous.
    if value.tzinfo is None:
        raise ValueError("Include a UTC offset or Z, for example 2026-10-01T09:30:00+01:00.")
    return value


AwareDateTime = Annotated[datetime, AfterValidator(require_timezone)]


class Page(BaseModel):
    meta: PageMeta


class SearchBody(StrictModel):
    """Base for POST .../search endpoints. Search text can be personal data (a name, an email,
    a phone number), so it travels in the request body, never in the URL, where proxies, load
    balancers and browser history could keep it."""
    page: int = Field(1, ge=1, le=10000, description="Page number, starting at 1")
    page_size: int = Field(25, ge=1, le=MAX_PAGE_SIZE, description=f"Items per page (max {MAX_PAGE_SIZE})")

    def paging(self):
        return PageParams(self.page, self.page_size)
