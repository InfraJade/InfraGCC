"""RFC 9457 problem details for every error response (app API and ingest API)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_MEDIA_TYPE = "application/problem+json"
_TYPE_BASE = "https://gcc.example/problems/"

_TITLES = {
    400: "Bad request",
    401: "Not authenticated",
    403: "Forbidden",
    404: "Not found",
    405: "Method not allowed",
    409: "Conflict",
    413: "Payload too large",
    415: "Unsupported media type",
    422: "Validation failed",
    429: "Too many requests",
    500: "Internal server error",
    502: "Bad gateway",
    503: "Service unavailable",
}


class Problem(Exception):
    """Raise anywhere in a request to return `application/problem+json`."""

    def __init__(
        self,
        status: int,
        detail: str | None = None,
        *,
        type_: str | None = None,
        title: str | None = None,
        headers: dict[str, str] | None = None,
        **extensions: Any,
    ) -> None:
        super().__init__(detail or title or _TITLES.get(status, "Error"))
        self.status = status
        self.detail = detail
        self.type = type_ or (_TYPE_BASE + _slug(title or _TITLES.get(status, "error")))
        self.title = title or _TITLES.get(status, "Error")
        self.headers = headers
        self.extensions = extensions

    def body(self, instance: str | None = None) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type, "title": self.title, "status": self.status}
        if self.detail:
            out["detail"] = self.detail
        if instance:
            out["instance"] = instance
        out.update(self.extensions)
        return out


def _slug(text: str) -> str:
    return "-".join(text.lower().split())


def problem_response(problem: Problem, request: Request | None = None) -> JSONResponse:
    instance = request.url.path if request is not None else None
    return JSONResponse(
        problem.body(instance),
        status_code=problem.status,
        media_type=PROBLEM_MEDIA_TYPE,
        headers=problem.headers,
    )


async def _problem_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, Problem)
    return problem_response(exc, request)


async def _http_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    detail = exc.detail if isinstance(exc.detail, str) else None
    headers = dict(exc.headers) if exc.headers else None
    return problem_response(Problem(exc.status_code, detail, headers=headers), request)


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"loc": [str(p) for p in e.get("loc", ())], "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return problem_response(Problem(422, "The request did not pass validation.", errors=errors), request)


def install_problem_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Problem, _problem_handler)
    app.add_exception_handler(StarletteHTTPException, _http_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
