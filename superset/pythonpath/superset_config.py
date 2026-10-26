"""Jade GCC Superset configuration (Superset 4.1.2).

Every secret and endpoint comes from the environment, with dev defaults that match the shared compose file.
Nothing here is specific to one host; staging/prod only change environment variables.

Main variables (dev default in brackets):
  SUPERSET_SECRET_KEY            Flask secret [dev-superset-secret-key-change-me]
  SUPERSET_METADATA_DB_URI       Superset's own metadata DB [postgresql+psycopg2://superset_meta:...@timescaledb/superset_meta]
                                 (SUPERSET_META_DB_URI is accepted as an alias)
  SUPERSET_CACHE_REDIS_URL       chart/filter/explore caches and rate limits [redis://redis:6379/2]
  SUPERSET_CELERY_BROKER_URL     Celery broker for reports [redis://redis:6379/3]
  SUPERSET_RESULTS_REDIS_URL     Celery results [redis://redis:6379/4]
  SUPERSET_GUEST_TOKEN_SECRET    signs embedded guest tokens [dev-superset-guest-token-secret]
  SUPERSET_EMBED_ALLOWED_ORIGINS app origins that may frame Superset [http://localhost:3000,http://localhost:5173]
  SUPERSET_FRAME_ANCESTORS       overrides the frame-ancestors list (defaults to the allowed origins)
  SUPERSET_CORS_ORIGINS          overrides the CORS origins (defaults to the allowed origins)
  SUPERSET_AUTH                  oauth | db [oauth]. With oauth, analysts sign in with Keycloak and local
                                 accounts (admin) keep a password form at /local-login/.
  SUPERSET_OIDC_ISSUER           browser-facing issuer [http://localhost:8080/realms/gcc]
  SUPERSET_OIDC_INTERNAL_URL     back-channel realm URL for token/userinfo/JWKS [http://keycloak:8080/realms/gcc]
  SUPERSET_OIDC_CLIENT_ID / SUPERSET_OIDC_CLIENT_SECRET  [superset / dev-superset-oidc-secret]
  SUPERSET_SITE_CODES            sites that get an SSO site role + RLS filter [PNQ1,HYD1]
  SUPERSET_PUBLIC_URL            links in report emails [http://localhost:8090]
  SUPERSET_WEBDRIVER_BASEURL     how workers reach the web server [http://superset:8088/]
  SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASSWORD / SMTP_STARTTLS / SMTP_SSL / SMTP_MAIL_FROM  [mailpit:1025]
"""

from __future__ import annotations

import os
from datetime import timedelta
from typing import Any, ClassVar
from urllib.parse import quote

from celery.schedules import crontab
from flask_appbuilder.security.manager import AUTH_DB, AUTH_OAUTH


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    return _env(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str) -> list[str]:
    return [item.strip().rstrip("/") for item in _env(name, default).split(",") if item.strip()]


# ---------------------------------------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------------------------------------
SECRET_KEY = _env("SUPERSET_SECRET_KEY", "dev-superset-secret-key-change-me")
SQLALCHEMY_DATABASE_URI = _env(
    "SUPERSET_METADATA_DB_URI",
    _env(
        "SUPERSET_META_DB_URI",
        "postgresql+psycopg2://superset_meta:dev-superset-meta-pw@timescaledb:5432/superset_meta",
    ),
)
SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

# Behind nginx / the compose port mapping: trust one hop of X-Forwarded-* headers.
ENABLE_PROXY_FIX = True
PROXY_FIX_CONFIG = {"x_for": 1, "x_proto": 1, "x_host": 1, "x_port": 1, "x_prefix": 1}

FEATURE_FLAGS = {
    "EMBEDDED_SUPERSET": True,
    "ALERT_REPORTS": True,
    "DASHBOARD_RBAC": True,
    "ENABLE_TEMPLATE_PROCESSING": False,
}

# Postgres only ships second/minute/hour/day grains; add the rollup-friendly ones for analysts.
TIME_GRAIN_ADDON_EXPRESSIONS = {
    "postgresql": {
        "PT5M": "date_bin(INTERVAL '5 minutes', {col}, TIMESTAMPTZ '2000-01-01')",
        "PT15M": "date_bin(INTERVAL '15 minutes', {col}, TIMESTAMPTZ '2000-01-01')",
        "PT30M": "date_bin(INTERVAL '30 minutes', {col}, TIMESTAMPTZ '2000-01-01')",
        "PT6H": "date_bin(INTERVAL '6 hours', {col}, TIMESTAMPTZ '2000-01-01')",
    }
}

SUPERSET_WEBSERVER_TIMEOUT = 60
ROW_LIMIT = 10000

