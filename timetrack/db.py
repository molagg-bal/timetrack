"""Datenbankzugriff. Produktiv MariaDB/MySQL, für Tests optional SQLite.

Schema:
  stamps    – ein Zeitstempel je Button-Klick (Zeitpunkt + 'work'|'pause'),
              Index auf ts für Tages-/Monatsabfragen
  day_marks – höchstens eine Tagesart je Tag (TU, AU, EGZ, NF); auto=1 bei
              automatisch eingetragenen Feiertagen
  years     – je Kalenderjahr Urlaubstage und Wochenarbeitszeit (Minuten)
  settings  – Schlüssel/Wert (Startdatum, Startsaldo, Schema-Version)
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from decimal import Decimal
import threading
import time
from datetime import date, datetime

SCHEMA_VERSION = 3  # v2: Urlaubstage/Wochenstunden als Dezimalzahlen, v3: Tageskommentare
BACKUP_FORMAT = "timetrack-backup"
BACKUP_FORMATS_ACCEPTED = (BACKUP_FORMAT, "timeapp-backup")  # auch Sicherungen der alten timeapp
OPTIONAL_BACKUP_TABLES = ("day_notes",)  # fehlen in Sicherungen vor v3

# Tabellen und Spalten der Datensicherung, mit Umwandlung aus JSON
BACKUP_TABLES = {
    "settings": {"name": str, "value": str},
    "years": {"year": int, "vacation_days": float, "weekly_minutes": float, "holidays_done": int},
    "day_marks": {"day": date.fromisoformat, "kind": str, "note": lambda v: None if v is None else str(v),
                  "auto": int},
    "stamps": {"id": int, "ts": datetime.fromisoformat, "kind": str},
    "day_notes": {"day": date.fromisoformat, "note": str},
}

MYSQL_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS settings (
        name VARCHAR(50) NOT NULL PRIMARY KEY,
        value VARCHAR(255) NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS stamps (
        id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
        ts DATETIME NOT NULL,
        kind ENUM('work','pause') NOT NULL,
        KEY idx_stamps_ts (ts)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS day_marks (
        day DATE NOT NULL PRIMARY KEY,
        kind ENUM('TU','AU','EGZ','NF') NOT NULL,
        note VARCHAR(100) NULL,
        auto TINYINT(1) NOT NULL DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS day_notes (
        day DATE NOT NULL PRIMARY KEY,
        note TEXT NOT NULL
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
    """CREATE TABLE IF NOT EXISTS years (
        year SMALLINT UNSIGNED NOT NULL PRIMARY KEY,
        vacation_days DECIMAL(5,2) NOT NULL,
        weekly_minutes DECIMAL(7,2) NOT NULL,
        holidays_done TINYINT(1) NOT NULL DEFAULT 0
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4""",
]

SQLITE_SCHEMA = [
    "CREATE TABLE IF NOT EXISTS settings (name TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS stamps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts DATETIME NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('work','pause')))""",
    "CREATE INDEX IF NOT EXISTS idx_stamps_ts ON stamps (ts)",
    """CREATE TABLE IF NOT EXISTS day_marks (
        day DATE PRIMARY KEY,
        kind TEXT NOT NULL CHECK (kind IN ('TU','AU','EGZ','NF')),
        note TEXT NULL,
        auto INTEGER NOT NULL DEFAULT 0)""",
    "CREATE TABLE IF NOT EXISTS day_notes (day DATE PRIMARY KEY, note TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS years (
        year INTEGER PRIMARY KEY,
        vacation_days REAL NOT NULL,
        weekly_minutes REAL NOT NULL,
        holidays_done INTEGER NOT NULL DEFAULT 0)""",
]

sqlite3.register_adapter(date, lambda d: d.isoformat())
sqlite3.register_adapter(datetime, lambda d: d.isoformat(sep=" "))
sqlite3.register_converter("DATE", lambda b: date.fromisoformat(b.decode()))
sqlite3.register_converter("DATETIME", lambda b: datetime.fromisoformat(b.decode()))


class Database:
    """Kapselt Verbindungsaufbau und SQL-Dialekt.

    Konfiguration über Umgebungsvariablen:
      TIMETRACK_DB_SQLITE   Pfad zu einer SQLite-Datei (nur Entwicklung/Test)
      TIMETRACK_DB_SOCKET   Unix-Socket von MariaDB (Standard: /run/mysqld/mysqld.sock)
      TIMETRACK_DB_HOST / TIMETRACK_DB_PORT  statt Socket per TCP verbinden
      TIMETRACK_DB_NAME     Datenbankname (Standard: timetrack)
      TIMETRACK_DB_USER     Benutzer (Standard: timetrack)
      TIMETRACK_DB_PASSWORD_FILE  Datei mit Passwort (optional; bei Socket-Auth leer)
    """

    def __init__(self, env=os.environ):
        self.sqlite_path = env.get("TIMETRACK_DB_SQLITE")
        self.dialect = "sqlite" if self.sqlite_path else "mysql"
        self.socket = env.get("TIMETRACK_DB_SOCKET", "/run/mysqld/mysqld.sock")
        self.host = env.get("TIMETRACK_DB_HOST")
        self.port = int(env.get("TIMETRACK_DB_PORT", "3306"))
        self.name = env.get("TIMETRACK_DB_NAME", "timetrack")
        self.user = env.get("TIMETRACK_DB_USER", "timetrack")
        self.password = ""
        pw_file = env.get("TIMETRACK_DB_PASSWORD_FILE")
        if pw_file:
            with open(pw_file) as f:
                self.password = f.read().strip()
        self._local = threading.local()

    # --- Verbindung -------------------------------------------------------
    def _connect(self):
        if self.dialect == "sqlite":
            conn = sqlite3.connect(self.sqlite_path, detect_types=sqlite3.PARSE_DECLTYPES,
                                   isolation_level=None, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            return conn
        kw = dict(user=self.user, charset="utf8mb4", autocommit=True)
        if self.password:
            kw["password" if _driver_name() == "pymysql" else "passwd"] = self.password
        if self.host:
            kw.update(host=self.host, port=self.port)
        else:
            kw["unix_socket"] = self.socket
        if _driver_name() == "pymysql":
            import pymysql
            return pymysql.connect(database=self.name, **kw)
        import MySQLdb
        return MySQLdb.connect(db=self.name, **kw)

    def conn(self):
        c = getattr(self._local, "conn", None)
        if c is not None and self.dialect == "mysql":
            try:
                c.ping()
            except Exception:
                c = None
        if c is None:
            c = self._connect()
            self._local.conn = c
        return c

    def wait_ready(self, timeout: float = 120.0):
        """Wartet, bis die Datenbank erreichbar ist (z. B. direkt nach dem Booten)."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.conn()
                return
            except Exception as e:  # noqa: BLE001
                if time.monotonic() > deadline:
                    raise
                print(f"Datenbank noch nicht erreichbar ({e}), neuer Versuch …", flush=True)
                time.sleep(2)

    # --- Abfragen ---------------------------------------------------------
    def _sql(self, sql: str) -> str:
        if self.dialect == "sqlite":
            sql = sql.replace("%s", "?").replace("INSERT IGNORE", "INSERT OR IGNORE")
        return sql

    def execute(self, sql: str, params=()) -> tuple[int, int | None]:
        cur = self.conn().cursor()
        try:
            cur.execute(self._sql(sql), params)
            return cur.rowcount, cur.lastrowid
        finally:
            cur.close()

    def query(self, sql: str, params=()) -> list[tuple]:
        cur = self.conn().cursor()
        try:
            cur.execute(self._sql(sql), params)
            return list(cur.fetchall())
        finally:
            cur.close()

    # --- Schema -----------------------------------------------------------
    def init_schema(self):
        for stmt in (SQLITE_SCHEMA if self.dialect == "sqlite" else MYSQL_SCHEMA):
            self.execute(stmt)
        version = self.get_setting("schema_version")
        if version is not None and int(version) < 2 and self.dialect == "mysql":
            # v1 -> v2: Dezimalstellen für Urlaubstage und Wochenstunden
            self.execute("ALTER TABLE years MODIFY vacation_days DECIMAL(5,2) NOT NULL, "
                         "MODIFY weekly_minutes DECIMAL(7,2) NOT NULL")
        if version is None or int(version) < SCHEMA_VERSION:
            self.set_setting("schema_version", str(SCHEMA_VERSION))
        if self.get_setting("start_date") is None:
            self.set_setting("start_date", date.today().isoformat())
        if self.get_setting("start_balance") is None:
            self.set_setting("start_balance", "0")

    @contextmanager
    def transaction(self):
        self.execute("BEGIN" if self.dialect == "sqlite" else "START TRANSACTION")
        try:
            yield
        except BaseException:
            self.execute("ROLLBACK")
            raise
        self.execute("COMMIT")

    # --- Datensicherung -----------------------------------------------------
    def export_data(self) -> dict:
        def conv(v):
            if isinstance(v, (date, datetime)):
                return v.isoformat()
            if isinstance(v, Decimal):
                return float(v)
            return v

        out = {"format": BACKUP_FORMAT, "schema_version": SCHEMA_VERSION,
               "exported_at": datetime.now().replace(microsecond=0).isoformat()}
        for table, cols in BACKUP_TABLES.items():
            names = list(cols)
            rows = self.query(f"SELECT {', '.join(names)} FROM {table} ORDER BY {names[0]}")
            out[table] = [{n: conv(v) for n, v in zip(names, row)} for row in rows]
        return out

    def import_data(self, data: dict) -> dict:
        """Ersetzt alle Daten durch den Inhalt einer Datensicherung."""
        if not isinstance(data, dict) or data.get("format") not in BACKUP_FORMATS_ACCEPTED:
            raise ValueError("Keine timetrack-Datensicherung")
        if int(data.get("schema_version", 0)) > SCHEMA_VERSION:
            raise ValueError("Datensicherung stammt von einer neueren Version")
        parsed = {}
        for table, cols in BACKUP_TABLES.items():
            rows = data.get(table, [] if table in OPTIONAL_BACKUP_TABLES else None)
            if not isinstance(rows, list):
                raise ValueError(f"Tabelle {table} fehlt")
            try:
                parsed[table] = [tuple(conv(row[c]) for c, conv in cols.items()) for row in rows]
            except (KeyError, TypeError, ValueError) as e:
                raise ValueError(f"Ungültige Daten in Tabelle {table}: {e}")
        for r in parsed["stamps"]:
            if r[2] not in ("work", "pause"):
                raise ValueError(f"Ungültiger Stempeltyp {r[2]!r}")
        for r in parsed["day_marks"]:
            if r[1] not in ("TU", "AU", "EGZ", "NF"):
                raise ValueError(f"Ungültige Tagesart {r[1]!r}")
        try:
            with self.transaction():
                for table in BACKUP_TABLES:
                    self.execute(f"DELETE FROM {table}")
                for table, cols in BACKUP_TABLES.items():
                    sql = (f"INSERT INTO {table} ({', '.join(cols)}) "
                           f"VALUES ({', '.join(['%s'] * len(cols))})")
                    for row in parsed[table]:
                        self.execute(sql, row)
        except Exception as e:  # noqa: BLE001 – Datenbankfehler, alles zurückgerollt
            raise ValueError(f"Einspielen fehlgeschlagen, vorhandene Daten unverändert: {e}")
        self.init_schema()  # fehlende Pflicht-Einstellungen ergänzen
        return {t: len(rows) for t, rows in parsed.items()}

    def get_setting(self, name: str) -> str | None:
        rows = self.query("SELECT value FROM settings WHERE name=%s", (name,))
        return rows[0][0] if rows else None

    def set_setting(self, name: str, value: str):
        if self.execute("UPDATE settings SET value=%s WHERE name=%s", (value, name))[0] == 0:
            self.execute("INSERT IGNORE INTO settings (name, value) VALUES (%s, %s)", (name, value))
            self.execute("UPDATE settings SET value=%s WHERE name=%s", (value, name))


def _driver_name() -> str:
    try:
        import MySQLdb  # noqa: F401
        return "mysqlclient"
    except ImportError:
        return "pymysql"
