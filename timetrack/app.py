"""Flask-Anwendung: JSON-API und Auslieferung der Weboberfläche."""
from __future__ import annotations

import json
import os
import re
from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import Flask, Response, jsonify, request, send_from_directory

from . import calc, export, holidays
from .db import Database

TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$")


class ApiError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def create_app(db: Database | None = None, env=os.environ, clock=datetime.now) -> Flask:
    db = db or Database(env)
    state = env.get("TIMETRACK_HOLIDAY_STATE", "NI").upper()
    if state not in holidays.STATES:
        raise SystemExit(f"Unbekanntes Bundesland {state!r}, erlaubt: {', '.join(holidays.STATES)}")

    static_dir = os.path.join(os.path.dirname(__file__), "static")
    app = Flask(__name__, static_folder=None)
    app.json.ensure_ascii = False

    def now() -> datetime:
        return clock().replace(microsecond=0)

    # --- Hilfsfunktionen ----------------------------------------------------
    def ensure_year(y: int) -> bool:
        """Legt ein Jahr mit Standardwerten an (aus dem Vorjahr übernommen) und
        trägt einmalig die Feiertage als NF ein."""
        rows = db.query("SELECT vacation_days, weekly_minutes FROM years WHERE year<%s "
                        "ORDER BY year DESC LIMIT 1", (y,))
        if not rows:
            rows = db.query("SELECT vacation_days, weekly_minutes FROM years WHERE year>%s "
                            "ORDER BY year LIMIT 1", (y,))
        vac, weekly = rows[0] if rows else (calc.DEFAULT_VACATION_DAYS, calc.DEFAULT_WEEKLY_MINUTES)
        created = db.execute("INSERT IGNORE INTO years (year, vacation_days, weekly_minutes, "
                             "holidays_done) VALUES (%s, %s, %s, 0)", (y, vac, weekly))[0] > 0
        insert_holidays(y)
        return created

    def insert_holidays(y: int, force: bool = False):
        if not force:
            done = db.query("SELECT holidays_done FROM years WHERE year=%s", (y,))
            if not done or done[0][0]:
                return
        for d, name in holidays.holidays(y, state).items():
            db.execute("INSERT IGNORE INTO day_marks (day, kind, note, auto) "
                       "VALUES (%s, 'NF', %s, 1)", (d, name))
        db.execute("UPDATE years SET holidays_done=1 WHERE year=%s", (y,))

    def ensure_years(*extra: int):
        start = start_date()
        today = now().date()
        existing = {r[0] for r in db.query("SELECT year FROM years")}
        wanted = set(range(start.year, today.year + 1))
        wanted.update(y for y in extra if start.year <= y <= today.year + 5)
        for y in sorted(wanted - existing):
            ensure_year(y)

    def start_date() -> date:
        return date.fromisoformat(db.get_setting("start_date") or now().date().isoformat())

    def load_ledger() -> calc.Ledger:
        years = {int(y): calc.YearCfg(float(v), int(w))
                 for y, v, w in db.query("SELECT year, vacation_days, weekly_minutes FROM years")}
        stamps: dict[date, list] = {}
        for ts, kind in db.query("SELECT ts, kind FROM stamps ORDER BY ts, id"):
            stamps.setdefault(ts.date(), []).append((ts, kind))
        marks = {d: (k, n) for d, k, n in db.query("SELECT day, kind, note FROM day_marks")}
        return calc.Ledger(start_date=start_date(),
                           start_balance=int(db.get_setting("start_balance") or 0),
                           years=years, stamps=stamps, marks=marks, now=now())

    def day_stamps(d: date):
        nxt = d + timedelta(days=1)
        return db.query("SELECT id, ts, kind FROM stamps WHERE ts >= %s AND ts < %s "
                        "ORDER BY ts, id", (datetime.combine(d, datetime.min.time()),
                                            datetime.combine(nxt, datetime.min.time())))

    def current_state(d: date) -> tuple[str, datetime | None]:
        rows = day_stamps(d)
        if not rows:
            return "pause", None
        _, ts, kind = rows[-1]
        return kind, ts

    def parse_date(s: str) -> date:
        try:
            return date.fromisoformat(s)
        except ValueError:
            raise ApiError("Ungültiges Datum")

    def parse_time(d: date, s: str) -> datetime:
        m = TIME_RE.match((s or "").strip())
        if not m:
            raise ApiError("Ungültige Uhrzeit (erwartet HH:MM)")
        h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        if h > 23 or mi > 59 or se > 59:
            raise ApiError("Ungültige Uhrzeit")
        return datetime(d.year, d.month, d.day, h, mi, se)

    def parse_kind(s) -> str:
        if s not in ("work", "pause"):
            raise ApiError("Typ muss 'work' oder 'pause' sein")
        return s

    def body() -> dict:
        return request.get_json(silent=True) or {}

    def num(v):
        return float(v) if isinstance(v, Decimal) else v

    def day_payload(ledger: calc.Ledger, d: date) -> dict:
        res = ledger.day(d).to_dict()
        res["entries"] = [{"id": i, "time": ts.strftime("%H:%M:%S"), "kind": k}
                          for i, ts, k in day_stamps(d)]
        mark = db.query("SELECT auto FROM day_marks WHERE day=%s", (d,))
        res["mark_auto"] = bool(mark[0][0]) if mark else False
        return res

    def status_payload() -> dict:
        n = now()
        ensure_years()
        ledger = load_ledger()
        st, since = current_state(n.date())
        today = ledger.day(n.date()).to_dict()
        open_days = sorted(d.isoformat() for d, r in ledger.days.items()
                           if calc.F_OPEN in r.flags)
        return {"state": st, "since": since.isoformat() if since else None,
                "server_time": n.isoformat(), "today": today,
                "balance": ledger.balance, "open_days": open_days}

    # --- Fehlerbehandlung ---------------------------------------------------
    @app.errorhandler(ApiError)
    def _api_error(e: ApiError):
        return jsonify(error=str(e)), e.status

    @app.after_request
    def _no_cache(resp):
        if request.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    # --- Statische Seiten ---------------------------------------------------
    @app.get("/")
    def index():
        return send_from_directory(static_dir, "index.html")

    @app.get("/static/<path:name>")
    def static_file(name):
        return send_from_directory(static_dir, name)

    # --- Hauptseite ---------------------------------------------------------
    @app.get("/api/status")
    def api_status():
        return jsonify(status_payload())

    @app.post("/api/toggle")
    def api_toggle():
        n = now()
        st, _ = current_state(n.date())
        expected = body().get("from")
        if expected in (None, st):
            db.execute("INSERT INTO stamps (ts, kind) VALUES (%s, %s)",
                       (n, "work" if st == "pause" else "pause"))
        # Bei abweichendem Zustand (z. B. zweiter Browser-Tab) nichts eintragen,
        # nur den aktuellen Stand zurückgeben.
        return jsonify(status_payload())

    # --- Kalender -------------------------------------------------------------
    @app.get("/api/month/<int:year>/<int:month>")
    def api_month(year, month):
        if not (1 <= month <= 12 and 1900 < year < 3000):
            raise ApiError("Ungültiger Monat")
        ensure_years(year)
        ledger = load_ledger()
        days = [ledger.day(date(year, month, i)).to_dict()
                for i in range(1, monthrange(year, month)[1] + 1)]
        vac = ledger.vacation_for(year)
        return jsonify(year=year, month=month, days=days, balance=ledger.balance,
                       vacation={k: num(v) for k, v in vac.items()},
                       start_date=ledger.start_date.isoformat(), today=ledger.today.isoformat())

    @app.get("/api/day/<d>")
    def api_day(d):
        d = parse_date(d)
        ensure_years(d.year)
        return jsonify(day_payload(load_ledger(), d))

    @app.post("/api/day/<d>/stamps")
    def api_add_stamp(d):
        d = parse_date(d)
        b = body()
        db.execute("INSERT INTO stamps (ts, kind) VALUES (%s, %s)",
                   (parse_time(d, b.get("time")), parse_kind(b.get("kind"))))
        return jsonify(day_payload(load_ledger(), d))

    @app.put("/api/stamps/<int:sid>")
    def api_update_stamp(sid):
        rows = db.query("SELECT ts FROM stamps WHERE id=%s", (sid,))
        if not rows:
            raise ApiError("Eintrag nicht gefunden", 404)
        d = rows[0][0].date()
        b = body()
        db.execute("UPDATE stamps SET ts=%s, kind=%s WHERE id=%s",
                   (parse_time(d, b.get("time")), parse_kind(b.get("kind")), sid))
        return jsonify(day_payload(load_ledger(), d))

    @app.delete("/api/stamps/<int:sid>")
    def api_delete_stamp(sid):
        rows = db.query("SELECT ts FROM stamps WHERE id=%s", (sid,))
        if not rows:
            raise ApiError("Eintrag nicht gefunden", 404)
        db.execute("DELETE FROM stamps WHERE id=%s", (sid,))
        return jsonify(day_payload(load_ledger(), rows[0][0].date()))

    @app.put("/api/day/<d>/mark")
    def api_set_mark(d):
        d = parse_date(d)
        kind = body().get("mark") or None
        if kind is not None and kind not in calc.MARKS:
            raise ApiError("Tagesart muss TU, AU, EGZ oder NF sein")
        db.execute("DELETE FROM day_marks WHERE day=%s", (d,))
        if kind:
            note = holidays.holidays(d.year, state).get(d) if kind == "NF" else None
            db.execute("INSERT INTO day_marks (day, kind, note, auto) VALUES (%s, %s, %s, 0)",
                       (d, kind, note))
        return jsonify(day_payload(load_ledger(), d))

    # --- Jahre & Einstellungen ------------------------------------------------
    def years_payload() -> dict:
        ensure_years()
        ledger = load_ledger()
        rows = db.query("SELECT year, vacation_days, weekly_minutes FROM years ORDER BY year DESC")
        years = []
        for y, v, w in rows:
            vac = ledger.vacation_for(int(y))
            years.append({"year": int(y), "vacation_days": num(v), "weekly_minutes": int(w),
                          "carry_in": vac["carry_in"], "available": vac["available"],
                          "taken": vac["taken"], "planned": vac["planned"],
                          "remaining": vac["remaining"],
                          "overtime": ledger.year_overtime(int(y)),
                          "before_start": int(y) < ledger.start_date.year})
        return {"years": years, "balance": ledger.balance,
                "start_date": ledger.start_date.isoformat(),
                "start_balance": int(db.get_setting("start_balance") or 0),
                "holiday_state": state, "holiday_state_name": holidays.STATES[state]}

    @app.get("/api/years")
    def api_years():
        return jsonify(years_payload())

    @app.post("/api/years")
    def api_add_year():
        try:
            y = int(body().get("year"))
        except (TypeError, ValueError):
            raise ApiError("Ungültiges Jahr")
        if not 1900 < y < 3000:
            raise ApiError("Ungültiges Jahr")
        if not ensure_year(y):
            raise ApiError(f"Jahr {y} existiert bereits", 409)
        return jsonify(years_payload())

    @app.put("/api/years/<int:y>")
    def api_update_year(y):
        b = body()
        try:
            vac = float(b.get("vacation_days"))
            weekly = round(float(b.get("weekly_hours")) * 60)
        except (TypeError, ValueError):
            raise ApiError("Ungültige Werte")
        if not (0 <= vac <= 365 and 0 <= weekly <= 7 * 24 * 60):
            raise ApiError("Werte außerhalb des gültigen Bereichs")
        ensure_year(y)
        db.execute("UPDATE years SET vacation_days=%s, weekly_minutes=%s WHERE year=%s",
                   (vac, weekly, y))
        return jsonify(years_payload())

    @app.delete("/api/years/<int:y>")
    def api_delete_year(y):
        db.execute("DELETE FROM years WHERE year=%s", (y,))
        return jsonify(years_payload())

    @app.post("/api/years/<int:y>/holidays")
    def api_year_holidays(y):
        ensure_year(y)
        insert_holidays(y, force=True)
        return jsonify(years_payload())

    @app.put("/api/settings")
    def api_settings():
        b = body()
        if "start_date" in b:
            db.set_setting("start_date", parse_date(b["start_date"]).isoformat())
        if "start_balance" in b:
            try:
                db.set_setting("start_balance", str(int(b["start_balance"])))
            except (TypeError, ValueError):
                raise ApiError("Ungültiger Startsaldo")
        return jsonify(years_payload())

    # --- Export & Datensicherung --------------------------------------------
    def download(data: bytes, mimetype: str, filename: str) -> Response:
        return Response(data, mimetype=mimetype, headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store"})

    @app.get("/api/export/excel")
    def api_export_excel():
        ensure_years()
        ledger = load_ledger()
        end = ledger.today
        start = export.years_back(end, 2)
        return download(export.build_xlsx(ledger, start, end),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        f"arbeitszeiten_{start.isoformat()}_bis_{end.isoformat()}.xlsx")

    @app.get("/api/backup")
    def api_backup_export():
        data = json.dumps(db.export_data(), ensure_ascii=False, indent=1).encode()
        return download(data, "application/json",
                        f"timetrack-datensicherung_{now():%Y-%m-%d_%H%M}.json")

    @app.post("/api/backup")
    def api_backup_import():
        data = request.get_json(silent=True)
        if data is None:
            raise ApiError("Die Datei ist kein gültiges JSON")
        try:
            counts = db.import_data(data)
        except ValueError as e:
            raise ApiError(str(e))
        return jsonify(imported=counts)

    app.config["DB"] = db
    return app
