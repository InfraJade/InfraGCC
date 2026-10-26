"""Idempotent Superset bootstrap for Jade GCC (run by the superset-init service after `db upgrade` + `init`).

Steps, all safe to repeat on every start:
  1. Local admin user (`SUPERSET_UI_ADMIN_USERNAME`, default admin) with SUPERSET_UI_ADMIN_PASSWORD.
  2. Import the bundle (database, six datasets, charts, six dashboards) with overwrite, then point the
     "GCC Analytics" database at SUPERSET_ANALYTICS_DB_URI.
  3. Roles: GccGuest (embedded guest users), GccEmbedService (the app API's service account),
     GccSite_<CODE> (SSO users limited to a site) with a row-level-security filter per site.
  4. Embed service user (`SUPERSET_EMBED_USERNAME`, default gcc_embed) with SUPERSET_EMBED_PASSWORD.
  5. Embedding enabled on the six dashboards with stable UUIDs; allowed domains from
     SUPERSET_EMBED_ALLOWED_DOMAINS (comma-separated, empty = any).
  6. Weekly capacity report (CSV by e-mail) owned by the admin user.
Prints a JSON summary with the embedded UUIDs at the end.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "bundle"))

import generate_bundle as gb

log = logging.getLogger("gcc.superset.init")

ANALYTICS_URI_DEFAULT = "postgresql+psycopg2://gcc_superset_ro:dev-superset-ro-pw@timescaledb:5432/gcc"
BUNDLE_ZIP = Path(__file__).resolve().parent / "bundle" / "gcc_bundle.zip"
SPEC = Path(__file__).resolve().parent / "bundle" / "spec.yaml"

GUEST_ROLE = "GccGuest"
EMBED_ROLE = "GccEmbedService"

# What an embedded (guest) dashboard needs: read the dashboard and its charts, run chart queries, keep
# native-filter state, and download chart data. No write access to any asset.
GUEST_PERMISSIONS = [
    ("can_read", "Dashboard"),
    ("can_read", "Chart"),
    ("can_read", "Dataset"),
    ("can_read", "EmbeddedDashboard"),
    ("can_dashboard", "Superset"),
    ("can_explore_json", "Superset"),
    ("can_csv", "Superset"),
    ("can_time_range", "Api"),
    ("can_query_form_data", "Api"),
    ("can_query", "Api"),
    ("can_read", "DashboardFilterStateRestApi"),
    ("can_write", "DashboardFilterStateRestApi"),
    ("can_read", "DashboardPermalinkRestApi"),
    ("can_write", "DashboardPermalinkRestApi"),
    ("can_view_chart_as_table", "Dashboard"),
    ("can_view_query", "Dashboard"),
    ("can_drill", "Dashboard"),
]
# The app API: sign in, find dashboards by slug and their embedded config, mint guest tokens.
EMBED_PERMISSIONS = [
    ("can_grant_guest_token", "SecurityRestApi"),
    ("can_read", "SecurityRestApi"),
    ("can_read", "Dashboard"),
    ("can_read", "Chart"),
    ("can_read", "Dataset"),
    ("can_read", "EmbeddedDashboard"),
]


def env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value if value not in (None, "") else default


def env_list(name: str, default: str) -> list[str]:
    return [item.strip().rstrip("/") for item in env(name, default).split(",") if item.strip()]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    from superset.app import create_app

    app = create_app()
    with app.app_context():
        from flask import current_app
        from sqlalchemy.engine.url import make_url
        from superset import db, security_manager
        from superset.commands.importers.v1.assets import ImportAssetsCommand
        from superset.connectors.sqla.models import RowLevelSecurityFilter, SqlaTable
        from superset.models.core import Database
        from superset.models.dashboard import Dashboard
        from superset.models.embedded_dashboard import EmbeddedDashboard
        from superset.models.slice import Slice
        from superset.reports.models import ReportRecipients, ReportSchedule
        from superset.utils.core import override_user

        sm = security_manager
        spec = gb.load_spec(SPEC)

        # ---- 1. local admin ------------------------------------------------------------------------
        def upsert_user(username: str, password: str, roles: list[Any], first: str, email: str) -> Any:
            user = sm.find_user(username=username)
            if user is None:
                user = sm.add_user(username, first, "GCC", email, roles, password)
                if not user:
                    raise RuntimeError(f"could not create user {username}")
                log.info("created user %s", username)
            else:
                user.roles = roles
                user.active = True
                sm.update_user(user)
                sm.reset_password(user.id, password)
                log.info("updated user %s (roles, password)", username)
            return user

        admin_name = env("SUPERSET_UI_ADMIN_USERNAME", "admin")
        admin = upsert_user(
            admin_name,
            env("SUPERSET_UI_ADMIN_PASSWORD", env("SUPERSET_ADMIN_UI_PASSWORD", "dev-superset-admin")),
            [sm.find_role("Admin")],
            "Superset admin",
            f"{admin_name}@gcc.example",
        )

        # ---- 2. bundle import ------------------------------------------------------------------------
        contents = gb.read_zip(BUNDLE_ZIP) if BUNDLE_ZIP.exists() else gb.build_contents(spec)
        analytics_uri = env("SUPERSET_ANALYTICS_DB_URI", ANALYTICS_URI_DEFAULT)
        passwords = {gb.database_file(spec): make_url(analytics_uri).password or ""}
        with override_user(admin):
            ImportAssetsCommand(contents, passwords=passwords).run()
        log.info("imported bundle (%d files)", len(contents))

        database = db.session.query(Database).filter_by(uuid=gb.database_uuid(spec)).one()
        database.set_sqlalchemy_uri(analytics_uri)
        database.expose_in_sqllab = True
        db.session.commit()
        log.info("database %r -> %s", database.database_name, make_url(analytics_uri).render_as_string())

        datasets = {
            name: db.session.query(SqlaTable).filter_by(uuid=gb.dataset_uuid(name)).one() for name in spec["datasets"]
        }
        datasource_pvms = []
        for dataset in datasets.values():
            datasource_pvms.append(sm.add_permission_view_menu("datasource_access", dataset.perm))
        db.session.commit()

        # ---- 3. roles ---------------------------------------------------------------------------------
        def set_role(name: str, wanted: list[tuple[str, str]], extra: list[Any]) -> Any:
            role = sm.find_role(name) or sm.add_role(name)
            pvms = []
            for perm, view in wanted:
                pvm = sm.find_permission_view_menu(perm, view)
                if pvm is None:
                    log.warning("permission %s on %s does not exist in this Superset; skipped", perm, view)
                    continue
                pvms.append(pvm)
            role.permissions = pvms + list(extra)
            db.session.commit()
            log.info("role %s: %d permissions", name, len(role.permissions))
            return role

        set_role(current_app.config.get("GUEST_ROLE_NAME", GUEST_ROLE), GUEST_PERMISSIONS, datasource_pvms)
        embed_role = set_role(EMBED_ROLE, EMBED_PERMISSIONS, datasource_pvms)

        prefix = current_app.config.get("SITE_ROLE_PREFIX", "GccSite_")
        for code in current_app.config.get("SITE_CODES", ["PNQ1", "HYD1"]):
            role = sm.find_role(f"{prefix}{code}") or sm.add_role(f"{prefix}{code}")
            name = f"GCC site {code}"
            rls = db.session.query(RowLevelSecurityFilter).filter_by(name=name).one_or_none()
            if rls is None:
                rls = RowLevelSecurityFilter(name=name)
                db.session.add(rls)
            rls.description = f"SSO users in gcc-site-{code} see only site {code} (same group key = OR)."
            rls.filter_type = "Regular"
            rls.group_key = "site"
            rls.clause = f"site_code = '{code}'"
            rls.roles = [role]
            rls.tables = list(datasets.values())
            db.session.commit()
            log.info("site role %s%s with RLS %r", prefix, code, rls.clause)

        # ---- 4. embed service user --------------------------------------------------------------------
        embed_name = env("SUPERSET_EMBED_USERNAME", env("SUPERSET_ADMIN_USERNAME", "gcc_embed"))
        upsert_user(
            embed_name,
            env("SUPERSET_EMBED_PASSWORD", env("SUPERSET_ADMIN_PASSWORD", "dev-superset-embed-pw")),
            [embed_role],
            "GCC embed service",
            f"{embed_name}@gcc.example",
        )

        # ---- 5. embedding -----------------------------------------------------------------------------
        # Empty = any referrer; which origins may frame Superset at all is enforced by CSP frame-ancestors.
        allowed = env_list("SUPERSET_EMBED_ALLOWED_DOMAINS", "")
        summary: dict[str, Any] = {"dashboards": [], "allowed_domains": allowed}
        for board in spec["dashboards"]:
            dashboard = db.session.query(Dashboard).filter_by(uuid=gb.dashboard_uuid(board["slug"])).one()
            dashboard.published = True
            if dashboard.embedded:
                embedded = dashboard.embedded[0]
            else:
                embedded = EmbeddedDashboard(uuid=gb.embedded_uuid(board["slug"]))
                dashboard.embedded = [embedded]
            embedded.allow_domain_list = ",".join(allowed)
            db.session.commit()
            summary["dashboards"].append(
                {
                    "slug": board["slug"],
                    "id": dashboard.id,
                    "title": dashboard.dashboard_title,
                    "embedded_uuid": str(embedded.uuid),
                    "refresh_s": int(board["refresh"]),
                }
            )

        # ---- 6. weekly capacity report ----------------------------------------------------------------
        recipients = env_list("SUPERSET_REPORT_RECIPIENTS", "capacity-planning@gcc.example")
        report_name = "Weekly capacity report"
        chart = db.session.query(Slice).filter_by(uuid=gb.chart_uuid("pw_headroom")).one()
        report = db.session.query(ReportSchedule).filter_by(name=report_name).one_or_none()
        if report is None:
            report = ReportSchedule(name=report_name, type="Report", creation_method="alerts_reports")
            db.session.add(report)
        report.description = "Rack power headroom against capacity, as CSV, every Monday morning."
        report.crontab = env("SUPERSET_CAPACITY_REPORT_CRON", "0 7 * * 1")
        report.timezone = env("SUPERSET_REPORT_TIMEZONE", "Asia/Kolkata")
        report.report_format = "CSV"
        report.chart = chart
        report.dashboard = None
        report.active = bool(recipients)
        report.owners = [admin]
        report.email_subject = "Weekly capacity report — rack power headroom"
        report.recipients = [
            ReportRecipients(type="Email", recipient_config_json=json.dumps({"target": ",".join(recipients)}))
        ]
        db.session.commit()
        summary["report"] = {"name": report_name, "crontab": report.crontab, "recipients": recipients}

        print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
