"""Sign-in, roles and site scope for the app API.

Every request carries an OIDC access token (Keycloak in dev, any OIDC IdP in prod; DECISIONS D20). The
token's signature is checked against the IdP's JWKS (keys cached), plus issuer, audience and expiry.

Roles come from IdP groups through `role_group_map`; the highest role wins. Analysts have Viewer rights in
the app (D21). Site limits come from `gcc-site-<CODE>` groups; a user with no site group sees all sites.
Objects outside a user's sites are reported as 404, exactly like objects that do not exist.

The first request of each token session (`sid`) upserts the `users` row and writes one `user.login`
audit entry.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import ColumnElement, false, or_, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core import audit
from app.core.config import Settings, get_settings
from app.core.db import get_sessionmaker
from app.core.enums import Role
from app.core.problems import Problem
from app.core.ratelimit import check_rate_limit
from app.models import Site, User

log = logging.getLogger("gcc.security")

# Viewer and Analyst share the lowest app level (D21); each higher role includes everything below it.
ROLE_LEVEL: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.ANALYST: 0,
    Role.NOC_OPERATOR: 1,
    Role.DC_ENGINEER: 2,
    Role.PLATFORM_ADMIN: 3,
}
ROLE_LABEL: dict[Role, str] = {
    Role.VIEWER: "Viewer",
    Role.ANALYST: "Analyst",
    Role.NOC_OPERATOR: "NOC operator",
    Role.DC_ENGINEER: "DC engineer",
    Role.PLATFORM_ADMIN: "Platform admin",
}
_ROLE_ORDER = [Role.PLATFORM_ADMIN, Role.DC_ENGINEER, Role.NOC_OPERATOR, Role.ANALYST, Role.VIEWER]
_CLOCK_LEEWAY_S = 30


class AuthError(Exception):
    """The token is missing, malformed, expired or not issued for this API."""


@dataclass(frozen=True)
class Principal:
    sub: str
    username: str
    name: str
    email: str | None
    roles: frozenset[Role]
    # None = unrestricted (all sites); otherwise the site codes/ids the user may see.
    site_codes: frozenset[str] | None
    site_ids: frozenset[int] | None
    session_id: str
    expires_at: datetime

    @property
    def display_name(self) -> str:
        return self.name or self.username or self.sub

    @property
    def level(self) -> int:
        return max((ROLE_LEVEL[r] for r in self.roles), default=-1)

    @property
    def primary_role(self) -> Role | None:
        return next((r for r in _ROLE_ORDER if r in self.roles), None)

    @property
    def restricted(self) -> bool:
        return self.site_ids is not None

    def has_role(self, minimum: Role) -> bool:
        return self.level >= ROLE_LEVEL[minimum]

    def can_see_site(self, site_id: int | None) -> bool:
        if self.site_ids is None:
            return True
        return site_id is not None and site_id in self.site_ids

    def site_filter(self, column: Any, *, include_global: bool = False) -> ColumnElement[bool]:
        """WHERE clause limiting `column` (a site id) to this user's sites.

        `include_global` also lets through rows whose site is NULL (objects that apply to every site).
        """
        if self.site_ids is None:
            return true()
        allowed: ColumnElement[bool] = column.in_(sorted(self.site_ids)) if self.site_ids else false()
        return or_(column.is_(None), allowed) if include_global else allowed


def not_found(kind: str = "Object") -> Problem:
    return Problem(404, f"{kind} not found.")


def ensure_site(principal: Principal, site_id: int | None, kind: str = "Object") -> None:
    """404 when the object's site is outside the user's scope (indistinguishable from missing)."""
    if not principal.can_see_site(site_id):
        raise not_found(kind)


def ensure_unrestricted(principal: Principal, what: str) -> None:
    if principal.restricted:
        raise Problem(403, f"{what} applies to every site; only users without a site limit can change it.")


# ---------------------------------------------------------------------------------------------- tokens


class TokenValidator:
    """Validates RS256 access tokens against the IdP's JWKS (fetched lazily, keys cached)."""

    def __init__(self, settings: Settings, jwks_client: jwt.PyJWKClient | None = None) -> None:
        self.issuer = settings.oidc_issuer
        self.audience = settings.oidc_audience
        self.jwks_client = jwks_client or jwt.PyJWKClient(
            settings.jwks_url, cache_keys=True, max_cached_keys=16, lifespan=3600, timeout=10
        )

    async def decode(self, token: str) -> dict[str, Any]:
        try:
            key = await asyncio.to_thread(self.jwks_client.get_signing_key_from_jwt, token)
        except jwt.PyJWKClientConnectionError as exc:
            log.error("cannot fetch JWKS: %s", exc)
            raise Problem(503, "The identity provider's signing keys are unavailable.") from exc
        except (jwt.PyJWKClientError, jwt.PyJWKError, jwt.DecodeError) as exc:
            raise AuthError(f"Unknown signing key or malformed token: {exc}") from exc
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                leeway=_CLOCK_LEEWAY_S,
                options={"require": ["exp", "iat", "iss", "sub"]},
            )
        except jwt.ExpiredSignatureError as exc:
            raise AuthError("The access token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise AuthError(f"Invalid access token: {exc}") from exc
        return claims


_validator: TokenValidator | None = None


def get_token_validator() -> TokenValidator:
    global _validator
    if _validator is None:
        _validator = TokenValidator(get_settings())
    return _validator


def set_token_validator(validator: TokenValidator | None) -> None:
    """Swap the validator (tests serve their own JWKS)."""
    global _validator
    _validator = validator


def _group_names(claims: dict[str, Any], claim: str) -> list[str]:
    raw = claims.get(claim) or []
    groups = [raw] if isinstance(raw, str) else [g for g in raw if isinstance(g, str)]
    realm_roles = (claims.get("realm_access") or {}).get("roles") or []
    names = [g.rstrip("/").rsplit("/", 1)[-1] for g in groups]
    return names + [r for r in realm_roles if isinstance(r, str)]


def roles_and_sites(
    claims: dict[str, Any], settings: Settings
) -> tuple[frozenset[Role], frozenset[str] | None]:
    names = _group_names(claims, settings.oidc_roles_claim)
    roles: set[Role] = set()
    sites: set[str] = set()
    prefix = settings.site_group_prefix.lower()
    for name in names:
        mapped = settings.role_group_map.get(name)
        if mapped is not None:
            try:
                roles.add(Role(mapped))
            except ValueError:
                log.warning("role_group_map maps %s to unknown role %s", name, mapped)
        elif name.lower().startswith(prefix) and len(name) > len(prefix):
            sites.add(name[len(prefix) :].upper())
    return frozenset(roles), (frozenset(sites) if sites else None)


async def _site_ids(codes: frozenset[str] | None) -> frozenset[int] | None:
    if codes is None:
        return None
    async with get_sessionmaker()() as session:
        rows = await session.execute(select(Site.id).where(Site.code.in_(sorted(codes))))
        return frozenset(int(r[0]) for r in rows)


async def principal_from_token(token: str) -> Principal:
    """Validate a token and build the principal (resolving site codes to ids). Raises AuthError."""
    claims = await get_token_validator().decode(token)
    settings = get_settings()
    roles, site_codes = roles_and_sites(claims, settings)
    sub = str(claims["sub"])
    username = str(claims.get("preferred_username") or claims.get("email") or sub)
    session_id = str(claims.get("sid") or claims.get("session_state") or f"iat:{claims.get('iat')}")
    return Principal(
        sub=sub,
        username=username,
        name=str(claims.get("name") or username),
        email=claims.get("email"),
        roles=roles,
        site_codes=site_codes,
        site_ids=await _site_ids(site_codes),
        session_id=session_id,
        expires_at=datetime.fromtimestamp(int(claims["exp"]), UTC),
    )


# ------------------------------------------------------------------------------------- user sessions

_SEEN_MAX = 10_000
_seen_sessions: OrderedDict[str, None] = OrderedDict()


def reset_security_caches() -> None:
    _seen_sessions.clear()


async def record_session(principal: Principal, request: Request | None) -> None:
    """Upsert the user and audit `user.login` once per token session."""
    key = f"{principal.sub}|{principal.session_id}"
    if key in _seen_sessions:
        _seen_sessions.move_to_end(key)
        return
    now = datetime.now(UTC)
    roles = sorted(r.value for r in principal.roles)
    sites = sorted(principal.site_codes) if principal.site_codes is not None else None
    stmt = pg_insert(User).values(
        sub=principal.sub,
        email=principal.email,
        name=principal.display_name,
        roles=roles,
        sites=sites,
        last_session=principal.session_id,
        last_login_at=now,
    )
    upsert = stmt.on_conflict_do_update(
        index_elements=[User.sub],
        set_={
            "email": stmt.excluded.email,
            "name": stmt.excluded.name,
            "roles": stmt.excluded.roles,
            "sites": stmt.excluded.sites,
            "last_session": stmt.excluded.last_session,
            "last_login_at": stmt.excluded.last_login_at,
        },
        where=User.last_session.is_distinct_from(stmt.excluded.last_session),
    ).returning(User.id)
    async with get_sessionmaker()() as session:
        new_session = (await session.execute(upsert)).first() is not None
        if new_session:
            audit.record(
                session,
                principal=principal,
                action="user.login",
                object_type="user",
                object_id=principal.sub,
                after={"roles": roles, "sites": sites, "session": principal.session_id},
                request=request,
            )
        await session.commit()
    _seen_sessions[key] = None
    if len(_seen_sessions) > _SEEN_MAX:
        _seen_sessions.popitem(last=False)


# --------------------------------------------------------------------------------------- dependencies

_bearer = HTTPBearer(auto_error=False, description="OIDC access token from the company IdP.")
_WWW_AUTH = {"WWW-Authenticate": 'Bearer realm="gcc"'}


async def get_principal(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Principal:
    """Authenticated user (any role). Also applies the per-user rate limit."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials:
        raise Problem(401, "A bearer access token is required.", headers=_WWW_AUTH)
    try:
        principal = await principal_from_token(credentials.credentials)
    except AuthError as exc:
        raise Problem(401, str(exc), headers=_WWW_AUTH) from exc
    await check_rate_limit(principal.sub, get_settings().rate_limit_per_minute)
    await record_session(principal, request)
    request.state.principal = principal
    return principal


def require_role(minimum: Role) -> Callable[..., Awaitable[Principal]]:
    """Dependency: the user must hold `minimum` or a higher role."""

    async def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if not principal.roles:
            raise Problem(403, "Your account has no Jade GCC role. Ask a platform admin for access.")
        if not principal.has_role(minimum):
            raise Problem(403, f"This action needs the {ROLE_LABEL[minimum]} role or higher.")
        return principal

    return dependency


CurrentUser = Annotated[Principal, Depends(get_principal)]
ViewerUser = Annotated[Principal, Depends(require_role(Role.VIEWER))]
OperatorUser = Annotated[Principal, Depends(require_role(Role.NOC_OPERATOR))]
EngineerUser = Annotated[Principal, Depends(require_role(Role.DC_ENGINEER))]
AdminUser = Annotated[Principal, Depends(require_role(Role.PLATFORM_ADMIN))]


def capabilities(principal: Principal) -> dict[str, bool]:
    """What the UI may offer this user (the API enforces the same rules)."""
    viewer = principal.has_role(Role.VIEWER) and bool(principal.roles)
    operator = principal.has_role(Role.NOC_OPERATOR)
    engineer = principal.has_role(Role.DC_ENGINEER)
    admin = principal.has_role(Role.PLATFORM_ADMIN)
    return {
        "view": viewer,
        "ack_alerts": operator,
        "comment_alerts": operator,
        "resolve_alerts": operator,
        "onboard_servers": engineer,
        "edit_racks": engineer,
        "edit_maintenance": engineer,
        "edit_baselines": engineer,
        "edit_sites": admin,
        "edit_collectors": admin,
        "edit_thresholds": admin,
        "edit_alert_rules": admin,
        "edit_alert_routes": admin,
        "view_users": admin,
        "view_audit": admin and not principal.restricted,
        "superset_editor": Role.ANALYST in principal.roles or admin,
    }


def sites_in(principal: Principal, site_ids: Iterable[int]) -> list[int]:
    """The given site ids that the user may see."""
    return [s for s in site_ids if principal.can_see_site(s)]
