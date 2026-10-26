"""Reading request bodies with a size limit, gzip-aware (guards against oversized and gzip-bomb bodies)."""

from __future__ import annotations

import zlib

from fastapi import Request

from app.core.problems import Problem

_GZIP_MAGIC = b"\x1f\x8b"


def _too_large(limit: int) -> Problem:
    return Problem(413, f"Body exceeds {limit} bytes.")


async def read_body(request: Request, limit: int) -> bytes:
    declared = request.headers.get("Content-Length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise _too_large(limit)
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise _too_large(limit)
        chunks.append(chunk)
    raw = b"".join(chunks)

    encoding = request.headers.get("Content-Encoding", "identity").strip().lower()
    if encoding not in ("", "identity", "gzip", "x-gzip"):
        raise Problem(415, f"Content-Encoding {encoding!r} is not supported; use gzip or none.")
    if encoding in ("gzip", "x-gzip") or raw.startswith(_GZIP_MAGIC):
        return gunzip_limited(raw, limit)
    return raw


def gunzip_limited(data: bytes, limit: int) -> bytes:
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = decompressor.decompress(data, limit + 1)
    except zlib.error as exc:
        raise Problem(400, f"Body is not valid gzip: {exc}") from exc
    if len(out) > limit or decompressor.unconsumed_tail:
        raise _too_large(limit)
    if not decompressor.eof:
        raise Problem(400, "Body is not valid gzip: truncated stream.")
    return out
