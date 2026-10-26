"""Security manager for Keycloak SSO that keeps a password form for local accounts.

With AUTH_TYPE = AUTH_OAUTH, Flask-AppBuilder's /login/ page only offers the identity provider. The local
`admin` account (and break-glass access when Keycloak is down) still needs a password form, so this manager
registers one extra view at /local-login/ that checks the Superset database password. Service accounts such
as `gcc_embed` use the REST API (`POST /api/v1/security/login`, provider "db"), which works in either mode.
"""

from __future__ import annotations

from flask_appbuilder import expose
from flask_appbuilder.security.views import AuthDBView
from superset.security import SupersetSecurityManager
from werkzeug.wrappers import Response


class LocalLoginView(AuthDBView):
    """Database-password sign-in at /local-login/ (also reachable as /local-login/login/)."""

    route_base = "/local-login"

    @expose("/", methods=["GET", "POST"])
    def local(self) -> Response:
        return self.login()


class GccSecurityManager(SupersetSecurityManager):
    def register_views(self) -> None:
        super().register_views()
        self.appbuilder.add_view_no_menu(LocalLoginView())
