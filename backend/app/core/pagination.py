"""Opaque cursor (keyset) pagination for every list endpoint.

Query: `limit` (default 50, max 500) and `cursor`. Response: `{"items": [...], "next_cursor": str | null}`.
A cursor encodes the sort-key values of the last row returned, plus a tag naming the sort, so the next
page continues after that row even while rows are being added. Sort keys always end with a unique column,
which makes the order total and stable: walking every cursor returns every row exactly once.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any

from fastapi import Query
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Row, Select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import QueryableAttribute

from app.core.problems import Problem

# Any SELECT / result row, whatever its column types (SQLAlchemy 2.1 types them as variadic tuples).
type AnySelect = Select[*tuple[Any, ...]]
type AnyRow = Row[*tuple[Any, ...]]

DEFAULT_LIMIT = 50
MAX_LIMIT = 500


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


@dataclass(frozen=True)
class PageParams:
    limit: int = DEFAULT_LIMIT
    cursor: str | None = None


def page_params(
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT, description="Page size (max 500).")] = DEFAULT_LIMIT,
    cursor: Annotated[
        str | None, Query(max_length=2048, description="`next_cursor` from the previous page.")
    ] = None,
) -> PageParams:
    return PageParams(limit=limit, cursor=cursor)


@dataclass(frozen=True)
class SortKey:
    """One ORDER BY term. The expression must never be NULL (wrap nullable columns in coalesce)."""

    expr: ColumnElement[Any] | QueryableAttribute[Any]
    descending: bool = False


def _encode_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"dt": value.isoformat()}
    return value


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"dt"}:
        return datetime.fromisoformat(str(value["dt"]))
    return value


def encode_cursor(tag: str, values: Sequence[Any]) -> str:
    raw = json.dumps({"k": tag, "v": [_encode_value(v) for v in values]}, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str, tag: str, size: int) -> list[Any]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        values = data["v"]
        if data["k"] != tag or not isinstance(values, list) or len(values) != size:
            raise ValueError("cursor does not match this list")
        return [_decode_value(v) for v in values]
    except (ValueError, KeyError, TypeError, binascii.Error, UnicodeDecodeError) as exc:
        raise Problem(
            422,
            "The cursor is invalid or belongs to a different list or sort order.",
            errors=[{"loc": ["query", "cursor"], "msg": str(exc), "type": "value_error"}],
        ) from exc


def _after(keys: Sequence[SortKey], values: Sequence[Any]) -> ColumnElement[bool]:
    """Rows strictly after `values` in the (possibly mixed-direction) key order."""
    terms: list[ColumnElement[bool]] = []
    for i, key in enumerate(keys):
        equal = [keys[j].expr == values[j] for j in range(i)]
        beyond = key.expr < values[i] if key.descending else key.expr > values[i]
        terms.append(and_(*equal, beyond))
    return or_(*terms)


async def paginate(
    session: AsyncSession,
    stmt: AnySelect,
    keys: Sequence[SortKey],
    params: PageParams,
    tag: str,
) -> tuple[list[AnyRow], str | None]:
    """Run `stmt` for one page. Returns the rows (with the sort keys appended) and the next cursor."""
    labels = [f"_pg{i}" for i in range(len(keys))]
    stmt = stmt.add_columns(*[k.expr.label(label) for k, label in zip(keys, labels, strict=True)])
    if params.cursor:
        stmt = stmt.where(_after(keys, decode_cursor(params.cursor, tag, len(keys))))
    stmt = stmt.order_by(*[k.expr.desc() if k.descending else k.expr.asc() for k in keys])
    rows = list((await session.execute(stmt.limit(params.limit + 1))).all())
    next_cursor: str | None = None
    if len(rows) > params.limit:
        rows = rows[: params.limit]
        last = rows[-1]._mapping
        next_cursor = encode_cursor(tag, [last[label] for label in labels])
    return rows, next_cursor
