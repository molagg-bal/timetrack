"""End-to-End-Test der API gegen eine SQLite-Testdatenbank mit fester Uhr."""
from datetime import datetime

import pytest

from timetrack.app import create_app
from timetrack.db import Database


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def env(tmp_path):
    e = {"TIMETRACK_DB_SQLITE": str(tmp_path / "t.db"), "TIMETRACK_HOLIDAY_STATE": "NI"}
    db = Database(e)
    db.init_schema()
    db.set_setting("start_date", "2026-11-02")
    clock = Clock(datetime(2026, 11, 2, 8, 0))
    app = create_app(db, env=e, clock=clock)
    return app.test_client(), clock


def test_toggle_flow(env):
    c, clock = env
    s = c.get("/api/status").get_json()
    assert s["state"] == "pause" and s["today"]["net"] == 0
    s = c.post("/api/toggle", json={"from": "pause"}).get_json()
    assert s["state"] == "work"
    # doppelter Klick aus veraltetem Tab ändert nichts
    s = c.post("/api/toggle", json={"from": "pause"}).get_json()
    assert s["state"] == "work"
    clock.t = datetime(2026, 11, 2, 12, 0)
    assert c.get("/api/status").get_json()["today"]["net"] == 4 * 3600
    s = c.post("/api/toggle", json={"from": "work"}).get_json()
    assert s["state"] == "pause" and s["since"].endswith("12:00:00")
    clock.t = datetime(2026, 11, 2, 12, 30)
    c.post("/api/toggle", json={"from": "pause"})
    clock.t = datetime(2026, 11, 2, 17, 0)
    s = c.post("/api/toggle", json={"from": "work"}).get_json()
    assert s["today"]["net"] == int(8.5 * 3600) and s["today"]["pause"] == 1800
    assert s["balance"] == 0  # heute zählt noch nicht
    clock.t = datetime(2026, 11, 3, 7, 0)
    s = c.get("/api/status").get_json()
    assert s["state"] == "pause" and s["balance"] == 1800


def test_calendar_edit(env):
    c, clock = env
    clock.t = datetime(2026, 11, 6, 9, 0)
    d = c.post("/api/day/2026-11-03/stamps", json={"time": "08:00", "kind": "work"}).get_json()
    assert "open" in d["flags"]
    sid = d["entries"][0]["id"]
    d = c.post("/api/day/2026-11-03/stamps", json={"time": "16:30", "kind": "pause"}).get_json()
    assert d["net"] == 8 * 3600 and "pause_short" in d["flags"]
    d = c.put(f"/api/stamps/{sid}", json={"time": "08:30:00", "kind": "work"}).get_json()
    assert d["gross"] == 8 * 3600
    m = c.get("/api/month/2026/11").get_json()
    days = {x["date"]: x for x in m["days"]}
    assert "missing" in days["2026-11-02"]["flags"]
    assert "missing" in days["2026-11-04"]["flags"]
    assert days["2026-11-01"]["flags"] == []  # vor Startdatum
    assert m["balance"] == -24 * 3600 - 1800  # Mo, Mi, Do fehlen; Di 8h ohne Pause -> -30m
    d = c.put("/api/day/2026-11-02/mark", json={"mark": "TU"}).get_json()
    assert d["mark"] == "TU" and d["flags"] == []
    d = c.put("/api/day/2026-11-02/mark", json={"mark": None}).get_json()
    assert d["mark"] is None
    assert c.put("/api/day/2026-11-02/mark", json={"mark": "XY"}).status_code == 400
    assert c.post("/api/day/2026-11-02/stamps", json={"time": "25:00", "kind": "work"}).status_code == 400
    assert c.delete(f"/api/stamps/{sid}").status_code == 200
    assert c.delete(f"/api/stamps/{sid}").status_code == 404


def test_holidays_auto_and_years(env):
    c, clock = env
    m = c.get("/api/month/2026/12").get_json()
    days = {x["date"]: x for x in m["days"]}
    assert days["2026-12-25"]["mark"] == "NF"
    # gelöschter Feiertag kommt nicht von selbst zurück
    c.put("/api/day/2026-12-25/mark", json={"mark": None})
    m = c.get("/api/month/2026/12").get_json()
    assert {x["date"]: x for x in m["days"]}["2026-12-25"]["mark"] is None
    y = c.get("/api/years").get_json()
    assert [r["year"] for r in y["years"]] == [2026]
    y = c.put("/api/years/2026", json={"vacation_days": "28", "weekly_hours": "38.5"}).get_json()
    assert y["years"][0]["vacation_days"] == 28 and y["years"][0]["weekly_minutes"] == 2310
    y = c.post("/api/years", json={"year": 2027}).get_json()
    assert y["years"][0]["year"] == 2027 and y["years"][0]["carry_in"] == 28
    assert y["years"][0]["weekly_minutes"] == 2310  # vom Vorjahr übernommen
    assert c.post("/api/years", json={"year": 2027}).status_code == 409
    m = c.get("/api/month/2027/1").get_json()
    assert m["days"][0]["mark"] == "NF"
    y = c.put("/api/settings", json={"start_date": "2026-11-01", "start_balance": 3600}).get_json()
    assert y["start_balance"] == 3600


