"""Pagination and sorting shared by every list endpoint.

- page_size has a hard server maximum (100), so nobody can download a whole table in one call.
- Sorting only accepts keys from an allow-list, e.g. ?sort=-updated_at (the minus means newest first).
- Pagination is applied AFTER the permission filters, so it can never widen what a caller sees.
"""
import math
from dataclasses import dataclass

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import text

from app.errors import invalid

MAX_PAGE_SIZE = 100


@dataclass
class PageParams:
    page: int
    page_size: int


def page_params(
    page: int = Query(1, ge=1, le=10000, description="Page number, starting at 1"),
    page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE, description=f"Items per page (max {MAX_PAGE_SIZE})"),
):
    return PageParams(page, page_size)


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int


def order_by(sort, allowed, default, tiebreak="id"):
    """Turn "?sort=-updated_at" into "ORDER BY updated_at DESC, id DESC".

    allowed maps the public sort key to a real column, e.g. {"updated_at": "p.updated_at"}.
    The column names come from our code, never from the client.
    """
    sort = sort or default
    direction = "DESC" if sort.startswith("-") else "ASC"
    key = sort.lstrip("-")
    if key not in allowed:
        raise invalid(f"sort must be one of: {', '.join(sorted(allowed))} (prefix with - for descending).",
                      field="sort")
    # The id tie-breaker keeps the order stable between pages.
    return f"ORDER BY {allowed[key]} {direction}, {tiebreak} {direction}"


def paginate(db, select_sql, count_sql, params, paging, serialize=dict):
    total = db.execute(text(count_sql), params).scalar_one()
    page_params_ = dict(params, limit=paging.page_size, offset=(paging.page - 1) * paging.page_size)
    rows = db.execute(text(select_sql + " LIMIT :limit OFFSET :offset"), page_params_).mappings().all()
    return {
        "data": [serialize(row) for row in rows],
        "meta": {
            "page": paging.page,
            "page_size": paging.page_size,
            "total": total,
            "total_pages": math.ceil(total / paging.page_size),
        },
    }


def like_pattern(search):
    """Turn a search word into an ILIKE pattern: john -> %john%.

    % and _ are special in LIKE, so they are escaped first; otherwise "%" would match everything.
    """
    search = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{search}%"
