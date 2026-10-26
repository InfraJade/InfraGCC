"""Verify a running Jade GCC Superset through its REST API (Phase 5 checks). Standard library only.

Checks
  1. Six dashboards (by slug) exist, each with an embedded UUID and the DESIGN refresh interval.
  2. Every dataset's columns exist in its reporting view (catches view/spec drift).
  3. Every chart's saved query runs: GET /api/v1/chart/{id}/data/ returns 200 (empty data is fine).
  4. The embed service account can mint a guest token; with RLS `site_id IN (<one site>)` every chart's
     data request (as the embedded dashboard sends it) returns 200 and only rows of that site.
  5. Optional --sso USER:PASSWORD: Keycloak sign-in works and maps groups to roles (--expect-role).
  6. Optional --local-login: the /local-login/ password form signs in the local admin (oauth mode).
  7. Optional --mailpit URL: the weekly capacity report e-mail arrived (needs a fast report cron).

    python verify_superset.py --url http://localhost:8090
    python verify_superset.py --url http://localhost:8090 --sso analyst:demo1234 --expect-role Alpha \
        --local-login --mailpit http://localhost:8025

Exit code 0 when all checks pass.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

DASHBOARDS = {
    "dc-overview": 300,
    "thermal": 300,
    "power-capacity": 900,
    "hardware-health": 900,
    "alerts": 900,
    "inventory-firmware": 86400,
}
SITE_COLUMNS = ("site_id", "site_code")


class CheckFailed(Exception):
    pass


class Client:
    """Tiny HTTP client with a cookie jar and JSON helpers."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.headers: dict[str, str] = {}

    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        headers: dict[str, str] | None = None,
        form: dict[str, str] | None = None,
    ) -> tuple[int, Any, str]:
        url = path if path.startswith("http") else f"{self.base}{path}"
        data: bytes | None = None
        all_headers = {"Accept": "application/json", **self.headers, **(headers or {})}
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            all_headers["Content-Type"] = "application/x-www-form-urlencoded"
            all_headers["Accept"] = "text/html"
        elif body is not None:
            data = json.dumps(body).encode()
            all_headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=all_headers)
        try:
            with self.opener.open(req, timeout=60) as resp:
                status, raw, final = resp.status, resp.read(), resp.geturl()
        except urllib.error.HTTPError as exc:
            status, raw, final = exc.code, exc.read(), url
        except (urllib.error.URLError, OSError) as exc:
            raise CheckFailed(f"{method} {url}: {exc}") from exc
        text = raw.decode("utf-8", errors="replace")
        try:
            payload: Any = json.loads(text)
        except ValueError:
            payload = text
        return status, payload, final

    def json(self, method: str, path: str, body: Any = None, headers: dict[str, str] | None = None) -> Any:
        status, payload, _ = self.request(method, path, body, headers)
        if status != 200:
            raise CheckFailed(f"{method} {path} -> HTTP {status}: {str(payload)[:300]}")
        return payload

    def login(self, username: str, password: str) -> None:
        payload = self.json(
            "POST",
            "/api/v1/security/login",
            {"username": username, "password": password, "provider": "db", "refresh": False},
        )
        self.headers["Authorization"] = f"Bearer {payload['access_token']}"
        csrf = self.json("GET", "/api/v1/security/csrf_token/")
        self.headers["X-CSRFToken"] = csrf["result"]
        self.headers["Referer"] = self.base


class FormParser(HTMLParser):
    """Collects the first <form> action and its input values."""

    def __init__(self) -> None:
        super().__init__()
        self.action: str | None = None
        self.inputs: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {k: v or "" for k, v in attrs}
        if tag == "form" and self.action is None:
            self.action = values.get("action", "")
        elif tag == "input" and values.get("name"):
            self.inputs[values["name"]] = values.get("value", "")


def ok(message: str) -> None:
    print(f"  ok   {message}")