def test_static(env):
    c, _ = env
    assert b"timetrack" in c.get("/").data
    assert c.get("/static/app.js").status_code == 200


def test_excel_export(env):
    openpyxl = pytest.importorskip("openpyxl")
    import io
    c, clock = env
    clock.t = datetime(2026, 11, 6, 10, 0)
    for t, k in (("08:00", "work"), ("12:00", "pause"), ("12:30", "work"), ("17:00", "pause")):
        c.post("/api/day/2026-11-03/stamps", json={"time": t, "kind": k})
    c.post("/api/day/2026-11-06/stamps", json={"time": "08:00", "kind": "work"})
    c.put("/api/day/2026-11-04/mark", json={"mark": "TU"})
    c.put("/api/day/2026-11-05/mark", json={"mark": "AU"})
    c.put("/api/day/2025-03-10/mark", json={"mark": "EGZ"})
    c.put("/api/day/2024-11-05/mark", json={"mark": "TU"})  # vor dem Zeitraum
    r = c.get("/api/export/excel")
    assert r.status_code == 200
    assert "2024-11-06_bis_2026-11-06" in r.headers["Content-Disposition"]
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    assert wb.sheetnames == ["März 2025", "November 2026"]
    ws = wb["November 2026"]
    stats = {ws.cell(row, 1).value: ws.cell(row, 3).value for row in range(3, 7)}
    # Mo 2.11. fehlt (-8h), Di +0:30, Mi TU, Do AU; heute nicht gezählt
    assert stats["Überstunden im Monat"] == "-7:30 h"
    assert stats["Genutzte Urlaubstage"] == 1 and stats["Krankheitstage"] == 1
    rows = {ws.cell(row, 1).value.date().day: [ws.cell(row, col).value for col in range(1, 11)]
            for row in range(10, 16)}
    assert len([r for r in ws.iter_rows(min_row=10) if r[0].value]) == 6  # 1.–6.11.
    assert rows[3][3:6] == ["08:00", "17:00", "08:00–12:00, 12:30–17:00"]
    assert round(rows[3][6].total_seconds() if hasattr(rows[3][6], "total_seconds") else rows[3][6] * 86400) == 8.5 * 3600
    assert rows[4][2] == "Urlaub" and rows[5][2] == "Krankschreibung"
    assert rows[6][5] == "08:00–(läuft)"
    m = wb["März 2025"]
    assert m.cell(10, 1).value.date().day == 1  # alle Tage des Monats
    assert any(row[2].value == "Gleitzeittag" for row in m.iter_rows(min_row=10))
    assert any(row[2].value == "Feiertag" for row in m.iter_rows(min_row=10)) is False  # März ohne NF in NI


def test_backup_roundtrip(env):
    c, clock = env
    clock.t = datetime(2026, 11, 6, 10, 0)
    c.post("/api/day/2026-11-03/stamps", json={"time": "08:00", "kind": "work"})
    c.put("/api/day/2026-11-04/mark", json={"mark": "TU"})
    c.put("/api/years/2026", json={"vacation_days": "27.5", "weekly_hours": "39"})
    r = c.get("/api/backup")
    assert "attachment" in r.headers["Content-Disposition"]
    backup = r.get_json()
    assert backup["format"] == "timetrack-backup"
    # Daten ändern, dann Sicherung einspielen -> alter Stand
    c.post("/api/day/2026-11-05/stamps", json={"time": "09:00", "kind": "work"})
    c.put("/api/day/2026-11-04/mark", json={"mark": None})
    res = c.post("/api/backup", json=backup).get_json()
    assert res["imported"]["stamps"] == 1
    assert c.get("/api/backup").get_json()["stamps"] == backup["stamps"]
    assert c.get("/api/day/2026-11-04").get_json()["mark"] == "TU"
    assert c.get("/api/years").get_json()["years"][0]["vacation_days"] == 27.5
    # ungültige Datei ändert nichts
    bad = dict(backup, stamps=[{"id": 1, "ts": "kaputt", "kind": "work"}])
    assert c.post("/api/backup", json=bad).status_code == 400
    assert c.post("/api/backup", json={"foo": 1}).status_code == 400
    assert c.get("/api/backup").get_json()["stamps"] == backup["stamps"]


def test_backup_rollback(env):
    c, clock = env
    c.post("/api/day/2026-11-02/stamps", json={"time": "08:00", "kind": "work"})
    backup = c.get("/api/backup").get_json()
    dup = dict(backup, stamps=[{"id": 5, "ts": "2026-01-01T08:00:00", "kind": "work"}] * 2)
    r = c.post("/api/backup", json=dup)
    assert r.status_code == 400 and "unverändert" in r.get_json()["error"]
    assert c.get("/api/backup").get_json()["stamps"] == backup["stamps"]
