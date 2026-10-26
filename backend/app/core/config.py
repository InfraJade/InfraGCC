"""Service configuration, read from environment variables.

Every service (ingest API, app API, alert worker, scheduler, migrate) uses this one settings class;
each container only sets the variables it needs. Dev defaults let `docker compose up` work from a clean
clone, and `check_production_safety` refuses to run in prod while any of them are still in place.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that are fine on a laptop and never acceptable in production.
_DEV_SENTINELS = ("dev-", "change-me", "devpass")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    service_name: str = "gcc-backend"

    # Database. Each service connects as its own least-privilege role (see infra/timescale/init).
    database_url: SecretStr = SecretStr("postgresql+asyncpg://gcc_app:dev-app-pw@localhost:5432/gcc")
    migration_database_url: SecretStr | None = None
    db_pool_size: int = 10
    db_max_overflow: int = 10

    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"

    # OIDC (Keycloak in dev). The issuer is what the browser sees; JWKS may be fetched on an internal URL.
    oidc_issuer: str = "http://localhost:8080/realms/gcc"
    oidc_audience: str = "gcc-api"
    oidc_jwks_url: str | None = None
    oidc_roles_claim: str = "groups"
    role_group_map: dict[str, str] = Field(
        default_factory=lambda: {
            "gcc-viewer": "viewer",
            "gcc-noc-operator": "noc_operator",
            "gcc-dc-engineer": "dc_engineer",
            "gcc-platform-admin": "platform_admin",
            "gcc-analyst": "analyst",
        }
    )
    site_group_prefix: str = "gcc-site-"

    # Ingest
    ingest_auth_mode: Literal["token", "mtls"] = "token"
    ingest_shared_token: SecretStr = SecretStr("dev-ingest-token")
    ingest_mtls_fingerprint_header: str = "X-Client-Cert-Fingerprint"
    ingest_mtls_subject_header: str = "X-Client-Cert-Subject"
    ingest_trusted_proxies: list[str] = Field(default_factory=lambda: ["127.0.0.1"])
    ingest_max_body_bytes: int = 20 * 1024 * 1024
    collector_offline_after_s: int = 90
    collector_config_refresh_s: int = 60

    # Alerting / notifications
    app_secret_key: SecretStr = SecretStr("dev-app-secret-key-change-me-32bytes!!")
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = False
    smtp_from: str = "Jade GCC Monitoring <gcc-alerts@gcc.example>"
    escalation_after_s: int = 15 * 60
    public_app_url: str = "http://localhost:3000"
    report_recipients: list[str] = Field(default_factory=list)

    # Superset
    superset_url: str = "http://localhost:8090"
    superset_public_url: str = "http://localhost:8090"
    superset_admin_username: str = "gcc_embed"
    superset_admin_password: SecretStr = SecretStr("dev-superset-embed-pw")

    # API
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://localhost:5173"]
    )
    rate_limit_per_minute: int = 600

    # Dev conveniences
    dev_backfill_days: float = Field(default=7.0, gt=0)  # fractional for tests
    dev_backfill_enabled: bool = True

    @property
    def jwks_url(self) -> str:
        return self.oidc_jwks_url or f"{self.oidc_issuer}/protocol/openid-connect/certs"

    def check_production_safety(self) -> None:
        """Fail fast if prod is configured with any dev default secret."""
        if self.app_env != "prod":
            return
        secrets = {
            "DATABASE_URL": self.database_url.get_secret_value(),
            "INGEST_SHARED_TOKEN": self.ingest_shared_token.get_secret_value(),
            "APP_SECRET_KEY": self.app_secret_key.get_secret_value(),
            "SUPERSET_ADMIN_PASSWORD": self.superset_admin_password.get_secret_value(),
        }
        bad = [name for name, value in secrets.items() if any(s in value for s in _DEV_SENTINELS)]
        if bad:
            raise RuntimeError(f"Refusing to start in prod with dev default values for: {', '.join(bad)}")
        if self.ingest_auth_mode != "mtls":
            raise RuntimeError("INGEST_AUTH_MODE must be 'mtls' in prod")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.check_production_safety()
    return settings