# ---------------------------------------------------------------------------------------------------------
# Redis: cache (DB 2), Celery broker (DB 3), Celery results (DB 4)
# ---------------------------------------------------------------------------------------------------------
CACHE_REDIS_URL = _env("SUPERSET_CACHE_REDIS_URL", "redis://redis:6379/2")
CELERY_BROKER_URL = _env("SUPERSET_CELERY_BROKER_URL", "redis://redis:6379/3")
RESULTS_REDIS_URL = _env("SUPERSET_RESULTS_REDIS_URL", "redis://redis:6379/4")


def _cache(prefix: str, timeout: int) -> dict[str, Any]:
    return {
        "CACHE_TYPE": "RedisCache",
        "CACHE_DEFAULT_TIMEOUT": timeout,
        "CACHE_KEY_PREFIX": f"gcc_superset_{prefix}_",
        "CACHE_REDIS_URL": CACHE_REDIS_URL,
    }


CACHE_CONFIG = _cache("meta", 300)
# Rollups refresh every 5 minutes; caching chart data longer would only hide new buckets.
DATA_CACHE_CONFIG = _cache("data", 300)
FILTER_STATE_CACHE_CONFIG = _cache("filter", int(timedelta(days=7).total_seconds()))
EXPLORE_FORM_DATA_CACHE_CONFIG = _cache("explore", int(timedelta(days=7).total_seconds()))
RATELIMIT_STORAGE_URI = CACHE_REDIS_URL


class CeleryConfig:
    broker_url = CELERY_BROKER_URL
    result_backend = RESULTS_REDIS_URL
    imports = (
        "superset.sql_lab",
        "superset.tasks.scheduler",
        "superset.tasks.thumbnails",
        "superset.tasks.cache",
    )
    worker_prefetch_multiplier = 1
    task_acks_late = False
    broker_connection_retry_on_startup = True
    beat_schedule: ClassVar[dict[str, Any]] = {
        # Fires every minute and runs the alert/report schedules that are due.
        "reports.scheduler": {"task": "reports.scheduler", "schedule": crontab(minute="*", hour="*")},
        "reports.prune_log": {"task": "reports.prune_log", "schedule": crontab(minute=10, hour=0)},
    }


CELERY_CONFIG = CeleryConfig

# ---------------------------------------------------------------------------------------------------------
# Alerts & reports (scheduled e-mail summaries; real-time alerting stays in the backend)
# ---------------------------------------------------------------------------------------------------------
ALERT_REPORTS_NOTIFICATION_DRY_RUN = _env_bool("SUPERSET_REPORTS_DRY_RUN", False)
WEBDRIVER_BASEURL = _env("SUPERSET_WEBDRIVER_BASEURL", "http://superset:8088/")
WEBDRIVER_BASEURL_USER_FRIENDLY = _env("SUPERSET_PUBLIC_URL", "http://localhost:8090").rstrip("/") + "/"
EMAIL_REPORTS_SUBJECT_PREFIX = "[GCC Analytics] "

SMTP_HOST = _env("SMTP_HOST", "mailpit")
SMTP_PORT = int(_env("SMTP_PORT", "1025"))
SMTP_STARTTLS = _env_bool("SMTP_STARTTLS", False)
SMTP_SSL = _env_bool("SMTP_SSL", False)
SMTP_USER = _env("SMTP_USER", "")
SMTP_PASSWORD = _env("SMTP_PASSWORD", "")
SMTP_MAIL_FROM = _env("SMTP_MAIL_FROM", "superset@gcc.example")
SMTP_SSL_SERVER_AUTH = _env_bool("SMTP_SSL_SERVER_AUTH", False)

# ---------------------------------------------------------------------------------------------------------
# Embedding (guest tokens) and browser security headers
# ---------------------------------------------------------------------------------------------------------
GUEST_ROLE_NAME = "GccGuest"
GUEST_TOKEN_JWT_SECRET = _env("SUPERSET_GUEST_TOKEN_SECRET", "dev-superset-guest-token-secret")
GUEST_TOKEN_JWT_ALGO = "HS256"
GUEST_TOKEN_JWT_EXP_SECONDS = 300  # DESIGN: guest tokens valid 5 minutes

_APP_ORIGINS = _env_list("SUPERSET_EMBED_ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:5173")
FRAME_ANCESTORS = _env_list("SUPERSET_FRAME_ANCESTORS", ",".join(_APP_ORIGINS))
CORS_ALLOWED_ORIGINS = _env_list("SUPERSET_CORS_ORIGINS", ",".join(_APP_ORIGINS))

