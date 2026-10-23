"""Embedded Superset dashboards: the dashboard list and short-lived guest tokens (RLS by site)."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.security import ViewerUser
from app.schemas.misc import DashboardOut, GuestTokenIn, GuestTokenOut
from app.services.superset import SupersetUnavailable, get_superset, unavailable_problem

router = APIRouter(prefix="/superset", tags=["analytics"])


@router.get("/dashboards", response_model=list[DashboardOut], summary="Embeddable dashboards")
async def dashboards(principal: ViewerUser) -> list[DashboardOut]:
    try:
        return await get_superset().dashboards()
    except SupersetUnavailable as exc:
        raise unavailable_problem(exc) from exc


@router.post(
    "/guest-token", response_model=GuestTokenOut, summary="5-minute guest token for one embedded dashboard"
)
async def guest_token(body: GuestTokenIn, principal: ViewerUser) -> GuestTokenOut:
    try:
        return await get_superset().guest_token(body.dashboard, principal)
    except SupersetUnavailable as exc:
        raise unavailable_problem(exc) from exc
