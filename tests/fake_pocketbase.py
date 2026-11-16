"""In-memory PocketBase stand-in that evaluates filters the way PocketBase does.

Only the network edge is faked: callers build their real filter strings and this
fake applies them, so a missing ``site_id`` or ``status`` clause lets the wrong
record through exactly as it would in production. Unsupported filter syntax
fails loudly instead of matching everything.
"""

import math
import re
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

_TOKEN = re.compile(
    r"\s*(?:(?P<lp>\()|(?P<rp>\))|(?P<and>&&)|(?P<or>\|\|)"
    r'|(?P<field>[a-zA-Z_][a-zA-Z0-9_]*)\s*(?P<op>!=|=)\s*"(?P<value>(?:[^"\\]|\\.)*)")'
)


def _tokens(expr: str) -> list[tuple[str, Any]]:
    tokens: list[tuple[str, Any]] = []
    pos = 0
    expr = expr.strip()
    while pos < len(expr):
        match = _TOKEN.match(expr, pos)
        if not match:
            raise AssertionError(f"Fake PocketBase cannot parse filter: {expr!r}")
        if match.group("field"):
            value = re.sub(r"\\(.)", r"\1", match.group("value"))
            tokens.append(("cmp", (match.group("field"), match.group("op"), value)))
        else:
            tokens.append((match.lastgroup, None))
        pos = match.end()
        while pos < len(expr) and expr[pos].isspace():
            pos += 1
    return tokens


def matches(record: dict[str, Any], expr: str | None) -> bool:
    if not expr:
        return True
    tokens = _tokens(expr)
    index = 0

    def parse_or() -> bool:
        nonlocal index
        result = parse_and()
        while index < len(tokens) and tokens[index][0] == "or":
            index += 1
            right = parse_and()
            result = result or right
        return result

    def parse_and() -> bool:
        nonlocal index
        result = parse_atom()
        while index < len(tokens) and tokens[index][0] == "and":
            index += 1
            right = parse_atom()
            result = result and right
        return result

    def parse_atom() -> bool:
        nonlocal index
        kind, payload = tokens[index]
        index += 1
        if kind == "lp":
            result = parse_or()
            if tokens[index][0] != "rp":
                raise AssertionError(f"Unbalanced filter: {expr!r}")
            index += 1
            return result
        if kind != "cmp":
            raise AssertionError(f"Unexpected token {kind} in {expr!r}")
        field, op, value = payload
        actual = record.get(field)
        actual = "" if actual is None else str(actual)
        return actual == value if op == "=" else actual != value

    result = parse_or()
    if index != len(tokens):
        raise AssertionError(f"Trailing tokens in filter: {expr!r}")
    return result


class FakePocketBase:
    def __init__(self, **collections: list[dict[str, Any]]) -> None:
        self._static_token = "static-token"
        self.collections: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows] for name, rows in collections.items()
        }
        self.list_calls: list[tuple[str, str | None]] = []
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.updated: list[tuple[str, str, dict[str, Any]]] = []
        self._clock = 0

    def _now(self) -> str:
        # The real client stamps created_at/updated_at itself; keep them ordered.
        self._clock += 1
        return f"2026-11-16T12:00:00.{self._clock:06d}Z"

    async def list_records(
        self,
        collection: str,
        token: str | None = None,
        filter: str | None = None,
        sort: str | None = None,
        page: int = 1,
        per_page: int = 50,
        expand: str | None = None,
    ) -> dict[str, Any]:
        self.list_calls.append((collection, filter))
        rows = [r for r in self.collections.get(collection, []) if matches(r, filter)]
        if sort:
            for key in reversed(sort.split(",")):
                descending = key.startswith("-")
                name = key.lstrip("-+")
                rows.sort(key=lambda r: str(r.get(name) or ""), reverse=descending)
        total_pages = max(1, math.ceil(len(rows) / per_page))
        start = (page - 1) * per_page
        return {
            "items": rows[start : start + per_page],
            "page": page,
            "perPage": per_page,
            "totalItems": len(rows),
            "totalPages": total_pages,
        }

    async def find_one_by_filter(
        self,
        collection: str,
        filter_expr: str,
        token: str | None = None,
        expand: str | None = None,
    ) -> dict[str, Any]:
        result = await self.list_records(collection, filter=filter_expr, per_page=1)
        if not result["items"]:
            raise HTTPException(status_code=404, detail="Record not found")
        return result["items"][0]

    async def create_record(
        self,
        collection: str,
        data: dict[str, Any],
        token: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        now = self._now()
        record = {
            "id": f"rec_{uuid4().hex[:12]}",
            "deleted_at": "",
            **data,
            "created_at": now,
            "updated_at": now,
        }
        self.collections.setdefault(collection, []).append(record)
        self.created.append((collection, data))
        return dict(record)

    async def update_record(
        self,
        collection: str,
        record_id: str,
        data: dict[str, Any],
        token: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        for record in self.collections.get(collection, []):
            if record["id"] == record_id:
                record.update(data, updated_at=self._now())
                self.updated.append((collection, record_id, data))
                return dict(record)
        raise HTTPException(status_code=404, detail="Record not found")