TALISMAN_ENABLED = True
TALISMAN_CONFIG = {
    "content_security_policy": {
        "base-uri": ["'self'"],
        "default-src": ["'self'"],
        "img-src": ["'self'", "blob:", "data:"],
        "worker-src": ["'self'", "blob:"],
        "connect-src": ["'self'"],
        "object-src": "'none'",
        "style-src": ["'self'", "'unsafe-inline'"],
        "script-src": ["'self'", "'strict-dynamic'"],
        # The React app embeds dashboards in an iframe; only its origins may frame Superset.
        "frame-ancestors": ["'self'", *FRAME_ANCESTORS],
    },
    "content_security_policy_nonce_in": ["script-src"],
    # X-Frame-Options cannot express an allow-list; CSP frame-ancestors above replaces it.
    "frame_options": None,
    "force_https": False,
    "session_cookie_secure": False,
}
TALISMAN_DEV_CONFIG = TALISMAN_CONFIG

ENABLE_CORS = True
CORS_OPTIONS = {
    "supports_credentials": True,
    "allow_headers": ["*"],
    "resources": [r"/api/*"],
    "origins": CORS_ALLOWED_ORIGINS,
}

# The app API calls the guest-token endpoint with a bearer token from a server, never from a browser form.
WTF_CSRF_EXEMPT_LIST = [
    "superset.views.core.log",
    "superset.views.core.explore_json",
    "superset.charts.data.api.data",
    "superset.dashboards.api.cache_dashboard_screenshot",
    "superset.security.api.guest_token",
]

SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = _env_bool("SUPERSET_SESSION_COOKIE_SECURE", False)

# ---------------------------------------------------------------------------------------------------------
# Authentication: Keycloak OIDC for people, database passwords for local/service accounts
# ---------------------------------------------------------------------------------------------------------
SITE_CODES = [code.upper() for code in _env_list("SUPERSET_SITE_CODES", "PNQ1,HYD1")]
SITE_ROLE_PREFIX = "GccSite_"

AUTH_MODE = _env("SUPERSET_AUTH", "oauth").lower()

if AUTH_MODE == "oauth":
    from gcc_security import GccSecurityManager

    _ISSUER = _env("SUPERSET_OIDC_ISSUER", "http://localhost:8080/realms/gcc").rstrip("/")
    _INTERNAL = _env("SUPERSET_OIDC_INTERNAL_URL", "http://keycloak:8080/realms/gcc").rstrip("/")

    AUTH_TYPE = AUTH_OAUTH
    CUSTOM_SECURITY_MANAGER = GccSecurityManager
    OAUTH_PROVIDERS = [
        {
            "name": "keycloak",
            "icon": "fa-key",
            "token_key": "access_token",
            "remote_app": {
                "client_id": _env("SUPERSET_OIDC_CLIENT_ID", "superset"),
                "client_secret": _env("SUPERSET_OIDC_CLIENT_SECRET", "dev-superset-oidc-secret"),
                "client_kwargs": {"scope": "openid email profile"},
                # The browser is sent to the public issuer; Superset itself talks to Keycloak over the
                # compose network. Explicit endpoints (no discovery) keep that split working.
                "authorize_url": f"{_ISSUER}/protocol/openid-connect/auth",
                "access_token_url": f"{_INTERNAL}/protocol/openid-connect/token",
                "api_base_url": f"{_INTERNAL}/protocol/",
                "jwks_uri": f"{_INTERNAL}/protocol/openid-connect/certs",
                "issuer": _ISSUER,
                "request_token_url": None,
            },
        }
    ]
    # Group claim (full path off) → Superset roles. Everyone else gets the registration role (Gamma).
    AUTH_ROLES_MAPPING: dict[str, list[str]] = {
        "gcc-analyst": ["Alpha"],
        "gcc-platform-admin": ["Admin"],
        **{f"gcc-site-{code}": [f"{SITE_ROLE_PREFIX}{code}"] for code in SITE_CODES},
    }
    AUTH_ROLES_SYNC_AT_LOGIN = True
    AUTH_USER_REGISTRATION = True
    AUTH_USER_REGISTRATION_ROLE = "Gamma"
    # End the Keycloak session too, then come back to Superset's (OAuth) login page.
    LOGOUT_REDIRECT_URL = (
        f"{_ISSUER}/protocol/openid-connect/logout?client_id={_env('SUPERSET_OIDC_CLIENT_ID', 'superset')}"
        f"&post_logout_redirect_uri={quote(WEBDRIVER_BASEURL_USER_FRIENDLY + 'login/', safe='')}"
    )
else:
    AUTH_TYPE = AUTH_DB
    AUTH_USER_REGISTRATION = False

# Only admins see the security admin pages (Superset default); keep the public role empty.
PUBLIC_ROLE_LIKE = None