def chart_rows(payload: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in payload.get("result", []):
        rows.extend(result.get("data") or [])
    return rows


def site_values(rows: list[dict[str, Any]]) -> set[tuple[str, Any]]:
    found: set[tuple[str, Any]] = set()
    for row in rows:
        for column in SITE_COLUMNS:
            if column in row and row[column] is not None:
                found.add((column, row[column]))
    return found


def check_dashboards(admin: Client) -> dict[str, dict[str, Any]]:
    print("1. dashboards, embedding, refresh intervals")
    boards: dict[str, dict[str, Any]] = {}
    for slug, refresh in DASHBOARDS.items():
        result = admin.json("GET", f"/api/v1/dashboard/{slug}")["result"]
        meta = json.loads(result.get("json_metadata") or "{}")
        if int(meta.get("refresh_frequency") or 0) != refresh:
            raise CheckFailed(f"{slug}: refresh_frequency {meta.get('refresh_frequency')} != {refresh}")
        embedded = admin.json("GET", f"/api/v1/dashboard/{result['id']}/embedded")["result"]
        charts = admin.json("GET", f"/api/v1/dashboard/{result['id']}/charts")["result"]
        boards[slug] = {"id": result["id"], "embedded_uuid": embedded["uuid"], "charts": charts}
        ok(f"{slug:<19} id={result['id']:<3} embedded={embedded['uuid']} refresh={refresh}s charts={len(charts)}")
    return boards


def check_datasets(admin: Client) -> dict[str, int]:
    print("2. datasets match the reporting views")
    query = urllib.parse.quote(
        json.dumps({"filters": [{"col": "schema", "opr": "eq", "value": "reporting"}], "page_size": 100}).replace(
            " ", ""
        )
    )
    found = admin.json("GET", f"/api/v1/dataset/?q={query}")["result"]
    ids: dict[str, int] = {}
    for item in found:
        detail = admin.json("GET", f"/api/v1/dataset/{item['id']}")["result"]
        db_id = detail["database"]["id"]
        name = detail["table_name"]
        meta_path = f"/api/v1/database/{db_id}/table_metadata/?name={name}&schema=reporting"
        actual = {c["name"] for c in admin.json("GET", meta_path)["columns"]}
        declared = {c["column_name"] for c in detail["columns"]}
        missing = declared - actual
        if missing:
            raise CheckFailed(f"{name}: columns not in the view: {sorted(missing)}")
        if "site_id" not in actual:
            raise CheckFailed(f"{name}: view has no site_id, so guest RLS cannot filter it")
        extra = actual - declared
        ids[name] = item["id"]
        ok(f"{name:<22} {len(declared)} columns" + (f" (view also has {sorted(extra)})" if extra else ""))
    if len(ids) != 6:
        raise CheckFailed(f"expected 6 reporting datasets, found {sorted(ids)}")
    return ids


def check_chart_data(admin: Client, boards: dict[str, dict[str, Any]]) -> dict[int, int]:
    print("3. every chart's saved query returns 200")
    rowcounts: dict[int, int] = {}
    for slug, board in boards.items():
        for chart in board["charts"]:
            cid = chart["id"]
            status, payload, _ = admin.request("GET", f"/api/v1/chart/{cid}/data/")
            if status != 200:
                raise CheckFailed(f"{slug}/{chart['slice_name']} (chart {cid}) -> HTTP {status}: {str(payload)[:400]}")
            rowcounts[cid] = len(chart_rows(payload))
        rows = sum(rowcounts[c["id"]] for c in board["charts"])
        ok(f"{slug:<19} {len(board['charts'])} charts, {rows} rows in total")
    return rowcounts


def site_ids(admin: Client, inventory_id: int) -> dict[int, str]:
    payload = admin.json(
        "POST",
        "/api/v1/chart/data",
        {
            "datasource": {"id": inventory_id, "type": "table"},
            "queries": [
                {
                    "columns": ["site_id", "site_code"],
                    "metrics": ["servers"],
                    "orderby": [["site_id", True]],
                    "row_limit": 100,
                }
            ],
            "result_format": "json",
            "result_type": "full",
        },
    )
    return {int(r["site_id"]): str(r["site_code"]) for r in chart_rows(payload)}


def check_guest_rls(
    url: str,
    admin: Client,
    embed_user: str,
    embed_password: str,
    boards: dict[str, dict[str, Any]],
    datasets: dict[str, int],
    site: str | None,
) -> None:
    print("4. guest token with RLS returns only the permitted site")
    sites = site_ids(admin, datasets["v_inventory"])
    if not sites:
        raise CheckFailed("no sites visible in v_inventory; seed the database first")
    site_id = next((i for i, code in sites.items() if code == site), min(sites)) if site else min(sites)
    code = sites[site_id]
    embed = Client(url)
    embed.login(embed_user, embed_password)
    token = embed.json(
        "POST",
        "/api/v1/security/guest_token/",
        {
            "user": {"username": "verify-guest", "first_name": "Verify", "last_name": "Guest"},
            "resources": [{"type": "dashboard", "id": b["embedded_uuid"]} for b in boards.values()],
            "rls": [{"clause": f"site_id IN ({site_id})"}],
        },
    )["token"]
    ok(f"guest token minted by {embed_user} (RLS site_id IN ({site_id}) = {code})")

    guest = Client(url)
    guest.headers["X-GuestToken"] = token
    checked_rows = 0
    other_sites_seen_by_admin = False
    for slug, board in boards.items():
        for chart in board["charts"]:
            detail = admin.json("GET", f"/api/v1/chart/{chart['id']}")["result"]
            query_context = json.loads(detail["query_context"])
            query_context["form_data"].update({"dashboardId": board["id"], "slice_id": chart["id"]})
            status, payload, _ = guest.request("POST", "/api/v1/chart/data", query_context)
            if status != 200:
                raise CheckFailed(f"guest {slug}/{detail['slice_name']} -> HTTP {status}: {str(payload)[:400]}")
            rows = chart_rows(payload)
            for column, value in site_values(rows):
                expected: Any = site_id if column == "site_id" else code
                if value != expected:
                    raise CheckFailed(f"guest saw {column}={value!r} in {slug}/{detail['slice_name']}")
                checked_rows += 1
            admin_payload = admin.json("POST", "/api/v1/chart/data", query_context)
            if any(v not in (site_id, code) for _, v in site_values(chart_rows(admin_payload))):
                other_sites_seen_by_admin = True
        ok(f"{slug:<19} all {len(board['charts'])} charts return 200 for the guest")
    if checked_rows == 0:
        raise CheckFailed("no chart returned site columns; cannot prove RLS (seed sample data)")
    ok(
        f"{checked_rows} site values checked, all {code}"
        + ("; the admin sees other sites in the same charts" if other_sites_seen_by_admin else "")
    )

    # Unfiltered count vs guest count on the same chart proves rows were removed, not just relabelled.
    servers_chart = next(c for c in boards["dc-overview"]["charts"] if c["slice_name"] == "Servers monitored")
    detail = admin.json("GET", f"/api/v1/chart/{servers_chart['id']}")["result"]
    qc = json.loads(detail["query_context"])
    qc["form_data"].update({"dashboardId": boards["dc-overview"]["id"], "slice_id": servers_chart["id"]})
    admin_count = chart_rows(admin.json("POST", "/api/v1/chart/data", qc))[0].get("servers")
    _, guest_payload, _ = guest.request("POST", "/api/v1/chart/data", qc)
    guest_count = chart_rows(guest_payload)[0].get("servers")
    if admin_count and guest_count is not None and guest_count >= admin_count and len(sites) > 1:
        raise CheckFailed(f"guest servers {guest_count} not fewer than unrestricted {admin_count}")
    ok(f"servers monitored: unrestricted {admin_count}, guest ({code}) {guest_count}")

    # A guest must not be able to change the saved query.
    qc["queries"][0]["metrics"] = ["count"]
    status, _, _ = guest.request("POST", "/api/v1/chart/data", qc)
    if status == 200:
        raise CheckFailed("guest could run a modified chart query")
    ok(f"modified guest query rejected (HTTP {status})")


def follow_form(client: Client, html: str, page_url: str, fields: dict[str, str]) -> tuple[int, Any, str]:
    parser = FormParser()
    parser.feed(html)
    if parser.action is None:
        raise CheckFailed(f"no form on {page_url}")
    action = urllib.parse.urljoin(page_url, parser.action)
    return client.request("POST", action, form={**parser.inputs, **fields})


def check_sso(url: str, credentials: str, expect_roles: list[str]) -> None:
    print("5. Keycloak SSO")
    username, _, password = credentials.partition(":")
    browser = Client(url)
    status, page, page_url = browser.request(
        "GET", "/login/keycloak?next=/api/v1/me/roles/", headers={"Accept": "text/html"}
    )
    if status != 200 or "kc-form-login" not in str(page):
        raise CheckFailed(f"expected the Keycloak login page, got HTTP {status} at {page_url}")
    status, payload, final = follow_form(browser, str(page), page_url, {"username": username, "password": password})
    status, payload, final = browser.request("GET", "/api/v1/me/roles/")
    if status != 200:
        raise CheckFailed(f"after SSO, /api/v1/me/roles/ -> HTTP {status} ({final})")
    roles = sorted(payload["result"]["roles"])
    missing = [r for r in expect_roles if r not in roles]
    if missing:
        raise CheckFailed(f"SSO user {username} has roles {roles}, missing {missing}")
    ok(f"{username} signed in through Keycloak; roles {roles}")


def check_local_login(url: str, username: str, password: str) -> None:
    print("6. local password form (/local-login/)")
    browser = Client(url)
    status, page, page_url = browser.request("GET", "/local-login/", headers={"Accept": "text/html"})
    if status != 200 or "csrf_token" not in str(page):
        raise CheckFailed(f"/local-login/ -> HTTP {status}")
    follow_form(browser, str(page), page_url, {"username": username, "password": password})
    status, payload, _ = browser.request("GET", "/api/v1/me/")
    if status != 200 or payload["result"]["username"] != username:
        raise CheckFailed(f"local login for {username} failed (HTTP {status})")
    ok(f"{username} signed in with the password form")


def check_mailpit(mailpit: str, timeout_s: int) -> None:
    print("7. weekly capacity report e-mail")
    client = Client(mailpit)
    deadline = time.time() + timeout_s
    while True:
        status, payload, _ = client.request("GET", "/api/v1/search?query=" + urllib.parse.quote('subject:"capacity"'))
        messages = payload.get("messages", []) if status == 200 and isinstance(payload, dict) else []
        if messages:
            msg = messages[0]
            attachments = msg.get("Attachments", 0)
            ok(f"mailpit has {len(messages)} report e-mail(s): {msg.get('Subject')!r}, attachments={attachments}")
            return
        if time.time() > deadline:
            raise CheckFailed("no capacity report e-mail in mailpit")
        time.sleep(10)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.environ.get("SUPERSET_VERIFY_URL", "http://localhost:8090"))
    parser.add_argument("--admin", default=os.environ.get("SUPERSET_UI_ADMIN_USERNAME", "admin"))
    parser.add_argument("--admin-password", default=os.environ.get("SUPERSET_UI_ADMIN_PASSWORD", "dev-superset-admin"))
    # Embed service account: the backend's names (SUPERSET_ADMIN_*) or the Superset container's (SUPERSET_EMBED_*).
    parser.add_argument(
        "--embed",
        default=os.environ.get("SUPERSET_ADMIN_USERNAME") or os.environ.get("SUPERSET_EMBED_USERNAME") or "gcc_embed",
    )
    parser.add_argument(
        "--embed-password",
        default=os.environ.get("SUPERSET_ADMIN_PASSWORD")
        or os.environ.get("SUPERSET_EMBED_PASSWORD")
        or "dev-superset-embed-pw",
    )
    parser.add_argument("--site", default=None, help="site code for the RLS check (default: lowest site id)")
    parser.add_argument("--sso", default=None, help="USER:PASSWORD of a Keycloak user to sign in with")
    parser.add_argument("--expect-role", action="append", default=[], help="role the SSO user must get")
    parser.add_argument("--local-login", action="store_true", help="check the /local-login/ form (oauth mode)")
    parser.add_argument("--mailpit", default=None, help="mailpit base URL; wait for the report e-mail")
    parser.add_argument("--mail-timeout", type=int, default=150)
    args = parser.parse_args(argv)

    print(f"Verifying Superset at {args.url}")
    try:
        admin = Client(args.url)
        admin.login(args.admin, args.admin_password)
        boards = check_dashboards(admin)
        datasets = check_datasets(admin)
        check_chart_data(admin, boards)
        check_guest_rls(args.url, admin, args.embed, args.embed_password, boards, datasets, args.site)
        if args.sso:
            check_sso(args.url, args.sso, args.expect_role)
        if args.local_login:
            check_local_login(args.url, args.admin, args.admin_password)
        if args.mailpit:
            check_mailpit(args.mailpit, args.mail_timeout)
    except CheckFailed as exc:
        print(f"FAIL {exc}")
        return 1
    print("All Superset checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
